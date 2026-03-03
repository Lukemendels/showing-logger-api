import os
import datetime
from fastapi import FastAPI, Header, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from google import genai
from dotenv import load_dotenv
import httpx
import json

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SHEETS_WEBHOOK_URL = os.getenv("SHEETS_WEBHOOK_URL")
AUTH_SECRET = os.getenv("AUTH_SECRET", "my_secret_demo_key")

app = FastAPI(title="Showing Logger API")

# Initialize Gemini Client
client = genai.Client() if GEMINI_API_KEY else None

from typing import List, Optional

# Pydantic models for request and response
class Action(BaseModel):
    action_type: str  # "ADD_ROW" or "CHECK_OFF"
    tab: str          # "Tasks", "Touchpoints", "Recon", "Personal", or "Contacts"
    task_name: Optional[str] = None
    row_data: Optional[List[str]] = None

class ActionList(BaseModel):
    actions: List[Action]

# Dependency to check headers
async def verify_auth_header(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != AUTH_SECRET:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    return authorization

@app.post("/api/second-brain")
async def process_second_brain(audio: UploadFile = File(...), auth: str = Depends(verify_auth_header)):
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is missing")

    if not client:
        raise HTTPException(status_code=500, detail="Gemini API Key is missing. Backend not fully configured.")

    # 1. Fetch Current State from Google Sheets
    sheet_context = {}
    if SHEETS_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(follow_redirects=True) as http_client:
                context_response = await http_client.get(
                    SHEETS_WEBHOOK_URL,
                    timeout=10.0
                )
                context_response.raise_for_status()
                sheet_context = context_response.json()
        except Exception as e:
            print(f"Error fetching state from Sheets Webhook: {e}")
            # We can still proceed even if context fails

    # 2. Transcribe Audio (Prompt 1)
    transcription_prompt = "Listen to this audio and return a highly accurate, raw text transcription of exactly what is said. Do not add any formatting or commentary, just the transcription."
    audio_bytes = await audio.read()
    
    try:
        transcription_response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                genai.types.Part.from_bytes(data=audio_bytes, mime_type=audio.content_type or "audio/mp4"),
                transcription_prompt
            ]
        )
        raw_transcript = transcription_response.text
        print(f"Transcription complete: {raw_transcript}")
    except Exception as e:
        print(f"Error during audio transcription: {e}")
        raise HTTPException(status_code=500, detail="Failed to transcribe audio with Gemini")

    # 3. Route and Format Actions (Prompt 2)
    current_datetime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    formatting_prompt = f"""
    You are an intelligent Second Brain assistant. Read the provided Transcription and parse it into structured actions for a Google Sheet.
    
    Current Date and Time: {current_datetime}
    
    Current Context:
    - Active Tasks: {json.dumps(sheet_context.get('tasks', []))}
    - Contacts: {json.dumps(sheet_context.get('contacts', []))}
    
    Transcription:
    "{raw_transcript}"
    
    Based on the dictation, create a list of actions to perform on the Google Sheet.
    
    Allowed action_type: "ADD_ROW" or "CHECK_OFF"
    Allowed tabs: "Tasks", "Touchpoints", "Recon", "Personal", "Contacts"
    
    Rules for ADD_ROW:
    - row_data must perfectly match the tab's headers in exact order.
    
    1. Tasks Tab ["FALSE", "Date", "Time Due", "Task", "Details", "Action Required"]
       * "Task": A short, 3-to-5 word title (e.g., "Smith Closing Docs").
       * "Details": Any extra context or information provided (e.g., "Missing signature on page 4"). Leave blank if none.
       * "Action Required": The physical, immediate next step starting with a verb (e.g., "Call Title Company", "Draft Email to John"). Do NOT repeat the Task name here.
       
    2. Touchpoints Tab ["FALSE", "Date", "Time Due", "Person", "Context", "Drafted SMS"]
       * "Person": The name of the client or contact.
       * "Context": Why are we reaching out? (e.g. "Just had a baby", "Met at coffee shop").
       * "Drafted SMS": You MUST write a polite, ready-to-send text message based on the context. Do not leave this blank.
       
    3. Recon Tab ["FALSE", "Date", "Time Due", "Opportunity", "Location", "Next Steps"]
    4. Personal Tab ["FALSE", "Date", "Time Due", "Item", "Details", "Notes"]
    5. Contacts Tab ["Name", "Phone", "Email", "Context / VIP Status"] (No "FALSE" or "Time Due" here)
    
    - "Time Due" should be formatted like "10:30 AM", "Morning", "Afternoon", or left as an empty string "" if not stated.
    - If adding a row with a checkbox, the first item in row_data must be the string "FALSE".
    - Use "YYYY-MM-DD" for dates.
    
    ### CRITICAL BUSINESS LOGIC:
    - If the user asks to explicitly perform TWO overlapping things (e.g. "Draft an SMS to Kevin" AND "Remind me to do it tomorrow"), you should generate TWO distinct Actions in the array. 
    - The first action goes to the Touchpoints tab to map the context and actually draft the SMS.
    - The second action goes to the Tasks tab ("Send Kevin SMS") so it hits their daily to-do list workflow.
    
    Rules for CHECK_OFF:
    - task_name is required. It should match or closely resemble the name of the item to be checked off.
    - row_data should be null.
    
    Generate the JSON matching the ActionList schema.
    """

    try:
        routing_response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=formatting_prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ActionList,
                temperature=0.2
            ),
        )
        extracted_data = json.loads(routing_response.text)
    except Exception as e:
        print(f"Error calling Gemini for routing: {e}")
        raise HTTPException(status_code=500, detail="Failed to route transcript with Gemini")

    # 3. Send the extracted actions to Google Sheets Webhook
    sheet_status = "Skipped (No URL provided)"
    if SHEETS_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(follow_redirects=True) as http_client:
                sheet_response = await http_client.post(
                    SHEETS_WEBHOOK_URL, 
                    json=extracted_data,
                    timeout=15.0
                )
                sheet_response.raise_for_status()
                sheet_status = sheet_response.json()
        except Exception as e:
            print(f"Error sending data to Sheets Webhook: {e}")
            sheet_status = f"Failed: {str(e)}"

    return {
        "status": "success", 
        "actions": extracted_data,
        "sheet_status": sheet_status
    }
