"""
Voice API routes — ASR (/voice) and TTS (/tts).

Phase 6: Language-aware voice pipeline (§19, §36).
Voice and text use the SAME LangGraph pipeline (§5).
Translation is handled as input normalization (§17).
"""

import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.workflow import kisan_agent
from app.api.deps import get_optional_farmer_id
from app.models.requests import TTSRequest
from app.models.responses import ChatResponse, TTSResponse, ErrorDetail
from app.services.chat_profile_service import (
    load_saved_chat_profile,
    merge_chat_profiles,
    save_chat_profile,
)
from app.services.profile_service import SEARCH_STATUSES, record_search
from app.services.review_workflow import link_review_case
from app.services.voice_service import transcribe_audio, generate_speech, ASRResult
from app.services.language_service import translate_to_internal, translate_from_internal
from app.localization.detect import detect_text_language, spoken_language
from app.localization.languages import (
    get_sarvam_code, resolve_language_code, INTERNAL_LANGUAGE,
)
from app.utils.serialization import build_chat_response
from app.services.chat_history_service import context_messages, record_turn, resolve_thread
from app.utils.validation import validate_audio_upload, get_audio_extension
from app.core.logging import get_logger
from app.core.exceptions import SchemSetuError, ConfigurationError, ServiceQuotaError, public_message

logger = get_logger(__name__)

router = APIRouter(tags=["Voice"])


@router.post(
    "/voice",
    response_model=ChatResponse,
    summary="Voice input conversation with the Kisan Agent",
    description="Upload audio for ASR transcription, then process through the agent.",
)
async def chat_with_voice(
    file: UploadFile = File(..., description="Audio file from microphone"),
    thread_id: str = Form("default_session", description="Session thread ID"),
    language: str = Form("en", description="Selected language code (e.g. 'hi', 'kn')"),
    consent_to_save_profile: bool = Form(False),
    farmer_id: str | None = Depends(get_optional_farmer_id),
):
    """
    Process voice audio: ASR → Translation → LangGraph → Translation → TTS (§19).
    Uses the SAME pipeline as /chat (§5, §36).
    """
    request_id = str(uuid.uuid4())[:8]

    # Generate unique thread_id if default (§57)
    if not thread_id or thread_id == "default_session":
        thread_id = str(uuid.uuid4())
    # never continue a conversation that belongs to another account (docs/CHAT_HISTORY.md)
    thread_id = await resolve_thread(farmer_id, thread_id)

    lang_code = resolve_language_code(language)
    logger.info(
        f"[{request_id}] Voice request: thread={thread_id}, "
        f"lang={lang_code}, content_type={file.content_type}"
    )

    try:
        # 1. Read and validate audio (§21)
        audio_bytes = await file.read()
        is_valid, error_msg = validate_audio_upload(
            content_type=file.content_type,
            file_size=len(audio_bytes),
            filename=file.filename,
            header=audio_bytes[:16],
        )
        if not is_valid:
            logger.warning(f"[{request_id}] Audio validation failed: {error_msg}")
            return ChatResponse(
                status="error",
                reply=error_msg,
                error=ErrorDetail(
                    code="VALIDATION_ERROR",
                    message=error_msg,
                    request_id=request_id,
                ),
                request_id=request_id,
            )

        # Determine correct filename with proper extension (§20)
        extension = get_audio_extension(file.content_type or "audio/webm")
        safe_filename = f"recording{extension}"

        # 2. ASR — language-aware transcription (§27)
        asr_result = await transcribe_audio(
            audio_bytes=audio_bytes,
            filename=safe_filename,
            content_type=file.content_type or "audio/webm",
            language_code=lang_code,
        )

        if not asr_result or not asr_result.text:
            # §29 — VOICE_TRANSCRIPTION_FAILED
            return ChatResponse(
                status="error",
                reply="Sorry, I couldn't understand the audio. Please try again or type your question.",
                error=ErrorDetail(
                    code="VOICE_TRANSCRIPTION_FAILED",
                    message="ASR returned empty transcript.",
                    request_id=request_id,
                ),
                request_id=request_id,
            )

        native_transcript = asr_result.text
        # Answer in the language Sarvam heard, whatever the picker says
        lang_code = spoken_language(asr_result.language, lang_code)
        logger.info(f"[{request_id}] ASR transcript received ({len(native_transcript)} chars), "
                    f"spoken language={lang_code}")

        # 3. Internal (English) text: speech-to-text-translate already returns English; translate only
        #    if the transcript came back in an Indian script (§15, §18)
        script = detect_text_language(native_transcript, INTERNAL_LANGUAGE)
        internal_text = (native_transcript if script == INTERNAL_LANGUAGE
                         else await translate_to_internal(native_transcript, script))
        logger.info(f"[{request_id}] Internal text ready ({len(internal_text)} chars)")

        # 4. Pass through SAME LangGraph pipeline (§5)
        inputs = {
            "messages": [HumanMessage(content=internal_text)],
            "session_id": thread_id,
            # per-turn flags: a previous turn's review notice must not carry over
            "needs_review": False, "review_reason": None, "review_case_id": None,
            "live_check": None,           # per turn: never show an earlier turn's live check
        }
        config = {"configurable": {"thread_id": thread_id}}

        saved_profile, profile_consent = await load_saved_chat_profile(farmer_id)
        checkpoint = await kisan_agent.aget_state(config)
        current_profile = checkpoint.values.get("profile")
        if hasattr(current_profile, "model_dump"):
            current_profile = current_profile.model_dump()
        inputs["profile"] = merge_chat_profiles(
            current_profile, saved_profile, saved_is_authoritative=profile_consent)
        # Continuing a saved conversation whose in-memory state is gone: give the assistant its last turns
        if not checkpoint.values.get("messages"):
            earlier = await context_messages(farmer_id, thread_id)
            if earlier:
                inputs["messages"] = [HumanMessage(content=t) if role == "human" else AIMessage(content=t)
                                      for role, t in earlier] + inputs["messages"]

        final_state = await kisan_agent.ainvoke(inputs, config=config)

        # 5. Build response
        response_data = build_chat_response(
            final_state,
            request_id=request_id,
            user_transcript=native_transcript,
        )
        try:
            response_data["profile_saved"] = await save_chat_profile(
                farmer_id,
                final_state.get("profile"),
                consent_to_save=consent_to_save_profile,
                existing_consent=profile_consent,
                previous=inputs["profile"],
            )
        except Exception as e:
            logger.error(
                f"[{request_id}] Failed to persist voice profile ({type(e).__name__})."
            )
            response_data["profile_saved"] = False
            response_data["profile_save_error"] = (
                "Your answer was processed, but profile details could not be saved. "
                "Please try again."
            )

        # Recent searches: kept only per the retention policy (docs/DASHBOARD.md)
        if response_data.get("status") in SEARCH_STATUSES:
            await record_search(farmer_id, native_transcript, len(response_data.get("schemes") or []), lang_code)

        # Let a signed-in farmer follow the review case their search raised (docs/HUMAN_REVIEW.md)
        if farmer_id and (response_data.get("review") or {}).get("case_id"):
            await link_review_case(response_data["review"]["case_id"], farmer_id)

        # 6. Translate response to native language (§31)
        if lang_code != INTERNAL_LANGUAGE and response_data.get("reply"):
            try:
                response_data["reply"] = await translate_from_internal(
                    response_data["reply"], lang_code
                )
            except Exception as e:
                logger.warning(f"[{request_id}] Response translation failed: {e}")
                # §33 — keep English text as fallback

        # Chat history: the question as asked and the reply as shown (signed-in accounts only)
        await record_turn(farmer_id, thread_id, native_transcript, response_data, language=lang_code,
                          input_mode="voice")
        response_data["thread_id"] = thread_id  # client continues this session
        response_data["language"] = lang_code    # the UI speaks the reply in this language
        return ChatResponse(**response_data)

    except ConfigurationError as e:
        logger.error(f"[{request_id}] Configuration error: {e.message}")
        return ChatResponse(
            status="error",
            reply="Voice service is not configured. Please contact support.",
            error=ErrorDetail(code=e.code, message=public_message(e), request_id=request_id),
            request_id=request_id,
        )
    except SchemSetuError as e:
        logger.error(f"[{request_id}] Voice processing error: {e.message}")
        quota = isinstance(e, ServiceQuotaError)
        return ChatResponse(
            status="error",
            reply=("Voice input isn't available right now: the speech service has no credits left. "
                   "Please type your question instead." if quota
                   else "Voice processing failed. Please try again or use text input."),
            error=ErrorDetail(code=e.code, message=public_message(e), request_id=request_id),
            request_id=request_id,
        )
    except Exception as e:
        logger.error(f"[{request_id}] Unexpected error in /voice: {e}")
        return ChatResponse(
            status="error",
            reply="Something went wrong processing your voice. Please try again.",
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="Voice processing failed.",
                request_id=request_id,
            ),
            request_id=request_id,
        )


@router.post(
    "/tts",
    response_model=TTSResponse,
    summary="Text-to-Speech conversion",
    description="Convert text to speech audio using Sarvam AI.",
)
async def text_to_speech(request: TTSRequest):
    """Convert text to speech via Sarvam TTS (§32)."""
    request_id = str(uuid.uuid4())[:8]
    logger.info(
        f"[{request_id}] TTS request: lang={request.language_code}, "
        f"text_len={len(request.text)}"
    )

    try:
        audio_base64 = await generate_speech(
            text=request.text,
            language_code=request.language_code,
        )

        if not audio_base64:
            # §33 — TTS failure: return text, audio_status = unavailable
            return TTSResponse(
                error=ErrorDetail(
                    code="TTS_EMPTY",
                    message="No audio was generated.",
                    request_id=request_id,
                ),
                request_id=request_id,
            )

        return TTSResponse(audio_base64=audio_base64, request_id=request_id)

    except ConfigurationError as e:
        logger.error(f"[{request_id}] TTS config error: {e.message}")
        return TTSResponse(
            error=ErrorDetail(code=e.code, message=public_message(e), request_id=request_id),
            request_id=request_id,
        )
    except SchemSetuError as e:
        logger.error(f"[{request_id}] TTS error: {e.message}")
        return TTSResponse(
            error=ErrorDetail(code=e.code, message=public_message(e), request_id=request_id),
            request_id=request_id,
        )
    except Exception as e:
        logger.error(f"[{request_id}] Unexpected TTS error: {e}")
        return TTSResponse(
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="Text-to-speech failed.",
                request_id=request_id,
            ),
            request_id=request_id,
        )
