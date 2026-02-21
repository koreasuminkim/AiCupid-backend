# LangGraph / LangSmith 스튜디오 구분

## 1. LangSmith (트레이싱 대시보드) — 다른 것

- **URL:** https://smith.langchain.com/
- **용도:** API 호출 기록(Runs), 트레이싱, 데이터셋, 평가
- **연동:** `.env`에 `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY=...` 설정 시 자동 기록
- **그래프 시각화/디버깅:** 여기서는 **안 됨**

---

## 2. LangSmith Studio (그래프 IDE) — 그래프 열 때 쓸 것

- **URL:** **반드시 아래 주소로 열기 (포트 2025 사용 — 다른 프로젝트와 겹치지 않음)**
  ```
  https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025
  ```
- **용도:** LangGraph **그래프 시각화**, 스레드 생성, 노드 단위 디버깅
- **사용 순서:**
  1. **AiCupid-backend** 폴더에서만 아래 명령 실행 (다른 프로젝트는 2024 쓰면 됨):
     ```bash
     langgraph dev --port 2025
     ```
  2. 로컬 서버가 `http://localhost:2025` 에 뜬 뒤, 브라우저에서 **위 URL(2025)** 로 접속
  3. 그래프 **aicupid_quiz** 선택 후, 초기 상태로 실행

- **주의:** `baseUrl=http://127.0.0.1:2025` 로 열어야 **이 프로젝트** 그래프만 보입니다.  
  (2024는 다른 프로젝트(quote-ai 등)가 쓸 수 있어서, AiCupid는 2025로 고정)

- **`[Errno 48] Address already in use` 가 나오면:** 2024 포트가 이미 사용 중입니다.  
  **반드시** `langgraph dev --port 2025` 또는 `./run-studio.sh` 로 실행하세요.

---

## 요약

| 구분           | LangSmith (트레이싱)     | LangSmith Studio (그래프 IDE)      |
| -------------- | ----------------------- | ---------------------------------- |
| URL            | smith.langchain.com     | smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025 |
| 사용 시점      | LANGCHAIN_API_KEY 설정 후 | `langgraph dev` 실행 후            |
| 하는 일        | Run/트레이스 보기       | 그래프 시각화, 스레드, 디버깅      |

**그래프를 보고 싶다면** → **AiCupid-backend**에서 `langgraph dev --port 2025` 실행 후,  
**https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025** 로만 접속하면 됩니다.

---

## 다른 프로젝트 그래프가 여전히 열릴 때

- **원인:** Studio가 2024 포트(다른 프로젝트)에 연결돼 있거나, 브라우저가 예전 baseUrl을 기억하고 있을 수 있음.
- **조치 (이 프로젝트만 보이게):**
  1. **AiCupid-backend** 폴더에서 **반드시 포트 2025** 로 실행:
     ```bash
     langgraph dev --port 2025
     ```
  2. 브라우저 주소창에 **아래를 직접 입력**해서 접속 (북마크/예전 링크 말고):
     ```
     https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025
     ```
  3. 그래프 목록에서 **aicupid_quiz** 선택.
- 2024가 아니라 **2025**로 접속해야 이 저장소의 그래프만 나옵니다.
