"""스카우팅 노트. 노트는 작성자 본인만 조회·수정·삭제한다."""

from __future__ import annotations

import sqlite3

from scouting.db import transaction


def create_note(conn: sqlite3.Connection, user_id: int, player_id: int, rating: int, body: str) -> int:
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO scouting_note (user_id, player_id, rating, body) VALUES (?, ?, ?, ?)",
            (user_id, player_id, rating, body),
        )
        return int(cur.lastrowid)


def list_notes_for_player(conn: sqlite3.Connection, user_id: int, player_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT note_id, player_id, rating, body, created_at, updated_at
           FROM scouting_note WHERE user_id = ? AND player_id = ?
           ORDER BY updated_at DESC, note_id DESC""",
        (user_id, player_id),
    )
    return [dict(r) for r in rows]


def list_my_notes(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT n.note_id, n.player_id, p.name AS player_name, n.rating, n.body,
                  n.created_at, n.updated_at
           FROM scouting_note n JOIN player p ON p.player_id = n.player_id
           WHERE n.user_id = ?
           ORDER BY n.updated_at DESC, n.note_id DESC""",
        (user_id,),
    )
    return [dict(r) for r in rows]


def note_owned(conn: sqlite3.Connection, user_id: int, note_id: int) -> bool:
    """CLI 사전 확인용. 최종 UPDATE/DELETE 의 user_id 조건과는 별개로 유지된다."""
    return conn.execute(
        "SELECT 1 FROM scouting_note WHERE note_id = ? AND user_id = ?", (note_id, user_id)
    ).fetchone() is not None


def update_note(
    conn: sqlite3.Connection,
    user_id: int,
    note_id: int,
    *,
    rating: int | None = None,
    body: str | None = None,
) -> bool:
    """rating/body 중 None이 아닌 것만 수정. 본인 노트가 아니면(또는 없으면) False."""
    with transaction(conn):
        cur = conn.execute(
            """UPDATE scouting_note
               SET rating = COALESCE(?, rating), body = COALESCE(?, body)
               WHERE note_id = ? AND user_id = ?""",
            (rating, body, note_id, user_id),
        )
        return cur.rowcount > 0


def delete_note(conn: sqlite3.Connection, user_id: int, note_id: int) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "DELETE FROM scouting_note WHERE note_id = ? AND user_id = ?", (note_id, user_id)
        )
        return cur.rowcount > 0
