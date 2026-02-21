from sqlalchemy import Column, Integer, String, JSON
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    profile_image_url = Column(String, nullable=True)
    gender = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
     # ["영화", "게임"] 형태
    interests = Column(JSON, nullable=False)