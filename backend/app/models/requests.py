"""
API request models.

Typed request schemas for all API endpoints.
"""

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class ChatRequest(BaseModel):
    """Request body for POST /chat."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=settings.MAX_MESSAGE_CHARS,
        description="User's text message",
    )
    thread_id: str = Field(
        default="default_session",
        max_length=128,
        description="Session thread ID for multi-turn conversation"
    )
    language: str = Field(
        default="en",
        max_length=16,
        description="Selected language code (e.g. 'hi', 'kn', 'ta')"
    )
    consent_to_save_profile: bool = Field(
        default=False,
        description="Explicit consent to save profile details extracted from this conversation",
    )

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


class TTSRequest(BaseModel):
    """Request body for POST /tts."""
    text: str = Field(..., min_length=1, max_length=5000, description="Text to convert to speech")
    language_code: str = Field(
        default="hi-IN",
        max_length=16,
        description="Target language code for TTS (e.g., hi-IN, en-IN, kn-IN)"
    )
