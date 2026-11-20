"""선수 검색·프로필·성장표·시장가치·동나이대 백분위·유사 선수."""

from __future__ import annotations

import json
import sqlite3
import math
from datetime import date

from scouting.services.knn import knn


def _reference_date(conn: sqlite3.Connection) -> str:
    """나이 계산 기준일: 가장 최신 스냅샷의 as_of_date (없으면 오늘)."""
    row = conn.execute("SELECT MAX(as_of_date) FROM snapshot").fetchone()
    return row[0] or date.today().isoformat()


def _age_on(dob: str | None, ref: str) -> int | None:
    if not dob:
        return None
    try:
        b, r = date.fromisoformat(dob), date.fromisoformat(ref)
    except ValueError:
        return None
    return int((r - b).days / 365.25)


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(conn, name, pos_group, max_age, competition_id) -> tuple[str, list]:
    ref = _reference_date(conn)
    where: list[str] = []
    params: list = []
    if name:
        where.append("p.name LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(name.strip())}%")
    if pos_group:
        where.append("p.pos_group = ?")
        params.append(pos_group)
    if max_age is not None:
        # 만 나이 <= max_age  <=>  생일 > ref - (max_age+1)년
        where.append("p.date_of_birth IS NOT NULL AND p.date_of_birth > date(?, ?)")
        params += [ref, f"-{int(max_age) + 1} years"]
    if competition_id:
        where.append("EXISTS (SELECT 1 FROM appearance a WHERE a.player_id = p.player_id AND a.competition_id = ?)")
        params.append(competition_id)
    return (("WHERE " + " AND ".join(where)) if where else ""), params


def count_players(
    conn: sqlite3.Connection,
    *,
    name: str | None = None,
    pos_group: str | None = None,
    max_age: int | None = None,
    competition_id: str | None = None,
) -> int:
    clause, params = _filters(conn, name, pos_group, max_age, competition_id)
    return conn.execute(f"SELECT COUNT(*) FROM player p {clause}", params).fetchone()[0]


def search_players(
    conn: sqlite3.Connection,
    *,
    name: str | None = None,
    pos_group: str | None = None,
    max_age: int | None = None,
    competition_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """정렬: 완전 일치(0) → 성/이름(단어) 접두 일치(1) → 부분 일치(2), 같은 순위는 최고 시장가치 내림차순."""
    ref = _reference_date(conn)
    clause, params = _filters(conn, name, pos_group, max_age, competition_id)
    rank_sql, rank_params = "0", []
    if name and name.strip():
        q = _like_escape(name.strip())
        rank_sql = (
            "CASE WHEN p.name = ? COLLATE NOCASE THEN 0 "
            "WHEN p.name LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\' THEN 1 "
            "ELSE 2 END"
        )
        rank_params = [name.strip(), f"{q}%", f"% {q}%", f"%-{q}%"]
    sql = f"""
        SELECT c.* FROM (
            SELECT p.player_id, {rank_sql} AS rk,
                   COALESCE((SELECT MAX(v.market_value_eur) FROM player_valuation v
                              WHERE v.player_id = p.player_id), -1) AS pk
            FROM player p {clause}
            ORDER BY rk, pk DESC, p.name COLLATE NOCASE, p.player_id LIMIT ? OFFSET ?
        ) s
        JOIN v_player_card c ON c.player_id = s.player_id
        ORDER BY s.rk, s.pk DESC, c.name COLLATE NOCASE, c.player_id
    """  # rank_sql/clause 는 고정 문자열 조각만 조합한다. 값은 전부 ? 바인딩.
    rows = [dict(r) for r in conn.execute(sql, (*rank_params, *params, int(limit), int(offset)))]
    for r in rows:
        r["age"] = _age_on(r["date_of_birth"], ref)
    return rows


def competition_exists(conn: sqlite3.Connection, competition_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM competition WHERE competition_id = ?", (competition_id,)
    ).fetchone() is not None


def player_card(conn: sqlite3.Connection, player_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM v_player_card WHERE player_id = ?", (player_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["age"] = _age_on(d["date_of_birth"], _reference_date(conn))
    return d


def latest_snapshot_season(conn: sqlite3.Connection, snapshot_id: int, player_id: int) -> int | None:
    """선택한 스냅샷에 포함된 선수의 가장 최근 완료 시즌 (GUI/CLI 흐름 보조)."""
    row = conn.execute(
        "SELECT MAX(season) FROM v_player_season_asof WHERE snapshot_id = ? AND player_id = ?",
        (snapshot_id, player_id),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def valuation_by_season(conn: sqlite3.Connection, player_id: int) -> list[dict]:
    """시즌(7/1~다음 해 6/30)별 시장가치 요약: 최고(날짜)·최종(날짜)·건수."""
    by: dict[int, dict] = {}
    for v in valuation_history(conn, player_id):
        y, m = int(v["date"][:4]), int(v["date"][5:7])
        season = y if m >= 7 else y - 1
        e = by.setdefault(season, {"season": season, "peak_eur": -1, "peak_date": None,
                                   "last_eur": None, "last_date": None, "n": 0})
        e["n"] += 1
        if v["market_value_eur"] > e["peak_eur"]:
            e["peak_eur"], e["peak_date"] = v["market_value_eur"], v["date"]
        e["last_eur"], e["last_date"] = v["market_value_eur"], v["date"]  # 날짜 오름차순이므로 마지막이 최종
    return [by[k] for k in sorted(by)]


def season_history(conn: sqlite3.Connection, player_id: int) -> list[dict]:
    """player_season + 지표 값(wide: m_<metric_code> 키)."""
    seasons = [
        dict(r)
        for r in conn.execute(
            """SELECT ps.*, c.name AS club_name
               FROM player_season ps JOIN club c ON c.club_id = ps.main_club_id
               WHERE ps.player_id = ? ORDER BY ps.season""",
            (player_id,),
        )
    ]
    by_season = {s["season"]: s for s in seasons}
    for r in conn.execute(
        "SELECT season, metric_code, value FROM player_season_metric WHERE player_id = ?", (player_id,)
    ):
        by_season[r["season"]]["m_" + r["metric_code"]] = r["value"]
    return seasons


def valuation_history(conn: sqlite3.Connection, player_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT v.date, v.market_value_eur, c.name AS club_name
           FROM player_valuation v LEFT JOIN club c ON c.club_id = v.club_id
           WHERE v.player_id = ? ORDER BY v.date""",
        (player_id,),
    )
    return [dict(r) for r in rows]


def display_value(metric_code: str, value: float) -> tuple[float, str]:
    """로그 변환 지표를 원래 단위로 되돌린다 (z/백분위 계산은 변환값 그대로)."""
    if metric_code == "comp_strength":      # log10(eur + 1) -> 평균 시장가치 €M
        return (10 ** value - 1) / 1_000_000, "€M"
    if metric_code == "uefa_minutes":       # ln(1 + minutes) -> 분
        return math.exp(value) - 1, "분"
    return value, ""


def cohort_percentiles(
    conn: sqlite3.Connection, snapshot_id: int, player_id: int, season: int
) -> list[dict]:
    """같은 스냅샷·포지션군·나이 코호트 안의 백분위(0~100, 클수록 좋음; higher_is_better=0 은 뒤집음)."""
    base = conn.execute(
        """SELECT pos_group, age FROM v_player_season_asof
           WHERE snapshot_id = ? AND player_id = ? AND season = ?""",
        (snapshot_id, player_id, season),
    ).fetchone()
    if base is None:
        return []
    out: list[dict] = []
    weights = {
        r["metric_code"]: r["weight"]
        for r in conn.execute("SELECT metric_code, weight FROM metric_weight WHERE pos_group = ?", (base["pos_group"],))
    }
    metrics = conn.execute(
        """SELECT m.metric_code, m.name_ko, m.higher_is_better, psm.value
           FROM player_season_metric psm JOIN metric m ON m.metric_code = psm.metric_code
           WHERE psm.player_id = ? AND psm.season = ? ORDER BY m.metric_code""",
        (player_id, season),
    ).fetchall()
    metrics = sorted(metrics, key=lambda m: (m["metric_code"] not in weights,
                                             -weights.get(m["metric_code"], 0.0), m["metric_code"]))
    for m in metrics:
        row = conn.execute(
            """SELECT COUNT(*) AS n,
                      COALESCE(SUM(cm.value < ?), 0) AS below,
                      COALESCE(SUM(cm.value = ?), 0) AS equal
               FROM v_player_season_asof c
               JOIN player_season_metric cm
                 ON cm.player_id = c.player_id AND cm.season = c.season AND cm.metric_code = ?
               WHERE c.snapshot_id = ? AND c.pos_group = ? AND c.age = ?""",
            (m["value"], m["value"], m["metric_code"], snapshot_id, base["pos_group"], base["age"]),
        ).fetchone()
        if not row["n"]:
            continue
        pct = 100.0 * (row["below"] + 0.5 * row["equal"]) / row["n"]
        if not m["higher_is_better"]:
            pct = 100.0 - pct
        display = display_value(m["metric_code"], m["value"])
        out.append(
            {
                "metric_code": m["metric_code"],
                "name_ko": m["name_ko"],
                "value": m["value"],
                "display_value": display[0],
                "unit": display[1],
                "weight": weights.get(m["metric_code"]),
                "percentile": pct,
                "cohort_n": row["n"],
            }
        )
    return out


def similar_players(
    conn: sqlite3.Connection,
    snapshot_id: int,
    player_id: int,
    season: int,
    k: int = 10,
    def_id: int | None = None,
) -> list[dict]:
    """같은 나이 비교 풀(스냅샷 내 모든 시즌, 본인 제외)에서 가장 닮은 k명. def_id 를 주면 월클 여부도 표시."""
    base = conn.execute(
        "SELECT pos_group FROM player_season WHERE player_id = ? AND season = ?", (player_id, season)
    ).fetchone()
    if base is None:
        return []
    res = knn(
        conn,
        "SELECT player_id, age FROM player_season WHERE player_id = :cand_pid AND season = :L",
        snapshot_id=snapshot_id,
        base_season=season,
        pos_group=base["pos_group"],
        k=k,
        pool_max_season=9999,
        def_id=def_id,
        params={"cand_pid": player_id},
    ).get(player_id, [])
    out = []
    for n in res:
        info = conn.execute(
            """SELECT p.name, ps.age, c.name AS club_name
               FROM player p
               JOIN player_season ps ON ps.player_id = p.player_id AND ps.season = ?
               JOIN club c ON c.club_id = ps.main_club_id
               WHERE p.player_id = ?""",
            (n["season"], n["player_id"]),
        ).fetchone()
        out.append({**n, "name": info["name"], "age": info["age"], "club_name": info["club_name"]})
    return out


# ---------------------------------------------------------------------------
# 커리어 탐색기용 읽기 전용 서비스 (GUI). 위 함수들은 수정하지 않고 추가만 한다.
# ---------------------------------------------------------------------------

def data_cutoff(conn: sqlite3.Connection) -> dict:
    """데이터 기준일: 경기/출전/시장가치의 최대 날짜와 마지막 경기 시즌(시작 연도)."""
    return {
        "game": conn.execute("SELECT MAX(date) FROM game").fetchone()[0],
        "appearance": conn.execute("SELECT MAX(date) FROM appearance").fetchone()[0],
        "valuation": conn.execute("SELECT MAX(date) FROM player_valuation").fetchone()[0],
        "season": conn.execute("SELECT MAX(season) FROM game").fetchone()[0],
    }


def nationalities(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT country_of_citizenship FROM player "
        "WHERE country_of_citizenship IS NOT NULL AND country_of_citizenship <> '' "
        "ORDER BY country_of_citizenship COLLATE NOCASE"
    )
    return [r[0] for r in rows]


def _filters_ext(conn, name, pos_group, nationality, club_name, min_age, max_age,
                 sub_positions=None, club_ids=None) -> tuple[str, list]:
    where: list[str] = []
    params: list = []
    ref = _reference_date(conn)
    if name and name.strip():
        where.append("p.name LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(name.strip())}%")
    if pos_group:
        where.append("p.pos_group = ?")
        params.append(pos_group)
    if nationality:
        where.append("p.country_of_citizenship = ?")
        params.append(nationality)
    if club_name and club_name.strip():
        like = f"%{_like_escape(club_name.strip())}%"
        ids = "SELECT club_id FROM club WHERE name LIKE ? ESCAPE '\\'"
        where.append(
            f"(p.player_id IN (SELECT a.player_id FROM appearance a WHERE a.club_id IN ({ids})) "
            f"OR p.player_id IN (SELECT t.player_id FROM transfer t WHERE t.from_club_id IN ({ids}) "
            f"OR t.to_club_id IN ({ids})))"
        )
        params += [like, like, like]
    if club_ids:
        # 정확한 구단 id 로 거른다: 그 구단으로/에서 이적했거나 그 구단 소속으로 뛴 선수. id 목록은 JSON 한 개로 바인딩.
        ids = "SELECT value FROM json_each(?)"
        where.append(
            f"(p.player_id IN (SELECT a.player_id FROM appearance a WHERE a.club_id IN ({ids})) "
            f"OR p.player_id IN (SELECT t.player_id FROM transfer t WHERE t.from_club_id IN ({ids}) "
            f"OR t.to_club_id IN ({ids})))")
        blob = json.dumps([int(i) for i in club_ids])
        params += [blob, blob, blob]
    if sub_positions:
        where.append("p.sub_position IN (" + ",".join("?" * len(sub_positions)) + ")")
        params += list(sub_positions)
    if max_age is not None:
        where.append("p.date_of_birth IS NOT NULL AND p.date_of_birth > date(?, ?)")
        params += [ref, f"-{int(max_age) + 1} years"]
    if min_age is not None:
        where.append("p.date_of_birth IS NOT NULL AND p.date_of_birth <= date(?, ?)")
        params += [ref, f"-{int(min_age)} years"]
    return (("WHERE " + " AND ".join(where)) if where else ""), params


def count_players_ext(
    conn: sqlite3.Connection, *, name=None, pos_group=None, nationality=None,
    club_name=None, min_age=None, max_age=None, sub_positions=None, club_ids=None,
) -> int:
    clause, params = _filters_ext(conn, name, pos_group, nationality, club_name, min_age, max_age,
                                  sub_positions, club_ids)
    return conn.execute(f"SELECT COUNT(*) FROM player p {clause}", params).fetchone()[0]


def search_players_ext(
    conn: sqlite3.Connection, *, name=None, pos_group=None, nationality=None, club_name=None,
    min_age=None, max_age=None, limit: int = 20, offset: int = 0, sub_positions=None, club_ids=None,
) -> list[dict]:
    """search_players 와 같은 관련도 정렬(완전 일치 → 단어 접두 → 부분, 최고 시장가치 내림차순) + 국적/출신 구단/나이 하한."""
    ref = _reference_date(conn)
    clause, params = _filters_ext(conn, name, pos_group, nationality, club_name, min_age, max_age,
                                  sub_positions, club_ids)
    rank_sql, rank_params = "0", []
    if name and name.strip():
        q = _like_escape(name.strip())
        rank_sql = (
            "CASE WHEN p.name = ? COLLATE NOCASE THEN 0 "
            "WHEN p.name LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\' THEN 1 "
            "ELSE 2 END"
        )
        rank_params = [name.strip(), f"{q}%", f"% {q}%", f"%-{q}%"]
    sql = f"""
        SELECT c.* FROM (
            SELECT p.player_id, {rank_sql} AS rk,
                   COALESCE((SELECT MAX(v.market_value_eur) FROM player_valuation v
                              WHERE v.player_id = p.player_id), -1) AS pk
            FROM player p {clause}
            ORDER BY rk, pk DESC, p.name COLLATE NOCASE, p.player_id LIMIT ? OFFSET ?
        ) s
        JOIN v_player_card c ON c.player_id = s.player_id
        ORDER BY s.rk, s.pk DESC, c.name COLLATE NOCASE, c.player_id
    """  # 조각은 고정 문자열, 값은 전부 ? 바인딩.
    rows = [dict(r) for r in conn.execute(sql, (*rank_params, *params, int(limit), int(offset)))]
    for r in rows:
        r["age"] = _age_on(r["date_of_birth"], ref)
    return rows


def transfer_history(conn: sqlite3.Connection, player_id: int, *, cutoff: str | None = None) -> list[dict]:
    """이적 이력(유소년 포함), 날짜 오름차순. upcoming=1 이면 데이터 기준일(마지막 경기일) 이후 이적."""
    cutoff = cutoff or data_cutoff(conn)["game"]
    rows = conn.execute(
        """SELECT t.transfer_id, t.transfer_date, t.transfer_season,
                  t.from_club_id, f.name AS from_club, t.to_club_id, c.name AS to_club,
                  t.fee_eur, t.market_value_eur
           FROM transfer t
           LEFT JOIN club f ON f.club_id = t.from_club_id
           LEFT JOIN club c ON c.club_id = t.to_club_id
           WHERE t.player_id = ?
           ORDER BY t.transfer_date, t.transfer_id""",
        (player_id,),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["upcoming"] = int(bool(cutoff) and d["transfer_date"] > cutoff)
        out.append(d)
    return out


def career_seasons(conn: sqlite3.Connection, player_id: int, *, league_only: bool = False) -> list[dict]:
    """(시즌, 구단, 대회) 단위 기록 + 시즌 소계 행(is_subtotal=1, club/competition 은 None).

    appearance(player_id, date) 인덱스 → game(PK) → competition(PK) → game_lineup(PK) 조인.
    starts 는 라인업 데이터가 있는 경기가 하나도 없으면 None.
    """
    league = "AND co.type = 'domestic_league'" if league_only else ""
    sql = f"""
        SELECT g.season, a.club_id, cl.name AS club_name, a.competition_id,
               co.name AS competition_slug, co.type AS competition_type,
               COUNT(*) AS apps, COUNT(l.game_id) AS lineup_rows,
               COALESCE(SUM(l.is_starter), 0) AS starts,
               SUM(a.minutes_played) AS minutes, SUM(a.goals) AS goals, SUM(a.assists) AS assists,
               SUM(a.yellow_cards) AS yellow, SUM(a.red_cards) AS red
        FROM appearance a
        JOIN game g ON g.game_id = a.game_id
        JOIN competition co ON co.competition_id = a.competition_id
        JOIN club cl ON cl.club_id = a.club_id
        LEFT JOIN game_lineup l ON l.game_id = a.game_id AND l.player_id = a.player_id
        WHERE a.player_id = ? {league}
        GROUP BY g.season, a.club_id, a.competition_id
        ORDER BY g.season, (co.type = 'domestic_league') DESC, minutes DESC, a.competition_id, a.club_id
    """  # league 는 고정 문자열 조각.
    rows = [dict(r) for r in conn.execute(sql, (player_id,))]
    out: list[dict] = []
    keys = ("apps", "minutes", "goals", "assists", "yellow", "red")
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j]["season"] == rows[i]["season"]:
            j += 1
        grp = rows[i:j]
        for r in grp:
            r["is_subtotal"] = 0
            r["starts"] = r["starts"] if r.pop("lineup_rows") else None
            out.append(r)
        sub = {"season": rows[i]["season"], "club_id": None, "club_name": None, "competition_id": None,
               "competition_slug": None, "competition_type": None, "is_subtotal": 1}
        for k in keys:
            sub[k] = sum(r[k] for r in grp)
        known = [r["starts"] for r in grp if r["starts"] is not None]
        sub["starts"] = sum(known) if known else None
        out.append(sub)
        i = j
    return out


def coverage_summary(conn: sqlite3.Connection) -> dict:
    """수록 범위: is_covered 리그 수와 실제 출전 기록이 있는 대회 유형."""
    covered = conn.execute("SELECT COUNT(*) FROM competition WHERE is_covered = 1").fetchone()[0]
    types = {r[0] for r in conn.execute(
        "SELECT DISTINCT co.type FROM competition co WHERE EXISTS "
        "(SELECT 1 FROM appearance a WHERE a.competition_id = co.competition_id)")}
    uefa = conn.execute(
        "SELECT 1 FROM competition co WHERE (co.is_uefa_club = 1 OR co.type = 'international_cup' "
        "OR co.sub_type LIKE 'uefa%') AND EXISTS (SELECT 1 FROM appearance a "
        "WHERE a.competition_id = co.competition_id) LIMIT 1").fetchone() is not None
    return {"covered_leagues": covered, "types": sorted(types), "has_uefa": uefa}


def first_appearance_date(conn: sqlite3.Connection, player_id: int) -> str | None:
    """수록된 첫 출전 경기 날짜 (appearance(player_id, date) 인덱스로 MIN 한 번)."""
    row = conn.execute("SELECT MIN(date) FROM appearance WHERE player_id = ?", (player_id,)).fetchone()
    return row[0]


def suggest_players(conn: sqlite3.Connection, text: str, limit: int = 8) -> list[dict]:
    """이름 연관검색어. 정렬은 search_players 와 같다: 완전 일치 -> 단어 접두 -> 부분 일치, 같은 순위는 최고 시장가치 순.

    순위 단계(rk)별로 따로 조회해서, 시장가치 서브쿼리를 필요한 단계의 후보에만 돌린다.
    """
    q = (text or "").strip()
    if not q:
        return []
    esc = _like_escape(q)
    out: list[dict] = []
    for rk in (0, 1, 2):
        need = limit - len(out)
        if need <= 0:
            break
        rows = conn.execute(
            """SELECT c.player_id, c.name, c.pos_group, c.sub_position, c.date_of_birth,
                      c.current_club_name, c.peak_value_eur
               FROM (
                 SELECT p.player_id, p.name,
                        COALESCE((SELECT MAX(v.market_value_eur) FROM player_valuation v
                                   WHERE v.player_id = p.player_id), -1) AS pk
                 FROM player p
                 WHERE p.name LIKE ? ESCAPE '\\'
                   AND (CASE WHEN p.name = ? COLLATE NOCASE THEN 0
                             WHEN p.name LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\'
                                  OR p.name LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END) = ?
                 ORDER BY pk DESC, p.name COLLATE NOCASE, p.player_id LIMIT ?
               ) s JOIN v_player_card c ON c.player_id = s.player_id
               ORDER BY s.pk DESC, c.name COLLATE NOCASE, c.player_id""",
            (f"%{esc}%", q, f"{esc}%", f"% {esc}%", f"%-{esc}%", rk, need),
        ).fetchall()
        for r in rows:
            d = dict(r)
            d["birth_year"] = (d["date_of_birth"] or "")[:4] or None
            out.append(d)
    return out


def suggest_clubs(conn: sqlite3.Connection, text: str, limit: int = 8) -> list[dict]:
    """구단 연관검색어. 이름이 접두/단어 접두로 맞는 구단을 먼저, 같은 단계에서는 거쳐 간 선수가 많은 순.

    거쳐 간 선수 수는 이적 기록(도착/출발 구단)에서 센다: 출전 기록에는 구단 인덱스가 없어 매번 전체를 훑어야 한다.
    """
    q = (text or "").strip()
    if not q:
        return []
    esc = _like_escape(q)
    rows = conn.execute(
        """WITH m AS (
               SELECT club_id, name,
                      CASE WHEN name LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END AS rk
               FROM club WHERE name LIKE ? ESCAPE '\\'),
           pc AS (
               SELECT t.to_club_id AS club_id, t.player_id FROM transfer t JOIN m ON m.club_id = t.to_club_id
               UNION
               SELECT t.from_club_id, t.player_id FROM transfer t JOIN m ON m.club_id = t.from_club_id)
           SELECT m.club_id, m.name, COUNT(pc.player_id) AS n_players
           FROM m LEFT JOIN pc ON pc.club_id = m.club_id
           GROUP BY m.club_id, m.name, m.rk
           ORDER BY m.rk, n_players DESC, m.name COLLATE NOCASE LIMIT ?""",
        (f"{esc}%", f"% {esc}%", f"%{esc}%", int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def domestic_leagues(conn: sqlite3.Connection) -> list[dict]:
    """국내 1부/하위 리그 목록(competition.type='domestic_league'): 수록 리그(is_covered)가 먼저, 나라 이름순."""
    rows = conn.execute(
        """SELECT competition_id, name, country_name, is_covered FROM competition
           WHERE type = 'domestic_league'
           ORDER BY is_covered DESC, country_name COLLATE NOCASE, name COLLATE NOCASE, competition_id""")
    return [dict(r) for r in rows]


def league_clubs(conn: sqlite3.Connection, competition_id: str) -> list[dict]:
    """그 리그 경기에 (홈 또는 원정으로, 어느 시즌이든) 나온 모든 구단, 이름순. game(competition_id, season) 인덱스를 쓴다."""
    rows = conn.execute(
        """SELECT c.club_id, c.name FROM club c
           WHERE c.club_id IN (SELECT home_club_id FROM game WHERE competition_id = ?
                               UNION SELECT away_club_id FROM game WHERE competition_id = ?)
           ORDER BY c.name COLLATE NOCASE, c.club_id""",
        (competition_id, competition_id))
    return [dict(r) for r in rows]


def club_ids_by_name(conn: sqlite3.Connection, text: str) -> list[int]:
    """이름에 text 가 들어 있는 모든 구단 id (예전 club_name 부분 일치 필터와 같은 의미)."""
    q = (text or "").strip()
    if not q:
        return []
    rows = conn.execute("SELECT club_id FROM club WHERE name LIKE ? ESCAPE '\\'", (f"%{_like_escape(q)}%",))
    return [r[0] for r in rows]


def club_tenures(conn: sqlite3.Connection, player_ids, club_ids) -> dict[int, list[tuple]]:
    """선수별로 club_ids 구단에서 보낸 기간 [(시작, 끝|None, 근거)] (시간순, ISO 날짜).

    근거(source)는 'transfer'(이적 기록 기반) 또는 'appearance'(출전 기록만으로 추정). 수록 경기가 2012/13 부터라
    출전 기반 기간은 실제보다 짧을 수 있어 화면에서 따로 표시한다.

    - 구간은 club_ids 로 오는 이적에서 시작해 그 선수의 다음 이적일에 끝난다. 이후 이적이 없고 현재 구단이 club_ids 면
      진행 중(끝 None), 아니면 그 구단 마지막 출전일.
    - 이적 기록이 없는데 그 구단 출전이 있으면 첫/마지막 출전일을 쓴다(진행 중 표시는 하지 않는다). 그 구단에서 나가는 이적만 있으면 (None, 이적일).
    페이지 한 장(선수 수십 명)분을 이적 조회 1번 + 출전 조회 1번 + 현재 구단 조회 1번으로 모은 뒤 파이썬에서 묶는다.
    """
    pids = [int(p) for p in player_ids]
    cids = {int(c) for c in club_ids}
    if not pids or not cids:
        return {}
    pid_json, cid_json = json.dumps(pids), json.dumps(sorted(cids))
    transfers: dict[int, list[tuple]] = {}
    for r in conn.execute(
            """SELECT player_id, transfer_date, from_club_id, to_club_id FROM transfer
               WHERE player_id IN (SELECT value FROM json_each(?))
               ORDER BY player_id, transfer_date, transfer_id""", (pid_json,)):
        transfers.setdefault(r[0], []).append((r[1], r[2], r[3]))
    appearances = {r[0]: (r[1], r[2]) for r in conn.execute(
        """SELECT player_id, MIN(date), MAX(date) FROM appearance
           WHERE player_id IN (SELECT value FROM json_each(?)) AND club_id IN (SELECT value FROM json_each(?))
           GROUP BY player_id""", (pid_json, cid_json))}
    current = {r[0]: r[1] for r in conn.execute(
        "SELECT player_id, current_club_id FROM player WHERE player_id IN (SELECT value FROM json_each(?))",
        (pid_json,))}
    out: dict[int, list[tuple]] = {}
    for pid in pids:
        moves = transfers.get(pid, [])
        stints: list[tuple] = []
        for i, (day, _frm, to) in enumerate(moves):
            if to not in cids:
                continue
            later = [m[0] for m in moves[i + 1:] if m[0] > day]
            if later:
                end = later[0]
            elif current.get(pid) in cids:
                end = None                                    # 진행 중
            else:
                end = appearances.get(pid, (None, None))[1] or day   # 알 수 없으면 그 구단 마지막 출전일, 없으면 시작일
            stints.append((day, end, "transfer"))
        if not stints and pid in appearances:
            lo, hi = appearances[pid]
            stints.append((lo, hi, "appearance"))
        if not stints:
            left = [m[0] for m in moves if m[1] in cids]
            if left:
                stints.append((None, left[-1], "transfer"))
        if stints:
            out[pid] = stints
    return out
