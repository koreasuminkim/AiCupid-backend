from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.database import Base


class VoiceConversationTurn(Base):
    """세션별 대화 턴: 유저 음성 전사 + AI 답변. 에이전트 history 구성용."""
    __tablename__ = "voice_conversation_turns"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    user_text = Column(Text, nullable=True)   # 변환된 음성(전사)
    assistant_reply = Column(Text, nullable=False)  # 생성한 MC 답변
    created_at = Column(DateTime, default=datetime.utcnow)
