/**
 * ╔══════════════════════════════════════════════════════╗
 * ║              AIMC  –  Configuration                  ║
 * ║  모든 동작 관련 상수를 이 파일에서 관리합니다.           ║
 * ╚══════════════════════════════════════════════════════╝
 */

// ── AI Models ─────────────────────────────────────────────
export const MODELS = {
    /** Gemini Live (audio streaming + built-in VAD) */
    LIVE_AUDIO: "gemini-2.5-flash-native-audio-preview-12-2025",
    /** Gemini Live (text output, for Supertone TTS mode) */
    LIVE_TEXT: "gemini-2.0-flash-live-001",
    /** Standard text model — quiz generation etc. */
    TEXT: "gemini-2.0-flash",
} as const;

// ── Supertone TTS ─────────────────────────────────────────
export const SUPERTONE = {
    BASE_URL: "https://supertoneapi.com",
    /** TTS synthesis language code */
    LANGUAGE: "ko",
    /** Voice style — see Supertone docs for options */
    STYLE: "neutral",
    /** TTS model */
    MODEL: "sona_speech_1",
} as const;

// ── Quiz ──────────────────────────────────────────────────
export const QUIZ = {
    /** Trigger a quiz every N user messages */
    TRIGGER_EVERY_N_MESSAGES: 5,
    /** How many recent messages to include in quiz context */
    HISTORY_WINDOW: 20,
    /** Max conversation turns fed into the quiz generation prompt */
    PROMPT_HISTORY_LIMIT: 12,
    /** Prompt sent to the text model for quiz generation */
    GENERATION_PROMPT: (conversationText: string) =>
        `Based on this conversation, create 1-2 trivia quiz questions about topics that were discussed.
Return ONLY a JSON array (no markdown):
[{"id":"q1","question":"...","answers":["A","B","C","D"],"correctIndex":0,"timeLimit":20}]

Conversation:
${conversationText}`,
} as const;

// ── Persona System Prompts ────────────────────────────────
/**
 * Each persona defines:
 *   - name:   display name
 *   - prompt: system instruction sent to Gemini
 *
 * Add or edit personas here — no other file needs to change.
 */
export interface PersonaConfig {
    name: string;
    prompt: string;
}

export const PERSONAS: Record<string, PersonaConfig> = {
    hypebot: {
        name: "HypeBot",
        prompt: `You are HypeBot, an ultra-high-energy AI MC. Use short punchy sentences, occasional ALL CAPS for emphasis, and lots of enthusiasm. Keep every response to 2-3 sentences max. You're hosting a live event and love engaging the crowd.`,
    },

    oracle: {
        name: "The Oracle",
        prompt: `You are The Oracle, a calm, philosophical AI MC who speaks with measured wisdom. Use thoughtful metaphors and reflective language. Keep every response to 2-3 sentences max.`,
    },

    roastmaster: {
        name: "Roastmaster",
        prompt: `You are the Roastmaster, an edgy comedic AI MC who lightly roasts everything with wit. Keep jokes sharp but never mean. Keep every response to 2-3 sentences max.`,
    },

    narrator: {
        name: "The Narrator",
        prompt: `You are The Narrator, a dramatic storytelling AI MC. Frame everything as an epic tale with vivid language and dramatic pauses (marked with '...'). Keep every response to 2-3 sentences max.`,
    },
};

/** Returns the system prompt for a given persona ID (falls back to oracle). */
export function getPersonaPrompt(personaId: string): string {
    return (PERSONAS[personaId] ?? PERSONAS.oracle).prompt;
}
