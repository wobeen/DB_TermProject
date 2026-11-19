"""다음 월클 추천 (CONTRACT §4). 스냅샷 의존 데이터는 v_*_asof 뷰와 snapshot_id 키 테이블로만 읽는다."""

from __future__ import annotations

import random
import sqlite3

from scouting.db import transaction
from scouting.services.knn import knn

METHODS = ("random", "market_value", "similarity", "hybrid")
POS_GROUPS = ("GK", "DF", "MF", "FW")

# 후보: 기준 시즌 L 의 player_season. 월클 라벨이 없는(=0) 선수만.
CAND_SQL = """
SELECT ps.player_id AS player_id, ps.age AS age
FROM v_player_season_asof ps
JOIN v_player_age_asof a ON a.snapshot_id = ps.snapshot_id AND a.player_id = ps.player_id
LEFT JOIN world_class_label l
  ON l.snapshot_id = ps.snapshot_id AND l.def_id = :def_id AND l.player_id = ps.player_id
WHERE ps.snapshot_id = :snap AND ps.season = :L AND ps.pos_group = :pos
  AND ps.league_minutes >= :min_minutes AND a.age <= :max_age
  AND COALESCE(l.is_world_class, 0) = 0
"""


def base_season(conn: sqlite3.Connection, snapshot_id: int) -> int:
    """기준 시즌 L: 스냅샷에 포함된 최대 시즌."""
    row = conn.execute(
        "SELECT MAX(season) FROM v_player_season_asof WHERE snapshot_id = ?", (snapshot_id,)
    ).fetchone()
    if row[0] is None:
        raise ValueError("이 스냅샷에는 시즌 데이터가 없습니다.")
    return int(row[0])


def _cand_rows(conn, *, snapshot_id, def_id, pos_group, max_age, min_minutes, L) -> list[tuple[int, int]]:
    rows = conn.execute(
        CAND_SQL + " ORDER BY ps.player_id",
        {
            "snap": snapshot_id,
            "def_id": def_id,
            "pos": pos_group,
            "max_age": max_age,
            "min_minutes": min_minutes,
            "L": L,
        },
    )
    return [(r["player_id"], r["age"]) for r in rows]


def candidate_ids(
    conn: sqlite3.Connection, *, snapshot_id: int, def_id: int, pos_group: str, max_age: int, min_minutes: int
) -> list[int]:
    L = base_season(conn, snapshot_id)
    return [
        pid
        for pid, _ in _cand_rows(
            conn,
            snapshot_id=snapshot_id,
            def_id=def_id,
            pos_group=pos_group,
            max_age=max_age,
            min_minutes=min_minutes,
            L=L,
        )
    ]


def _latest_values(conn, snapshot_id: int, ids: list[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        marks = ",".join("?" * len(chunk))  # 자리표시자 개수만 조합, 값은 바인딩
        for r in conn.execute(
            f"SELECT player_id, market_value_eur FROM v_latest_value_asof "
            f"WHERE snapshot_id = ? AND player_id IN ({marks})",
            (snapshot_id, *chunk),
        ):
            out[r["player_id"]] = r["market_value_eur"]
    return out


def _percent_rank(values: dict[int, float]) -> dict[int, float]:
    """SQL PERCENT_RANK 와 동일: (자신보다 작은 값의 수) / (n-1). n=1 이면 0."""
    n = len(values)
    if n <= 1:
        return {k: 0.0 for k in values}
    sorted_vals = sorted(values.values())
    import bisect

    return {k: bisect.bisect_left(sorted_vals, v) / (n - 1) for k, v in values.items()}


def _sim_score(neigh: list[dict]) -> float:
    num = sum(n["is_wc"] / (n["distance"] + 0.1) for n in neigh)
    den = sum(1 / (n["distance"] + 0.1) for n in neigh)
    return num / den


def _save_run(conn, *, user_id, snapshot_id, def_id, method, pos_group, max_age, min_minutes, k,
              pool_lag_seasons, top_n, seed) -> int:
    cur = conn.execute(
        """INSERT INTO recommendation_run
           (user_id, snapshot_id, def_id, method, pos_group, max_age, min_minutes, k,
            pool_lag_seasons, top_n, seed)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, snapshot_id, def_id, method, pos_group, max_age, min_minutes, k,
         pool_lag_seasons, top_n, seed),
    )
    return int(cur.lastrowid)


def _save_items(conn, run_id: int, season: int, ranked: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO recommendation_item (run_id, rank, player_id, season, score, wc_neighbors)
           VALUES (?,?,?,?,?,?)""",
        [(run_id, i, r["player_id"], season, r["score"], r["wc_neighbors"]) for i, r in enumerate(ranked, 1)],
    )


def _save_evidence(conn, run_id: int, ranked: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO recommendation_evidence
           (run_id, player_id, neighbor_player_id, neighbor_season, distance, neighbor_is_wc)
           VALUES (?,?,?,?,?,?)""",
        [
            (run_id, r["player_id"], n["player_id"], n["season"], n["distance"], n["is_wc"])
            for r in ranked
            for n in r["neighbors"]
        ],
    )


def run_recommendation(
    conn: sqlite3.Connection,
    *,
    user_id: int | None,
    snapshot_id: int,
    def_id: int,
    pos_group: str,
    method: str,
    max_age: int = 21,
    min_minutes: int = 900,
    k: int = 25,
    pool_lag_seasons: int = 3,
    top_n: int = 20,
    seed: int = 42,
) -> int:
    if method not in METHODS:
        raise ValueError(f"method 는 {', '.join(METHODS)} 중 하나여야 합니다.")
    if pos_group not in POS_GROUPS:
        raise ValueError("포지션군은 GK/DF/MF/FW 중 하나여야 합니다.")
    if k <= 0 or top_n <= 0 or pool_lag_seasons < 0 or min_minutes < 0:
        raise ValueError("k, top_n 은 양수, pool_lag_seasons, min_minutes 는 0 이상이어야 합니다.")
    if not 15 <= max_age <= 30:
        raise ValueError("max_age 는 15~30 이어야 합니다.")

    L = base_season(conn, snapshot_id)
    cands = _cand_rows(
        conn, snapshot_id=snapshot_id, def_id=def_id, pos_group=pos_group,
        max_age=max_age, min_minutes=min_minutes, L=L,
    )
    ids = [pid for pid, _ in cands]

    neighbors: dict[int, list[dict]] = {}
    sim: dict[int, float] = {}
    if method in ("similarity", "hybrid"):
        neighbors = knn(
            conn, CAND_SQL, snapshot_id=snapshot_id, base_season=L, pos_group=pos_group, k=k,
            pool_max_season=L - pool_lag_seasons, def_id=def_id,
            params={"max_age": max_age, "min_minutes": min_minutes},
        )
        sim = {pid: _sim_score(nb) for pid, nb in neighbors.items()}

    scored: list[dict] = []
    if method == "random":
        order = sorted(ids)
        random.Random(seed).shuffle(order)
        scored = [{"player_id": pid, "score": 0.0} for pid in order]  # 셔플 순서 = 순위
    elif method == "market_value":
        vals = _latest_values(conn, snapshot_id, ids)
        scored = [{"player_id": pid, "score": float(vals.get(pid, 0))} for pid in ids]
    elif method == "similarity":
        scored = [{"player_id": pid, "score": sim[pid]} for pid in ids if pid in sim]
    else:  # hybrid
        vals = _latest_values(conn, snapshot_id, ids)
        pr_sim = _percent_rank(sim)
        pr_val = _percent_rank({pid: float(v) for pid, v in vals.items()})
        scored = [
            {"player_id": pid, "score": 0.5 * pr_sim.get(pid, 0.0) + 0.5 * pr_val.get(pid, 0.0)}
            for pid in ids
        ]
    if method != "random":
        scored.sort(key=lambda r: (-r["score"], r["player_id"]))
    ranked = scored[:top_n]
    for r in ranked:
        nb = neighbors.get(r["player_id"], [])
        r["neighbors"] = nb
        r["wc_neighbors"] = sum(n["is_wc"] for n in nb) if method in ("similarity", "hybrid") else None

    with transaction(conn):
        run_id = _save_run(
            conn, user_id=user_id, snapshot_id=snapshot_id, def_id=def_id, method=method,
            pos_group=pos_group, max_age=max_age, min_minutes=min_minutes, k=k,
            pool_lag_seasons=pool_lag_seasons, top_n=top_n, seed=seed,
        )
        _save_items(conn, run_id, L, ranked)
        if method in ("similarity", "hybrid"):
            _save_evidence(conn, run_id, ranked)
    return run_id


# ---- 기준 돌파 유망주 (R-36: 집합 비교 ALL / SOME) ---------------------------------

# SQLite 는 ALL/SOME/ANY 를 지원하지 않으므로 존재 한정자로 재작성한다.
#   mode="all":  원래 형태  cv.value >  ALL (SELECT s.value FROM s WHERE s.age = cv.age)
#                재작성     NOT EXISTS (SELECT 1 FROM s WHERE s.age = cv.age AND s.value >= cv.value)
#   mode="some": 원래 형태  cv.value >  SOME (SELECT s.value FROM s WHERE s.age = cv.age)
#                재작성     EXISTS     (SELECT 1 FROM s WHERE s.age = cv.age AND s.value <  cv.value)
# 빈 집합에서 > ALL 은 참이지만(공허한 참) 의미가 없으므로 비교 월클이 0명이면 제외한다(EXISTS 조건).
_BREAKOUT_SQL = """
WITH cand AS (
    {cand_sql}
),
cv AS (  -- 후보의 기준 시즌 지표 값
    SELECT c.player_id, c.age, m.value
    FROM cand c
    JOIN player_season_metric m
      ON m.player_id = c.player_id AND m.season = :L AND m.metric_code = :metric
),
s AS (  -- 비교 집합 S: 같은 스냅샷에 포함된 시즌의 같은 포지션군 월클 선수-시즌 (나이별)
    SELECT ps.age AS age, m.value AS value
    FROM v_player_season_asof ps
    JOIN world_class_label l
      ON l.snapshot_id = ps.snapshot_id AND l.def_id = :def_id
     AND l.player_id = ps.player_id AND l.is_world_class = 1
    JOIN player_season_metric m
      ON m.player_id = ps.player_id AND m.season = ps.season AND m.metric_code = :metric
    WHERE ps.snapshot_id = :snap AND ps.pos_group = :pos
)
SELECT cv.player_id, p.name, cv.age, cv.value,
       (SELECT COUNT(*)   FROM s WHERE s.age = cv.age) AS n_wc,
       (SELECT MAX(value) FROM s WHERE s.age = cv.age) AS wc_max,
       (SELECT MIN(value) FROM s WHERE s.age = cv.age) AS wc_min
FROM cv
JOIN player p ON p.player_id = cv.player_id
WHERE EXISTS (SELECT 1 FROM s WHERE s.age = cv.age)
  AND {predicate}
ORDER BY cv.value DESC, cv.player_id
"""
_BREAKOUT_PREDICATES = {
    # x > ALL(S)
    "all": "NOT EXISTS (SELECT 1 FROM s WHERE s.age = cv.age AND s.value >= cv.value)",
    # x > SOME(S)
    "some": "EXISTS (SELECT 1 FROM s WHERE s.age = cv.age AND s.value < cv.value)",
}


def breakout_prospects(
    conn: sqlite3.Connection,
    *,
    snapshot_id: int,
    def_id: int,
    pos_group: str,
    metric_code: str = "minutes_share",
    max_age: int = 21,
    mode: str = "all",
    min_minutes: int = 900,
) -> list[dict]:
    """시즌 L 후보 중 같은 나이 시점 월클의 metric 값보다 높은(all=전원, some=한 명 이상) 선수."""
    if mode not in _BREAKOUT_PREDICATES:
        raise ValueError("mode 는 all 또는 some 이어야 합니다.")
    if pos_group not in POS_GROUPS:
        raise ValueError("포지션군은 GK/DF/MF/FW 중 하나여야 합니다.")
    if conn.execute("SELECT 1 FROM metric WHERE metric_code = ?", (metric_code,)).fetchone() is None:
        raise ValueError("존재하지 않는 지표입니다.")
    L = base_season(conn, snapshot_id)
    sql = _BREAKOUT_SQL.format(cand_sql=CAND_SQL, predicate=_BREAKOUT_PREDICATES[mode])  # 고정 조각만 조합
    rows = conn.execute(
        sql,
        {"snap": snapshot_id, "def_id": def_id, "pos": pos_group, "metric": metric_code, "L": L,
         "max_age": max_age, "min_minutes": min_minutes},
    )
    return [dict(r) for r in rows]


def breakout_wc_count(conn: sqlite3.Connection, *, snapshot_id: int, def_id: int, pos_group: str,
                      metric_code: str) -> int:
    """비교 집합 S 전체 크기(나이 무관). 0 이면 비교 자체가 불가능하다는 안내에 쓴다."""
    return conn.execute(
        """SELECT COUNT(*) FROM v_player_season_asof ps
           JOIN world_class_label l ON l.snapshot_id = ps.snapshot_id AND l.def_id = ?
                AND l.player_id = ps.player_id AND l.is_world_class = 1
           JOIN player_season_metric m ON m.player_id = ps.player_id AND m.season = ps.season
                AND m.metric_code = ?
           WHERE ps.snapshot_id = ? AND ps.pos_group = ?""",
        (def_id, metric_code, snapshot_id, pos_group),
    ).fetchone()[0]


def list_metrics(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT metric_code, name_ko FROM metric ORDER BY metric_code")]


# ---- 조회 (CLI용) ---------------------------------------------------------

def list_snapshots(conn: sqlite3.Connection, *, built_only: bool = False) -> list[dict]:
    sql = "SELECT snapshot_id, name, as_of_date, built_at FROM snapshot"
    if built_only:
        sql += " WHERE built_at IS NOT NULL"
    return [dict(r) for r in conn.execute(sql + " ORDER BY snapshot_id")]


def list_definitions(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM world_class_definition ORDER BY def_id")]


def list_runs(conn: sqlite3.Connection, user_id: int | None = None) -> list[dict]:
    """user_id 가 None 이면 전체(관리자 백테스트 선택용)."""
    sql = """SELECT r.run_id, r.created_at, s.name AS snapshot, d.code AS def_code, r.method,
                    r.pos_group, r.top_n, r.user_id, r.snapshot_id, r.def_id
             FROM recommendation_run r
             JOIN snapshot s ON s.snapshot_id = r.snapshot_id
             JOIN world_class_definition d ON d.def_id = r.def_id"""
    if user_id is None:
        rows = conn.execute(sql + " ORDER BY r.run_id DESC")
    else:
        rows = conn.execute(sql + " WHERE r.user_id = ? ORDER BY r.run_id DESC", (user_id,))
    return [dict(r) for r in rows]


def get_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM recommendation_run WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def run_items(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT i.rank, i.player_id, p.name, i.season, i.score, i.wc_neighbors, c.name AS club_name,
                  (SELECT v.market_value_eur FROM v_latest_value_asof v
                    WHERE v.snapshot_id = r.snapshot_id AND v.player_id = i.player_id) AS value_eur
           FROM recommendation_item i
           JOIN recommendation_run r ON r.run_id = i.run_id
           JOIN player p ON p.player_id = i.player_id
           LEFT JOIN player_season ps ON ps.player_id = i.player_id AND ps.season = i.season
           LEFT JOIN club c ON c.club_id = ps.main_club_id
           WHERE i.run_id = ? ORDER BY i.rank""",
        (run_id,),
    )
    return [dict(r) for r in rows]


def run_evidence(conn: sqlite3.Connection, run_id: int, player_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT e.neighbor_player_id, p.name, e.neighbor_season, e.distance, e.neighbor_is_wc
           FROM recommendation_evidence e JOIN player p ON p.player_id = e.neighbor_player_id
           WHERE e.run_id = ? AND e.player_id = ?
           ORDER BY e.distance, e.neighbor_player_id, e.neighbor_season""",
        (run_id, player_id),
    )
    return [dict(r) for r in rows]
