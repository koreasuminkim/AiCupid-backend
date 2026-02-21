import base64
import io
import json
import os
import uuid
import wave
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from langchain_core.messages import HumanMessage, SystemMessage

from app.database import get_db
from app.models.user import User
from app.models.voice_session import VoiceSession
from app.models.voice_conversation_turn import VoiceConversationTurn
from ai_agent.prompts import AI_MC_SYSTEM_PROMPT
from ai_agent.live_context_graph import get_live_context_graph

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


def _gemini_audio_to_transcript(audio_bytes: bytes, mime_type: str) -> str:
    """
    Gemini 멀티모달 API: 오디오 → 유저 발화 전사(한 줄). 답변 생성은 live_context_graph에서 동일하게 수행.
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not set")

    system = (
        "위 음성을 듣고, 화자가 한 말을 **한 줄**로만 전사(한국어)하세요. "
        "따옴표·설명 없이 말 내용만 출력하세요."
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


async def _read_audio_and_transcribe(
    file: UploadFile,
) -> tuple[bytes, str, str]:
    """공통: 파일 검증 후 바이트·mime_type·전사 텍스트 반환."""
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
        user_transcript = _gemini_audio_to_transcript(audio_bytes, mime_type)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return audio_bytes, mime_type, user_transcript


def _reply_and_tts(reply: str) -> tuple[str, str]:
    """reply 텍스트 → TTS 후 base64 WAV, mime_type 반환."""
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
            pass
    return audio_b64, "audio/wav" if audio_b64 else None


# ----- 첫 번째 대화: 세션 ID 생성, STT+AI 응답 DB 저장, session_id 포함 응답 -----


@router.post("/first-conversation")
async def first_conversation(
    file: Annotated[UploadFile, File(description="음성 파일 (wav, mp3 등)")],
    user_id_1: Annotated[str, Form(description="참가 유저 ID 1")],
    user_id_2: Annotated[str, Form(description="참가 유저 ID 2")],
    db: Session = Depends(get_db),
):
    """
    첫 번째 대화. 세션 ID를 생성하고, STT 결과(유저 발화)와 AI 응답 텍스트를 DB에 저장한 뒤
    session_id와 함께 응답을 반환합니다.
    """
    session_id = str(uuid.uuid4())
    # 세션 등록 (유저 2명)
    db.add(
        VoiceSession(
            session_id=session_id,
            user_id_1=user_id_1,
            user_id_2=user_id_2,
        )
    )
    db.commit()

    _, _, user_transcript = await _read_audio_and_transcribe(file)
    # 대화는 이번 유저 발화 하나뿐
    messages = [{"role": "user", "content": user_transcript or ""}]
    conversation_bytes = json.dumps(messages, ensure_ascii=False).encode("utf-8")
    graph = get_live_context_graph()
    out = graph.invoke({"raw_bytes": conversation_bytes})
    reply = (out.get("reply") or "").strip()
    system_instruction = out.get("system_instruction") or AI_MC_SYSTEM_PROMPT

    # DB에 STT 결과 + AI 응답 저장
    db.add(
        VoiceConversationTurn(
            session_id=session_id,
            user_text=user_transcript or None,
            assistant_reply=reply,
        )
    )
    db.commit()

    audio_b64, mime_type = _reply_and_tts(reply)
    return {
        "session_id": session_id,
        "reply": reply,
        "system_instruction": system_instruction,
        "audio": audio_b64,
        "mime_type": mime_type,
    }


# ----- 이어지는 대화: 전체 히스토리 로드 후 AI에 전달, 응답만 반환 -----


@router.post("/continue-conversation")
async def continue_conversation(
    file: Annotated[UploadFile, File(description="음성 파일 (wav, mp3 등)")],
    session_id: Annotated[str, Form(description="세션 ID (첫 대화 응답에서 받은 값)")],
    db: Session = Depends(get_db),
):
    """
    두 번째 이후 대화. 반드시 해당 세션의 대화 히스토리 전부를 로드해 AI에 넣고,
    이번 턴만 저장한 뒤 응답만 반환합니다. (session_id는 요청에서 받음)
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id는 필수입니다.")

    first_session = (
        db.query(VoiceSession)
        .filter(VoiceSession.session_id == session_id)
        .order_by(VoiceSession.created_at)
        .first()
    )
    if not first_session:
        raise HTTPException(status_code=400, detail="해당 session_id를 찾을 수 없습니다.")

    _, _, user_transcript = await _read_audio_and_transcribe(file)

    # 해당 세션 대화 히스토리 전부 로드
    turns = (
        db.query(VoiceConversationTurn)
        .filter(VoiceConversationTurn.session_id == session_id)
        .order_by(VoiceConversationTurn.created_at)
        .all()
    )
    conversation: list[tuple[str, str]] = []
    for t in turns:
        if t.user_text:
            conversation.append(("user", t.user_text))
        conversation.append(("ai", t.assistant_reply or ""))
    conversation.append(("user", user_transcript or ""))

    # 전체 히스토리로 그래프 호출
    messages = [{"role": "user" if r == "user" else "ai", "content": c} for r, c in conversation]
    conversation_bytes = json.dumps(messages, ensure_ascii=False).encode("utf-8")
    graph = get_live_context_graph()
    out = graph.invoke({"raw_bytes": conversation_bytes})
    reply = (out.get("reply") or "").strip()
    system_instruction = out.get("system_instruction") or AI_MC_SYSTEM_PROMPT

    # 이번 턴만 DB 저장
    db.add(
        VoiceConversationTurn(
            session_id=session_id,
            user_text=user_transcript or None,
            assistant_reply=reply,
        )
    )
    db.commit()

    audio_b64, mime_type = _reply_and_tts(reply)
    return {
        "reply": reply,
        "system_instruction": system_instruction,
        "audio": audio_b64,
        "mime_type": mime_type,
    }


# ----- 심리 테스트 질문 생성: 세션 기반 유저 정보 + 대화 히스토리 컨텍스트, MC 역할로 질문 1개 + 음성 -----


def _user_summary(u: User) -> str:
    """프롬프트용 유저 요약 (비밀번호 등 제외)."""
    interests = getattr(u, "interests", None)
    if isinstance(interests, list):
        interests_str = ", ".join(str(x) for x in interests)
    else:
        interests_str = str(interests) if interests else ""
    return (
        f"이름={getattr(u, 'name', '')}, 성별={getattr(u, 'gender', '')}, 나이={getattr(u, 'age', '')}, "
        f"관심사=[{interests_str}], MBTI={getattr(u, 'mbti', '') or '-'}, 소개={getattr(u, 'bio', '') or '-'}"
    )


@router.post("/psych-test")
async def psych_test(
    file: Annotated[UploadFile, File(description="음성 파일 (wav, mp3 등)")],
    session_id: Annotated[str, Form(description="세션 ID")],
    db: Session = Depends(get_db),
):
    """
    음성 파일 + 세션 ID 받아서, 해당 세션의 두 유저 정보와 과거 대화 전체를 컨텍스트로 넣고
    MC 역할로 심리 테스트 질문 하나를 제작. 질문 텍스트와 TTS 음성을 함께 반환.
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id는 필수입니다.")

    # 세션에서 user_id 두 개 조회
    first_session = (
        db.query(VoiceSession)
        .filter(VoiceSession.session_id == session_id)
        .order_by(VoiceSession.created_at)
        .first()
    )
    if not first_session:
        raise HTTPException(status_code=400, detail="해당 session_id를 찾을 수 없습니다.")
    user_id_1, user_id_2 = first_session.user_id_1, first_session.user_id_2

    # 유저 테이블에서 두 명 정보 조회 (userId 기준). 없으면 무시하고 질문만 생성
    users = db.query(User).filter(User.userId.in_([user_id_1, user_id_2])).all()
    if len(users) != 2:
        try:
            u1 = db.query(User).filter(User.id == int(user_id_1)).first()
            u2 = db.query(User).filter(User.id == int(user_id_2)).first()
            users = [u for u in (u1, u2) if u is not None]
        except (ValueError, TypeError):
            pass
    if len(users) == 2:
        user1_summary = _user_summary(users[0])
        user2_summary = _user_summary(users[1])
    else:
        user1_summary = "(참가자 프로필 없음)"
        user2_summary = "(참가자 프로필 없음)"

    # 세션 기준 과거 대화 전체
    turns = (
        db.query(VoiceConversationTurn)
        .filter(VoiceConversationTurn.session_id == session_id)
        .order_by(VoiceConversationTurn.created_at)
        .all()
    )
    history_lines = []
    for t in turns:
        if t.user_text:
            history_lines.append(f"- user: {t.user_text}")
        history_lines.append(f"- ai: {t.assistant_reply or ''}")
    history_block = "\n".join(history_lines) if history_lines else "(아직 대화 없음)"

    # 음성 파일 → 전사 (최근 발화 컨텍스트)
    _, _, recent_transcript = await _read_audio_and_transcribe(file)

    # MC 역할 + 유저 정보 + 대화 히스토리 + 최근 발화 → 심리 테스트 질문 1개 생성
    system = (
        f"{AI_MC_SYSTEM_PROMPT.strip()}\n\n"
        "역할: 당신은 **MC**이며, 소개팅/미팅에서 참가자들에게 **심리 테스트 질문**을 하나 제작합니다. "
        "참가자 두 명의 프로필과 지금까지의 대화, 그리고 방금 전사된 발화를 참고해 "
        "분위기에 맞는 심리 테스트 질문 **한 문장**만 출력하세요. 따옴표·설명 없이 질문만 출력하세요. 한국어로 하세요."
    )
    user_content = (
        "[참가자 1]\n"
        f"{user1_summary}\n\n"
        "[참가자 2]\n"
        f"{user2_summary}\n\n"
        "[지금까지의 대화]\n"
        f"{history_block}\n\n"
        "[방금 전사된 발화]\n"
        f"{recent_transcript or '(없음)'}\n\n"
        "위 정보를 바탕으로 MC가 할 심리 테스트 질문 한 문장만 작성하세요."
    )
    from quiz_chain import get_llm

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_content),
    ]
    try:
        response = get_llm().invoke(messages)
        question = (response.content if hasattr(response, "content") else str(response)).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # 질문 텍스트 → TTS 음성
    audio_b64, mime_type = _reply_and_tts(question)

    return {
        "question": question,
        "audio": audio_b64,
        "mime_type": mime_type,
    }