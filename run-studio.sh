#!/usr/bin/env bash
# AiCupid LangGraph Studio — 포트 2025 사용 (2024는 다른 프로젝트가 사용 중일 수 있음)
cd "$(dirname "$0")"
echo "▶ 포트 2025에서 실행합니다 (2024 충돌 방지)."
echo "▶ Studio 주소 (브라우저에서 열기):"
echo ""
echo "   https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025"
echo ""
exec langgraph dev --port 2025
