import type WebSocket from "ws";
import type { Session } from "@google/genai";
import { v4 as uuidv4 } from "uuid";
import {
  createSession,
  addMessage,
  getMessages,
  getUserMessageCount,
  saveQuiz,
} from "./db";
import {
  createLiveSession,
  sendAudioChunk,
  closeLiveSession,
  sendActivityStart,
  sendActivityEnd,
  type LiveCallbacks,
} from "./gemini";
import {
  createTextLiveSession,
  type TextLiveCallbacks,
} from "./gemini-text";
import { supertoneTextToSpeech } from "./supertone";
import { QUIZ } from "./config";
import { EventEngine } from "./events/engine";
import { QuizRuleTrigger } from "./events/quiz-rule";
// import { QuizAgentTrigger } from "./events/quiz-agent";
import type { MCEvent } from "./events/types";
import type { ClientMessage, ServerMessage } from "./types";

function send(ws: WebSocket, msg: ServerMessage): void {
  if (ws.readyState === 1 /* OPEN */) {
    ws.send(JSON.stringify(msg));
  }
}

// ── 이벤트 엔진 ───────────────────────────────────────────────────
const eventEngine = new EventEngine()
  .register(new QuizRuleTrigger());
// .register(new QuizAgentTrigger({ minGap: 3 }))

// ── PCM-16 RMS 계산 (auto VAD 대체용) ─────────────────────
// base64 인코딩된 Int16 PCM 데이터의 RMS 에너지를 반환합니다.
// 클라이언트 ENERGY_THRESHOLD(0.012 normalized) 기준 → Int16 ≈ 400
const SPEECH_THRESHOLD = 400;
const SILENCE_TIMEOUT_MS = 600;

function calcPCMRMS(base64PCM: string): number {
  const buf = Buffer.from(base64PCM, "base64");
  const count = Math.floor(buf.length / 2);
  if (count === 0) return 0;
  let sum = 0;
  for (let i = 0; i < count; i++) {
    const s = buf.readInt16LE(i * 2);
    sum += s * s;
  }
  return Math.sqrt(sum / count);
}

export function handleConnection(ws: WebSocket): void {
  let sessionId: string | null = null;
  let personaId = "oracle";
  let ttsMode: "gemini" | "supertone" = "gemini";
  let geminiSession: Session | null = null;

  // Gemini inputAudioTranscription으로 받은 사용자 발화 텍스트
  let currentUserTranscript = "";

  // ── Manual VAD 상태 ────────────────────────────────────
  // auto VAD 비활성화 후 activityStart/End를 직접 관리합니다.
  let isActivityActive = false;
  let silenceTimer: ReturnType<typeof setTimeout> | null = null;

  console.log("[WS] Client connected");

  // ── Gemini Live (AUDIO mode) callbacks ───────────────────────
  const liveCallbacks: LiveCallbacks = {
    onTranscript: (text) => {
      currentUserTranscript = text;
      console.log(`[WS] User transcript: "${text}"`);
      send(ws, { type: "transcript", text });
      send(ws, { type: "avatar_state", state: "thinking" });
    },

    onAudioChunk: async (base64, mimeType, done) => {
      if (!done) {
        send(ws, { type: "ai_audio", data: base64, mimeType, done: false });
        send(ws, { type: "avatar_state", state: "speaking" });
      } else {
        send(ws, { type: "ai_audio", data: "", mimeType, done: true });
        send(ws, { type: "avatar_state", state: "listening" });
        await saveTurnAndDispatchEvents("[audio]");
        currentUserTranscript = "";
        // Gemini 응답 완료 → 다음 발화를 위해 activity 상태 초기화
        isActivityActive = false;
        if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
      }
    },

    onError: (err) => {
      console.error("[Gemini Live] Error:", err.message);
      send(ws, { type: "error", message: "Gemini Live session error" });
      send(ws, { type: "avatar_state", state: "idle" });
    },

    onClose: () => {
      console.log("[Gemini Live] Session closed");
      geminiSession = null;
    },
  };

  // ── Gemini Live (TEXT mode) + Supertone callbacks ─────────────
  const textLiveCallbacks: TextLiveCallbacks = {
    onTranscript: (text) => {
      currentUserTranscript = text;
      console.log(`[WS] User transcript: "${text}"`);
      send(ws, { type: "transcript", text });
      send(ws, { type: "avatar_state", state: "thinking" });
    },

    onTextResponse: async (text) => {
      send(ws, { type: "ai_text", text });
      send(ws, { type: "avatar_state", state: "speaking" });

      try {
        const audioBuffer = await supertoneTextToSpeech(text);
        const base64 = audioBuffer.toString("base64");
        send(ws, { type: "ai_audio", data: base64, mimeType: "audio/mpeg", done: false });
        send(ws, { type: "ai_audio", data: "", mimeType: "audio/mpeg", done: true });
      } catch (err) {
        console.error("[Supertone] TTS failed:", err);
        send(ws, { type: "error", message: "Supertone TTS failed" });
      }

      send(ws, { type: "avatar_state", state: "listening" });
      await saveTurnAndDispatchEvents(text);
      currentUserTranscript = "";
    },

    onError: (err) => {
      console.error("[Gemini Text Live] Error:", err.message);
      send(ws, { type: "error", message: "Gemini Text Live session error" });
      send(ws, { type: "avatar_state", state: "idle" });
    },

    onClose: () => {
      console.log("[Gemini Text Live] Session closed");
      geminiSession = null;
    },
  };

  // ── 턴 완료: DB 저장(STT 전사 텍스트) + 이벤트 엔진 ──────────────
  // currentUserTranscript 는 Gemini inputAudioTranscription 결과물.
  // DB에 사용자 발화 텍스트를 저장하므로 퀴즈 생성 등 컨텍스트로 활용됩니다.
  async function saveTurnAndDispatchEvents(aiMessage: string) {
    if (!sessionId || !currentUserTranscript) return;

    addMessage(sessionId, "user", currentUserTranscript);
    addMessage(sessionId, "assistant", aiMessage);
    console.log(`[WS] Turn saved — user: "${currentUserTranscript.slice(0, 60)}"`);

    const messageCount = getUserMessageCount(sessionId);
    const history = getMessages(sessionId, QUIZ.HISTORY_WINDOW);

    const events = await eventEngine.processTurn({
      sessionId,
      userMessage: currentUserTranscript,
      aiMessage,
      messageCount,
      history,
    });

    for (const event of events) {
      await dispatchEvent(event);
    }
  }

  async function dispatchEvent(event: MCEvent) {
    switch (event.type) {
      case "quiz": {
        const { payload: questions } = event;
        saveQuiz(sessionId!, questions);
        send(ws, { type: "quiz", questions });
        console.log(`[WS] Quiz dispatched: ${questions.length} question(s)`);
        break;
      }
    }
  }

  // ── WebSocket message handler ─────────────────────────────────
  ws.on("message", async (raw) => {
    let msg: ClientMessage;
    try {
      msg = JSON.parse(raw.toString()) as ClientMessage;
    } catch {
      send(ws, { type: "error", message: "Invalid JSON payload" });
      return;
    }

    switch (msg.type) {
      case "init": {
        if (geminiSession) {
          closeLiveSession(geminiSession);
          geminiSession = null;
        }

        sessionId = uuidv4();
        personaId = msg.personaId ?? "oracle";
        ttsMode = msg.ttsMode ?? "gemini";
        createSession(sessionId, personaId);

        console.log(`[WS] Session starting: ${sessionId} (${personaId}) mode=${ttsMode}`);

        try {
          if (ttsMode === "supertone") {
            geminiSession = await createTextLiveSession(personaId, textLiveCallbacks);
          } else {
            geminiSession = await createLiveSession(personaId, liveCallbacks);
          }

          send(ws, { type: "session_ready", sessionId });
          send(ws, { type: "avatar_state", state: "listening" });
          console.log(`[WS] Session ready: ${sessionId}`);
        } catch (err) {
          console.error("[WS] Failed to create Gemini session:", err);
          send(ws, { type: "error", message: "Failed to connect to Gemini Live" });
        }
        break;
      }

      case "audio_chunk": {
        if (!geminiSession) return;

        const energy = calcPCMRMS(msg.data);

        if (energy > SPEECH_THRESHOLD) {
          // 발화 감지: 침묵 타이머 리셋
          if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }

          // 새 발화 시작 시 activityStart 전송
          if (!isActivityActive) {
            sendActivityStart(geminiSession);
            isActivityActive = true;
          }

          // 침묵 감지 타이머 설정 (600ms 무음 → activityEnd)
          silenceTimer = setTimeout(() => {
            silenceTimer = null;
            if (geminiSession && isActivityActive) {
              sendActivityEnd(geminiSession);
              isActivityActive = false;
            }
          }, SILENCE_TIMEOUT_MS);
        }

        // activity 활성 구간의 오디오만 전송
        if (isActivityActive) {
          sendAudioChunk(geminiSession, msg.data);
        }
        break;
      }

      case "force_commit": {
        if (!geminiSession) return;
        // 침묵 타이머 취소 후 즉시 activityEnd (발화 중일 때만)
        if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
        if (isActivityActive) {
          sendActivityEnd(geminiSession);
          isActivityActive = false;
        }
        send(ws, { type: "avatar_state", state: "thinking" });
        break;
      }

      case "quiz_answer": {
        console.log(`[WS] Quiz answer — q:${msg.questionId} idx:${msg.answerIndex}`);
        break;
      }

      default: {
        send(ws, { type: "error", message: `Unknown message type` });
      }
    }
  });

  ws.on("close", () => {
    console.log(`[WS] Disconnected (session: ${sessionId ?? "none"})`);
    if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
    if (geminiSession) {
      closeLiveSession(geminiSession);
      geminiSession = null;
    }
  });

  ws.on("error", (err) => {
    console.error("[WS] Socket error:", err);
  });
}
