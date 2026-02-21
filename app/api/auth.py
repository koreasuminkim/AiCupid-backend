from fastapi import APIRouter

router = APIRouter(tags=["auth"])

@router.post("/signup")
def signup():
    return {"message": "회원가입 로직을 구현하세요."}