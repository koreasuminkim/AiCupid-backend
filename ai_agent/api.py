"""
AiCupid AI 에이전트 HTTP 라우트.
"""

from fastapi import APIRouter, HTTPException

from ai_agent.agent import run_chat_agent, run_quiz_agent
from ai_agent.schemas import (
    ChatRequest,
    ChatResponse,
    QuizAgentRequest,
    QuizAgentResponse,
)

router = APIRouter(prefix="/agent", tags=["ai-agent"])


@router.post("/quiz", response_model=QuizAgentResponse)
async def quiz_invoke(request: QuizAgentRequest) -> QuizAgentResponse:
    """사용자 메시지를 받아 퀴즈/채팅 한 번 실행 (기존 /invoke와 동일 동작)."""
    try:
        return await run_quiz_agent(request)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"퀴즈 엔진 오류 (GEMINI_API_KEY 확인): {e}",
        )


@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(request: ChatRequest) -> ChatResponse:
    """채팅 메시지 목록을 받아 퀴즈/대화 응답을 반환합니다."""
    try:
        return await run_chat_agent(request.messages, request.state)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"에이전트 오류: {e}")
