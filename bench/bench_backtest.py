"""백테스트 실험: 스냅샷 × 포지션군 4 × 정의 2 × method 4, top_n=50, outcome=current, k=20/50.
random 은 seed 10개 평균. 추천 기록은 복사본(data/bench_work.sqlite)에 쓴다."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_queries as B  # noqa: E402
from make_variants import WORK_PATH, make_work  # noqa: E402
from pipeline import derive  # noqa: E402
from scouting.db import connect  # noqa: E402
from scouting.services.backtest import evaluate_run  # noqa: E402
from scouting.services.recommend import run_recommendation  # noqa: E402

POS = ("GK", "DF", "MF", "FW")
METHODS = ("random", "market_value", "similarity", "hybrid")
EXTRA_SNAPSHOTS = {"bt2019": "2019-07-01", "bt2020": "2020-07-01"}
RANDOM_SEEDS = range(10)
TOP_N, KS = 50, (20, 50)


def ensure_snapshots(main_conn, log) -> None:
    """bt2019, bt2020 을 메인 DB에 pipeline.derive API 로 추가(이미 built 면 건너뜀)."""
    for name, as_of in EXTRA_SNAPSHOTS.items():
        sid = derive.create_snapshot(main_conn, name, as_of)
        built = main_conn.execute("SELECT built_at FROM snapshot WHERE snapshot_id=?", (sid,)).fetchone()[0]
        if built is None:
            t = time.perf_counter()
            derive.build_snapshot(main_conn, sid)
            log(f"[BACKTEST] 스냅샷 {name} 빌드 {time.perf_counter() - t:.1f}s")


def run(quick: bool, log) -> list[dict]:
    make_work()
    conn = connect(WORK_PATH)
    snaps = ["bt2018"] if quick else ["bt2018", "bt2019", "bt2020"]
    out_id = conn.execute("SELECT snapshot_id FROM snapshot WHERE name='current'").fetchone()[0]
    defs = {r["def_id"]: r["code"] for r in conn.execute("SELECT def_id, code FROM world_class_definition ORDER BY def_id")}
    rows: list[dict] = []
    for sn in snaps:
        sid = conn.execute("SELECT snapshot_id FROM snapshot WHERE name=?", (sn,)).fetchone()[0]
        for pos in POS:
            for def_id, code in defs.items():
                for method in METHODS:
                    t0 = time.perf_counter()
                    seeds = RANDOM_SEEDS if method == "random" else [42]
                    acc: dict[int, list[dict]] = {k: [] for k in KS}
                    for seed in seeds:
                        run_id = run_recommendation(conn, user_id=None, snapshot_id=sid, def_id=def_id, pos_group=pos,
                                                    method=method, top_n=TOP_N, seed=seed)
                        for r in evaluate_run(conn, run_id, outcome_snapshot_id=out_id, k_values=KS):
                            acc[r["k"]].append(r)
                    for k in KS:
                        rs = acc[k]
                        n = len(rs)
                        rec = [r["recall"] for r in rs if r["recall"] is not None]
                        rows.append({
                            "snapshot": sn, "pos_group": pos, "def_code": code, "method": method, "k": k,
                            "n_candidates": rs[0]["n_candidates"], "n_positive": rs[0]["n_positive"],
                            "hits": sum(r["hits"] for r in rs) / n, "precision": sum(r["precision"] for r in rs) / n,
                            "recall": (sum(rec) / len(rec)) if rec else None, "n_runs": n})
                    log(f"[BACKTEST] {sn} {pos} {code} {method}: P@20={acc[20][0]['precision'] if method != 'random' else sum(r['precision'] for r in acc[20]) / len(acc[20]):.3f} "
                        f"(cands {acc[20][0]['n_candidates']}, pos {acc[20][0]['n_positive']}, {time.perf_counter() - t0:.1f}s)")
    conn.close()
    return rows
