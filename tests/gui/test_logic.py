import pytest

from scouting.gui import logic


def test_season_label_and_competition_name():
    assert logic.season_label(2024) == "2024/25"
    assert logic.season_label(1999) == "1999/00"
    assert logic.season_label(None) == "-"
    assert logic.competition_name("premier-league") == "Premier League"
    assert logic.competition_name("uefa-champions-league") == "UEFA Champions League"
    assert logic.competition_name("laliga") == "LaLiga"
    assert logic.competition_name("fa-cup") == "FA Cup"
    assert logic.competition_name(None) == "-"


def test_fee_and_eur_formatting():
    assert logic.fee_text(None) == "-"
    assert logic.fee_text(0) == "€0"
    assert logic.fee_text(22_000_000) == "€22.0M"
    assert logic.fee_text(500_000) == "€500K"
    assert logic.eur(50_000_000) == "€50.0M"
    assert logic.eur(None) == "-"


def test_banner_text():
    text = logic.banner_text({"game": "2026-07-06", "valuation": "2026-06-12", "season": 2025})
    assert text == "데이터 기준: 경기 2026-07-06 · 시장가치 2026-06-12 (2025/26 시즌까지, 이후 이적 미반영)"


def test_coverage_note():
    note = logic.coverage_note({"covered_leagues": 14, "types": ["domestic_league", "national_team_competition"],
                                "has_uefa": True})
    assert note == "유럽 1부 14개 리그·UEFA 대회·주요 국가대항전만 수록. 그 외 리그(MLS, K리그 등) 기록은 없음."
    assert "국내컵" in logic.coverage_note({"covered_leagues": 14, "types": ["domestic_cup"], "has_uefa": False})


def test_rows_and_series():
    t = logic.transfer_rows([
        {"transfer_date": "2025-07-15", "transfer_season": "25/26", "from_club": "A", "to_club": "B",
         "fee_eur": None, "market_value_eur": 1_000_000, "upcoming": 1},
        {"transfer_date": "2020-01-01", "transfer_season": None, "from_club": None, "to_club": "B",
         "fee_eur": 2_000_000, "market_value_eur": None, "upcoming": 0}])
    assert t[0] == ("2025-07-15 (예정)", "25/26", "A → B", "-", "€1.0M")
    assert t[1] == ("2020-01-01", "-", "- → B", "€2.0M", "-")
    rows = logic.season_rows([
        {"season": 2024, "club_name": "A", "competition_slug": "premier-league", "apps": 3, "starts": None,
         "minutes": 200, "goals": 1, "assists": 0, "yellow": 0, "red": 0, "is_subtotal": 0},
        {"season": 2024, "club_name": None, "competition_slug": None, "apps": 3, "starts": None,
         "minutes": 200, "goals": 1, "assists": 0, "yellow": 0, "red": 0, "is_subtotal": 1}])
    assert rows[0] == (("2024/25", "A", "Premier League", 3, "-", 200, 1, 0, 0, 0), False)
    assert rows[1][1] is True and rows[1][0][1] == "소계"
    chart = logic.season_chart_series([{"season": 2024, "minutes": 200, "goals": 1, "assists": 2, "is_subtotal": 1},
                                       {"season": 2023, "minutes": 100, "goals": 0, "assists": 0, "is_subtotal": 1},
                                       {"season": 2023, "minutes": 100, "goals": 0, "assists": 0, "is_subtotal": 0}])
    assert chart == {"seasons": ["2023/24", "2024/25"], "minutes": [100, 200], "ga": [0, 3]}
    vals = logic.valuation_series([{"date": "2022-01-01", "market_value_eur": 10},
                                   {"date": "2021-01-01", "market_value_eur": 20}])
    assert vals["dates"] == ["2021-01-01", "2022-01-01"] and vals["peak"]["market_value_eur"] == 20
    moves = logic.club_moves([{"transfer_date": "2020-01-01", "from_club_id": 1, "to_club_id": 2, "to_club": "B"},
                              {"transfer_date": "2021-01-01", "from_club_id": 2, "to_club_id": 2, "to_club": "B"}])
    assert moves == [("2020-01-01", "B")]


def test_input_and_labels():
    assert logic.parse_int("21", "나이", 1, 100) == 21
    assert logic.parse_int("", "나이", 1, 100) is None
    with pytest.raises(ValueError):
        logic.parse_int("x", "나이", 1, 100)
    with pytest.raises(ValueError):
        logic.parse_int("101", "나이", 1, 100)
    assert logic.pos_group_of("공격수") == "FW" and logic.pos_group_of("") is None
    assert logic.identifier(1234567) == "1234567"
