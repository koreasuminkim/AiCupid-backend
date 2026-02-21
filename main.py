from dotenv import load_dotenv

load_dotenv()

import os
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from audio_to_text_graph import build_audio_to_text_graph

app = FastAPI(
    title="AiCupid Backend API",
    description="음성 파일을 텍스트로 변환하는 API (Gemini + LangGraph).",
)


@app.get("/")
def read_root():
    return {"service": "AiCupid-backend", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "AiCupid-backend"}


# --- 음성 → 텍스트 (LangGraph + Gemini) ---

_AUDIO_TO_TEXT_RUNNABLE = None


def _get_audio_to_text_runnable():
    global _AUDIO_TO_TEXT_RUNNABLE
    if _AUDIO_TO_TEXT_RUNNABLE is None:
        _AUDIO_TO_TEXT_RUNNABLE = build_audio_to_text_graph().compile()
    return _AUDIO_TO_TEXT_RUNNABLE


# 업로드 허용 MIME (Gemini 지원 형식)
AUDIO_MIME_TYPES = {
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/webm",
    "audio/flac",
    "audio/mp4",
}


@app.post("/api/audio-to-text")
async def audio_to_text(
    file: Annotated[UploadFile, File(description="음성 파일 (wav, mp3, ogg, webm, flac 등)")],
):
    """
    음성 파일을 업로드하면 Gemini로 텍스트로 변환해 반환합니다.
    LangGraph로 변환 파이프라인을 구성합니다.
    """
    if not file.content_type or file.content_type.lower() not in AUDIO_MIME_TYPES:
        # content_type이 비어 있거나 목록에 없으면 파일 확장자로 추정
        name = (file.filename or "").lower()
        if not any(name.endswith(ext) for ext in (".wav", ".mp3", ".ogg", ".webm", ".flac", ".m4a", ".mp4")):
            raise HTTPException(
                status_code=400,
                detail=f"지원 형식: {', '.join(sorted(AUDIO_MIME_TYPES))}. filename 또는 Content-Type 필요.",
            )
        mime_type = "audio/wav"
        if name.endswith(".mp3") or name.endswith(".mpeg"):
            mime_type = "audio/mpeg"
        elif name.endswith(".ogg"):
            mime_type = "audio/ogg"
        elif name.endswith(".webm"):
            mime_type = "audio/webm"
        elif name.endswith(".flac"):
            mime_type = "audio/flac"
        elif name.endswith(".mp4") or name.endswith(".m4a"):
            mime_type = "audio/mp4"
    else:
        mime_type = file.content_type.lower()

    try:
        audio_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {e}")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    try:
        runnable = _get_audio_to_text_runnable()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"엔진 초기화 실패 (GEMINI_API_KEY 확인): {e}")

    state = {
        "audio_bytes": audio_bytes,
        "mime_type": mime_type,
        "text": "",
        "error": "",
    }
    result = runnable.invoke(state)

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])

    return {"text": result.get("text", "")}
