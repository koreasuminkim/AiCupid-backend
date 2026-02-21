import { GoogleGenAI, Modality } from "@google/genai";
import type { Session, LiveServerMessage } from "@google/genai";
import type { QuizQuestion, Message } from "./types";
import { MODELS, QUIZ, getPersonaPrompt } from "./config";

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });

// ── Callbacks for Live session events ────────────────────
export interface LiveCallbacks {
  onTranscript: (text: string) => void;
  onAudioChunk: (base64: string, mimeType: string, done: boolean) => void;
  onError: (error: Error) => void;
  onClose: () => void;
}

// ── Create a Gemini Live session (AUDIO mode) ─────────────
export async function createLiveSession(
  personaId: string,
  callbacks: LiveCallbacks
): Promise<Session> {
  const systemInstruction = getPersonaPrompt(personaId);

  const session = await ai.live.connect({
    model: MODELS.LIVE_AUDIO,
    config: {
      responseModalities: [Modality.AUDIO],
      systemInstruction: {
        parts: [{ text: systemInstruction }],
      },
      // Request transcription of user's speech
      inputAudioTranscription: {},
      // Disable server-side VAD so we can use activityStart/activityEnd manually.
      // sendClientContent({ turnComplete }) is not valid for native audio models.
      realtimeInputConfig: {
        automaticActivityDetection: { disabled: true },
      },
    },
    callbacks: {
      onopen: () => {
        console.log("[Gemini Live] Session opened");
      },

      onmessage: (msg: LiveServerMessage) => {
        // AI audio response chunks
        const parts = msg.serverContent?.modelTurn?.parts ?? [];
        for (const part of parts) {
          if (part.inlineData?.data) {
            const mimeType = part.inlineData.mimeType ?? "audio/pcm;rate=24000";
            callbacks.onAudioChunk(part.inlineData.data, mimeType, false);
          }
        }

        // AI turn complete
        if (msg.serverContent?.turnComplete) {
          callbacks.onAudioChunk("", "audio/pcm;rate=24000", true);
        }

        // User speech transcription
        const transcription = msg.serverContent?.inputTranscription;
        if (transcription?.text && transcription.finished) {
          callbacks.onTranscript(transcription.text);
        }
      },

      onerror: (e: ErrorEvent) => {
        callbacks.onError(new Error(e.message ?? "Gemini Live error"));
      },

      onclose: (e: CloseEvent) => {
        console.log(`[Gemini Live] Session closed (code=${e?.code}, reason=${e?.reason ?? "none"})`);
        callbacks.onClose();
      },
    },
  });

  return session;
}

// ── Send a PCM audio chunk to the live session ───────────
export function sendAudioChunk(session: Session, base64PCM: string): void {
  session.sendRealtimeInput({
    audio: {
      data: base64PCM,
      mimeType: "audio/pcm;rate=16000",
    },
  });
}

// ── Close the live session ───────────────────────────────
export function closeLiveSession(session: Session): void {
  try {
    session.close();
  } catch {
    // Already closed — ignore
  }
}

// ── Manual activity signals (replaces auto VAD) ──────────
// activityStart: 사용자 발화 시작 신호 (오디오 전송 전 호출)
export function sendActivityStart(session: Session): void {
  try {
    session.sendRealtimeInput({ activityStart: {} });
  } catch (err) {
    console.warn("[Gemini Live] sendActivityStart failed:", err);
  }
}

// activityEnd: 발화 종료 신호 → Gemini가 즉시 응답 생성 시작
// force_commit(아바타 탭) 또는 침묵 감지 시 호출됩니다.
export function sendActivityEnd(session: Session): void {
  try {
    session.sendRealtimeInput({ activityEnd: {} });
    console.log("[Gemini Live] Force-committed current audio turn");
  } catch (err) {
    console.warn("[Gemini Live] sendActivityEnd failed:", err);
  }
}

// ── Generate quiz from conversation history ──────────────
export async function generateQuiz(
  history: Message[]
): Promise<QuizQuestion[]> {
  const conversationText = [...history]
    .reverse()
    .slice(0, QUIZ.PROMPT_HISTORY_LIMIT)
    .map((m) => `${m.role === "user" ? "Guest" : "MC"}: ${m.content}`)
    .join("\n");

  const result = await ai.models.generateContent({
    model: MODELS.TEXT,
    contents: [
      {
        role: "user",
        parts: [{ text: QUIZ.GENERATION_PROMPT(conversationText) }],
      },
    ],
  });

  const raw = result.text?.trim() ?? "";
  const cleaned = raw
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/```\s*$/, "")
    .trim();

  try {
    return JSON.parse(cleaned) as QuizQuestion[];
  } catch {
    console.error("[Gemini] Quiz parse failed:", raw);
    return [];
  }
}
