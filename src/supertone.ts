/**
 * Supertone REST API helper
 * POST https://supertoneapi.com/v1/text-to-speech/{voiceId}
 * Header: x-sup-api-key
 * Response: binary audio (mp3)
 */
import { SUPERTONE } from "./config";

const API_KEY = process.env.SUPERTONE_API_KEY!;
const VOICE_ID = process.env.SUPERTONE_VOICE_ID!;

/**
 * Convert text to speech via Supertone API.
 * Language, style, and model are read from config.ts (SUPERTONE.*).
 * Returns a Buffer containing MP3 audio data.
 */
export async function supertoneTextToSpeech(text: string): Promise<Buffer> {
    const url = `${SUPERTONE.BASE_URL}/v1/text-to-speech/${VOICE_ID}`;

    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "x-sup-api-key": API_KEY,
        },
        body: JSON.stringify({
            text,
            language: SUPERTONE.LANGUAGE,
            style: SUPERTONE.STYLE,
            model: SUPERTONE.MODEL,
        }),
    });

    if (!response.ok) {
        const errText = await response.text().catch(() => "(no body)");
        throw new Error(
            `[Supertone] TTS request failed: ${response.status} ${response.statusText} — ${errText}`
        );
    }

    const arrayBuffer = await response.arrayBuffer();
    console.log(
        `[Supertone] TTS success — ${text.length} chars → ${arrayBuffer.byteLength} bytes`
    );
    return Buffer.from(arrayBuffer);
}
