import operator
import sqlite3
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

# 지연 로딩을 위한 싱글톤 변수
_app_runnable = None

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    question_id: int
    score: int
    next_action: str

def get_app_runnable():
    global _app_runnable
    if _app_runnable is not None:
        return _app_runnable

    from langchain_google_genai import ChatGoogleGenerativeAI
    from quiz_chain import QuizGrader, QuestionProvider, quiz_data

    llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0)

    # --- 기존 노드 로직 (동일) ---
    def router_node(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        action = "chat"
        
        # 퀴즈 시작 키워드 체크
        if "퀴즈" in last_message[1] and "시작" in last_message[1]:
            return {"next_action": "ask"}

        # 메시지가 2개 이상일 때만 이전 AI 메시지 확인
        if len(messages) >= 2:
            prev_role, prev_msg = messages[-2]
            if state["question_id"] < len(quiz_data):
                if prev_role == "ai" and "질문" in prev_msg:
                    action = "grade"
                else:
                    action = "ask"
            else:
                action = "finish"
        
        return {"next_action": action}

    def grade_answer_node(state: AgentState):
        user_answer = state["messages"][-1][1]
        q_id = state["question_id"]
        grader = QuizGrader(user_answer=user_answer, question_id=q_id)
        is_correct = grader.grade()
        new_score = state["score"] + (1 if is_correct else 0)
        msg = f"정답입니다! 현재 점수: {new_score}" if is_correct else f"아쉽네요. 정답은 '{quiz_data[q_id]['answer']}'입니다."
        return {"messages": [("ai", msg)], "score": new_score, "question_id": q_id + 1}

    def ask_question_node(state: AgentState):
        q_id = state["question_id"]
        question = QuestionProvider(question_id=q_id).get_question()
        return {"messages": [("ai", f"퀴즈 질문입니다: {question}")]}

    def chat_node(state: AgentState):
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    # --- 그래프 빌드 ---
    workflow = StateGraph(AgentState)
    workflow.add_node("router", router_node)
    workflow.add_node("grade_answer", grade_answer_node)
    workflow.add_node("ask_question", ask_question_node)
    workflow.add_node("chat", chat_node)
    
    workflow.set_entry_point("router")
    workflow.add_conditional_edges("router", lambda x: x["next_action"], 
                                 {"grade": "grade_answer", "ask": "ask_question", "chat": "chat", "finish": END})
    workflow.add_edge("grade_answer", "router")
    workflow.add_edge("ask_question", "router")
    workflow.add_edge("chat", "router")

    # --- SQLite 체크포인터 설정 ---
    # 파일 이름을 'checkpoints.db'로 설정하여 데이터를 로컬에 물리적으로 저장합니다.
    memory = SqliteSaver.from_conn_string("checkpoints.db")
    _app_runnable = workflow.compile(checkpointer=memory)
    
    return _app_runnable