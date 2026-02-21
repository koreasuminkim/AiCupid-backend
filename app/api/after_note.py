from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models.user import User
from app.models.after_note import AfterNote
from app.schemas.after_note import AfterResponseRequest, MatchResultResponse
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/after", tags=["after-note"])

@router.post("/respond")
async def respond_after(
    request: AfterResponseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. 내 응답 저장/업데이트
    existing_note = db.query(AfterNote).filter(
        AfterNote.sender_id == current_user.userId,
        AfterNote.receiver_id == request.partner_id
    ).first()

    if existing_note:
        existing_note.choice = request.choice
        existing_note.created_at = datetime.utcnow()
    else:
        new_note = AfterNote(
            sender_id=current_user.userId,
            receiver_id=request.partner_id,
            choice=request.choice
        )
        db.add(new_note)
    db.commit()

    # 2. 즉시 매칭 판정 및 번호 추출
    is_matched = False
    partner_phone = None

    if request.choice:  # 내가 'O'를 택했을 때만 체크
        partner_note = db.query(AfterNote).filter(
            AfterNote.sender_id == request.partner_id,
            AfterNote.receiver_id == current_user.userId,
            AfterNote.choice == True
        ).first()

        if partner_note:
            is_matched = True
            # 매칭 성공 시 상대방 유저 정보를 가져와 전번 추출
            partner_user = db.query(User).filter(User.userId == request.partner_id).first()
            partner_phone = partner_user.phone_number if partner_user else None

    return {
        "status": "ok",
        "is_matched": is_matched,
        "phone_number": partner_phone  # 매칭 안 되면 null, 되면 번호가 나감
    }

@router.get("/received")
async def get_received_notes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 나에게 쪽지를 보낸 사람들과 그 내용을 가져옴
    results = (
        db.query(AfterNote, User)
        .join(User, AfterNote.sender_id == User.userId)
        .filter(AfterNote.receiver_id == current_user.userId)
        .all()
    )

    notes_list = []
    for note, sender in results:
        # 내가 이 사람에게 보낸 응답이 있는지 확인
        my_reply = db.query(AfterNote).filter(
            AfterNote.sender_id == current_user.userId,
            AfterNote.receiver_id == sender.userId
        ).first()

        # 상호 'O' 인지 확인
        is_matched = note.choice and (my_reply and my_reply.choice)
        
        notes_list.append({
            "sender_id": sender.userId,
            "sender_name": sender.name,
            "sender_profile_image": sender.profile_image_url,
            "choice": note.choice,
            "is_matched": is_matched,
            "phone_number": sender.phone_number if is_matched else None, # 매칭 시에만 전번 포함
            "is_read": note.is_read,
            "created_at": note.created_at
        })
        
        # 목록을 확인했으므로 읽음 처리 (선택 사항)
        note.is_read = True
    
    db.commit()
    return {"notes": notes_list}