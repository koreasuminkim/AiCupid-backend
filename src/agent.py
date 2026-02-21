"""
LangGraph Studio 진입점.
langgraph.json에서 "./src/agent.py:agent" 로 참조됩니다.
LangGraph API/Studio는 자체 persistence를 사용하므로 checkpointer를 넣지 않음.
"""
from ai_agent.graph import build_quiz_graph

# checkpointer 없이 컴파일 — LangGraph API가 플랫폼 persistence 사용
agent = build_quiz_graph().compile()
