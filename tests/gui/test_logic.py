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
    assert text == "데이터 기준 경기 2026-07-06, 시장가치 2026-06-12 (2025/26 시즌까지, 이후 이적 미반영)"


def test_coverage_note():
    note = logic.coverage_note({"covered_leagues": 14, "types": ["domestic_league", "national_team_competition"],
                                "has_uefa": True})
    assert note == "유럽 1부 14개 리그, UEFA 대회, 주요 국가대항전만 수록. 그 외 리그(MLS, K리그 등) 기록은 없음."
    assert "국내컵" in logic.coverage_note({"covered_leagues": 14, "types": ["domestic_cup"], "has_uefa": False})


def test_rows_and_series():
    t = logic.transfer_rows([
        {"transfer_date": "2025-07-15", "transfer_season": "25/26", "from_club": "A", "to_club": "B",
         "fee_eur": None, "market_value_eur": 1_000_000, "upcoming": 1},
        {"transfer_date": "2020-01-01", "transfer_season": None, "from_club": None, "to_club": "B",
         "fee_eur": 2_000_000, "market_value_eur": None, "upcoming": 0}])
    assert t[0] == ("2025-07-15 (예정)", "25/26", "A → B", "-", "€1.0M")
    assert t[1] == ("2020-01-01", "-", "- → B", "€2.0M", "-")
    groups = logic.season_groups([
        {"season": 2024, "club_id": 1, "club_name": "A", "competition_slug": "premier-league", "apps": 3,
         "starts": None, "minutes": 200, "goals": 1, "assists": 0, "yellow": 0, "red": 0, "is_subtotal": 0},
        {"season": 2024, "club_id": 1, "club_name": "A", "competition_slug": "fa-cup", "apps": 1,
         "starts": 1, "minutes": 90, "goals": 0, "assists": 1, "yellow": 1, "red": 0, "is_subtotal": 0},
        {"season": 2024, "club_id": 2, "club_name": "B", "competition_slug": "laliga", "apps": 2,
         "starts": None, "minutes": 50, "goals": 0, "assists": 0, "yellow": 0, "red": 0, "is_subtotal": 0},
        {"season": 2024, "club_id": None, "club_name": None, "competition_slug": None, "apps": 6,
         "starts": 1, "minutes": 340, "goals": 1, "assists": 1, "yellow": 1, "red": 0, "is_subtotal": 1}])
    assert [(g["season"], g["club"]) for g in groups] == [("2024/25", "A"), ("2024/25", "B")]   # 구단별 부모, 소계 행은 무시
    assert groups[0]["values"] == (4, 1, 290, 1, 1, 1, 0)
    assert groups[0]["children"][0] == ("Premier League", (3, "-", 200, 1, 0, 0, 0))
    assert groups[0]["children"][1][0] == "FA Cup" and len(groups[0]["children"]) == 2
    assert groups[1]["values"][1] == "-"
    chart = logic.season_chart_series([{"season": 2024, "minutes": 200, "goals": 1, "assists": 2, "is_subtotal": 1},
                                       {"season": 2023, "minutes": 100, "goals": 0, "assists": 0, "is_subtotal": 1},
                                       {"season": 2023, "minutes": 100, "goals": 0, "assists": 0, "is_subtotal": 0}])
    assert chart == {"seasons": ["2023/24", "2024/25"], "minutes": [100, 200], "ga": [0, 3]}
    vals = logic.valuation_series([{"date": "2022-01-01", "market_value_eur": 10},
                                   {"date": "2021-01-01", "market_value_eur": 20}])
    assert vals["dates"] == ["2021-01-01", "2022-01-01"] and vals["peak"]["market_value_eur"] == 20
    moves = logic.club_moves([{"transfer_date": "2020-01-01", "from_club_id": 1, "to_club_id": 2, "to_club": "B"},
                              {"transfer_date": "2021-01-01", "from_club_id": 2, "to_club_id": 2, "to_club": "B"}])
    assert moves == [("2020-01-01", "B", None)]


def test_input_and_labels():
    assert logic.parse_int("21", "나이", 1, 100) == 21
    assert logic.parse_int("", "나이", 1, 100) is None
    with pytest.raises(ValueError):
        logic.parse_int("x", "나이", 1, 100)
    with pytest.raises(ValueError):
        logic.parse_int("101", "나이", 1, 100)
    assert logic.pos_group_of("공격수") == "FW" and logic.pos_group_of("") is None
    assert logic.identifier(1234567) == "1234567"


def _t(tid, date, to_id, to_club, fee=None):
    return {"transfer_id": tid, "transfer_date": date, "to_club_id": to_id, "to_club": to_club, "fee_eur": fee}


def test_tenures_cover_first_transfer_to_cutoff_without_gaps_or_overlaps():
    transfers = [_t(3, "2010-07-01", 3, "C", 5_000_000.0), _t(1, "2005-01-01", 1, "A"), _t(2, "2008-01-01", 2, "B"),
                 _t(4, "2013-07-01", 1, "A", 0.0),             # A 로 복귀
                 _t(5, "2030-01-01", 9, "Future", 1.0)]         # 기준일 이후(예정)는 제외
    blocks = logic.tenures(transfers, "2026-07-06")
    assert [b["club"] for b in blocks] == ["A", "B", "C", "A"]
    assert blocks[0]["start"] == "2005-01-01" and blocks[-1]["end"] == "2026-07-06"
    for prev, nxt in zip(blocks, blocks[1:]):
        assert prev["end"] == nxt["start"]                      # 빈틈도 겹침도 없다
    assert all(b["start"] < b["end"] for b in blocks)
    assert blocks[2]["fee"] == 5_000_000.0
    # 처음 등장한 구단 순서로 0,1,0 ... 복귀한 A 는 첫 재직 때 색을 유지
    assert [b["color"] for b in blocks] == [0, 1, 0, 0]
    assert blocks[3]["color"] == blocks[0]["color"]


def test_tenures_edge_cases():
    assert logic.tenures([], "2026-01-01") == []
    # 같은 날 두 이적은 마지막 도착지만, 도착 구단이 없는 행은 무시, 기준일 당일 시작은 길이 0 이라 제외
    rows = [_t(1, "2020-01-01", 1, "A"), _t(2, "2020-01-01", 2, "B"), {"transfer_id": 3,
            "transfer_date": "2021-01-01", "to_club_id": None, "to_club": None},
            _t(4, "2026-01-01", 3, "C")]
    blocks = logic.tenures(rows, "2026-01-01")
    assert [(b["club"], b["start"], b["end"]) for b in blocks] == [("B", "2020-01-01", "2026-01-01")]


def test_fit_label_fits_truncates_or_drops():
    def measure(text):
        return 10 * len(text)

    assert logic.fit_label("Arsenal", 100, measure) == "Arsenal"
    assert logic.fit_label("Tottenham Hotspur", 80, measure) == "Tottenh…"      # 8글자(… 포함)까지
    assert logic.fit_label("Tottenham Hotspur", 30, measure) == "To…"           # 3글자까지는 허용
    assert logic.fit_label("Tottenham Hotspur", 29, measure) is None            # 3글자도 안 들어가면 라벨 없음
    assert logic.fit_label("", 100, measure) is None


def test_position_and_notes():
    assert logic.position_text({"pos_group": "FW", "sub_position": "Left Winger"}) == "공격수 (Left Winger)"
    assert logic.position_text({"pos_group": "GK", "sub_position": None}) == "골키퍼"
    assert "14개" in logic.no_league_note({"covered_leagues": 14})
    assert logic.EMPTY_SEARCH.startswith("조건에 맞는 선수가 없습니다.")


def test_shorten_club_for_strip():
    cases = {
        "Los Angeles Football Club": "Los Angeles", "Bayer 04 Leverkusen": "Leverkusen",
        "Hamburger SV": "Hamburger", "SL Benfica": "Benfica", "FC Barcelona": "Barcelona",
        "Real Madrid Club de Fútbol": "Real Madrid", "Juventus Football Club": "Juventus",
        "Hannover 96": "Hannover", "1. FC Köln": "Köln", "SC Beira-Mar": "Beira-Mar",
        "Atlético de Madrid": "Atlético de Madrid", "Tottenham Hotspur": "Tottenham Hotspur",
        "Hamburger SV II": "Hamburger SV II", "FC": "FC", "Club Brugge": "Brugge",
    }
    for full, short in cases.items():
        assert logic.shorten_club(full) == short, full


def test_youth_collapse_and_strip_start():
    blocks = logic.tenures([_t(1, "2005-01-01", 1, "Hupyeong MS"), _t(2, "2007-01-01", 2, "Yukminkwan MS"),
                            _t(3, "2010-07-01", 3, "Hamburger SV II"), _t(4, "2013-07-01", 4, "Hamburger SV"),
                            _t(5, "2015-08-01", 5, "Tottenham")], "2026-07-06")
    # 첫 시장가치 2010-12-01, 첫 출전 2012-08-01 -> 이른 쪽(2010-12-01) 이전에 끝난 구간만 유스 (Hamburger SV II 는 걸침)
    out = logic.collapse_youth(blocks, "2010-12-01", "2012-08-01")
    assert [b["club"] for b in out] == ["유스", "Hamburger SV II", "Hamburger SV", "Tottenham"]
    assert (out[0]["start"], out[0]["end"], out[0]["color"]) == ("2005-01-01", "2010-07-01", 2)
    assert out[1]["start"] == out[0]["end"]                       # 빈틈 없음
    # 첫 출전이 더 이르면 그 날이 기준
    early = logic.collapse_youth(blocks, "2010-12-01", "2007-06-01")
    assert [b["club"] for b in early][:2] == ["유스", "Yukminkwan MS"] and early[0]["end"] == "2007-01-01"
    assert logic.collapse_youth(blocks, None, None) == blocks          # 기준이 없으면 그대로
    assert logic.collapse_youth(blocks, "2004-01-01", None) == blocks  # 끝난 구간이 없으면 그대로
    assert logic.strip_start("2005-01-01", "2010-12-01") == "2009-12-01"
    assert logic.strip_start("2012-01-01", "2010-12-01") == "2012-01-01"
    assert logic.strip_start("2005-01-01", None) == "2005-01-01"
