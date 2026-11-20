from scouting.services import players


def test_career_seasons_grouping_and_subtotals(career_conn):
    rows = players.career_seasons(career_conn, 301)
    detail = [r for r in rows if not r["is_subtotal"]]
    assert [(r["season"], r["club_name"], r["competition_id"]) for r in detail] == [
        (2023, "Alpha FC", "GB1"), (2023, "Alpha FC", "CL"), (2024, "Beta United", "GB1"),
        (2025, "Alpha FC", "FIWC"),
    ]
    gb1 = detail[0]
    assert (gb1["apps"], gb1["starts"], gb1["minutes"], gb1["goals"], gb1["assists"], gb1["yellow"], gb1["red"]) \
        == (2, 1, 120, 2, 2, 1, 0)
    assert detail[2]["starts"] is None            # 라인업 없음
    subs = {r["season"]: r for r in rows if r["is_subtotal"]}
    assert set(subs) == {2023, 2024, 2025}
    s23 = subs[2023]
    assert (s23["apps"], s23["starts"], s23["minutes"], s23["goals"], s23["assists"], s23["yellow"], s23["red"]) \
        == (3, 2, 180, 3, 2, 1, 1)
    assert rows.index(s23) == 2                   # 시즌 마지막 행
    assert subs[2024]["starts"] is None


def test_career_seasons_league_only(career_conn):
    rows = players.career_seasons(career_conn, 301, league_only=True)
    assert {r["competition_id"] for r in rows if not r["is_subtotal"]} == {"GB1"}
    assert {r["season"] for r in rows} == {2023, 2024}
    s23 = next(r for r in rows if r["is_subtotal"] and r["season"] == 2023)
    assert (s23["apps"], s23["minutes"], s23["goals"]) == (2, 120, 2)
    assert players.career_seasons(career_conn, 303) == []


def test_transfer_order_and_upcoming_flag(career_conn):
    cutoff = players.data_cutoff(career_conn)
    assert cutoff["game"] == "2025-06-01" and cutoff["season"] == 2025
    rows = players.transfer_history(career_conn, 301)
    assert [r["transfer_date"] for r in rows] == ["2015-01-01", "2022-07-01", "2024-07-01", "2025-07-15"]
    assert [r["upcoming"] for r in rows] == [0, 0, 0, 1]
    assert rows[0]["from_club"] is None and rows[0]["to_club"] == "Gamma SC"
    assert rows[2]["from_club"] == "Alpha FC" and rows[2]["to_club"] == "Beta United"
    assert players.transfer_history(career_conn, 301, cutoff="2030-01-01")[-1]["upcoming"] == 0


def test_data_cutoff_dates(career_conn):
    c = players.data_cutoff(career_conn)
    assert c["appearance"] == "2025-06-01" and c["valuation"] == "2025-05-01"


def test_search_by_nationality_and_club(career_conn):
    kr = players.search_players_ext(career_conn, nationality="Korea, South")
    assert {r["player_id"] for r in kr} == {301, 303}
    assert players.count_players_ext(career_conn, nationality="Korea, South") == 2
    assert players.nationalities(career_conn) == ["Brazil", "Korea, South"]
    # 301: 출전 기록 + 이적 기록으로 Beta 포함, 303: 이적 기록만, 302: Beta 와 무관
    beta = players.search_players_ext(career_conn, club_name="beta")
    assert {r["player_id"] for r in beta} == {301, 303}
    gamma = players.search_players_ext(career_conn, club_name="Gamma")
    assert {r["player_id"] for r in gamma} == {301, 303}
    assert {r["player_id"] for r in players.search_players_ext(career_conn, club_name="Alpha")} == {301, 302}
    both = players.search_players_ext(career_conn, nationality="Korea, South", club_name="Alpha", pos_group="FW")
    assert [r["player_id"] for r in both] == [301]
    assert players.count_players_ext(career_conn, club_name="Alpha", nationality="Brazil") == 1
    assert players.count_players_ext(career_conn, club_name="%") == 0     # LIKE 와일드카드는 이스케이프


def test_search_age_range_and_relevance(career_conn):
    rows = players.search_players_ext(career_conn, min_age=30)
    assert [r["player_id"] for r in rows] == [302]
    rows = players.search_players_ext(career_conn, max_age=26)
    assert {r["player_id"] for r in rows} == {301, 303}
    assert [r["player_id"] for r in players.search_players_ext(career_conn, name="career guy")] == [301]
    assert len(players.search_players_ext(career_conn, name="guy", limit=1, offset=1)) == 1
    assert players.count_players_ext(career_conn, name="guy") == 2


def test_suggest_players_ranking_and_fields(career_conn):
    rows = players.suggest_players(career_conn, "guy")
    assert [r["player_id"] for r in rows][:1] == [301]            # 같은 순위(부분 일치)에서는 최고 시장가치가 앞
    assert {r["player_id"] for r in rows} == {301, 302}
    first = rows[0]
    assert first["name"] == "Career Guy" and first["birth_year"] == "2000" and first["sub_position"] == "Centre-Forward"
    assert first["current_club_name"] == "Alpha FC"
    assert [r["player_id"] for r in players.suggest_players(career_conn, "career guy")] == [301]
    assert players.suggest_players(career_conn, "zzzz") == [] and players.suggest_players(career_conn, "  ") == []
    assert len(players.suggest_players(career_conn, "guy", limit=1)) == 1
    assert players.suggest_players(career_conn, "%") == []          # LIKE 와일드카드는 이스케이프


def test_suggest_players_prefers_exact_then_word_prefix(career_conn):
    from tests.gui.career_synth import add_player

    add_player(career_conn, 310, "Guy", "1995-01-01")             # 이름이 정확히 같다
    add_player(career_conn, 311, "Big Guyton", "1995-01-01")      # 부분 일치만
    career_conn.commit()
    names = [r["name"] for r in players.suggest_players(career_conn, "guy")]
    assert names[0] == "Guy"                                       # 완전 일치
    assert names.index("Career Guy") < names.index("Big Guyton")   # 단어 접두 -> 부분 일치


def test_suggest_clubs_orders_by_players_passed_through(career_conn):
    rows = players.suggest_clubs(career_conn, "a")
    names = [r["name"] for r in rows]
    assert "Alpha FC" in names and "Beta United" in names and "Gamma SC" in names
    assert players.suggest_clubs(career_conn, "gam")[0]["name"] == "Gamma SC"
    assert players.suggest_clubs(career_conn, "gam")[0]["n_players"] == 2          # 301, 303 이 거쳐 감
    assert players.suggest_clubs(career_conn, "") == [] and players.suggest_clubs(career_conn, "zzz") == []


def test_search_by_sub_positions(career_conn):
    both = players.search_players_ext(career_conn, sub_positions=["Right Winger", "Centre-Forward"])
    assert {r["player_id"] for r in both} == {301, 303}
    assert players.count_players_ext(career_conn, sub_positions=["Right Winger", "Centre-Forward"]) == 2
    only = players.search_players_ext(career_conn, sub_positions=["Central Midfield"])
    assert [r["player_id"] for r in only] == [302]
    combined = players.search_players_ext(career_conn, nationality="Korea, South", sub_positions=["Right Winger"])
    assert [r["player_id"] for r in combined] == [303]
    assert players.count_players_ext(career_conn, sub_positions=[]) == players.count_players_ext(career_conn)
