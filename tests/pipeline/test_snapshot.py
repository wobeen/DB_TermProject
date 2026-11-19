"""z-score와 월드클래스 라벨 테스트 (CONTRACT §3.3)."""

from __future__ import annotations

import math

import pytest

from pipeline import derive


def _insert_ps(conn, pid, season, age, pos="DF", club=1, minutes=1800):
    conn.execute(
        "INSERT INTO player_season VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, season, age, pos, club, 20, 20, minutes, 38, 0, 0, 0, 0, 0, 0, 0, 0, 0.0))


def _cohort(b, n=25, age=20, season=2018, outlier=None):
    """DF 코호트 n명. goals_per90(높을수록 좋음)=i*0.1, onpitch_ga_per90(낮을수록 좋음)=i*0.1."""
    vals = {}
    for i in range(n):
        pid = 100 + i
        b.player(pid, dob=f"{season - age}-01-01")
        _insert_ps(b.conn, pid, season, age)
        v = i * 0.1
        if outlier is not None and i == n - 1:
            v = outlier
        vals[pid] = v
        b.conn.execute("INSERT INTO player_season_metric VALUES (?,?,?,?)", (pid, season, "goals_per90", v))
        b.conn.execute("INSERT INTO player_season_metric VALUES (?,?,?,?)", (pid, season, "onpitch_ga_per90", v))
    return vals


def _z(conn, sid, pid, code):
    r = conn.execute("SELECT z FROM player_season_z WHERE snapshot_id=? AND player_id=? AND metric_code=?",
                     (sid, pid, code)).fetchone()
    return None if r is None else r[0]


def test_z_sign_flip_for_lower_is_better(conn, b):
    vals = _cohort(b)
    sid = derive.create_snapshot(conn, "s", "2019-07-01")
    derive.build_snapshot(conn, sid)
    xs = list(vals.values())
    mean = sum(xs) / len(xs)
    std = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))     # 모표준편차
    base = conn.execute("SELECT mean, std, n FROM cohort_baseline WHERE snapshot_id=? AND metric_code='goals_per90'",
                        (sid,)).fetchone()
    assert base["n"] == 25 and base["mean"] == pytest.approx(mean) and base["std"] == pytest.approx(std)
    for pid, v in vals.items():
        z_hi = _z(conn, sid, pid, "goals_per90")            # higher_is_better = 1
        z_lo = _z(conn, sid, pid, "onpitch_ga_per90")       # higher_is_better = 0 → 부호 반전
        assert z_hi == pytest.approx((v - mean) / std)
        assert z_lo == pytest.approx(-(v - mean) / std)
    top = max(vals, key=vals.get)
    assert _z(conn, sid, top, "goals_per90") > 0 > _z(conn, sid, top, "onpitch_ga_per90")


def test_z_clipped_to_plus_minus_4(conn, b):
    vals = _cohort(b, n=30, outlier=1000.0)
    sid = derive.create_snapshot(conn, "s", "2019-07-01")
    derive.build_snapshot(conn, sid)
    out = max(vals, key=vals.get)
    assert _z(conn, sid, out, "goals_per90") == 4.0
    assert _z(conn, sid, out, "onpitch_ga_per90") == -4.0
    zs = [r[0] for r in conn.execute("SELECT z FROM player_season_z WHERE snapshot_id = ?", (sid,))]
    assert all(-4.0 <= z <= 4.0 for z in zs)


def test_z_needs_cohort_n_20_and_positive_std(conn, b):
    _cohort(b, n=19)                                   # n < 20 → z 없음
    sid = derive.create_snapshot(conn, "small", "2019-07-01")
    derive.build_snapshot(conn, sid)
    assert conn.execute("SELECT COUNT(*) FROM player_season_z WHERE snapshot_id=?", (sid,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM cohort_baseline WHERE snapshot_id=? AND metric_code='goals_per90'",
                        (sid,)).fetchone()[0] == 1   # baseline 행 자체는 남는다


def test_z_skips_zero_std_cohort_and_age_outside_16_35(conn, b):
    for i in range(25):                                # 모두 같은 값 → std=0 → z 없음
        pid = 200 + i
        b.player(pid, dob="1998-01-01")
        _insert_ps(conn, pid, 2018, 20)
        conn.execute("INSERT INTO player_season_metric VALUES (?,?,?,?)", (pid, 2018, "goals_per90", 0.3))
    for i in range(25):                                # 나이 15 → baseline 대상 아님
        pid = 300 + i
        b.player(pid, dob="2003-01-01")
        _insert_ps(conn, pid, 2018, 15)
        conn.execute("INSERT INTO player_season_metric VALUES (?,?,?,?)", (pid, 2018, "goals_per90", i * 0.1))
    sid = derive.create_snapshot(conn, "s", "2019-07-01")
    derive.build_snapshot(conn, sid)
    assert conn.execute("SELECT COUNT(*) FROM player_season_z WHERE snapshot_id=?", (sid,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM cohort_baseline WHERE snapshot_id=? AND age=15", (sid,)).fetchone()[0] == 0


def test_create_snapshot_idempotent_and_conflict(conn):
    a = derive.create_snapshot(conn, "x", "2018-07-01")
    assert derive.create_snapshot(conn, "x", "2018-07-01") == a
    with pytest.raises(ValueError):
        derive.create_snapshot(conn, "x", "2019-07-01")


def test_build_snapshot_sets_built_at_and_is_repeatable(conn, b):
    _cohort(b)
    sid = derive.create_snapshot(conn, "s", "2019-07-01")
    assert conn.execute("SELECT built_at FROM snapshot WHERE snapshot_id=?", (sid,)).fetchone()[0] is None
    r1 = derive.build_snapshot(conn, sid)
    r2 = derive.build_snapshot(conn, sid)                 # 지우고 다시 계산: 행 수 동일
    assert r1["z"] == r2["z"] > 0 and r1["baseline"] == r2["baseline"]
    assert conn.execute("SELECT built_at FROM snapshot WHERE snapshot_id=?", (sid,)).fetchone()[0] is not None


# ---------------------------------------------------------------- 라벨
def _val(conn, pid, date, eur):
    conn.execute("INSERT INTO player_valuation (player_id, date, market_value_eur) VALUES (?,?,?)", (pid, date, eur))


def _label(conn, sid, def_id, pid):
    return conn.execute("SELECT is_world_class, achieved_on FROM world_class_label "
                        "WHERE snapshot_id=? AND def_id=? AND player_id=?", (sid, def_id, pid)).fetchone()


def test_peak_value_label_with_gk_threshold_and_achieved_on(conn, b):
    b.player(1, position="Attack")
    b.player(2, position="Defender")
    b.player(3, position="Goalkeeper")
    b.player(4, position="Goalkeeper")
    b.player(5, position="Attack")
    b.player(6, position="Missing")
    _val(conn, 1, "2015-01-01", 20_000_000)
    _val(conn, 1, "2016-01-01", 50_000_000)       # 처음 임계값(5천만) 도달
    _val(conn, 1, "2017-01-01", 70_000_000)
    _val(conn, 2, "2016-01-01", 49_999_999)       # 미달
    _val(conn, 3, "2016-06-01", 30_000_000)       # GK 임계값 3천만 정확히 도달
    _val(conn, 4, "2016-06-01", 29_999_999)       # GK 미달
    _val(conn, 5, "2018-07-01", 90_000_000)       # as_of 날짜 당일 → 미만이 아니므로 제외
    _val(conn, 6, "2016-01-01", 90_000_000)
    sid = derive.create_snapshot(conn, "s", "2018-07-01")
    derive.build_snapshot(conn, sid)
    assert tuple(_label(conn, sid, 1, 1)) == (1, "2016-01-01")
    assert tuple(_label(conn, sid, 1, 2)) == (0, None)
    assert tuple(_label(conn, sid, 1, 3)) == (1, "2016-06-01")
    assert tuple(_label(conn, sid, 1, 4)) == (0, None)
    assert tuple(_label(conn, sid, 1, 5)) == (0, None)
    assert _label(conn, sid, 1, 6) is None                       # pos_group 없는 선수는 행 없음
    # 모든 pos_group 선수 × 모든 정의에 행이 있다
    assert conn.execute("SELECT COUNT(*) FROM world_class_label WHERE snapshot_id=?", (sid,)).fetchone()[0] == 5 * 2


def _big5_games(b, pid, seasons, comp="L1", start_gid=None):
    for s in seasons:
        for k in range(2):
            gid = (start_gid or pid * 1000) + (s - 2000) * 10 + k + (0 if comp == "L1" else 5)
            b.game(gid, season=s, comp=comp, date=f"{s}-09-0{k + 1}")
            b.app(gid, pid, 1, 90)


def test_big5_regular_label_and_achieved_on(conn, b):
    # 정의 2를 작은 숫자로 바꿔 합성 데이터로 검증: 시즌 3개 × 180분 이상 + CL 90분
    conn.execute("UPDATE world_class_definition SET min_seasons=3, min_league_minutes=180, min_cl_minutes=90 "
                 "WHERE def_id=2")
    for pid in (1, 2, 3, 4):
        b.player(pid)
    _big5_games(b, 1, [2015, 2016, 2017])               # X: 3시즌 충족
    _big5_games(b, 1, [2016], comp="CL")                # CL 90×2=180분 (2016)
    _big5_games(b, 2, [2015, 2016, 2017])               # Y: CL 없음
    _big5_games(b, 3, [2015, 2016])                     # Z: 2시즌뿐
    _big5_games(b, 3, [2015], comp="CL")
    _big5_games(b, 4, [2015, 2016, 2018])               # W: 2017 결번 → 세 번째 시즌은 2018
    _big5_games(b, 4, [2015], comp="CL")
    # 시즌 중 NL1(covered, big5 아님)은 big5 시즌으로 안 센다
    _big5_games(b, 3, [2017], comp="NL1", start_gid=3500)
    sid_a = derive.create_snapshot(conn, "a", "2018-07-01")     # 2017 시즌까지 포함
    sid_b = derive.create_snapshot(conn, "b", "2019-07-01")     # 2018 시즌까지 포함
    sid_c = derive.create_snapshot(conn, "c", "2018-06-30")     # 2017 시즌 제외(경계)
    for sid in (sid_a, sid_b, sid_c):
        derive.build_snapshot(conn, sid)
    assert tuple(_label(conn, sid_a, 2, 1)) == (1, "2018-06-30")     # 세 조건 처음 충족 시즌 2017 → 2018-06-30
    assert tuple(_label(conn, sid_a, 2, 2)) == (0, None)
    assert tuple(_label(conn, sid_a, 2, 3)) == (0, None)
    assert tuple(_label(conn, sid_a, 2, 4)) == (0, None)
    assert tuple(_label(conn, sid_b, 2, 1)) == (1, "2018-06-30")     # achieved_on은 스냅샷이 달라도 그대로
    assert tuple(_label(conn, sid_b, 2, 4)) == (1, "2019-06-30")
    assert tuple(_label(conn, sid_c, 2, 1)) == (0, None)             # (2017+1)-06-30 < as_of 가 거짓


def test_build_labels_recomputes_one_definition(conn, b):
    b.player(1, position="Attack")
    _val(conn, 1, "2016-01-01", 40_000_000)
    sid = derive.create_snapshot(conn, "s", "2018-07-01")
    derive.build_snapshot(conn, sid)
    assert _label(conn, sid, 1, 1)["is_world_class"] == 0
    conn.execute("UPDATE world_class_definition SET value_threshold_eur = 40000000 WHERE def_id = 1")
    assert derive.build_labels(conn, sid, def_id=1) == 1
    assert tuple(_label(conn, sid, 1, 1)) == (1, "2016-01-01")
    assert _label(conn, sid, 2, 1) is not None                       # 다른 정의 행은 그대로
