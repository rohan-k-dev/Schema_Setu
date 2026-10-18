"""
Serialization utilities — Phase 4.

Reusable helpers for extracting data from the expanded LangGraph state.
Prevents duplicating response-parsing logic across multiple routes.
"""

from typing import Optional, Dict, Any, List
from langchain_core.messages import BaseMessage


def extract_latest_ai_message(messages: list) -> Optional[str]:
    """
    Safely extract the latest AI/assistant message from LangGraph messages.

    Handles both LangChain BaseMessage objects and tuple formats.
    Returns None if no AI message is found.
    """
    if not messages:
        return None

    # Walk backwards to find the latest AI message
    for msg in reversed(messages):
        # LangChain BaseMessage object
        if hasattr(msg, "type") and msg.type == "ai":
            return msg.content
        # Tuple format: ("assistant", "text") or ("ai", "text")
        if isinstance(msg, (list, tuple)) and len(msg) >= 2:
            if msg[0] in ("ai", "assistant"):
                return msg[1]

    return None


def build_chat_response(
    final_state: dict,
    request_id: Optional[str] = None,
    user_transcript: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a normalized chat response from LangGraph final state.

    Phase 4: Uses response_status, response_text, response_schemes,
    and retrieval_metadata from the expanded state.
    """
    messages = final_state.get("messages", [])
    profile = final_state.get("profile")

    # Serialize profile if it's a Pydantic model
    if profile and hasattr(profile, "model_dump"):
        profile = profile.model_dump()

    response: Dict[str, Any] = {"request_id": request_id}

    # Phase 4 response fields
    response_status = final_state.get("response_status")
    response_text = final_state.get("response_text")
    response_schemes = final_state.get("response_schemes", [])
    retrieval_metadata = final_state.get("retrieval_metadata")

    if response_status:
        # Use the Phase 4 typed response
        response["status"] = response_status
        response["reply"] = response_text or extract_latest_ai_message(messages)
        response["current_profile"] = profile

        if response_schemes:
            response["schemes"] = response_schemes

        if retrieval_metadata:
            response["retrieval_metadata"] = retrieval_metadata

    else:
        # Fallback to Phase 0 behavior for backward compatibility
        schemes = final_state.get("recommended_schemes", [])

        if schemes:
            response.update({
                "status": "schemes_found",
                "schemes": schemes,
                "current_profile": profile,
            })
        else:
            reply = extract_latest_ai_message(messages)
            if reply:
                response.update({
                    "status": "asking_question",
                    "reply": reply,
                    "current_profile": profile,
                })
            else:
                response.update({
                    "status": "error",
                    "reply": "I couldn't process that request. Could you try again?",
                })

    if response.get("status") == "error" and final_state.get("error"):
        response["error"] = {
            "code": final_state["error"],
            "message": response.get("reply") or "The request could not be completed.",
            "request_id": request_id,
        }

    # Safe review status for the user (§191) — never exposes reviewer data
    if final_state.get("needs_review"):
        response["review"] = {
            "needs_review": True,
            "reason": final_state.get("review_reason"),
            "case_id": final_state.get("review_case_id"),
        }

    # Include user transcript for voice responses
    if user_transcript:
        response["user_transcript"] = user_transcript

    return response
