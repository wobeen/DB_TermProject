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


def _tenure_db(conn):
    """club_tenures 시나리오용 선수: 330(같은 구단을 세 번), 331(진행 중), 332(출전 기록만), 333(이적 기록 없는 이적 후 출전)."""
    from tests.gui.career_synth import add_app, add_player, add_transfer

    for pid, name in ((330, "Boomerang"), (331, "Ongoing"), (332, "Appearances Only")):
        add_player(conn, pid, name, "1995-01-01")
    for tid, date, frm, to in ((501, "2010-01-01", 3, 1), (502, "2012-01-01", 1, 2), (503, "2014-01-01", 2, 1),
                               (504, "2016-01-01", 1, 2), (505, "2018-01-01", 2, 1)):
        add_transfer(conn, tid, 330, date, "x", frm, to)
    add_transfer(conn, 510, 331, "2025-01-01", "24/25", 3, 1)
    conn.execute("INSERT INTO game (game_id, competition_id, season, date, home_club_id, away_club_id, home_goals,"
                 " away_goals) VALUES (20, 'GB1', 2024, '2024-10-01', 2, 3, 1, 0)")
    add_app(conn, 20, 332, 2, "GB1", "2024-10-01")
    conn.execute("UPDATE player SET current_club_id = 3 WHERE player_id IN (332)")
    conn.commit()


def test_club_tenures_transfer_based_ongoing_and_next_transfer_end(career_conn):
    _tenure_db(career_conn)
    t = players.club_tenures(career_conn, [301, 331], [1])
    assert t[301] == [("2022-07-01", "2024-07-01", "transfer")]                  # 이적해 들어와 다음 이적일에 끝난다
    assert t[331] == [("2025-01-01", None, "transfer")]                          # 이후 이적이 없고 현재 구단 -> 진행 중
    t = players.club_tenures(career_conn, [301], [3])
    assert t[301] == [("2015-01-01", "2022-07-01", "transfer"), ("2025-07-15", "2025-07-15", "transfer")]  # 마지막은 끝을 알 수 없어 시작일


def test_club_tenures_multiple_stints_and_club_sets(career_conn):
    _tenure_db(career_conn)
    t = players.club_tenures(career_conn, [330], [1])
    assert t[330] == [("2010-01-01", "2012-01-01", "transfer"), ("2014-01-01", "2016-01-01", "transfer"),
                      ("2018-01-01", None, "transfer")]
    both = players.club_tenures(career_conn, [301], [1, 2])          # 여러 구단 id: 구간이 각각
    assert both[301] == [("2022-07-01", "2024-07-01", "transfer"), ("2024-07-01", "2025-07-15", "transfer")]


def test_club_tenures_appearance_fallback_and_leave_only(career_conn):
    _tenure_db(career_conn)
    t = players.club_tenures(career_conn, [302, 332, 303], [1, 2])
    assert t[302] == [("2023-09-01", "2023-09-01", "appearance")]                  # 이적 기록 없이 출전만 -> 첫/마지막 출전일
    assert t[332] == [("2024-10-01", "2024-10-01", "appearance")]
    assert t[303] == [("2024-07-01", None, "transfer")]                          # 303 은 2 로 이적했고 현재 구단 1 도 id 에 포함 -> 진행 중
    out_only = players.club_tenures(career_conn, [303], [3])        # 303 은 3 에서 나가기만 했다
    assert out_only[303] == [(None, "2024-07-01", "transfer")]
    assert players.club_tenures(career_conn, [], [1]) == {} and players.club_tenures(career_conn, [301], []) == {}
    assert 301 not in players.club_tenures(career_conn, [301], [99999])


def test_club_tenures_batch_is_a_handful_of_queries(career_conn):
    _tenure_db(career_conn)
    seen = []
    career_conn.set_trace_callback(seen.append)
    players.club_tenures(career_conn, [301, 302, 303, 330, 331, 332], [1])
    career_conn.set_trace_callback(None)
    assert len([q for q in seen if q.lstrip().upper().startswith("SELECT")]) <= 3


def test_league_clubs_and_domestic_leagues(career_conn):
    clubs = players.league_clubs(career_conn, "GB1")
    assert [c["name"] for c in clubs] == ["Alpha FC", "Beta United", "Gamma SC"]      # 홈/원정 어느 쪽이든, 이름순
    assert [c["name"] for c in players.league_clubs(career_conn, "CL")] == ["Alpha FC", "Beta United"]   # 다른 대회도 같은 방식
    assert players.league_clubs(career_conn, "NOPE") == []
    leagues = players.domestic_leagues(career_conn)
    assert [(r["competition_id"], r["country_name"], r["is_covered"]) for r in leagues] == [("GB1", "England", 1)]
    assert players.club_ids_by_name(career_conn, "a") and players.club_ids_by_name(career_conn, "zzz") == []
    assert players.club_ids_by_name(career_conn, "gamma") == [3] and players.club_ids_by_name(career_conn, "%") == []


def test_search_by_club_ids(career_conn):
    assert {r["player_id"] for r in players.search_players_ext(career_conn, club_ids=[1])} == {301, 302}
    assert {r["player_id"] for r in players.search_players_ext(career_conn, club_ids=[3])} == {301, 303}   # 이적만
    assert {r["player_id"] for r in players.search_players_ext(career_conn, club_ids=[2])} == {301, 303}
    assert players.count_players_ext(career_conn, club_ids=[1, 2, 3]) == 3
    assert players.count_players_ext(career_conn, club_ids=[]) == players.count_players_ext(career_conn) == 3
    assert players.count_players_ext(career_conn, club_ids=[99999]) == 0
    both = players.search_players_ext(career_conn, club_ids=[1, 2, 3], sub_positions=["Right Winger"])
    assert [r["player_id"] for r in both] == [303]
    # 예전 이름 부분 일치 필터와 같은 결과 (이름 -> id 한 번 풀기)
    by_name = players.search_players_ext(career_conn, club_name="gam")
    by_ids = players.search_players_ext(career_conn, club_ids=players.club_ids_by_name(career_conn, "gam"))
    assert {r["player_id"] for r in by_name} == {r["player_id"] for r in by_ids}


def test_club_tenures_source_marks_appearance_only_stints(career_conn):
    """이적 기록이 전혀 없는 선수(예: 데이터가 2012/13 부터라 출전만 보이는 경우)는 'appearance' 로 표시된다."""
    _tenure_db(career_conn)
    t = players.club_tenures(career_conn, [301, 302, 330, 332], [1, 2])
    assert {src for stints in t.values() for _s, _e, src in stints} == {"transfer", "appearance"}
    assert all(src == "appearance" for _s, _e, src in t[302] + t[332])
    assert all(src == "transfer" for _s, _e, src in t[301] + t[330])
    # 이적 기록으로 설명되는 선수는 출전 기록이 있어도 transfer 로 남는다 (301 은 Beta 에서도 뛰었다)
    assert [src for _s, _e, src in players.club_tenures(career_conn, [301], [2])[301]] == ["transfer"]
