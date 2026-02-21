import Database from "better-sqlite3";
import path from "path";
import type { Message, QuizQuestion } from "./types";

const DB_PATH = path.resolve(process.cwd(), "aimc.db");
let db: Database.Database;

export function initDB(): void {
  db = new Database(DB_PATH);
  db.pragma("journal_mode = WAL");
  db.exec(`
    CREATE TABLE IF NOT EXISTS sessions (
      id         TEXT    PRIMARY KEY,
      persona_id TEXT    NOT NULL,
      created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS messages (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT    NOT NULL,
      role       TEXT    NOT NULL CHECK(role IN ('user','assistant')),
      content    TEXT    NOT NULL,
      timestamp  INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES sessions(id)
    );

    CREATE TABLE IF NOT EXISTS quizzes (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id   TEXT    NOT NULL,
      questions    TEXT    NOT NULL,
      triggered_at INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
  `);
  console.log(`[DB] Ready at ${DB_PATH}`);
}

export function createSession(id: string, personaId: string): void {
  db.prepare(
    "INSERT INTO sessions (id, persona_id, created_at) VALUES (?, ?, ?)"
  ).run(id, personaId, Date.now());
}

export function addMessage(
  sessionId: string,
  role: "user" | "assistant",
  content: string
): void {
  db.prepare(
    "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)"
  ).run(sessionId, role, content, Date.now());
}

/** Returns messages newest-first, up to `limit`. Caller reverses if needed. */
export function getMessages(sessionId: string, limit = 10): Message[] {
  return db
    .prepare(
      `SELECT role, content, timestamp
       FROM messages
       WHERE session_id = ?
       ORDER BY timestamp DESC
       LIMIT ?`
    )
    .all(sessionId, limit) as Message[];
}

export function getUserMessageCount(sessionId: string): number {
  const row = db
    .prepare(
      "SELECT COUNT(*) as count FROM messages WHERE session_id = ? AND role = 'user'"
    )
    .get(sessionId) as { count: number };
  return row.count;
}

export function saveQuiz(sessionId: string, questions: QuizQuestion[]): void {
  db.prepare(
    "INSERT INTO quizzes (session_id, questions, triggered_at) VALUES (?, ?, ?)"
  ).run(sessionId, JSON.stringify(questions), Date.now());
}
