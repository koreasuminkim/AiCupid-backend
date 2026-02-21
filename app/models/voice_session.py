from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base


class VoiceSession(Base):
    """음성 세션: session_id + 참가 유저 2명 ID 저장."""
    __tablename__ = "voice_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    user_id_1 = Column(String, nullable=False)
    user_id_2 = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
