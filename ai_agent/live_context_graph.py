"""
Live API용 간단한 그래프: 클라이언트가 보낸 대화 내역(바이트) → 시스템 지시문 생성.

- roles: ai, mc (AI MC 역할)
- 어색한 대화를 풀어주는 맥락을 system_instruction에 담아 Live API에 전달
"""

from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from ai_agent.prompts import AI_MC_SYSTEM_PROMPT
from ai_agent.balance_game import generate_balance_game_questions


@tool
def start_balance_game() -> str:
    """참가자가 밸런스 게임을 하자고 하거나, MC가 밸런스 게임을 제안·시작할 때 호출하세요. 대화 맥락에 맞는 밸런스 게임 질문 3개가 생성됩니다."""
    return ""


class LiveContextState(TypedDict, total=False):
    """대화 바이트 → Live용 시스템 지시문 상태."""

    raw_bytes: bytes
    raw_text: str  # LangGraph Studio 등에서 JSON 문자열로 대화 내역 전달 시 사용
    conversation: list[tuple[str, str]]  # (role, content)
    system_instruction: str
    reply: str  # MC가 할 답변(새 질문/말) — Studio 등에서 출력용
    triggered_balance_game_questions: list[tuple[str, str, str]]  # (question_text, option_a, option_b) 3개, 에이전트가 게임 트리거 시


def _parse_conversation_node(state: LiveContextState) -> dict:
    """바이트를 UTF-8 JSON으로 파싱해 대화 목록으로 넣음. Studio에서는 raw_text 사용. 평문 한 줄이면 user 메시지 1개로 처리."""
    raw = state.get("raw_bytes") or b""
    if not raw and state.get("raw_text"):
        raw = (state["raw_text"] or "").encode("utf-8")
    conversation: list[tuple[str, str]] = []
    text = ""
    try:
        text = (raw.decode("utf-8") or "").strip()
        if not text:
            return {"conversation": conversation}
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    role = (item.get("role") or "user").lower()
                    if role not in ("user", "human"):
                        role = "ai"  # mc, assistant 등 → ai
                    content = item.get("content") or item.get("text") or ""
                    conversation.append((role, str(content)))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    conversation.append((str(item[0]), str(item[1])))
        elif isinstance(data, dict) and "messages" in data:
            for m in data["messages"]:
                if isinstance(m, (list, tuple)) and len(m) >= 2:
                    conversation.append((str(m[0]), str(m[1])))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        pass
    # JSON이 아니거나 대화 목록이 비었으면: 평문 전체를 user 메시지 1개로 사용 (예: "안녕 나는 김수민이야")
    if not conversation and text:
        conversation = [("user", text)]
    return {"conversation": conversation}


def _build_instruction_node(state: LiveContextState) -> dict:
    """roles(ai, mc) + 어색한 대화 풀어주기 + (대화 있으면) 맥락을 바탕으로 새 질문 하도록 지시."""
    conv = state.get("conversation") or []
    base = AI_MC_SYSTEM_PROMPT.strip()
    role_instruction = (
        "역할(roles): 당신은 **ai**이자 **mc**입니다. "
        "소개팅/미팅 상황을 이끄는 MC로서, 어색한 대화를 자연스럽게 풀어 주세요."
    )
    parts = [base, role_instruction]

    if conv:
        lines = ["[지금까지의 대화 내역:]"]
        for role, content in conv[-20:]:
            lines.append(f"- {role}: {content[:200]}{'…' if len(content) > 200 else ''}")
        context_block = "\n".join(lines)
        parts.append(
            f"{context_block}\n\n"
            "위 대화 내역을 기반으로 참가자에게 자연스러운 **새 질문**을 하거나, 대화를 이어가세요. "
            "맥락에 맞는 질문으로 분위기를 이끌어 주세요. "
            "참가자가 밸런스 게임을 하자고 하면 start_balance_game 도구를 호출하세요."
        )

    system_instruction = "\n\n".join(parts)
    return {"system_instruction": system_instruction}


def _generate_reply_node(state: LiveContextState) -> dict:
    """시스템 지시문 + 대화 맥락으로 MC 답변(새 질문/말) 생성. 밸런스 게임 요청 시 도구로 질문 3개 생성 후 답변에 포함."""
    instruction = state.get("system_instruction") or ""
    conv = state.get("conversation") or []
    if not instruction:
        return {"reply": ""}
    from quiz_chain import get_llm

    messages = [SystemMessage(content=instruction)]
    for role, content in conv:
        if role in ("user", "human"):
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content="위 대화 맥락에 맞게, MC로서 참가자에게 할 한 문장(인사·질문·말)만 짧게 답해 주세요. 따옴표나 설명 없이 말만 출력하세요. 단, 밸런스 게임을 시작할 때는 start_balance_game 도구를 먼저 호출한 뒤, 그 결과를 활용해 답하세요."))

    triggered_questions: list[tuple[str, str, str]] | None = None
    try:
        llm_with_tools = get_llm().bind_tools([start_balance_game])
        response = llm_with_tools.invoke(messages)

        if getattr(response, "tool_calls", None):
            tool_messages = []
            for tc in response.tool_calls:
                if tc.get("name") == "start_balance_game":
                    context_parts = [f"- {role}: {content}" for role, content in conv]
                    context = "\n".join(context_parts) if context_parts else "(아직 대화 없음)"
                    questions = generate_balance_game_questions(context)
                    if questions and len(questions) == 3:
                        triggered_questions = questions
                        lines = []
                        for i, (q, a, b) in enumerate(questions, 1):
                            lines.append(f"Q{i}: {q}  A: {a}  B: {b}")
                        result = "밸런스 게임 질문 3개: " + " | ".join(lines)
                    else:
                        result = "밸런스 게임 질문 생성에 실패했습니다."
                    tool_messages.append(ToolMessage(tool_call_id=tc["id"], content=result))
            messages.append(response)
            messages.extend(tool_messages)
            response = llm_with_tools.invoke(messages)

        reply = (response.content or "").strip() if hasattr(response, "content") else str(response).strip()
    except Exception:
        reply = ""

    out: dict = {"reply": reply}
    if triggered_questions is not None:
        out["triggered_balance_game_questions"] = triggered_questions
    return out


def build_live_context_graph() -> StateGraph:
    """대화 바이트 → 시스템 지시문 + MC 답변 생성 그래프 (단순 선형)."""
    workflow = StateGraph(LiveContextState)
    workflow.add_node("parse", _parse_conversation_node)
    workflow.add_node("build_instruction", _build_instruction_node)
    workflow.add_node("generate_reply", _generate_reply_node)
    workflow.set_entry_point("parse")
    workflow.add_edge("parse", "build_instruction")
    workflow.add_edge("build_instruction", "generate_reply")
    workflow.add_edge("generate_reply", END)
    return workflow


_compiled_live_context_graph = None


def get_live_context_graph():
    """컴파일된 Live 컨텍스트 그래프 반환."""
    global _compiled_live_context_graph
    if _compiled_live_context_graph is None:
        _compiled_live_context_graph = build_live_context_graph().compile()
    return _compiled_live_context_graph


def get_system_instruction_from_conversation_bytes(raw_bytes: bytes) -> str:
    """
    대화 내역 바이트를 넣으면 Live API에 줄 시스템 지시문을 반환.
    동기 함수; async가 필요하면 호출 측에서 run_in_executor 사용.
    """
    graph = get_live_context_graph()
    out = graph.invoke({"raw_bytes": raw_bytes})
    return out.get("system_instruction") or AI_MC_SYSTEM_PROMPT


# LangGraph Studio(langgraph dev)에서 로드할 그래프 — langgraph.json에서 참조
# 입력: {"raw_text": "[{\"role\":\"user\",\"content\":\"...\"},{\"role\":\"ai\",\"content\":\"...\"}]"}
agent = build_live_context_graph().compile()
