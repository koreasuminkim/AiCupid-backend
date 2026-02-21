from enum import Enum
from typing import List, Optional, Literal
from pydantic import BaseModel, EmailStr, Field

class InterestEnum(str, Enum):
    MOVIE = "영화"
    SPORT = "스포츠"
    GAME = "게임"
    MUSIC = "음악"
    TRAVEL = "여행"
    READING = "독서"
    COOKING = "요리"
    FASHION = "패션"
    OUTDOOR = "아웃도어"
    DATING = "연애"

class UserBase(BaseModel):
    email: EmailStr
    name: str
    gender: Literal["남", "여"]
    age: int
    interests: List[InterestEnum] = Field(..., min_items=1, max_items=10)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

class UserResponse(UserBase):
    id: int
    profile_image_url: Optional[str] = None

    class Config:
        from_attributes = True

class UserProfile(BaseModel):
    userId: str
    name: str
    gender: str
    age: int
    interests: List[str]
    mbti: Optional[str] = None
    bio: Optional[str] = None
    profileImage: Optional[str] = None

class RegisterRequest(BaseModel): # 회원가입 요청
    userId: str
    password: str
    name: str
    gender: str
    age: int
    interests: List[str]
    mbti: Optional[str] = None
    bio: Optional[str] = None
    profileImage: Optional[str] = None

class LoginRequest(BaseModel): # 로그인 요청
    userId: str
    password: str

class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    interests: Optional[List[str]] = None
    mbti: Optional[str] = None
    bio: Optional[str] = None
    profileImage: Optional[str] = None # Base64 string