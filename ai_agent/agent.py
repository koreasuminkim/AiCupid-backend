"""
AiCupid 퀴즈 에이전트 실행 로직.
- run_quiz_agent: 단일 메시지 → 퀴즈/채팅 응답 (기존 /invoke 호환)
- run_chat_agent: 채팅 히스토리 → 응답 + 상태
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from ai_agent.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    QuizAgentRequest,
    QuizAgentResponse,
)

_memory = MemorySaver()
_api_graph = None


def _get_graph():
    """Lazy import: 퀴즈 LangGraph (checkpointer 포함)."""
    global _api_graph
    if _api_graph is None:
        from ai_agent.graph import build_quiz_graph
        _api_graph = build_quiz_graph().compile(checkpointer=_memory)
    return _api_graph


_plain_runnable = None


def get_app_runnable():
    """checkpointer 없이 컴파일한 그래프 (main.py /invoke, websocket 호환)."""
    global _plain_runnable
    if _plain_runnable is None:
        from ai_agent.graph import build_quiz_graph
        _plain_runnable = build_quiz_graph().compile()
    return _plain_runnable


# ── 단일 호출 (기존 /invoke 호환) ──────────────────────────────


async def run_quiz_agent(request: QuizAgentRequest) -> QuizAgentResponse:
    """
    사용자 메시지를 받아 퀴즈/채팅 그래프를 한 번 실행하고 응답을 반환합니다.
    """
    graph = _get_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    current_state = request.state or {"messages": [], "question_id": 0, "score": 0}
    current_state["messages"] = current_state.get("messages", []) + [("user", request.input)]

    result = await graph.ainvoke(current_state, config)

    last_ai_message = ""
    for role, msg in reversed(result.get("messages", [])):
        if role == "ai":
            last_ai_message = msg if isinstance(msg, str) else getattr(msg, "content", str(msg))
            break

    return QuizAgentResponse(response=last_ai_message, state=result)


# ── 채팅 기반 ───────────────────────────────────────────────────


async def run_chat_agent(
    messages: list[ChatMessage],
    state: dict | None = None,
) -> ChatResponse:
    """
    채팅 메시지 목록을 받아 마지막 사용자 메시지로 그래프를 실행하고 응답을 반환합니다.
    """
    user_message = ""
    for msg in reversed(messages):
        if msg.role == "user":
            user_message = msg.content
            break

    if not user_message:
        return ChatResponse(
            reply="메시지를 입력해 주세요.",
            state=state or {"messages": [], "question_id": 0, "score": 0},
        )

    graph = _get_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    base = state or {"messages": [], "question_id": 0, "score": 0}
    base["messages"] = base.get("messages", []) + [("user", user_message)]

    result = await graph.ainvoke(base, config)

    last_ai_message = ""
    for role, msg in reversed(result.get("messages", [])):
        if role == "ai":
            last_ai_message = msg if isinstance(msg, str) else getattr(msg, "content", str(msg))
            break

    return ChatResponse(reply=last_ai_message, state=result)
