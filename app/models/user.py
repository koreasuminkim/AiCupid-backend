from sqlalchemy import Column, Integer, String, JSON
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    userId = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True) # 이메일, 비번 추가
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    profile_image_url = Column(String, nullable=True)
    gender = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
     # ["영화", "게임"] 형태
    interests = Column(JSON, nullable=False)
    mbti = Column(String, nullable=True) 
    bio = Column(String, nullable=True)