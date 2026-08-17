from typing import TypedDict, Annotated, List, Optional
from langchain_core.messages import BaseMessage
from operator import add
from app.models.schemas import FarmerProfile

class KisanState(TypedDict):
    """
    The central state object for the Kisan Agent LangGraph workflow.
    This tracks the conversation, extracted data, and final outputs.
    """
    
    # Tracks the full conversation history. 
    # The 'add' operator ensures new messages are appended to the list rather than overwriting it.
    messages: Annotated[List[BaseMessage], add]
    
    # The structured data matrix extracted from the user's text/voice inputs.
    # We map this directly to the Pydantic model for type safety.
    profile: FarmerProfile
    
    # A dynamic list of critical fields (e.g., 'state', 'land_size_acres') that the user 
    # hasn't provided yet, triggering the Multi-Turn Loop.
    missing_fields: List[str]
    
    # The final list of eligible government schemes retrieved from Tavily and NeonDB, 
    # complete with Explainable AI (XAI) reasoning.
    recommended_schemes: List[dict]
    
    # The language tag (e.g., "hi" for Hindi, "en" for English) detected by Sarvam ASR 
    # during the initial input, ensuring the final TTS output matches the user's language.
    native_language: str