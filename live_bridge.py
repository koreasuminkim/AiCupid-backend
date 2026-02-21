"""
Gemini Live API WebSocket 브리지.
프론트에서 받은 음성 청크를 Live API로 전달하고, 응답 오디오/텍스트를 프론트로 전달.

- 입력: 16-bit PCM, 16kHz, mono (프론트에서 끊어서 전송)
- 출력: 24kHz 오디오 (Live API 기본)
- 참고: https://ai.google.dev/gemini-api/docs/live
"""

from __future__ import annotations

import asyncio
import base64
import json
import os

# GEMINI_API_KEY는 .env에서 로드된 상태여야 함


# Live API 모델 (네이티브 오디오 지원)
LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

# 기본 시스템 지시 (ai_agent.prompts.SYSTEM_PROMPT와 통일 가능)
DEFAULT_SYSTEM_INSTRUCTION = """당신은 AiCupid 퀴즈·대화 에이전트입니다.
사용자와 퀴즈를 진행하거나, 퀴즈와 무관한 대화를 할 수 있습니다.
답변은 친근하고 짧게, 한국어로 해 주세요. 음성으로 자연스럽게 답해 주세요."""


def get_system_instruction_from_langchain() -> str:
    """LangChain(ai_agent) 시스템 프롬프트를 Live용으로 사용."""
    try:
        from ai_agent.prompts import SYSTEM_PROMPT
        return SYSTEM_PROMPT + " 음성으로 자연스럽게 답해 주세요."
    except Exception:
        return DEFAULT_SYSTEM_INSTRUCTION


async def run_live_session(websocket, system_instruction: str | None = None, use_langchain_prompt: bool = True):
    """
    WebSocket과 Gemini Live API를 연결합니다.
    - websocket: FastAPI WebSocket 인스턴스
    - system_instruction: None이면 use_langchain_prompt=True 시 ai_agent.prompts 사용
    - 프론트 → 백: binary(PCM) 또는 JSON {"audio": "base64..."}
    - 백 → 프론트: JSON {"type": "audio", "data": "base64"} / {"type": "text", "text": "..."} / {"type": "error"} / {"type": "done"}
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        await websocket.send_json({"type": "error", "text": "GEMINI_API_KEY not set"})
        return

    if system_instruction is None and use_langchain_prompt:
        instruction = get_system_instruction_from_langchain()
    else:
        instruction = system_instruction or DEFAULT_SYSTEM_INSTRUCTION
    config = {
        "response_modalities": ["AUDIO"],
        "system_instruction": instruction,
    }

    client = genai.Client(api_key=api_key)
    audio_queue_to_live = asyncio.Queue(maxsize=64)

    async def send_audio_to_live(session):
        """WebSocket에서 받은 오디오를 Live API로 전달."""
        try:
            while True:
                chunk = await audio_queue_to_live.get()
                if chunk is None:
                    break
                await session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await websocket.send_json({"type": "error", "text": str(e)})

    async def receive_from_live(session):
        """Live API 응답을 WebSocket으로 전달 (오디오 base64, 텍스트)."""
        try:
            async for message in session.receive():
                if not message:
                    continue
                sc = getattr(message, "server_content", None)
                if not sc:
                    continue
                if getattr(sc, "interrupted", False):
                    await websocket.send_json({"type": "interrupted"})
                    continue
                mt = getattr(sc, "model_turn", None)
                if not mt:
                    continue
                parts = getattr(mt, "parts", None) or []
                for part in parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        data = inline.data
                        if isinstance(data, bytes):
                            b64 = base64.b64encode(data).decode("ascii")
                            await websocket.send_json({"type": "audio", "data": b64})
                    if getattr(part, "text", None):
                        await websocket.send_json({"type": "text", "text": part.text})
            await websocket.send_json({"type": "done"})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await websocket.send_json({"type": "error", "text": str(e)})

    async def read_from_websocket():
        """WebSocket에서 오디오 청크 수신 → 큐에 넣음."""
        try:
            while True:
                raw = await websocket.receive()
                if raw.get("type") == "websocket.disconnect":
                    break
                if "bytes" in raw and raw["bytes"]:
                    await audio_queue_to_live.put(bytes(raw["bytes"]))
                elif "text" in raw:
                    try:
                        obj = json.loads(raw["text"])
                        if "audio" in obj:
                            chunk = base64.b64decode(obj["audio"])
                            await audio_queue_to_live.put(chunk)
                    except (json.JSONDecodeError, KeyError):
                        pass
            await audio_queue_to_live.put(None)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await audio_queue_to_live.put(None)
            await websocket.send_json({"type": "error", "text": str(e)})

    try:
        async with client.aio.live.connect(
            model=LIVE_MODEL,
            config=config,
        ) as session:
            await websocket.send_json({"type": "connected", "model": LIVE_MODEL})

            send_task = asyncio.create_task(send_audio_to_live(session))
            recv_task = asyncio.create_task(receive_from_live(session))
            ws_task = asyncio.create_task(read_from_websocket())

            await asyncio.gather(ws_task, recv_task)
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)})
