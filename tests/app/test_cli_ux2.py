"""Follow-up 2 회귀 테스트 (항목 A~G): 합성 DB + 입력 주입."""

import math
import sqlite3

import pytest

import synth
from scouting.cli import main as cli_main
from scouting.cli import ui
from scouting.db import connect
from scouting.services import players, recommend, users
from test_cli import inject


def login(name="scout1"):
    return ["1", name, "pw1234"]


@pytest.fixture()
def world(db_path):
    path, ids = db_path
    conn = connect(path)
    users.register(conn, "scout1", "pw1234")
    conn.close()
    return path, ids


def _conn_app(path):
    conn = connect(path)
    return conn, cli_main.App(conn, ui.IO(lambda p="": "", lambda *a: None))


# ---- A. ID 쉼표 ------------------------------------------------------------
def test_ids_have_no_thousands_separator_and_input_accepts_commas(world):
    path, _ = world
    conn = connect(path)
    synth.add_player(conn, 1185888, "Big Id", "2000-01-01")
    conn.close()
    t = ui.table(["ID", "분", "run"], [[1185888, 12345, 1234567]])
    assert "1185888" in t and "1,185,888" not in t and "1234567" in t
    assert "12,345" in t  # ID 가 아닌 큰 수는 그대로 쉼표
    for typed in ("1185888", "1,185,888"):
        code, out = inject(path, [*login(), "2", typed, "n", "1", "0", "0"])
        assert "→ Big Id" in out, typed
    code, out = inject(path, [*login(), "1", "Big Id", "", "", "", "", "0", "0"])
    assert "1185888" in out and "1,185,888" not in out


# ---- B. 검색 정렬·총 건수·페이지 -----------------------------------------------
def _add_named(conn, pid, name, peak):
    synth.add_player(conn, pid, name, "2000-01-01", "Attack")
    synth.add_val(conn, pid, "2020-01-01", peak)


def test_search_ranking_exact_prefix_substring_then_value(world):
    path, _ = world
    conn = connect(path)
    _add_named(conn, 501, "Son", 1_000_000)               # 완전 일치
    _add_named(conn, 502, "Heung-min Son", 90_000_000)    # 성 접두(단어 접두)
    _add_named(conn, 503, "Sonny Cheap", 2_000_000)       # 이름 접두
    _add_named(conn, 504, "Jason Mount", 200_000_000)     # 부분 일치(가치가 가장 높아도 뒤)
    _add_named(conn, 505, "Son Famous", 50_000_000)       # 접두
    got = [r["player_id"] for r in players.search_players(conn, name="son")]
    assert got == [501, 502, 505, 503, 504]
    assert players.count_players(conn, name="son") == 5
    assert [r["player_id"] for r in players.search_players(conn, name="son", limit=2, offset=2)] == [505, 503]
    conn.close()


def test_search_pagination_in_cli(world):
    path, _ = world
    conn = connect(path)
    for i in range(45):
        _add_named(conn, 600 + i, f"Pager {i:02d}", 1_000_000 * (i + 1))
    conn.close()
    code, out = inject(path, [*login(), "1", "Pager", "", "", "",
                              "n", "n", "n", "p", "p", "p", "p", "", "0", "0"])
    assert "총 45명 중 1~20번째 (페이지 1/3)" in out
    assert "총 45명 중 41~45번째 (페이지 3/3)" in out
    assert "마지막 페이지입니다." in out and "첫 페이지입니다." in out
    assert out.index("Pager 44") < out.index("Pager 25")  # 시장가치 내림차순


def test_pick_player_uses_same_paging_for_profile(world):
    path, _ = world
    conn = connect(path)
    for i in range(25):
        _add_named(conn, 700 + i, f"Pick {i:02d}", 1_000_000 * (i + 1))
    conn.close()
    code, out = inject(path, [*login(), "3", "Pick", "n", "700", "0", "0", "0"])
    assert "총 25명" in out and "페이지 2/2" in out
    first, second = out.split("페이지 1/2")
    assert "Pick 00" not in first and "Pick 00" in second   # 2페이지에서 가치가 낮은 선수가 나온다


# ---- C. 포지션군별 성장표 ---------------------------------------------------------
def test_growth_table_columns_by_position(world):
    path, _ = world
    conn, app = _conn_app(path)
    hist = [{"season": 2017, "age": 18, "club_name": "A", "league_apps": 20, "league_starts": 18,
             "league_minutes": 1500, "m_minutes_share": 0.9, "m_goals_per90": 0.5, "m_ga_per90": 0.7,
             "m_assists_per90": 0.2, "m_onpitch_gd_per90": 0.3, "m_onpitch_ga_per90": 1.1,
             "m_clean_sheet_rate": 0.4}]
    common = ["시즌", "나이", "구단", "출전", "선발", "분", "점유율"]
    expect = {
        "GK": ["실점/90", "무실점률"],
        "DF": ["실점/90", "무실점률", "득실차/90"],
        "MF": ["공격P/90", "도움/90", "득실차/90"],
        "FW": ["득점/90", "공격P/90", "득실차/90"],
    }
    for pos, extra in expect.items():
        header = app.growth_table(pos, hist).splitlines()[0]
        cols = [c.strip() for c in header.split("|")]
        assert cols == common + extra, pos
    assert "실점/90" not in app.growth_table("FW", hist)
    conn.close()


# ---- D. 시장가치 시즌 요약 ---------------------------------------------------------
def test_valuation_by_season_summary_and_cli(world):
    path, _ = world
    conn = connect(path)
    for d, v in (("2019-03-01", 10_000_000), ("2019-09-01", 90_000_000), ("2020-02-01", 50_000_000),
                 ("2020-06-30", 40_000_000), ("2020-07-01", 45_000_000)):
        synth.add_val(conn, 103, d, v)
    s = players.valuation_by_season(conn, 103)
    assert [(x["season"], x["peak_eur"], x["peak_date"], x["last_eur"], x["last_date"], x["n"]) for x in s] == [
        (2018, 10_000_000, "2019-03-01", 10_000_000, "2019-03-01", 1),
        (2019, 90_000_000, "2019-09-01", 40_000_000, "2020-06-30", 3),
        (2020, 45_000_000, "2020-07-01", 45_000_000, "2020-07-01", 1),
    ]
    conn.close()
    code, out = inject(path, [*login(), "2", "103", "n", "0", "0", "0"])
    assert "€90.0M" in out and "2019-09-01" in out and "전체 시장가치 이력을 볼까요?" in out
    assert "2020-02-01" not in out                      # 요약에는 중간 값이 없다
    code, out = inject(path, [*login(), "2", "103", "y", "0", "0", "0"])
    assert "2020-02-01" in out                          # 전체 이력


# ---- E. 백분위 표시 -------------------------------------------------------------------
def test_display_value_unit_conversion():
    v, u = players.display_value("comp_strength", math.log10(100_000_000 + 1))
    assert u == "€M" and v == pytest.approx(100.0)
    v, u = players.display_value("uefa_minutes", math.log(1 + 900))
    assert u == "분" and v == pytest.approx(900)
    assert players.display_value("goals_per90", 0.4) == (0.4, "")


def test_percentile_table_formatting_and_order(world):
    path, ids = world
    conn = connect(path)
    for pid, k in ((101, 3.0), (102, 2.0), (103, 1.0)):
        synth.add_metric(conn, pid, 2017, "comp_strength", math.log10(k * 100_000_000 + 1))
        synth.add_metric(conn, pid, 2017, "minutes_share", 0.5 * k / 3)
        synth.add_metric(conn, pid, 2017, "start_rate", 0.5 * k / 3)
        synth.add_metric(conn, pid, 2017, "goals_per90", 0.1 * k)   # DF 가중치 없음
    pct = players.cohort_percentiles(conn, ids["bt"], 101, 2017)
    assert [p["metric_code"] for p in pct] == ["comp_strength", "minutes_share", "start_rate", "goals_per90"]
    assert [p["weight"] for p in pct] == [2.0, 2.0, 1.0, None]
    assert pct[0]["display_value"] == pytest.approx(300.0) and pct[0]["unit"] == "€M"
    assert pct[0]["value"] == pytest.approx(math.log10(300_000_001))   # 계산값은 그대로
    conn.close()
    code, out = inject(path, [*login(), "2", "101", "n", "1", "0", "0", "0"])
    assert "83.3" in out and "83.33" not in out         # 소수 1자리
    assert "€300.0M" in out
    assert "(90분당 득점)" in out and "가중치가 없어" in out
    assert out.index("리그 수준") < out.index("출전 시간 점유율") < out.index("선발 비율") < out.index("(90분당 득점)")


# ---- F. DB 잠금 ----------------------------------------------------------------------
def _locked_once(monkeypatch):
    real = recommend.run_recommendation
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **k)

    monkeypatch.setattr(recommend, "run_recommendation", flaky)
    return calls


def test_locked_database_guides_and_retries(world, monkeypatch):
    path, _ = world
    calls = _locked_once(monkeypatch)
    code, out = inject(path, [*login(), "4", "1", "1", "2", "2", "y", "maybe", "y", "0", "0"])
    assert "다른 작업(스냅샷 재계산 등)이 DB를 사용 중입니다. 잠시 후 다시 시도해 주세요." in out
    assert "다시 시도할까요?" in out and "y 또는 n 으로 답해 주세요." in out
    assert "database is locked" not in out and "[DB 오류]" not in out
    assert calls["n"] == 2 and "추천 완료: run #1" in out


def test_locked_database_decline_retry(world, monkeypatch):
    path, _ = world
    calls = _locked_once(monkeypatch)
    code, out = inject(path, [*login(), "4", "1", "1", "2", "2", "y", "n", "0", "0"])
    assert calls["n"] == 1 and "추천 실행을 취소했습니다." in out
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM recommendation_run").fetchone()[0] == 0
    conn.close()


def test_locked_in_other_menu_is_friendly(world, monkeypatch):
    path, _ = world

    def boom(*a, **k):
        raise sqlite3.OperationalError("database table is locked")

    monkeypatch.setattr(players, "count_players", boom)
    code, out = inject(path, [*login(), "1", "x", "", "", "", "0", "0"])
    assert "DB를 사용 중입니다" in out and "[DB 오류]" not in out and "종료합니다" in out


# ---- G. 진행 표시 ---------------------------------------------------------------------
def test_recommend_shows_progress_and_elapsed(world):
    path, _ = world
    code, out = inject(path, [*login(), "4", "1", "1", "2", "2", "y", "0", "0"])
    assert "계산 중... (후보 3명)" in out
    assert out.index("계산 중...") < out.index("추천 완료: run #1") and "소요 " in out and "초)" in out
