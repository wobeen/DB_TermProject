"""CLI 진입점과 메뉴 (CONTRACT §7). 어떤 입력에도 traceback 으로 종료하지 않는다."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections.abc import Callable

from scouting import db as dbm
from scouting.cli.ui import INT_MAX, IO, Quit, R, eur, fmt, local_time, table
from scouting.services import admin, backtest, notes, players, recommend, users, watchlist
from scouting.services.users import User

POS = ("GK", "DF", "MF", "FW")
PAGE = 20
LOCK_MSG = "다른 작업(스냅샷 재계산 등)이 DB를 사용 중입니다. 잠시 후 다시 시도해 주세요."


def is_locked(e: sqlite3.OperationalError) -> bool:
    m = str(e).lower()
    return "locked" in m or "busy" in m


def translate_integrity(e: sqlite3.IntegrityError) -> str:
    msg = str(e)
    if "UNIQUE" in msg or "PRIMARY KEY" in msg:
        if "watchlist" in msg:
            return "이미 워치리스트에 있는 선수입니다."
        if "username" in msg:
            return "이미 사용 중인 사용자명입니다."
        return "이미 존재하는 값입니다 (중복)."
    if "FOREIGN KEY" in msg:
        return "연결된 데이터가 있거나 존재하지 않는 대상입니다 (참조 무결성 위반)."
    if "CHECK" in msg:
        return "입력값이 허용 범위를 벗어났습니다 (길이/범위 제한 위반)."
    if "NOT NULL" in msg:
        return "필수 값이 비어 있습니다."
    return "데이터 무결성 오류로 처리하지 못했습니다."


class App:
    def __init__(self, conn: sqlite3.Connection, io: IO):
        self.conn = conn
        self.io = io
        self.user: User | None = None

    # ---- 공통 -------------------------------------------------------------
    def say(self, s: str = "") -> None:
        self.io.say(s)

    def empty(self, hint: str) -> None:
        self.say(f"표시할 데이터가 없습니다. ({hint})")

    def with_retry(self, fn):
        """DB 잠금(locked/busy)이면 안내하고 다시 시도할지 묻는다. 포기하면 None."""
        while True:
            try:
                return fn()
            except sqlite3.OperationalError as e:
                if not is_locked(e):
                    raise
                self.say(LOCK_MSG)
                if not self.io.confirm("다시 시도할까요?"):
                    return None

    def safe(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Quit:
            raise
        except sqlite3.IntegrityError as e:
            self.say(f"[오류] {translate_integrity(e)}")
        except (ValueError, PermissionError, RuntimeError) as e:
            self.say(f"[오류] {e}")
        except sqlite3.OperationalError as e:
            self.say(f"[오류] {LOCK_MSG}" if is_locked(e) else f"[DB 오류] {e}")
        except sqlite3.Error as e:
            self.say(f"[DB 오류] {e}")
        except Exception as e:  # 마지막 방어선: traceback 대신 메시지
            self.say(f"[예상치 못한 오류] {type(e).__name__}: {e}")

    def menu(self, title: str, items: list[tuple[str, str, Callable[[], None]]], zero: str) -> None:
        while True:
            self.say()
            self.say(f"=== {title} ===")
            for key, label, _ in items:
                self.say(f"  {key:>2}. {label}")
            self.say(f"  {'0':>2}. {zero}")
            sel = self.io.text("선택> ", blank_ok=True)
            if sel == "0":
                return
            for key, _, fn in items:
                if sel == key:
                    self.safe(fn)
                    break
            else:
                self.say("잘못된 선택입니다. 메뉴에 있는 번호를 입력해 주세요.")

    # ---- 메인 -------------------------------------------------------------
    def run(self) -> None:
        self.menu(
            "스카우팅 DB",
            [("1", "로그인", self.login), ("2", "회원가입", self.signup)],
            "종료",
        )
        self.say("종료합니다.")

    def signup(self) -> None:
        while True:  # 사용자명 길이·중복을 비밀번호 입력 전에 검사
            name = self.io.text("사용자명(3~32자, 빈 입력=취소): ", blank_ok=True)
            if not name:
                return
            problem = users.username_problem(self.conn, name)
            if problem is None:
                break
            self.say(problem)
        while True:
            pw = self.io.secret("비밀번호(4자 이상, 빈 입력=취소): ")
            if not pw:
                return
            if len(pw) >= users.MIN_PASSWORD_LEN:
                break
            self.say(f"비밀번호는 {users.MIN_PASSWORD_LEN}자 이상이어야 합니다.")
        users.register(self.conn, name, pw, "scout")
        self.say("회원가입 완료. 로그인해 주세요.")

    def login(self) -> None:
        name = self.io.text("사용자명: ")
        pw = self.io.secret("비밀번호: ")
        u = users.authenticate(self.conn, name, pw)
        if u is None:
            self.say("사용자명 또는 비밀번호가 올바르지 않습니다.")
            return
        self.user = u
        self.say(f"{u.username} 님 환영합니다. (역할: {u.role})")
        items = [
            ("1", "선수 검색", self.search),
            ("2", "선수 프로필", self.profile),
            ("3", "유사 선수 Top-k", self.similar),
            ("4", "다음 월클 추천 실행", self.recommend),
            ("5", "내 추천 기록 / 결과 상세", self.my_runs),
            ("6", "워치리스트", self.watch_menu),
            ("7", "스카우팅 노트", self.note_menu),
            ("8", "기준 돌파 유망주 (> ALL / > SOME)", self.breakout),
        ]
        if u.role == "admin":
            items += [
                ("9", "데이터 현황", self.status),
                ("10", "스냅샷 재계산", self.rebuild),
                ("11", "월클 정의 관리", self.definitions),
                ("12", "백테스트 실행", self.backtest),
                ("13", "사용자 역할 변경", self.change_role),
            ]
        self.menu(f"메인 메뉴 ({u.username})", items, "로그아웃")
        self.user = None

    # ---- 선택 도우미 ------------------------------------------------------
    def pick_player(self, prompt: str = "선수 ID 또는 이름 검색어: ") -> int | None:
        while True:
            s = self.io.text(prompt + "(빈 입력=취소) ", blank_ok=True)
            if not s:
                return None
            if s.replace(",", "").isdigit():
                num = int(s.replace(",", ""))
                if not 1 <= num <= INT_MAX:
                    self.say(f"ID 는 1~{INT_MAX} 범위여야 합니다.")
                    continue
                card = players.player_card(self.conn, num)
                if card:
                    self.say(f"  → {card['name']} ({card['pos_group'] or '-'})")
                    return card["player_id"]
                self.say("해당 ID의 선수가 없습니다.")
                continue
            pid = self.browse_players({"name": s}, select=True)
            if pid is not None:
                return pid

    def browse_players(self, filters: dict, *, select: bool) -> int | None:
        """검색 결과를 20명씩 보여 주고 n/p 로 페이지를 넘긴다. select=True 면 ID 를 골라 반환."""
        total = players.count_players(self.conn, **filters)
        if total == 0:
            self.empty("이름 철자나 나이·리그 조건을 줄여 보세요")
            return None
        pages = (total + PAGE - 1) // PAGE
        page = 0
        while True:
            rows = players.search_players(self.conn, **filters, limit=PAGE, offset=page * PAGE)
            self.print_players(rows)
            self.say(f"총 {total:,}명 중 {page * PAGE + 1}~{page * PAGE + len(rows)}번째 (페이지 {page + 1}/{pages})")
            nav = "n=다음, " if page + 1 < pages else ""
            nav += "p=이전, " if page > 0 else ""
            msg = ("선수 ID 선택" if select else "더 보기") + f" ({nav}빈 입력={'다시 검색' if select else '종료'}): "
            ans = self.io.text(msg, blank_ok=True).lower()
            if not ans:
                return None
            if ans == "n":
                if page + 1 < pages:
                    page += 1
                else:
                    self.say("마지막 페이지입니다.")
            elif ans == "p":
                if page > 0:
                    page -= 1
                else:
                    self.say("첫 페이지입니다.")
            elif select and ans.replace(",", "").isdigit():
                pid = int(ans.replace(",", ""))
                if any(r["player_id"] == pid for r in rows):
                    return pid
                self.say("현재 페이지 목록에 없는 ID 입니다.")
            else:
                self.say("n, p" + (", 목록의 선수 ID" if select else "") + " 또는 빈 입력만 사용할 수 있습니다.")

    def pick_snapshot(self, built_only: bool = True) -> dict | None:
        snaps = recommend.list_snapshots(self.conn, built_only=built_only)
        if not snaps:
            self.say("사용 가능한 스냅샷이 없습니다.")
            return None
        return self.io.choose(
            "스냅샷을 선택하세요.",
            [(s, f"{s['name']}  (as_of {s['as_of_date']}, 빌드 {local_time(s['built_at']) if s['built_at'] else '미완료'})") for s in snaps],
        )

    def pick_definition(self) -> dict | None:
        defs = recommend.list_definitions(self.conn)
        if not defs:
            self.say("월클 정의가 없습니다.")
            return None
        return self.io.choose("월클 정의를 선택하세요.", [(d, f"{d['code']}  {d['name_ko']}") for d in defs])

    def pick_pos(self) -> str | None:
        return self.io.choose("포지션군을 선택하세요.", [(p, p) for p in POS])

    def print_players(self, rows: list[dict]) -> None:
        self.say(
            table(
                ["ID", "이름", "포지션", "나이", "구단", "시장가치"],
                [
                    [r["player_id"], r["name"], r["pos_group"], r["age"], r["current_club_name"],
                     eur(r["latest_value_eur"])]
                    for r in rows
                ],
            )
        )

    # ---- 스카우트 메뉴 ----------------------------------------------------
    def search(self) -> None:
        name = self.io.text("이름(빈 입력=전체): ", blank_ok=True) or None
        while True:
            pos = self.io.text("포지션군 GK/DF/MF/FW(빈 입력=전체): ", blank_ok=True).upper() or None
            if pos is None or pos in POS:
                break
            self.say("포지션군은 GK/DF/MF/FW 중 하나여야 합니다.")
        max_age = self.io.integer("최대 나이 10~60(빈 입력=무제한): ", 10, 60, blank_ok=True)
        while True:
            comp = self.io.text("리그 ID 예: GB1, ES1(빈 입력=전체): ", blank_ok=True).upper() or None
            if comp is None or players.competition_exists(self.conn, comp):
                break
            self.say("competition 테이블에 없는 리그 ID 입니다.")
        self.browse_players(
            {"name": name, "pos_group": pos, "max_age": max_age, "competition_id": comp}, select=False
        )

    GROWTH_EXTRA = {
        "GK": [("실점/90", "m_onpitch_ga_per90"), ("무실점률", "m_clean_sheet_rate")],
        "DF": [("실점/90", "m_onpitch_ga_per90"), ("무실점률", "m_clean_sheet_rate"),
               ("득실차/90", "m_onpitch_gd_per90")],
        "MF": [("공격P/90", "m_ga_per90"), ("도움/90", "m_assists_per90"), ("득실차/90", "m_onpitch_gd_per90")],
        "FW": [("득점/90", "m_goals_per90"), ("공격P/90", "m_ga_per90"), ("득실차/90", "m_onpitch_gd_per90")],
    }

    def growth_table(self, pos_group: str | None, hist: list[dict]) -> str:
        extra = self.GROWTH_EXTRA.get(pos_group or "", [])
        headers = ["시즌", "나이", "구단", "출전", "선발", "분", "점유율"] + [h for h, _ in extra]
        rows = [
            [h["season"], h["age"], h["club_name"], h["league_apps"], h["league_starts"], h["league_minutes"],
             h.get("m_minutes_share")] + [h.get(key) for _, key in extra]
            for h in hist
        ]
        return table(headers, rows)

    @staticmethod
    def percentile_value(p: dict) -> str:
        dv, unit = p["display_value"], p["unit"]
        if unit == "€M":
            return f"€{dv:,.1f}M"
        if unit == "분":
            return f"{dv:,.0f}분"
        return fmt(float(dv))

    def _snapshot_season(self, snap: dict, pid: int) -> int | None:
        row = self.conn.execute(
            "SELECT MAX(season) FROM v_player_season_asof WHERE snapshot_id = ? AND player_id = ?",
            (snap["snapshot_id"], pid),
        ).fetchone()
        return row[0]

    def profile(self) -> None:
        pid = self.pick_player()
        if pid is None:
            return
        card = players.player_card(self.conn, pid)
        self.say(
            f"\n[{card['name']}] {card['position']} / 나이 {fmt(card['age'])} / "
            f"구단 {card['current_club_name'] or '-'} / 현재가치 {eur(card['latest_value_eur'])} / "
            f"최고가치 {eur(card['peak_value_eur'])}"
        )
        hist = players.season_history(self.conn, pid)
        if hist:
            self.say(f"\n시즌별 성장표 ({card['pos_group']})")
            self.say(self.growth_table(card["pos_group"], hist))
        else:
            self.empty("이 선수의 covered 리그 출전 기록이 없거나 시즌 파생 데이터가 아직 계산되지 않았습니다")
        vals = players.valuation_by_season(self.conn, pid)
        if vals:
            self.say("\n시장가치 추이 (시즌 = 7/1 ~ 다음 해 6/30)")
            self.say(table(
                ["시즌", "최고가치", "최고 시점", "최종가치", "최종 시점", "건수"],
                [[v["season"], eur(v["peak_eur"]), v["peak_date"], eur(v["last_eur"]), v["last_date"], v["n"]]
                 for v in vals],
            ))
            if self.io.confirm("전체 시장가치 이력을 볼까요?"):
                full = players.valuation_history(self.conn, pid)
                self.say(table(["날짜", "시장가치", "구단"],
                               [[v["date"], eur(v["market_value_eur"]), v["club_name"]] for v in full]))
        snap = self.pick_snapshot()
        if snap is None:
            return
        season = self._snapshot_season(snap, pid)
        if season is None:
            self.empty("이 스냅샷 기준으로 완료된 시즌 출전 기록이 없습니다. 다른 스냅샷을 선택해 보세요")
            return
        pct = players.cohort_percentiles(self.conn, snap["snapshot_id"], pid, season)
        self.say(f"\n동나이대 백분위 (스냅샷 {snap['name']}, 시즌 {season})")
        if not pct:
            self.empty("해당 시즌 출전 시간이 지표 최소 출전 시간에 못 미치거나 지표가 계산되지 않았습니다")
            return
        self.say(
            table(
                ["지표", "값", "백분위", "가중치", "코호트 n"],
                [
                    [p["name_ko"] if p["weight"] is not None else f"({p['name_ko']})",
                     R(self.percentile_value(p)), R(f"{p['percentile']:.1f}"),
                     R(f"{p['weight']:g}") if p["weight"] is not None else "-", p["cohort_n"]]
                    for p in pct
                ],
            )
        )
        if any(p["weight"] is None for p in pct):
            self.say("( ) 표시 지표는 이 포지션군의 유사도 가중치가 없어 추천에는 쓰이지 않습니다.")

    def similar(self) -> None:
        pid = self.pick_player()
        if pid is None:
            return
        snap = self.pick_snapshot()
        if snap is None:
            return
        season = self._snapshot_season(snap, pid)
        if season is None:
            self.empty("이 스냅샷 기준으로 완료된 시즌 출전 기록이 없습니다. 다른 스냅샷을 선택해 보세요")
            return
        k = self.io.integer("k (기본 10, 1~50): ", 1, 50, blank_ok=True) or 10
        d = self.pick_definition()
        res = players.similar_players(
            self.conn, snap["snapshot_id"], pid, season, k, def_id=d["def_id"] if d else None
        )
        if not res:
            self.empty("지표가 부족하거나(가중치 60% 미만 공유) 같은 나이 비교 풀이 없습니다. 스냅샷 미빌드일 수도 있습니다")
            return
        self.say(f"시즌 {season} 기준 유사 선수 Top-{k}")
        self.say(
            table(
                ["순위", "ID", "이름", "시즌", "나이", "구단", "거리", "월클"],
                [[i, r["player_id"], r["name"], r["season"], r["age"], r["club_name"], r["distance"],
                  "O" if r["is_wc"] else "-"] for i, r in enumerate(res, 1)],
            )
        )

    def recommend(self) -> None:
        snap = self.pick_snapshot()
        if snap is None:
            return
        d = self.pick_definition()
        if d is None:
            return
        pos = self.pick_pos()
        if pos is None:
            return
        method = self.io.choose("추천 method", [(m, m) for m in recommend.METHODS])
        if method is None:
            return
        params: dict = {}
        if not self.io.confirm("기본값(max_age 21, min_minutes 900, k 25, top_n 20, pool_lag 3, seed 42)으로 "
                               "바로 실행할까요? n=고급 설정 입력"):
            for key, label, lo, hi in (
                ("max_age", "max_age 15~30 (기본 21)", 15, 30),
                ("min_minutes", "min_minutes 0~5000 (기본 900)", 0, 5000),
                ("k", "k 1~200 (기본 25)", 1, 200),
                ("top_n", "top_n 1~200 (기본 20)", 1, 200),
                ("pool_lag_seasons", "pool_lag_seasons 0~10 (기본 3)", 0, 10),
                ("seed", "seed 1 이상 정수 (기본 42)", None, None),
            ):
                v = self.io.integer(f"{label}, 빈 입력=기본값: ", lo, hi, blank_ok=True)
                if v is not None:
                    params[key] = v
        n_cand = len(recommend.candidate_ids(
            self.conn, snapshot_id=snap["snapshot_id"], def_id=d["def_id"], pos_group=pos,
            max_age=params.get("max_age", 21), min_minutes=params.get("min_minutes", 900),
        ))
        self.say(f"계산 중... (후보 {n_cand}명)")
        t0 = time.perf_counter()
        run_id = self.with_retry(lambda: recommend.run_recommendation(
            self.conn, user_id=self.user.user_id, snapshot_id=snap["snapshot_id"], def_id=d["def_id"],
            pos_group=pos, method=method, **params,
        ))
        if run_id is None:
            self.say("추천 실행을 취소했습니다.")
            return
        self.say(f"추천 완료: run #{run_id} (소요 {time.perf_counter() - t0:.1f}초)")
        self.show_run(run_id)

    def show_run(self, run_id: int) -> None:
        run = recommend.get_run(self.conn, run_id)
        items = recommend.run_items(self.conn, run_id)
        self.say(
            f"run #{run_id}  method={run['method']} pos={run['pos_group']} max_age={run['max_age']} "
            f"k={run['k']} top_n={run['top_n']} seed={run['seed']}"
        )
        if not items:
            self.empty("후보가 없습니다. 나이·최소 출전 시간 조건을 완화하거나 스냅샷이 빌드됐는지 확인하세요")
            return
        self.say(
            table(
                ["순위", "ID", "이름", "구단", "점수", "월클이웃", "시장가치(as_of)"],
                [[i["rank"], i["player_id"], i["name"], i["club_name"], i["score"], i["wc_neighbors"],
                  eur(i["value_eur"])] for i in items],
            )
        )

    def my_runs(self) -> None:
        runs = recommend.list_runs(self.conn, self.user.user_id)
        if not runs:
            self.empty("아직 실행한 추천이 없습니다. 메뉴 4 에서 추천을 실행하세요")
            return
        self.say(
            table(
                ["run", "생성", "스냅샷", "정의", "method", "포지션"],
                [[r["run_id"], local_time(r["created_at"]), r["snapshot"], r["def_code"], r["method"], r["pos_group"]]
                 for r in runs],
            )
        )
        rid = self.io.integer("상세를 볼 run 번호(빈 입력=취소): ", blank_ok=True)
        if rid is None:
            return
        if not any(r["run_id"] == rid for r in runs):
            self.say("내 추천 기록에 없는 번호입니다.")
            return
        self.show_run(rid)
        pid = self.io.integer("근거 이웃을 볼 선수 ID(빈 입력=종료): ", blank_ok=True)
        if pid is not None:
            ev = recommend.run_evidence(self.conn, rid, pid)
            if not ev:
                self.empty("근거 이웃은 similarity/hybrid 추천의 상위 항목에만 저장됩니다")
            else:
                self.say(
                    table(
                        ["이웃 ID", "이름", "시즌", "거리", "월클"],
                        [[e["neighbor_player_id"], e["name"], e["neighbor_season"], e["distance"],
                          "O" if e["neighbor_is_wc"] else "-"] for e in ev],
                    )
                )

    def breakout(self) -> None:
        snap = self.pick_snapshot()
        if snap is None:
            return
        d = self.pick_definition()
        if d is None:
            return
        pos = self.pick_pos()
        if pos is None:
            return
        metrics = recommend.list_metrics(self.conn)
        metric = self.io.choose(
            "비교할 지표 (값이 클수록 우수한 지표 기준 해석)",
            [(m["metric_code"], f"{m['metric_code']}  {m['name_ko']}") for m in metrics],
        )
        if metric is None:
            return
        mode = self.io.choose("비교 방식", [("all", "all  : 값 > ALL (그 나이 월클 전원보다 높음)"),
                                         ("some", "some : 값 > SOME (적어도 한 명보다 높음)")])
        if mode is None:
            return
        max_age = self.io.integer("후보 최대 나이 15~30 (빈 입력=21): ", 15, 30, blank_ok=True) or 21
        kw = dict(snapshot_id=snap["snapshot_id"], def_id=d["def_id"], pos_group=pos, metric_code=metric)
        rows = recommend.breakout_prospects(self.conn, max_age=max_age, mode=mode, **kw)
        if not rows:
            if recommend.breakout_wc_count(self.conn, **kw) == 0:
                self.empty(f"스냅샷 {snap['name']} 에서 {pos} 월클({d['code']})의 해당 지표 기록이 없어 비교할 수 없습니다")
            else:
                self.empty("기준을 넘는 후보가 없습니다. 방식을 some 으로 바꾸거나 나이·지표를 바꿔 보세요")
            return
        self.say(f"{pos} / {metric} / {mode.upper()} 비교: {len(rows)}명")
        self.say(table(
            ["순위", "ID", "이름", "나이", "값", "비교 월클 수", "월클 최댓값", "월클 최솟값"],
            [[i, r["player_id"], r["name"], r["age"], r["value"], r["n_wc"], r["wc_max"], r["wc_min"]]
             for i, r in enumerate(rows, 1)],
        ))

    # ---- 워치리스트 -------------------------------------------------------
    def watch_menu(self) -> None:
        uid = self.user.user_id

        def show() -> None:
            rows = watchlist.list_watchlist(self.conn, uid)
            if not rows:
                self.empty("워치리스트가 비어 있습니다. 2 번 메뉴로 선수를 추가하세요")
                return
            self.say(table(["ID", "이름", "포지션", "구단", "시장가치", "메모"],
                           [[r["player_id"], r["name"], r["pos_group"], r["current_club_name"],
                             eur(r["latest_value_eur"]), r["memo"]] for r in rows]))

        def add() -> None:
            pid = self.pick_player()
            if pid is None:
                return
            memo = self.io.text("메모(200자 이하, 빈 입력=없음): ", blank_ok=True) or None
            watchlist.add_to_watchlist(self.conn, uid, pid, memo)
            self.say("추가했습니다.")

        def owned_pid(prompt: str) -> int | None:
            pid = self.io.integer(prompt)
            if not watchlist.is_watched(self.conn, uid, pid):  # 입력 전에 먼저 확인
                self.say("권한 없음 또는 없음: 내 워치리스트에 없는 선수입니다.")
                return None
            return pid

        def edit() -> None:
            pid = owned_pid("메모를 수정할 선수 ID: ")
            if pid is None:
                return
            memo = self.io.text("새 메모(빈 입력=메모 삭제): ", blank_ok=True) or None
            ok = watchlist.update_watch_memo(self.conn, uid, pid, memo)
            self.say("수정했습니다." if ok else "권한 없음 또는 없음: 내 워치리스트에 없는 선수입니다.")

        def remove() -> None:
            pid = owned_pid("삭제할 선수 ID: ")
            if pid is None or not self.io.confirm("워치리스트에서 삭제할까요?"):
                return
            ok = watchlist.remove_from_watchlist(self.conn, uid, pid)
            self.say("삭제했습니다." if ok else "권한 없음 또는 없음: 내 워치리스트에 없는 선수입니다.")

        self.menu("워치리스트", [("1", "조회", show), ("2", "추가", add), ("3", "메모 수정", edit), ("4", "삭제", remove)], "뒤로")

    # ---- 노트 -------------------------------------------------------------
    def note_menu(self) -> None:
        uid = self.user.user_id

        def show_all() -> None:
            rows = notes.list_my_notes(self.conn, uid)
            if not rows:
                self.empty("작성한 노트가 없습니다. 3 번 메뉴로 작성하세요")
                return
            self.say(table(["노트", "선수", "평점", "내용", "수정일"],
                           [[r["note_id"], r["player_name"], r["rating"], r["body"].replace("\n", " "),
                             local_time(r["updated_at"])] for r in rows], max_col=50))

        def show_player() -> None:
            pid = self.pick_player()
            if pid is None:
                return
            rows = notes.list_notes_for_player(self.conn, uid, pid)
            if not rows:
                self.empty("이 선수에 대한 내 노트가 없습니다")
                return
            self.say(table(["노트", "평점", "내용", "수정일"],
                           [[r["note_id"], r["rating"], r["body"].replace("\n", " "), local_time(r["updated_at"])]
                            for r in rows], max_col=60))

        def create() -> None:
            pid = self.pick_player()
            if pid is None:
                return
            rating = self.io.integer("평점(1~5): ", 1, 5)
            body = self.io.text("내용(2000자 이하): ")
            nid = notes.create_note(self.conn, uid, pid, rating, body)
            self.say(f"노트 #{nid} 를 저장했습니다.")

        def owned_nid(prompt: str) -> int | None:
            nid = self.io.integer(prompt)
            if not notes.note_owned(self.conn, uid, nid):  # 평점·내용을 받기 전에 먼저 확인
                self.say("권한 없음 또는 없음: 내 노트가 아니거나 존재하지 않습니다.")
                return None
            return nid

        def edit() -> None:
            nid = owned_nid("수정할 노트 번호: ")
            if nid is None:
                return
            rating = self.io.integer("새 평점 1~5(빈 입력=유지): ", 1, 5, blank_ok=True)
            body = self.io.text("새 내용(빈 입력=유지): ", blank_ok=True) or None
            if rating is None and body is None:
                self.say("바꿀 내용이 없습니다.")
                return
            ok = notes.update_note(self.conn, uid, nid, rating=rating, body=body)
            self.say("수정했습니다." if ok else "권한 없음 또는 없음: 내 노트가 아니거나 존재하지 않습니다.")

        def delete() -> None:
            nid = owned_nid("삭제할 노트 번호: ")
            if nid is None or not self.io.confirm("노트를 삭제할까요?"):
                return
            ok = notes.delete_note(self.conn, uid, nid)
            self.say("삭제했습니다." if ok else "권한 없음 또는 없음: 내 노트가 아니거나 존재하지 않습니다.")

        self.menu("스카우팅 노트", [("1", "내 노트 전체 조회", show_all), ("2", "선수별 조회", show_player),
                                   ("3", "작성", create), ("4", "수정", edit), ("5", "삭제", delete)], "뒤로")

    # ---- 관리자 -----------------------------------------------------------
    def status(self) -> None:
        st = admin.data_status(self.conn)
        self.say(table(["테이블", "행 수"], [[t, n] for t, n in st["tables"].items()]))
        self.say()
        self.say(table(["ID", "스냅샷", "as_of", "빌드 시각"],
                       [[s["snapshot_id"], s["name"], s["as_of_date"], local_time(s["built_at"]) if s["built_at"] else "미완료"]
                        for s in st["snapshots"]]))

    def rebuild(self) -> None:
        snap = self.pick_snapshot(built_only=False)
        if snap is None:
            return
        if not self.io.confirm(f"스냅샷 {snap['name']} 을(를) 재계산합니다. 시간이 걸릴 수 있습니다. 계속할까요?"):
            return
        res = self.with_retry(lambda: admin.rebuild_snapshot(self.conn, snap["snapshot_id"], actor=self.user))
        if res is not None:
            self.say(f"재계산 완료: {res}")

    def definitions(self) -> None:
        def show() -> None:
            self.say(table(["ID", "코드", "이름", "규칙", "임계값", "GK 임계값", "시즌 수", "리그 분", "CL 분"],
                           [[d["def_id"], d["code"], d["name_ko"], d["rule_type"], d["value_threshold_eur"],
                             d["gk_value_threshold_eur"], d["min_seasons"], d["min_league_minutes"],
                             d["min_cl_minutes"]] for d in recommend.list_definitions(self.conn)]))

        def add() -> None:
            code = self.io.text("코드(영문, 고유): ")
            name = self.io.text("이름: ")
            rule = self.io.choose("규칙 종류", [("peak_value", "최고 시장가치"), ("big5_regular", "빅5 주전 + CL")])
            if rule is None:
                return
            if rule == "peak_value":
                f = dict(value_threshold_eur=self.io.integer("임계값(€, 양수): ", 1),
                         gk_value_threshold_eur=self.io.integer("GK 임계값(€, 양수): ", 1))
            else:
                f = dict(min_seasons=self.io.integer("최소 시즌 수(양수): ", 1),
                         min_league_minutes=self.io.integer("시즌당 최소 리그 분(양수): ", 1),
                         min_cl_minutes=self.io.integer("CL 최소 분(0 이상): ", 0))
            did = admin.create_definition(self.conn, self.user, code=code, name_ko=name, rule_type=rule, **f)
            self.say(f"정의 #{did} 를 추가하고 라벨을 계산했습니다.")

        def edit() -> None:
            d = self.pick_definition()
            if d is None:
                return
            f: dict = {}
            name = self.io.text("새 이름(빈 입력=유지): ", blank_ok=True)
            if name:
                f["name_ko"] = name
            if d["rule_type"] == "peak_value":
                for col, label in (("value_threshold_eur", "임계값"), ("gk_value_threshold_eur", "GK 임계값")):
                    v = self.io.integer(f"새 {label}(빈 입력=유지): ", 1, blank_ok=True)
                    if v is not None:
                        f[col] = v
            else:
                for col, label, lo in (("min_seasons", "최소 시즌 수", 1), ("min_league_minutes", "최소 리그 분", 1),
                                       ("min_cl_minutes", "CL 최소 분", 0)):
                    v = self.io.integer(f"새 {label}(빈 입력=유지): ", lo, blank_ok=True)
                    if v is not None:
                        f[col] = v
            if not f:
                self.say("바꿀 내용이 없습니다.")
                return
            ok = admin.update_definition(self.conn, self.user, d["def_id"], **f)
            self.say("수정하고 라벨을 다시 계산했습니다." if ok else "존재하지 않는 정의입니다.")

        def delete() -> None:
            d = self.pick_definition()
            if d is None:
                return
            if self.io.confirm(f"정의 {d['code']} 와 그 라벨을 삭제할까요?"):
                ok = admin.delete_definition(self.conn, self.user, d["def_id"])
                self.say("삭제했습니다." if ok else "존재하지 않는 정의입니다.")

        self.menu("월클 정의 관리", [("1", "조회", show), ("2", "추가", add), ("3", "수정", edit), ("4", "삭제", delete)], "뒤로")

    def backtest(self) -> None:
        runs = recommend.list_runs(self.conn)
        if not runs:
            self.say("추천 run 이 없습니다.")
            return
        self.say(table(["run", "스냅샷", "정의", "method", "포지션", "top_n"],
                       [[r["run_id"], r["snapshot"], r["def_code"], r["method"], r["pos_group"], r["top_n"]]
                        for r in runs[:30]]))
        rid = self.io.integer("평가할 run 번호(빈 입력=취소): ", blank_ok=True)
        if rid is None:
            return
        run = recommend.get_run(self.conn, rid)
        if run is None:
            self.say("존재하지 않는 run 입니다.")
            return
        out = self.pick_snapshot()
        if out is None:
            return
        ks = tuple(k for k in (20, 50) if k <= run["top_n"]) or (run["top_n"],)
        res = self.with_retry(
            lambda: backtest.evaluate_run(self.conn, rid, outcome_snapshot_id=out["snapshot_id"], k_values=ks)
        )
        if res is None:
            return
        self.say(table(["k", "후보 수", "정답 수", "hits", "precision", "recall"],
                       [[r["k"], r["n_candidates"], r["n_positive"], r["hits"], r["precision"], r["recall"]]
                        for r in res]))

    def change_role(self) -> None:
        self.say(table(["ID", "사용자", "역할", "워치", "노트", "run"],
                       [[u["user_id"], u["username"], u["role"], u["watchlist_count"], u["note_count"],
                         u["run_count"]] for u in users.list_users(self.conn, self.user)]))
        uid = self.io.integer("대상 사용자 ID: ")
        role = self.io.choose("새 역할", [("scout", "scout"), ("admin", "admin")])
        if role is None:
            return
        users.set_role(self.conn, self.user, uid, role)
        self.say("역할을 변경했습니다.")


def describe_db_error(e: Exception, path: str | None) -> str:
    """--db 로 연 DB 를 쓸 수 없을 때의 한국어 안내."""
    p = dbm.db_path(path)
    msg = str(e).lower()
    if "locked" in msg or "busy" in msg:
        return f"DB 파일이 다른 프로세스에 의해 잠겨 있습니다: {p}. 잠시 후 다시 시도해 주세요."
    if "unable to open" in msg:
        if p.is_dir():
            return f"경로가 디렉터리입니다. DB 파일 경로를 지정해 주세요: {p}"
        if not p.parent.exists():
            return f"DB 파일의 상위 폴더가 없습니다: {p.parent}"
        return f"DB 파일을 열 수 없습니다(권한 또는 경로 문제): {p}"
    if "not a database" in msg or "malformed" in msg or "corrupt" in msg:
        return f"DB 파일이 손상되었거나 SQLite 파일이 아닙니다: {p}"
    return f"DB 를 열 수 없습니다: {p} ({e})"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    has_tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    if not has_tables:
        dbm.apply_sql(conn)


def main(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input,
         print_fn: Callable[..., None] = print) -> int:
    parser = argparse.ArgumentParser(prog="python -m scouting", description="축구 유망주 스카우팅 DB")
    parser.add_argument("--db", help="SQLite 파일 경로 (기본: data/scouting.sqlite)")
    sub = parser.add_subparsers(dest="cmd")
    ca = sub.add_parser("create-admin", help="관리자 계정 생성")
    ca.add_argument("username")
    ca.add_argument("--password", required=True)
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):  # 한글 출력이 cp949 등에서 깨지지 않게
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if input_fn is input and sys.stdin is not None and not sys.stdin.isatty():
        try:
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    conn = None
    try:
        conn = dbm.connect(args.db)
        _ensure_schema(conn)
    except (sqlite3.Error, RuntimeError) as e:
        print_fn(f"[오류] {describe_db_error(e, args.db)}")
        if conn is not None:
            conn.close()
        return 1
    try:
        if args.cmd == "create-admin":
            try:
                uid = users.register(conn, args.username, args.password, "admin")
            except ValueError as e:
                print_fn(f"[오류] {e}")
                return 1
            print_fn(f"관리자 '{args.username}' 생성 완료 (user_id={uid}).")
            return 0
        app = App(conn, IO(input_fn, print_fn))
        try:
            app.run()
        except Quit:
            print_fn("\n입력이 종료되어 프로그램을 마칩니다.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
