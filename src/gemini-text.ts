import { GoogleGenAI, Modality } from "@google/genai";
import type { Session, LiveServerMessage } from "@google/genai";
import { MODELS, getPersonaPrompt } from "./config";

// gemini-2.0-flash-live-001 is only available on v1alpha, not v1beta
const ai = new GoogleGenAI({
    apiKey: process.env.GEMINI_API_KEY!,
    httpOptions: { apiVersion: "v1alpha" },
});

// ── Callbacks for text-mode Live session ─────────────────
export interface TextLiveCallbacks {
    onTranscript: (text: string) => void;
    /** Called when a full AI text response turn is complete */
    onTextResponse: (text: string) => void;
    onError: (error: Error) => void;
    onClose: () => void;
}

/**
 * Create a Gemini Live session that produces TEXT output only.
 * Used when the client requested ttsMode = "supertone".
 * The caller is responsible for converting the text to audio via Supertone.
 */
export async function createTextLiveSession(
    personaId: string,
    callbacks: TextLiveCallbacks
): Promise<Session> {
    const systemInstruction = getPersonaPrompt(personaId);

    // Accumulate model text turn
    let currentTextTurn = "";

    const session = await ai.live.connect({
        model: MODELS.LIVE_TEXT,
        config: {
            responseModalities: [Modality.TEXT],
            systemInstruction: {
                parts: [{ text: systemInstruction }],
            },
            inputAudioTranscription: {},
        },
        callbacks: {
            onopen: () => {
                console.log("[Gemini Text Live] Session opened");
            },

            onmessage: (msg: LiveServerMessage) => {
                // Accumulate text parts from the model
                const parts = msg.serverContent?.modelTurn?.parts ?? [];
                for (const part of parts) {
                    if (part.text) {
                        currentTextTurn += part.text;
                    }
                }

                // Turn complete → emit full text response
                if (msg.serverContent?.turnComplete) {
                    const text = currentTextTurn.trim();
                    currentTextTurn = "";
                    if (text) {
                        console.log(
                            `[Gemini Text Live] AI response: "${text.slice(0, 80)}"`
                        );
                        callbacks.onTextResponse(text);
                    }
                }

                // User speech transcription
                const transcription = msg.serverContent?.inputTranscription;
                if (transcription?.text && transcription.finished) {
                    callbacks.onTranscript(transcription.text);
                }
            },

            onerror: (e: ErrorEvent) => {
                callbacks.onError(new Error(e.message ?? "Gemini Text Live error"));
            },

            onclose: (e: CloseEvent) => {
                console.log(
                    `[Gemini Text Live] Session closed (code=${e?.code}, reason=${e?.reason ?? "none"})`
                );
                callbacks.onClose();
            },
        },
    });

    return session;
}
