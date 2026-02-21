/**
 * ─────────────────────────────────────────────────────────────────
 *  AIMC Event System — Core Types
 * ─────────────────────────────────────────────────────────────────
 *
 * 이벤트 종류를 추가하려면:
 *   1. MCEvent 유니온에 새 타입을 추가
 *   2. events/ 폴더에 새 트리거 파일 생성
 *   3. engine.ts에 등록
 * ─────────────────────────────────────────────────────────────────
 */

import type { Message, QuizQuestion } from "../types";

// ── 매 대화 턴에서 트리거에 전달되는 컨텍스트 ─────────────────────
export interface TurnContext {
    sessionId: string;
    /** 해당 턴의 사용자 발화 텍스트 */
    userMessage: string;
    /** 해당 턴의 AI 텍스트 응답 (Gemini / Supertone 모드 공통) */
    aiMessage: string;
    /** 세션 내 누적 사용자 메시지 수 (이번 턴 포함) */
    messageCount: number;
    /** 최근 대화 히스토리 (DB에서 조회된 순서) */
    history: Message[];
}

// ── 이벤트 유니온 ─────────────────────────────────────────────────
// 새 이벤트를 추가할 때 여기에 타입을 추가하세요.
export type MCEvent =
    | { type: "quiz"; payload: QuizQuestion[] }
    // 예시: 앞으로 추가할 이벤트들
    // | { type: "crowd_cheer"; payload: { intensity: number } }
    // | { type: "highlight_reel"; payload: { summary: string } }
    // | { type: "vote"; payload: { question: string; options: string[] } }
    ;

// ── EventTrigger 인터페이스 ───────────────────────────────────────
/**
 * 이벤트 트리거 플러그인의 기본 계약(contract).
 *
 * 구현체는 매 턴 완료 후 onTurn()을 호출받고:
 *   - 이벤트를 발화해야 한다면 MCEvent를 반환
 *   - 아직 아니라면 null을 반환
 *
 * 여러 이벤트를 한 턴에 반환해야 한다면 MCEvent[]로 변경 가능.
 */
export interface EventTrigger {
    /** 트리거 식별 이름 (로그·디버깅용) */
    readonly name: string;

    /**
     * 매 대화 턴 완료 후 호출됩니다.
     * @returns 발화할 이벤트, 혹은 이번 턴은 패스할 경우 null
     */
    onTurn(ctx: TurnContext): Promise<MCEvent | null>;
}
