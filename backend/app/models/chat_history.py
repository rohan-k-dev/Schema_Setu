"""API models for a farmer's saved conversations (docs/CHAT_HISTORY.md)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ConversationSummary(BaseModel):
    thread_id: str
    title: Optional[str] = None
    language: Optional[str] = None
    message_count: int = 0
    created_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None


class ConversationMessage(BaseModel):
    role: str                                   # USER / ASSISTANT
    content: str
    language: Optional[str] = None
    input_mode: Optional[str] = None            # text / voice
    status: Optional[str] = None                # the reply's status (schemes_found, asking_question, …)
    schemes: Optional[List[Dict[str, Any]]] = None   # schemes shown with that reply (id, name, section, status)
    created_at: Optional[datetime] = None


class Conversation(ConversationSummary):
    messages: List[ConversationMessage] = []


class ChatHistorySettings(BaseModel):
    enabled: bool
