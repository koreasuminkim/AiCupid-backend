/**
 * ─────────────────────────────────────────────────────────────────
 *  QuizRuleTrigger — 룰 베이스 퀴즈 트리거
 * ─────────────────────────────────────────────────────────────────
 *
 *  동작: 세션 내 사용자 메시지 수가 N의 배수가 될 때마다 퀴즈 생성.
 *  설정: config.ts의 QUIZ.TRIGGER_EVERY_N_MESSAGES / HISTORY_WINDOW
 * ─────────────────────────────────────────────────────────────────
 */

import type { EventTrigger, MCEvent, TurnContext } from "./types";
import { generateQuiz } from "../gemini";
import { QUIZ } from "../config";

export class QuizRuleTrigger implements EventTrigger {
    readonly name = "quiz-rule";

    async onTurn(ctx: TurnContext): Promise<MCEvent | null> {
        const { messageCount, history } = ctx;

        // N의 배수 턴에만 발동
        if (messageCount <= 0 || messageCount % QUIZ.TRIGGER_EVERY_N_MESSAGES !== 0) {
            return null;
        }

        console.log(
            `[QuizRuleTrigger] Triggered at message #${messageCount} — generating quiz`
        );

        const questions = await generateQuiz(history);
        if (questions.length === 0) return null;

        return { type: "quiz", payload: questions };
    }
}
