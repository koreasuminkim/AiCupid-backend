"""
AiCupid 퀴즈/채팅 에이전트용 시스템·유저 프롬프트.
"""

from __future__ import annotations

# 퀴즈 에이전트 역할 (필요 시 노드별로 확장)
SYSTEM_PROMPT = """당신은 AiCupid 퀴즈·대화 에이전트입니다.
사용자와 퀴즈를 진행하거나, 퀴즈와 무관한 대화를 할 수 있습니다.
답변은 친근하고 짧게, 한국어로 해 주세요."""


def build_user_prompt(user_message: str) -> str:
    """사용자 메시지를 그대로 전달 (추가 컨텍스트 필요 시 확장)."""
    return user_message
