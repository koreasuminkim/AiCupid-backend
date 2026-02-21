import base64
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserProfile
from app.schemas.user import ProfileUpdateRequest
from app.api.auth import get_current_user
from app.schemas.user import UserProfile, ProfileUpdateRequest, MatchableUserListResponse, MatchableUserResponse
from services.s3_service import upload_file_to_s3_raw
from fastapi import Query
from sqlalchemy import func
from services.youtube_service import fetch_youtube_subscriptions, analyze_interests_with_llm

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

@router.get("/search", response_model=MatchableUserListResponse)
async def search_users_by_id(
    userId_query: Optional[str] = Query(None, alias="userId", description="검색할 유저 ID (부분 일치)"),
    skip: int = 0,
    limit: int = 15,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    userId로 유저를 검색합니다. 
    검색어가 없으면 전체 유저를 가입순(최신순)으로 나열합니다.
    """
    # 1. 기본 쿼리 생성: 본인 제외
    query = db.query(User).filter(User.userId != current_user.userId)

    # 2. userId 검색 조건 추가 (부분 일치 검색)
    if userId_query:
        # User.userId에 검색어가 포함되어 있는지 확인 (LIKE %query%)
        query = query.filter(User.userId.contains(userId_query))

    # 3. 가입순 정렬 (ID가 클수록 최신 가입자)
    query = query.order_by(User.id.desc())

    # 4. 전체 개수 구하기 (페이지네이션 전)
    total_count = query.count()

    # 5. 페이지네이션 적용 (skip, limit)
    searched_users = query.offset(skip).limit(limit).all()

    # 6. 응답 데이터 변환
    result = [
        MatchableUserResponse(
            userId=u.userId,
            name=u.name,
            age=u.age,
            gender=u.gender,
            mbti=u.mbti,
            interests=u.interests,
            profileImage=u.profile_image_url
        ) for u in searched_users
    ]

    return {
        "users": result,
        "total_count": total_count
    }

@router.get("/matchable", response_model=MatchableUserListResponse)
async def get_matchable_users(
    skip: int = 0,
    limit: int = 15,
    sort_by: str = Query(None, description="정렬 기준: mbti, interests"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    페이지네이션과 다중 조건 정렬 알고리즘이 적용된 매칭 유저 목록 조회
    """
    # 1. 기본 필터: 본인 제외
    query = db.query(User).filter(User.userId != current_user.userId)
    all_users = query.all()

    # 2. 추천 점수 계산 함수 (1순위 기준용)
    def calculate_primary_score(other_user: User):
        score = 0
        if sort_by == "mbti" and current_user.mbti and other_user.mbti:
            m1, m2 = current_user.mbti.upper(), other_user.mbti.upper()
            score = sum(1 for a, b in zip(m1, m2) if a == b)
        elif sort_by == "interests":
            c_ints = set(current_user.interests or [])
            o_ints = set(other_user.interests or [])
            score = len(c_ints & o_ints)
        return score

    # 3. 다중 조건 정렬 (Python의 sorted는 stable 하므로 튜플을 이용해 한 번에 정렬)
    # (점수 내림차순, 나이차이 오름차순, ID 내림차순)
    # reverse=True를 사용하므로, 오름차순을 원하는 값(나이차이)은 음수로 처리합니다.
    if sort_by in ["mbti", "interests"]:
        sorted_users = sorted(
            all_users, 
            key=lambda u: (
                calculate_primary_score(u),            # 1순위: 점수 (높을수록 앞)
                -abs(current_user.age - u.age),        # 2순위: 나이차 적을수록 앞 (음수로 큰 값이 됨)
                u.id                                   # 3순위: 최신 가입자 (ID 클수록 앞)
            ), 
            reverse=True
        )
    else:
        # 기준이 없으면 최신 가입 순으로만 정렬
        sorted_users = sorted(all_users, key=lambda u: u.id, reverse=True)

    # 4. 페이지네이션 슬라이싱  
    paginated_users = sorted_users[skip : skip + limit]
    
    # 5. 응답 데이터 변환
    result = [
        MatchableUserResponse(
            userId=u.userId,
            name=u.name,
            age=u.age,
            gender=u.gender,
            mbti=u.mbti,
            interests=u.interests,
            profileImage=u.profile_image_url
        ) for u in paginated_users
    ]

    return {
        "users": result,
        "total_count": len(all_users)
    }

@router.post("/sync-youtube")
async def sync_youtube_interests(
    request: dict, # {"access_token": "..."}
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    access_token = request.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Google Access Token이 필요합니다.")
    
    # 1. 유튜브에서 구독 채널 이름들 긁어오기
    channels = fetch_youtube_subscriptions(access_token)
    if not channels:
        return {"status": "error", "message": "구독 목록을 가져올 수 없거나 목록이 비어있습니다."}
    
    # 2. LLM으로 분석
    analysis = await analyze_interests_with_llm(channels)
    if not analysis:
        raise HTTPException(status_code=500, detail="취향 분석 중 오류가 발생했습니다.")
    
    # 3. DB 업데이트
    current_user.interests = analysis["interests"]
    
    db.commit()
    db.refresh(current_user)
    
    return {
        "status": "ok",
        "updated_data": {
            "interests": current_user.interests,
        }
    }