import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from typing import TypedDict, Annotated, List
import operator
import json

from quiz_chain import QuizGrader, QuestionProvider, quiz_data, get_react_chain

# .env 파일에서 환경 변수 로드
load_dotenv()

# --- LangGraph 상태 정의 ---
class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    question_id: int
    score: int
    next_action: str  # "grade", "ask", "chat", "finish"

# --- LLM 및 도구 초기화 ---
llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0)
react_chain = get_react_chain()

# --- LangGraph 노드 함수 정의 ---

# 1. 라우터 노드: 다음에 수행할 작업을 결정
def router_node(state: AgentState):
    """사용자 입력과 현재 상태를 기반으로 다음 행동을 결정합니다."""
    last_message = state["messages"][-1]
    
    # react_chain을 호출하여 LLM이 다음 행동을 결정하도록 함
    # 실제로는 LLM이 JSON 형식의 도구 호출을 반환하도록 유도해야 함
    # 여기서는 개념을 단순화하여 규칙 기반으로 처리
    
    action = "chat" # 기본값
    if state["question_id"] < len(quiz_data):
        # 퀴즈가 진행 중일 때
        # 사용자가 답변을 한 것인지, 아니면 다른 말을 한 것인지 판단 필요
        # 여기서는 일단 질문 다음엔 무조건 채점한다고 가정
        if len(state["messages"]) > 1 and state["messages"][-2][0] == 'ai' and "질문" in state["messages"][-2][1]:
             action = "grade"
        else:
             action = "ask"
    else:
        action = "finish"

    if "퀴즈" in last_message[1] and "시작" in last_message[1]:
        action = "ask"

    print(f"Router decided action: {action}")
    return {"next_action": action}

# 2. 답변 채점 노드
def grade_answer_node(state: AgentState):
    """사용자의 답변을 채점하고 점수를 업데이트합니다."""
    user_message = state["messages"][-1]
    user_answer = user_message[1]
    q_id = state["question_id"]

    grader = QuizGrader(user_answer=user_answer, question_id=q_id)
    is_correct = grader.grade()
    
    new_score = state["score"]
    response_message = ""
    if is_correct:
        new_score += 1
        response_message = f"정답입니다! 현재 점수: {new_score}"
    else:
        correct_answer = quiz_data[q_id]["answer"]
        response_message = f"아쉽네요. 정답은 '{correct_answer}'입니다. 현재 점수: {new_score}"
        
    # 다음 질문으로 넘어가기 위해 question_id 증가
    next_q_id = q_id + 1
    
    return {
        "messages": [("ai", response_message)],
        "score": new_score,
        "question_id": next_q_id
    }

# 3. 질문 출제 노드
def ask_question_node(state: AgentState):
    """다음 퀴즈 질문을 제공합니다."""
    q_id = state["question_id"]
    provider = QuestionProvider(question_id=q_id)
    question = provider.get_question()
    
    message = f"퀴즈 질문입니다: {question}" if q_id < len(quiz_data) else question
    
    return {"messages": [("ai", message)]}

# 4. 일반 대화 노드
def chat_node(state: AgentState):
    """퀴즈와 관련 없는 일반 대화를 처리합니다."""
    response = llm.invoke(state['messages'])
    return {"messages": [response]}

# --- LangGraph 워크플로우 정의 ---
workflow = StateGraph(AgentState)

workflow.add_node("router", router_node)
workflow.add_node("grade_answer", grade_answer_node)
workflow.add_node("ask_question", ask_question_node)
workflow.add_node("chat", chat_node)

workflow.set_entry_point("router")

# 조건부 엣지 설정
def decide_next_step(state: AgentState):
    return state["next_action"]

workflow.add_conditional_edges(
    "router",
    decide_next_step,
    {
        "grade": "grade_answer",
        "ask": "ask_question",
        "chat": "chat",
        "finish": END,
    },
)

# 각 행동 후에는 다시 라우터로 돌아가 다음 행동을 결정
workflow.add_edge("grade_answer", "router")
workflow.add_edge("ask_question", "router")
workflow.add_edge("chat", "router")


# 그래프 컴파일
app_runnable = workflow.compile()

# FastAPI 앱 생성
app = FastAPI()

@app.post("/invoke")
async def invoke(data: dict):
    """
    LangGraph 퀴즈 체인을 호출합니다.
    Request Body:
    {
        "input": "Your message here",
        "state": {
            "messages": [("user", "퀴즈 시작")],
            "question_id": 0,
            "score": 0
        }
    }
    """
    user_input = data.get("input")
    if not user_input:
        return {"error": "Input message is required"}, 400
    
    current_state = data.get("state", {"messages": [], "question_id": 0, "score": 0})
    current_state["messages"] = current_state.get("messages", []) + [("user", user_input)]

    # LangGraph 실행
    result = app_runnable.invoke(current_state)
    
    # 마지막 AI 메시지만 추출하여 응답
    last_ai_message = ""
    for role, msg in reversed(result['messages']):
        if role == 'ai':
            last_ai_message = msg
            break
            
    return {"response": last_ai_message, "state": result}


# ... (기존 import 구문들) ...
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.cloud import speech
from elevenlabs.client import ElevenLabs
from elevenlabs import stream as elevenlabs_stream

# ... (기존 LangGraph 및 FastAPI 앱 설정 코드) ...

# --- ElevenLabs 및 Google STT 클라이언트 초기화 ---
elevenlabs_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
speech_client = speech.SpeechClient()

# --- WebSocket을 통한 실시간 음성 처리 ---

@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Google STT 스트리밍 설정
    streaming_config = speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="ko-KR",
        ),
        interim_results=True,
    )

    try:
        # LangGraph 상태 초기화
        graph_state = {"messages": [], "question_id": 0, "score": 0}

        while True:
            # 1. 클라이언트로부터 음성 데이터 수신 및 STT 처리
            stt_requests = (
                speech.StreamingRecognizeRequest(audio_content=chunk)
                async for chunk in websocket.iter_bytes()
            )
            
            # Google STT API로 스트리밍 요청
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

                # 중간 결과는 클라이언트로 보내 실시간 자막처럼 보여줄 수 있음
                if not result.is_final:
                    await websocket.send_json({"type": "interim_transcript", "text": result.alternatives[0].transcript})
                else:
                    # 최종 결과가 나오면 전체 문장을 구성
                    transcript = result.alternatives[0].transcript
                    await websocket.send_json({"type": "final_transcript", "text": transcript})
                    break # 한 문장이 완성되면 STT 스트림 중지

            if not transcript:
                continue

            # 2. STT 변환 텍스트로 LangGraph 체인 호출
            graph_state["messages"] = graph_state.get("messages", []) + [("user", transcript)]
            graph_result = app_runnable.invoke(graph_state)
            graph_state = graph_result # 다음 요청을 위해 상태 업데이트

            # LangGraph의 마지막 AI 응답 추출
            ai_response_text = ""
            for role, msg in reversed(graph_result['messages']):
                if role == 'ai':
                    ai_response_text = msg
                    break
            
            if not ai_response_text:
                continue

            await websocket.send_json({"type": "ai_response_text", "text": ai_response_text})

            # 3. LLM 응답 텍스트를 ElevenLabs TTS로 스트리밍하여 클라이언트로 전송
            audio_stream = elevenlabs_client.generate(
                text=ai_response_text,
                model="eleven_multilingual_v2", # 한국어 지원 모델
                stream=True
            )
            
            # 오디오 청크를 클라이언트로 스트리밍
            for chunk in elevenlabs_stream(audio_stream):
                await websocket.send_bytes(chunk)
            
            # 스트리밍 종료를 알리는 메시지
            await websocket.send_json({"type": "audio_stream_end"})


    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"An error occurred: {e}")
        await websocket.close(code=1011, reason=str(e))


@app.get("/")
def read_root():
    return {"Hello": "LangGraph Quiz"}
