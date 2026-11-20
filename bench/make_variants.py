"""B1(보조 인덱스 없음) DB 생성: 메인 DB 복사본에서 ix_ 인덱스를 모두 DROP 후 VACUUM.
또한 갱신 실험용 작업 복사본 data/bench_work.sqlite 를 만든다."""

from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scouting.db import DEFAULT_DB_PATH  # noqa: E402

B1_PATH = ROOT / "data" / "bench_b1.sqlite"
WORK_PATH = ROOT / "data" / "bench_work.sqlite"


def _copy(src: Path, dst: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(dst) + suffix).unlink(missing_ok=True)
    shutil.copyfile(src, dst)


def make_b1(src: Path = DEFAULT_DB_PATH, dst: Path = B1_PATH, force: bool = False) -> dict:
    if dst.exists() and not force:
        conn = sqlite3.connect(dst)
        n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND substr(name, 1, 3) = 'ix_'").fetchone()[0]
        conn.close()
        if n == 0:
            return {"path": str(dst), "dropped": 0, "reused": True}
    t0 = time.perf_counter()
    _copy(src, dst)
    conn = sqlite3.connect(dst, isolation_level=None)
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND substr(name, 1, 3) = 'ix_'")]
    for n in names:
        conn.execute(f'DROP INDEX "{n}"')  # 이름은 sqlite_master 에서 온 값
    conn.execute("VACUUM")
    conn.close()
    return {"path": str(dst), "dropped": len(names), "reused": False, "seconds": time.perf_counter() - t0}


def make_work(src: Path = DEFAULT_DB_PATH, dst: Path = WORK_PATH) -> Path:
    _copy(src, dst)
    return dst


if __name__ == "__main__":
    print(make_b1(force="--force" in sys.argv))
