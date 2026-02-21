import base64
import io
import os
import wave
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from ai_agent.prompts import AI_MC_SYSTEM_PROMPT

router = APIRouter(tags=["voice"])

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

# Gemini TTS 출력: 24kHz, 16bit, mono PCM
TTS_SAMPLE_RATE = 24000


def _pcm_to_wav_bytes(pcm: bytes, rate: int = TTS_SAMPLE_RATE) -> bytes:
    """16bit mono PCM → WAV 바이트."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _gemini_text_to_speech(text: str) -> bytes:
    """
    Gemini TTS: 텍스트 → 음성 PCM (24kHz). 한국어 등 자동 감지.
    """
    if not text.strip():
        return b""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text.strip(),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore"),
                )
            ),
        ),
    )
    parts = getattr(response.candidates[0].content, "parts", None) or []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            data = inline.data
            if isinstance(data, bytes):
                return data
    return b""


def _gemini_audio_to_reply(audio_bytes: bytes, mime_type: str) -> str:
    """
    Gemini 멀티모달 API: 오디오를 직접 넣고 STT 없이 MC 답변 한 번에 생성.
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not set")

    system = (
        f"{AI_MC_SYSTEM_PROMPT.strip()}\n\n"
        "역할(roles): 당신은 **ai**이자 **mc**입니다. "
        "위 음성을 듣고, MC로서 참가자에게 할 한 문장(인사·질문·말)만 짧게 답해 주세요. "
        "따옴표나 설명 없이 말만 출력하세요. 한국어로 답하세요."
    )
    try:
        part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    except (AttributeError, TypeError):
        blob = types.Blob(data=audio_bytes, mime_type=mime_type)
        part = types.Part(inline_data=blob)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[part],
        config=types.GenerateContentConfig(system_instruction=system),
    )
    return (response.text or "").strip()


@router.post("/audio-to-text")
async def audio_to_text(
    file: Annotated[UploadFile, File(description="음성 파일 (wav, mp3 등)")],
):
    """
    음성 파일 업로드 → Gemini 멀티모달(MC 답변 텍스트) → Gemini TTS(음성 변환).
    응답: reply(텍스트), system_instruction, audio(base64 WAV), mime_type.
    """
    mime_type = (file.content_type or "audio/wav").strip().lower()
    if mime_type not in AUDIO_MIME_TYPES and not mime_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 오디오 타입: {mime_type}")
    try:
        audio_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {e}")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="오디오 데이터가 비어 있습니다.")

    try:
        reply = _gemini_audio_to_reply(audio_bytes, mime_type)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # 텍스트 답변을 Gemini TTS로 음성 변환 (POST 응답에 음성 포함)
    audio_b64 = ""
    if reply:
        try:
            pcm = _gemini_text_to_speech(reply)
            if pcm:
                wav_bytes = _pcm_to_wav_bytes(pcm)
                audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
        except HTTPException:
            raise
        except Exception:
            pass  # TTS 실패해도 reply, system_instruction은 반환

    system_instruction = (
        f"{AI_MC_SYSTEM_PROMPT.strip()}\n\n"
        "역할(roles): 당신은 **ai**이자 **mc**입니다. "
        "소개팅/미팅 상황을 이끄며, 어색한 대화를 자연스럽게 풀어 주세요."
    )
    return {
        "reply": reply,
        "system_instruction": system_instruction,
        "audio": audio_b64,
        "mime_type": "audio/wav" if audio_b64 else None,
    }