from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AfterResponseRequest(BaseModel):
    partner_id: str
    choice: bool  # 'O'는 True, 'X'는 False로 매핑

class MatchResultResponse(BaseModel):
    is_matched: bool
    partner_id: str
    phone_number: Optional[str] = None  # 매칭 성공 시에만 노출
    partner_name: str

class ReceivedNoteResponse(BaseModel):
    sender_id: str
    sender_name: str
    sender_profile_image: Optional[str] = None
    choice: bool      # 상대방이 나에게 보낸 선택 (보통 True인 것만 필터링하거나 전체 노출)
    is_read: bool     # 내가 읽었는지 여부
    created_at: datetime

class ReceivedNoteListResponse(BaseModel):
    notes: list[ReceivedNoteResponse]
    unread_count: int  # 빨간 점(Badge)에 표시할 숫자