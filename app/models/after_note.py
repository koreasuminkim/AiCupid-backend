from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from app.database import Base

class AfterNote(Base):
    """
    애프터 신청 및 수락 상태를 저장하는 모델
    """
    __tablename__ = "after_notes"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(String, index=True, nullable=False)   # 보내는 사람 (나)
    receiver_id = Column(String, index=True, nullable=False) # 받는 사람 (상대방)
    choice = Column(Boolean, nullable=False)                 # 'O' 또는 'X'
    is_read = Column(Boolean, default=False)                # 읽음 여부 (알림용)
    created_at = Column(DateTime, default=datetime.utcnow)