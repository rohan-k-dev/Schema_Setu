"""
Question Agent — generates follow-up questions for missing profile fields.

Responsibilities (§19–20):
- Ask for ONE missing field at a time
- Follow deterministic priority order
- Never ask duplicate questions
- Handle profile conflict confirmations
- Use simple farmer-friendly language
"""

from app.graph.state import SchemeSetuState
from app.core.logging import get_logger
from app.core.config import settings
from app.retrieval.models import ResponseStatus
from app.core.exceptions import LANGUAGE_SERVICE_UNAVAILABLE

logger = get_logger(__name__)

# Deterministic question templates for each field (§19)
FIELD_QUESTIONS = {
    "state": "Which state in India are you from?",
    "land_size_acres": "How many acres of land do you have?",
    "primary_crop": "What is the main crop you grow?",
    "district": "Which district are you from?",
    "annual_income": "What is your approximate annual income?",
    "category": "What is your social category? (General, OBC, SC, ST, or EWS)",
    "gender": "Could you share your gender?",
    "has_aadhaar": "Do you have an Aadhaar card?",
}


def _build_conflict_question(conflict: dict) -> str:
    """Build a confirmation question for a profile conflict (§15)."""
    field = conflict.get("field", "")
    old_val = conflict.get("old_value", "")
    new_val = conflict.get("new_value", "")

    field_labels = {
        "state": "state",
        "land_size_acres": "land size",
        "primary_crop": "main crop",
        "annual_income": "annual income",
        "district": "district",
        "category": "category",
        "gender": "gender",
    }
    label = field_labels.get(field, field)
    return (
        f"You previously mentioned your {label} as {old_val}. "
        f"Could you confirm whether it is {old_val} or {new_val}?"
    )


async def question_agent_node(state: SchemeSetuState) -> dict:
    """
    LangGraph node: Generate a follow-up question.

    Priority:
    1. If profile conflicts exist → ask conflict confirmation
    2. If needs_clarification → ask clarification question
    3. Else → ask for first missing field in priority order
    """
    logger.info("Executing Question Agent...")

    # 0. Language service unavailable: say so instead of repeating the question
    if state.get("error") == LANGUAGE_SERVICE_UNAVAILABLE:
        message = ("I can't understand free-text answers right now because the language "
                   "service is unavailable. Please try again in a little while.")
        return {
            "messages": [("assistant", message)],
            "response_text": message,
            "response_status": ResponseStatus.ERROR.value,
        }

    # 1. Handle profile conflicts first (§15)
    conflicts = state.get("profile_conflicts", [])
    if conflicts:
        conflict = conflicts[0]
        question = _build_conflict_question(conflict)
        logger.info(f"Asking conflict resolution: {question}")
        return {
            "messages": [("assistant", question)],
            "response_text": question,
            "response_status": ResponseStatus.ASKING_QUESTION.value,
        }

    # 2. Handle query clarification (§52)
    needs_clarification = state.get("needs_clarification", False)
    if needs_clarification:
        reason = state.get("contextual_query") or "Which scheme would you like to know about?"
        question = reason if isinstance(reason, str) else "Could you please clarify which scheme you're referring to?"
        logger.info(f"Asking clarification: {question}")
        return {
            "messages": [("assistant", question)],
            "response_text": question,
            "response_status": ResponseStatus.CLARIFICATION_REQUIRED.value,
        }

    # 3. Ask for missing field (§19)
    missing = state.get("missing_fields", [])
    if not missing:
        return {"messages": []}

    # Use deterministic priority — first missing field
    field = missing[0]
    question = FIELD_QUESTIONS.get(field, f"Could you tell me about your {field}?")

    # Try LLM-enhanced question generation for more natural phrasing
    try:
        from app.services.llm_service import generate_follow_up_question
        llm_question = await generate_follow_up_question(
            missing_fields=missing,
            messages=state.get("messages", []),
        )
        if llm_question:
            question = llm_question
    except Exception as e:
        logger.warning(f"LLM question generation failed, using template: {e}")
        # Keep the deterministic template question as fallback

    logger.info(f"Asking for missing field '{field}': {question[:100]}...")
    return {
        "messages": [("assistant", question)],
        "response_text": question,
        "response_status": ResponseStatus.ASKING_QUESTION.value,
    }
