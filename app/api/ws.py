import asyncio
import json
import base64
from uuid import uuid4
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.voice import speech_to_text_gemini, text_to_speech_openai
from services.agent import get_app_runnable
from ai_agent.live_context_graph import get_system_instruction_from_conversation_bytes
from live_bridge import run_live_session

router = APIRouter(prefix="/ws", tags=["websocket"])

async def _run_quiz_voice_loop(websocket: WebSocket):
    """음성 청크 수신 → STT → 퀴즈 에이전트 → TTS 응답 (공통 로직)."""
    session_id = websocket.query_params.get("session_id", str(uuid4()))
    config = {"configurable": {"thread_id": session_id}}
    runnable = get_app_runnable() 
    audio_chunks = []

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message:
                audio_chunks.append(message["bytes"])
            elif "text" in message:
                data = json.loads(message["text"])
                if data.get("type") == "speech_end" and audio_chunks:
                    raw_pcm = b"".join(audio_chunks)
                    audio_chunks = []

                    # 1. STT
                    transcript = await speech_to_text_gemini(raw_pcm)
                    print(f"[STT] {transcript}")
                    await websocket.send_json({"type": "final_transcript", "text": transcript})

                    # 2. Agent Invoke
                    result = await runnable.ainvoke({"messages": [("user", transcript)]}, config=config)
                    ai_text = result["messages"][-1][1] if result["messages"] else "죄송해요."
                    await websocket.send_json({"type": "ai_response_text", "text": ai_text})

                    # 3. TTS
                    audio_content = await text_to_speech_openai(ai_text)
                    await websocket.send_json({
                        "type": "audio",
                        "data": base64.b64encode(audio_content).decode("utf-8"),
                        "mime_type": "audio/wav"
                    })
    except WebSocketDisconnect:
        print(f"Disconnected: {session_id}")


@router.websocket("/quiz")
async def websocket_quiz_endpoint(websocket: WebSocket):
    await websocket.accept()
    await _run_quiz_voice_loop(websocket)


@router.websocket("/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    """/ws/quiz와 동일한 음성→STT→퀴즈→TTS 흐름 (호환용 별칭)."""
    await websocket.accept()
    await _run_quiz_voice_loop(websocket)


def _quiz_live_system_instruction(first_question: str, first_answer: str) -> str:
    """첫 질문을 이미 TTS로 보냈을 때, Live API용 시스템 지시."""
    return f"""당신은 AiCupid 퀴즈 진행자입니다. 음성으로만 답하세요.
첫 번째 질문 "{first_question}" (정답: {first_answer})는 이미 사용자에게 재생되었습니다.
이제 사용자의 음성을 듣고, 정답 여부를 알려주고 다음 질문을 하거나 퀴즈를 마무리하세요. 친근하게, 한국어로 말하세요."""


@router.websocket("/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        from quiz_chain import quiz_data
        if quiz_data:
            first_q = quiz_data[0]["question"]
            first_a = quiz_data[0]["answer"]
            # 첫 턴: 질문만 음성으로 전달 (STT 없이)
            audio_wav = await text_to_speech_openai(first_q)
            b64 = base64.b64encode(audio_wav).decode("utf-8")
            await websocket.send_json({
                "type": "first_question",
                "text": first_q,
                "audio": b64,
                "mime_type": "audio/wav",
            })
            instruction = _quiz_live_system_instruction(first_q, first_a)
            await run_live_session(websocket, system_instruction=instruction, use_langchain_prompt=False)
        else:
            await run_live_session(websocket)
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)})


def _parse_conversation_bytes_from_message(message: dict) -> bytes | None:
    """첫 메시지에서 대화 내역 바이트 추출. 바이트 프레임 또는 JSON(type: conversation_history) 지원."""
    if "bytes" in message and message["bytes"]:
        return bytes(message["bytes"])
    if "text" in message and message["text"]:
        try:
            data = json.loads(message["text"])
            if data.get("type") == "conversation_history":
                payload = data.get("data") or data.get("payload") or data.get("base64")
                if payload:
                    return base64.b64decode(payload)
                if "messages" in data:
                    return json.dumps(data["messages"]).encode("utf-8")
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return None


@router.websocket("/live/mc")
async def websocket_live_mc_endpoint(websocket: WebSocket):
    """
    클라이언트가 대화 내역을 바이트(또는 JSON)로 보내면, roles(ai, mc)와
    '어색한 대화를 풀어줘' 맥락을 담은 시스템 지시문으로 Live API 세션을 시작합니다.
    첫 메시지: binary(대화 JSON 바이트) 또는 text JSON {"type":"conversation_history","data":"<base64>"}
    이후: 기존과 동일하게 PCM 오디오 청크 전송 → Live API 음성 스트리밍.
    """
    await websocket.accept()
    try:
        # 첫 메시지로 대화 내역 수신 (바이트 파일 또는 JSON)
        raw_bytes: bytes | None = None
        try:
            first = await asyncio.wait_for(websocket.receive(), timeout=10.0)
            raw_bytes = _parse_conversation_bytes_from_message(first)
        except asyncio.TimeoutError:
            pass

        if raw_bytes:
            instruction = await asyncio.get_event_loop().run_in_executor(
                None, get_system_instruction_from_conversation_bytes, raw_bytes
            )
            await run_live_session(websocket, system_instruction=instruction, use_langchain_prompt=False)
        else:
            # 대화 내역 없이 연결된 경우: 기본 AI MC 지시문만 적용
            from ai_agent.prompts import AI_MC_SYSTEM_PROMPT
            instruction = (
                f"{AI_MC_SYSTEM_PROMPT}\n\n"
                "역할(roles): 당신은 **ai**이자 **mc**입니다. "
                "소개팅/미팅 상황을 이끄며, 어색한 대화를 자연스럽게 풀어 주세요. 음성으로 답하세요."
            )
            await run_live_session(websocket, system_instruction=instruction, use_langchain_prompt=False)
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)})