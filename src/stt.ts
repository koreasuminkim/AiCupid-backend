/**
 * ─────────────────────────────────────────────────────────────────
 *  Background STT (Speech-to-Text)
 * ─────────────────────────────────────────────────────────────────
 *
 *  AI가 응답을 생성하는 동안 사용자의 발화를 PCM 청크 배열로 받아
 *  Gemini에게 전사를 요청합니다.
 *  결과 텍스트는 다음 턴의 컨텍스트로만 주입됩니다 (새 응답 미트리거).
 * ─────────────────────────────────────────────────────────────────
 */

import { GoogleGenAI } from "@google/genai";
import { MODELS } from "./config";

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });

/**
 * base64 PCM 16kHz 모노 청크 배열을 합쳐 Gemini로 전사합니다.
 * 무음이거나 내용이 없으면 빈 문자열을 반환합니다.
 */
export async function transcribeBackgroundAudio(
    base64Chunks: string[]
): Promise<string> {
    if (base64Chunks.length === 0) return "";

    // 모든 청크를 하나의 버퍼로 합산
    const buffers = base64Chunks.map((c) => Buffer.from(c, "base64"));
    const combined = Buffer.concat(buffers);
    const combinedBase64 = combined.toString("base64");

    console.log(
        `[STT] Transcribing background audio — ${(combined.byteLength / 1024).toFixed(1)} KB`
    );

    try {
        const result = await ai.models.generateContent({
            model: MODELS.TEXT,
            contents: [
                {
                    role: "user",
                    parts: [
                        {
                            text: "Transcribe the following audio exactly. Return ONLY the transcription text. If the audio is silent or unclear, return an empty string.",
                        },
                        {
                            inlineData: {
                                mimeType: "audio/pcm;rate=16000",
                                data: combinedBase64,
                            },
                        },
                    ],
                },
            ],
        });

        const text = result.text?.trim() ?? "";
        console.log(`[STT] Transcription: "${text.slice(0, 80)}"`);
        return text;
    } catch (err) {
        console.error("[STT] Transcription failed:", err);
        return "";
    }
}
