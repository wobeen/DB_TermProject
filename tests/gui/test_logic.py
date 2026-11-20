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
    groups = logic.season_groups([
        {"season": 2024, "club_id": 1, "club_name": "A", "competition_slug": "premier-league", "apps": 3,
         "starts": None, "minutes": 200, "goals": 1, "assists": 0, "yellow": 0, "red": 0, "is_subtotal": 0},
        {"season": 2024, "club_id": 1, "club_name": "A", "competition_slug": "fa-cup", "apps": 1,
         "starts": 1, "minutes": 90, "goals": 0, "assists": 1, "yellow": 1, "red": 0, "is_subtotal": 0},
        {"season": 2024, "club_id": 2, "club_name": "B", "competition_slug": "laliga", "apps": 2,
         "starts": None, "minutes": 50, "goals": 0, "assists": 0, "yellow": 0, "red": 0, "is_subtotal": 0},
        {"season": 2024, "club_id": None, "club_name": None, "competition_slug": None, "apps": 6,
         "starts": 1, "minutes": 340, "goals": 1, "assists": 1, "yellow": 1, "red": 0, "is_subtotal": 1}])
    assert [g["label"] for g in groups] == ["2024/25 · A", "2024/25 · B"]      # 구단별 부모, 소계 행은 무시
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


def test_chart_move_merge_shorten_and_skip_rules():
    # 180일 미만 간격은 하나로: 임대 후 복귀는 마지막 도착 구단만 남는다
    moves = [("2010-01-01", "A"), ("2010-03-01", "B"), ("2010-05-01", "A"), ("2012-01-01", "C")]
    moves = [(d, c, None) for d, c in moves]
    assert logic.merge_close_moves(moves) == [("2010-05-01", "A", None), ("2012-01-01", "C", None)]
    assert len(logic.merge_close_moves([("2010-01-01", "A", None), ("2010-06-30", "B", None)])) == 2  # 180일
    assert logic.shorten("SL Benfica") == "SL Benfica"
    assert logic.shorten("Wolverhampton Wanderers") == "Wolverhampton…" and len(logic.shorten("Wolverhampton Wanderers")) == 14
    transfers = [{"transfer_date": d, "from_club_id": f, "to_club_id": t, "to_club": c} for d, f, t, c in (
        ("2005-01-01", 1, 2, "Early"),                    # 범위 밖
        ("2010-01-01", 2, 3, "Loan Club"), ("2010-03-01", 3, 2, "Home Club With Long Name"),
        ("2012-01-01", 2, 4, "Last"), ("2020-01-01", 4, 5, "Future"))]
    assert logic.chart_moves(transfers, "2008-01-01", "2015-01-01") == [
        ("2010-03-01", "Home Club Wit…", None), ("2012-01-01", "Last", None)]
    # 라벨 줄 배치: 겹치면 다음 줄, 3줄 모두 겹치면 생략, 줄이 비면 재사용
    spans = [(0, 50), (10, 60), (20, 70), (30, 80), (100, 150)]
    assert logic.assign_label_rows(spans, rows=3, pad=4) == [0, 1, 2, None, 0]
    assert logic.assign_label_rows([(0, 50), (54, 90)], rows=1, pad=4) == [0, 0]
    assert logic.assign_label_rows([(0, 50), (52, 90)], rows=1, pad=4) == [0, None]


def test_oblak_like_labels_keep_the_paid_move():
    rows = [("2010-01-04", "SL Benfica", 4_000_000.0), ("2010-01-05", "SC Beira-Mar", 0.0),
            ("2010-06-30", "SL Benfica", 0.0), ("2011-01-04", "SC Olhanense", 0.0),
            ("2011-06-30", "SL Benfica", 0.0), ("2011-09-09", "União de Leiria", 0.0),
            ("2012-06-30", "SL Benfica", 0.0), ("2012-09-09", "Rio Ave FC", 0.0),
            ("2013-06-30", "SL Benfica", 0.0), ("2014-07-16", "Atlético de Madrid", 16_000_000.0)]
    transfers = [{"transfer_date": d, "to_club": c, "fee_eur": f, "from_club_id": i, "to_club_id": i + 1}
                 for i, (d, c, f) in enumerate(rows)]
    moves = logic.chart_moves(transfers, "2010-01-01", "2015-01-01")
    atletico = next(i for i, m in enumerate(moves) if m[1].startswith("Atl"))
    order = logic.label_priority(moves)
    assert moves[order[0]][1].startswith("Atl")                 # 이적료 큰 순이 먼저
    assert moves[order[1]][2] == 4_000_000.0                    # 그다음 이적료가 있는 이적(임대와 병합돼도 이적료 유지)
    assert [moves[i][0] for i in order[2:]] == sorted((m[0] for m in moves if not m[2]), reverse=True)
    # 시간 순으로는 앞쪽 라벨이 3줄을 모두 차지해 Atlético 가 밀리는 좁은 간격 (모두 서로 겹침)
    spans = [(100 + 5 * i, 190 + 5 * i) for i in range(len(moves))]
    assert logic.assign_label_rows(spans, rows=3)[atletico] is None
    placed = logic.assign_label_rows(spans, rows=3, order=order)
    assert placed[atletico] == 0                                # 우선순위 배치에서는 유지
    assert sum(r is not None for r in placed) == 3              # 나머지는 겹치면 생략
