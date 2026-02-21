import os
import base64
from io import BytesIO
from services.s3_service import upload_file_to_s3_raw
from passlib.context import CryptContext
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
from fastapi import Security
from jose import JWTError, jwt

from app.database import get_db
from app.models.user import User
from app.schemas.user import RegisterRequest, LoginRequest
from app.schemas.user import UserCreate, UserResponse

PWD_CONTEXT = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "fallback-for-local-dev")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

router = APIRouter(tags=["auth"])

@router.post("/register")
async def register(user_data: RegisterRequest, db: Session = Depends(get_db)):
    # 1. 중복 체크
    if db.query(User).filter(User.userId == user_data.userId).first():
        raise HTTPException(status_code=400, detail="이미 존재하는 ID입니다.")

    # 2. Base64 이미지 처리 (있을 경우에만 업로드)
    image_url = None
    if user_data.profileImage and "base64," in user_data.profileImage:
        try:
            # 먼저 데이터를 추출하고 변수를 정의합니다.
            format, imgstr = user_data.profileImage.split(';base64,') 
            ext = format.split('/')[-1]
            image_data = base64.b64decode(imgstr)
            
            # 정의된 변수를 사용하여 업로드 호출
            image_url = upload_file_to_s3_raw(image_data, f"{user_data.userId}.{ext}", ext)
        except Exception as e:
            print(f"이미지 업로드 실패: {e}")

    # 3. 유저 저장
    new_user = User(
        userId=user_data.userId,
        hashed_password=PWD_CONTEXT.hash(user_data.password),
        name=user_data.name,
        gender=user_data.gender,
        age=user_data.age,
        interests=user_data.interests,
        mbti=user_data.mbti,
        bio=user_data.bio,
        profile_image_url=image_url
    )
    db.add(new_user)
    db.commit()
    return {"status": "ok"}

@router.post("/login")
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.userId == request.userId).first()
    
    if not user or not PWD_CONTEXT.verify(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호 오류")

    # 토큰 생성
    token = jwt.encode({"sub": user.userId}, SECRET_KEY, algorithm=ALGORITHM)
    
    return {
        "status": "ok",
        "token": token,
        "userProfile": {
            "userId": user.userId,
            "name": user.name,
            "gender": user.gender,
            "age": user.age,
            "interests": user.interests,
            "mbti": user.mbti,
            "bio": user.bio,
            "profileImage": user.profile_image_url
        }
    }


# Swagger Authorize용: OAuth2 형식(form)으로 받아 access_token 반환
@router.post("/token")
async def login_token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Swagger/OpenAPI Authorize 버튼용. username에 userId, password에 비밀번호를 넣으세요.
    """
    user = db.query(User).filter(User.userId == form.username).first()
    if not user or not PWD_CONTEXT.verify(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호 오류")
    token = jwt.encode({"sub": user.userId}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보가 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.userId == user_id).first()
    if user is None:
        raise credentials_exception
    return user