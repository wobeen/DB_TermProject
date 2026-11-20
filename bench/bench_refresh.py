"""갱신 비용: build_player_season 전체 vs 1시즌, build_snapshot 소요 시간, DB 파일 크기(인덱스 유무 · 파생 테이블).
모두 복사본(data/bench_work.sqlite)에서 실행한다. 메인 DB는 건드리지 않는다."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_queries as B  # noqa: E402
from make_variants import B1_PATH, WORK_PATH, make_work  # noqa: E402
from pipeline import derive  # noqa: E402
from scouting.db import DEFAULT_DB_PATH, connect  # noqa: E402

ONE_SEASON = 2025
DERIVED = ("player_season", "player_season_metric", "player_season_z", "cohort_baseline", "world_class_label",
           "competition_season_strength")


def _t(fn):
    t = time.perf_counter()
    r = fn()
    return time.perf_counter() - t, r


def table_sizes(path: Path) -> dict[str, int]:
    """dbstat 가상 테이블로 객체별 바이트 수(테이블 + 인덱스)를 구한다."""
    conn = sqlite3.connect(path)
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name")}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def derived_size_rows(log) -> list[dict]:
    """dbstat 이 없는 빌드를 위해: B1 복사본에서 파생 테이블 행을 지우고 VACUUM 한 크기 차이 = 파생 테이블 저장 공간(인덱스 제외)."""
    import shutil
    tmp = B1_PATH.with_name("bench_size.sqlite")
    shutil.copyfile(B1_PATH, tmp)
    conn = sqlite3.connect(tmp, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = OFF")
    before = tmp.stat().st_size
    out = []
    for t in ("player_season_z", "player_season_metric", "cohort_baseline", "world_class_label", "player_season",
              "competition_season_strength"):  # 고정 이름
        conn.execute(f"DELETE FROM {t}")
    conn.execute("VACUUM")
    conn.close()
    after = tmp.stat().st_size
    tmp.unlink()
    out.append({"operation": "derived tables bytes (6 tables, no ix_ indexes; B1 size minus size after emptying them)",
                "value": before - after, "unit": "bytes", "rows": None, "note": "bytes (VACUUM diff)"})
    log(f"[REFRESH] derived tables: {(before - after) / 1e6:,.1f} MB")
    return out


def run(quick: bool, log) -> list[dict]:
    rows: list[dict] = []

    def add(op, value, n=None, note=""):
        unit = "bytes" if "bytes" in note else "s"
        rows.append({"operation": op, "value": value, "unit": unit, "rows": n, "note": note})
        log(f"[REFRESH] {op}: " + (f"{value:,.0f} bytes" if unit == "bytes" else f"{value:.2f}s")
            + (f" ({n} rows)" if n is not None else ""))

    make_work()
    conn = connect(WORK_PATH)
    reps = 1 if quick else 3
    snaps = [r["snapshot_id"] for r in conn.execute("SELECT snapshot_id FROM snapshot WHERE name IN ('current','bt2018')")]
    cur_id = conn.execute("SELECT snapshot_id FROM snapshot WHERE name='current'").fetchone()[0]

    for i in range(reps):
        s, n = _t(lambda: derive.build_player_season(conn, [ONE_SEASON]))
        add(f"build_player_season(1 season={ONE_SEASON}) run{i + 1}", s, n)
    for i in range(reps):
        s, n = _t(lambda: derive.build_snapshot(conn, cur_id))
        add(f"build_snapshot(current) run{i + 1}", s, n["z"], "z rows")
    if not quick:
        s, n = _t(lambda: derive.build_player_season(conn))
        add("build_player_season(all 2012-2025)", s, n)
        for sid in snaps:  # 전체 재계산 후 모든 스냅샷 재빌드
            s, n = _t(lambda sid=sid: derive.build_snapshot(conn, sid))
            name = conn.execute("SELECT name FROM snapshot WHERE snapshot_id=?", (sid,)).fetchone()[0]
            add(f"build_snapshot({name}) after full rebuild", s, n["z"], "z rows")
    conn.close()

    # 크기: 메인(인덱스 있음, = B2/P) vs B1(인덱스 없음)
    main_sz, b1_sz = DEFAULT_DB_PATH.stat().st_size, B1_PATH.stat().st_size
    add("db_size_bytes main(with ix_ indexes)", main_sz, None, "bytes")
    add("db_size_bytes B1(no ix_ indexes)", b1_sz, None, "bytes")
    for r in derived_size_rows(log):
        rows.append(r)
    sizes = table_sizes(DEFAULT_DB_PATH)
    if sizes:
        derived = sum(v for k, v in sizes.items() if k in DERIVED or k.startswith("sqlite_autoindex_player_season")
                      or k in ("ix_player_season_cohort", "ix_psm_metric_season", "ix_psz_cohort", "ix_wcl_snapshot_def_flag"))
        tab_only = sum(v for k, v in sizes.items() if k in DERIVED)
        ixs = sum(v for k, v in sizes.items() if k.startswith("ix_"))
        add("derived tables bytes (6 tables incl. PK)", tab_only, None, "bytes (dbstat)")
        add("derived tables + their ix_ indexes bytes", derived, None, "bytes (dbstat)")
        add("all ix_ indexes bytes", ixs, None, "bytes (dbstat)")
        for k in sorted(sizes, key=sizes.get, reverse=True)[:12]:
            add(f"object_bytes {k}", sizes[k], None, "bytes (dbstat top12)")
    return rows
