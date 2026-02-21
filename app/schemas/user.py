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
    
    TECH = "IT/기술"
    FINANCE = "경제/재테크"
    BEAUTY = "뷰티"
    HEALTH = "헬스/운동"
    ANIMAL = "반려동물"
    ART = "예술/전시"
    COMEDY = "코미디/유머"
    SCIENCE = "과학/지식"
    VOLUNTEER = "봉사"
    LANGUAGE = "외국어"
    FOOD = "맛집탐방"
    CAR = "자동차"
    CAMPING = "캠핑"
    DIY = "DIY/만들기"
    EDUCATION = "교육/자기계발"
    VLOG = "브이로그"
    PHOTOGRAPHY = "사진/영상촬영"
    EDITING = "영상편집"
    POLITICS = "정치/사회이슈"
    DOCUMENTARY = "다큐/교양"
    HISTORY = "역사"
    NEWS = "뉴스/시사"
    REVIEW = "리뷰/언박싱"
    ASMR = "ASMR/힐링"
    STUDY = "공부/수험"
    PRODUCTIVITY = "생산성/시간관리"
    ANIMATION = "애니/만화"
    DRAMA = "드라마/예능"
    KPOP = "K-POP/아이돌"
    MIND = "마인드/자기이해"
    HOME = "인테리어/집꾸미기"
    FISHING = "낚시"
    GARDENING = "원예/식물"
    CAREER = "취업/커리어"
    BUSINESS = "비즈니스/창업"

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

class MatchableUserListResponse(BaseModel):
    users: List[UserProfile]

class MatchableUserResponse(BaseModel):
    userId: str
    name: str
    age: int
    gender: str
    mbti: Optional[str] = None
    interests: List[str] = []
    profileImage: Optional[str] = None

class MatchableUserListResponse(BaseModel):
    users: List[MatchableUserResponse]
    total_count: int