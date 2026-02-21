"""
AiCupid 퀴즈 LangGraph 정의.
router → grade / ask_question / chat / finish
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph

from quiz_chain import QuizGrader, QuestionProvider, quiz_data, get_llm, get_react_chain


class AgentState(TypedDict):
    """퀴즈 그래프 상태."""

    messages: Annotated[list, operator.add]
    question_id: int
    score: int
    next_action: str


def build_quiz_graph() -> StateGraph:
    """퀴즈/채팅 LangGraph를 빌드하여 반환 (compile은 호출 측에서). LLM은 첫 실행 시 로드."""

    def router_node(state: AgentState):
        messages = state.get("messages") or []
        if not messages:
            return {"next_action": "chat", "question_id": 0, "score": 0}
        last_message = messages[-1]
        last_content = last_message[1] if isinstance(last_message, (list, tuple)) and len(last_message) > 1 else str(last_message)
        question_id = state.get("question_id", 0)
        score = state.get("score", 0)
        action = "chat"
        if question_id < len(quiz_data):
            if (
                len(messages) > 1
                and messages[-2][0] == "ai"
                and "질문" in (messages[-2][1] if isinstance(messages[-2], (list, tuple)) and len(messages[-2]) > 1 else str(messages[-2]))
            ):
                action = "grade"
            else:
                action = "ask"
        else:
            action = "finish"
        if "퀴즈" in last_content and "시작" in last_content:
            action = "ask"
        return {"next_action": action, "question_id": question_id, "score": score}

    def grade_answer_node(state: AgentState):
        messages = state.get("messages") or []
        user_message = messages[-1] if messages else ("user", "")
        user_answer = user_message[1] if isinstance(user_message, (list, tuple)) and len(user_message) > 1 else str(user_message)
        q_id = state.get("question_id", 0)
        grader = QuizGrader(user_answer=user_answer, question_id=q_id)
        is_correct = grader.grade()
        new_score = state.get("score", 0)
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
        q_id = state.get("question_id", 0)
        provider = QuestionProvider(question_id=q_id)
        question = provider.get_question()
        message = f"퀴즈 질문입니다: {question}" if q_id < len(quiz_data) else question
        return {"messages": [("ai", message)]}

    def chat_node(state: AgentState):
        messages = state.get("messages") or []
        response = get_llm().invoke(messages)
        return {"messages": [response]}

    def decide_next_step(state: AgentState):
        return state.get("next_action", "chat")

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

    return workflow
