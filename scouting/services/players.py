"""선수 검색·프로필·성장표·시장가치·동나이대 백분위·유사 선수."""

from __future__ import annotations

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
