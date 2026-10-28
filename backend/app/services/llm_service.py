"""
LLM Service — abstraction over Groq LLM interactions.

Validates that GROQ_API_KEY is configured before use.
Does not crash at import time if the key is missing.
"""

from typing import Optional

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ConfigurationError, ExternalServiceError
from app.models.profile import FarmerProfile

logger = get_logger(__name__)

# LLM instances are lazily created to avoid import-time failures
_llm: Optional[ChatGroq] = None
_structured_llm = None


def _get_llm() -> ChatGroq:
    """Get or create the Groq LLM instance."""
    global _llm
    if _llm is None:
        if not settings.GROQ_API_KEY:
            raise ConfigurationError(
                "GROQ_API_KEY is not configured. Set it in your .env file."
            )
        model_kwargs = {}
        if settings.GROQ_MODEL.startswith("openai/gpt-oss"):
            # Reasoning models: low effort is enough for extraction / wording and saves
            # tokens against the free-tier tokens-per-minute limit.
            model_kwargs["reasoning_effort"] = "low"
        _llm = ChatGroq(
            temperature=0,
            model_name=settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            request_timeout=settings.GROQ_TIMEOUT,
            max_retries=2,
            model_kwargs=model_kwargs,
        )
    return _llm


# Earlier assistant replies (long scheme lists) are shortened in LLM prompts; the user's own
# words are kept in full. The latest question the assistant asked stays readable.
MAX_ASSISTANT_CHARS_IN_HISTORY = 300


def recent_history(messages: list, window: int) -> list:
    """Last `window` messages, with long assistant messages truncated."""
    from langchain_core.messages import AIMessage, BaseMessage

    recent = messages[-window:] if len(messages) > window else list(messages)
    out = []
    for m in recent:
        if isinstance(m, BaseMessage):
            role, content = m.type, m.content
        elif isinstance(m, (tuple, list)) and len(m) == 2:
            role, content = m
        else:
            out.append(m)
            continue
        if role in ("ai", "assistant") and isinstance(content, str) \
                and len(content) > MAX_ASSISTANT_CHARS_IN_HISTORY:
            out.append(AIMessage(content=content[:MAX_ASSISTANT_CHARS_IN_HISTORY] + " …"))
        else:
            out.append(m)
    return out


def _get_structured_llm():
    """Get or create the structured output LLM bound to FarmerProfile."""
    global _structured_llm
    if _structured_llm is None:
        _structured_llm = _get_llm().with_structured_output(FarmerProfile)
    return _structured_llm


# --- Question generation chain ---
QUESTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful and polite agricultural assistant in India. 
    The user is applying for government schemes, but their profile is missing the following information: {missing_fields}.
    Ask a very brief, simple, and friendly question to get ONE of these missing pieces of information. 
    Ask in English, but keep the vocabulary extremely simple. Do not ask for everything at once. 
    Focus only on the first missing field in the list."""),
    ("placeholder", "{messages}")
])


async def generate_follow_up_question(missing_fields: list[str], messages: list) -> Optional[str]:
    """
    Generate a follow-up question for the first missing critical field.

    Returns None if generation fails, so callers keep their deterministic,
    field-specific template question (a generic fallback here used to
    override it — Phase 7 BUG-016).
    """
    try:
        llm = _get_llm()
        chain = QUESTION_PROMPT | llm | StrOutputParser()
        question = await chain.ainvoke({
            "missing_fields": ", ".join(missing_fields),
            "messages": recent_history(messages, settings.RECENT_MESSAGES_WINDOW),
        })
        return question.strip() if question and question.strip() else None
    except ConfigurationError:
        raise
    except Exception as e:
        logger.warning(f"Question generation failed, caller uses template: {e}")
        return None
