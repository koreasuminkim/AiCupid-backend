import base64
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserProfile
from app.schemas.user import ProfileUpdateRequest
from app.api.auth import get_current_user
from services.s3_service import upload_file_to_s3_raw

router = APIRouter(prefix="/api/users", tags=["users"])

@router.put("/profile")
async def update_profile(
    update_data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. 이미지 처리 (새 이미지가 Base64로 들어온 경우)
    if update_data.profileImage and "base64," in update_data.profileImage:
        try:
            format, imgstr = update_data.profileImage.split(';base64,') 
            ext = format.split('/')[-1]
            image_data = base64.b64decode(imgstr)
            
            # S3 업로드 및 URL 갱신
            new_image_url = upload_file_to_s3_raw(image_data, f"{current_user.userId}_updated.{ext}", ext)
            if new_image_url:
                current_user.profile_image_url = new_image_url
        except Exception as e:
            print(f"프로필 이미지 수정 실패: {e}")

    # 2. 필드 업데이트
    update_fields = ["name", "gender", "age", "interests", "mbti", "bio"]
    for field in update_fields:
        value = getattr(update_data, field)
        if value is not None: # 값이 제공된 것만 수정
            setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)

    return {
        "status": "ok",
        "updatedProfile": {
            "userId": current_user.userId,
            "name": current_user.name,
            "gender": current_user.gender,
            "age": current_user.age,
            "interests": current_user.interests,
            "mbti": current_user.mbti,
            "bio": current_user.bio,
            "profileImage": current_user.profile_image_url
        }
    }

@router.get("/me", response_model=UserProfile)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """
    현재 로그인한 사용자의 프로필 정보를 가져옵니다. (마이페이지용)
    """
    return UserProfile(
        userId=current_user.userId,
        name=current_user.name,
        gender=current_user.gender,
        age=current_user.age,
        interests=current_user.interests,
        mbti=current_user.mbti,
        bio=current_user.bio,
        profileImage=current_user.profile_image_url
    )