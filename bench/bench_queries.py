"""Q1/Q2/Q3 지연시간 측정 + 원천 경로와 P 경로의 결과 일치 검증 + EXPLAIN QUERY PLAN 저장.

구성: B1(원천 경로, 인덱스 없음) / B2(원천 경로, 인덱스 있음) / P(파생 테이블 + 서비스 함수).
"""

from __future__ import annotations

import csv
import random
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from scouting.db import DEFAULT_DB_PATH, connect  # noqa: E402
from scouting.services import players as svc  # noqa: E402
from scouting.services.knn import KNN_SQL  # noqa: E402

import raw_queries as R  # noqa: E402
from make_variants import B1_PATH  # noqa: E402

RESULTS = ROOT / "bench" / "results"
SNAP_ID = 1  # current
TOL = 1e-9
K = 10
BENCH_DEF = 1  # Q3 지연 측정에 쓰는 월클 정의(peak_value_50m). 검증은 두 정의 모두 수행


def pctl(xs: list[float], q: float) -> float:
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def pick_sample(conn, n_per_pos: int = 5, seed: int = 42) -> list[dict]:
    """시즌 L(=2025)에 리그 900분 이상, 16~21세. 포지션군별 5명, seed 42. P 질의 결과가 비어 있지 않은 선수만."""
    L = conn.execute("SELECT MAX(season) FROM v_player_season_asof WHERE snapshot_id = ?", (SNAP_ID,)).fetchone()[0]
    out = []
    for pos in ("GK", "DF", "MF", "FW"):
        ids = [dict(r) for r in conn.execute(
            "SELECT player_id, age, pos_group FROM player_season WHERE season = ? AND pos_group = ? "
            "AND league_minutes >= 900 AND age BETWEEN 16 AND 21 ORDER BY player_id", (L, pos))]
        random.Random(seed).shuffle(ids)
        got = 0
        for d in ids:
            if svc.cohort_percentiles(conn, SNAP_ID, d["player_id"], L) and \
               svc.similar_players(conn, SNAP_ID, d["player_id"], L, k=K, def_id=BENCH_DEF):
                out.append({**d, "season": L})
                got += 1
                if got == n_per_pos:
                    break
    return out


def as_of_of(conn) -> str:
    return conn.execute("SELECT as_of_date FROM snapshot WHERE snapshot_id = ?", (SNAP_ID,)).fetchone()[0]


def run_q(q: str, config: str, conn, s: dict, as_of: str, def_id: int = BENCH_DEF):
    pid, L = s["player_id"], s["season"]
    if config == "P":
        if q == "Q1":
            return svc.season_history(conn, pid)
        if q == "Q2":
            return svc.cohort_percentiles(conn, SNAP_ID, pid, L)
        return svc.similar_players(conn, SNAP_ID, pid, L, k=K, def_id=def_id)
    if q == "Q1":
        return R.q1_raw(conn, pid)
    if q == "Q2":
        return R.q2_raw(conn, as_of=as_of, player_id=pid, season=L, pos_group=s["pos_group"], age=s["age"])
    return R.q3_raw(conn, as_of=as_of, player_id=pid, season=L, pos_group=s["pos_group"], age=s["age"],
                    def_id=def_id, k=K)


# ------------------------------------------------------------------ 정합성 검증
def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) <= TOL
    return a == b


def compare(q: str, raw, p) -> list[str]:
    errs: list[str] = []
    if q == "Q1":
        if [r["season"] for r in raw] != [r["season"] for r in p]:
            return [f"seasons differ raw={[r['season'] for r in raw]} p={[r['season'] for r in p]}"]
        for a, b in zip(raw, p):
            for k, v in a.items():
                if k not in b:
                    errs.append(f"season {a['season']}: key {k} missing in P")
                elif not _close(v, b[k]):
                    errs.append(f"season {a['season']} {k}: raw={v} p={b[k]}")
            for k in b:
                if k.startswith("m_") and k not in a:
                    errs.append(f"season {a['season']}: metric {k} missing in raw")
    elif q == "Q2":
        ra, pb = {r["metric_code"]: r for r in raw}, {r["metric_code"]: r for r in p}
        if set(ra) != set(pb):
            return [f"metrics differ raw={sorted(ra)} p={sorted(pb)}"]
        for m in ra:
            for k in ("value", "percentile", "cohort_n"):
                if not _close(ra[m][k], pb[m][k]):
                    errs.append(f"{m}.{k}: raw={ra[m][k]} p={pb[m][k]}")
    else:
        if [(r["player_id"], r["season"]) for r in raw] != [(r["player_id"], r["season"]) for r in p]:
            return [f"neighbors differ raw={[(r['player_id'], r['season']) for r in raw]} "
                    f"p={[(r['player_id'], r['season']) for r in p]}"]
        for a, b in zip(raw, p):
            if not _close(a["distance"], b["distance"]):
                errs.append(f"distance nb {a['player_id']}: raw={a['distance']} p={b['distance']}")
            if int(a["is_wc"]) != int(b["is_wc"]):
                errs.append(f"is_wc nb {a['player_id']}: raw={a['is_wc']} p={b['is_wc']}")
    return errs


def validate(conns: dict, sample: list[dict], log, b1_def2_n: int = 3) -> dict:
    """모든 표본에 대해 raw(B2, B1) == P 확인. 항목별 PASS/FAIL 반환."""
    as_of = as_of_of(conns["P"])
    res: dict[str, dict] = {}
    plan = [("Q1", "B2", None), ("Q1", "B1", None), ("Q2", "B2", None), ("Q2", "B1", None),
            ("Q3", "B2", 1), ("Q3", "B2", 2), ("Q3", "B1", 1), ("Q3", "B1", 2)]
    for q, cfg, d in plan:
        key = f"{q}/{cfg}" + (f"/def{d}" if d else "")
        # B1 + 정의 2 의 Q3 는 라벨 계산이 appearance 전체 스캔이라 느려 앞 b1_def2_n 명만 검증
        subset = sample[:b1_def2_n] if (q == "Q3" and cfg == "B1" and d == 2) else sample
        bad: list[str] = []
        t0 = time.perf_counter()
        for s in subset:
            raw = run_q(q, cfg, conns[cfg], s, as_of, d or BENCH_DEF)
            if q == "Q3":
                p = svc.similar_players(conns["P"], SNAP_ID, s["player_id"], s["season"], k=K, def_id=d)
            else:
                p = run_q(q, "P", conns["P"], s, as_of)
            for e in compare(q, raw, p):
                bad.append(f"player {s['player_id']}: {e}")
        res[key] = {"n": len(subset), "pass": not bad, "errors": bad[:5], "seconds": round(time.perf_counter() - t0, 1)}
        log(f"[VERIFY] {key}: {'PASS' if not bad else 'FAIL'} ({len(subset)} players, {res[key]['seconds']}s)"
            + ("" if not bad else " " + "; ".join(bad[:3])))
    return res


# ------------------------------------------------------------------ EXPLAIN
_P_Q1 = ["""SELECT ps.*, c.name AS club_name FROM player_season ps JOIN club c ON c.club_id = ps.main_club_id
               WHERE ps.player_id = :pid ORDER BY ps.season""",
         "SELECT season, metric_code, value FROM player_season_metric WHERE player_id = :pid"]
_P_Q2 = """SELECT COUNT(*) AS n, COALESCE(SUM(cm.value < :v), 0) AS below, COALESCE(SUM(cm.value = :v), 0) AS equal
               FROM v_player_season_asof c
               JOIN player_season_metric cm
                 ON cm.player_id = c.player_id AND cm.season = c.season AND cm.metric_code = :mc
               WHERE c.snapshot_id = :snap AND c.pos_group = :pos AND c.age = :age"""
_SCAN_RE = re.compile(r"\bSCAN (appearance|game|game_event|game_lineup|player|player_valuation|player_season|"
                      r"player_season_metric|player_season_z|world_class_label)\b")


def _plan(conn, sql: str, bind: dict) -> str:
    return "\n".join(f"{r[0]:>4} {r[1]:>4}  {r[3]}" for r in conn.execute("EXPLAIN QUERY PLAN " + sql, bind))


def write_explain(conns: dict, s: dict, as_of: str) -> list[dict]:
    outdir = RESULTS / "explain"
    outdir.mkdir(parents=True, exist_ok=True)
    pid, L, pos, age = s["player_id"], s["season"], s["pos_group"], s["age"]
    rawb = {"as_of": as_of, "pid": pid, "L": L, "pos": pos, "age": age, "k": K, "pool_max": 9999,
            "gk": 30000000, "thr": 50000000}
    stats = []
    for cfg in ("B1", "B2", "P"):
        conn = conns[cfg]
        texts = {}
        if cfg == "P":
            texts["Q1"] = "\n-- stmt 2\n".join(_plan(conn, q, {"pid": pid}) for q in _P_Q1)
            mc = conn.execute("SELECT metric_code FROM player_season_metric WHERE player_id=? AND season=? LIMIT 1",
                              (pid, L)).fetchone()[0]
            texts["Q2"] = _plan(conn, _P_Q2, {"v": 0.5, "snap": SNAP_ID, "pos": pos, "age": age, "mc": mc})
            texts["Q3"] = _plan(conn, KNN_SQL.format(cand_sql="SELECT player_id, age FROM player_season "
                                                    "WHERE player_id = :cand_pid AND season = :L"),
                                {"snap": SNAP_ID, "L": L, "pos": pos, "k": K, "pool_max": 9999, "def_id": BENCH_DEF,
                                 "cand_pid": pid})
        else:
            texts["Q1"] = _plan(conn, R.Q1_SQL, {"pid": pid, "as_of": "9999-12-31"})
            texts["Q2"] = _plan(conn, R.Q2_SQL, {"as_of": as_of, "pid": pid, "L": L, "pos": pos, "age": age})
            texts["Q3"] = _plan(conn, R._Q3_SQL["peak_value"], rawb)
        for q, t in texts.items():
            (outdir / f"{q}_{cfg}.txt").write_text(
                f"# {q} {cfg} EXPLAIN QUERY PLAN (player {pid}, {pos}, age {age})\n{t}\n", encoding="utf-8")
            lines = t.splitlines()
            stats.append({
                "query": q, "config": cfg,
                "scan_source_tables": sum(1 for ln in lines if _SCAN_RE.search(ln)),
                "search_using_index": sum(1 for ln in lines if "SEARCH" in ln and "USING" in ln and "AUTOMATIC" not in ln),
                "automatic_index": sum(1 for ln in lines if "AUTOMATIC" in ln),
            })
    return stats


# ------------------------------------------------------------------ 측정
def bench(conns: dict, sample: list[dict], reps: dict, log) -> tuple[list[dict], list[dict]]:
    """reps[(query, config)] = (warmup, runs_per_player). 반환: latency 행, 요약 행."""
    as_of = as_of_of(conns["P"])
    rows: list[dict] = []
    for q in ("Q1", "Q2", "Q3"):
        for cfg in ("B1", "B2", "P"):
            warm, runs = reps[(q, cfg)]
            t0 = time.perf_counter()
            for s in sample:
                for _ in range(warm):
                    run_q(q, cfg, conns[cfg], s, as_of)
                for i in range(runs):
                    t = time.perf_counter()
                    run_q(q, cfg, conns[cfg], s, as_of)
                    rows.append({"query": q, "config": cfg, "player_id": s["player_id"], "run": i + 1,
                                 "ms": (time.perf_counter() - t) * 1000})
            log(f"[BENCH] {q} {cfg}: warmup {warm} + {runs} runs x {len(sample)} players "
                f"({time.perf_counter() - t0:.0f}s)")
    summ: list[dict] = []
    for q in ("Q1", "Q2", "Q3"):
        med = {}
        part = []
        for cfg in ("B1", "B2", "P"):
            xs = [r["ms"] for r in rows if r["query"] == q and r["config"] == cfg]
            med[cfg] = statistics.median(xs)
            part.append({"query": q, "config": cfg, "median_ms": med[cfg], "p95_ms": pctl(xs, 0.95),
                         "speedup_vs_b1": None, "warmup": reps[(q, cfg)][0],
                         "runs_per_player": reps[(q, cfg)][1], "n_samples": len(xs)})
        for r in part:
            r["speedup_vs_b1"] = med["B1"] / r["median_ms"]
        summ += part
    return rows, summ


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def open_conns() -> dict:
    return {"B1": connect(B1_PATH), "B2": connect(DEFAULT_DB_PATH), "P": connect(DEFAULT_DB_PATH)}
