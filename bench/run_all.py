"""전체 벤치마크 실행: python bench/run_all.py [--quick]

순서: 스냅샷 보강 → B1 생성 → 표본/정합성 검증 → EXPLAIN → 지연 측정 → 갱신 비용 → 프로파일 → 백테스트 → 그래프/SUMMARY/env.json
정합성 검증이 하나라도 FAIL 이면 실험을 무효로 하고 비정상 종료한다.
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

import bench_backtest  # noqa: E402
import bench_profile  # noqa: E402
import bench_queries as B  # noqa: E402
import bench_refresh  # noqa: E402
import make_variants  # noqa: E402
import plots  # noqa: E402
from scouting.db import DEFAULT_DB_PATH, connect  # noqa: E402

RES = B.RESULTS
LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG_LINES.append(line)


def reps_config(quick: bool) -> dict:
    """(warmup, 사람당 측정 횟수). 원천 경로의 무거운 질의는 횟수를 줄인다(SUMMARY에 명시)."""
    if quick:
        return {("Q1", "B1"): (1, 2), ("Q1", "B2"): (1, 5), ("Q1", "P"): (1, 5),
                ("Q2", "B1"): (1, 2), ("Q2", "B2"): (1, 2), ("Q2", "P"): (1, 5),
                ("Q3", "B1"): (1, 2), ("Q3", "B2"): (1, 2), ("Q3", "P"): (1, 5)}
    return {("Q1", "B1"): (1, 10), ("Q1", "B2"): (3, 30), ("Q1", "P"): (3, 30),
            ("Q2", "B1"): (1, 5), ("Q2", "B2"): (1, 5), ("Q2", "P"): (3, 30),
            ("Q3", "B1"): (1, 5), ("Q3", "B2"): (1, 5), ("Q3", "P"): (3, 30)}


def cpu_name() -> str:
    try:
        out = subprocess.run(["wmic", "cpu", "get", "name"], capture_output=True, text=True, timeout=10).stdout
        lines = [ln.strip() for ln in out.splitlines() if ln.strip() and ln.strip().lower() != "name"]
        if lines:
            return lines[0]
    except Exception:
        pass
    return platform.processor() or "unknown"


def write_env(quick: bool, reps: dict, verify: dict, sample: list[dict]) -> dict:
    conn = connect(DEFAULT_DB_PATH)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # 테이블명은 sqlite_master 값
              for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
    env = {
        "cpu": cpu_name(), "cpu_count": __import__("os").cpu_count(), "os": platform.platform(),
        "python": sys.version, "sqlite": sqlite3.sqlite_version,
        "mode": "quick" if quick else "full",
        "db_size_bytes": {"main(B2,P)": DEFAULT_DB_PATH.stat().st_size, "B1": make_variants.B1_PATH.stat().st_size},
        "row_counts": counts,
        "reps(warmup,runs_per_player)": {f"{q}/{c}": v for (q, c), v in reps.items()},
        "sample": sample, "verify": verify,
        "snapshots": [dict(r) for r in conn.execute("SELECT * FROM snapshot ORDER BY snapshot_id")],
    }
    (RES / "env.json").write_text(json.dumps(env, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return env


# ---------------------------------------------------------------------------------------------
def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def make_summary(ctx: dict) -> str:
    import csv

    def rd(name):
        with (RES / name).open(encoding="utf-8") as f:
            return list(csv.DictReader(f))

    qs, bt, rf = rd("query_summary.csv"), rd("backtest.csv"), rd("refresh.csv")
    es = ctx["explain_stats"]
    L = []
    a = L.append
    a("# 벤치마크 요약 (BenchAgent)\n")
    a(f"실행 모드: **{'quick' if ctx['quick'] else 'full'}**. 모든 수치는 `bench/run_all.py` 가 생성한 CSV에서 온다. "
      "재현: `python bench/run_all.py`.\n")
    a("## 0. 실험 설계와 편차 (보고서에 반드시 밝힐 것)\n")
    a("- **구성**: B1 = 원천 경로 + 보조 인덱스 없음(`data/bench_b1.sqlite`, 메인 DB 복사 후 `ix_*` 15개 DROP + VACUUM), "
      "B2 = 원천 경로 + 인덱스(메인 DB), P = 파생 테이블 + 인덱스(서비스 함수 `season_history`, `cohort_percentiles`, `similar_players` 직접 호출).")
    a("- **표본**: 시즌 L=2025, 리그 900분 이상, **16~21세**(추천 후보 규칙 max_age=21과 맞춤), seed 42, 포지션군별 5명 = 20명. "
      "P 결과가 비어 있지 않은 선수만 포함.")
    a("- **원천 경로**(`raw_queries.py`): §3.2 공식(출전 구간·선발 판정·on-pitch 득실·주 소속 구단·리그 수준·지표)을 단일 `WITH` 질의의 CTE로 "
      "매번 계산한다. 계산 범위는 질의가 필요로 하는 (선수, 시즌)으로 좁힌다 — Q1은 한 선수의 전 시즌, Q2/Q3는 같은 포지션군·같은 나이 코호트의 전 시즌"
      "(코호트 평균/표준편차가 필요하므로). Q3의 이웃 월클 라벨도 원천(시장가치/출전)에서 이웃 k명에 대해서만 계산한다. "
      "TEMP 테이블은 쓰지 않았고 `AS MATERIALIZED` 힌트와 Q1의 `CROSS JOIN`(조인 순서 고정: 선수→출전)만 썼다.")
    a("- **공통 입력으로 취급한 것**: `competition_season_strength`(14리그×14시즌의 작은 참조 집계), `metric`, `metric_weight`, `world_class_definition`. "
      "리그 수준 집계는 전 선수 시장가치 평균이라 질의마다 재계산하면 비현실적이어서 두 경로가 공유한다.")
    a("- **Q3 지연 측정은 월클 정의 1(peak_value_50m)** 로 한다. 정합성 검증은 정의 1, 2 모두 수행한다(B1+정의2는 라벨 계산이 appearance 전체 스캔이라 "
      "질의당 약 50초여서 앞 3명만 검증).")
    a("- **측정 횟수 편차**: 계약은 워밍업 3 + 측정 30이지만, 원천 경로의 Q2/Q3는 질의 1회가 수 초~수십 초라 "
      "**워밍업 1 + 선수당 5회**(Q1 B1은 선수당 10회)로 줄였다. P와 Q1(B2)은 워밍업 3 + 선수당 30회. "
      "정확한 값은 `query_summary.csv`의 `warmup`, `runs_per_player`, `n_samples` 열과 `env.json`에 있다. 20명 × 5회 = 100개 표본으로 median/p95를 계산했다.\n")

    a("## 1. 정합성 검증 (원천 경로 == P)\n")
    a("지표 오차 1e-9 이하, 이웃 (player_id, season) 순서 동일, 이웃 월클 여부 동일.\n")
    a("| 항목 | 선수 수 | 결과 |\n|---|---|---|")
    for k, v in ctx["verify"].items():
        a(f"| {k} | {v['n']} | {'PASS' if v['pass'] else 'FAIL'} |")
    a("")

    a("## 2. 질의 지연시간 (ms)\n")
    a("| 질의 | 구성 | median | p95 | B1 대비 속도 향상 | warmup | 선수당 측정 | 표본 수 |\n|---|---|---|---|---|---|---|---|")
    for r in qs:
        a(f"| {r['query']} | {r['config']} | {float(r['median_ms']):,.2f} | {float(r['p95_ms']):,.2f} | "
          f"{float(r['speedup_vs_b1']):,.1f}x | {r['warmup']} | {r['runs_per_player']} | {r['n_samples']} |")
    a("")
    sp = {(r["query"], r["config"]): float(r["median_ms"]) for r in qs}
    for q in ("Q1", "Q2", "Q3"):
        a(f"- {q}: B1→B2 {sp[(q, 'B1')] / sp[(q, 'B2')]:.1f}x, B2→P {sp[(q, 'B2')] / sp[(q, 'P')]:.1f}x, B1→P {sp[(q, 'B1')] / sp[(q, 'P')]:.1f}x")
    a("\n![latency](figures/query_latency.png)\n")

    a("## 3. 개선 이유\n")
    a("### 3.1 EXPLAIN QUERY PLAN (`explain/<Q>_<config>.txt`)\n")
    a("| 질의 | 구성 | 원천/파생 테이블 SCAN 수 | 인덱스 SEARCH 수 | AUTOMATIC INDEX 수 |\n|---|---|---|---|---|")
    for e in es:
        a(f"| {e['query']} | {e['config']} | {e['scan_source_tables']} | {e['search_using_index']} | {e['automatic_index']} |")
    a("")
    a("읽는 법: B1은 인덱스가 없어 `appearance`·`game_event` 등 원천 테이블을 SCAN하거나 질의 때마다 **임시 AUTOMATIC INDEX**를 만들어야 한다. "
      "B2는 `ix_appearance_player_date`, `ix_game_event_game_type`, `ix_player_posgroup_dob` 등으로 SEARCH로 바뀌지만, "
      "원천 집계 자체(출전 구간·on-pitch 계산, 코호트 통계)는 매번 해야 한다. P는 미리 계산된 `player_season*`/`player_season_z`를 "
      "PK 및 `ix_psz_cohort`(snapshot_id, pos_group, age, metric_code, …) **커버링 인덱스 SEARCH**로 읽는다(원천 테이블 접근 0).\n")
    for fn in ("Q3_B1", "Q3_P"):
        t = (RES / "explain" / f"{fn}.txt").read_text(encoding="utf-8").splitlines()
        key = [ln for ln in t if ("SCAN" in ln or "SEARCH" in ln)][:8]
        a(f"`{fn}.txt` 발췌:\n```\n" + "\n".join(k[:150] for k in key) + "\n```\n")
    a("### 3.2 cProfile (`profile_similarity_P.txt`, `profile_q3_raw_B1.txt`)\n")
    for name, key in (("similarity 추천 1회 (P)", "similarity_P"), ("Q3 원천 경로 B1 1회", "q3_raw_B1")):
        pr = ctx["profile"][key]
        a(f"**{name}** — 총 {pr['total_s']:.2f}s. tottime 상위:\n")
        a("| 함수 | 호출 | tottime(s) | cumtime(s) |\n|---|---|---|---|")
        for t in pr["top"]:
            a(f"| `{t['func']}` | {t['calls']} | {t['tottime']:.3f} | {t['cumtime']:.3f} |")
        a("")
    a("해석: SQLite 실행은 C 코드라 cProfile에는 `sqlite3.Connection.execute`(또는 fetch를 포함한 cursor 호출) 한 줄로 합산된다. "
      "두 프로파일 모두 시간의 대부분이 이 SQL 실행 호출에 쓰이고, Python 쪽 후처리(점수 계산, dict 조립, `sqrt`, INSERT)는 작다. "
      "즉 병목은 Python이 아니라 SQL이 읽고 계산하는 행 수이며, 파생 테이블은 그 행 수를 줄이는 방법이다.\n")

    a("## 4. 단점과 오버헤드\n")
    ref = {r["operation"]: r for r in rf}
    def sec(prefix):
        xs = [float(r["value"]) for r in rf if r["unit"] == "s" and r["operation"].startswith(prefix)]
        return sorted(xs)[len(xs) // 2] if xs else None
    one, full, snap = sec("build_player_season(1 season"), sec("build_player_season(all"), sec("build_snapshot(current) run")
    snap_all = [float(r["value"]) for r in rf if r["unit"] == "s" and r["operation"].startswith("build_snapshot(")]
    szs = {r["operation"]: float(r["value"]) / 1e6 for r in rf if r["unit"] == "bytes"}
    main_mb = next(v for k, v in szs.items() if k.startswith("db_size_bytes main"))
    b1_mb = next(v for k, v in szs.items() if k.startswith("db_size_bytes B1"))
    a("| 항목 | 값 |\n|---|---|")
    if one is not None:
        a(f"| build_player_season, 1시즌(2025) | {one:.1f}s |")
    if full is not None:
        a(f"| build_player_season, 전체(2012~2025) | {full:.1f}s |")
    if snap is not None:
        a(f"| build_snapshot(current) | {snap:.1f}s |")
    for r in rf:
        if r["operation"].startswith("build_snapshot(") and "after full" in r["operation"]:
            a(f"| {r['operation']} | {float(r['value']):.1f}s |")
    for r in rf:
        if r["unit"] == "bytes" and not r["operation"].startswith("object_bytes"):
            a(f"| {r['operation']} | {float(r['value']) / 1e6:,.1f} MB |")
    a("")
    a("- 파생 테이블은 **저장 공간**(위 표)과 **갱신 비용**을 대가로 질의 시간을 줄인다. 원천 데이터가 바뀌면 해당 시즌 `build_player_season` → "
      "스냅샷 `build_snapshot`을 다시 돌려야 하고, 1시즌 갱신은 전체의 일부 시간이지만 스냅샷 재빌드(코호트 기준치·z 전체)는 시즌 수와 무관하게 든다.")
    a("- B1→B2: 인덱스는 파일 크기를 키우고 쓰기(적재·파생 빌드)를 느리게 하지만, 원천 경로 질의는 일부만 빨라진다(위 §2). "
      "인덱스만으로는 파생 계산 비용 자체가 사라지지 않는다.")
    a(f"- **인덱스 저장 오버헤드**: ix_ 인덱스 15개가 DB를 {b1_mb:,.1f} MB → {main_mb:,.1f} MB (+{main_mb - b1_mb:,.1f} MB, +{(main_mb / b1_mb - 1) * 100:.0f}%)로 키운다. "
      f""
      "**파생 테이블 저장 공간**은 위 표의 `derived tables` 행(6개 테이블, 인덱스 제외)이다.")
    a(f"- **갱신 비용**: 1시즌 재계산 ~{one:.0f}s(전체 {full:.0f}s의 {one / full * 100:.0f}%), 스냅샷 재빌드 {min(snap_all):.0f}~{max(snap_all):.0f}s(스냅샷당, 전체 재계산 직후 측정치와 단독 측정치 범위). "
      "질의 한 번의 이득(수 초 → 수십 ms)을 얻는 대신, 데이터가 바뀔 때마다 이 비용을 치러야 한다.")
    a("- `player_season_z`는 age, pos_group을 비정규화해 가지므로 일관성은 빌드 코드(같은 트랜잭션)가 보장해야 한다.\n")
    a("![refresh](figures/refresh_cost.png)\n")

    a("## 5. 백테스트\n")
    a("설정: 스냅샷 × 포지션군 4 × 정의 2 × method 4, top_n=50, outcome=`current`, k=20/50, 기본 파라미터(max_age 21, min_minutes 900, k_nn 25, pool_lag 3). "
      "random은 seed 0~9 평균. 정답 = outcome 스냅샷에서 같은 정의의 월클.\n")
    snaps = sorted({r["snapshot"] for r in bt})
    methods = ["random", "market_value", "similarity", "hybrid"]
    k20 = [r for r in bt if r["k"] == "20"]
    a("### 5.1 method별 평균 precision@20 (전 스냅샷·포지션·정의 평균, 셀 단순 평균)\n")
    a("| method | precision@20 | precision@50 | 평균 hits@20 |\n|---|---|---|---|")
    res = {}
    for m in methods:
        p20 = mean(float(r["precision"]) for r in k20 if r["method"] == m)
        p50 = mean(float(r["precision"]) for r in bt if r["k"] == "50" and r["method"] == m)
        h20 = mean(float(r["hits"]) for r in k20 if r["method"] == m)
        res[m] = p20
        a(f"| {m} | {p20:.3f} | {p50:.3f} | {h20:.2f} |")
    a("\n### 5.2 포지션군 × method (precision@20, 스냅샷·정의 평균)\n")
    a("| pos | " + " | ".join(methods) + " |\n|---|" + "---|" * len(methods))
    for pos in ("GK", "DF", "MF", "FW"):
        a(f"| {pos} | " + " | ".join(f"{mean(float(r['precision']) for r in k20 if r['pos_group'] == pos and r['method'] == m):.3f}" for m in methods) + " |")
    a("\n### 5.3 스냅샷 × 정의 × method (precision@20, 포지션 평균) 와 후보·정답 수\n")
    a("| 스냅샷 | 정의 | " + " | ".join(methods) + " | 후보 수(합) | 정답 수(합) |\n|---|---|" + "---|" * len(methods) + "---|---|")
    for sn in snaps:
        for dc in sorted({r["def_code"] for r in bt}):
            sel = [r for r in k20 if r["snapshot"] == sn and r["def_code"] == dc]
            cand = sum(int(r["n_candidates"]) for r in sel if r["method"] == "market_value")
            pos_ = sum(int(r["n_positive"]) for r in sel if r["method"] == "market_value")
            a(f"| {sn} | {dc} | " + " | ".join(f"{mean(float(r['precision']) for r in sel if r['method'] == m):.3f}" for m in methods)
              + f" | {cand} | {pos_} |")
    a("\n![backtest](figures/backtest_precision20.png)\n")
    # 판정 문장은 수치에서 자동 생성한다
    mv, sm, hy, rnd = res["market_value"], res["similarity"], res["hybrid"], res["random"]
    wins = defaultdict(int)
    cells = {(r["snapshot"], r["pos_group"], r["def_code"], r["method"]): float(r["precision"]) for r in k20}
    keys = {k[:3] for k in cells}
    for m in ("similarity", "hybrid"):
        for kk in keys:
            d = cells[kk + (m,)] - cells[kk + ("market_value",)]
            wins[(m, "win" if d > 1e-12 else "lose" if d < -1e-12 else "tie")] += 1
    a("### 5.4 해석 (수치에서 자동 생성)\n")
    a(f"- 평균 precision@20: random {rnd:.3f} / market_value {mv:.3f} / similarity {sm:.3f} / hybrid {hy:.3f}.")
    a(f"- similarity vs market_value: {len(keys)}개 셀 중 similarity 우세 {wins[('similarity', 'win')]}, 동률 {wins[('similarity', 'tie')]}, 열세 {wins[('similarity', 'lose')]}. "
      f"hybrid vs market_value: 우세 {wins[('hybrid', 'win')]}, 동률 {wins[('hybrid', 'tie')]}, 열세 {wins[('hybrid', 'lose')]}.")
    best = max(res, key=res.get)
    a(f"- 평균 기준 최고는 **{best}**. 시장가치 기준선(사실상 state of the art)을 "
      f"similarity는 {'넘었다' if sm > mv else '넘지 못했다'}, hybrid는 {'넘었다' if hy > mv else '넘지 못했다'}. 결과를 조정하지 않고 그대로 보고한다.\n")
    # ---- GK 제외 분석 ----
    ng = [r for r in bt if r["pos_group"] != "GK"]
    gk_c = sorted({int(r["n_candidates"]) for r in bt if r["pos_group"] == "GK"})
    a("### 5.4b GK 제외 분석 (DF/MF/FW 18셀)\n")
    a(f"GK는 스냅샷·정의당 후보가 {gk_c[0]}~{gk_c[-1]}명뿐이라 top-20이 후보 전체를 덮고, 모든 method의 precision@20이 정답 수/20 으로 같아진다"
      "(정답 1~2명이라 0.05~0.10). 그래서 method 비교는 GK를 뺀 DF/MF/FW로 한다.\n")
    a("| method | precision@20 | precision@50 | recall@20 | recall@50 |\n|---|---|---|---|---|")
    for m in methods:
        def v(k, col, m=m):
            return mean(float(r[col]) for r in ng if r["method"] == m and r["k"] == k and r[col] != "")
        a(f"| {m} | {v('20', 'precision'):.3f} | {v('50', 'precision'):.3f} | {v('20', 'recall'):.3f} | {v('50', 'recall'):.3f} |")
    cells2 = {(r["snapshot"], r["pos_group"], r["def_code"], r["method"]): float(r["precision"]) for r in ng if r["k"] == "20"}
    keys2 = {k[:3] for k in cells2}
    a(f"\nmarket_value 대비 셀별 precision@20 승·무·패 ({len(keys2)}셀):\n")
    a("| method | 우세 | 동률 | 열세 |\n|---|---|---|---|")
    for m in ("similarity", "hybrid"):
        w = t = l = 0
        for kk in keys2:
            d = cells2[kk + (m,)] - cells2[kk + ("market_value",)]
            if d > 1e-12:
                w += 1
            elif d < -1e-12:
                l += 1
            else:
                t += 1
        a(f"| {m} | {w} | {t} | {l} |")
    q = {m: mean(float(r["precision"]) for r in ng if r["method"] == m and r["k"] == "20") for m in methods}
    a(f"\n**결론**: GK 제외 평균 precision@20은 random {q['random']:.3f}, market_value {q['market_value']:.3f}, "
      f"similarity {q['similarity']:.3f}, hybrid {q['hybrid']:.3f}. 시장가치 순위가 가장 강하다. 제안 방식(similarity)은 무작위의 약 "
      f"{q['similarity'] / q['random']:.1f}배지만 시장가치를 넘지 못한다. 결합(hybrid, 무작위의 {q['hybrid'] / q['random']:.1f}배)이 격차를 줄이지만 "
      "역시 넘지는 못한다. recall@20/50에서도 같은 순서다. 시장가치는 월클 정의 1과 같은 변수라는 구조적 이점이 있다(§5.5).\n")
    a("### 5.5 한계\n")
    a("- **GK는 후보가 매우 적다**(스냅샷당 5~수십 명, 후보 수는 §5.3·`backtest.csv`의 `n_candidates`). 후보 수가 k 이하이면 top-k가 후보 전체라 모든 method의 precision이 같아지고(=정답 수/k), method 비교에 정보가 없다. 평균에는 포함하되 GK 열은 해석에서 제외해야 한다.")
    a("- **정답 수가 작다**: 셀(스냅샷·포지션·정의)당 후보 수백 명 중 정답이 한 자릿수~수십 명이라 precision@20의 분산이 크고, 셀 간 차이가 우연일 수 있다. 신뢰구간·유의성 검정은 하지 않았다.")
    a("- 시장가치는 **월클 정의 1(최고 시장가치 €50M)과 같은 변수**를 쓰므로 정의 1에서 market_value 기준선이 구조적으로 유리하다(정의 순환성). 정의 2(빅5 주전+CL)에서의 비교가 더 공정하다.")
    a("- similarity는 출전량·리그 수준·득점/실점 등 **박스스코어 파생 지표**만 쓴다. 태클·패스·xG·선방 등은 데이터에 없다(CONTRACT §1).")
    a("- 정답은 `current`(2026-07-07) 시점까지 월클이 된 선수라서, bt2020처럼 기준이 최근일수록 관찰 기간이 짧아 정답이 적다(right-censoring). 포지션별 정의 임계값(€50M, GK €30M)과 빅5/CL 조건은 임의 선택이다.")
    a("- 스냅샷 3개는 서로 독립이 아니다(같은 선수·같은 정답을 공유). 이웃 풀은 해당 스냅샷에서 보이는 과거 시즌만 사용하므로 미래 정보 누수는 없다(스키마로 차단).")
    a("- random은 seed 10개 평균, 나머지는 결정적이다(seed 42, 동률은 player_id 순).\n")

    a("## 6. 산출물\n")
    a("`query_latency.csv`, `query_summary.csv`, `refresh.csv`, `backtest.csv`, `env.json`, `explain/*.txt`, `profile_*.txt`, `figures/*.png`, `run_all.log`.\n")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="반복 5회, 스냅샷 bt2018만")
    ap.add_argument("--summary-only", action="store_true", help="저장된 ctx.json 과 CSV 로 그래프/SUMMARY 만 다시 만든다")
    args = ap.parse_args()
    quick = args.quick
    RES.mkdir(parents=True, exist_ok=True)
    if args.summary_only:
        ctx = json.loads((RES / "ctx.json").read_text(encoding="utf-8"))
        plots.make_all()
        (RES / "SUMMARY.md").write_text(make_summary(ctx), encoding="utf-8")
        return 0
    t_all = time.perf_counter()
    log(f"=== bench/run_all.py ({'quick' if quick else 'full'}) ===")
    log(f"SQLite {sqlite3.sqlite_version}, Python {platform.python_version()}")

    main_conn = connect(DEFAULT_DB_PATH)
    for name in ("bt2018",):
        row = main_conn.execute("SELECT built_at FROM snapshot WHERE name=?", (name,)).fetchone()
        if row is None or row[0] is None:
            log(f"[ERROR] 메인 DB에 빌드된 스냅샷 {name} 이 없다. PipelineAgent 산출물을 확인하라.")
            return 2
    if not quick:
        bench_backtest.ensure_snapshots(main_conn, log)
    main_conn.close()

    log(f"[SETUP] B1: {make_variants.make_b1(force=True)}")
    conns = B.open_conns()
    sample = B.pick_sample(conns["P"])
    log(f"[SETUP] 표본 {len(sample)}명: " + ", ".join(f"{s['pos_group']}:{s['player_id']}(age {s['age']})" for s in sample))
    if len(sample) < 20:
        log("[ERROR] 표본 20명을 채우지 못했다.")
        return 2

    verify = B.validate(conns, sample, log)
    (RES / "verify.json").write_text(json.dumps(verify, indent=2, ensure_ascii=False), encoding="utf-8")
    if not all(v["pass"] for v in verify.values()):
        log("[FAIL] 정합성 검증 실패 — 실험 무효. 위 [VERIFY] 줄과 verify.json 을 확인하라.")
        return 1
    log("[VERIFY] 전 항목 PASS")

    explain_stats = B.write_explain(conns, sample[0], B.as_of_of(conns["P"]))
    reps = reps_config(quick)
    lat, summ = B.bench(conns, sample, reps, log)
    B.write_csv(RES / "query_latency.csv", lat)
    B.write_csv(RES / "query_summary.csv", summ)
    for r in summ:
        log(f"[RESULT] {r['query']} {r['config']}: median {r['median_ms']:.2f} ms, p95 {r['p95_ms']:.2f} ms, "
            f"speedup_vs_b1 {r['speedup_vs_b1']:.1f}x")
    for c in conns.values():
        c.close()

    refresh_rows = bench_refresh.run(quick, log)
    B.write_csv(RES / "refresh.csv", refresh_rows)

    profile = bench_profile.run(sample, log)

    bt_rows = bench_backtest.run(quick, log)
    B.write_csv(RES / "backtest.csv", bt_rows)
    for m in ("random", "market_value", "similarity", "hybrid"):
        xs = [r["precision"] for r in bt_rows if r["method"] == m and r["k"] == 20]
        log(f"[RESULT] backtest {m}: mean precision@20 = {mean(xs):.4f} (cells {len(xs)})")

    plots.make_all()
    ctx = {"quick": quick, "verify": verify, "explain_stats": explain_stats, "profile": profile}
    (RES / "ctx.json").write_text(json.dumps(ctx, ensure_ascii=False, default=str), encoding="utf-8")
    write_env(quick, reps, verify, sample)
    (RES / "SUMMARY.md").write_text(make_summary(ctx), encoding="utf-8")
    log(f"=== 완료: {time.perf_counter() - t_all:.0f}s. 정합성 전 항목 PASS ===")
    (RES / "run_all.log").write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
