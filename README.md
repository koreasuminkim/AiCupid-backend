# AiCupid Backend

실시간 음성 대화 AI MC 백엔드입니다.  
STT(음성→텍스트) → LLM(텍스트→응답 생성) → TTS(텍스트→음성) 파이프라인을 통해 대화가 이루어집니다.

## 주요 특징 및 구조

- FastAPI 기반 Python 서버
- WebSocket을 통한 실시간 음성/텍스트 대화
- STT, LLM, TTS(예: Gemini, Supertone 등) 연동
- SQLite 기반 데이터베이스

### 처리 흐름

1. **STT**: 사용자의 음성 입력을 텍스트로 변환
2. **LLM**: 텍스트 입력을 받아 AI 응답 생성
3. **TTS**: 생성된 텍스트를 음성으로 변환하여 사용자에게 전달

이 과정에서 각 단계의 처리 시간이 누적되어 입력~출력 간 지연이 발생할 수 있습니다.

## 디렉터리 구조

```
.
├── main.py                # FastAPI 진입점
├── audio_to_text_graph.py # STT 처리
├── ai_agent/              # LLM/에이전트 관련 코드
├── services/              # TTS, S3 등 외부 서비스 연동
├── app/                   # API, DB, 모델, 스키마 등
├── static/                # 정적 파일
├── requirements.txt       # Python 패키지 목록
└── ...
```
