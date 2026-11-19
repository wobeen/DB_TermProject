"""백테스트: 추천 run 의 상위 k 가 outcome 스냅샷에서 실제 월클이 됐는지 평가 (CONTRACT §4)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from scouting.db import transaction
from scouting.services.recommend import CAND_SQL, base_season


def evaluate_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    outcome_snapshot_id: int,
    k_values: Sequence[int] = (20, 50),
) -> list[dict]:
    """k 마다 hits/precision/recall 을 계산해 backtest_result 에 저장(같은 키면 덮어씀)하고 돌려준다.

    정답 = outcome 스냅샷에서 같은 정의의 is_world_class = 1.
    recall = hits / (후보 중 정답 수), 정답 수가 0이면 NULL(None).
    """
    run = conn.execute("SELECT * FROM recommendation_run WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("존재하지 않는 run 입니다.")
    out = conn.execute(
        "SELECT as_of_date FROM snapshot WHERE snapshot_id = ?", (outcome_snapshot_id,)
    ).fetchone()
    if out is None:
        raise ValueError("존재하지 않는 outcome 스냅샷입니다.")
    run_asof = conn.execute(
        "SELECT as_of_date FROM snapshot WHERE snapshot_id = ?", (run["snapshot_id"],)
    ).fetchone()[0]
    if out["as_of_date"] <= run_asof:  # 같은 시점이면 정답에 미래 정보가 없어 평가가 무의미하다
        raise ValueError(
            f"outcome 스냅샷의 기준일({out['as_of_date']})은 run 스냅샷의 기준일({run_asof})보다 "
            "나중이어야 합니다. 더 최신 스냅샷을 선택하세요."
        )
    ks = sorted({int(k) for k in k_values})
    if not ks or ks[0] <= 0:
        raise ValueError("k 는 양수여야 합니다.")
    if ks[-1] > run["top_n"]:
        raise ValueError(f"k 는 run 의 top_n({run['top_n']}) 이하여야 합니다.")

    L = base_season(conn, run["snapshot_id"])
    cands = [
        r["player_id"]
        for r in conn.execute(
            CAND_SQL,
            {
                "snap": run["snapshot_id"],
                "def_id": run["def_id"],
                "pos": run["pos_group"],
                "max_age": run["max_age"],
                "min_minutes": run["min_minutes"],
                "L": L,
            },
        )
    ]
    positives = {
        r["player_id"]
        for r in conn.execute(
            "SELECT player_id FROM world_class_label "
            "WHERE snapshot_id = ? AND def_id = ? AND is_world_class = 1",
            (outcome_snapshot_id, run["def_id"]),
        )
    }
    n_candidates = len(cands)
    n_positive = sum(1 for p in cands if p in positives)
    ranked = [
        r["player_id"]
        for r in conn.execute(
            "SELECT player_id FROM recommendation_item WHERE run_id = ? ORDER BY rank", (run_id,)
        )
    ]

    results = []
    with transaction(conn):
        for k in ks:
            hits = sum(1 for p in ranked[:k] if p in positives)
            precision = hits / k
            recall = hits / n_positive if n_positive else None
            conn.execute(
                """INSERT OR REPLACE INTO backtest_result
                   (run_id, outcome_snapshot_id, k_eval, n_candidates, n_positive, hits,
                    precision_at_k, recall_at_k)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, outcome_snapshot_id, k, n_candidates, n_positive, hits, precision, recall),
            )
            results.append(
                {
                    "run_id": run_id,
                    "k": k,
                    "n_candidates": n_candidates,
                    "n_positive": n_positive,
                    "hits": hits,
                    "precision": precision,
                    "recall": recall,
                }
            )
    return results
