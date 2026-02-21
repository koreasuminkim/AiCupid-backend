from dotenv import load_dotenv

load_dotenv()

import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import TypedDict, Annotated, List
import operator
import json

# FastAPI 앱 먼저 생성 (퀴즈/LLM은 지연 로딩 → API 키 없어도 서버 기동 가능)
app = FastAPI()

_app_runnable = None


def get_app_runnable():
    """Gemini/퀴즈 체인은 첫 사용 시 로드 (GEMINI_API_KEY 없어도 서버는 뜸)"""
    global _app_runnable
    if _app_runnable is not None:
        return _app_runnable

    from langgraph.graph import StateGraph, END
    from langchain_google_genai import ChatGoogleGenerativeAI
    from quiz_chain import QuizGrader, QuestionProvider, quiz_data, get_react_chain

    class AgentState(TypedDict):
        messages: Annotated[list, operator.add]
        question_id: int
        score: int
        next_action: str

    llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0)
    react_chain = get_react_chain()

    def router_node(state: AgentState):
        last_message = state["messages"][-1]
        action = "chat"
        if state["question_id"] < len(quiz_data):
            if len(state["messages"]) > 1 and state["messages"][-2][0] == "ai" and "질문" in state["messages"][-2][1]:
                action = "grade"
            else:
                action = "ask"
        else:
            action = "finish"
        if "퀴즈" in last_message[1] and "시작" in last_message[1]:
            action = "ask"
        print(f"Router decided action: {action}")
        return {"next_action": action}

    def grade_answer_node(state: AgentState):
        user_message = state["messages"][-1]
        user_answer = user_message[1]
        q_id = state["question_id"]
        grader = QuizGrader(user_answer=user_answer, question_id=q_id)
        is_correct = grader.grade()
        new_score = state["score"]
        if is_correct:
            new_score += 1
            response_message = f"정답입니다! 현재 점수: {new_score}"
        else:
            correct_answer = quiz_data[q_id]["answer"]
            response_message = f"아쉽네요. 정답은 '{correct_answer}'입니다. 현재 점수: {new_score}"
        next_q_id = q_id + 1
        return {
            "messages": [("ai", response_message)],
            "score": new_score,
            "question_id": next_q_id,
        }

    def ask_question_node(state: AgentState):
        q_id = state["question_id"]
        provider = QuestionProvider(question_id=q_id)
        question = provider.get_question()
        message = f"퀴즈 질문입니다: {question}" if q_id < len(quiz_data) else question
        return {"messages": [("ai", message)]}

    def chat_node(state: AgentState):
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    def decide_next_step(state: AgentState):
        return state["next_action"]

    workflow = StateGraph(AgentState)
    workflow.add_node("router", router_node)
    workflow.add_node("grade_answer", grade_answer_node)
    workflow.add_node("ask_question", ask_question_node)
    workflow.add_node("chat", chat_node)
    workflow.set_entry_point("router")
    workflow.add_conditional_edges(
        "router",
        decide_next_step,
        {"grade": "grade_answer", "ask": "ask_question", "chat": "chat", "finish": END},
    )
    workflow.add_edge("grade_answer", "router")
    workflow.add_edge("ask_question", "router")
    workflow.add_edge("chat", "router")

    _app_runnable = workflow.compile()
    return _app_runnable


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


# --- WebSocket: 첫 연결 시에만 speech/elevenlabs 로드 (키 없어도 서버는 뜸) ---

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
