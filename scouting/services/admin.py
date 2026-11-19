"""관리자 기능: 데이터 현황, 월클 정의 관리, 스냅샷 재계산 (pipeline.derive 위임)."""

from __future__ import annotations

import sqlite3
import sys

from scouting.db import ROOT, transaction
from scouting.services.users import User, require_admin

# 테이블 이름은 고정 화이트리스트 (식별자는 바인딩 불가)
STATUS_TABLES = (
    "competition", "club", "player", "game", "appearance", "game_lineup", "game_event",
    "player_valuation", "transfer", "player_season", "player_season_metric", "snapshot",
    "cohort_baseline", "player_season_z", "world_class_definition", "world_class_label",
    "app_user", "watchlist", "scouting_note", "recommendation_run", "recommendation_item",
    "recommendation_evidence", "backtest_result",
)

_DEF_FIELDS = (
    "code", "name_ko", "rule_type", "value_threshold_eur", "gk_value_threshold_eur",
    "min_seasons", "min_league_minutes", "min_cl_minutes",
)


def _derive():
    """pipeline.derive 를 지연 import (PipelineAgent 소유). 테스트에서 monkeypatch 한다."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from pipeline import derive
    except ImportError as e:
        raise RuntimeError("pipeline.derive 를 불러올 수 없습니다 (파이프라인 미설치).") from e
    return derive


def data_status(conn: sqlite3.Connection) -> dict:
    tables = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in STATUS_TABLES}
    snapshots = [
        dict(r)
        for r in conn.execute("SELECT snapshot_id, name, as_of_date, built_at FROM snapshot ORDER BY snapshot_id")
    ]
    return {"tables": tables, "snapshots": snapshots}


def _built_snapshot_ids(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT snapshot_id FROM snapshot WHERE built_at IS NOT NULL ORDER BY 1")]


def _relabel(conn: sqlite3.Connection, def_id: int) -> None:
    ids = _built_snapshot_ids(conn)
    if not ids:
        return
    derive = _derive()
    for sid in ids:
        derive.build_labels(conn, sid, def_id)


def create_definition(conn: sqlite3.Connection, actor: User, **fields) -> int:
    require_admin(conn, actor)
    unknown = set(fields) - set(_DEF_FIELDS)
    if unknown:
        raise ValueError(f"알 수 없는 필드: {', '.join(sorted(unknown))}")
    cols = [c for c in _DEF_FIELDS if c in fields]
    with transaction(conn):
        cur = conn.execute(
            f"INSERT INTO world_class_definition ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [fields[c] for c in cols],
        )
        def_id = int(cur.lastrowid)
        _relabel(conn, def_id)
    return def_id


def update_definition(conn: sqlite3.Connection, actor: User, def_id: int, **fields) -> bool:
    require_admin(conn, actor)
    unknown = set(fields) - set(_DEF_FIELDS)
    if unknown:
        raise ValueError(f"알 수 없는 필드: {', '.join(sorted(unknown))}")
    if not fields:
        raise ValueError("수정할 값이 없습니다.")
    cols = [c for c in _DEF_FIELDS if c in fields]
    with transaction(conn):
        cur = conn.execute(
            f"UPDATE world_class_definition SET {', '.join(c + ' = ?' for c in cols)} WHERE def_id = ?",
            [*(fields[c] for c in cols), def_id],
        )
        if cur.rowcount == 0:
            return False
        _relabel(conn, def_id)  # 실패하면 정의 수정도 함께 롤백
    return True


def delete_definition(conn: sqlite3.Connection, actor: User, def_id: int) -> bool:
    """추천 run 이 참조 중이면 FK 때문에 IntegrityError."""
    require_admin(conn, actor)
    with transaction(conn):
        cur = conn.execute("DELETE FROM world_class_definition WHERE def_id = ?", (def_id,))
        return cur.rowcount > 0


def rebuild_snapshot(conn: sqlite3.Connection, snapshot_id: int, *, actor: User) -> dict:
    """pipeline.derive.build_snapshot 위임. actor 는 필수이며 항상 관리자 여부를 검사한다."""
    require_admin(conn, actor)
    if conn.execute("SELECT 1 FROM snapshot WHERE snapshot_id = ?", (snapshot_id,)).fetchone() is None:
        raise ValueError("존재하지 않는 스냅샷입니다.")
    return _derive().build_snapshot(conn, snapshot_id)
