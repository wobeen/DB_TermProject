"""원천 적재 (CONTRACT §3.1). CSV(gz) → 정규화된 원천 테이블."""

from __future__ import annotations

import csv
import gzip
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from pathlib import Path

from scouting.db import transaction

csv.field_size_limit(1 << 24)

COVERED = ("GB1", "ES1", "IT1", "L1", "FR1", "PO1", "NL1", "BE1", "TR1", "RU1", "UKR1", "SC1", "GR1", "DK1")
BIG5 = ("GB1", "ES1", "IT1", "L1", "FR1")
UEFA_CLUB = ("CL", "EL")
COMP_TYPES = {"domestic_league", "domestic_cup", "international_cup", "national_team_competition", "other"}
BATCH = 50_000


# ---------------------------------------------------------------- helpers
def read_csv(path: Path) -> Iterator[dict[str, str | None]]:
    """빈 문자열은 None으로 바꿔 행을 dict로 낸다."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            yield {h: (v if v != "" else None) for h, v in zip(header, row)}


def d10(value: str | None) -> str | None:
    """날짜는 앞 10자만. 유효한 ISO 날짜가 아니면 None."""
    if not value:
        return None
    s = value[:10]
    try:
        return date.fromisoformat(s).isoformat() if len(s) == 10 else None
    except ValueError:
        return None


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _insert(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> tuple[int, int]:
    """한 테이블 = 한 트랜잭션, executemany를 배치로 나눠 넣는다. (시도한 행 수, 실제 변경된 행 수)를 반환한다.

    INSERT OR IGNORE 가 PK/UNIQUE 충돌로 버린 행 수 = 시도 - 변경.
    """
    it = iter(rows)
    attempted = changed = 0
    with transaction(conn):
        while True:
            chunk = []
            for r in it:
                chunk.append(r)
                if len(chunk) >= BATCH:
                    break
            if not chunk:
                break
            attempted += len(chunk)
            changed += conn.executemany(sql, chunk).rowcount
    return attempted, changed


class Table:
    """테이블별 원천 행 수 / 제외 사유 집계."""

    def __init__(self) -> None:
        self.source = 0
        self.excluded: Counter[str] = Counter()   # 적재되지 않은 행(사유별)
        self.adjusted: Counter[str] = Counter()   # 행은 적재했지만 값을 바꾼 경우(NULL 처리 등)

    def skip(self, reason: str) -> None:
        self.excluded[reason] += 1

    def adjust(self, note: str) -> None:
        self.adjusted[note] += 1

    def ignored(self, result: tuple[int, int]) -> None:
        """INSERT OR IGNORE 로 버려진 행(PK/UNIQUE 중복)을 제외 사유로 기록한다."""
        attempted, changed = result
        if attempted - changed:
            self.excluded["PK/UNIQUE 중복 → INSERT OR IGNORE 로 버림"] += attempted - changed

    def report(self, loaded: int, stubs: int = 0, **extra: int) -> dict:
        """불변식: source_rows == loaded_rows - stub_clubs + sum(excluded)."""
        out = {"source_rows": self.source, "loaded_rows": loaded, "excluded": dict(self.excluded),
               "adjusted": dict(self.adjusted)}
        if stubs:
            out["stub_clubs"] = stubs
        out.update(extra)
        return out


def check_report(report: dict[str, dict]) -> dict[str, int]:
    """테이블마다 원천 행 수 = (적재 - stub) + 제외 합계 인지 검사한다. 어긋난 만큼(원천 - 기대)을 반환한다."""
    gaps = {}
    for name, rep in report.items():
        if "source_rows" not in rep:
            continue
        gaps[name] = rep["source_rows"] - (rep["loaded_rows"] - rep.get("stub_clubs", 0) + sum(rep["excluded"].values()))
    return gaps


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # table은 내부 상수(화이트리스트)


def _ids(conn: sqlite3.Connection, table: str, col: str) -> set:
    return {row[0] for row in conn.execute(f"SELECT {col} FROM {table}")}  # 내부 상수


# ---------------------------------------------------------------- loaders
def _load_competition(conn, tm: Path) -> dict:
    t = Table()
    out = []
    for r in read_csv(tm / "competitions.csv.gz"):
        t.source += 1
        cid = r["competition_id"]
        typ = r["type"] if r["type"] in COMP_TYPES else "other"
        out.append((cid, r["name"] or cid, typ, r["sub_type"], r["country_name"], r["confederation"],
                    int(cid in COVERED), int(cid in BIG5), int(cid in UEFA_CLUB)))
    _insert(conn, "INSERT INTO competition VALUES (?,?,?,?,?,?,?,?,?)", out)
    return t.report(_count(conn, "competition"))


def _scan_club_refs(tm: Path) -> dict[int, str | None]:
    """원천 전체에서 참조되는 구단 id → 이름(알면)."""
    names: dict[int, str | None] = {}

    def see(cid: str | None, name: str | None = None) -> None:
        i = to_int(cid)
        if i is None:
            return
        if names.get(i) is None:
            names[i] = name

    for r in read_csv(tm / "games.csv.gz"):
        see(r["home_club_id"], r["home_club_name"])
        see(r["away_club_id"], r["away_club_name"])
    for r in read_csv(tm / "transfers.csv.gz"):
        see(r["from_club_id"], r["from_club_name"])
        see(r["to_club_id"], r["to_club_name"])
    for r in read_csv(tm / "appearances.csv.gz"):
        see(r["player_club_id"])
    for r in read_csv(tm / "game_lineups.csv.gz"):
        see(r["club_id"])
    for r in read_csv(tm / "game_events.csv.gz"):
        see(r["club_id"])
    for r in read_csv(tm / "players.csv.gz"):
        see(r["current_club_id"])
    for r in read_csv(tm / "player_valuations.csv.gz"):
        see(r["current_club_id"])
    return names


def _load_club(conn, tm: Path) -> dict:
    t = Table()
    comps = _ids(conn, "competition", "competition_id")
    seen: set[int] = set()
    out = []
    for r in read_csv(tm / "clubs.csv.gz"):
        t.source += 1
        cid = to_int(r["club_id"])
        if cid is None or cid in seen:
            t.skip("club_id 없음/중복")
            continue
        seen.add(cid)
        dom = r["domestic_competition_id"]
        if dom not in comps:
            if dom is not None:
                t.adjust("domestic_competition_id 미존재 → NULL로 적재")
            dom = None
        out.append((cid, r["name"] or f"Unknown club {cid}", dom, 0))
    refs = _scan_club_refs(tm)
    stubs = [(i, n or f"Unknown club {i}", None, 1) for i, n in sorted(refs.items()) if i not in seen]
    _insert(conn, "INSERT INTO club VALUES (?,?,?,?)", out + stubs)
    return t.report(_count(conn, "club"), stubs=len(stubs))


def _load_player(conn, tm: Path) -> dict:
    t = Table()
    clubs = _ids(conn, "club", "club_id")

    def gen():
        for r in read_csv(tm / "players.csv.gz"):
            t.source += 1
            pid = to_int(r["player_id"])
            if pid is None or not r["name"]:
                t.skip("player_id/name 없음")
                continue
            h = to_int(r["height_in_cm"])
            if h is not None and (h < 10 or h > 220):
                h = None
                t.adjust("키 10 미만 또는 220 초과 → NULL로 적재")
            elif h is not None and h < 140:
                h = None
                t.adjust("키 10~139 → NULL로 적재(스키마 CHECK 140 이상)")
            cc = to_int(r["current_club_id"])
            yield (pid, r["name"], d10(r["date_of_birth"]), r["position"] or "Missing", r["sub_position"],
                   r["foot"], h, r["country_of_citizenship"], cc if cc in clubs else None)

    t.ignored(_insert(conn, "INSERT OR IGNORE INTO player (player_id,name,date_of_birth,position,sub_position,foot,"
                  "height_cm,country_of_citizenship,current_club_id) VALUES (?,?,?,?,?,?,?,?,?)", gen()))
    return t.report(_count(conn, "player"))


def _load_game(conn, tm: Path) -> dict:
    t = Table()
    comps = _ids(conn, "competition", "competition_id")

    def gen():
        for r in read_csv(tm / "games.csv.gz"):
            t.source += 1
            gid, h, a = to_int(r["game_id"]), to_int(r["home_club_id"]), to_int(r["away_club_id"])
            hg, ag = to_int(r["home_club_goals"]), to_int(r["away_club_goals"])
            season, dt = to_int(r["season"]), d10(r["date"])
            if None in (gid, h, a, hg, ag, season, dt) or h == a:
                t.skip("필수값 누락 또는 홈=원정")
                continue
            if r["competition_id"] not in comps:
                t.skip("competition 없음")
                continue
            yield (gid, r["competition_id"], season, r["round"], dt, h, a, hg, ag)

    t.ignored(_insert(conn, "INSERT OR IGNORE INTO game VALUES (?,?,?,?,?,?,?,?,?)", gen()))
    return t.report(_count(conn, "game"))


def _load_appearance(conn, tm: Path) -> dict:
    t = Table()
    players = _ids(conn, "player", "player_id")
    games = _ids(conn, "game", "game_id")
    comps = _ids(conn, "competition", "competition_id")

    def gen():
        for r in read_csv(tm / "appearances.csv.gz"):
            t.source += 1
            pid, gid, cid = to_int(r["player_id"]), to_int(r["game_id"]), to_int(r["player_club_id"])
            dt, mp = d10(r["date"]), to_int(r["minutes_played"])
            if pid not in players:
                t.skip("players에 없는 선수")
                continue
            if gid not in games or r["competition_id"] not in comps or None in (cid, dt, mp):
                t.skip("games/competition에 없음 또는 필수값 누락")
                continue
            yield (r["appearance_id"], gid, pid, cid, dt, r["competition_id"], mp, to_int(r["goals"]) or 0,
                   to_int(r["assists"]) or 0, to_int(r["yellow_cards"]) or 0, to_int(r["red_cards"]) or 0)

    t.ignored(_insert(conn, "INSERT OR IGNORE INTO appearance VALUES (?,?,?,?,?,?,?,?,?,?,?)", gen()))
    return t.report(_count(conn, "appearance"))


def _load_lineup(conn, tm: Path) -> dict:
    t = Table()
    players = _ids(conn, "player", "player_id")
    games = _ids(conn, "game", "game_id")
    attempted = 0

    def gen():
        nonlocal attempted
        for r in read_csv(tm / "game_lineups.csv.gz"):
            t.source += 1
            pid, gid, cid = to_int(r["player_id"]), to_int(r["game_id"]), to_int(r["club_id"])
            if pid not in players:
                t.skip("players에 없는 선수")
                continue
            if gid not in games or cid is None:
                t.skip("games에 없음 또는 club 누락")
                continue
            attempted += 1
            yield (gid, pid, cid, int(r["type"] == "starting_lineup"), r["position"], to_int(r["team_captain"]) or 0)

    # 중복 (game, player)은 선발 행을 우선해 1건만 남긴다
    _insert(conn, "INSERT INTO game_lineup VALUES (?,?,?,?,?,?) ON CONFLICT(game_id, player_id) DO UPDATE SET "
                  "club_id=excluded.club_id, is_starter=excluded.is_starter, position=excluded.position, "
                  "team_captain=excluded.team_captain WHERE excluded.is_starter > game_lineup.is_starter", gen())
    loaded = _count(conn, "game_lineup")
    if attempted - loaded:
        t.excluded["(game_id, player_id) 중복 → 선발 행 우선 1건 유지"] = attempted - loaded
    return t.report(loaded)


def _load_event(conn, tm: Path) -> dict:
    t = Table()
    games = _ids(conn, "game", "game_id")

    def gen():
        for r in read_csv(tm / "game_events.csv.gz"):
            t.source += 1
            gid, mn, cid = to_int(r["game_id"]), to_int(r["minute"]), to_int(r["club_id"])
            if gid not in games or cid is None or mn is None or not -1 <= mn <= 130:
                t.skip("games에 없음 또는 club/minute 누락·범위 밖")
                continue
            desc = r["description"]
            typ = r["type"]
            send = int(typ == "Cards" and desc is not None
                       and (desc.startswith("Red card") or desc.startswith("Second yellow")))
            yield (r["game_event_id"], gid, mn, typ, cid, to_int(r["player_id"]), to_int(r["player_in_id"]),
                   to_int(r["player_assist_id"]), send, desc)

    t.ignored(_insert(conn, "INSERT OR IGNORE INTO game_event VALUES (?,?,?,?,?,?,?,?,?,?)", gen()))
    return t.report(_count(conn, "game_event"))


def _load_valuation(conn, tm: Path) -> dict:
    t = Table()
    players = _ids(conn, "player", "player_id")
    clubs = _ids(conn, "club", "club_id")

    def gen():
        for r in read_csv(tm / "player_valuations.csv.gz"):
            t.source += 1
            pid, dt, mv = to_int(r["player_id"]), d10(r["date"]), to_int(r["market_value_in_eur"])
            if pid not in players or dt is None or mv is None or mv < 0:
                t.skip("players에 없음 또는 필수값 누락")
                continue
            cid = to_int(r["current_club_id"])
            yield (pid, dt, mv, cid if cid in clubs else None)

    t.ignored(_insert(conn, "INSERT OR IGNORE INTO player_valuation VALUES (?,?,?,?)", gen()))
    return t.report(_count(conn, "player_valuation"))


def _load_transfer(conn, tm: Path) -> dict:
    t = Table()
    players = _ids(conn, "player", "player_id")
    clubs = _ids(conn, "club", "club_id")

    def gen():
        for r in read_csv(tm / "transfers.csv.gz"):
            t.source += 1
            pid, dt = to_int(r["player_id"]), d10(r["transfer_date"])
            if pid not in players or dt is None:
                t.skip("players에 없음 또는 날짜 누락")
                continue
            f, to = to_int(r["from_club_id"]), to_int(r["to_club_id"])
            fee, mv = to_float(r["transfer_fee"]), to_float(r["market_value_in_eur"])
            yield (pid, dt, r["transfer_season"], f if f in clubs else None, to if to in clubs else None,
                   fee if fee is None or fee >= 0 else None, mv if mv is None or mv >= 0 else None)

    _insert(conn, "INSERT INTO transfer (player_id,transfer_date,transfer_season,from_club_id,to_club_id,"
                  "fee_eur,market_value_eur) VALUES (?,?,?,?,?,?,?)", gen())
    return t.report(_count(conn, "transfer"))


STEPS: tuple[tuple[str, Callable], ...] = (
    ("competition", _load_competition),
    ("club", _load_club),
    ("player", _load_player),
    ("game", _load_game),
    ("appearance", _load_appearance),
    ("game_lineup", _load_lineup),
    ("game_event", _load_event),
    ("player_valuation", _load_valuation),
    ("transfer", _load_transfer),
)


def load_all(conn: sqlite3.Connection, tm_dir: Path,
             progress: Callable[[str, float, dict], None] | None = None) -> dict[str, dict]:
    """원천 전체를 적재하고 load_report 내용을 반환한다. 끝나면 foreign_key_check가 0행이어야 한다."""
    tm_dir = Path(tm_dir)
    old_sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    conn.execute("PRAGMA synchronous = OFF")  # 대량 적재 중에만
    report: dict[str, dict] = {}
    try:
        for name, fn in STEPS:
            t0 = time.perf_counter()
            report[name] = fn(conn, tm_dir)
            if progress:
                progress(name, time.perf_counter() - t0, report[name])
    finally:
        conn.execute(f"PRAGMA synchronous = {int(old_sync)}")
    gaps = check_report(report)
    report["_balance"] = {"gap_by_table": gaps, "ok": not any(gaps.values())}
    if not report["_balance"]["ok"]:
        raise RuntimeError(f"원천 행 수 ≠ 적재 + 제외: {gaps}")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    report["_foreign_key_check"] = {"violations": len(violations)}
    if violations:
        raise RuntimeError(f"foreign_key_check 위반 {len(violations)}건: {[tuple(v) for v in violations[:5]]}")
    return report
