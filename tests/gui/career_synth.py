"""Synthetic career data for the GUI/service tests (extends tests/app/synth.py helpers)."""

from tests.app.synth import add_player, add_snapshot, add_val, new_db

CUTOFF = "2025-06-01"          # 마지막 경기일
FUTURE = "2025-07-15"          # 기준일 이후 이적


def add_game(conn, gid, comp, season, date, home=1, away=2):
    conn.execute(
        "INSERT INTO game (game_id, competition_id, season, date, home_club_id, away_club_id, home_goals, away_goals)"
        " VALUES (?,?,?,?,?,?,1,0)", (gid, comp, season, date, home, away))


def add_app(conn, gid, pid, club, comp, date, minutes=90, goals=0, assists=0, yellow=0, red=0, starter=None):
    conn.execute(
        "INSERT INTO appearance (appearance_id, game_id, player_id, club_id, date, competition_id, minutes_played,"
        " goals, assists, yellow_cards, red_cards) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (f"{gid}_{pid}", gid, pid, club, date, comp, minutes, goals, assists, yellow, red))
    if starter is not None:
        conn.execute("INSERT INTO game_lineup (game_id, player_id, club_id, is_starter) VALUES (?,?,?,?)",
                     (gid, pid, club, starter))


def add_transfer(conn, tid, pid, date, season, frm, to, fee=None, value=None):
    conn.execute(
        "INSERT INTO transfer (transfer_id, player_id, transfer_date, transfer_season, from_club_id, to_club_id,"
        " fee_eur, market_value_eur) VALUES (?,?,?,?,?,?,?,?)", (tid, pid, date, season, frm, to, fee, value))


def build_career(path):
    """player 301 'Career Guy'(Korea, South, FW): 2023 에 Alpha(리그 2경기+CL 1경기), 2024 에 Beta(리그 1경기).
    player 302 'Other Guy'(Brazil, MF): Alpha 에서 1경기. 303 'Never Played'(Korea, South): Beta 로 이적만 있음."""
    conn = new_db(path)
    add_snapshot(conn, "current", "2026-07-07")
    conn.execute("UPDATE competition SET country_name = 'England' WHERE competition_id = 'GB1'")
    conn.execute("INSERT INTO competition (competition_id, name, type, is_uefa_club) VALUES "
                 "('CL','uefa-champions-league','international_cup',1)")
    conn.execute("INSERT INTO competition (competition_id, name, type) VALUES "
                 "('FIWC','world-cup','national_team_competition')")
    conn.execute("INSERT INTO club (club_id, name) VALUES (2,'Beta United'), (3,'Gamma SC')")
    for pid, name, dob, pos, nat in ((301, "Career Guy", "2000-01-01", "Attack", "Korea, South"),
                                     (302, "Other Guy", "1990-01-01", "Midfield", "Brazil"),
                                     (303, "Never Played", "2004-01-01", "Attack", "Korea, South")):
        add_player(conn, pid, name, dob, pos)
        conn.execute("UPDATE player SET country_of_citizenship = ? WHERE player_id = ?", (nat, pid))
    for pid, sub in ((301, "Centre-Forward"), (302, "Central Midfield"), (303, "Right Winger")):
        conn.execute("UPDATE player SET sub_position = ? WHERE player_id = ?", (sub, pid))
    add_game(conn, 1, "GB1", 2023, "2023-09-01")
    add_game(conn, 2, "GB1", 2023, "2023-10-01")
    add_game(conn, 3, "CL", 2023, "2023-11-01")
    add_game(conn, 4, "GB1", 2024, "2024-09-01", home=2, away=3)
    add_game(conn, 5, "FIWC", 2025, CUTOFF, home=1, away=3)
    add_app(conn, 1, 301, 1, "GB1", "2023-09-01", 90, goals=2, assists=1, yellow=1, starter=1)
    add_app(conn, 2, 301, 1, "GB1", "2023-10-01", 30, goals=0, assists=1, starter=0)
    add_app(conn, 3, 301, 1, "CL", "2023-11-01", 60, goals=1, red=1, starter=1)
    add_app(conn, 4, 301, 2, "GB1", "2024-09-01", 80, goals=1)          # 라인업 데이터 없음
    add_app(conn, 5, 301, 1, "FIWC", CUTOFF, 45, assists=1)
    add_app(conn, 1, 302, 1, "GB1", "2023-09-01", 90, starter=1)
    add_transfer(conn, 12, 301, "2022-07-01", "22/23", 3, 1, fee=5_000_000, value=3_000_000)
    add_transfer(conn, 11, 301, "2015-01-01", "14/15", None, 3)          # 유소년 입단, 날짜 순서는 id 와 다르다
    add_transfer(conn, 13, 301, "2024-07-01", "24/25", 1, 2, fee=0, value=10_000_000)
    add_transfer(conn, 14, 301, FUTURE, "25/26", 2, 3, fee=20_000_000, value=25_000_000)
    add_transfer(conn, 15, 303, "2024-07-01", "24/25", 3, 2)
    add_val(conn, 301, "2023-01-01", 3_000_000)
    add_val(conn, 301, "2025-05-01", 12_000_000)
    conn.commit()
    return conn
