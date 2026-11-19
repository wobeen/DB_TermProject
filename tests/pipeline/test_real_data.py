"""실데이터 검증 (data/scouting.sqlite 가 없으면 skip). CONTRACT §1, §10."""

from __future__ import annotations

import functools
import sqlite3
from pathlib import Path

import pytest

REAL_DB = Path(__file__).resolve().parents[2] / "data" / "scouting.sqlite"
pytestmark = pytest.mark.skipif(not REAL_DB.exists(), reason="data/scouting.sqlite 없음")

# 계약과 무관한 독립 검증: 원천 테이블만으로 출전 구간 (in, out] 길이를 다시 계산해 minutes_played 와 비교한다.
MATCH_SQL = """
WITH apps AS (
    SELECT a.game_id, a.player_id, a.minutes_played AS mp
    FROM appearance a
    JOIN game g ON g.game_id = a.game_id
    JOIN competition c ON c.competition_id = g.competition_id AND c.is_covered = 1
    WHERE g.season = :season AND a.minutes_played >= 1
), ein AS (
    SELECT game_id, player_in_id AS player_id, MIN(CASE WHEN minute >= 0 THEN minute END) AS in_min
    FROM game_event WHERE type = 'Substitutions' AND player_in_id IS NOT NULL
      AND game_id IN (SELECT game_id FROM game WHERE season = :season)
    GROUP BY game_id, player_in_id
), eout AS (
    SELECT game_id, player_id, MIN(minute) AS out_min FROM (
        SELECT game_id, player_id, minute FROM game_event
         WHERE type = 'Substitutions' AND player_id IS NOT NULL AND minute >= 0
        UNION ALL
        SELECT game_id, player_id, minute FROM game_event
         WHERE is_sending_off = 1 AND player_id IS NOT NULL AND minute >= 0)
    WHERE game_id IN (SELECT game_id FROM game WHERE season = :season)
    GROUP BY game_id, player_id
), calc AS (
    SELECT x.mp,
           CASE WHEN COALESCE(l.is_starter, CASE WHEN ein.player_id IS NULL THEN 1 ELSE 0 END) = 1 THEN 0
                ELSE ein.in_min END AS inn,
           eout.out_min AS out_min
    FROM apps x
    LEFT JOIN game_lineup l ON l.game_id = x.game_id AND l.player_id = x.player_id
    LEFT JOIN ein ON ein.game_id = x.game_id AND ein.player_id = x.player_id
    LEFT JOIN eout ON eout.game_id = x.game_id AND eout.player_id = x.player_id
)
SELECT COUNT(*) AS n,
       SUM(CASE WHEN inn IS NOT NULL AND ABS((COALESCE(out_min, 90) - inn) - mp) <= 5 THEN 1 ELSE 0 END) AS ok
FROM calc
"""


def _locked(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


@pytest.fixture(scope="module")
def real():
    """읽기 전용 URI로 연다. 다른 프로세스가 쓰는 중이라 잠겨 있으면 실패 대신 skip."""
    uri = f"file:{REAL_DB.as_posix()}?mode=ro"
    try:
        c = sqlite3.connect(uri, uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute("SELECT 1 FROM snapshot LIMIT 1").fetchone()
    except sqlite3.OperationalError as e:
        pytest.skip(f"실DB를 읽을 수 없음(잠금/사용 중): {e}")
    yield c
    c.close()


def skip_if_locked(fn):
    """테스트 도중 잠금 오류(OperationalError locked/busy)가 나도 실패가 아니라 skip."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if _locked(e):
                pytest.skip(f"실DB 잠김: {e}")
            raise

    return wrapper


def match_rate(conn: sqlite3.Connection, season: int = 2018) -> tuple[int, int, float]:
    row = conn.execute(MATCH_SQL, {"season": season}).fetchone()
    return row["n"], row["ok"], row["ok"] / row["n"]


@skip_if_locked
def test_2018_playing_time_model_matches_minutes_played(real):
    n, ok, rate = match_rate(real, 2018)
    print(f"\n2018 시즌 covered 리그 출전 {n:,}건 중 ±5분 일치 {ok:,}건 = {rate:.6f}")
    assert n > 50_000
    assert rate >= 0.999


@skip_if_locked
def test_foreign_key_check_is_empty(real):
    assert real.execute("PRAGMA foreign_key_check").fetchall() == []


@skip_if_locked
def test_snapshots_built(real):
    rows = {r["name"]: r["built_at"] for r in real.execute("SELECT name, built_at FROM snapshot")}
    assert {"current", "bt2018"} <= rows.keys()
    assert all(v is not None for v in rows.values())
