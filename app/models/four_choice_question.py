from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.database import Base


class FourChoiceQuestion(Base):
    """4지 선다 퀴즈: 질문 원본, 정답 1개, 비정답 3개. 상대방에 대한 퀴즈."""
    __tablename__ = "four_choice_questions"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(String, unique=True, index=True, nullable=False)  # UUID 등 클라이언트용 ID
    session_id = Column(String, index=True, nullable=False)
    question_text = Column(Text, nullable=False)
    correct_answer = Column(Text, nullable=False)
    wrong_answer_1 = Column(Text, nullable=False)
    wrong_answer_2 = Column(Text, nullable=False)
    wrong_answer_3 = Column(Text, nullable=False)
    about_user_name = Column(String, nullable=True)  # TTS에서 "OOO에 대한 퀴즈" 읽을 때 사용
    created_at = Column(DateTime, default=datetime.utcnow)
