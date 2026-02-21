from dotenv import load_dotenv

load_dotenv()

import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ai_agent import get_app_runnable
from ai_agent.api import router as ai_agent_router

# FastAPI 앱 먼저 생성 (퀴즈/LLM은 지연 로딩 → API 키 없어도 서버 기동 가능)
app = FastAPI()

app.include_router(ai_agent_router)


# --- 라우트: API 키 없이 바로 응답 ---

@app.get("/")
def read_root():
    return {"Hello": "LangGraph Quiz", "docs": "http://localhost:8000/docs"}


@app.get("/health")
async def health():
    """서버 상태 확인용 헬스체크 API"""
    return {"status": "ok", "service": "AiCupid-backend"}


@app.get("/api/hello")
async def hello(name: str = "Guest"):
    """간단한 인사 API - 쿼리: ?name=이름"""
    from datetime import datetime
    return {"message": f"Hello, {name}!", "timestamp": datetime.now().isoformat()}


@app.post("/invoke")
async def invoke(data: dict):
    """
    LangGraph 퀴즈 체인을 호출합니다. (GEMINI_API_KEY 필요)
    """
    try:
        runnable = get_app_runnable()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": f"퀴즈 엔진 초기화 실패 (GEMINI_API_KEY 확인): {e}"},
        )

    user_input = data.get("input")
    if not user_input:
        return JSONResponse(status_code=400, content={"error": "Input message is required"})

    current_state = data.get("state", {"messages": [], "question_id": 0, "score": 0})
    current_state["messages"] = current_state.get("messages", []) + [("user", user_input)]

    result = runnable.invoke(current_state)
    last_ai_message = ""
    for role, msg in reversed(result["messages"]):
        if role == "ai":
            last_ai_message = msg
            break
    return {"response": last_ai_message, "state": result}


# --- WebSocket: Gemini Live API (프론트 음성 청크 → Live API) ---

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """
    프론트에서 끊어서 보낸 음성 청크를 Gemini Live API로 스트리밍합니다.
    - 입력: binary (16-bit PCM, 16kHz, mono) 또는 JSON {"audio": "base64"}
    - 출력: JSON {"type": "audio", "data": "base64"} (24kHz) / {"type": "text", "text": "..."} / {"type": "done"}
    - 시스템 프롬프트: ai_agent.prompts (LangChain) 사용
    - 참고: https://ai.google.dev/gemini-api/docs/live
    """
    await websocket.accept()
    try:
        from live_bridge import run_live_session
        await run_live_session(websocket, system_instruction=None, use_langchain_prompt=True)
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# --- WebSocket: Google STT + LangGraph + ElevenLabs (기존) ---

@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    try:
        from google.cloud import speech
        from elevenlabs.client import ElevenLabs
        from elevenlabs import stream as elevenlabs_stream
    except Exception as e:
        await websocket.send_json({"type": "error", "text": f"의존성 로드 실패: {e}"})
        await websocket.close(code=1011, reason=str(e))
        return

    speech_client = speech.SpeechClient()
    elevenlabs_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
    streaming_config = speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="ko-KR",
        ),
        interim_results=True,
    )

    try:
        graph_state = {"messages": [], "question_id": 0, "score": 0}
        runnable = get_app_runnable()

        while True:
            stt_requests = (
                speech.StreamingRecognizeRequest(audio_content=chunk)
                async for chunk in websocket.iter_bytes()
            )
            stt_responses = speech_client.streaming_recognize(
                config=streaming_config, requests=stt_requests
            )

            transcript = ""
            for response in stt_responses:
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue
                if not result.is_final:
                    await websocket.send_json({"type": "interim_transcript", "text": result.alternatives[0].transcript})
                else:
                    transcript = result.alternatives[0].transcript
                    await websocket.send_json({"type": "final_transcript", "text": transcript})
                    break

            if not transcript:
                continue

            graph_state["messages"] = graph_state.get("messages", []) + [("user", transcript)]
            graph_result = runnable.invoke(graph_state)
            graph_state = graph_result

            ai_response_text = ""
            for role, msg in reversed(graph_result["messages"]):
                if role == "ai":
                    ai_response_text = msg
                    break
            if not ai_response_text:
                continue

            await websocket.send_json({"type": "ai_response_text", "text": ai_response_text})

            audio_stream = elevenlabs_client.generate(
                text=ai_response_text,
                model="eleven_multilingual_v2",
                stream=True,
            )
            for chunk in elevenlabs_stream(audio_stream):
                await websocket.send_bytes(chunk)
            await websocket.send_json({"type": "audio_stream_end"})

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"An error occurred: {e}")
        await websocket.close(code=1011, reason=str(e))
