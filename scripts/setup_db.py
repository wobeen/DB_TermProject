"""빈 DB 생성 → 다운로드 → 적재 → 파생 → 기본 스냅샷 빌드 (CONTRACT §6.2).

사용: python scripts/setup_db.py [--db PATH] [--raw data/raw] [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import derive, download, load  # noqa: E402
from scouting.db import apply_sql, connect, db_path  # noqa: E402

SNAPSHOTS = (("current", "2026-07-07"), ("bt2018", "2018-07-01"))
SQL_BEFORE_LOAD = ("schema.sql", "views.sql", "reference_data.sql")
SQL_AFTER_LOAD = ("indexes.sql",)  # 대량 적재 후 한 번에 만들어 속도를 높인다


def _remove_db(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()


class Timer:
    def __init__(self) -> None:
        self.rows: list[tuple[str, float]] = []

    def step(self, name: str, seconds: float, info: str = "") -> None:
        self.rows.append((name, seconds))
        print(f"[{seconds:8.1f}s] {name}" + (f"  {info}" if info else ""), flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="스카우팅 DB 구축")
    ap.add_argument("--db", default=None, help="DB 경로 (기본 data/scouting.sqlite)")
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"), help="원천 디렉터리")
    ap.add_argument("--force", action="store_true", help="기존 DB를 지우고 다시 만든다")
    args = ap.parse_args(argv)

    path = db_path(args.db)
    if path.exists() and not args.force:
        print(f"오류: {path} 가 이미 있다. 다시 만들려면 --force 를 쓴다.", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    _remove_db(path)

    tm = Timer()
    t_all = time.perf_counter()

    t0 = time.perf_counter()
    tm_dir = download.ensure_dataset(Path(args.raw))
    tm.step("1. 원천 확인(ensure_dataset)", time.perf_counter() - t0, str(tm_dir))

    conn = connect(path)
    t0 = time.perf_counter()
    apply_sql(conn, files=SQL_BEFORE_LOAD)
    tm.step("2. 스키마 생성", time.perf_counter() - t0)

    print("3. 원천 적재")
    t0 = time.perf_counter()
    report = load.load_all(
        conn, tm_dir,
        progress=lambda n, s, rep: print(f"     [{s:7.1f}s] {n:<17} {rep['loaded_rows']:>10,} / 원천 {rep['source_rows']:,}",
                                         flush=True))
    tm.step("3. 원천 적재 합계", time.perf_counter() - t0,
            f"FK 위반 {report['_foreign_key_check']['violations']}건, stub 구단 {report['club']['stub_clubs']:,}")

    t0 = time.perf_counter()
    apply_sql(conn, files=SQL_AFTER_LOAD)
    tm.step("4. 보조 인덱스 생성", time.perf_counter() - t0)

    t0 = time.perf_counter()
    n = derive.build_competition_strength(conn)
    tm.step("5. 리그 수준(competition_season_strength)", time.perf_counter() - t0, f"{n:,}행")

    t0 = time.perf_counter()
    n_ps = derive.build_player_season(conn)
    n_psm = conn.execute("SELECT COUNT(*) FROM player_season_metric").fetchone()[0]
    tm.step("6. player_season + metric", time.perf_counter() - t0, f"player_season {n_ps:,}행, metric {n_psm:,}행")
    print("     진단: " + json.dumps(derive.LAST_BUILD_STATS, ensure_ascii=False), flush=True)

    snap_reports = {}
    for name, as_of in SNAPSHOTS:
        t0 = time.perf_counter()
        sid = derive.create_snapshot(conn, name, as_of)
        rep = derive.build_snapshot(conn, sid)
        snap_reports[name] = rep
        tm.step(f"7. 스냅샷 {name} (as_of {as_of})", time.perf_counter() - t0,
                f"baseline {rep['baseline']:,}, z {rep['z']:,}, label {rep['labels']:,}, built_at {rep['built_at']}")

    t0 = time.perf_counter()
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    tm.step("8. foreign_key_check", time.perf_counter() - t0, f"{len(violations)}행")
    conn.execute("PRAGMA optimize")
    conn.execute("ANALYZE")

    out = ROOT / "data" / "load_report.json" if args.db is None else path.with_name(path.stem + "_load_report.json")
    report["_derive"] = {"stats": dict(derive.LAST_BUILD_STATS), "snapshots": snap_reports,
                         "timings_sec": {k: round(v, 1) for k, v in tm.rows}}
    report["_foreign_key_check"]["violations_final"] = len(violations)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 요약 ===")
    for t in ("competition", "club", "player", "game", "appearance", "game_lineup", "game_event",
              "player_valuation", "transfer", "competition_season_strength", "player_season",
              "player_season_metric", "player_season_z", "cohort_baseline", "world_class_label"):
        print(f"  {t:<30}{conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>12,}")  # 상수 이름
    for r in conn.execute("SELECT snapshot_id, name, as_of_date, built_at FROM snapshot ORDER BY snapshot_id"):
        print(f"  snapshot {r['name']:<8} as_of={r['as_of_date']}  built_at={r['built_at']}")
    print(f"load_report: {out}")
    print(f"총 소요: {time.perf_counter() - t_all:.1f}s, DB 크기 {path.stat().st_size / 1e6:.0f} MB")
    conn.close()
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
