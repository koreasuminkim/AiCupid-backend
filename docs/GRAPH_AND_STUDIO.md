# 그래프에 넘어가는 로직 & LangGraph Studio 테스트

## 1. 그래프로 넘어가는 로직 (입력 구조)

`ainvoke`로 에이전트에 넘기는 값은 **그래프 상태(AgentState)** 한 덩어리입니다.

### 상태 스키마 (AgentState)

| 필드 | 타입 | 설명 |
|------|------|------|
| **messages** | `list` of `(role, content)` | 대화 목록. `("user", "텍스트")` / `("ai", "텍스트")`. `operator.add`로 누적됨 |
| **question_id** | int | 현재 퀴즈 문항 인덱스 (0부터). 없으면 0 |
| **score** | int | 현재까지 맞힌 개수. 없으면 0 |
| **next_action** | str | 내부용. router가 "grade" / "ask" / "chat" / "finish" 중 하나로 설정 |

### 소켓 → 그래프로 넘길 때 (ws/quiz)

```python
# app/api/ws.py
result = await runnable.ainvoke(
    {"messages": [("user", transcript)]},  # STT 결과 한 줄만 넣음
    config=config
)
```

- **실제로 넘기는 것:** `{"messages": [("user", "사용자가 말한 내용")]}`
- `question_id`, `score`는 안 넘기므로 **매 턴 0으로 시작** (현재는 세션 간 퀴즈 진행 상태 유지 안 함).

### 그래프 안에서의 흐름 (로직)

1. **진입:** 항상 **router** 노드부터 실행.
2. **router_node**
   - `state["messages"]`의 **마지막 메시지** 내용으로 분기:
     - `"퀴즈" in 내용 and "시작" in 내용` → **ask** (첫 질문 내기)
     - 그 외, `question_id < len(quiz_data)` 이고 **직전이 AI 질문**이면 → **grade** (방금 user 메시지를 답안으로 채점)
     - 그 외, `question_id < len(quiz_data)` → **ask** (다음 질문)
     - 퀴즈 다 끝났으면 → **finish**
     - 나머지 → **chat** (일반 대화)
3. **grade_answer_node**  
   → `QuizGrader`로 마지막 user 메시지 채점 → 정답/오답 메시지 추가, `score`/`question_id` 갱신.
4. **ask_question_node**  
   → `QuestionProvider`로 `question_id`번 질문 문자열 가져와서 메시지로 추가.
5. **chat_node**  
   → `get_llm().invoke(messages)` 로 **지금까지 messages 전체**를 LLM에 넘겨서 일반 답변 생성.
6. **finish**  
   → 그래프 종료.

정리하면, **그래프에 넘어가는 로직**은  
「**messages + (선택) question_id, score**」이고,  
**router**가 이걸 보고 **grade / ask / chat / finish** 중 다음 노드를 고르고,  
각 노드가 **messages**와 **question_id, score**를 갱신하는 구조입니다.

---

## 2. LangGraph Studio에서 테스트하기

`ainvoke`로 넘기는 것과 **같은 그래프**를 Studio에서 돌릴 수 있습니다.

### 전제

- `langgraph.json`에 **aicupid_quiz** 그래프가 `./src/agent.py:agent` 로 등록돼 있음.
- `src/agent.py`는 `ai_agent.graph.build_quiz_graph().compile()` 을 그대로 쓰므로, **웹소켓에서 쓰는 그래프와 동일**합니다.

### 실행 순서

1. **백엔드에서 LangGraph 개발 서버 실행 (AiCupid-backend 폴더에서)**

   ```bash
   langgraph dev --port 2025
   ```

2. **브라우저에서 Studio 열기**

   ```
   https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025
   ```

3. **그래프 선택**  
   목록에서 **aicupid_quiz** 선택.

4. **입력(Initial state) 설정**  
   스튜디오에서 그래프 실행 시 넣는 값 = `ainvoke`의 첫 인자와 같은 형태로 넣으면 됨.

   **예시 (한 턴만 테스트):**

   ```json
   {
     "messages": [["user", "퀴즈 시작"]]
   }
   ```

   또는:

   ```json
   {
     "messages": [["user", "서울"]]
   }
   ```

   - `"퀴즈 시작"` → router가 **ask** 선택 → 첫 질문 나옴.
   - `"서울"` (이전에 AI가 “대한민국 수도는?”이라고 했다고 가정) → **grade** → 채점 후 메시지/score 갱신.

   필요하면 `question_id`, `score`도 넣어서 테스트 가능:

   ```json
   {
     "messages": [["ai", "퀴즈 질문입니다: 대한민국의 수도는 어디인가요?"], ["user", "서울"]],
     "question_id": 0,
     "score": 0
   }
   ```

5. **실행**  
   Run 버튼으로 실행하면, 노드별 입출력과 최종 state를 Studio에서 확인할 수 있음.  
   → **ainvoke로 에이전트에 넘기는 로직**을 그대로 Studio에서 재현·디버깅할 수 있습니다.

### 요약

- **그래프로 넘어가는 로직:**  
  `messages` (필수) + 선택적으로 `question_id`, `score`.  
  router가 이걸 보고 **grade / ask / chat / finish**로 분기하고, 각 노드가 메시지·점수·문항 번호를 갱신.
- **Studio에서 테스트:**  
  `langgraph dev --port 2025` → Studio에서 `baseUrl=http://127.0.0.1:2025` 로 접속 → **aicupid_quiz** 선택 → 위와 같은 형태로 **messages**(와 필요 시 question_id, score) 넣고 Run 하면, `ainvoke`와 동일한 그래프를 Studio에서 테스트할 수 있음.
