"""cProfile 2종: similarity 추천 1회(P), Q3 원천 경로 1회. 상위 25개 함수를 저장한다."""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_queries as B  # noqa: E402
from scouting.db import connect  # noqa: E402
from scouting.services.recommend import run_recommendation  # noqa: E402

OUT = B.RESULTS


def _profile(fn, path: Path, title: str) -> dict:
    pr = cProfile.Profile()
    pr.enable()
    fn()
    pr.disable()
    buf = io.StringIO()
    st = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    st.print_stats(25)
    total = st.total_tt
    path.write_text(f"# {title}\n# total_tt={total:.3f}s (정렬: cumulative, 상위 25)\n{buf.getvalue()}\n"
                    f"\n# ---- tottime 기준 ----\n" + _by_tottime(pr), encoding="utf-8")
    tops = sorted(st.stats.items(), key=lambda kv: kv[1][2], reverse=True)[:6]
    return {"total_s": total, "top": [
        {"func": f"{Path(k[0]).name}:{k[2]}" if k[0] != "~" else k[2], "calls": v[1], "tottime": v[2], "cumtime": v[3]}
        for k, v in tops]}


def _by_tottime(pr) -> str:
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("tottime").print_stats(25)
    return buf.getvalue()


def run(sample: list[dict], log) -> dict:
    s = sample[0]
    # P: similarity 추천 1회. 메인 DB 오염을 피하려면 복사본을 써야 하지만 recommendation_* 만 쓰므로
    # 작업 복사본(bench_work)에서 실행한다.
    from make_variants import WORK_PATH
    conn = connect(WORK_PATH)
    log("[PROFILE] similarity 추천 1회 (P, FW, current, top_n=20)")
    prof_sim = _profile(lambda: run_recommendation(conn, user_id=None, snapshot_id=B.SNAP_ID, def_id=B.BENCH_DEF,
                                                pos_group="FW", method="similarity", top_n=20),
                     OUT / "profile_similarity_P.txt", "similarity 추천 1회 (P, FW, current)")
    raw = connect(B.B1_PATH)
    as_of = B.as_of_of(raw)
    log("[PROFILE] Q3 원천 경로(B1) 1회")
    prof_q3 = _profile(lambda: B.run_q("Q3", "B1", raw, s, as_of), OUT / "profile_q3_raw_B1.txt",
                    f"Q3 원천 경로 B1 1회 (player {s['player_id']})")
    conn.close()
    raw.close()
    return {"similarity_P": prof_sim, "q3_raw_B1": prof_q3}
