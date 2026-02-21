from fastapi import APIRouter, File, UploadFile, HTTPException
from typing import Annotated
from audio_to_text_graph import build_audio_to_text_graph

router = APIRouter(tags=["voice"])

_AUDIO_TO_TEXT_RUNNABLE = None

def _get_audio_to_text_runnable():
    global _AUDIO_TO_TEXT_RUNNABLE
    if _AUDIO_TO_TEXT_RUNNABLE is None:
        _AUDIO_TO_TEXT_RUNNABLE = build_audio_to_text_graph().compile()
    return _AUDIO_TO_TEXT_RUNNABLE

AUDIO_MIME_TYPES = {
    "audio/wav", "audio/wave", "audio/x-wav", "audio/mpeg", 
    "audio/mp3", "audio/ogg", "audio/webm", "audio/flac", "audio/mp4",
}

@router.post("/audio-to-text")
async def audio_to_text(
    file: Annotated[UploadFile, File(description="음성 파일 (wav, mp3 등)")],
):
    mime_type = file.content_type.lower() if file.content_type else "audio/wav"
    
    try:
        audio_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {e}")

    runnable = _get_audio_to_text_runnable()
    state = {"audio_bytes": audio_bytes, "mime_type": mime_type, "text": "", "error": ""}
    result = runnable.invoke(state)

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])

    return {"text": result.get("text", "")}