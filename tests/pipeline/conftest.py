"""합성 데이터 테스트용 픽스처: 임시 DB에 apply_sql 후 최소 행만 넣는다."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scouting.db import apply_sql, connect  # noqa: E402


class Builder:
    """합성 원천 행을 넣는 도우미."""

    def __init__(self, conn):
        self.conn = conn
        conn.executemany(
            "INSERT INTO competition (competition_id, name, type, is_covered, is_big5, is_uefa_club) VALUES (?,?,?,?,?,?)",
            [("L1", "Big5 League", "domestic_league", 1, 1, 0),
             ("NL1", "Covered League", "domestic_league", 1, 0, 0),
             ("CL", "Champions League", "international_cup", 0, 0, 1),
             ("CUP", "Cup", "domestic_cup", 0, 0, 0)],
        )
        for cid in range(1, 6):
            conn.execute("INSERT INTO club (club_id, name) VALUES (?, ?)", (cid, f"Club {cid}"))
        self._date_seq = 0

    def player(self, pid, dob="2000-01-01", position="Defender"):
        self.conn.execute("INSERT INTO player (player_id, name, date_of_birth, position) VALUES (?,?,?,?)",
                          (pid, f"P{pid}", dob, position))

    def game(self, gid, home=1, away=2, hg=0, ag=0, season=2018, comp="L1", date=None):
        self.conn.execute("INSERT INTO game VALUES (?,?,?,?,?,?,?,?,?)",
                          (gid, comp, season, None, date or f"{season}-09-01", home, away, hg, ag))

    def app(self, gid, pid, club, minutes, goals=0, assists=0, yc=0, rc=0):
        row = self.conn.execute("SELECT competition_id, date FROM game WHERE game_id = ?", (gid,)).fetchone()
        self.conn.execute("INSERT INTO appearance VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (f"{gid}_{pid}", gid, pid, club, row["date"], row["competition_id"], minutes,
                           goals, assists, yc, rc))

    def lineup(self, gid, pid, club, starter):
        self.conn.execute("INSERT INTO game_lineup (game_id, player_id, club_id, is_starter) VALUES (?,?,?,?)",
                          (gid, pid, club, int(starter)))

    def event(self, gid, minute, typ, club, player=None, player_in=None, desc=None, sending_off=0):
        self._date_seq += 1
        self.conn.execute("INSERT INTO game_event VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (f"e{self._date_seq}", gid, minute, typ, club, player, player_in, None, sending_off, desc))

    def goal(self, gid, minute, club, player=None, desc=None):
        self.event(gid, minute, "Goals", club, player=player, desc=desc)

    def sub(self, gid, minute, club, out_pid, in_pid):
        self.event(gid, minute, "Substitutions", club, player=out_pid, player_in=in_pid)

    def red(self, gid, minute, club, pid):
        self.event(gid, minute, "Cards", club, player=pid, desc="Red card, Foul", sending_off=1)

    def ps(self, pid, season=2018):
        return self.conn.execute("SELECT * FROM player_season WHERE player_id = ? AND season = ?",
                                 (pid, season)).fetchone()


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.sqlite")
    apply_sql(c)
    yield c
    c.close()


@pytest.fixture
def b(conn):
    return Builder(conn)
