import httpx
import os
from fastapi import UploadFile, File, Form, HTTPException
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from .database import init_db, close_db, get_db_connection
from psycopg import AsyncConnection
from pydantic import BaseModel
from app.graph.workflow import kisan_agent
from langchain_core.messages import HumanMessage

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Open DB pool
    await init_db()
    yield
    # Shutdown: Close DB pool
    await close_db()

app = FastAPI(
    title="Kisan Agent API",
    description="Backend for Rural Edge AI Capstone",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default_session"

# --- Add this Pydantic model near your ChatRequest model ---
class TTSRequest(BaseModel):
    text: str
    language_code: str = "hi-IN" # Defaulting to Hindi for the prototype

@app.post("/voice")
async def chat_with_voice(
    file: UploadFile = File(...), 
    thread_id: str = Form("default_session")
):
    """1. ASR: Converts Farmer's Audio -> English Text -> LangGraph"""
    audio_bytes = await file.read()
    
    sarvam_api_key = os.getenv("SARVAM_API_KEY")
    if not sarvam_api_key:
        raise HTTPException(status_code=500, detail="Sarvam API Key missing.")

    # Call Sarvam AI to translate Native Speech to English Text
    sarvam_url = "https://api.sarvam.ai/speech-to-text-translate"
    files = {"file": (file.filename, audio_bytes, file.content_type)}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                sarvam_url,
                headers={"api-subscription-key": sarvam_api_key},
                files=files
            )
            response.raise_for_status()
            translated_text = response.json().get("transcript", "")
        except Exception as e:
            print(f"Sarvam ASR Error: {e}")
            raise HTTPException(status_code=502, detail="Speech processing failed.")

    if not translated_text:
        return {"status": "error", "reply": "I couldn't hear that clearly."}

    # Pass the translated text into LangGraph
    inputs = {"messages": [HumanMessage(content=translated_text)]}
    config = {"configurable": {"thread_id": thread_id}}
    final_state = await kisan_agent.ainvoke(inputs, config=config)
    
    # Safely parse response (using the same logic as our text /chat endpoint)
    messages = final_state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        reply_text = last_msg.content if hasattr(last_msg, 'type') else last_msg[1]
        
        return {
            "status": "asking_question",
            "reply": reply_text,
            "user_transcript": translated_text,
            "current_profile": final_state.get("profile")
        }
    
    schemes = final_state.get("recommended_schemes", [])
    if schemes:
        return {
            "status": "schemes_found",
            "schemes": schemes,
            "user_transcript": translated_text,
            "current_profile": final_state.get("profile")
        }
        
    return {"status": "error", "reply": "I couldn't process that request."}

@app.post("/tts")
async def generate_speech(request: TTSRequest):
    """2. TTS: Converts AI English Text -> Native Language Audio"""
    sarvam_api_key = os.getenv("SARVAM_API_KEY")
    url = "https://api.sarvam.ai/text-to-speech"
    
    # CORRECTED PAYLOAD FOR SARVAM AI
    payload = {
        "inputs": [request.text],
        "target_language_code": request.language_code, # e.g., "hi-IN"
        "speaker": "aditya", # standard female voice
        "pace": 1.0,        # bulbul:v3 supports pace, but not pitch/loudness
        "model": "bulbul:v3"
    }
    
    headers = {
        "api-subscription-key": sarvam_api_key, 
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            # Returns a base64 encoded audio string
            return {"audio_base64": data["audios"][0]}
        except httpx.HTTPStatusError as e:
            print(f"Sarvam TTS Error: {e.response.text}")
            raise HTTPException(status_code=502, detail="Text to speech failed.")
        except Exception as e:
            print(f"Sarvam TTS Error: {e}")
            raise HTTPException(status_code=502, detail="Text to speech failed.")

@app.post("/chat")
async def chat_with_agent(request: ChatRequest):
    inputs = {"messages": [HumanMessage(content=request.message)]}
    config = {"configurable": {"thread_id": request.thread_id}}
    
    final_state = await kisan_agent.ainvoke(inputs, config=config)
    
    messages = final_state.get("messages", [])
    
    # Safely parse the final message regardless of how LangGraph formats it
    if messages:
        last_message = messages[-1]
        is_ai = False
        reply_text = ""
        
        # Check if it's a LangChain BaseMessage object
        if hasattr(last_message, 'type') and last_message.type == 'ai':
            is_ai = True
            reply_text = last_message.content
        # Check if it's a tuple (e.g., ("assistant", "Hello"))
        elif isinstance(last_message, tuple) and last_message[0] in ["ai", "assistant"]:
            is_ai = True
            reply_text = last_message[1]

        if is_ai:
            return {
                "status": "asking_question",
                "reply": reply_text,
                "current_profile": final_state.get("profile")
            }
    
    schemes = final_state.get("recommended_schemes", [])
    if schemes:
        return {
            "status": "schemes_found",
            "schemes": schemes,
            "current_profile": final_state.get("profile")
        }
        
    return {"status": "error", "reply": "I couldn't process that request."}

@app.get("/")
async def root():
    return {"message": "Kisan Agent API is running."}

@app.get("/health")
async def health_check(conn: AsyncConnection = Depends(get_db_connection)):
    """Verifies the API is up and the database is accessible."""
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1;")
            result = await cur.fetchone()
        return {
            "status": "healthy", 
            "db_connected": result[0] == 1
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")