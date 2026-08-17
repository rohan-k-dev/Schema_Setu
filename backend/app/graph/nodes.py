import os
import json
from tavily import TavilyClient
from langchain_core.prompts import PromptTemplate
from app.database import get_db_connection
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from pydantic import ValidationError


from .state import KisanState
from app.models.schemas import FarmerProfile

tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Initialize the Groq LLM
# LLaMA 3.3 70B is excellent for highly accurate entity extraction
llm = ChatGroq(
    temperature=0, 
    model_name="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY")
)

# Bind the LLM to our Pydantic schema
# This guarantees the output will be a FarmerProfile object, not random text
structured_llm = llm.with_structured_output(FarmerProfile)

reasoning_prompt = PromptTemplate.from_template("""
You are an expert agricultural scheme advisor in India.
You have the following farmer profile:
{profile}

You have found the following potential government schemes:
{schemes_data}

Analyze each scheme against the farmer's profile. 
Return a JSON list of strictly eligible schemes. For each scheme, include:
1. "scheme_name": The name of the scheme.
2. "benefit": A brief explanation of what the farmer gets.
3. "xai_explanation": A simple, explainable reason WHY they are eligible based on their specific profile data (e.g., "Because you own less than 2 acres of land...").

Output ONLY valid JSON. No markdown tags, no conversational text.
""")

# Define the extraction prompt
extraction_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an expert agricultural AI assistant operating in India. 
    Your job is to read the conversation history and extract demographic and agricultural data about the farmer.
    If a piece of information is not explicitly mentioned, leave it as null/None. 
    Do not guess or assume.
    Extract the following if available: state, district, land_size_acres, primary_crop, annual_income, category, gender, has_aadhaar.
    """),
    ("placeholder", "{messages}")
])

extraction_chain = extraction_prompt | structured_llm

async def profile_extractor_node(state: KisanState) -> dict:
    """Uses Groq LLM to passively extract profile data from user messages."""
    print("Executing Profile Extractor Node...")
    
    messages = state.get("messages", [])
    if not messages:
        return {"profile": state.get("profile")}
        
    try:
        # Pass the conversation history to the LLM to extract the latest state
        extracted_profile = await extraction_chain.ainvoke({"messages": messages})
        
        # SAFETY CHECK: If the LLM returned None, just return the existing profile
        if not extracted_profile:
            return {"profile": state.get("profile")}
            
        # Merge the newly extracted data with the existing profile
        current_profile_dict = state.get("profile", FarmerProfile()).model_dump()
        new_profile_dict = extracted_profile.model_dump(exclude_unset=True, exclude_none=True)
        
        current_profile_dict.update(new_profile_dict)
        
        return {"profile": FarmerProfile(**current_profile_dict)}
        
    except Exception as e:
        print(f"Extraction failed: {e}")
        return {"profile": state.get("profile")}

async def completeness_checker_node(state: KisanState) -> dict:
    """
    Evaluates the completeness threshold.
    Critical fields: state, land_size_acres, primary_crop.
    """
    print("Executing Completeness Checker Node...")
    
    profile = state.get("profile")
    missing_fields = []
    
    if not profile:
        return {"missing_fields": ["state", "land_size_acres", "primary_crop"]}

    # Check critical fields as defined in your architecture
    if not profile.state:
        missing_fields.append("state")
    if profile.land_size_acres is None:
        missing_fields.append("land_size_acres")
    if not profile.primary_crop:
        missing_fields.append("primary_crop")
        
    print(f"Missing fields identified: {missing_fields}")
    
    return {"missing_fields": missing_fields}

async def fetch_local_schemes(state_name: str, crop: str) -> list:
    """Fetches cached schemes from NeonDB based on basic keyword matching."""
    schemes = []
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                # Basic SQL search to find relevant local schemes
                query = """
                    SELECT title, ministry, benefits_details, eligibility_criteria_raw 
                    FROM schemes 
                    WHERE state_specific = %s OR eligibility_criteria_raw ILIKE %s
                """
                await cur.execute(query, (state_name, f"%{crop}%"))
                rows = await cur.fetchall()
                for row in rows:
                    schemes.append({
                        "source": "NeonDB",
                        "title": row[0],
                        "ministry": row[1],
                        "benefits": row[2],
                        "criteria": row[3]
                    })
    except Exception as e:
        print(f"Database search failed: {e}")
    return schemes

async def eligibility_filter_node(state: KisanState) -> dict:
    """Discovers schemes (Tavily + NeonDB) and matches them against the profile."""
    print("Executing Eligibility Filter Node (Search + Reasoning)...")
    
    profile = state.get("profile")
    if not profile:
        return {"recommended_schemes": []}
    
    # 1. PARALLEL SEARCH
    search_query = f"Government agricultural schemes in {profile.state} for {profile.primary_crop} farmers with {profile.land_size_acres} acres of land"
    
    # Fetch from Tavily (Web)
    print(f"Searching Tavily for: {search_query}")
    tavily_results = tavily_client.search(query=search_query, search_depth="advanced", max_results=3)
    web_schemes = [{"source": "Tavily Web", "content": res["content"]} for res in tavily_results.get("results", [])]
    
    # Fetch from NeonDB (Local Cache)
    print(f"Searching NeonDB local cache...")
    local_schemes = await fetch_local_schemes(profile.state, profile.primary_crop)
    
    # Combine Data
    combined_schemes_data = json.dumps({"web_results": web_schemes, "local_results": local_schemes})
    profile_data = profile.model_dump_json()

    # 2. COGNITIVE REASONING (Groq LLaMA 3.3)
    try:
        print("Running XAI Eligibility Matching...")
        formatted_prompt = reasoning_prompt.format(
            profile=profile_data, 
            schemes_data=combined_schemes_data
        )
        
        # We enforce a strict JSON output so the frontend can parse it easily
        response = await llm.ainvoke(formatted_prompt)
        
        # Clean the output in case the LLM wraps it in markdown blocks
        clean_json = response.content.replace("```json", "").replace("```", "").strip()
        final_recommendations = json.loads(clean_json)
        
        print(f"Successfully matched {len(final_recommendations)} schemes.")
        return {"recommended_schemes": final_recommendations}
        
    except Exception as e:
        print(f"Eligibility reasoning failed: {e}")
        return {"recommended_schemes": []}

# Define a standard prompt for asking follow-up questions
question_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful and polite agricultural assistant in India. 
    The user is applying for government schemes, but their profile is missing the following information: {missing_fields}.
    Ask a very brief, simple, and friendly question to get ONE of these missing pieces of information. 
    Ask in English, but keep the vocabulary extremely simple. Do not ask for everything at once. 
    Focus only on the first missing field in the list."""),
    ("placeholder", "{messages}")
])

question_chain = question_prompt | llm | StrOutputParser()

async def question_generator_node(state: KisanState) -> dict:
    """Generates a follow-up question when critical profile fields are missing."""
    print("Executing Question Generator Node...")
    
    missing = state.get("missing_fields", [])
    if not missing:
        return {"messages": []} # Failsafe
        
    try:
        # Generate the question text
        question_text = await question_chain.ainvoke({
            "missing_fields": ", ".join(missing),
            "messages": state.get("messages", [])
        })
        
        print(f"Generated Question: {question_text}")
        
        # In the full system, this text gets sent to Sarvam TTS to create audio.
        # For the LangGraph state, we return it as an AI message.
        return {"messages": [("assistant", question_text)]}
        
    except Exception as e:
        print(f"Question generation failed: {e}")
        return {"messages": [("assistant", "Could you please tell me more about your farming land?")]}