# AIMC Backend

WebSocket 서버. Gemini Live API를 통해 실시간 AI MC 음성 대화를 처리하고, Supertone TTS 모드를 지원합니다.

## 기술 스택

| 레이어           | 기술                                      |
| ---------------- | ----------------------------------------- |
| 런타임           | Node.js + TypeScript (`tsx`)              |
| 웹 프레임워크    | Express                                   |
| 실시간 통신      | WebSocket (`ws`)                          |
| AI (오디오 모드) | Gemini Live API — 음성 직접 생성          |
| AI (텍스트 모드) | Gemini Live API TEXT + Supertone REST TTS |
| DB               | SQLite (`better-sqlite3`)                 |

## 디렉터리 구조

```
backend/
├── src/
│   ├── config.ts        ← ✏️  동작 설정 (페르소나·모델·퀴즈·Supertone)
│   ├── index.ts         ← 서버 진입점 (Express + WebSocketServer)
│   ├── ws-handler.ts    ← WebSocket 연결 처리 & 이벤트 디스패치
│   ├── gemini.ts        ← Gemini Live AUDIO 세션
│   ├── gemini-text.ts   ← Gemini Live TEXT 세션 (Supertone 모드)
│   ├── supertone.ts     ← Supertone REST TTS 호출
│   ├── db.ts            ← SQLite CRUD
│   ├── types.ts         ← WebSocket 메시지 타입
│   └── events/          ← 이벤트 엔진
│       ├── types.ts     ← TurnContext, MCEvent 유니온, EventTrigger 인터페이스
│       ├── engine.ts    ← 트리거 플러그인 레지스트리 & 코디네이터
│       ├── quiz-rule.ts ← 룰 기반 퀴즈 트리거 (매 N턴)
│       └── quiz-agent.ts← LLM 에이전트 기반 퀴즈 트리거
└── .env                 ← API 키 (아래 참조)
```

## 이벤트 엔진 (`src/events/`)

매 대화 턴이 끝날 때마다 등록된 **EventTrigger** 플러그인들이 병렬로 실행됩니다.
트리거가 이벤트를 발화해야 한다고 판단하면 `MCEvent`를 반환하고, `ws-handler.ts`가 이를 클라이언트로 전송합니다.

### 새 이벤트 추가하기

**1. `events/types.ts`에 이벤트 타입 추가**
```ts
export type MCEvent =
  | { type: "quiz"; payload: QuizQuestion[] }
  | { type: "crowd_cheer"; payload: { intensity: number } }  // ← 추가
  ;
```

**2. 트리거 파일 생성**
```ts
// events/crowd-cheer-rule.ts
export class CrowdCheerTrigger implements EventTrigger {
  readonly name = "crowd-cheer-rule";
  async onTurn(ctx: TurnContext): Promise<MCEvent | null> {
    // 판단 로직 ...
    return { type: "crowd_cheer", payload: { intensity: 0.8 } };
  }
}
```

**3. `ws-handler.ts`에 등록 & 처리**
```ts
// 등록
const eventEngine = new EventEngine()
  .register(new QuizRuleTrigger())
  .register(new CrowdCheerTrigger());  // ← 추가

// dispatchEvent() 에 case 추가
case "crowd_cheer": { send(ws, { type: "crowd_cheer", ...event.payload }); break; }
```

### 룰 베이스 ↔ LLM 에이전트 전환

`ws-handler.ts` 상단의 주석을 토글하면 됩니다:

```ts
const eventEngine = new EventEngine()
  .register(new QuizRuleTrigger());      // 룰 기반
  // .register(new QuizAgentTrigger());  // LLM 에이전트
```

## 설정 파일 (`src/config.ts`)

**동작을 바꾸고 싶을 때는 이 파일만 수정하세요.**

| 섹션        | 내용                                               |
| ----------- | -------------------------------------------------- |
| `MODELS`    | Gemini 모델 이름 (Live Audio / Live Text / Quiz용) |
| `SUPERTONE` | TTS 언어·스타일·모델                               |
| `QUIZ`      | 퀴즈 트리거 주기, 히스토리 창 크기, 생성 프롬프트  |
| `PERSONAS`  | AI MC 페르소나 이름 + 시스템 프롬프트              |

페르소나 추가 예시:

```ts
// src/config.ts
export const PERSONAS: Record<string, PersonaConfig> = {
  // ... 기존 페르소나
  comedian: {
    name: "The Comedian",
    prompt: `You are a stand-up comedian MC. ...`,
  },
};
```

## 환경 변수 (`.env`)

```env
GEMINI_API_KEY=<Gemini API 키>
SUPERTONE_API_KEY=<Supertone API 키>
SUPERTONE_VOICE_ID=<Supertone 보이스 ID>
PORT=8080                          # 선택 (기본: 8080)
FRONTEND_ORIGIN=http://localhost:3000  # 선택 (CORS)
```

## 실행

```bash
# 개발 (파일 변경 시 자동 재시작)
npm run dev

# 프로덕션 빌드 & 실행
npm run build
npm start
```

## WebSocket 프로토콜

### Client → Server

| 타입          | 설명                                                           |
| ------------- | -------------------------------------------------------------- |
| `init`        | 세션 시작. `personaId`, `ttsMode?("gemini"\|"supertone")` 포함 |
| `audio_chunk` | PCM 16kHz Base64 청크 (마이크 스트리밍)                        |
| `quiz_answer` | 퀴즈 답변 제출                                                 |

### Server → Client

| 타입            | 설명                                        |
| --------------- | ------------------------------------------- |
| `session_ready` | 세션 준비 완료                              |
| `transcript`    | 사용자 발화 텍스트 (STT)                    |
| `ai_text`       | AI 텍스트 응답 (Supertone 모드)             |
| `ai_audio`      | AI 오디오 청크 (`done:true`로 턴 종료 신호) |
| `avatar_state`  | `idle\|listening\|thinking\|speaking`       |
| `quiz`          | 퀴즈 문제 배열                              |
| `error`         | 에러 메시지                                 |

## TTS 모드 비교

|                   | Gemini Live 모드  | Supertone 모드             |
| ----------------- | ----------------- | -------------------------- |
| `ttsMode`         | `"gemini"` (기본) | `"supertone"`              |
| 오디오 형식       | PCM 24kHz         | MP3                        |
| 지연              | 낮음 (스트리밍)   | 보통 (REST 호출)           |
| 음성 커스터마이징 | Gemini 기본음     | Supertone 보이스 선택 가능 |
