"""load_report 의 원천 행 수 = 적재 + 제외 합계 검사 (리뷰 m4)."""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest

from pipeline.load import check_report, load_all
from scouting.db import apply_sql, connect

ROOT = Path(__file__).resolve().parents[2]

HEADERS = {
    "competitions": ["competition_id", "name", "sub_type", "type", "country_name", "confederation"],
    "clubs": ["club_id", "name", "domestic_competition_id"],
    "players": ["player_id", "name", "current_club_id", "country_of_citizenship", "date_of_birth", "sub_position",
                "position", "foot", "height_in_cm"],
    "games": ["game_id", "competition_id", "season", "round", "date", "home_club_id", "away_club_id",
              "home_club_goals", "away_club_goals", "home_club_name", "away_club_name"],
    "appearances": ["appearance_id", "game_id", "player_id", "player_club_id", "date", "competition_id",
                    "yellow_cards", "red_cards", "goals", "assists", "minutes_played"],
    "game_lineups": ["game_id", "player_id", "club_id", "type", "position", "team_captain"],
    "game_events": ["game_event_id", "game_id", "minute", "type", "club_id", "player_id", "description",
                    "player_in_id", "player_assist_id"],
    "player_valuations": ["player_id", "date", "market_value_in_eur", "current_club_id"],
    "transfers": ["player_id", "transfer_date", "transfer_season", "from_club_id", "to_club_id", "from_club_name",
                  "to_club_name", "transfer_fee", "market_value_in_eur"],
}


def _write(d: Path, name: str, rows: list[dict]) -> None:
    with gzip.open(d / f"{name}.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS[name], restval="")
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def tm_dir(tmp_path):
    d = tmp_path / "tm"
    d.mkdir()
    _write(d, "competitions", [{"competition_id": "L1", "name": "l1", "sub_type": "first_tier",
                                "type": "domestic_league", "country_name": "Germany", "confederation": "europa"}])
    _write(d, "clubs", [{"club_id": 1, "name": "A", "domestic_competition_id": "L1"},
                        {"club_id": 2, "name": "B", "domestic_competition_id": "ZZZ"},   # 없는 리그 → NULL 보정
                        {"club_id": 2, "name": "B2", "domestic_competition_id": "L1"}])  # 중복 → 제외
    p = {"name": "p", "current_club_id": 1, "date_of_birth": "2000-01-01", "position": "Attack", "height_in_cm": 180}
    _write(d, "players", [dict(p, player_id=1), dict(p, player_id=2, height_in_cm=5),
                          dict(p, player_id=1),                                      # PK 중복 → IGNORE
                          dict(p, player_id=3, name="")])                            # 이름 없음 → 제외
    g = {"competition_id": "L1", "season": 2018, "date": "2018-09-01", "home_club_id": 1, "away_club_id": 3,
         "home_club_goals": 1, "away_club_goals": 0, "home_club_name": "A", "away_club_name": "C"}
    _write(d, "games", [dict(g, game_id=10), dict(g, game_id=10),                    # PK 중복
                        dict(g, game_id=11, competition_id="NOPE"),                  # 대회 없음
                        dict(g, game_id=12, away_club_id=1)])                        # 홈 = 원정
    a = {"game_id": 10, "player_club_id": 1, "date": "2018-09-01", "competition_id": "L1", "minutes_played": 90}
    _write(d, "appearances", [dict(a, appearance_id="10_1", player_id=1), dict(a, appearance_id="10_1", player_id=1),
                              dict(a, appearance_id="10_9", player_id=9),            # 없는 선수
                              dict(a, appearance_id="99_1", player_id=1, game_id=99)])  # 없는 경기
    ln = {"game_id": 10, "club_id": 1, "position": "x", "team_captain": 0}
    _write(d, "game_lineups", [dict(ln, player_id=1, type="substitutes"), dict(ln, player_id=1, type="starting_lineup"),
                               dict(ln, player_id=9, type="starting_lineup"), dict(ln, player_id=2, game_id=99,
                                                                                    type="substitutes")])
    e = {"game_id": 10, "minute": 5, "type": "Goals", "club_id": 1}
    _write(d, "game_events", [dict(e, game_event_id="a"), dict(e, game_event_id="a"),
                              dict(e, game_event_id="b", game_id=99), dict(e, game_event_id="c", minute=500)])
    v = {"player_id": 1, "market_value_in_eur": 1000, "current_club_id": 1}
    _write(d, "player_valuations", [dict(v, date="2018-01-01"), dict(v, date="2018-01-01"),
                                    dict(v, date="2018-02-01", player_id=77)])
    t = {"player_id": 1, "transfer_date": "2018-01-01", "transfer_fee": "5", "from_club_id": 1, "to_club_id": 4,
         "to_club_name": "D"}
    _write(d, "transfers", [t, dict(t, player_id=55)])
    return d


def test_report_balances_with_silent_drops_counted(tmp_path, tm_dir):
    conn = connect(tmp_path / "t.sqlite")
    apply_sql(conn, files=("schema.sql", "views.sql", "reference_data.sql"))
    rep = load_all(conn, tm_dir)
    assert rep["_balance"]["ok"] and not any(rep["_balance"]["gap_by_table"].values())
    assert check_report(rep) == {k: 0 for k in check_report(rep)}
    dup = "PK/UNIQUE 중복 → INSERT OR IGNORE 로 버림"
    for t in ("player", "game", "appearance", "game_event", "player_valuation"):
        assert rep[t]["excluded"][dup] == 1, t
    assert rep["game_lineup"]["loaded_rows"] == 1 and sum(rep["game_lineup"]["excluded"].values()) == 3
    assert rep["club"]["stub_clubs"] == 2 and rep["club"]["source_rows"] == 3   # 구단 C, D 가 stub
    assert rep["club"]["adjusted"] and rep["player"]["adjusted"]                  # 값 보정은 제외가 아니라 adjusted
    conn.close()


def test_check_report_detects_gap():
    bad = {"t": {"source_rows": 10, "loaded_rows": 6, "excluded": {"x": 3}}}
    assert check_report(bad) == {"t": 1}


def test_real_load_report_balances():
    path = ROOT / "data" / "load_report.json"
    if not path.exists():
        pytest.skip("data/load_report.json 없음")
    rep = json.loads(path.read_text(encoding="utf-8"))
    if "_balance" not in rep:
        pytest.skip("구형 load_report (재적재 필요)")
    assert not any(check_report(rep).values())
