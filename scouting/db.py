"""DB 연결 계약 (docs/CONTRACT.md §6.1). 모든 모듈은 이 함수로만 연결한다."""

from __future__ import annotations

import itertools
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "scouting.sqlite"
SQL_DIR = ROOT / "db"
SQL_FILES: tuple[str, ...] = ("schema.sql", "views.sql", "indexes.sql", "reference_data.sql")
MIN_SQLITE = (3, 37, 0)  # STRICT 테이블

_savepoint_ids = itertools.count()


def db_path(path: str | os.PathLike[str] | None = None) -> Path:
    """명시 경로 > 환경변수 SCOUTING_DB > data/scouting.sqlite."""
    return Path(path or os.environ.get("SCOUTING_DB") or DEFAULT_DB_PATH)


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """autocommit 모드 연결. 쓰기는 반드시 transaction()으로 감싼다."""
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise RuntimeError(
            f"SQLite {'.'.join(map(str, MIN_SQLITE))}+ 필요 (현재 {sqlite3.sqlite_version})"
        )
    conn = sqlite3.connect(db_path(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ~ COMMIT, 예외 시 ROLLBACK.

    이미 트랜잭션 안이면 SAVEPOINT로 중첩한다: 안쪽 실패는 안쪽 변경만 되돌리고 예외를 다시 던진다.
    """
    if conn.in_transaction:
        name = f"sp_{next(_savepoint_ids)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def apply_sql(conn: sqlite3.Connection, files: Sequence[str] = SQL_FILES) -> None:
    """db/ 의 SQL 파일을 순서대로 실행한다 (빈 DB 초기화용)."""
    for name in files:
        conn.executescript((SQL_DIR / name).read_text(encoding="utf-8"))
