import math
import sqlite3

import pytest

import synth
from scouting.db import transaction
from scouting.services import admin, backtest, notes, players, recommend, users, watchlist
from scouting.services.knn import knn
from scouting.services.users import User


def _mk_users(conn):
    a = users.register(conn, "alice", "pw1234")
    b = users.register(conn, "bob", "pw1234")
    return a, b


# ---------------------------------------------------------------- 사용자
def test_password_hash_format_and_verify(env):
    conn, _ = env
    uid = users.register(conn, "alice", "s3cret!")
    h = conn.execute("SELECT password_hash FROM app_user WHERE user_id=?", (uid,)).fetchone()[0]
    algo, it, salt, digest = h.split("$")
    assert algo == "pbkdf2_sha256" and int(it) == 200_000 and len(salt) == 32 and len(digest) == 64
    assert "s3cret!" not in h
    assert users.authenticate(conn, "alice", "s3cret!") == User(uid, "alice", "scout")
    assert users.authenticate(conn, "alice", "wrong") is None
    assert users.authenticate(conn, "nobody", "s3cret!") is None
    assert not users.verify_password("x", "garbage")


def test_duplicate_username_rejected(env):
    conn, _ = env
    users.register(conn, "alice", "pw1234")
    with pytest.raises(ValueError, match="이미"):
        users.register(conn, "alice", "other-pw")
    assert conn.execute("SELECT COUNT(*) FROM app_user").fetchone()[0] == 1


def test_register_validation(env):
    conn, _ = env
    for bad in [("ab", "pw1234"), ("x" * 33, "pw1234"), ("okname", "123")]:
        with pytest.raises(ValueError):
            users.register(conn, *bad)
    with pytest.raises(ValueError):
        users.register(conn, "okname", "pw1234", role="root")


def test_admin_only_features_rejected(env):
    conn, _ = env
    a, b = _mk_users(conn)
    admin_id = users.register(conn, "boss", "pw1234", role="admin")
    scout = User(a, "alice", "scout")
    boss = User(admin_id, "boss", "admin")
    with pytest.raises(PermissionError):
        users.set_role(conn, scout, b, "admin")
    with pytest.raises(PermissionError):
        users.list_users(conn, scout)
    with pytest.raises(PermissionError):
        admin.create_definition(conn, scout, code="x", name_ko="x", rule_type="peak_value",
                                value_threshold_eur=1, gk_value_threshold_eur=1)
    with pytest.raises(PermissionError):
        admin.update_definition(conn, scout, 1, name_ko="hack")
    with pytest.raises(PermissionError):
        admin.delete_definition(conn, scout, 1)
    with pytest.raises(PermissionError):
        admin.rebuild_snapshot(conn, 1, actor=scout)
    # 객체가 위조되어도 DB의 역할을 본다
    with pytest.raises(PermissionError):
        users.set_role(conn, User(a, "alice", "admin"), b, "admin")
    assert conn.execute("SELECT role FROM app_user WHERE user_id=?", (b,)).fetchone()[0] == "scout"
    users.set_role(conn, boss, b, "admin")
    assert conn.execute("SELECT role FROM app_user WHERE user_id=?", (b,)).fetchone()[0] == "admin"
    users.set_role(conn, boss, b, "scout")
    with pytest.raises(ValueError, match="마지막"):
        users.set_role(conn, boss, admin_id, "scout")


# ------------------------------------------------- 소유권 (노트, 워치리스트)
def test_notes_ownership(env):
    conn, _ = env
    a, b = _mk_users(conn)
    nid = notes.create_note(conn, a, 101, 4, "좋은 수비수")
    assert notes.update_note(conn, b, nid, body="탈취") is False
    assert notes.delete_note(conn, b, nid) is False
    row = conn.execute("SELECT body, rating FROM scouting_note WHERE note_id=?", (nid,)).fetchone()
    assert (row["body"], row["rating"]) == ("좋은 수비수", 4)
    assert notes.list_notes_for_player(conn, b, 101) == []
    assert notes.update_note(conn, a, nid, rating=5) is True
    assert notes.list_notes_for_player(conn, a, 101)[0]["rating"] == 5
    assert notes.update_note(conn, a, 99999, body="x") is False
    assert notes.delete_note(conn, a, nid) is True
    assert notes.list_my_notes(conn, a) == []


def test_note_integrity_errors(env):
    conn, _ = env
    a, _b = _mk_users(conn)
    with pytest.raises(sqlite3.IntegrityError):
        notes.create_note(conn, a, 101, 9, "범위 밖 평점")
    with pytest.raises(sqlite3.IntegrityError):
        notes.create_note(conn, a, 999999, 3, "없는 선수")
    assert not conn.in_transaction


def test_watchlist_ownership(env):
    conn, _ = env
    a, b = _mk_users(conn)
    watchlist.add_to_watchlist(conn, a, 101, "메모A")
    assert watchlist.update_watch_memo(conn, b, 101, "탈취") is False
    assert watchlist.remove_from_watchlist(conn, b, 101) is False
    assert watchlist.list_watchlist(conn, a)[0]["memo"] == "메모A"
    assert watchlist.list_watchlist(conn, b) == []
    with pytest.raises(sqlite3.IntegrityError):  # 중복
        watchlist.add_to_watchlist(conn, a, 101)
    assert watchlist.update_watch_memo(conn, a, 101, "새 메모") is True
    assert watchlist.remove_from_watchlist(conn, a, 101) is True
    assert watchlist.remove_from_watchlist(conn, a, 101) is False


# ------------------------------------------------------------ 선수 조회
def test_search_and_card(env):
    conn, _ = env
    rows = players.search_players(conn, name="cand")
    assert [r["player_id"] for r in rows] == [102, 101, 103]  # 접두 일치 → 최고 시장가치 순
    assert players.search_players(conn, name="100%") == []  # LIKE 와일드카드 이스케이프
    assert {r["player_id"] for r in players.search_players(conn, pos_group="MF")} == {107, 208}
    young = {r["player_id"] for r in players.search_players(conn, max_age=19, limit=100)}
    assert 106 not in young  # 1995년생
    assert players.player_card(conn, 101)["name"] == "Cand One"
    assert players.player_card(conn, 424242) is None
    assert players.search_players(conn, name="'; DROP TABLE player; --") == []


def test_history_and_percentiles(env):
    conn, ids = env
    for pid, v in ((101, 0.9), (102, 0.1), (103, 0.5)):
        synth.add_metric(conn, pid, 2017, "goals_per90", v)
    hist = players.season_history(conn, 101)
    assert hist[0]["season"] == 2017 and hist[0]["m_goals_per90"] == 0.9
    pct = {p["metric_code"]: p for p in players.cohort_percentiles(conn, ids["bt"], 101, 2017)}
    assert pct["goals_per90"]["cohort_n"] == 3
    assert pct["goals_per90"]["percentile"] == pytest.approx(100 * (2 + 0.5) / 3)
    synth.add_metric(conn, 101, 2017, "cards_per90", 0.9)  # higher_is_better = 0
    synth.add_metric(conn, 102, 2017, "cards_per90", 0.1)
    pct = {p["metric_code"]: p for p in players.cohort_percentiles(conn, ids["bt"], 101, 2017)}
    assert pct["cards_per90"]["percentile"] == pytest.approx(100 - 100 * (1 + 0.5) / 2)
    assert players.cohort_percentiles(conn, ids["bt"], 101, 2025) == []  # 스냅샷에 없는 시즌
    synth.add_val(conn, 101, "2018-01-01", 7_000_000)
    assert [v["market_value_eur"] for v in players.valuation_history(conn, 101)] == [5_000_000, 7_000_000]


# --------------------------------------------------------------- 추천
def _expected_dist(a: dict, b: dict) -> float:
    shared = [m for m in a if m in b]
    sw = sum(synth.DF_W[m] for m in shared)
    return math.sqrt(sum(synth.DF_W[m] * (a[m] - b[m]) ** 2 for m in shared) / sw)


def test_knn_matches_hand_computation(env):
    conn, ids = env
    c1 = {"minutes_share": 1.0, "start_rate": 0.0, "onpitch_ga_per90": -1.0}
    by_id = {
        201: c1,
        202: {"minutes_share": 1.5, "start_rate": 0.5, "onpitch_ga_per90": -0.5},
        209: {"minutes_share": 1.5, "start_rate": 0.5, "onpitch_ga_per90": -0.5},
        203: {"minutes_share": 0.0, "start_rate": 0.0, "onpitch_ga_per90": 0.0},
        204: {"minutes_share": 2.0, "start_rate": 1.0},
    }
    # 손으로 계산한 순서: 201(0) < 202 = 209(0.5, id 순) < 203(0.882) < 204(1.0). 205 는 60% 미만, 206/207/208 은 풀 밖.
    hand = sorted(by_id, key=lambda p: (round(_expected_dist(c1, by_id[p]), 12), p))
    assert hand == [201, 202, 209, 203, 204]
    got = knn(conn, "SELECT player_id, age FROM player_season WHERE player_id = :cand_pid AND season = :L",
              snapshot_id=ids["bt"], base_season=2017, pos_group="DF", k=10,
              pool_max_season=2014, def_id=1, params={"cand_pid": 101})[101]
    assert [n["player_id"] for n in got] == hand
    for n in got:
        assert n["distance"] == pytest.approx(_expected_dist(c1, by_id[n["player_id"]]))
    assert [n["is_wc"] for n in got] == [1, 0, 0, 1, 0]  # 201, 203 이 bt 월클


def test_similarity_run_scores_and_evidence(env):
    conn, ids = env
    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                       method="similarity", k=3)
    items = recommend.run_items(conn, rid)
    assert {i["player_id"] for i in items} == {101, 102, 103}  # 104~107 제외
    c1 = next(i for i in items if i["player_id"] == 101)
    ev = recommend.run_evidence(conn, rid, 101)
    assert [e["neighbor_player_id"] for e in ev] == [201, 202, 209]
    d = [0.0, 0.5, 0.5]
    w = [1 / (x + 0.1) for x in d]
    assert c1["score"] == pytest.approx(w[0] / sum(w))
    assert c1["wc_neighbors"] == 1
    assert [i["score"] for i in items] == sorted((i["score"] for i in items), reverse=True)
    assert [i["rank"] for i in items] == [1, 2, 3]


def test_similarity_60pct_weight_sharing_rule(env):
    conn, ids = env
    # 후보 한 명만 두고, 풀 선수의 공유 지표 가중치 비율로 포함 여부 확인
    c = {"minutes_share": 1.0, "start_rate": 0.0, "onpitch_ga_per90": -1.0}  # 총 4.5, 60% = 2.7
    got = knn(conn, "SELECT player_id, age FROM player_season WHERE player_id = :cand_pid AND season = :L",
              snapshot_id=ids["bt"], base_season=2017, pos_group="DF", k=50, pool_max_season=2014,
              def_id=1, params={"cand_pid": 101})[101]
    included = {n["player_id"] for n in got}
    assert 204 in included       # 3.0 / 4.5 = 66.7%
    assert 205 not in included   # 2.0 / 4.5 = 44.4%
    # 205 에 start_rate 를 추가하면 공유 가중치 3.0/4.5 ≥ 60% 라서 포함된다
    synth.add_z(conn, ids["bt"], 205, 2014, "DF", 18, {"start_rate": 0.5})
    got = knn(conn, "SELECT player_id, age FROM player_season WHERE player_id = :cand_pid AND season = :L",
              snapshot_id=ids["bt"], base_season=2017, pos_group="DF", k=50, pool_max_season=2014,
              def_id=1, params={"cand_pid": 101})[101]
    assert 205 in {n["player_id"] for n in got}


def test_pool_lag_filter(env):
    conn, ids = env
    kw = dict(user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF", method="similarity", k=50)
    r3 = recommend.run_recommendation(conn, pool_lag_seasons=3, **kw)
    n3 = {e["neighbor_player_id"] for e in recommend.run_evidence(conn, r3, 101)}
    assert 206 not in n3  # 2015 시즌 = L-2 → lag 3 이면 풀 밖
    r2 = recommend.run_recommendation(conn, pool_lag_seasons=2, **kw)
    assert 206 in {e["neighbor_player_id"] for e in recommend.run_evidence(conn, r2, 101)}
    r0 = recommend.run_recommendation(conn, pool_lag_seasons=0, **kw)
    seasons = {e["neighbor_season"] for e in recommend.run_evidence(conn, r0, 101)}
    assert max(seasons) <= 2017
    # 다른 나이(207), 다른 포지션(208)은 어떤 lag 에서도 풀 밖
    assert not ({207, 208} & {e["neighbor_player_id"] for e in recommend.run_evidence(conn, r0, 101)})


def test_candidates_exclude_existing_world_class(env):
    conn, ids = env
    kw = dict(snapshot_id=ids["bt"], pos_group="DF", max_age=21, min_minutes=900)
    assert recommend.candidate_ids(conn, def_id=1, **kw) == [101, 102, 103]  # 104 는 bt 월클이라 제외
    assert 104 in recommend.candidate_ids(conn, def_id=2, **kw)              # 정의 2 에서는 월클 아님
    assert 105 not in recommend.candidate_ids(conn, def_id=2, **{**kw, "min_minutes": 900})
    assert 105 in recommend.candidate_ids(conn, def_id=2, **{**kw, "min_minutes": 100})
    assert 106 not in recommend.candidate_ids(conn, def_id=2, **kw)          # 나이 초과
    assert 107 not in recommend.candidate_ids(conn, def_id=2, **kw)          # 다른 포지션
    assert recommend.candidate_ids(conn, def_id=2, **{**kw, "max_age": 30}).count(106) == 1


def test_methods_market_value_random_hybrid(env):
    conn, ids = env
    kw = dict(user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF")
    mv = recommend.run_items(conn, recommend.run_recommendation(conn, method="market_value", **kw))
    assert [i["player_id"] for i in mv] == [102, 101, 103]  # 30M(최신 값) > 5M > 없음(0)
    assert mv[-1]["score"] == 0
    r1 = [i["player_id"] for i in recommend.run_items(conn, recommend.run_recommendation(conn, method="random", seed=7, **kw))]
    r2 = [i["player_id"] for i in recommend.run_items(conn, recommend.run_recommendation(conn, method="random", seed=7, **kw))]
    assert r1 == r2 and sorted(r1) == [101, 102, 103]
    hy = recommend.run_items(conn, recommend.run_recommendation(conn, method="hybrid", k=3, **kw))
    assert len(hy) == 3 and all(0 <= i["score"] <= 1 for i in hy)
    hy_run = conn.execute("SELECT MAX(run_id) FROM recommendation_run").fetchone()[0]
    assert recommend.run_evidence(conn, hy_run, hy[0]["player_id"])
    with pytest.raises(ValueError):
        recommend.run_recommendation(conn, method="nope", **kw)
    with pytest.raises(ValueError):
        recommend.run_recommendation(conn, method="random", max_age=99, **kw)


def test_run_rolls_back_on_exception(env, monkeypatch):
    conn, ids = env
    users.register(conn, "alice", "pw1234")

    def boom(*a, **k):
        raise RuntimeError("주입된 실패")

    monkeypatch.setattr(recommend, "_save_evidence", boom)  # run, item 저장 이후에 실패
    with pytest.raises(RuntimeError):
        recommend.run_recommendation(conn, user_id=1, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                     method="similarity", k=3)
    for t in ("recommendation_run", "recommendation_item", "recommendation_evidence"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    assert not conn.in_transaction


def test_item_failure_also_rolls_back_run(env, monkeypatch):
    conn, ids = env
    monkeypatch.setattr(recommend, "_save_items", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                     method="market_value")
    assert conn.execute("SELECT COUNT(*) FROM recommendation_run").fetchone()[0] == 0


def test_backtest_snapshot_has_no_leakage(env):
    """bt 스냅샷 as_of(2018-07-01) 이후 데이터를 바꿔도 bt 추천 결과가 같아야 한다."""
    conn, ids = env

    def snapshot_results():
        out = {}
        for m in recommend.METHODS:
            rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1,
                                               pos_group="DF", method=m, k=5, top_n=10, seed=3)
            ev = [(e["player_id"], e["neighbor_player_id"], e["neighbor_season"], e["distance"])
                  for e in conn.execute("SELECT * FROM recommendation_evidence WHERE run_id=?", (rid,))]
            out[m] = ([(i["rank"], i["player_id"], i["score"], i["wc_neighbors"]) for i in recommend.run_items(conn, rid)],
                      sorted(ev))
        return out

    before = snapshot_results()

    # 미래 시장가치 (as_of 이후 날짜): 103 을 슈퍼스타로, 101 은 폭락
    synth.add_val(conn, 103, "2018-07-01", 200_000_000)   # as_of 당일 = '미만' 조건 밖
    synth.add_val(conn, 103, "2020-01-01", 300_000_000)
    synth.add_val(conn, 101, "2019-01-01", 0)
    # 미래 시즌 데이터: 새 후보 등장, 기존 시즌 행 변경
    synth.add_player(conn, 301, "Future Cand", "1999-01-01")
    for season in (2018, 2019):
        synth.add_ps(conn, 301, season, season - 1999)
        synth.add_ps(conn, 101, season, season - 1999)
    conn.execute("UPDATE player_season SET league_minutes = 0 WHERE season >= 2018")
    synth.add_z(conn, ids["bt"], 301, 2018, "DF", 19, synth.DF_W)  # bt 스냅샷에 섞여 들어온 미래 z
    # outcome 스냅샷 라벨 변경은 bt 추천과 무관
    synth.add_label(conn, ids["cur"], 1, 102, True)
    conn.execute("UPDATE player_season_z SET z = z + 5 WHERE snapshot_id = ? AND season > 2017", (ids["bt"],))

    assert snapshot_results() == before


# ---------------------------------------------------------------- 백테스트
def test_evaluate_run_precision_recall(env):
    conn, ids = env
    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                       method="market_value", top_n=3)
    # market_value 순위: 102, 101, 103 / cur 정답: 101, 103 (후보 중 2명)
    res = {r["k"]: r for r in backtest.evaluate_run(conn, rid, outcome_snapshot_id=ids["cur"], k_values=(1, 2, 3))}
    assert (res[1]["hits"], res[1]["precision"], res[1]["recall"]) == (0, 0.0, 0.0)
    assert (res[2]["hits"], res[2]["precision"], res[2]["recall"]) == (1, 0.5, 0.5)
    assert (res[3]["hits"], res[3]["n_candidates"], res[3]["n_positive"]) == (2, 3, 2)
    assert res[3]["precision"] == pytest.approx(2 / 3) and res[3]["recall"] == 1.0
    stored = conn.execute("SELECT COUNT(*) FROM backtest_result WHERE run_id=?", (rid,)).fetchone()[0]
    assert stored == 3
    backtest.evaluate_run(conn, rid, outcome_snapshot_id=ids["cur"], k_values=(2,))  # 재평가는 덮어쓰기
    assert conn.execute("SELECT COUNT(*) FROM backtest_result WHERE run_id=?", (rid,)).fetchone()[0] == 3
    with pytest.raises(ValueError):
        backtest.evaluate_run(conn, rid, outcome_snapshot_id=ids["cur"], k_values=(4,))  # k > top_n


def test_evaluate_run_zero_positive_recall_is_null(env):
    conn, ids = env
    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=2, pos_group="DF",
                                       method="market_value", top_n=2)  # cur 에 정의 2 정답 없음
    (r,) = backtest.evaluate_run(conn, rid, outcome_snapshot_id=ids["cur"], k_values=(2,))
    assert r["n_positive"] == 0 and r["recall"] is None and r["precision"] == 0.0
    row = conn.execute("SELECT recall_at_k FROM backtest_result WHERE run_id=?", (rid,)).fetchone()
    assert row[0] is None


# ------------------------------------------------------------------ 관리자
def test_definition_update_relabels_and_rolls_back(env, monkeypatch):
    conn, ids = env
    boss = User(users.register(conn, "boss", "pw1234", role="admin"), "boss", "admin")
    calls = []

    class FakeDerive:
        @staticmethod
        def build_labels(c, snapshot_id, def_id=None):
            calls.append((snapshot_id, def_id))
            return 0

    monkeypatch.setattr(admin, "_derive", lambda: FakeDerive)
    assert admin.update_definition(conn, boss, 1, name_ko="바뀐 이름") is True
    assert sorted(calls) == [(ids["bt"], 1), (ids["cur"], 1)]
    assert conn.execute("SELECT name_ko FROM world_class_definition WHERE def_id=1").fetchone()[0] == "바뀐 이름"
    assert admin.update_definition(conn, boss, 999, name_ko="x") is False

    class Broken:
        @staticmethod
        def build_labels(*a, **k):
            raise RuntimeError("라벨 계산 실패")

    monkeypatch.setattr(admin, "_derive", lambda: Broken)
    with pytest.raises(RuntimeError):
        admin.update_definition(conn, boss, 1, name_ko="롤백되어야 함")
    assert conn.execute("SELECT name_ko FROM world_class_definition WHERE def_id=1").fetchone()[0] == "바뀐 이름"

    monkeypatch.setattr(admin, "_derive", lambda: FakeDerive)
    did = admin.create_definition(conn, boss, code="peak_100m", name_ko="1억", rule_type="peak_value",
                                  value_threshold_eur=100_000_000, gk_value_threshold_eur=60_000_000)
    assert (ids["bt"], did) in calls
    assert admin.delete_definition(conn, boss, did) is True
    rid = recommend.run_recommendation(conn, user_id=None, snapshot_id=ids["bt"], def_id=1, pos_group="DF",
                                       method="random")
    with pytest.raises(sqlite3.IntegrityError):  # run 이 참조 중
        admin.delete_definition(conn, boss, 1)
    assert rid


def test_rebuild_snapshot_delegates(env, monkeypatch):
    conn, ids = env
    boss = User(users.register(conn, "boss", "pw1234", role="admin"), "boss", "admin")

    class FakeDerive:
        @staticmethod
        def build_snapshot(c, snapshot_id):
            return {"snapshot_id": snapshot_id}

    monkeypatch.setattr(admin, "_derive", lambda: FakeDerive)
    assert admin.rebuild_snapshot(conn, ids["bt"], actor=boss) == {"snapshot_id": ids["bt"]}
    with pytest.raises(ValueError):
        admin.rebuild_snapshot(conn, 999, actor=boss)


def test_data_status(env):
    conn, ids = env
    st = admin.data_status(conn)
    assert st["tables"]["player"] == 16
    assert [s["name"] for s in st["snapshots"]] == ["bt2018", "current"]
    assert all(s["built_at"] for s in st["snapshots"])


def test_transaction_nesting_with_services(env):
    conn, _ = env
    a, _b = _mk_users(conn)
    with pytest.raises(RuntimeError):
        with transaction(conn):
            notes.create_note(conn, a, 101, 3, "중첩 안")
            raise RuntimeError
    assert notes.list_my_notes(conn, a) == []
