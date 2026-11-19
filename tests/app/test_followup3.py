"""Follow-up 3 (교차 리뷰 반영): M1~M3, m1, m2, m5, R-36(ALL/SOME)."""

import bisect
import math
import random
import sqlite3
import subprocess
import sys

import pytest

import synth
from scouting.cli import main as cli_main
from scouting.db import connect
from scouting.services import admin, backtest, players, recommend, users
from scouting.services.users import User
from test_cli import ROOT, inject


def login(name="scout1"):
    return ["1", name, "pw1234"]


@pytest.fixture()
def world(db_path):
    path, ids = db_path
    conn = connect(path)
    users.register(conn, "scout1", "pw1234")
    users.register(conn, "boss", "pw1234", role="admin")
    conn.close()
    return path, ids


# ------------------------------------------------------------------ M1: --db 오류
def _main(path):
    out: list[str] = []
    code = cli_main.main(["--db", str(path)], input_fn=lambda p="": "0", print_fn=lambda *a: out.append(" ".join(map(str, a))))
    return code, "\n".join(out)


def test_db_error_missing_parent_dir(tmp_path):
    code, out = _main(tmp_path / "no" / "such" / "x.sqlite")
    assert code == 1 and "상위 폴더가 없습니다" in out


def test_db_error_directory(tmp_path):
    code, out = _main(tmp_path)
    assert code == 1 and "디렉터리" in out
    p = subprocess.run([sys.executable, "-m", "scouting", "--db", str(tmp_path)], input="0\n",
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=60)
    assert p.returncode == 1 and "Traceback" not in p.stderr + p.stdout and "디렉터리" in p.stdout


def test_db_error_corrupt_file(tmp_path):
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"this is definitely not a sqlite database " * 200)
    code, out = _main(bad)
    assert code == 1 and "손상되었거나 SQLite 파일이 아닙니다" in out


def test_db_error_locked(db_path):
    path, _ = db_path
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        code, out = _main(path)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert code == 1 and "잠겨 있습니다" in out and "Traceback" not in out


# ------------------------------------------------------------------ M2: rebuild actor 필수
def test_rebuild_snapshot_requires_admin_actor(world):
    path, ids = world
    conn = connect(path)
    scout = User(1, "scout1", "scout")
    with pytest.raises(TypeError):
        admin.rebuild_snapshot(conn, ids["bt"])            # actor 생략 불가
    with pytest.raises(PermissionError):
        admin.rebuild_snapshot(conn, ids["bt"], actor=scout)
    with pytest.raises(PermissionError):
        admin.rebuild_snapshot(conn, ids["bt"], actor=None)
    conn.close()


# ------------------------------------------------------------------ M3: 기대값 비교
def _brute_neighbors(conn, snap, cand, L, lag, k, pos="DF"):
    w = {r[0]: r[1] for r in conn.execute("SELECT metric_code, weight FROM metric_weight WHERE pos_group=?", (pos,))}
    vec = {r[0]: r[1] for r in conn.execute(
        "SELECT metric_code, z FROM player_season_z WHERE snapshot_id=? AND player_id=? AND season=?", (snap, cand, L))}
    vec = {m: z for m, z in vec.items() if m in w}
    age = conn.execute("SELECT age FROM player_season WHERE player_id=? AND season=?", (cand, L)).fetchone()[0]
    tw = sum(w[m] for m in vec)
    pool: dict = {}
    for r in conn.execute("SELECT player_id, season, metric_code, z FROM player_season_z "
                          "WHERE snapshot_id=? AND pos_group=? AND age=? AND season<=? AND player_id<>?",
                          (snap, pos, age, L - lag, cand)):
        pool.setdefault((r[0], r[1]), {})[r[2]] = r[3]
    out = []
    for (pid, season), z in pool.items():
        shared = [m for m in vec if m in z]
        sw = sum(w[m] for m in shared)
        if sw * 10 < tw * 6 or not shared:
            continue
        d = math.sqrt(sum(w[m] * (vec[m] - z[m]) ** 2 for m in shared) / sw)
        out.append((d, pid, season))
    out.sort()
    return out[:k]


def _sim_score(conn, snap, def_id, nb):
    wc = {r[0] for r in conn.execute("SELECT player_id FROM world_class_label WHERE snapshot_id=? AND def_id=? "
                                     "AND is_world_class=1", (snap, def_id))}
    num = sum((1 / (d + 0.1)) for d, pid, _ in nb if pid in wc)
    return num / sum(1 / (d + 0.1) for d, _, _ in nb)


def _pr(vals: dict):
    n = len(vals)
    if n <= 1:
        return {k: 0.0 for k in vals}
    s = sorted(vals.values())
    return {k: bisect.bisect_left(s, v) / (n - 1) for k, v in vals.items()}


def test_hybrid_expected_scores_with_missing_value_and_no_neighbors(db_path):
    path, ids = db_path
    conn = connect(path)
    snap = ids["bt"]
    # 108: 이웃이 없는 후보 (풀과 공유하는 지표가 없음), 가치도 없음
    synth.add_player(conn, 108, "No Neighbors", "1999-01-01"); synth.add_ps(conn, 108, 2017, 18)
    synth.add_z(conn, snap, 108, 2017, "DF", 18, {"cards_per90": 0.1}); synth.add_label(conn, snap, 1, 108, False)
    cands = recommend.candidate_ids(conn, snapshot_id=snap, def_id=1, pos_group="DF", max_age=21, min_minutes=900)
    assert cands == [101, 102, 103, 108]

    nb = {c: _brute_neighbors(conn, snap, c, 2017, 3, 25) for c in cands}
    assert nb[108] == [] and all(nb[c] for c in (101, 102, 103))
    sim = {c: _sim_score(conn, snap, 1, nb[c]) for c in cands if nb[c]}
    vals = {101: 5_000_000.0, 102: 30_000_000.0}          # 103, 108 은 시장가치 없음
    prs, prv = _pr(sim), _pr(vals)
    expected = {c: 0.5 * prs.get(c, 0.0) + 0.5 * prv.get(c, 0.0) for c in cands}

    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=snap, def_id=1, pos_group="DF",
                                       method="hybrid", top_n=10)
    items = {i["player_id"]: i for i in recommend.run_items(conn, rid)}
    assert set(items) == set(cands)
    for c in cands:
        assert items[c]["score"] == pytest.approx(expected[c]), c
    assert expected[108] == 0.0 and items[108]["score"] == 0.0 and items[108]["wc_neighbors"] == 0
    assert recommend.run_evidence(conn, rid, 108) == []
    # similarity 방식에서는 이웃 없는 후보가 제외된다
    rid2 = recommend.run_recommendation(conn, user_id=None, snapshot_id=snap, def_id=1, pos_group="DF",
                                        method="similarity", top_n=10)
    assert {i["player_id"] for i in recommend.run_items(conn, rid2)} == {101, 102, 103}
    for c in (101, 102, 103):
        assert [round(e["distance"], 9) for e in recommend.run_evidence(conn, rid, c)] == \
               [round(d, 9) for d, _, _ in nb[c]]
    conn.close()


@pytest.mark.parametrize("seed", [0, 7, 42, 12345])
def test_random_matches_sorted_shuffle(env, seed):
    conn, ids = env
    expected = sorted([101, 102, 103])
    random.Random(seed).shuffle(expected)
    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                       method="random", seed=seed)
    assert [i["player_id"] for i in recommend.run_items(conn, rid)] == expected


def test_top_n_truncation(env):
    conn, ids = env
    for method in ("market_value", "similarity", "hybrid", "random"):
        rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                           method=method, top_n=2, k=3)
        items = recommend.run_items(conn, rid)
        assert [i["rank"] for i in items] == [1, 2], method
        if method in ("similarity", "hybrid"):
            ev_players = {r[0] for r in conn.execute("SELECT player_id FROM recommendation_evidence WHERE run_id=?", (rid,))}
            assert ev_players == {i["player_id"] for i in items}   # 절단된 항목의 증거는 저장되지 않는다


def test_market_value_ties_break_by_player_id(env):
    conn, ids = env
    synth.add_val(conn, 103, "2017-06-01", 5_000_000)      # 101 과 같은 값
    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                       method="market_value")
    items = recommend.run_items(conn, rid)
    assert [i["player_id"] for i in items] == [102, 101, 103]
    assert items[1]["score"] == items[2]["score"] == 5_000_000


# ------------------------------------------------------------------ m1: 정수 범위
def test_integer_inputs_bounded(world):
    path, _ = world
    code, out = inject(path, [*login(), "7", "4", "0", "9223372036854775808", "-3", "1", "0", "0", "0"])
    assert out.count("범위(1~9223372036854775807)") == 3
    assert "권한 없음 또는 없음" in out
    code, out = inject(path, [*login(), "2", "0", "9223372036854775808", "99999999999999999999", "", "0", "0"])
    assert out.count("ID 는 1~9223372036854775807 범위여야 합니다.") == 3
    assert "Traceback" not in out and "종료합니다" in out
    # min_minutes 같은 0 허용 항목은 명시한 하한(0)을 따른다
    code, out = inject(path, [*login(), "4", "1", "1", "2", "2", "n", "", "0", "", "", "", "", "0", "0"])
    assert "추천 완료" in out


# ------------------------------------------------------------------ m2: outcome 시점 검증
def test_evaluate_run_rejects_non_later_outcome(env):
    conn, ids = env
    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                       method="market_value")
    with pytest.raises(ValueError, match="나중이어야"):
        backtest.evaluate_run(conn, rid, outcome_snapshot_id=ids["bt"], k_values=(2,))
    rid_cur = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["cur"], def_id=1, pos_group="DF",
                                           method="market_value")
    with pytest.raises(ValueError, match="나중이어야"):
        backtest.evaluate_run(conn, rid_cur, outcome_snapshot_id=ids["bt"], k_values=(2,))  # 더 이른 outcome
    assert conn.execute("SELECT COUNT(*) FROM backtest_result").fetchone()[0] == 0


def test_cli_backtest_same_snapshot_message(world):
    path, ids = world
    code, out = inject(path, [*login("boss"), "4", "1", "1", "2", "2", "y",
                              "12", "1", "1", "0", "0"])   # outcome = 같은 스냅샷(1번)
    assert "나중이어야 합니다" in out and "종료합니다" in out and "Traceback" not in out


# ------------------------------------------------------------------ m5: 위치 인자
def test_similar_players_positional_def_id(env):
    conn, ids = env
    res = players.similar_players(conn, ids["bt"], 101, 2017, 3, 1)
    assert [r["player_id"] for r in res] == [201, 202, 209]
    assert [r["is_wc"] for r in res] == [1, 0, 0]
    assert players.similar_players(conn, ids["bt"], 101, 2017, 3)[0]["is_wc"] == 0


# ------------------------------------------------------------------ R-36: ALL / SOME
def _breakout_data(conn, ids):
    bt = ids["bt"]
    for pid, v in ((101, 0.7), (102, 0.4), (103, 0.2)):
        synth.add_metric(conn, pid, 2017, "minutes_share", v)
    for pid, season, v in ((201, 2014, 0.3), (203, 2014, 0.6), (104, 2017, 0.5), (207, 2014, 0.01)):
        synth.add_metric(conn, pid, season, "minutes_share", v)
    synth.add_label(conn, bt, 1, 207, True)                 # 19세 월클 (18세 비교 집합에는 들어가면 안 됨)
    # 월클이 없는 나이(17세)의 후보: > ALL 이 공허하게 참이 되면 안 된다
    synth.add_player(conn, 110, "Age Seventeen", "2000-06-01"); synth.add_ps(conn, 110, 2017, 17)
    synth.add_z(conn, bt, 110, 2017, "DF", 17, synth.DF_W)
    synth.add_metric(conn, 110, 2017, "minutes_share", 0.99)


def _set_for(conn, snap, def_id, pos, age, metric="minutes_share"):
    return [r[0] for r in conn.execute(
        """SELECT m.value FROM v_player_season_asof ps
           JOIN world_class_label l ON l.snapshot_id=ps.snapshot_id AND l.def_id=? AND l.player_id=ps.player_id
                AND l.is_world_class=1
           JOIN player_season_metric m ON m.player_id=ps.player_id AND m.season=ps.season AND m.metric_code=?
           WHERE ps.snapshot_id=? AND ps.pos_group=? AND ps.age=?""", (def_id, metric, snap, pos, age))]


def test_breakout_all_some_equal_max_min_equivalents(env):
    conn, ids = env
    _breakout_data(conn, ids)
    bt = ids["bt"]
    kw = dict(snapshot_id=bt, def_id=1, pos_group="DF", metric_code="minutes_share")
    cands = {r[0]: r[1] for r in conn.execute(
        "SELECT cv.player_id, m.value FROM player_season_metric m JOIN player_season cv ON cv.player_id=m.player_id "
        "AND cv.season=m.season WHERE m.season=2017 AND m.metric_code='minutes_share' AND m.player_id IN "
        "(101,102,103,110)")}
    assert _set_for(conn, bt, 1, "DF", 18) and sorted(_set_for(conn, bt, 1, "DF", 18)) == [0.3, 0.5, 0.6]
    exp_all, exp_some = [], []
    for pid, x in cands.items():
        age = conn.execute("SELECT age FROM player_season WHERE player_id=? AND season=2017", (pid,)).fetchone()[0]
        s = _set_for(conn, bt, 1, "DF", age)
        if not s:
            continue                                # S 가 비면 제외
        if x > max(s):                              # x > ALL(S) == x > MAX(S)
            exp_all.append(pid)
        if x > min(s):                              # x > SOME(S) == x > MIN(S)
            exp_some.append(pid)
    assert sorted(exp_all) == [101] and sorted(exp_some) == [101, 102]   # 손계산과도 일치
    got_all = recommend.breakout_prospects(conn, mode="all", **kw)
    got_some = recommend.breakout_prospects(conn, mode="some", **kw)
    assert sorted(r["player_id"] for r in got_all) == sorted(exp_all)
    assert sorted(r["player_id"] for r in got_some) == sorted(exp_some)
    assert 110 not in {r["player_id"] for r in got_all + got_some}      # 비교 월클 0명인 나이는 제외
    top = got_some[0]
    assert (top["player_id"], top["n_wc"], top["wc_max"], top["wc_min"]) == (101, 3, 0.6, 0.3)
    assert [r["player_id"] for r in got_some] == [101, 102]              # 값 내림차순


def test_breakout_equal_value_is_not_strictly_greater(env):
    conn, ids = env
    _breakout_data(conn, ids)
    synth.add_metric(conn, 101, 2017, "minutes_share", 0.6)   # 월클 최댓값과 같음 → ALL 불통과, SOME 통과
    kw = dict(snapshot_id=ids["bt"], def_id=1, pos_group="DF")
    assert 101 not in {r["player_id"] for r in recommend.breakout_prospects(conn, mode="all", **kw)}
    assert 101 in {r["player_id"] for r in recommend.breakout_prospects(conn, mode="some", **kw)}


def test_breakout_empty_comparison_set(env):
    conn, ids = env
    _breakout_data(conn, ids)
    kw = dict(snapshot_id=ids["bt"], def_id=2, pos_group="DF", metric_code="minutes_share")  # 정의 2: bt 월클 0명
    assert recommend.breakout_wc_count(conn, **kw) == 0
    for mode in ("all", "some"):
        assert recommend.breakout_prospects(conn, mode=mode, **kw) == []
    with pytest.raises(ValueError):
        recommend.breakout_prospects(conn, mode="any", **kw)
    with pytest.raises(ValueError):
        recommend.breakout_prospects(conn, mode="all", **{**kw, "metric_code": "nope"})


def test_breakout_cli_menu_and_empty_reason(world):
    path, ids = world
    conn = connect(path)
    _breakout_data(conn, ids)
    metrics = recommend.list_metrics(conn)
    idx = [m["metric_code"] for m in metrics].index("minutes_share") + 1
    conn.close()
    code, out = inject(path, [*login(), "8", "1", "1", "2", str(idx), "2", "", "0", "0"])  # DF, some
    assert "기준 돌파 유망주" in out and "비교 월클 수" in out and "월클 최댓값" in out
    assert "Cand One" in out and "Cand Two" in out and "Cand Three" not in out
    code, out = inject(path, [*login(), "8", "1", "2", "2", str(idx), "1", "", "0", "0"])  # 정의 2: 월클 없음
    assert "표시할 데이터가 없습니다." in out and "비교할 수 없습니다" in out
    # 스카우트도 8번을 쓸 수 있고, 관리자 전용 메뉴는 9번부터
    code, out = inject(path, [*login(), "9", "0", "0"])
    assert "잘못된 선택입니다" in out and "데이터 현황" not in out
    code, out = inject(path, [*login("boss"), "9", "0", "0"])
    assert "행 수" in out
