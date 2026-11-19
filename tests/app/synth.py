"""합성 데이터 헬퍼: 실데이터 없이 임시 DB에 최소한의 행을 직접 넣는다."""

from __future__ import annotations

import sqlite3

from scouting.db import apply_sql, connect

DF_W = {"minutes_share": 2.0, "start_rate": 1.0, "onpitch_ga_per90": 1.5}  # 손계산 예제에 쓰는 지표(총 4.5)

BT_ASOF = "2018-07-01"   # 기준 시즌 L = 2017
CUR_ASOF = "2026-07-07"  # 기준 시즌 L = 2025
BUILT = "2026-07-08 00:00:00"


def new_db(path) -> sqlite3.Connection:
    conn = connect(path)
    apply_sql(conn)
    conn.execute("INSERT INTO competition (competition_id, name, type, is_covered, is_big5) "
                 "VALUES ('GB1','Premier League','domestic_league',1,1)")
    conn.execute("INSERT INTO club (club_id, name, domestic_competition_id) VALUES (1,'Alpha FC','GB1')")
    return conn


def add_snapshot(conn, name: str, as_of: str, built: bool = True) -> int:
    cur = conn.execute("INSERT INTO snapshot (name, as_of_date, built_at) VALUES (?,?,?)",
                       (name, as_of, BUILT if built else None))
    return cur.lastrowid


def add_player(conn, pid: int, name: str, dob: str, position: str = "Defender") -> None:
    conn.execute("INSERT INTO player (player_id, name, date_of_birth, position, current_club_id) "
                 "VALUES (?,?,?,?,1)", (pid, name, dob, position))


def add_ps(conn, pid: int, season: int, age: int, pos: str = "DF", minutes: int = 1500) -> None:
    conn.execute(
        """INSERT INTO player_season (player_id, season, age, pos_group, main_club_id, league_apps, league_starts,
               league_minutes, team_league_games, goals, assists, yellow_cards, red_cards, onpitch_gf,
               onpitch_ga, clean_sheets, uefa_minutes, comp_strength_eur)
           VALUES (?,?,?,?,1,20,18,?,38,1,1,2,0,20,15,5,0,1e8)""",
        (pid, season, age, pos, minutes),
    )


def add_z(conn, snap: int, pid: int, season: int, pos: str, age: int, zs: dict[str, float]) -> None:
    conn.executemany(
        "INSERT INTO player_season_z (snapshot_id, player_id, season, pos_group, age, metric_code, z) "
        "VALUES (?,?,?,?,?,?,?)",
        [(snap, pid, season, pos, age, m, z) for m, z in zs.items()],
    )


def add_label(conn, snap: int, def_id: int, pid: int, wc: bool) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO world_class_label (snapshot_id, def_id, player_id, is_world_class, achieved_on) "
        "VALUES (?,?,?,?,?)",
        (snap, def_id, pid, int(wc), "2020-01-01" if wc else None),
    )


def add_val(conn, pid: int, date: str, eur: int) -> None:
    conn.execute("INSERT OR REPLACE INTO player_valuation (player_id, date, market_value_eur, club_id) "
                 "VALUES (?,?,?,1)", (pid, date, eur))


def add_metric(conn, pid: int, season: int, code: str, value: float) -> None:
    conn.execute("INSERT OR REPLACE INTO player_season_metric (player_id, season, metric_code, value) "
                 "VALUES (?,?,?,?)", (pid, season, code, value))


def build_main(conn) -> dict:
    """손계산 가능한 시나리오 DB. 반환: 주요 ID 모음.

    bt 스냅샷(2018-07-01, L=2017): 후보 C1~C3(DF, 18세), 비교 풀 P1~P9.
    cur 스냅샷(2026-07-07): 정답 라벨(C1, C3 월클).
    """
    bt = add_snapshot(conn, "bt2018", BT_ASOF)
    cur = add_snapshot(conn, "current", CUR_ASOF)
    ids: dict = {"bt": bt, "cur": cur}

    # --- 후보 (시즌 2017, 나이 18) ---
    cands = {
        101: ("Cand One", "1999-03-01", {"minutes_share": 1.0, "start_rate": 0.0, "onpitch_ga_per90": -1.0}),
        102: ("Cand Two", "1999-05-01", {"minutes_share": -1.0, "start_rate": 0.5, "onpitch_ga_per90": 1.0}),
        103: ("Cand Three", "1999-08-01", {"minutes_share": 0.2, "start_rate": 0.2, "onpitch_ga_per90": 0.2}),
    }
    for pid, (name, dob, zs) in cands.items():
        add_player(conn, pid, name, dob)
        add_ps(conn, pid, 2017, 18)
        add_z(conn, bt, pid, 2017, "DF", 18, zs)
        add_z(conn, cur, pid, 2017, "DF", 18, zs)
    # 제외 대상: 이미 월클(bt 라벨 1), 출전 분 부족, 나이 초과, 다른 포지션
    add_player(conn, 104, "Already WC", "1999-01-01"); add_ps(conn, 104, 2017, 18)
    add_z(conn, bt, 104, 2017, "DF", 18, DF_W)
    add_player(conn, 105, "Few Minutes", "1999-01-01"); add_ps(conn, 105, 2017, 18, minutes=300)
    add_z(conn, bt, 105, 2017, "DF", 18, DF_W)
    add_player(conn, 106, "Too Old", "1995-01-01"); add_ps(conn, 106, 2017, 22)
    add_z(conn, bt, 106, 2017, "DF", 22, DF_W)
    add_player(conn, 107, "Midfielder", "1999-01-01", "Midfield"); add_ps(conn, 107, 2017, 18, pos="MF")
    add_z(conn, bt, 107, 2017, "MF", 18, DF_W)

    # --- 비교 풀 (시즌 2014, 나이 18, DF) ---
    pool = {
        201: {"minutes_share": 1.0, "start_rate": 0.0, "onpitch_ga_per90": -1.0},    # C1 과 거리 0
        202: {"minutes_share": 1.5, "start_rate": 0.5, "onpitch_ga_per90": -0.5},
        203: {"minutes_share": 0.0, "start_rate": 0.0, "onpitch_ga_per90": 0.0},
        204: {"minutes_share": 2.0, "start_rate": 1.0},                              # 공유 가중치 3.0/4.5 >= 60%
        205: {"minutes_share": 1.0},                                                 # 2.0/4.5 < 60% → 제외
        209: {"minutes_share": 1.5, "start_rate": 0.5, "onpitch_ga_per90": -0.5},    # 202 와 동률 → id 순
    }
    for pid, zs in pool.items():
        add_player(conn, pid, f"Pool {pid}", "1996-02-01")
        add_ps(conn, pid, 2014, 18)
        add_z(conn, bt, pid, 2014, "DF", 18, zs)
    # 풀에서 제외되어야 하는 행: lag 위반(2015), 다른 나이, 다른 포지션
    add_player(conn, 206, "Pool lag", "1997-02-01"); add_ps(conn, 206, 2015, 18)
    add_z(conn, bt, 206, 2015, "DF", 18, DF_W)
    add_player(conn, 207, "Pool age19", "1995-02-01"); add_ps(conn, 207, 2014, 19)
    add_z(conn, bt, 207, 2014, "DF", 19, DF_W)
    add_player(conn, 208, "Pool MF", "1996-02-01", "Midfield"); add_ps(conn, 208, 2014, 18, pos="MF")
    add_z(conn, bt, 208, 2014, "MF", 18, DF_W)

    # --- 라벨 ---
    for d in (1, 2):
        for pid in (*cands, 104, 105, 106, 107, *pool, 206, 207, 208):
            add_label(conn, bt, d, pid, pid in (201, 203, 104) and d == 1)  # bt: P1,P3,Already WC 월클
            add_label(conn, cur, d, pid, pid in (101, 103) and d == 1)       # cur: C1, C3 가 월클이 됨
    # --- 시장가치 (bt 이전) ---
    add_val(conn, 101, "2017-12-01", 5_000_000)
    add_val(conn, 102, "2017-12-01", 30_000_000)
    add_val(conn, 102, "2016-12-01", 1_000_000)
    # 103 은 가치 없음
    return ids
