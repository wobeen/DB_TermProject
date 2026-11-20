"""원천 경로(B1/B2) 질의: 파생 테이블(player_season*, cohort_baseline, world_class_label)을 쓰지 않고
CONTRACT §3.2~3.3 공식을 CTE로 매번 원천 테이블(appearance, game, game_event, game_lineup, player,
player_valuation)에서 직접 계산한다.

예외(두 경로 공통 입력으로 취급): `competition_season_strength`(리그×시즌 14×14행의 작은 참조 집계)와
`metric`, `metric_weight`, `world_class_definition`(기준 데이터).

계산 범위를 질의가 필요로 하는 (선수, 시즌) 집합으로 좁힌다(pairs CTE).
  Q1  : 한 선수의 전 시즌
  Q2/Q3: 같은 포지션군 · 같은 나이 코호트의 전 시즌(코호트 통계가 필요하므로)
"""

from __future__ import annotations

import math
import sqlite3

# ----------------------------------------------------------------------------
# 공통: pairs → 출전 사실 → player_season → metric
# <SELECTOR> 자리에는 pairs 선택 조건 SQL 조각(고정 문자열)이 들어간다. 값은 전부 :name 바인딩.
# ----------------------------------------------------------------------------
_FACTS = """
seasons(season) AS (
    SELECT 2012 UNION ALL SELECT season + 1 FROM seasons WHERE season < 2025
),
vis AS (SELECT season FROM seasons WHERE date((season + 1) || '-06-30') < :as_of),
pairs AS MATERIALIZED (
    SELECT p.player_id, p.pos_group, vis.season,
           CAST((julianday(vis.season || '-07-01') - julianday(p.date_of_birth)) / 365.25 AS INTEGER) AS age
    FROM vis JOIN player p
    WHERE p.date_of_birth IS NOT NULL AND p.pos_group IS NOT NULL
      AND <SELECTOR>
),
pairs_ok AS MATERIALIZED (SELECT * FROM pairs WHERE age BETWEEN 14 AND 45 AND <AGEFILTER>),
app AS MATERIALIZED (
    SELECT a.game_id, a.player_id, g.season, g.competition_id, a.club_id, g.home_club_id, g.away_club_id,
           a.minutes_played AS minutes, a.goals, a.assists, a.yellow_cards AS yc, a.red_cards AS rc,
           c.is_covered, c.is_uefa_club
    FROM pairs_ok pr
    <APPJOIN> appearance a ON a.player_id = pr.player_id
    JOIN game g ON g.game_id = a.game_id AND g.season = pr.season
    JOIN competition c ON c.competition_id = g.competition_id
    WHERE a.minutes_played >= 1 AND (c.is_covered = 1 OR c.is_uefa_club = 1)
),
ev_in AS MATERIALIZED (
    SELECT e.game_id, e.player_in_id AS player_id,
           MIN(CASE WHEN e.minute >= 0 THEN e.minute END) AS in_min
    FROM (SELECT DISTINCT game_id, player_id FROM app WHERE is_covered = 1) x
    JOIN game_event e ON e.game_id = x.game_id AND e.player_in_id = x.player_id
    WHERE e.type = 'Substitutions'
    GROUP BY e.game_id, e.player_in_id
),
ev_out AS MATERIALIZED (
    SELECT game_id, player_id, MIN(minute) AS out_min FROM (
        SELECT e.game_id, e.player_id, e.minute
        FROM (SELECT DISTINCT game_id, player_id FROM app WHERE is_covered = 1) x
        JOIN game_event e ON e.game_id = x.game_id AND e.player_id = x.player_id
        WHERE e.type = 'Substitutions' AND e.minute >= 0
        UNION ALL
        SELECT e.game_id, e.player_id, e.minute
        FROM (SELECT DISTINCT game_id, player_id FROM app WHERE is_covered = 1) x
        JOIN game_event e ON e.game_id = x.game_id AND e.player_id = x.player_id
        WHERE e.is_sending_off = 1 AND e.minute >= 0
    ) GROUP BY game_id, player_id
),
lg0 AS MATERIALIZED (
    SELECT x.*,
           CASE WHEN l.player_id IS NOT NULL THEN l.is_starter
                WHEN ei.player_id IS NULL THEN 1 ELSE 0 END AS is_start,
           ei.in_min, eo.out_min,
           CASE WHEN x.club_id IN (x.home_club_id, x.away_club_id) THEN 1 ELSE 0 END AS side_ok
    FROM app x
    LEFT JOIN game_lineup l ON l.game_id = x.game_id AND l.player_id = x.player_id
    LEFT JOIN ev_in ei ON ei.game_id = x.game_id AND ei.player_id = x.player_id
    LEFT JOIN ev_out eo ON eo.game_id = x.game_id AND eo.player_id = x.player_id
    WHERE x.is_covered = 1
),
lg1 AS MATERIALIZED (
    SELECT *, CASE WHEN is_start = 1 THEN 0 ELSE in_min END AS inn FROM lg0
),
pitch AS MATERIALIZED (
    SELECT x.game_id, x.player_id,
           COALESCE(SUM(CASE WHEN gl.club_id = x.club_id THEN 1 END), 0) AS gf,
           COALESCE(SUM(CASE WHEN gl.club_id <> x.club_id THEN 1 END), 0) AS ga
    FROM lg1 x
    JOIN game_event gl ON gl.game_id = x.game_id AND gl.type = 'Goals'
    WHERE x.side_ok = 1 AND x.inn IS NOT NULL
      AND gl.club_id IN (x.home_club_id, x.away_club_id)
      AND ((gl.minute = -1 AND x.inn = 0 AND x.out_min IS NULL)
           OR (gl.minute >= 0 AND gl.minute > x.inn AND gl.minute <= COALESCE(x.out_min, 1000000)))
    GROUP BY x.game_id, x.player_id
),
lg AS MATERIALIZED (
    SELECT x.*, COALESCE(p.gf, 0) AS gf, COALESCE(p.ga, 0) AS ga,
           CASE WHEN x.side_ok = 1 AND x.inn IS NOT NULL THEN 1 ELSE 0 END AS ok_on
    FROM lg1 x LEFT JOIN pitch p ON p.game_id = x.game_id AND p.player_id = x.player_id
),
agg AS MATERIALIZED (
    SELECT player_id, season, COUNT(*) AS apps, SUM(is_start) AS starts, SUM(minutes) AS minutes,
           SUM(goals) AS goals, SUM(assists) AS assists, SUM(yc) AS yc, SUM(rc) AS rc,
           SUM(CASE WHEN ok_on = 1 THEN gf ELSE 0 END) AS gf,
           SUM(CASE WHEN ok_on = 1 THEN ga ELSE 0 END) AS ga,
           SUM(CASE WHEN is_start = 1 AND ok_on = 1 AND out_min IS NULL AND ga = 0 THEN 1 ELSE 0 END) AS cs
    FROM lg GROUP BY player_id, season
),
mainclub AS MATERIALIZED (
    SELECT player_id, season, club_id FROM (
        SELECT player_id, season, club_id,
               ROW_NUMBER() OVER (PARTITION BY player_id, season
                                  ORDER BY SUM(minutes) DESC, COUNT(*) DESC, club_id ASC) AS rn
        FROM lg GROUP BY player_id, season, club_id)
    WHERE rn = 1
),
team AS MATERIALIZED (
    SELECT m.club_id, m.season, COUNT(*) AS n
    FROM (SELECT DISTINCT club_id, season FROM mainclub) m
    JOIN game g ON g.season = m.season AND (g.home_club_id = m.club_id OR g.away_club_id = m.club_id)
    JOIN competition c ON c.competition_id = g.competition_id AND c.is_covered = 1
    GROUP BY m.club_id, m.season
),
uefa AS MATERIALIZED (
    SELECT player_id, season, SUM(minutes) AS minutes FROM app WHERE is_uefa_club = 1 GROUP BY player_id, season
),
strength AS MATERIALIZED (
    SELECT l.player_id, l.season, SUM(l.minutes * s.avg_player_value_eur) * 1.0 / SUM(l.minutes) AS strength
    FROM (SELECT player_id, season, competition_id, SUM(minutes) AS minutes FROM lg
          GROUP BY player_id, season, competition_id) l
    JOIN competition_season_strength s ON s.competition_id = l.competition_id AND s.season = l.season
    GROUP BY l.player_id, l.season
),
ps AS MATERIALIZED (
    SELECT q.player_id, q.season, q.age, q.pos_group, m.club_id AS main_club_id, q.apps AS league_apps,
           q.starts AS league_starts, q.minutes AS league_minutes, COALESCE(tm.n, q.apps) AS team_league_games,
           q.goals, q.assists, q.yc AS yellow_cards, q.rc AS red_cards, q.gf AS onpitch_gf, q.ga AS onpitch_ga,
           q.cs AS clean_sheets, COALESCE(u.minutes, 0) AS uefa_minutes, COALESCE(st.strength, 0) AS comp_strength_eur
    FROM (SELECT a.*, pr.pos_group, pr.age FROM agg a
          JOIN pairs_ok pr ON pr.player_id = a.player_id AND pr.season = a.season) q
    JOIN mainclub m ON m.player_id = q.player_id AND m.season = q.season
    LEFT JOIN team tm ON tm.club_id = m.club_id AND tm.season = q.season
    LEFT JOIN uefa u ON u.player_id = q.player_id AND u.season = q.season
    LEFT JOIN strength st ON st.player_id = q.player_id AND st.season = q.season
),
psm AS MATERIALIZED (
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
        FROM ps JOIN metric m ON ps.league_minutes >= m.min_minutes
    ) WHERE value IS NOT NULL
)
"""

# 선택자 조각 (고정 문자열)
_SEL_PLAYER = "p.player_id = :pid"
_AGE_ANY = "1 = 1"
# 코호트: 같은 포지션군 + (시즌, 나이)가 :age. dob 범위는 ix_player_posgroup_dob 를 쓰기 위한 느슨한 사전 필터이고
# 정확한 나이 조건은 age = :age 로 다시 건다.
_SEL_COHORT = (
    "p.pos_group = :pos"
    " AND p.date_of_birth > date(vis.season || '-07-01', '-' || ((:age + 1) * 366) || ' days')"
    " AND p.date_of_birth <= date(vis.season || '-07-01', '-' || (:age * 365) || ' days')"
)
_AGE_EXACT = "age = :age"


def _facts(selector: str, agefilter: str, appjoin: str = "JOIN") -> str:
    # appjoin: Q1(한 선수)은 CROSS JOIN 으로 조인 순서를 고정(선수 → 출전, B2는 ix_appearance_player_date 사용).
    # 코호트 질의(Q2/Q3)는 플래너에 맡긴다(순서를 고정하면 오히려 느려짐).
    return _FACTS.replace("<SELECTOR>", selector).replace("<AGEFILTER>", agefilter).replace("<APPJOIN>", appjoin)


# ----------------------------------------------------------------------------
# Q1 시즌별 성장표
# ----------------------------------------------------------------------------
Q1_SQL = "WITH RECURSIVE " + _facts(_SEL_PLAYER, _AGE_ANY, "CROSS JOIN") + """
SELECT ps.*, c.name AS club_name, psm.metric_code, psm.value
FROM ps
JOIN club c ON c.club_id = ps.main_club_id
LEFT JOIN psm ON psm.player_id = ps.player_id AND psm.season = ps.season
ORDER BY ps.season
"""


def q1_raw(conn: sqlite3.Connection, player_id: int) -> list[dict]:
    """services.players.season_history 와 같은 형태(행당 dict, 지표는 m_<code> 키)를 돌려준다."""
    by: dict[int, dict] = {}
    for r in conn.execute(Q1_SQL, {"pid": player_id, "as_of": "9999-12-31"}):
        d = dict(r)
        code, val = d.pop("metric_code"), d.pop("value")
        row = by.setdefault(d["season"], d)
        if code is not None:
            row["m_" + code] = val
    return [by[s] for s in sorted(by)]


# ----------------------------------------------------------------------------
# Q2 동나이대 백분위 (스냅샷 as_of 기준 코호트)
# ----------------------------------------------------------------------------
Q2_SQL = "WITH RECURSIVE " + _facts(_SEL_COHORT, _AGE_EXACT) + """
SELECT m.metric_code, m.name_ko, m.higher_is_better, b.value AS value,
       COUNT(*) AS n,
       COALESCE(SUM(c.value < b.value), 0) AS below,
       COALESCE(SUM(c.value = b.value), 0) AS equal
FROM psm b
JOIN metric m ON m.metric_code = b.metric_code
JOIN psm c ON c.metric_code = b.metric_code
WHERE b.player_id = :pid AND b.season = :L
GROUP BY m.metric_code, m.name_ko, m.higher_is_better, b.value
ORDER BY m.metric_code
"""


def q2_raw(conn: sqlite3.Connection, *, as_of: str, player_id: int, season: int, pos_group: str, age: int) -> list[dict]:
    out = []
    for r in conn.execute(
        Q2_SQL, {"as_of": as_of, "pid": player_id, "L": season, "pos": pos_group, "age": age}
    ):
        pct = 100.0 * (r["below"] + 0.5 * r["equal"]) / r["n"]
        if not r["higher_is_better"]:
            pct = 100.0 - pct
        out.append({"metric_code": r["metric_code"], "name_ko": r["name_ko"], "value": r["value"],
                    "percentile": pct, "cohort_n": r["n"]})
    return out


# ----------------------------------------------------------------------------
# Q3 유사 선수 k-NN (+ 이웃의 월클 라벨도 원천에서 계산)
# ----------------------------------------------------------------------------
_Q3_TAIL = """,
base AS (
    SELECT metric_code, AVG(value) AS mu, COUNT(*) AS n FROM psm JOIN ps USING (player_id, season)
    WHERE ps.age BETWEEN 16 AND 35 GROUP BY metric_code
),
sd AS (
    SELECT x.metric_code, b.mu, b.n, sqrt(SUM((x.value - b.mu) * (x.value - b.mu)) / COUNT(*)) AS std
    FROM psm x JOIN ps USING (player_id, season) JOIN base b ON b.metric_code = x.metric_code
    WHERE ps.age BETWEEN 16 AND 35 GROUP BY x.metric_code
),
z AS MATERIALIZED (
    SELECT psm.player_id, psm.season, psm.metric_code,
           MAX(-4.0, MIN(4.0, CASE WHEN m.higher_is_better = 1 THEN 1.0 ELSE -1.0 END
                              * (psm.value - sd.mu) / sd.std)) + 0.0 AS z
    FROM psm JOIN ps USING (player_id, season)
    JOIN metric m ON m.metric_code = psm.metric_code
    JOIN sd ON sd.metric_code = psm.metric_code
    WHERE ps.age BETWEEN 16 AND 35 AND sd.n >= 20 AND sd.std > 1e-12
),
w AS (SELECT metric_code, weight FROM metric_weight WHERE pos_group = :pos),
cv AS (
    SELECT z.metric_code, z.z, w.weight FROM z JOIN w ON w.metric_code = z.metric_code
    WHERE z.player_id = :pid AND z.season = :L
),
ctot AS (SELECT SUM(weight) AS tw FROM cv),
pairs2 AS (
    SELECT pz.player_id AS nb_id, pz.season AS nb_season,
           SUM(cv.weight * (cv.z - pz.z) * (cv.z - pz.z)) AS wss, SUM(cv.weight) AS sw
    FROM cv JOIN z pz ON pz.metric_code = cv.metric_code
    WHERE pz.player_id <> :pid AND pz.season <= :pool_max
    GROUP BY pz.player_id, pz.season
),
ranked AS MATERIALIZED (
    SELECT p.nb_id, p.nb_season, p.wss / p.sw AS d2,
           ROW_NUMBER() OVER (ORDER BY p.wss / p.sw, p.nb_id, p.nb_season) AS rn
    FROM pairs2 p, ctot t WHERE p.sw * 10 >= t.tw * 6
),
top AS MATERIALIZED (SELECT * FROM ranked WHERE rn <= :k),
<WC>
SELECT t.nb_id, t.nb_season, t.d2, t.rn, COALESCE(wc.is_wc, 0) AS is_wc,
       p.name, s.age, c.name AS club_name
FROM top t
LEFT JOIN wc ON wc.player_id = t.nb_id
JOIN player p ON p.player_id = t.nb_id
JOIN ps_nb s ON s.player_id = t.nb_id AND s.season = t.nb_season
JOIN club c ON c.club_id = s.main_club_id
ORDER BY t.rn
"""

# 월클 라벨(§3.3)을 이웃 k명에 대해서만 원천에서 계산
_WC_PEAK = """
wc AS (
    SELECT t.nb_id AS player_id,
           CASE WHEN EXISTS (
               SELECT 1 FROM player_valuation v JOIN player pl ON pl.player_id = v.player_id
               WHERE v.player_id = t.nb_id AND v.date < :as_of
                 AND v.market_value_eur >= CASE pl.pos_group WHEN 'GK' THEN :gk ELSE :thr END
           ) THEN 1 ELSE 0 END AS is_wc
    FROM top t
)"""
_WC_BIG5 = """
wc AS (
    WITH nbs AS MATERIALIZED (SELECT DISTINCT nb_id FROM top),
    per AS MATERIALIZED (
        SELECT a.player_id, g.season,
               SUM(CASE WHEN c.is_big5 = 1 THEN a.minutes_played ELSE 0 END) AS b5,
               SUM(CASE WHEN g.competition_id = 'CL' THEN a.minutes_played ELSE 0 END) AS cl
        FROM nbs t
        CROSS JOIN appearance a ON a.player_id = t.nb_id
        JOIN game g ON g.game_id = a.game_id
        JOIN competition c ON c.competition_id = g.competition_id
        WHERE (c.is_big5 = 1 OR g.competition_id = 'CL') AND date((g.season + 1) || '-06-30') < :as_of
        GROUP BY a.player_id, g.season
    ), cum AS (
        SELECT player_id, season,
               SUM(CASE WHEN b5 >= :minl THEN 1 ELSE 0 END) OVER w AS n_seasons,
               SUM(cl) OVER w AS cl_total
        FROM per WINDOW w AS (PARTITION BY player_id ORDER BY season)
    ), hit AS (
        SELECT DISTINCT player_id FROM cum WHERE n_seasons >= :mins AND cl_total >= :mincl
    )
    SELECT t.nb_id AS player_id, CASE WHEN h.player_id IS NOT NULL THEN 1 ELSE 0 END AS is_wc
    FROM nbs t LEFT JOIN hit h ON h.player_id = t.nb_id
)"""

# 이웃의 (선수, 시즌) 정보(이름/나이/구단)는 이웃 시즌의 ps 행에서 가져온다. z 풀이 이미 ps 이므로 그대로 재사용.
_PS_NB = ",\nps_nb AS (SELECT player_id, season, age, main_club_id FROM ps)"


def _q3_sql(rule_type: str) -> str:
    wc = {"peak_value": _WC_PEAK, "big5_regular": _WC_BIG5}[rule_type]
    return "WITH RECURSIVE " + _facts(_SEL_COHORT, _AGE_EXACT) + _PS_NB + _Q3_TAIL.replace("<WC>", wc)


_Q3_SQL = {rt: _q3_sql(rt) for rt in ("peak_value", "big5_regular")}


def q3_raw(conn: sqlite3.Connection, *, as_of: str, player_id: int, season: int, pos_group: str, age: int,
           def_id: int, k: int = 10, pool_max_season: int = 9999) -> list[dict]:
    d = conn.execute("SELECT * FROM world_class_definition WHERE def_id = ?", (def_id,)).fetchone()
    bind = {"as_of": as_of, "pid": player_id, "L": season, "pos": pos_group, "age": age,
            "k": k, "pool_max": pool_max_season}
    if d["rule_type"] == "peak_value":
        bind.update(gk=d["gk_value_threshold_eur"], thr=d["value_threshold_eur"])
    else:
        bind.update(minl=d["min_league_minutes"], mins=d["min_seasons"], mincl=d["min_cl_minutes"])
    out = []
    for r in conn.execute(_Q3_SQL[d["rule_type"]], bind):
        out.append({"player_id": r["nb_id"], "season": r["nb_season"], "distance": math.sqrt(r["d2"]),
                    "is_wc": int(r["is_wc"]), "name": r["name"], "age": r["age"], "club_name": r["club_name"]})
    return out
