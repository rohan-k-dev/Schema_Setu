"""
Chat API route — Phase 6.

Thin route: validate → translate → invoke graph → translate → serialize.
No business logic, LLM calls, or SQL queries live here (§155).
Multilingual support: translate_to_internal before agent, translate_from_internal after (§15, §31).
Text and voice use the SAME LangGraph pipeline (§5).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from langchain_core.messages import HumanMessage

from app.graph.workflow import kisan_agent
from app.api.deps import get_optional_farmer_id
from app.models.requests import ChatRequest
from app.models.responses import ChatResponse, ErrorDetail
from app.services.chat_profile_service import (
    load_saved_chat_profile,
    merge_chat_profiles,
    save_chat_profile,
)
from app.services.language_service import translate_to_internal, translate_from_internal
from app.localization.languages import resolve_language_code, INTERNAL_LANGUAGE
from app.utils.serialization import build_chat_response
from app.core.logging import get_logger
from app.core.exceptions import SchemSetuError, public_message

logger = get_logger(__name__)

router = APIRouter(tags=["Chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Text-based conversation with the SchemeSetu Agent",
    description="Send a text message and receive scheme recommendations or follow-up questions.",
)
async def chat_with_agent(
    request: ChatRequest,
    farmer_id: str | None = Depends(get_optional_farmer_id),
):
    """Process a text chat message through the LangGraph multi-agent pipeline."""
    request_id = str(uuid.uuid4())[:8]

    # Generate unique thread_id if default/empty (§57)
    thread_id = request.thread_id
    if not thread_id or thread_id == "default_session":
        thread_id = str(uuid.uuid4())

    lang_code = resolve_language_code(request.language)

    logger.info(
        f"[{request_id}] Chat request: thread={thread_id}, "
        f"lang={lang_code}, message_len={len(request.message)}"
    )

    try:
        # 1. Translate to internal language if needed (§15)
        internal_text = await translate_to_internal(request.message, lang_code)

        # 2. Same LangGraph pipeline (§5)
        inputs = {
            "messages": [HumanMessage(content=internal_text)],
            "session_id": thread_id,
            # per-turn flags: a previous turn's review notice must not carry over
            "needs_review": False, "review_reason": None, "review_case_id": None,
        }
        config = {"configurable": {"thread_id": thread_id}}

        saved_profile, profile_consent = await load_saved_chat_profile(farmer_id)
        checkpoint = await kisan_agent.aget_state(config)
        current_profile = checkpoint.values.get("profile")
        if hasattr(current_profile, "model_dump"):
            current_profile = current_profile.model_dump()
        inputs["profile"] = merge_chat_profiles(current_profile, saved_profile)

        final_state = await kisan_agent.ainvoke(inputs, config=config)

        response_data = build_chat_response(final_state, request_id=request_id)
        try:
            response_data["profile_saved"] = await save_chat_profile(
                farmer_id,
                final_state.get("profile"),
                consent_to_save=request.consent_to_save_profile,
                existing_consent=profile_consent,
            )
        except Exception as e:
            logger.error(
                f"[{request_id}] Failed to persist chat profile ({type(e).__name__})."
            )
            response_data["profile_saved"] = False
            response_data["profile_save_error"] = (
                "Your answer was processed, but profile details could not be saved. "
                "Please try again."
            )

        # 3. Translate response back to user's language (§31)
        if lang_code != INTERNAL_LANGUAGE and response_data.get("reply"):
            try:
                response_data["reply"] = await translate_from_internal(
                    response_data["reply"], lang_code
                )
            except Exception as e:
                logger.warning(f"[{request_id}] Response translation failed: {e}")
                # §33 — keep English text as fallback

        response_data["thread_id"] = thread_id  # client continues this session
        return ChatResponse(**response_data)

    except SchemSetuError as e:
        logger.error(f"[{request_id}] Application error: {e.message}")
        return ChatResponse(
            status="error",
            reply="I couldn't process that request right now. Please try again.",
            error=ErrorDetail(code=e.code, message=public_message(e), request_id=request_id),
            request_id=request_id,
        )
    except Exception as e:
        logger.error(f"[{request_id}] Unexpected error in /chat: {e}")
        return ChatResponse(
            status="error",
            reply="Something went wrong. Please try again.",
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred.",
                request_id=request_id,
            ),
            request_id=request_id,
        )
