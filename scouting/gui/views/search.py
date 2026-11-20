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

        # 거쳐 간 구단: 제안은 도와 줄 뿐, 일부만 써도 검색된다
        label("거쳐 간 구단 (이름 일부)")
        self.club_entry = ttk.Entry(rail, textvariable=self.club)
        self.club_entry.pack(fill="x", padx=14)
        self.club_auto = Autocomplete(
            self.club_entry, app, min_chars=2, render=lambda item: item["name"],
            job=lambda text: (lambda conn: players.suggest_clubs(conn, text, limit=8)),
            on_accept=lambda item: self.club.set(item["name"]))
        self.entries.append(self.club_entry)

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
            ("name", "이름", 170, True), ("pos", "포지션", 100), ("nat", "국적", 120, True),
            ("age", "나이", 50), ("club", "현재 구단", 170, True), ("value", "현재 가치", 90), ("peak", "최고 가치", 90),
        )
        self.tree = make_tree(right, columns, height=18, left=("name", "pos", "nat", "club"))
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
        self.forward_btn = ttk.Button(foot, text="열어 둔 커리어 ▶", command=lambda: app.show_career())
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

    def refresh_nav(self):
        self.forward_btn.configure(state="normal" if self.app.career.player_id else "disabled")

    def reset(self):
        for var in (self.name, self.nat, self.club, self.min_age, self.max_age):
            var.set("")
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
        return {
            "name": self.name.get().strip() or None,
            "nationality": nat,
            "club_name": self.club.get().strip() or None,
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
            total = players.count_players_ext(connection, **filters)
            rows = players.search_players_ext(connection, **filters, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
            return total, rows

        def done(data):
            self.total, rows = data
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
                    row["current_club_name"] or "-", logic.eur(row["latest_value_eur"]) + "  ",
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
