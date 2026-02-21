import json
import base64
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import JSONResponse
from uuid import uuid4
from typing import Optional

from services.agent import get_app_runnable
from services.voice import speech_to_text_gemini, text_to_speech_openai
from services.s3_service import upload_file_to_s3

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "LangGraph Quiz", "docs": "http://localhost:8000/docs"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "AiCupid-backend"}

@app.get("/api/hello")
async def hello(name: str = "Guest"):
    return {"message": f"Hello, {name}!", "timestamp": datetime.now().isoformat()}

@app.post("/invoke")
async def invoke(data: dict):
    try:
        runnable = get_app_runnable()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": f"퀴즈 엔진 초기화 실패: {e}"},
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
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
                    sample_rate = int(data.get("sample_rate", 16000))
                    raw_pcm = b"".join(audio_chunks)
                    audio_chunks = [] # 청크 초기화
                    
                    # 1. STT
                    transcript = await speech_to_text_gemini(raw_pcm, sample_rate)
                    await websocket.send_json({"type": "final_transcript", "text": transcript})

                    # 2. Agent 호출 (LangGraph)
                    # 메시지가 비어있을 경우를 대비한 안전한 호출
                    result = runnable.invoke({"messages": [("user", transcript)]}, config=config)
                    
                    # 3. AI 답변 추출 (안전한 방식)
                    ai_text = ""
                    for role, msg in reversed(result["messages"]):
                        if role == "ai":
                            ai_text = msg.content if hasattr(msg, 'content') else str(msg)
                            break
                    
                    if not ai_text: ai_text = "죄송해요, 이해하지 못했어요."
                    
                    await websocket.send_json({"type": "ai_response_text", "text": ai_text})

                    # 4. TTS (OpenAI TTS)
                    audio_content = await text_to_speech_openai(ai_text) 

                    # 중복되는 send_bytes는 삭제하고, JSON 규격에만 맞춰서 보냅니다.
                    await websocket.send_json({
                        "type": "audio",
                        "data": base64.b64encode(audio_content).decode("utf-8"),
                        "mime_type": "audio/wav" # 문규격에 맞춰 wav로 명시
                    })
    except WebSocketDisconnect:
        print(f"Client disconnected: {session_id}")
    except Exception as e:
        print(f"Error: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})

@app.post("/upload-profile-image/")
async def create_upload_file(file: UploadFile = File(...)):
    """
    프로필 이미지를 S3에 업로드하고 이미지 URL을 반환합니다.
    """
    if not file:
        return {"message": "No upload file sent"}
    
    # 실제 프로덕션에서는 파일 이름을 고유하게 만드는 것이 좋습니다.
    # 예: object_name = f"profile_images/{uuid4()}-{file.filename}"
    
    file_url = upload_file_to_s3(file, file.filename)

    if file_url:
        return {"message": "File uploaded successfully", "file_url": file_url}
    else:
        return JSONResponse(status_code=500, content={"message": "File upload failed"})