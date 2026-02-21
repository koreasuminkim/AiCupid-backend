import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

# API 라우터 임포트
from app.database import engine, Base
from app.models.voice_session import VoiceSession  # 테이블 생성 위해 import
from app.models.voice_conversation_turn import VoiceConversationTurn
from app.models.four_choice_question import FourChoiceQuestion
from app.models.balance_game_question import BalanceGameQuestion
from app.api.auth import router as auth_router
from app.api.voice import router as voice_router
from app.api.ws import router as ws_router
from app.api.agent import router as agent_router # 기존 파일 유지 시
from app.api.users import router as users_router
from app.api.after_note import router as after_router # 임포트 추가
from app.models.after_note import AfterNote

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

# CORS (allow_credentials=True 일 때는 allow_origins에 "*" 불가 → 구체적 origin 사용)
_frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000").strip()
_cors_origins = [
    _frontend_origin,
    "https://aicupid-frontend.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",   # Vite 기본
    "http://127.0.0.1:5173",
]
# 중복 제거, 빈 문자열 제거
_cors_origins = list(dict.fromkeys(o for o in _cors_origins if o))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# 라우터 등록
app.include_router(auth_router, prefix="/api/auth")
app.include_router(voice_router, prefix="/api") # /api/voice/...
app.include_router(agent_router)               # 이미 /agent prefix 있음
app.include_router(ws_router)                  # /ws/quiz
app.include_router(users_router)
app.include_router(after_router)

@app.get("/")
def read_root():
    return {"service": "AiCupid-backend", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.on_event("startup")
async def startup_event():
    # LangGraph 전용 체크포인트 테이블 생성 (Postgres 사용 시 필수)
    if not SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        from services.agent import memory
        memory.setup()


@app.get("/docs/websocket-test", response_class=HTMLResponse)
def docs_websocket_test():
    """WebSocket 엔드포인트 연결 테스트용 HTML 페이지 (docs에 링크됨)."""
    path = os.path.join(os.path.dirname(__file__), "static", "websocket-test.html")
    with open(path, encoding="utf-8") as f:
        return f.read()