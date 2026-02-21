/**
 * ─────────────────────────────────────────────────────────────────
 *  QuizAgentTrigger — LLM 에이전트 기반 퀴즈 트리거
 * ─────────────────────────────────────────────────────────────────
 *
 *  동작: 매 턴마다 Gemini에게 "지금 퀴즈를 내기 좋은 타이밍인가?"를 묻고,
 *        LLM이 YES라고 판단하면 퀴즈를 생성합니다.
 *
 *  판단 기준 예시 (프롬프트에서 정의):
 *    - 흥미로운 주제(역사·과학·스포츠 등)가 충분히 언급됐을 때
 *    - 사용자가 5회 이상 발화했을 때
 *    - 직전 퀴즈로부터 최소 3턴이 지났을 때
 * ─────────────────────────────────────────────────────────────────
 */

import { GoogleGenAI } from "@google/genai";
import type { EventTrigger, MCEvent, TurnContext } from "./types";
import { generateQuiz } from "../gemini";
import { MODELS } from "../config";

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });

/** 에이전트 판단 프롬프트 */
function buildDecisionPrompt(ctx: TurnContext): string {
    const recent = ctx.history
        .slice(-6) // 최근 6개 메시지만
        .map((m) => `${m.role === "user" ? "Guest" : "MC"}: ${m.content}`)
        .join("\n");

    return `You are an event coordinator for a live AI MC show.
Decide whether NOW is a good time to run a trivia quiz for the audience.

Rules:
- At least 4 user messages must have occurred (current count: ${ctx.messageCount})
- The conversation must contain interesting facts or topics worth quizzing on
- Don't trigger if the conversation is purely casual/emotional with no learnable content
- Maintain at least 3 turns between quizzes

Recent conversation:
${recent}

Respond with ONLY "YES" or "NO".`;
}

export class QuizAgentTrigger implements EventTrigger {
    readonly name = "quiz-agent";

    private lastTriggeredAt = -Infinity; // 마지막 퀴즈가 발생한 messageCount
    private readonly minGap: number;

    constructor({ minGap = 3 }: { minGap?: number } = {}) {
        this.minGap = minGap;
    }

    async onTurn(ctx: TurnContext): Promise<MCEvent | null> {
        // 최소 4회 발화 & 이전 퀴즈로부터 충분한 간격
        if (
            ctx.messageCount < 4 ||
            ctx.messageCount - this.lastTriggeredAt < this.minGap
        ) {
            return null;
        }

        // ── LLM에게 판단 요청 ──────────────────────────────────
        const response = await ai.models.generateContent({
            model: MODELS.TEXT,
            contents: [
                { role: "user", parts: [{ text: buildDecisionPrompt(ctx) }] },
            ],
        });

        const decision = response.text?.trim().toUpperCase();
        console.log(
            `[QuizAgentTrigger] Decision at message #${ctx.messageCount}: ${decision}`
        );

        if (decision !== "YES") return null;

        // ── 퀴즈 생성 ─────────────────────────────────────────
        const questions = await generateQuiz(ctx.history);
        if (questions.length === 0) return null;

        this.lastTriggeredAt = ctx.messageCount;
        return { type: "quiz", payload: questions };
    }
}
