// Shared types between ws-handler, gemini, and db layers

export interface QuizQuestion {
  id: string;
  question: string;
  answers: string[];
  correctIndex: number;
  timeLimit: number;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

// ── Client → Server ──────────────────────────────────────
export type ClientMessage =
  | { type: "init"; personaId: string; ttsMode?: "gemini" | "supertone" }
  | { type: "audio_chunk"; data: string }
  | { type: "force_commit" }
  | { type: "quiz_answer"; sessionId: string; questionId: string; answerIndex: number };

// ── Server → Client ──────────────────────────────────────
export type ServerMessage =
  | { type: "session_ready"; sessionId: string }
  | { type: "transcript"; text: string }
  | { type: "ai_text"; text: string }
  | { type: "ai_audio"; data: string; mimeType: string; done: boolean }
  | { type: "avatar_state"; state: "idle" | "listening" | "speaking" | "thinking" }
  | { type: "quiz"; questions: QuizQuestion[] }
  | { type: "error"; message: string };
