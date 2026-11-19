"""player_season 합성 경기 단위 테스트 (CONTRACT §3.2)."""

from __future__ import annotations

from pipeline import derive


def _build(conn, seasons=(2018,)):
    return derive.build_player_season(conn, seasons=list(seasons))


def test_intervals_start_sub_in_sub_out_red(conn, b):
    """선발 / 교체 인 / 교체 아웃 / 퇴장 출전 구간 (in, out]."""
    b.game(1, home=1, away=2, hg=3, ag=2)
    for pid in (1, 2, 3, 4):
        b.player(pid)
    b.app(1, 1, 1, 90)   # 선발, 끝까지
    b.app(1, 2, 1, 60)   # 선발, 60분 교체 아웃
    b.app(1, 3, 1, 30)   # 60분 교체 인
    b.app(1, 4, 1, 30)   # 선발, 30분 퇴장
    for pid, st in ((1, 1), (2, 1), (3, 0), (4, 1)):
        b.lineup(1, pid, 1, st)
    b.sub(1, 60, 1, out_pid=2, in_pid=3)
    b.red(1, 30, 1, 4)
    b.goal(1, 20, 1)   # 홈 득점
    b.goal(1, 40, 2)   # 원정 득점
    b.goal(1, 60, 1)   # 경계: 아웃 선수(m ≤ out)는 포함, 인 선수(in < m)는 제외
    b.goal(1, 75, 2)
    _build(b.conn)
    p1, p2, p3, p4 = (b.ps(i) for i in (1, 2, 3, 4))
    assert (p1["onpitch_gf"], p1["onpitch_ga"]) == (2, 2)
    assert (p2["onpitch_gf"], p2["onpitch_ga"]) == (2, 1)      # (0,60]: 20, 60 / 40
    assert (p3["onpitch_gf"], p3["onpitch_ga"]) == (0, 1)      # (60,90): 75 만
    assert (p4["onpitch_gf"], p4["onpitch_ga"]) == (1, 0)      # (0,30]: 20 만
    assert [p["league_starts"] for p in (p1, p2, p3, p4)] == [1, 1, 0, 1]
    assert p1["league_minutes"] == 90 and p3["league_minutes"] == 30


def test_minute_minus_one_only_counts_for_full_game_starter(conn, b):
    b.game(1, home=1, away=2, hg=1, ag=1)
    for pid in (1, 2, 3):
        b.player(pid)
    b.app(1, 1, 1, 90)
    b.app(1, 2, 1, 70)
    b.app(1, 3, 1, 20)
    for pid, st in ((1, 1), (2, 1), (3, 0)):
        b.lineup(1, pid, 1, st)
    b.sub(1, 70, 1, out_pid=2, in_pid=3)
    b.goal(1, -1, 1)
    b.goal(1, -1, 2)
    _build(b.conn)
    assert (b.ps(1)["onpitch_gf"], b.ps(1)["onpitch_ga"]) == (1, 1)     # in=0, out=∞ → 센다
    assert (b.ps(2)["onpitch_gf"], b.ps(2)["onpitch_ga"]) == (0, 0)     # 교체 아웃 → 안 센다
    assert (b.ps(3)["onpitch_gf"], b.ps(3)["onpitch_ga"]) == (0, 0)     # 교체 인 → 안 센다


def test_own_goal_is_attributed_to_credited_club(conn, b):
    """game_event.club_id는 득점이 인정된 구단: 자책골은 가해 선수의 팀 실점, 상대 팀 득점."""
    b.game(1, home=1, away=2, hg=0, ag=1)
    b.player(1)  # 구단 1 선수, 자책골 가해자
    b.player(2)  # 구단 2 선수
    b.app(1, 1, 1, 90)
    b.app(1, 2, 2, 90)
    b.lineup(1, 1, 1, 1)
    b.lineup(1, 2, 2, 1)
    b.goal(1, 30, club=2, player=1, desc="Own goal")
    _build(b.conn)
    assert (b.ps(1)["onpitch_gf"], b.ps(1)["onpitch_ga"]) == (0, 1)
    assert (b.ps(2)["onpitch_gf"], b.ps(2)["onpitch_ga"]) == (1, 0)


def test_clean_sheet_rules(conn, b):
    """무실점 선발이고 끝까지 뛰고(out=∞) 출전 중 실점 0."""
    b.game(1, home=1, away=2, hg=1, ag=0)
    for pid in (1, 2, 3, 4):
        b.player(pid)
    b.app(1, 1, 1, 90)   # 풀타임 선발 → clean sheet
    b.app(1, 2, 1, 70)   # 교체 아웃 → 아님
    b.app(1, 3, 1, 20)   # 교체 인 → 아님(선발 아님)
    b.app(1, 4, 1, 90)   # 풀타임 선발인데 다른 경기에서 실점
    for pid, st in ((1, 1), (2, 1), (3, 0), (4, 1)):
        b.lineup(1, pid, 1, st)
    b.sub(1, 70, 1, out_pid=2, in_pid=3)
    b.goal(1, 10, 1)
    # 경기 2: 선수 4가 실점하는 경기, 선수 1은 퇴장으로 끝까지 못 뜀
    b.game(2, home=1, away=3, hg=0, ag=2, season=2018)
    b.app(2, 4, 1, 90)
    b.app(2, 1, 1, 40)
    b.lineup(2, 4, 1, 1)
    b.lineup(2, 1, 1, 1)
    b.red(2, 40, 1, 1)
    b.goal(2, 60, 3)
    _build(b.conn)
    assert b.ps(1)["clean_sheets"] == 1 and b.ps(1)["league_starts"] == 2
    assert b.ps(2)["clean_sheets"] == 0
    assert b.ps(3)["clean_sheets"] == 0 and b.ps(3)["league_starts"] == 0
    assert b.ps(4)["clean_sheets"] == 1 and b.ps(4)["league_starts"] == 2
    # 퇴장 선수는 실점 전에 나갔어도 out≠∞ 이므로 clean sheet 아님: 경기 2 포함 시 1(경기 1만)
    assert b.ps(1)["onpitch_ga"] == 0


def test_no_lineup_game_starter_fallback(conn, b):
    """라인업 행이 없으면 '그 경기에 교체 인 이벤트가 없음'을 선발로 본다."""
    b.game(1, home=1, away=2, hg=0, ag=1, season=2018)
    for pid in (1, 2, 3):
        b.player(pid)
    b.app(1, 1, 1, 90)   # 라인업 없음, 교체 인 이벤트 없음 → 선발
    b.app(1, 2, 1, 60)   # 라인업 없음, 60분 교체 아웃 → 선발
    b.app(1, 3, 1, 30)   # 라인업 없음, 교체 인 이벤트 있음 → 선발 아님
    b.sub(1, 60, 1, out_pid=2, in_pid=3)
    b.goal(1, 80, 2)     # 80분 실점: 3번만 출전 중
    _build(b.conn)
    assert b.ps(1)["league_starts"] == 1 and b.ps(1)["clean_sheets"] == 0
    assert b.ps(2)["league_starts"] == 1 and b.ps(2)["clean_sheets"] == 0   # out≠∞
    assert b.ps(3)["league_starts"] == 0
    assert (b.ps(3)["onpitch_gf"], b.ps(3)["onpitch_ga"]) == (0, 1)
    assert (b.ps(2)["onpitch_gf"], b.ps(2)["onpitch_ga"]) == (0, 0)
    # 라인업이 있으면 라인업의 is_starter가 우선
    b.game(2, home=1, away=2, hg=0, ag=0, season=2018)
    b.app(2, 1, 1, 90)
    b.lineup(2, 1, 1, 0)   # 라인업상 교체 선수(교체 이벤트는 없음)
    _build(b.conn)
    assert b.ps(1)["league_starts"] == 1  # 경기 2는 선발 아님


def test_club_not_in_game_is_excluded_from_onpitch_and_counted(conn, b):
    b.game(1, home=1, away=2, hg=1, ag=0)
    b.player(1)
    b.app(1, 1, 5, 90)    # 구단 5는 이 경기의 홈/원정이 아님
    b.lineup(1, 1, 5, 1)
    b.goal(1, 10, 1)
    _build(b.conn)
    p = b.ps(1)
    assert p["main_club_id"] == 5 and p["onpitch_gf"] == 0 and p["onpitch_ga"] == 0 and p["clean_sheets"] == 0
    assert derive.LAST_BUILD_STATS["excluded_onpitch_club_not_in_game"] == 1


def test_eligibility_age_and_missing_filters(conn, b):
    b.game(1)
    b.player(1, dob="2000-01-01")                       # 18세
    b.player(2, dob=None)                               # 생년월일 NULL
    b.player(3, position="Missing")                     # position Missing
    b.player(4, dob="2010-01-01")                       # 8세 → 14~45 밖
    b.player(5, dob="1970-01-01")                       # 48세 → 밖
    b.player(6, dob="2000-01-01")                       # 0분(출전 구간 1분 미만)
    for pid in (1, 2, 3, 4, 5):
        b.app(1, pid, 1, 90)
    b.app(1, 6, 1, 0)
    n = _build(b.conn)
    assert n == 1 and b.ps(1)["age"] == 18 and b.ps(1)["pos_group"] == "DF"


def test_non_covered_competitions_do_not_count_and_uefa_minutes(conn, b):
    b.game(1, comp="L1")
    b.game(2, comp="CUP", date="2018-10-01")
    b.game(3, comp="CL", date="2018-10-02")
    b.player(1)
    b.app(1, 1, 1, 90, goals=1)
    b.app(2, 1, 1, 90, goals=3)     # 컵: 제외
    b.app(3, 1, 1, 45, goals=2)     # CL: 리그 합계에서 제외, uefa_minutes 에만
    _build(b.conn)
    p = b.ps(1)
    assert p["league_minutes"] == 90 and p["goals"] == 1 and p["uefa_minutes"] == 45


def test_main_club_and_team_games(conn, b):
    """주 소속 구단 = 리그 출전 시간 최대. team_league_games = 그 구단의 해당 시즌 리그 경기 수."""
    b.game(1, home=1, away=3)
    b.game(2, home=2, away=3, date="2018-09-08")
    b.game(3, home=2, away=1, date="2018-09-15")
    b.player(1)
    b.app(1, 1, 1, 30)
    b.app(2, 1, 2, 60)
    b.app(3, 1, 2, 60)
    _build(b.conn)
    p = b.ps(1)
    assert p["main_club_id"] == 2 and p["team_league_games"] == 2 and p["league_minutes"] == 150


def test_metrics_formulas_and_min_minutes(conn, b):
    b.game(1, home=1, away=2, hg=1, ag=0)
    b.player(1)
    b.player(2)
    b.app(1, 1, 1, 90, goals=1, assists=1, yc=1)
    b.app(1, 2, 1, 90)
    b.lineup(1, 1, 1, 1)
    b.lineup(1, 2, 1, 1)
    # 선수 1: 450분 이상 필요한 지표가 나오도록 경기 추가
    for g in range(2, 7):
        b.game(g, home=1, away=2, hg=0, ag=0, date=f"2018-10-{g:02d}")
        b.app(g, 1, 1, 90)
        b.lineup(g, 1, 1, 1)
    _build(b.conn)
    m = {r["metric_code"]: r["value"] for r in
         b.conn.execute("SELECT * FROM player_season_metric WHERE player_id = 1 AND season = 2018")}
    assert m["minutes_share"] == 1.0                       # 540/(6*90)
    assert m["start_rate"] == 1.0
    assert abs(m["goals_per90"] - 1 * 90 / 540) < 1e-12
    assert abs(m["cards_per90"] - 90 / 540) < 1e-12
    assert m["clean_sheet_rate"] == 1.0                    # 6경기 모두 선발·무실점
    assert m["comp_strength"] == 0.0 and m["uefa_minutes"] == 0.0
    # 선수 2: 90분 < 450 → per90 지표는 행 없음, minutes_share 등은 있음
    m2 = {r["metric_code"] for r in
          b.conn.execute("SELECT metric_code FROM player_season_metric WHERE player_id = 2")}
    assert "goals_per90" not in m2 and "clean_sheet_rate" not in m2 and "minutes_share" in m2


def test_asof_boundary_season_included_only_after_june_30(conn, b):
    """시즌 s는 (s+1)-06-30 < as_of 일 때만 포함."""
    b.game(1, season=2018)
    b.player(1)
    b.app(1, 1, 1, 90)
    _build(b.conn)
    for name, as_of, expect in (("on", "2019-06-30", 0), ("after", "2019-07-01", 1)):
        sid = derive.create_snapshot(b.conn, name, as_of)
        derive.build_snapshot(b.conn, sid)
        n_view = b.conn.execute("SELECT COUNT(*) FROM v_player_season_asof WHERE snapshot_id = ?", (sid,)).fetchone()[0]
        n_base = b.conn.execute("SELECT COALESCE(SUM(n), 0) FROM cohort_baseline WHERE snapshot_id = ?", (sid,)).fetchone()[0]
        assert n_view == expect
        assert (n_base > 0) == bool(expect)


def test_build_player_season_with_seasons_leaves_other_seasons_alone(conn, b):
    b.game(1, season=2017, date="2017-09-01")
    b.game(2, season=2018, date="2018-09-01")
    b.player(1)
    b.app(1, 1, 1, 80)
    b.app(2, 1, 1, 70)
    derive.build_player_season(b.conn)
    sid = derive.create_snapshot(b.conn, "s", "2020-07-01")
    # 2017 시즌 z 행을 수동으로 심어 보존 여부를 본다
    b.conn.execute("INSERT INTO player_season_z VALUES (?,?,?,?,?,?,?)", (sid, 1, 2017, "DF", 17, "start_rate", 0.5))
    b.conn.execute("INSERT INTO player_season_z VALUES (?,?,?,?,?,?,?)", (sid, 1, 2018, "DF", 18, "start_rate", 0.5))

    def snap(season):
        ps = [tuple(r) for r in b.conn.execute("SELECT * FROM player_season WHERE season = ?", (season,))]
        m = [tuple(r) for r in b.conn.execute("SELECT * FROM player_season_metric WHERE season = ?", (season,))]
        z = [tuple(r) for r in b.conn.execute("SELECT * FROM player_season_z WHERE season = ?", (season,))]
        return ps, m, z

    before17, before18 = snap(2017), snap(2018)
    b.conn.execute("UPDATE appearance SET minutes_played = 85 WHERE appearance_id = '2_1'")
    n = derive.build_player_season(b.conn, seasons=[2018])
    assert n == 1
    after17, after18 = snap(2017), snap(2018)
    assert after17 == before17                      # 다른 시즌: player_season, metric, z 모두 그대로
    assert after18[0] != before18[0] and after18[0][0][7] == 85   # league_minutes 갱신
    assert after18[2] == []                          # 재계산 시즌의 z는 지워진다(스냅샷 재빌드 필요)
    assert b.conn.execute("PRAGMA foreign_key_check").fetchall() == []
