import os
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

# Pydantic models for request and response
class ShowingData(BaseModel):
    client_name: str
    property_address: str
    sentiment: str
    action_items: str
    drafted_sms: str

# Dependency to check headers
async def verify_auth_header(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != AUTH_SECRET:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    return authorization

@app.post("/api/log-showing")
async def log_showing(audio: UploadFile = File(...), auth: str = Depends(verify_auth_header)):
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is missing")

    if not client:
        raise HTTPException(status_code=500, detail="Gemini API Key is missing. Backend not fully configured.")

    # 1. Ask Gemini to extract data
    prompt = """
    You are a real estate assistant. Listen to the audio dictation of a property showing.
    
    Return exactly matching this JSON schema. If any information is missing, use "N/A" or make a reasonable empty assumption (like "None").
    For 'sentiment', summarize the buyer's feeling about the property in a few words.
    For 'drafted_sms', write a short, polite text message to the client thanking them for the showing and mentioning the next steps if any, or just touching base.
    """

    audio_bytes = await audio.read()

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                genai.types.Part.from_bytes(data=audio_bytes, mime_type=audio.content_type or "audio/mp4"),
                prompt
            ],
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ShowingData,
                temperature=0.2
            ),
        )
        extracted_data = json.loads(response.text)
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        raise HTTPException(status_code=500, detail="Failed to process audio with Gemini")

    # 2. Send the extracted data to Google Sheets Webhook
    sheet_status = "Skipped (No URL provided)"
    if SHEETS_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(follow_redirects=True) as http_client:
                sheet_response = await http_client.post(
                    SHEETS_WEBHOOK_URL, 
                    json=extracted_data,
                    timeout=10.0
                )
                sheet_response.raise_for_status()
                sheet_status = "Success"
        except Exception as e:
            print(f"Error sending data to Sheets Webhook: {e}")
            sheet_status = f"Failed: {str(e)}"

    return {
        "status": "success", 
        "data": extracted_data,
        "sheet_status": sheet_status
    }
