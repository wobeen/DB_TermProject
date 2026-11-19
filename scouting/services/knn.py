"""가중 z-score 거리 기반 k-NN. 거리 계산과 이웃 선정은 SQL 하나(CTE + GROUP BY + ROW_NUMBER)로 한다.

d² = Σ w·(z_c − z_p)² / Σ w  (공유 지표 기준). sqrt는 Python에서 취한다
(SQLite 수학 함수 빌드 옵션에 의존하지 않기 위해. sqrt는 단조라 정렬은 동일).
공유 지표 가중치 합이 후보 전체 가중치 합의 60% 미만이면 비교하지 않는다.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

# 정수 비교로 60% 규칙을 부동소수 오차 없이 판정한다: sw * 10 >= tw * 6
KNN_SQL = """
WITH cand AS (
    {cand_sql}
),
w AS (
    SELECT metric_code, weight FROM metric_weight WHERE pos_group = :pos
),
cv AS (  -- 후보 벡터: 후보의 기준 시즌 z 중 가중치가 정의된 지표
    SELECT c.player_id, c.age, z.metric_code, z.z, w.weight
    FROM cand c
    JOIN player_season_z z
      ON z.snapshot_id = :snap AND z.player_id = c.player_id AND z.season = :L
    JOIN w ON w.metric_code = z.metric_code
),
ctot AS (
    SELECT player_id, SUM(weight) AS tw FROM cv GROUP BY player_id
),
pairs AS (  -- 후보 × 비교 풀(같은 스냅샷·포지션군·나이, season <= pool_max, 본인 제외)
    SELECT cv.player_id AS cand_id, pz.player_id AS nb_id, pz.season AS nb_season,
           SUM(cv.weight * (cv.z - pz.z) * (cv.z - pz.z)) AS wss,
           SUM(cv.weight) AS sw
    FROM cv
    JOIN player_season_z pz
      ON pz.snapshot_id = :snap AND pz.pos_group = :pos
     AND pz.age = cv.age AND pz.metric_code = cv.metric_code
    WHERE pz.season <= :pool_max AND pz.player_id <> cv.player_id
    GROUP BY cv.player_id, pz.player_id, pz.season
),
ranked AS (
    SELECT p.cand_id, p.nb_id, p.nb_season, p.wss / p.sw AS d2,
           ROW_NUMBER() OVER (PARTITION BY p.cand_id
                              ORDER BY p.wss / p.sw, p.nb_id, p.nb_season) AS rn
    FROM pairs p
    JOIN ctot t ON t.player_id = p.cand_id
    WHERE p.sw * 10 >= t.tw * 6
)
SELECT r.cand_id, r.nb_id, r.nb_season, r.d2, r.rn,
       COALESCE(l.is_world_class, 0) AS is_wc
FROM ranked r
LEFT JOIN world_class_label l
  ON l.snapshot_id = :snap AND l.def_id = :def_id AND l.player_id = r.nb_id
WHERE r.rn <= :k
ORDER BY r.cand_id, r.rn
"""


def knn(
    conn: sqlite3.Connection,
    cand_sql: str,
    *,
    snapshot_id: int,
    base_season: int,
    pos_group: str,
    k: int,
    pool_max_season: int,
    def_id: int | None,
    params: dict[str, Any] | None = None,
) -> dict[int, list[dict]]:
    """후보별 이웃 목록 {cand_id: [{player_id, season, distance, is_wc}, ...]} (거리 오름차순).

    cand_sql 은 (player_id, age) 를 돌려주는 SELECT 이며 named 파라미터를 쓸 수 있다.
    def_id 가 None 이면 월클 여부는 전부 0.
    """
    bind = {
        "snap": snapshot_id,
        "L": base_season,
        "pos": pos_group,
        "k": k,
        "pool_max": pool_max_season,
        "def_id": def_id,
        **(params or {}),
    }
    out: dict[int, list[dict]] = {}
    for r in conn.execute(KNN_SQL.format(cand_sql=cand_sql), bind):
        out.setdefault(r["cand_id"], []).append(
            {
                "player_id": r["nb_id"],
                "season": r["nb_season"],
                "distance": math.sqrt(r["d2"]),
                "is_wc": int(r["is_wc"]),
            }
        )
    return out
