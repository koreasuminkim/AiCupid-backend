import base64
import io
import json
import os
import random
import re
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
from app.models.four_choice_question import FourChoiceQuestion
from app.models.balance_game_question import BalanceGameQuestion
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


# ----- 심리 테스트 결과 분석: 음성 2개(대화 내역) + 세션 → 궁합 점수·텍스트·음성 -----


def _parse_score_and_result(llm_output: str) -> tuple[int, str]:
    """LLM 출력에서 점수와 결과 문단 파싱. 기본: 0~100, 전체를 result로."""
    text = (llm_output or "").strip()
    score = 0
    result = text
    # "SCORE: 85" 또는 "점수: 85" 등
    score_match = re.search(r"(?:SCORE|점수)\s*[:：]\s*(\d+)", text, re.IGNORECASE)
    if score_match:
        score = min(100, max(0, int(score_match.group(1))))
    # "RESULT:" 또는 "결과:" 이후를 결과 텍스트로
    result_match = re.search(r"(?:RESULT|결과)\s*[:：]\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if result_match:
        result = result_match.group(1).strip()
    else:
        # 점수 줄을 제거한 나머지를 결과로
        result = re.sub(r"(?i)(?:SCORE|점수)\s*[:：]\s*\d+\s*", "", text).strip() or text
    return score, result


@router.post("/psych-test-result")
async def psych_test_result(
    session_id: Annotated[str, Form(description="세션 ID")],
    file_1: Annotated[UploadFile, File(description="참가자 1 대화 내역 음성 파일")],
    file_2: Annotated[UploadFile, File(description="참가자 2 대화 내역 음성 파일")],
    db: Session = Depends(get_db),
):
    """
    세션 ID + 대화 내역 음성 파일 2개를 받아, 두 참가자의 심리 테스트 응답을 전사하고
    궁합 분석 결과(점수 + 텍스트)를 생성한 뒤, 결과 텍스트를 TTS로 음성까지 만들어
    점수·텍스트·음성을 함께 반환합니다.
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id는 필수입니다.")

    # 음성 2개 전사
    _, _, transcript_1 = await _read_audio_and_transcribe(file_1)
    _, _, transcript_2 = await _read_audio_and_transcribe(file_2)

    # 세션 대화 히스토리 (선택 컨텍스트)
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
    history_block = "\n".join(history_lines) if history_lines else "(없음)"

    from quiz_chain import get_llm

    system = (
        f"{AI_MC_SYSTEM_PROMPT.strip()}\n\n"
        "역할: 당신은 **MC**이자 **심리 테스트 분석가**입니다. "
        "두 참가자가 심리 테스트에 답한 내용(전사)을 바탕으로 **궁합 분석**을 한 뒤, "
        "다음 형식으로만 출력하세요.\n"
        "1) 첫 줄: SCORE: (0~100 사이 정수 하나)\n"
        "2) 둘째 줄부터: RESULT: (두 분의 궁합을 2~4문장으로 친절히 설명, 한국어)"
    )
    user_content = (
        "[참가자 1의 답변 전사]\n"
        f"{transcript_1 or '(없음)'}\n\n"
        "[참가자 2의 답변 전사]\n"
        f"{transcript_2 or '(없음)'}\n\n"
        "[이 세션의 지금까지 대화]\n"
        f"{history_block}\n\n"
        "위를 바탕으로 궁합 점수(0~100)와 결과 문단을 SCORE: / RESULT: 형식으로 출력하세요."
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_content),
    ]
    try:
        response = get_llm().invoke(messages)
        raw = (response.content if hasattr(response, "content") else str(response)).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    score, result_text = _parse_score_and_result(raw)

    # 결과 텍스트 → TTS 음성
    audio_b64, mime_type = _reply_and_tts(result_text)

    return {
        "score": score,
        "result_text": result_text,
        "audio": audio_b64,
        "mime_type": mime_type,
    }


# ----- 4지 선다 퀴즈 질문 생성: 세션 → 유저 interests/이름 기반 상대방 퀴즈, DB 저장 + 음성 -----


def _parse_four_choice(llm_output: str) -> tuple[str, str, str, str, str] | None:
    """LLM 출력에서 QUESTION, CORRECT, WRONG1, WRONG2, WRONG3 파싱. 실패 시 None."""
    text = (llm_output or "").strip()
    patterns = [
        (r"(?:QUESTION|질문)\s*[:：]\s*(.+?)(?=(?:CORRECT|정답)|$)", "q"),
        (r"(?:CORRECT|정답)\s*[:：]\s*(.+?)(?=(?:WRONG|오답)|\n\n|$)", "c"),
        (r"(?:WRONG1|오답1)\s*[:：]\s*(.+?)(?=(?:WRONG2|오답2)|\n|$)", "w1"),
        (r"(?:WRONG2|오답2)\s*[:：]\s*(.+?)(?=(?:WRONG3|오답3)|\n|$)", "w2"),
        (r"(?:WRONG3|오답3)\s*[:：]\s*(.+)", "w3"),
    ]
    found = {}
    for pat, key in patterns:
        m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if m:
            found[key] = m.group(1).strip()
    if len(found) == 5:
        return (found["q"], found["c"], found["w1"], found["w2"], found["w3"])
    return None


@router.post("/four-choice-quiz")
async def four_choice_quiz(
    session_id: Annotated[str, Form(description="세션 ID")],
    db: Session = Depends(get_db),
):
    """
    세션 ID로 두 유저를 조회한 뒤, 각자의 interests·이름을 활용해
    상대방에 대한 4지 선다 퀴즈 2개 생성(각 1개씩). 질문 ID 부여 후 DB 저장하고,
    질문 텍스트, 정답 포함 4가지 선택지, 상대방 이름 포함 TTS 음성을 프론트로 반환.
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
    user_id_1, user_id_2 = first_session.user_id_1, first_session.user_id_2

    users = db.query(User).filter(User.userId.in_([user_id_1, user_id_2])).all()
    if len(users) != 2:
        try:
            u1 = db.query(User).filter(User.id == int(user_id_1)).first()
            u2 = db.query(User).filter(User.id == int(user_id_2)).first()
            users = [u for u in (u1, u2) if u is not None]
        except (ValueError, TypeError):
            pass
    if len(users) == 2:
        if getattr(users[0], "userId", None) == user_id_1:
            user1, user2 = users[0], users[1]
        else:
            user1, user2 = users[1], users[0]
        name1 = getattr(user1, "name", "참가자1")
        name2 = getattr(user2, "name", "참가자2")
        interests1 = getattr(user1, "interests", []) or []
        interests2 = getattr(user2, "interests", []) or []
        interests1_str = ", ".join(str(x) for x in interests1) if isinstance(interests1, list) else str(interests1)
        interests2_str = ", ".join(str(x) for x in interests2) if isinstance(interests2, list) else str(interests2)
    else:
        name1, name2 = "참가자1", "참가자2"
        interests1_str = interests2_str = "일반"

    from quiz_chain import get_llm

    def generate_one_question(about_name: str, about_interests: str) -> tuple[str, str, str, str, str] | None:
        system = (
            "당신은 소개팅/미팅 MC입니다. 주어진 참가자(이름, 관심사)에 대한 **4지 선다 퀴즈**를 하나 만드세요. "
            "관심사를 활용해 그 사람을 맞히는 재미있는 질문으로. "
            "반드시 아래 형식으로만 출력하세요.\n"
            "QUESTION: (질문 원본 한 문장)\n"
            "CORRECT: (정답 한 개)\n"
            "WRONG1: (오답 1)\nWRONG2: (오답 2)\nWRONG3: (오답 3)"
        )
        user_content = f"참가자 이름: {about_name}\n관심사: {about_interests}\n\n위 참가자에 대한 4지 선다 퀴즈 하나를 QUESTION/CORRECT/WRONG1~3 형식으로 출력하세요."
        messages = [SystemMessage(content=system), HumanMessage(content=user_content)]
        try:
            response = get_llm().invoke(messages)
            raw = (response.content if hasattr(response, "content") else str(response)).strip()
            return _parse_four_choice(raw)
        except Exception:
            return None

    results = []
    # 퀴즈 1: user2에 대한 퀴즈 (user1이 풀 때 상대방 이름 = name2)
    parsed1 = generate_one_question(name2, interests2_str)
    if parsed1:
        q_id_1 = str(uuid.uuid4())
        q_text_1, correct_1, wrong1_1, wrong2_1, wrong3_1 = parsed1
        db.add(
            FourChoiceQuestion(
                question_id=q_id_1,
                session_id=session_id,
                question_text=q_text_1,
                correct_answer=correct_1,
                wrong_answer_1=wrong1_1,
                wrong_answer_2=wrong2_1,
                wrong_answer_3=wrong3_1,
                about_user_name=name2,
            )
        )
        db.commit()
        choices_1 = [{"text": correct_1, "is_correct": True}, {"text": wrong1_1, "is_correct": False}, {"text": wrong2_1, "is_correct": False}, {"text": wrong3_1, "is_correct": False}]
        random.shuffle(choices_1)
        tts_text_1 = f"{name2}에 대한 퀴즈입니다. {q_text_1}"
        audio_1, mime_1 = _reply_and_tts(tts_text_1)
        results.append({
            "question_id": q_id_1,
            "question_text": q_text_1,
            "choices": choices_1,
            "audio": audio_1,
            "mime_type": mime_1,
        })
    # 퀴즈 2: user1에 대한 퀴즈 (user2가 풀 때 상대방 이름 = name1)
    parsed2 = generate_one_question(name1, interests1_str)
    if parsed2:
        q_id_2 = str(uuid.uuid4())
        q_text_2, correct_2, wrong1_2, wrong2_2, wrong3_2 = parsed2
        db.add(
            FourChoiceQuestion(
                question_id=q_id_2,
                session_id=session_id,
                question_text=q_text_2,
                correct_answer=correct_2,
                wrong_answer_1=wrong1_2,
                wrong_answer_2=wrong2_2,
                wrong_answer_3=wrong3_2,
                about_user_name=name1,
            )
        )
        db.commit()
        choices_2 = [{"text": correct_2, "is_correct": True}, {"text": wrong1_2, "is_correct": False}, {"text": wrong2_2, "is_correct": False}, {"text": wrong3_2, "is_correct": False}]
        random.shuffle(choices_2)
        tts_text_2 = f"{name1}에 대한 퀴즈입니다. {q_text_2}"
        audio_2, mime_2 = _reply_and_tts(tts_text_2)
        results.append({
            "question_id": q_id_2,
            "question_text": q_text_2,
            "choices": choices_2,
            "audio": audio_2,
            "mime_type": mime_2,
        })

    if not results:
        raise HTTPException(status_code=502, detail="퀴즈 생성에 실패했습니다.")
    return {"questions": results}


# ----- 밸런스 게임 질문 생성: 세션 + 과거 대화 → 질문 3개(각 선택지 2개) + TTS 3개 -----


def _parse_balance_game_three(llm_output: str) -> list[tuple[str, str, str]] | None:
    """LLM 출력에서 Q1~Q3, 각 OPTION_A/B 파싱. 반환: [(question_text, option_a, option_b), ...] 최대 3개."""
    text = (llm_output or "").strip()
    # Q1 / Q2 / Q3 구간으로 나누기
    blocks = re.split(r"(?=Q[123]\s*[:：]|질문[123]\s*[:：])", text, flags=re.IGNORECASE)
    blocks = [b.strip() for b in blocks if b.strip() and (re.match(r"^(?:Q[123]|질문[123])\s*[:：]", b, re.I) or "OPTION_A" in b or "OPTION_B" in b)]
    if len(blocks) < 3:
        blocks = re.split(r"\n\n+", text)
    result = []
    for block in blocks[:3]:
        q_match = re.search(r"(?:Q[123]|질문[123])\s*[:：]\s*(.+?)(?=(?:OPTION_A|선택A|A\s*[:：])|$)", block, re.DOTALL | re.IGNORECASE)
        a_match = re.search(r"(?:OPTION_A|선택A|A)\s*[:：]\s*(.+?)(?=(?:OPTION_B|선택B|B\s*[:：])|$)", block, re.DOTALL | re.IGNORECASE)
        b_match = re.search(r"(?:OPTION_B|선택B|B)\s*[:：]\s*(.+)", block, re.DOTALL | re.IGNORECASE)
        if q_match and a_match and b_match:
            result.append(
                (
                    q_match.group(1).strip()[:500],
                    a_match.group(1).strip()[:200],
                    b_match.group(1).strip()[:200],
                )
            )
    return result if len(result) == 3 else None


@router.post("/balance-game-questions")
async def balance_game_questions(
    session_id: Annotated[str, Form(description="세션 ID")],
    conversation_audio: Annotated[UploadFile | None, File(description="추가 대화 내용 음성 파일 (선택)")] = None,
    db: Session = Depends(get_db),
):
    """
    세션 ID를 받고, 선택적으로 추가 대화 내용 음성 파일을 받습니다. 해당 세션의 예전 대화를 검색해 활용하고
    밸런스 게임 질문 3개를 생성합니다. 각 질문은 선택지 2개(A/B)이며,
    질문 3개를 읽는 보이스 3개를 함께 프론트로 보냅니다.
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id는 필수입니다.")

    # 예전 대화 내용 검색
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
    if conversation_audio:
        try:
            _, _, transcript = await _read_audio_and_transcribe(conversation_audio)
            if transcript and transcript.strip():
                history_block = history_block + "\n\n[추가 대화]\n" + transcript.strip()
        except HTTPException:
            raise
        except Exception:
            pass

    from quiz_chain import get_llm

    system = (
        "당신은 소개팅/미팅 MC입니다. **밸런스 게임** 질문 3개를 만드세요. "
        "각 질문은 'A vs B' 형태로 두 가지 중 하나를 고르는 재미있는 질문이어야 합니다. "
        "반드시 아래 형식으로만 출력하세요.\n\n"
        "Q1: (첫 번째 질문 문장, 예: 영화 볼 때 팝콘 vs 나초?)\n"
        "OPTION_A: (첫 번째 선택지)\nOPTION_B: (두 번째 선택지)\n\n"
        "Q2: (두 번째 질문)\nOPTION_A: ...\nOPTION_B: ...\n\n"
        "Q3: (세 번째 질문)\nOPTION_A: ...\nOPTION_B: ..."
    )
    user_content = (
        "[이 세션의 대화 내역]\n"
        f"{history_block}\n\n"
        "위 대화 맥락을 활용해 참가자들이 고르기 좋은 밸런스 게임 질문 3개를 Q1/OPTION_A/OPTION_B 형식으로 출력하세요."
    )
    messages = [SystemMessage(content=system), HumanMessage(content=user_content)]
    try:
        response = get_llm().invoke(messages)
        raw = (response.content if hasattr(response, "content") else str(response)).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    parsed = _parse_balance_game_three(raw)
    if not parsed or len(parsed) != 3:
        # 폴백: 한 줄씩 간단 파싱 시도
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        parsed_fallback = []
        i = 0
        while i < len(lines) and len(parsed_fallback) < 3:
            q = lines[i] if i < len(lines) else ""
            a = lines[i + 1] if i + 1 < len(lines) else ""
            b = lines[i + 2] if i + 2 < len(lines) else ""
            if q and (q.startswith("Q") or "질문" in q or "?" in q or "vs" in q) and a and b:
                parsed_fallback.append((q.split(":", 1)[-1].strip() if ":" in q else q, a.split(":", 1)[-1].strip() if ":" in a else a, b.split(":", 1)[-1].strip() if ":" in b else b))
                i += 3
            else:
                i += 1
        if len(parsed_fallback) == 3:
            parsed = parsed_fallback
        if not parsed or len(parsed) != 3:
            raise HTTPException(status_code=502, detail="밸런스 게임 질문 3개를 파싱하지 못했습니다.")

    results = []
    for idx, (q_text, opt_a, opt_b) in enumerate(parsed):
        q_id = str(uuid.uuid4())
        db.add(
            BalanceGameQuestion(
                question_id=q_id,
                session_id=session_id,
                question_text=q_text,
                option_a=opt_a,
                option_b=opt_b,
            )
        )
        db.commit()
        # 질문 읽는 TTS (예: "첫 번째. [질문 텍스트]")
        order = ["첫 번째", "두 번째", "세 번째"][idx]
        tts_sentence = f"{order}. {q_text}"
        audio_b64, mime_type = _reply_and_tts(tts_sentence)
        results.append({
            "question_id": q_id,
            "question_text": q_text,
            "option_a": opt_a,
            "option_b": opt_b,
            "audio": audio_b64,
            "mime_type": mime_type,
        })
    return {"questions": results}


# ----- 퀴즈 O/X 결과: 음성 + 퀴즈 ID + 세션 ID → 정답 여부 판정 -----


@router.post("/quiz-result")
async def quiz_result(
    file: Annotated[UploadFile, File(description="유저 음성 파일 (선택한 답)")],
    question_id: Annotated[str, Form(description="퀴즈 ID (four_choice_questions.question_id)")],
    session_id: Annotated[str, Form(description="세션 ID")],
    db: Session = Depends(get_db),
):
    """
    유저 음성 파일 + 퀴즈 ID + 세션 ID를 받아, 퀴즈 ID로 질문·정답을 조회하고
    음성을 전사한 뒤 정답 여부를 판정해 O/X로 반환합니다.
    """
    question_id = (question_id or "").strip()
    session_id = (session_id or "").strip()
    if not question_id:
        raise HTTPException(status_code=400, detail="question_id는 필수입니다.")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id는 필수입니다.")

    quiz = (
        db.query(FourChoiceQuestion)
        .filter(
            FourChoiceQuestion.question_id == question_id,
            FourChoiceQuestion.session_id == session_id,
        )
        .first()
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="해당 퀴즈를 찾을 수 없습니다.")

    _, _, user_answer = await _read_audio_and_transcribe(file)
    user_answer = (user_answer or "").strip()
    correct_answer = (quiz.correct_answer or "").strip()

    # 정답 여부: 전사 내용이 정답과 의미적으로 일치하면 O (LLM으로 판정)
    from quiz_chain import get_llm

    is_correct = False
    if user_answer and correct_answer:
        judge_prompt = (
            f"질문: {quiz.question_text}\n"
            f"정답: {correct_answer}\n"
            f"참가자가 말한 내용: {user_answer}\n\n"
            "참가자가 정답을 맞혔으면 O, 틀렸으면 X만 한 글자로 출력하세요. (동의어·줄임말도 정답으로 인정)"
        )
        try:
            response = get_llm().invoke([HumanMessage(content=judge_prompt)])
            out = (response.content if hasattr(response, "content") else str(response)).strip().upper()
            is_correct = out.startswith("O") and "X" not in out[:2]
        except Exception:
            # 폴백: 포함 여부로 판정
            is_correct = correct_answer in user_answer or user_answer in correct_answer
    result = "O" if is_correct else "X"

    return {
        "result": result,
        "question_text": quiz.question_text,
        "correct_answer": correct_answer,
        "user_answer": user_answer,
    }