"""
AiCupid AI 에이전트 입출력 스키마.
- QuizAgentRequest / QuizAgentResponse: 퀴즈 한 번 호출 (하위 호환)
- ChatMessage, ChatRequest, ChatResponse: 채팅 기반 퀴즈/대화
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── 퀴즈 단일 호출 (기존 /invoke 호환) ─────────────────────────

class QuizAgentRequest(BaseModel):
    """에이전트에 넘기는 입력 (사용자 메시지 + 선택적 상태)."""

    input: str = Field(..., description="사용자 메시지 (예: 퀴즈 시작, 답변, 자유 대화)")
    state: dict | None = Field(
        None,
        description="이전 상태 (messages, question_id, score). 없으면 새 세션으로 시작",
    )


class QuizAgentResponse(BaseModel):
    """에이전트가 반환하는 퀴즈/채팅 응답."""

    response: str = Field(..., description="AI 응답 텍스트")
    state: dict = Field(..., description="다음 호출 시 넘길 상태 (messages, question_id, score)")


# ── 채팅 API 스키마 ────────────────────────────────────────────

class ChatMessage(BaseModel):
    """채팅 메시지."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """채팅 API 요청."""

    messages: list[ChatMessage] = Field(..., description="대화 히스토리")
    state: dict | None = Field(
        None,
        description="퀴즈 상태 (question_id, score 등). 없으면 새 세션",
    )


class ChatResponse(BaseModel):
    """채팅 API 응답."""

    reply: str = Field(..., description="AI 대화 응답 텍스트")
    state: dict = Field(..., description="업데이트된 퀴즈 상태 (다음 요청 시 전달)")

    model_config = {"populate_by_name": True}
