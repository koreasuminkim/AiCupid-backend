import json
import base64
from uuid import uuid4
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.voice import speech_to_text_gemini, text_to_speech_openai
from services.agent import get_app_runnable
from live_bridge import run_live_session

router = APIRouter(prefix="/ws", tags=["websocket"])

@router.websocket("/quiz")
async def websocket_quiz_endpoint(websocket: WebSocket):
    await websocket.accept()
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

@router.websocket("/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await websocket.accept()
    await run_live_session(websocket)