from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from scouting.services import players
from .. import logic
from ..common import clear_tree, make_tree

PAGE_SIZE = 20


class SearchView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.page = 0
        self.total = 0
        self.last_filters: dict | None = None
        self.pending = False

        panel = ttk.LabelFrame(self, text="검색 조건")
        panel.pack(side="left", fill="y", padx=(10, 4), pady=8)
        self.name = tk.StringVar()
        self.pos = tk.StringVar()
        self.nat = tk.StringVar()
        self.club = tk.StringVar()
        self.min_age = tk.StringVar()
        self.max_age = tk.StringVar()
        width = 22
        self.entries = []

        def field(label, widget):
            ttk.Label(panel, text=label).pack(anchor="w", padx=8, pady=(8, 0))
            widget.pack(fill="x", padx=8)
            self.entries.append(widget)
            return widget

        field("이름", ttk.Entry(panel, textvariable=self.name, width=width))
        field("포지션군", ttk.Combobox(panel, textvariable=self.pos, values=tuple(logic.POS_LABELS),
                                      width=width - 2, state="readonly"))
        field("국적", ttk.Combobox(panel, textvariable=self.nat, values=("", *app.nationalities), width=width - 2))
        field("거쳐 간 구단 (이름 포함)", ttk.Entry(panel, textvariable=self.club, width=width))
        ages = ttk.Frame(panel)
        ttk.Label(panel, text="나이 범위 (기준일 만 나이)").pack(anchor="w", padx=8, pady=(8, 0))
        ages.pack(fill="x", padx=8)
        ttk.Entry(ages, textvariable=self.min_age, width=6).pack(side="left")
        ttk.Label(ages, text=" ~ ").pack(side="left")
        ttk.Entry(ages, textvariable=self.max_age, width=6).pack(side="left")
        self.entries += list(ages.winfo_children())
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", padx=8, pady=12)
        self.search_btn = ttk.Button(buttons, text="검색", command=lambda: self.search(0))
        self.search_btn.pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, text="초기화", command=self.reset).pack(side="left", padx=(6, 0))
        for widget in self.entries:
            widget.bind("<Return>", lambda _e: self.search(0))

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=8)
        columns = (
            ("name", "이름", 170, True), ("pos", "포지션", 70), ("nat", "국적", 110, True),
            ("age", "나이", 45), ("club", "현재 구단", 150, True), ("value", "현재 가치", 85), ("peak", "최고 가치", 85),
        )
        self.tree = make_tree(right, columns, height=20, left=("name", "pos", "nat", "club"))
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<Return>", lambda _e: self.open_selected())
        foot = ttk.Frame(right)
        foot.pack(fill="x", pady=4)
        self.count = ttk.Label(foot, text="조건을 입력하고 검색하세요. 더블클릭 또는 Enter로 커리어를 엽니다.")
        self.count.pack(side="left")
        self.forward_btn = ttk.Button(foot, text="커리어로 ▶", command=lambda: app.show_career())
        self.forward_btn.pack(side="right", padx=(4, 8))
        ttk.Button(foot, text="커리어 보기", command=self.open_selected).pack(side="right", padx=4)
        self.next = ttk.Button(foot, text="다음", command=lambda: self.search(self.page + 1, use_last=True), state="disabled")
        self.next.pack(side="right", padx=4)
        self.prev = ttk.Button(foot, text="이전", command=lambda: self.search(self.page - 1, use_last=True), state="disabled")
        self.prev.pack(side="right")

    def refresh_nav(self):
        self.forward_btn.configure(state="normal" if self.app.career.player_id else "disabled")

    def reset(self):
        for var in (self.name, self.pos, self.nat, self.club, self.min_age, self.max_age):
            var.set("")

    def filters(self):
        nat = self.nat.get().strip() or None
        if nat and nat not in self.app.nationalities:
            raise ValueError("국적: 목록에 있는 값을 선택해 주세요.")
        lo = logic.parse_int(self.min_age.get(), "최소 나이", 1, 100)
        hi = logic.parse_int(self.max_age.get(), "최대 나이", 1, 100)
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("나이: 최소가 최대보다 클 수 없습니다.")
        return {
            "name": self.name.get().strip() or None,
            "pos_group": logic.pos_group_of(self.pos.get()),
            "nationality": nat,
            "club_name": self.club.get().strip() or None,
            "min_age": lo,
            "max_age": hi,
        }

    def search(self, page=0, *, use_last=False, open_index=None):
        """use_last: 페이지 이동처럼 마지막으로 검색한 조건을 그대로 쓴다. open_index: 로드 후 그 위치의 선수를 연다."""
        try:
            filters = self.last_filters if (use_last and self.last_filters is not None) else self.filters()
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
            for row in rows:
                self.tree.insert("", "end", iid=str(row["player_id"]), values=(
                    row["name"], logic.POS_KO.get(row["pos_group"], "-"),
                    row["country_of_citizenship"] or "-", "-" if row["age"] is None else row["age"],
                    row["current_club_name"] or "-", logic.eur(row["latest_value_eur"]),
                    logic.eur(row["peak_value_eur"]),
                ))
            pages = max(1, -(-self.total // PAGE_SIZE))
            self.count.configure(text=f"총 {self.total:,}명 · {page + 1}/{pages} 페이지")
            self.prev.configure(state="normal" if page else "disabled")
            self.next.configure(state="normal" if (page + 1) * PAGE_SIZE < self.total else "disabled")
            children = self.tree.get_children()
            if children:
                self.select_row(0)
            if open_index is not None and children:
                self.open_index(open_index)

        self.app.jobs.submit("선수 검색", job, done, button=self.search_btn,
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
