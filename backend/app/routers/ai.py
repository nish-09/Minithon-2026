import logging

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import RelationshipPreference, User
from ..schemas import AIUnderstandIn, TranscriptIn, VoiceCommandIn
from ..security import current_user
from ..services import nlu, voice
from .requests import flow

log = logging.getLogger("nexa.ai")
router = APIRouter(prefix="/api", tags=["ai"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/ai/understand-request")
def understand_request(body: AIUnderstandIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Structured understanding of free text, plus the Trusted Circle prompt the UI should show."""
    text, _ = voice.strip_wake_word(body.text)
    u = nlu.understand(text)
    lat = body.lat if body.lat is not None else user.lat
    lng = body.lng if body.lng is not None else user.lng
    summary = voice.circle_summary(db, user, lat, lng) if lat is not None else {"count": 0, "groups": {}, "phrase": "", "members": []}
    prompt = None
    if u.urgency == "normal" and summary["count"]:
        prompt = f"You have {summary['phrase']} nearby. Would you like me to ask them first?"
    pref = db.get(RelationshipPreference, user.id)
    window = 0 if u.urgency == "critical" else (
        pref.circle_window_override_s if pref and pref.circle_window_override_s is not None and u.urgency == "normal" else get_settings().circle_window(u.urgency))
    return {
        "understanding": u.to_dict(),
        "circle_window_s": window,
        "trusted_circle": summary,
        "circle_prompt": prompt,
        "suggested_routing": "emergency" if u.urgency == "critical" else ("circle_first" if summary["count"] and u.urgency == "normal" else "community"),
        "emergency_advice": (f"If this is serious, call {get_settings().emergency_number} now." if u.urgency == "critical" else None),
    }


@router.post("/ai/classify-urgency")
def classify_urgency(body: AIUnderstandIn, user: User = Depends(current_user)):
    text, _ = voice.strip_wake_word(body.text)
    u = nlu.understand(text)
    flags = nlu.detect_red_flags(text)
    return {"urgency": u.urgency, "category": u.category, "red_flags": flags, "source": u.source,
            "emergency_services_advised": u.urgency == "critical"}


@router.post("/voice/transcript")
def clean_transcript(body: TranscriptIn, user: User = Depends(current_user)):
    """Normalise a transcript produced by the browser's speech recognition (wake word stripped)."""
    text, wake = voice.strip_wake_word(body.transcript)
    return {"text": text, "wake_word_detected": wake, "low_confidence": body.confidence is not None and body.confidence < 0.5}


@router.post("/voice/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...), user: User = Depends(current_user)):
    """Server-side speech-to-text for clients without Web Speech support.

    Forwards to an OpenAI-compatible `/audio/transcriptions` endpoint configured via NEXA_STT_URL /
    NEXA_STT_API_KEY (works with OpenAI Whisper or a self-hosted faster-whisper server). If nothing is
    configured this returns 501 and the client falls back to typed input - we never fake a transcript.
    """
    s = get_settings()
    if not s.stt_url:
        raise HTTPException(501, "Server-side transcription is not configured. Use the browser's speech recognition or type your request.")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large")
    if not data:
        raise HTTPException(422, "Empty audio")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                s.stt_url, headers={"Authorization": f"Bearer {s.stt_api_key}"} if s.stt_api_key else {},
                files={"file": (audio.filename or "audio.webm", data, audio.content_type or "audio/webm")}, data={"model": s.stt_model})
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("STT failed: %s", e)
        raise HTTPException(502, "Transcription service unavailable. Please type your request.")
    if not text:
        raise HTTPException(422, "Could not hear anything. Please try again.")
    clean, wake = voice.strip_wake_word(text)
    return {"text": clean, "wake_word_detected": wake}


@router.post("/voice/command")
def voice_command(body: VoiceCommandIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One turn of the voice assistant: create / update / status / cancel / confirm / 'help has arrived'."""
    result = flow(lambda: voice.handle(db, user, text=body.text, lat=body.lat, lng=body.lng, share_location=body.share_location,
                                       ctx=body.context.model_dump(exclude_none=True)), db)
    db.commit()
    return result
