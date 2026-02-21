"""
밸런스 게임 질문 생성 (에이전트 도구·voice API 공용).
대화 맥락 문자열을 받아 밸런스 게임 질문 3개(Q, OPTION_A, OPTION_B)를 생성합니다.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    pass


def parse_balance_game_three(llm_output: str) -> list[tuple[str, str, str]] | None:
    """LLM 출력에서 Q1~Q3, 각 OPTION_A/B 파싱. 반환: [(question_text, option_a, option_b), ...] 최대 3개."""
    text = (llm_output or "").strip()
    blocks = re.split(r"(?=Q[123]\s*[:：]|질문[123]\s*[:：])", text, flags=re.IGNORECASE)
    blocks = [b.strip() for b in blocks if b.strip() and (re.match(r"^(?:Q[123]|질문[123])\s*[:：]", b, re.I) or "OPTION_A" in b or "OPTION_B" in b)]
    if len(blocks) < 3:
        blocks = re.split(r"\n\n+", text)
    result = []
    for block in blocks[:3]:
        q_match = re.search(r"(?:Q[123]|질문[123])\s*[:：]\s*(.+?)(?=(?:OPTION_A|선택A|A\s*[:：])|$)", block, re.DOTALL | re.IGNORECASE)
        a_match = re.search(r"(?:OPTION_A|선택A|A)\s*[:：]\s*(.+?)(?=(?:OPTION_B|선택B|B\s*[:：])|$)", block, re.DOTALL | re.IGNORECASE)
        b_match = re.search(r"(?:OPTION_B|선택B|B)\s*[:：]\s*(.+)", block, re.DOTALL | re.IGNORECASE)
        if q_match and a_match and b_match:
            result.append(
                (
                    q_match.group(1).strip()[:500],
                    a_match.group(1).strip()[:200],
                    b_match.group(1).strip()[:200],
                )
            )
    return result if len(result) == 3 else None


def generate_balance_game_questions(conversation_context: str) -> list[tuple[str, str, str]] | None:
    """
    대화 맥락 문자열을 받아 밸런스 게임 질문 3개를 생성합니다.
    반환: [(question_text, option_a, option_b), ...] 또는 실패 시 None.
    """
    from quiz_chain import get_llm

    history_block = (conversation_context or "").strip() or "(아직 대화 없음)"
    system = (
        "당신은 소개팅/미팅 MC입니다. **밸런스 게임** 질문 3개를 만드세요. "
        "각 질문은 'A vs B' 형태로 두 가지 중 하나를 고르는 재미있는 질문이어야 합니다. "
        "반드시 아래 형식으로만 출력하세요.\n\n"
        "Q1: (첫 번째 질문 문장, 예: 영화 볼 때 팝콘 vs 나초?)\n"
        "OPTION_A: (첫 번째 선택지)\nOPTION_B: (두 번째 선택지)\n\n"
        "Q2: (두 번째 질문)\nOPTION_A: ...\nOPTION_B: ...\n\n"
        "Q3: (세 번째 질문)\nOPTION_A: ...\nOPTION_B: ..."
    )
    user_content = (
        "[이 세션의 대화 내역]\n"
        f"{history_block}\n\n"
        "위 대화 맥락을 활용해 참가자들이 고르기 좋은 밸런스 게임 질문 3개를 Q1/OPTION_A/OPTION_B 형식으로 출력하세요."
    )
    messages = [SystemMessage(content=system), HumanMessage(content=user_content)]
    response = get_llm().invoke(messages)
    raw = (response.content if hasattr(response, "content") else str(response)).strip()
    parsed = parse_balance_game_three(raw)
    if parsed and len(parsed) == 3:
        return parsed
    # 폴백 파싱
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    parsed_fallback = []
    i = 0
    while i < len(lines) and len(parsed_fallback) < 3:
        q = lines[i] if i < len(lines) else ""
        a = lines[i + 1] if i + 1 < len(lines) else ""
        b = lines[i + 2] if i + 2 < len(lines) else ""
        if q and (q.startswith("Q") or "질문" in q or "?" in q or "vs" in q) and a and b:
            parsed_fallback.append(
                (
                    q.split(":", 1)[-1].strip() if ":" in q else q,
                    a.split(":", 1)[-1].strip() if ":" in a else a,
                    b.split(":", 1)[-1].strip() if ":" in b else b,
                )
            )
            i += 3
        else:
            i += 1
    return parsed_fallback if len(parsed_fallback) == 3 else None
