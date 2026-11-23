from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from scouting.services import players
from .. import logic, theme
from ..common import clear_tree, make_tree
from ..widgets import Autocomplete, PitchPicker

PAGE_SIZE = 20


class InlineError(ValueError):
    """입력 칸 아래에 직접 안내를 띄운 오류: 대화상자 없이 검색만 막는다."""


class SearchView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.page = 0
        self.total = 0
        self.last_filters: dict | None = None
        self.pending = False

        rail = ttk.Frame(self, style="Rail.TFrame", width=round(250 * app.dpi / 96.0))
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        ttk.Label(rail, text="검색 조건", style="RailTitle.TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        self.name = tk.StringVar()
        self.formation = tk.StringVar(value=logic.NO_FORMATION)
        self.nat = tk.StringVar()
        self.club = tk.StringVar()
        self.min_age = tk.StringVar()
        self.max_age = tk.StringVar()
        self.entries = []

        def label(text, pady=(8, 2)):
            ttk.Label(rail, text=text, style="Rail.TLabel").pack(anchor="w", padx=14, pady=pady)

        # 이름: 두 글자부터 연관검색어, 고르면 바로 그 선수의 커리어
        label("이름")
        self.name_entry = ttk.Entry(rail, textvariable=self.name)
        self.name_entry.pack(fill="x", padx=14)
        self.name_auto = Autocomplete(
            self.name_entry, app, min_chars=2, render=logic.suggestion_row,
            job=lambda text: (lambda conn: players.suggest_players(conn, text, limit=8)),
            on_accept=self.accept_player)
        self.entries.append(self.name_entry)

        # 포메이션 -> 자리 고르기
        label("포메이션")
        self.formation_box = ttk.Combobox(rail, textvariable=self.formation, state="readonly",
                                          values=(logic.NO_FORMATION, *logic.FORMATIONS))
        self.formation_box.pack(fill="x", padx=14)
        self.formation_box.bind("<<ComboboxSelected>>", lambda _e: self.on_formation())
        self.picker = PitchPicker(rail, app, on_change=self.refresh_picked)
        self.picker.pack(padx=14, pady=(6, 0), anchor="w")
        picked = ttk.Frame(rail, style="Rail.TFrame")
        picked.pack(fill="x", padx=14, pady=(2, 0))
        self.picked_label = ttk.Label(picked, text="", style="Rail.TLabel")
        self.picked_label.pack(side="left")
        self.clear_btn = ttk.Button(picked, text="지우기", style="Rail.TButton", width=6,
                                    command=self.picker.clear)
        self.clear_btn.pack(side="right")
        ttk.Label(rail, text="선수 등록 주 포지션 기준", style="RailNote.TLabel").pack(anchor="w", padx=14)
        self.refresh_picked()

        # 국적: 목록에서만 고른다 (한글 별칭도 찾는다)
        label("국적")
        self.nat_entry = ttk.Entry(rail, textvariable=self.nat)
        self.nat_entry.pack(fill="x", padx=14)
        self.nat_error = ttk.Label(rail, text=logic.NATIONALITY_ERROR, style="RailError.TLabel")
        self.nat_auto = Autocomplete(
            self.nat_entry, app, min_chars=1, render=str,
            local=lambda text: logic.suggest_nationalities(text, app.nationalities),
            on_accept=self.accept_nationality)
        self.nat.trace_add("write", lambda *_: self.nat_error.pack_forget())
        self.entries.append(self.nat_entry)

        # 거쳐 간 구단: 리그를 고른 뒤 구단을 고르거나, 구단 이름으로 찾는다. 직접 고른 구단이 이름 검색보다 우선한다.
        label("거쳐 간 구단: 리그")
        self.league = tk.StringVar(value=logic.LEAGUE_ALL)
        self.league_items = logic.league_options(app.leagues)
        self.league_box = ttk.Combobox(rail, textvariable=self.league, state="readonly",
                                       values=[label_ for label_, _ in self.league_items])
        self.league_box.pack(fill="x", padx=14)
        self.league_box.bind("<<ComboboxSelected>>", lambda _e: self.on_league())
        self.club_cache: dict[str, list[dict]] = {}
        self.club_items: list[tuple[str, int | None]] = [(logic.CLUB_ALL, None)]
        label("구단", pady=(6, 2))
        self.club_pick = tk.StringVar(value=logic.CLUB_ALL)
        self.club_box = ttk.Combobox(rail, textvariable=self.club_pick, state="disabled", values=[logic.CLUB_ALL])
        self.club_box.pack(fill="x", padx=14)
        self.club_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_club_note())
        label("구단 이름으로 찾기", pady=(6, 2))
        self.club_entry = ttk.Entry(rail, textvariable=self.club)
        self.club_entry.pack(fill="x", padx=14)
        self.club_auto = Autocomplete(
            self.club_entry, app, min_chars=2, render=lambda item: item["name"],
            job=lambda text: (lambda conn: players.suggest_clubs(conn, text, limit=8)),
            on_accept=lambda item: self.club.set(item["name"]))
        self.entries.append(self.club_entry)
        self.club_note = ttk.Label(rail, text="", style="RailNote.TLabel")
        self.club_note.pack(anchor="w", padx=14)
        self.club.trace_add("write", lambda *_: self.refresh_club_note())
        self.refresh_club_note()

        label("나이 범위 (기준일 만 나이)")
        ages = ttk.Frame(rail, style="Rail.TFrame")
        ages.pack(fill="x", padx=14)
        low = ttk.Entry(ages, textvariable=self.min_age, width=5)
        low.pack(side="left")
        ttk.Label(ages, text="부터", style="Rail.TLabel").pack(side="left", padx=4)
        high = ttk.Entry(ages, textvariable=self.max_age, width=5)
        high.pack(side="left")
        ttk.Label(ages, text="까지", style="Rail.TLabel").pack(side="left", padx=4)
        self.entries += [low, high]
        self.search_btn = ttk.Button(rail, text="검색", style="RailPrimary.TButton",
                                     command=lambda: self.search(0))
        self.search_btn.pack(fill="x", padx=14, pady=(14, 4))
        ttk.Button(rail, text="초기화", style="Rail.TButton", command=self.reset).pack(fill="x", padx=14)
        for widget in self.entries:      # 연관검색어 Enter 처리 뒤에 일반 검색이 이어지도록 add="+"
            widget.bind("<Return>", lambda _e: self.search(0), add="+")

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(14, 14), pady=12)
        top = ttk.Frame(right)
        top.pack(fill="x")
        self.count = ttk.Label(top, text=logic.DESCRIPTION, style="Muted.TLabel")
        self.count.pack(side="left")
        self.pager = ttk.Label(top, text="", style="Muted.TLabel")
        self.pager.pack(side="right")
        columns = (
            ("name", "이름", 120, True), ("pos", "포지션", 76), ("nat", "국적", 84, True),
            ("age", "나이", 44), ("club", "현재 구단", 150, True), ("tenure", "재직 기간", 300),
            ("value", "현재 가치", 70), ("peak", "최고 가치", 70),
        )
        self.tree = make_tree(right, columns, height=18, left=("name", "pos", "nat", "club", "tenure"))
        self.all_columns = tuple(c[0] for c in columns)
        self.base_widths = {c[0]: round(c[2] * app.dpi / 96.0) for c in columns}
        self.show_tenure(False)
        self.tree.tag_configure("zebra1", background=theme.ZEBRA)
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<Return>", lambda _e: self.open_selected())
        self.empty = ttk.Label(self.tree, text=logic.EMPTY_SEARCH, style="Empty.TLabel")
        foot = ttk.Frame(right)
        foot.pack(fill="x", pady=(6, 0))
        ttk.Button(foot, text="커리어 보기", style="Primary.TButton", command=self.open_selected).pack(side="right")
        self.next = ttk.Button(foot, text="다음", command=lambda: self.search(self.page + 1, use_last=True),
                               state="disabled")
        self.next.pack(side="right", padx=8)
        self.prev = ttk.Button(foot, text="이전", command=lambda: self.search(self.page - 1, use_last=True),
                               state="disabled")
        self.prev.pack(side="right")
        self.forward_btn = ttk.Button(foot, text="방금 본 커리어", command=lambda: app.show_career())
        self.forward_btn.pack(side="left")

    # --- 연관검색어 / 포메이션 --------------------------------------------------------
    def accept_player(self, item):
        self.name.set(item["name"])
        self.app.open_career(item["player_id"])

    def accept_nationality(self, country):
        self.nat.set(country)
        self.nat_error.pack_forget()

    def on_formation(self):
        self.picker.set_formation(self.formation.get())

    def set_formation(self, name):
        self.formation.set(name or logic.NO_FORMATION)
        self.on_formation()

    def refresh_picked(self):
        codes = self.picker.codes()
        self.picked_label.configure(text="선택한 포지션: " + (", ".join(codes) if codes else "없음"))
        self.clear_btn.state(["!disabled"] if codes else ["disabled"])

    def show_tenure(self, visible: bool):
        cols = self.all_columns if visible else tuple(c for c in self.all_columns if c != "tenure")
        self.tree.configure(displaycolumns=cols)
        for col in cols:        # 열을 보이거나 숨길 때 늘어난 너비를 처음 값으로 되돌려 남는 폭만 늘어나는 열에 나눠 준다
            self.tree.column(col, width=self.base_widths[col])

    def league_id(self):
        return dict(self.league_items).get(self.league.get())

    def league_clubs(self, league_id):
        if league_id not in self.club_cache:
            self.club_cache[league_id] = players.league_clubs(self.app.conn, league_id)    # 1~2 ms, 리그별로 한 번만
        return self.club_cache[league_id]

    def on_league(self):
        league_id = self.league_id()
        self.club_pick.set(logic.CLUB_ALL)
        if league_id is None:
            self.club_items = [(logic.CLUB_ALL, None)]
            self.club_box.configure(state="disabled", values=[logic.CLUB_ALL])
        else:
            self.club_items = logic.club_options(self.league_clubs(league_id))
            self.club_box.configure(state="readonly", values=[label_ for label_, _ in self.club_items])
        self.refresh_club_note()

    def club_filter(self):
        """(적용 방식, 구단 id 목록|None, 이름 일부): 직접 고른 구단 > 이름 일부 > 리그 전체."""
        league_id = self.league_id()
        league_ids = [c["club_id"] for c in self.league_clubs(league_id)] if league_id else None
        picked = dict(self.club_items).get(self.club_pick.get()) if league_id else None
        mode, ids = logic.club_filter(picked, league_ids, self.club.get())
        return mode, ids, (self.club.get().strip() or None)

    def refresh_club_note(self):
        mode, _ids, text = self.club_filter()
        self.club_note.configure(text=logic.club_filter_note(
            mode, club=self.club_pick.get(), league=self.league.get(), text=text or ""))

    def refresh_nav(self):
        self.forward_btn.configure(state="normal" if self.app.career.player_id else "disabled")

    def reset(self):
        for var in (self.name, self.nat, self.club, self.min_age, self.max_age):
            var.set("")
        self.league.set(logic.LEAGUE_ALL)
        self.on_league()
        self.set_formation("")

    def filters(self):
        nat = None
        if self.nat.get().strip():
            nat = logic.resolve_nationality(self.nat.get(), self.app.nationalities)
            if nat is None:
                self.nat_error.pack(anchor="w", padx=14, pady=(3, 0), after=self.nat_entry)
                raise InlineError(logic.NATIONALITY_ERROR)
            self.nat.set(nat)             # 한글 별칭으로 쓴 경우 정식 이름으로 바꿔 보여 준다
        lo = logic.parse_int(self.min_age.get(), "최소 나이", 1, 100)
        hi = logic.parse_int(self.max_age.get(), "최대 나이", 1, 100)
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("나이: 최소가 최대보다 클 수 없습니다.")
        mode, club_ids, club_text = self.club_filter()
        return {
            "name": self.name.get().strip() or None,
            "nationality": nat,
            "club_mode": mode,
            "club_ids": club_ids,
            "club_text": club_text if mode == "text" else None,
            "min_age": lo,
            "max_age": hi,
            "sub_positions": logic.sub_positions_for(self.picker.codes()) or None,
        }

    def search(self, page=0, *, use_last=False, open_index=None):
        """use_last: 페이지 이동처럼 마지막으로 검색한 조건을 그대로 쓴다. open_index: 로드 후 그 위치의 선수를 연다."""
        for auto in (self.name_auto, self.nat_auto, self.club_auto):
            auto.close()
        try:
            filters = self.last_filters if (use_last and self.last_filters is not None) else self.filters()
        except InlineError as exc:
            self.app.set_status(str(exc))
            return
        except ValueError as exc:
            self.app.error(exc)
            return
        page = max(0, page)
        self.pending = True

        def job(connection):
            kw = {k: v for k, v in filters.items() if k not in ("club_mode", "club_ids", "club_text")}
            ids = filters["club_ids"]
            if ids is None and filters["club_text"]:
                ids = players.club_ids_by_name(connection, filters["club_text"])    # 한 번에 풀어 id 로 거른다
                if not ids:
                    return 0, [], {}, None
            total = players.count_players_ext(connection, club_ids=ids, **kw)
            rows = players.search_players_ext(connection, club_ids=ids, **kw, limit=PAGE_SIZE,
                                              offset=page * PAGE_SIZE)
            tenures = players.club_tenures(connection, [r["player_id"] for r in rows], ids) if ids else {}
            return total, rows, tenures, ids

        def done(data):
            self.total, rows, tenures, club_ids = data
            self.show_tenure(bool(club_ids))
            self.page = page
            self.last_filters = filters
            self.pending = False
            if not use_last:                    # 새 검색이면 열려 있던 커리어는 더 이상 이 목록의 일부가 아니다
                self.app.career.index = None
            clear_tree(self.tree)
            for i, row in enumerate(rows):
                self.tree.insert("", "end", iid=str(row["player_id"]), tags=(f"zebra{i % 2}",), values=(
                    row["name"], logic.position_label(row["pos_group"], row["sub_position"]),
                    row["country_of_citizenship"] or "-",
                    str("-" if row["age"] is None else row["age"]) + "  ",
                    row["current_club_name"] or "-", logic.stint_text(tenures.get(row["player_id"], [])),
                    logic.eur(row["latest_value_eur"]) + "  ",
                    logic.eur(row["peak_value_eur"]) + "  ",
                ))
            pages = max(1, -(-self.total // PAGE_SIZE))
            self.count.configure(text=f"결과 {self.total:,}명")
            self.pager.configure(text=f"{page + 1} / {pages} 쪽")
            self.prev.configure(state="normal" if page else "disabled")
            self.next.configure(state="normal" if (page + 1) * PAGE_SIZE < self.total else "disabled")
            children = self.tree.get_children()
            if children:
                self.empty.place_forget()
                self.select_row(0)
            else:
                self.empty.place(relx=0.5, rely=0.3, anchor="center")
            if open_index is not None and children:
                self.open_index(open_index)

        self.app.jobs.submit(
            "선수 검색", job, done, button=self.search_btn, busy="선수를 찾는 중",
            done=lambda result, t: f"선수 {result[0]:,}명을 찾았습니다 ({t:.1f}초)",
            on_error=lambda _e: setattr(self, "pending", False))

    def select_row(self, row):
        iid = self.tree.get_children()[row]
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)
        return int(iid)

    def open_index(self, index):
        """검색 결과 전체에서 index(0-based) 번째 선수를 연다. 다른 페이지면 그 페이지를 먼저 불러온다."""
        if self.pending or not 0 <= index < self.total:
            return
        page, row = divmod(index, PAGE_SIZE)
        if page != self.page:
            self.search(page, use_last=True, open_index=index)
            return
        self.app.open_career(self.select_row(row), index)

    def selected_pid(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def open_selected(self):
        player_id = self.selected_pid()
        if player_id is None:
            self.app.error(ValueError("선수를 선택해 주세요."))
            return
        self.app.open_career(player_id, self.page * PAGE_SIZE + self.tree.index(self.tree.selection()[0]))
