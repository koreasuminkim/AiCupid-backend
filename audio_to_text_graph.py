"""
음성 파일 → 텍스트 변환 LangGraph.
Gemini로 오디오를 전사(transcribe)합니다.
"""

from __future__ import annotations

import os
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class AudioToTextState(TypedDict):
    """오디오 → 텍스트 그래프 상태."""

    audio_bytes: bytes
    mime_type: str
    text: str
    error: str


def _transcribe_node(state: AudioToTextState) -> dict:
    """Gemini로 오디오를 텍스트로 변환."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"text": "", "error": "GEMINI_API_KEY not set"}

    audio_bytes = state.get("audio_bytes") or b""
    mime_type = (state.get("mime_type") or "audio/wav").strip().lower()
    if not audio_bytes:
        return {"text": "", "error": "No audio data"}

    try:
        client = genai.Client(api_key=api_key)
        prompt = "Transcribe this audio to text. Output only the transcribed text, in the same language as the speech. Do not add any explanation."
        try:
            part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        except (AttributeError, TypeError):
            blob = types.Blob(data=audio_bytes, mime_type=mime_type)
            part = types.Part(inline_data=blob)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, part],
        )
        text = (response.text or "").strip()
        return {"text": text, "error": ""}
    except Exception as e:
        return {"text": "", "error": str(e)}


def build_audio_to_text_graph() -> StateGraph:
    """오디오 → 텍스트 LangGraph 빌드."""
    workflow = StateGraph(AudioToTextState)
    workflow.add_node("transcribe", _transcribe_node)
    workflow.add_edge(START, "transcribe")
    workflow.add_edge("transcribe", END)
    return workflow


def get_audio_to_text_runnable():
    """컴파일된 그래프 반환 (캐시)."""
    return build_audio_to_text_graph().compile()


# LangGraph Studio(langgraph dev)에서 로드할 그래프 — langgraph.json에서 참조
agent = build_audio_to_text_graph().compile()
