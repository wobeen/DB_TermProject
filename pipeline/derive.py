"""파생 계산 (CONTRACT §3.2~3.3). 전부 집합 기반 SQL(INSERT ... SELECT, CTE, 윈도 함수)로 계산한다.

Python은 오케스트레이션(임시 테이블 생성, 파라미터 바인딩)만 맡는다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from scouting.db import transaction

FIRST_SEASON = 2012
LAST_SEASON = 2025
COHORT_AGE_MIN, COHORT_AGE_MAX = 16, 35
MIN_COHORT_N = 20
EPS_STD = 1e-12  # 상수 코호트의 부동소수점 잡음(std≈1e-16)을 걸러낸다
Z_CLIP = 4.0

# 마지막 build_player_season 실행의 진단 수치(계약 §3.2의 예외 처리 건수). setup_db가 출력한다.
LAST_BUILD_STATS: dict[str, int] = {}

_TEMP_TABLES = ("t_app", "t_ev_in", "t_ev_out", "t_goal", "t_lg0", "t_pitch", "t_lg", "t_ps", "t_main",
                "t_team", "t_uefa", "t_str")


# ---------------------------------------------------------------- 공통
def _seasons_json(conn: sqlite3.Connection, seasons: Sequence[int] | None) -> str:
    """대상 시즌 목록을 JSON 배열 문자열로(?-바인딩 후 json_each로 푼다)."""
    if seasons is None:
        rows = conn.execute(
            "SELECT DISTINCT g.season FROM game g JOIN competition c ON c.competition_id = g.competition_id "
            "WHERE c.is_covered = 1 AND g.season BETWEEN ? AND ? ORDER BY 1", (FIRST_SEASON, LAST_SEASON)
        ).fetchall()
        return json.dumps([r[0] for r in rows])
    return json.dumps(sorted({int(s) for s in seasons}))


def _drop_temp(conn: sqlite3.Connection) -> None:
    for t in _TEMP_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS temp.{t}")  # 내부 상수 이름


# ---------------------------------------------------------------- competition_season_strength
def build_competition_strength(conn: sqlite3.Connection, seasons: Sequence[int] | None = None) -> int:
    """covered 리그 × 시즌별로 season-07-01 이전 최신 시장가치의 평균. 반환값은 저장한 행 수."""
    sj = _seasons_json(conn, seasons)
    with transaction(conn):
        conn.execute("DELETE FROM competition_season_strength WHERE season IN (SELECT value FROM json_each(?))", (sj,))
        cur = conn.execute(
            """
            INSERT INTO competition_season_strength (competition_id, season, avg_player_value_eur, n_players)
            SELECT competition_id, season, AVG(val), COUNT(*)
            FROM (
                SELECT d.competition_id, d.season,
                       (SELECT v.market_value_eur FROM player_valuation v
                         WHERE v.player_id = d.player_id AND v.date < d.season || '-07-01'
                         ORDER BY v.date DESC LIMIT 1) AS val
                FROM (SELECT DISTINCT g.competition_id, g.season, a.player_id
                        FROM appearance a
                        JOIN game g ON g.game_id = a.game_id
                        JOIN competition c ON c.competition_id = g.competition_id AND c.is_covered = 1
                       WHERE a.minutes_played >= 1 AND g.season IN (SELECT value FROM json_each(?))) d
            )
            WHERE val IS NOT NULL
            GROUP BY competition_id, season
            """,
            (sj,),
        )
        n = cur.rowcount
    return n


# ---------------------------------------------------------------- player_season
def _build_temp_facts(conn: sqlite3.Connection, sj: str) -> dict[str, int]:
    """출전 구간 모델로 출전 단위(appearance)별 사실을 TEMP 테이블에 만든다."""
    _drop_temp(conn)
    # 1) 대상 시즌의 covered 리그 + UEFA 클럽 대회 출전(1분 이상)
    conn.execute(
        """
        CREATE TEMP TABLE t_app AS
        SELECT a.game_id, a.player_id, g.season, g.competition_id, a.club_id,
               g.home_club_id, g.away_club_id, a.minutes_played AS minutes,
               a.goals, a.assists, a.yellow_cards AS yc, a.red_cards AS rc,
               c.is_covered, c.is_uefa_club
        FROM appearance a
        JOIN game g ON g.game_id = a.game_id
        JOIN competition c ON c.competition_id = g.competition_id
        WHERE a.minutes_played >= 1 AND (c.is_covered = 1 OR c.is_uefa_club = 1)
          AND g.season IN (SELECT value FROM json_each(?))
        """,
        (sj,),
    )
    conn.execute("CREATE INDEX temp.t_app_ix ON t_app(game_id, player_id)")
    # 2) 이벤트에서 파생한 구간 재료. minute = -1(분 정보 없음)은 in/out 계산에서 뺀다.
    conn.execute(
        """
        CREATE TEMP TABLE t_ev_in AS
        SELECT e.game_id, e.player_in_id AS player_id,
               MIN(CASE WHEN e.minute >= 0 THEN e.minute END) AS in_min
        FROM game_event e
        WHERE e.type = 'Substitutions' AND e.player_in_id IS NOT NULL
          AND e.game_id IN (SELECT game_id FROM t_app WHERE is_covered = 1)
        GROUP BY e.game_id, e.player_in_id
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_ev_in_ix ON t_ev_in(game_id, player_id)")
    conn.execute(
        """
        CREATE TEMP TABLE t_ev_out AS
        SELECT game_id, player_id, MIN(minute) AS out_min
        FROM (
            SELECT e.game_id, e.player_id, e.minute FROM game_event e
             WHERE e.type = 'Substitutions' AND e.player_id IS NOT NULL AND e.minute >= 0
               AND e.game_id IN (SELECT game_id FROM t_app WHERE is_covered = 1)
            UNION ALL
            SELECT e.game_id, e.player_id, e.minute FROM game_event e
             WHERE e.is_sending_off = 1 AND e.player_id IS NOT NULL AND e.minute >= 0
               AND e.game_id IN (SELECT game_id FROM t_app WHERE is_covered = 1)
        )
        GROUP BY game_id, player_id
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_ev_out_ix ON t_ev_out(game_id, player_id)")
    conn.execute(
        """
        CREATE TEMP TABLE t_goal AS
        SELECT e.game_id, e.minute, e.club_id FROM game_event e
        WHERE e.type = 'Goals' AND e.game_id IN (SELECT game_id FROM t_app WHERE is_covered = 1)
        """
    )
    conn.execute("CREATE INDEX temp.t_goal_ix ON t_goal(game_id)")
    # 3) 선발 판정 + 출전 구간 (in, out]
    conn.execute(
        """
        CREATE TEMP TABLE t_lg0 AS
        SELECT x.*,
               CASE WHEN l.player_id IS NOT NULL THEN l.is_starter
                    WHEN ei.player_id IS NULL THEN 1 ELSE 0 END AS is_start,
               ei.in_min, eo.out_min,
               CASE WHEN x.club_id IN (x.home_club_id, x.away_club_id) THEN 1 ELSE 0 END AS side_ok
        FROM t_app x
        LEFT JOIN game_lineup l ON l.game_id = x.game_id AND l.player_id = x.player_id
        LEFT JOIN t_ev_in ei ON ei.game_id = x.game_id AND ei.player_id = x.player_id
        LEFT JOIN t_ev_out eo ON eo.game_id = x.game_id AND eo.player_id = x.player_id
        WHERE x.is_covered = 1
        """
    )
    conn.execute("ALTER TABLE temp.t_lg0 ADD COLUMN inn INTEGER")
    conn.execute("UPDATE temp.t_lg0 SET inn = CASE WHEN is_start = 1 THEN 0 ELSE in_min END")
    conn.execute("CREATE UNIQUE INDEX temp.t_lg0_ix ON t_lg0(game_id, player_id)")
    # 4) 출전 중 팀 득점/실점. 구간 (in, out], minute=-1은 in=0 AND out=∞ 인 선수에게만.
    #    출전 구단이 홈/원정이 아니거나 in을 모르는 출전은 on-pitch 집계에서 뺀다(0으로 두고 건수 기록).
    conn.execute(
        """
        CREATE TEMP TABLE t_pitch AS
        SELECT x.game_id, x.player_id,
               COALESCE(SUM(CASE WHEN gl.club_id = x.club_id THEN 1 END), 0) AS gf,
               COALESCE(SUM(CASE WHEN gl.club_id <> x.club_id THEN 1 END), 0) AS ga
        FROM t_lg0 x
        JOIN t_goal gl ON gl.game_id = x.game_id
        WHERE x.side_ok = 1 AND x.inn IS NOT NULL
          AND gl.club_id IN (x.home_club_id, x.away_club_id)
          AND ((gl.minute = -1 AND x.inn = 0 AND x.out_min IS NULL)
               OR (gl.minute >= 0 AND gl.minute > x.inn AND gl.minute <= COALESCE(x.out_min, 1000000)))
        GROUP BY x.game_id, x.player_id
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_pitch_ix ON t_pitch(game_id, player_id)")
    conn.execute(
        """
        CREATE TEMP TABLE t_lg AS
        SELECT x.*, COALESCE(p.gf, 0) AS gf, COALESCE(p.ga, 0) AS ga,
               CASE WHEN x.side_ok = 1 AND x.inn IS NOT NULL THEN 1 ELSE 0 END AS ok_on
        FROM t_lg0 x LEFT JOIN t_pitch p ON p.game_id = x.game_id AND p.player_id = x.player_id
        """
    )
    conn.execute("CREATE INDEX temp.t_lg_ix ON t_lg(player_id, season)")
    stats = {}
    stats["league_appearances"] = conn.execute("SELECT COUNT(*) FROM t_lg").fetchone()[0]
    stats["excluded_onpitch_club_not_in_game"] = conn.execute("SELECT COUNT(*) FROM t_lg WHERE side_ok = 0").fetchone()[0]
    stats["excluded_onpitch_sub_without_in_event"] = conn.execute(
        "SELECT COUNT(*) FROM t_lg WHERE side_ok = 1 AND inn IS NULL").fetchone()[0]
    return stats


def _build_player_season_rows(conn: sqlite3.Connection, sj: str) -> int:
    conn.execute(
        """
        CREATE TEMP TABLE t_ps AS
        SELECT player_id, season, COUNT(*) AS apps, SUM(is_start) AS starts, SUM(minutes) AS minutes,
               SUM(goals) AS goals, SUM(assists) AS assists, SUM(yc) AS yc, SUM(rc) AS rc,
               SUM(CASE WHEN ok_on = 1 THEN gf ELSE 0 END) AS gf,
               SUM(CASE WHEN ok_on = 1 THEN ga ELSE 0 END) AS ga,
               SUM(CASE WHEN is_start = 1 AND ok_on = 1 AND out_min IS NULL AND ga = 0 THEN 1 ELSE 0 END) AS cs
        FROM t_lg GROUP BY player_id, season
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_ps_ix ON t_ps(player_id, season)")
    # 주 소속 구단: 출전 시간 최대 → 출전 수 → club_id 작은 쪽
    conn.execute(
        """
        CREATE TEMP TABLE t_main AS
        SELECT player_id, season, club_id FROM (
            SELECT player_id, season, club_id,
                   ROW_NUMBER() OVER (PARTITION BY player_id, season
                                      ORDER BY SUM(minutes) DESC, COUNT(*) DESC, club_id ASC) AS rn
            FROM t_lg GROUP BY player_id, season, club_id)
        WHERE rn = 1
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_main_ix ON t_main(player_id, season)")
    conn.execute(
        """
        CREATE TEMP TABLE t_team AS
        SELECT club_id, season, COUNT(*) AS n FROM (
            SELECT g.home_club_id AS club_id, g.season FROM game g
              JOIN competition c ON c.competition_id = g.competition_id AND c.is_covered = 1
             WHERE g.season IN (SELECT value FROM json_each(?))
            UNION ALL
            SELECT g.away_club_id, g.season FROM game g
              JOIN competition c ON c.competition_id = g.competition_id AND c.is_covered = 1
             WHERE g.season IN (SELECT value FROM json_each(?)))
        GROUP BY club_id, season
        """,
        (sj, sj),
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_team_ix ON t_team(club_id, season)")
    conn.execute(
        "CREATE TEMP TABLE t_uefa AS SELECT player_id, season, SUM(minutes) AS minutes "
        "FROM t_app WHERE is_uefa_club = 1 GROUP BY player_id, season"
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_uefa_ix ON t_uefa(player_id, season)")
    conn.execute(
        """
        CREATE TEMP TABLE t_str AS
        SELECT l.player_id, l.season, SUM(l.minutes * s.avg_player_value_eur) * 1.0 / SUM(l.minutes) AS strength
        FROM (SELECT player_id, season, competition_id, SUM(minutes) AS minutes FROM t_lg
              GROUP BY player_id, season, competition_id) l
        JOIN competition_season_strength s ON s.competition_id = l.competition_id AND s.season = l.season
        GROUP BY l.player_id, l.season
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.t_str_ix ON t_str(player_id, season)")
    cur = conn.execute(
        """
        INSERT INTO player_season
            (player_id, season, age, pos_group, main_club_id, league_apps, league_starts, league_minutes,
             team_league_games, goals, assists, yellow_cards, red_cards, onpitch_gf, onpitch_ga,
             clean_sheets, uefa_minutes, comp_strength_eur)
        SELECT q.player_id, q.season, q.age, q.pos_group, m.club_id, q.apps, q.starts, q.minutes,
               COALESCE(tm.n, q.apps), q.goals, q.assists, q.yc, q.rc, q.gf, q.ga, q.cs,
               COALESCE(u.minutes, 0), COALESCE(st.strength, 0)
        FROM (
            SELECT ps.*, p.pos_group,
                   CAST((julianday(ps.season || '-07-01') - julianday(p.date_of_birth)) / 365.25 AS INTEGER) AS age
            FROM t_ps ps
            JOIN player p ON p.player_id = ps.player_id
             AND p.date_of_birth IS NOT NULL AND p.pos_group IS NOT NULL
        ) q
        JOIN t_main m ON m.player_id = q.player_id AND m.season = q.season
        LEFT JOIN t_team tm ON tm.club_id = m.club_id AND tm.season = q.season
        LEFT JOIN t_uefa u ON u.player_id = q.player_id AND u.season = q.season
        LEFT JOIN t_str st ON st.player_id = q.player_id AND st.season = q.season
        WHERE q.age BETWEEN 14 AND 45
        """
    )
    return cur.rowcount


def _build_metrics(conn: sqlite3.Connection, sj: str) -> int:
    """db/reference_data.sql 의 metric.description 공식. min_minutes 미만이면 행을 만들지 않는다."""
    cur = conn.execute(
        """
        INSERT INTO player_season_metric (player_id, season, metric_code, value)
        SELECT player_id, season, metric_code, value FROM (
            SELECT ps.player_id, ps.season, m.metric_code,
                   CASE m.metric_code
                     WHEN 'minutes_share'    THEN MIN(1.0, ps.league_minutes * 1.0 / (ps.team_league_games * 90.0))
                     WHEN 'start_rate'       THEN MIN(1.0, ps.league_starts * 1.0 / ps.team_league_games)
                     WHEN 'goals_per90'      THEN ps.goals * 90.0 / ps.league_minutes
                     WHEN 'assists_per90'    THEN ps.assists * 90.0 / ps.league_minutes
                     WHEN 'ga_per90'         THEN (ps.goals + ps.assists) * 90.0 / ps.league_minutes
                     WHEN 'onpitch_gd_per90' THEN (ps.onpitch_gf - ps.onpitch_ga) * 90.0 / ps.league_minutes
                     WHEN 'onpitch_ga_per90' THEN ps.onpitch_ga * 90.0 / ps.league_minutes
                     WHEN 'clean_sheet_rate' THEN CASE WHEN ps.league_starts > 0
                                                       THEN ps.clean_sheets * 1.0 / ps.league_starts END
                     WHEN 'cards_per90'      THEN (ps.yellow_cards + 3 * ps.red_cards) * 90.0 / ps.league_minutes
                     WHEN 'comp_strength'    THEN log10(ps.comp_strength_eur + 1)
                     WHEN 'uefa_minutes'     THEN ln(1 + ps.uefa_minutes)
                   END AS value
            FROM player_season ps
            JOIN metric m ON ps.league_minutes >= m.min_minutes
            WHERE ps.season IN (SELECT value FROM json_each(?))
        ) WHERE value IS NOT NULL
        """,
        (sj,),
    )
    return cur.rowcount


def build_player_season(conn: sqlite3.Connection, seasons: Sequence[int] | None = None) -> int:
    """player_season + player_season_metric 계산. None=2012~2025 전체, 지정 시 해당 시즌만 삭제 후 재계산.

    반환값은 저장한 player_season 행 수. 재계산한 시즌의 player_season_z는 함께 지워진다(스냅샷 재빌드 필요).
    """
    sj = _seasons_json(conn, seasons)
    if conn.execute("SELECT COUNT(*) FROM json_each(?)", (sj,)).fetchone()[0] == 0:
        return 0
    # 필요한 시즌의 리그 수준이 없으면 먼저 만든다
    missing = [s for (s,) in conn.execute(
        "SELECT value FROM json_each(?) WHERE value NOT IN (SELECT season FROM competition_season_strength)", (sj,))]
    if missing:
        build_competition_strength(conn, missing)
    # 자식 테이블 cascade(z는 (player_id, season) 인덱스가 없다)를 피하려고 FK를 잠시 끄고 수동으로 지운다
    fk_was_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    toggled = bool(fk_was_on) and not conn.in_transaction
    if toggled:
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with transaction(conn):
            try:
                conn.execute("DELETE FROM player_season_z WHERE season IN (SELECT value FROM json_each(?))", (sj,))
                conn.execute("DELETE FROM player_season_metric WHERE season IN (SELECT value FROM json_each(?))", (sj,))
                conn.execute("DELETE FROM player_season WHERE season IN (SELECT value FROM json_each(?))", (sj,))
                stats = _build_temp_facts(conn, sj)
                n = _build_player_season_rows(conn, sj)
                stats["player_season_rows"] = n
                stats["player_season_metric_rows"] = _build_metrics(conn, sj)
                LAST_BUILD_STATS.clear()
                LAST_BUILD_STATS.update(stats)
            finally:
                _drop_temp(conn)
    finally:
        if toggled:
            conn.execute("PRAGMA foreign_keys = ON")
    return n


# ---------------------------------------------------------------- snapshot
def create_snapshot(conn: sqlite3.Connection, name: str, as_of_date: str) -> int:
    """이름이 이미 있으면 기존 id 반환(as_of가 다르면 ValueError)."""
    with transaction(conn):
        row = conn.execute("SELECT snapshot_id, as_of_date FROM snapshot WHERE name = ?", (name,)).fetchone()
        if row is not None:
            if row["as_of_date"] != as_of_date:
                raise ValueError(f"snapshot {name!r} 은 이미 as_of={row['as_of_date']} 로 존재한다 (요청: {as_of_date})")
            return row["snapshot_id"]
        cur = conn.execute("INSERT INTO snapshot (name, as_of_date) VALUES (?, ?)", (name, as_of_date))
        return cur.lastrowid


def _snapshot_as_of(conn: sqlite3.Connection, snapshot_id: int) -> str:
    row = conn.execute("SELECT as_of_date FROM snapshot WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise ValueError(f"snapshot_id={snapshot_id} 없음")
    return row[0]


def _build_baseline(conn: sqlite3.Connection, snapshot_id: int, as_of: str) -> int:
    # 모평균·모표준편차: 평균을 먼저 구한 뒤 편차 제곱합으로 분산을 계산한다(동일 값 코호트의 잡음 방지).
    cur = conn.execute(
        """
        INSERT INTO cohort_baseline (snapshot_id, pos_group, age, metric_code, mean, std, n)
        WITH x AS (
            SELECT ps.pos_group, ps.age, psm.metric_code, psm.value,
                   AVG(psm.value) OVER (PARTITION BY ps.pos_group, ps.age, psm.metric_code) AS mu
            FROM player_season_metric psm
            JOIN player_season ps ON ps.player_id = psm.player_id AND ps.season = psm.season
            WHERE date((ps.season + 1) || '-06-30') < :as_of AND ps.age BETWEEN :amin AND :amax
        )
        SELECT :snap, pos_group, age, metric_code, mu,
               sqrt(SUM((value - mu) * (value - mu)) / COUNT(*)), COUNT(*)
        FROM x
        GROUP BY pos_group, age, metric_code
        """,
        {"snap": snapshot_id, "as_of": as_of, "amin": COHORT_AGE_MIN, "amax": COHORT_AGE_MAX},
    )
    return cur.rowcount


def _build_z(conn: sqlite3.Connection, snapshot_id: int, as_of: str) -> int:
    # CROSS JOIN: 조인 순서를 ps → psm → m → cb 로 고정한다(planner가 cb 를 바깥 루프로 두면 지표 전체를 880번 훑는다).
    cur = conn.execute(
        """
        INSERT INTO player_season_z (snapshot_id, player_id, season, pos_group, age, metric_code, z)
        SELECT :snap, ps.player_id, ps.season, ps.pos_group, ps.age, psm.metric_code,
               MAX(-:clip, MIN(:clip,
                   CASE WHEN m.higher_is_better = 1 THEN 1.0 ELSE -1.0 END * (psm.value - cb.mean) / cb.std)) + 0.0
        FROM player_season ps
        CROSS JOIN player_season_metric psm ON psm.player_id = ps.player_id AND psm.season = ps.season
        CROSS JOIN metric m ON m.metric_code = psm.metric_code
        CROSS JOIN cohort_baseline cb ON cb.snapshot_id = :snap AND cb.pos_group = ps.pos_group AND cb.age = ps.age
                               AND cb.metric_code = psm.metric_code
        WHERE date((ps.season + 1) || '-06-30') < :as_of AND cb.n >= :minn AND cb.std > :eps
        """,
        {"snap": snapshot_id, "as_of": as_of, "clip": Z_CLIP, "minn": MIN_COHORT_N, "eps": EPS_STD},
    )
    return cur.rowcount


def _label_peak_value(conn: sqlite3.Connection, snapshot_id: int, as_of: str, d: sqlite3.Row) -> int:
    cur = conn.execute(
        """
        INSERT INTO world_class_label (snapshot_id, def_id, player_id, is_world_class, achieved_on)
        SELECT :snap, :def, p.player_id, CASE WHEN a.achieved IS NULL THEN 0 ELSE 1 END, a.achieved
        FROM player p
        LEFT JOIN (
            SELECT v.player_id, MIN(v.date) AS achieved
            FROM player_valuation v JOIN player p2 ON p2.player_id = v.player_id
            WHERE v.date < :as_of
              AND v.market_value_eur >= CASE p2.pos_group WHEN 'GK' THEN :gk ELSE :thr END
            GROUP BY v.player_id
        ) a ON a.player_id = p.player_id
        WHERE p.pos_group IS NOT NULL
        """,
        {"snap": snapshot_id, "def": d["def_id"], "as_of": as_of,
         "gk": d["gk_value_threshold_eur"], "thr": d["value_threshold_eur"]},
    )
    return cur.rowcount


def _label_big5_regular(conn: sqlite3.Connection, snapshot_id: int, as_of: str, d: sqlite3.Row) -> int:
    cur = conn.execute(
        """
        INSERT INTO world_class_label (snapshot_id, def_id, player_id, is_world_class, achieved_on)
        WITH per AS (
            SELECT a.player_id, g.season,
                   SUM(CASE WHEN c.is_big5 = 1 THEN a.minutes_played ELSE 0 END) AS b5,
                   SUM(CASE WHEN g.competition_id = 'CL' THEN a.minutes_played ELSE 0 END) AS cl
            FROM appearance a
            JOIN game g ON g.game_id = a.game_id
            JOIN competition c ON c.competition_id = g.competition_id
            WHERE (c.is_big5 = 1 OR g.competition_id = 'CL') AND date((g.season + 1) || '-06-30') < :as_of
            GROUP BY a.player_id, g.season
        ), cum AS (
            SELECT player_id, season,
                   SUM(CASE WHEN b5 >= :minl THEN 1 ELSE 0 END) OVER w AS n_seasons,
                   SUM(cl) OVER w AS cl_total
            FROM per
            WINDOW w AS (PARTITION BY player_id ORDER BY season)
        ), ach AS (
            SELECT player_id, MIN(season) AS season FROM cum
            WHERE n_seasons >= :mins AND cl_total >= :mincl
            GROUP BY player_id
        )
        SELECT :snap, :def, p.player_id, CASE WHEN ach.season IS NULL THEN 0 ELSE 1 END,
               CASE WHEN ach.season IS NULL THEN NULL ELSE date((ach.season + 1) || '-06-30') END
        FROM player p LEFT JOIN ach ON ach.player_id = p.player_id
        WHERE p.pos_group IS NOT NULL
        """,
        {"snap": snapshot_id, "def": d["def_id"], "as_of": as_of, "minl": d["min_league_minutes"],
         "mins": d["min_seasons"], "mincl": d["min_cl_minutes"]},
    )
    return cur.rowcount


_LABEL_BUILDERS = {"peak_value": _label_peak_value, "big5_regular": _label_big5_regular}


def _build_labels_tx(conn: sqlite3.Connection, snapshot_id: int, def_id: int | None) -> int:
    as_of = _snapshot_as_of(conn, snapshot_id)
    if def_id is None:
        defs = conn.execute("SELECT * FROM world_class_definition ORDER BY def_id").fetchall()
        conn.execute("DELETE FROM world_class_label WHERE snapshot_id = ?", (snapshot_id,))
    else:
        defs = conn.execute("SELECT * FROM world_class_definition WHERE def_id = ?", (def_id,)).fetchall()
        if not defs:
            raise ValueError(f"def_id={def_id} 없음")
        conn.execute("DELETE FROM world_class_label WHERE snapshot_id = ? AND def_id = ?", (snapshot_id, def_id))
    return sum(_LABEL_BUILDERS[d["rule_type"]](conn, snapshot_id, as_of, d) for d in defs)


def build_labels(conn: sqlite3.Connection, snapshot_id: int, def_id: int | None = None) -> int:
    """월드클래스 라벨 재계산(정의 수정 후). def_id=None이면 모든 정의. 저장한 행 수 반환."""
    with transaction(conn):
        return _build_labels_tx(conn, snapshot_id, def_id)


def build_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> dict:
    """하나의 트랜잭션에서 기존 행을 지우고 baseline, z, label을 다시 계산한 뒤 built_at을 갱신한다."""
    with transaction(conn):
        as_of = _snapshot_as_of(conn, snapshot_id)
        conn.execute("DELETE FROM player_season_z WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM cohort_baseline WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("UPDATE snapshot SET built_at = NULL WHERE snapshot_id = ?", (snapshot_id,))
        n_base = _build_baseline(conn, snapshot_id, as_of)
        n_z = _build_z(conn, snapshot_id, as_of)
        n_lab = _build_labels_tx(conn, snapshot_id, None)
        conn.execute("UPDATE snapshot SET built_at = datetime('now') WHERE snapshot_id = ?", (snapshot_id,))
        built_at = conn.execute("SELECT built_at FROM snapshot WHERE snapshot_id = ?", (snapshot_id,)).fetchone()[0]
    return {"snapshot_id": snapshot_id, "as_of_date": as_of, "baseline": n_base, "z": n_z,
            "labels": n_lab, "built_at": built_at}
