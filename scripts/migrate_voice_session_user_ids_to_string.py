"""
voice_sessions 테이블의 user_id_1, user_id_2를 Integer → String으로 변경하는 마이그레이션.
SQLite는 컬럼 타입 변경을 지원하지 않으므로 테이블을 새로 만들고 데이터를 옮깁니다.

사용법 (프로젝트 루트에서):
  python scripts/migrate_voice_session_user_ids_to_string.py
"""
import sqlite3
import sys
from pathlib import Path

# 프로젝트 루트 기준 DB 경로 (database.py와 동일)
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "cupid_main.py.db"


def main():
    if not DB_PATH.exists():
        print(f"DB 파일이 없습니다: {DB_PATH}")
        print("마이그레이션 불필요. 서버 실행 시 새 스키마로 테이블이 생성됩니다.")
        return 0

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA table_info(voice_sessions)")
        row = conn.execute("PRAGMA table_info(voice_sessions)").fetchone()
        if not row:
            print("voice_sessions 테이블이 없습니다. 마이그레이션 불필요.")
            return 0

        # user_id_1 컬럼 타입 확인 (2=INTEGER, 3=TEXT 등)
        for r in conn.execute("PRAGMA table_info(voice_sessions)").fetchall():
            if r[1] == "user_id_1" and "TEXT" in (r[2] or "").upper():
                print("user_id_1, user_id_2가 이미 String입니다. 마이그레이션 불필요.")
                return 0

        print("voice_sessions 테이블 재생성 (user_id_1, user_id_2 → String)...")
        conn.executescript("""
            CREATE TABLE voice_sessions_new (
                id INTEGER NOT NULL PRIMARY KEY,
                session_id VARCHAR NOT NULL,
                user_id_1 VARCHAR NOT NULL,
                user_id_2 VARCHAR NOT NULL,
                created_at DATETIME
            );
            INSERT INTO voice_sessions_new (id, session_id, user_id_1, user_id_2, created_at)
            SELECT id, session_id, CAST(user_id_1 AS TEXT), CAST(user_id_2 AS TEXT), created_at
            FROM voice_sessions;
            DROP TABLE voice_sessions;
            ALTER TABLE voice_sessions_new RENAME TO voice_sessions;
            CREATE INDEX IF NOT EXISTS ix_voice_sessions_session_id ON voice_sessions (session_id);
        """)
        conn.commit()
        print("마이그레이션 완료.")
        return 0
    except sqlite3.Error as e:
        print(f"오류: {e}", file=sys.stderr)
        conn.rollback()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
