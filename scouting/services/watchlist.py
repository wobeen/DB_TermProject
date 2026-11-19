"""워치리스트. 수정·삭제는 WHERE ... AND user_id = ? 로 소유권을 강제하고 영향 행 여부(bool)를 돌려준다."""

from __future__ import annotations

import sqlite3

from scouting.db import transaction


def add_to_watchlist(conn: sqlite3.Connection, user_id: int, player_id: int, memo: str | None = None) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO watchlist (user_id, player_id, memo) VALUES (?, ?, ?)",
            (user_id, player_id, memo),
        )


def list_watchlist(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT w.player_id, c.name, c.pos_group, c.current_club_name, c.latest_value_eur,
               w.memo, w.added_at
        FROM watchlist w
        JOIN v_player_card c ON c.player_id = w.player_id
        WHERE w.user_id = ?
        ORDER BY w.added_at DESC, w.player_id
        """,
        (user_id,),
    )
    return [dict(r) for r in rows]


def is_watched(conn: sqlite3.Connection, user_id: int, player_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM watchlist WHERE player_id = ? AND user_id = ?", (player_id, user_id)
    ).fetchone() is not None


def update_watch_memo(conn: sqlite3.Connection, user_id: int, player_id: int, memo: str | None) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE watchlist SET memo = ? WHERE player_id = ? AND user_id = ?",
            (memo, player_id, user_id),
        )
        return cur.rowcount > 0


def remove_from_watchlist(conn: sqlite3.Connection, user_id: int, player_id: int) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "DELETE FROM watchlist WHERE player_id = ? AND user_id = ?", (player_id, user_id)
        )
        return cur.rowcount > 0
