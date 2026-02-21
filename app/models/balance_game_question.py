from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.database import Base


class BalanceGameQuestion(Base):
    """밸런스 게임: 질문 1개당 선택지 2개(A vs B)."""
    __tablename__ = "balance_game_questions"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(String, unique=True, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    question_text = Column(Text, nullable=False)  # "팝콘 vs 나초" 같은 질문 문장
    option_a = Column(Text, nullable=False)
    option_b = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
