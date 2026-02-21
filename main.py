import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from typing import TypedDict, Annotated, List, Dict
import operator
import json

from google.cloud import speech
from elevenlabs.client import ElevenLabs
from elevenlabs import stream as elevenlabs_stream

# 기존 체인 및 새로 추가된 체인 import
from quiz_chain import QuestionProvider as QuizQuestionProvider, QuizGrader
from psych_test_chain import TestQuestionGenerator, TestResultAnalyzer

# .env 파일에서 환경 변수 로드
load_dotenv()

# --- LangGraph 상태 정의 ---
class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    next_action: str

    # 퀴즈 상태
    quiz_question: str
    quiz_answer: str
    quiz_score: int

    # 심리테스트 상태
    test_questions: List[str]
    test_answers: List[Dict[str, str]]
    current_test_question_index: int
    waiting_for: str # 'p1' 또는 'p2'의 답변을 기다림


# --- LLM 및 클라이언트 초기화 ---
llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0.7)
elevenlabs_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
speech_client = speech.SpeechClient()


# --- LangGraph 노드 함수 정의 ---

# 1. 메인 라우터 노드
def router_node(state: AgentState):
    """사용자 입력과 현재 상태를 기반으로 다음 행동을 결정합니다."""
    last_message_text = state["messages"][-1][1]
    
    # 심리테스트가 진행 중인 경우
    if state.get("test_questions") and len(state["test_questions"]) > 0:
        return {"next_action": "receive_test_answer"}

    # 퀴즈가 진행 중인 경우
    if state.get("quiz_question"):
        return {"next_action": "grade_quiz_answer"}

    # 새로운 작업 시작
    if "심리테스트" in last_message_text:
        return {"next_action": "start_psych_test"}
    if "퀴즈" in last_message_text:
        return {"next_action": "ask_quiz_question"}
    
    return {"next_action": "chat"}

# --- 퀴즈 관련 노드들 ---
def ask_quiz_question_node(state: AgentState):
    """LLM을 통해 새로운 퀴즈 질문을 생성하고 제공합니다."""
    provider = QuizQuestionProvider(history=state["messages"])
    new_quiz = provider.get_question()
    return {
        "messages": [("ai", f"퀴즈 질문입니다: {new_quiz['question']}")],
        "quiz_question": new_quiz['question'],
        "quiz_answer": new_quiz['answer']
    }

def grade_quiz_answer_node(state: AgentState):
    """퀴즈 답변을 채점합니다."""
    user_answer = state["messages"][-1][1]
    grader = QuizGrader(user_answer=user_answer, question=state["quiz_question"], correct_answer=state["quiz_answer"])
    is_correct = grader.grade()
    
    new_score = state["quiz_score"]
    if is_correct:
        new_score += 1
        response_message = f"정답입니다! 현재 점수: {new_score}점"
    else:
        response_message = f"아쉽네요. 정답은 '{state['quiz_answer']}'였습니다. 현재 점수: {new_score}점"
        
    return {
        "messages": [("ai", response_message)],
        "quiz_score": new_score,
        "quiz_question": "", # 상태 초기화
        "quiz_answer": "",
    }

# --- 심리테스트 관련 노드들 ---
def start_test_node(state: AgentState):
    """심리테스트를 시작하고 첫 질문을 던집니다."""
    generator = TestQuestionGenerator(history=state["messages"])
    questions = generator.generate_questions()
    
    # 상태 초기화 및 첫 질문 설정
    initial_answers = [{} for _ in questions]
    
    return {
        "messages": [("ai", f"지금부터 두 분의 마음을 알아볼 심리테스트를 시작하겠습니다. 첫 번째 질문입니다.\n\n{questions[0]}\n\n먼저 한 분이 답변해주세요.")] ,
        "test_questions": questions,
        "test_answers": initial_answers,
        "current_test_question_index": 0,
        "waiting_for": "p1" # 첫 번째 사람의 답변을 기다림
    }

def receive_answer_node(state: AgentState):
    """두 사람의 답변을 순서대로 받습니다."""
    current_index = state["current_test_question_index"]
    waiting_for = state["waiting_for"]
    user_answer = state["messages"][-1][1]
    
    # 답변 저장
    updated_answers = list(state["test_answers"])
    updated_answers[current_index][waiting_for] = user_answer
    
    next_action = ""
    response_message = ""
    
    if waiting_for == 'p1':
        # p1의 답변을 받았으므로, 이제 p2의 답변을 기다림
        response_message = "네, 답변 잘 들었습니다. 이제 다른 한 분이 답변해주세요."
        return {
            "messages": [("ai", response_message)],
            "test_answers": updated_answers,
            "waiting_for": "p2"
        }
    else: # waiting_for == 'p2'
        # p2의 답변까지 모두 받았으므로, 다음 질문으로 넘어가거나 결과를 분석
        response_message = "두 분의 답변을 모두 잘 들었습니다."
        if current_index < len(state["test_questions"]) - 1:
            # 다음 질문으로
            next_action = "ask_next_test_question"
        else:
            # 모든 질문이 끝났으므로 결과 분석으로
            next_action = "analyze_test_results"
            response_message += " 이제 최종 결과를 분석해드릴게요. 잠시만 기다려주세요."

        return {
            "messages": [("ai", response_message)],
            "test_answers": updated_answers,
            "next_action": next_action
        }

def ask_next_question_node(state: AgentState):
    """다음 심리테스트 질문을 던집니다."""
    next_index = state["current_test_question_index"] + 1
    next_question = state["test_questions"][next_index]
    
    return {
        "messages": [("ai", f"다음 질문입니다.\n\n{next_question}\n\n먼저 한 분이 답변해주세요.")],
        "current_test_question_index": next_index,
        "waiting_for": "p1" # 다시 p1부터 답변 시작
    }

def analyze_results_node(state: AgentState):
    """모든 답변을 종합하여 최종 결과를 생성하고 테스트 상태를 초기화합니다."""
    analyzer = TestResultAnalyzer(questions=state["test_questions"], answers=state["test_answers"])
    result = analyzer.analyze()
    
    # 상태 초기화
    return {
        "messages": [("ai", result)],
        "test_questions": [],
        "test_answers": [],
        "current_test_question_index": 0,
        "waiting_for": ""
    }

# --- 일반 대화 노드 ---
def chat_node(state: AgentState):
    """퀴즈나 테스트와 관련 없는 일반 대화를 처리합니다."""
    response = llm.invoke(state['messages'])
    return {"messages": [response]}


# --- LangGraph 워크플로우 정의 ---
workflow = StateGraph(AgentState)

workflow.add_node("router", router_node)
workflow.add_node("chat", chat_node)
# 퀴즈 노드
workflow.add_node("ask_quiz_question", ask_quiz_question_node)
workflow.add_node("grade_quiz_answer", grade_quiz_answer_node)
# 심리테스트 노드
workflow.add_node("start_psych_test", start_test_node)
workflow.add_node("receive_test_answer", receive_answer_node)
workflow.add_node("ask_next_test_question", ask_next_question_node)
workflow.add_node("analyze_test_results", analyze_results_node)

workflow.set_entry_point("router")

# 조건부 엣지 설정
def decide_next_step(state: AgentState):
    return state.get("next_action", "chat")

workflow.add_conditional_edges(
    "router",
    decide_next_step,
    {
        "chat": END, # 일반 대화 후 종료 (WebSocket 루프에서 다시 호출됨)
        "ask_quiz_question": "ask_quiz_question",
        "grade_quiz_answer": "grade_quiz_answer",
        "start_psych_test": "start_psych_test",
        "receive_test_answer": "receive_test_answer",
    },
)

# 각 노드 실행 후의 흐름 제어
workflow.add_edge("ask_quiz_question", END)
workflow.add_edge("grade_quiz_answer", END)
workflow.add_edge("start_psych_test", END)
workflow.add_edge("analyze_test_results", END)

# 답변을 받은 후, 다음 행동(다음 질문 or 결과 분석)을 위해 다시 라우팅
workflow.add_conditional_edges(
    "receive_test_answer",
    decide_next_step,
    {
        "ask_next_test_question": "ask_next_test_question",
        "analyze_test_results": "analyze_test_results",
    }
)
workflow.add_edge("ask_next_test_question", END)


# 그래프 컴파일
app_runnable = workflow.compile()

# FastAPI 앱 생성
app = FastAPI()

# --- WebSocket 엔드포인트 ---
@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # ... (기존 WebSocket 설정 코드) ...
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
        graph_state = {
            "messages": [], 
            "quiz_question": "", "quiz_answer": "", "quiz_score": 0,
            "test_questions": [], "test_answers": [], "current_test_question_index": 0, "waiting_for": ""
        }

        # ... (기존 WebSocket STT/TTS 처리 루프) ...
        # 루프 내에서 graph_state를 계속 업데이트하며 app_runnable.invoke(graph_state) 호출
        # (이 부분은 변경되지 않았으므로 생략)

    except WebSocketDisconnect:
        print("Client disconnected")
    # ... (이하 생략) ...

@app.get("/")
def read_root():
    return {"Hello": "AI Cupid Backend"}