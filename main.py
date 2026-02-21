from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# API 라우터 임포트
from app.database import engine, Base
from app.api.auth import router as auth_router
from app.api.voice import router as voice_router
from app.api.ws import router as ws_router
from app.api.agent import router as agent_router # 기존 파일 유지 시

load_dotenv()

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AiCupid Backend API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 일단 모두 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth_router, prefix="/api/auth")
app.include_router(voice_router, prefix="/api") # /api/voice/...
app.include_router(agent_router)               # 이미 /agent prefix 있음
app.include_router(ws_router)                  # /ws/quiz

@app.get("/")
def read_root():
    return {"service": "AiCupid-backend", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}