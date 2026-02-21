import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

# API 라우터 임포트
from app.database import engine, Base
from app.api.auth import router as auth_router
from app.api.voice import router as voice_router
from app.api.ws import router as ws_router
from app.api.agent import router as agent_router # 기존 파일 유지 시

load_dotenv()

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AiCupid Backend API",
    description="""
API 문서입니다.

**WebSocket 연결 테스트:** [소켓 테스트 페이지](/docs/websocket-test)  
→ `/ws/quiz-text`, `/ws/live`, `/ws/audio` 연결·텍스트 전송·수신 로그 확인
""",
)

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


@app.get("/docs/websocket-test", response_class=HTMLResponse)
def docs_websocket_test():
    """WebSocket 엔드포인트 연결 테스트용 HTML 페이지 (docs에 링크됨)."""
    path = os.path.join(os.path.dirname(__file__), "static", "websocket-test.html")
    with open(path, encoding="utf-8") as f:
        return f.read()