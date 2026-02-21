from enum import Enum
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

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

class UserCreate(BaseModel):
    name: str
    gender: Literal["남", "여"]
    age: int
    interests: List[InterestEnum] = Field(..., min_items=1, max_items=10)