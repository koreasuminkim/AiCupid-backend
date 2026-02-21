/**
 * ─────────────────────────────────────────────────────────────────
 *  EventEngine — 트리거 플러그인 레지스트리 & 코디네이터
 * ─────────────────────────────────────────────────────────────────
 *
 *  사용법:
 *    const engine = new EventEngine();
 *    engine.register(new QuizRuleTrigger());
 *    engine.register(new MyCustomTrigger());
 *
 *    // 매 턴 완료 후:
 *    const events = await engine.processTurn(ctx);
 *    for (const event of events) { ... }
 * ─────────────────────────────────────────────────────────────────
 */

import type { EventTrigger, MCEvent, TurnContext } from "./types";

export class EventEngine {
    private triggers: EventTrigger[] = [];

    /** 트리거 플러그인 등록 */
    register(trigger: EventTrigger): this {
        this.triggers.push(trigger);
        console.log(`[EventEngine] Registered trigger: "${trigger.name}"`);
        return this; // 체이닝 가능: engine.register(a).register(b)
    }

    /** 등록된 모든 트리거를 병렬 실행하고, null이 아닌 이벤트만 반환 */
    async processTurn(ctx: TurnContext): Promise<MCEvent[]> {
        const results = await Promise.allSettled(
            this.triggers.map((t) => t.onTurn(ctx))
        );

        const events: MCEvent[] = [];
        for (let i = 0; i < results.length; i++) {
            const result = results[i];
            if (result.status === "fulfilled") {
                if (result.value !== null) events.push(result.value);
            } else {
                console.error(
                    `[EventEngine] Trigger "${this.triggers[i].name}" threw:`,
                    result.reason
                );
            }
        }
        return events;
    }
}
