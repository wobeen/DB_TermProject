from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from scouting.services import players
from .. import logic, theme
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

        rail = ttk.Frame(self, style="Rail.TFrame", width=round(250 * app.dpi / 96.0))
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        ttk.Label(rail, text="검색 조건", style="RailTitle.TLabel").pack(anchor="w", padx=14, pady=(14, 4))
        self.name = tk.StringVar()
        self.pos = tk.StringVar()
        self.nat = tk.StringVar()
        self.club = tk.StringVar()
        self.min_age = tk.StringVar()
        self.max_age = tk.StringVar()
        self.entries = []

        def field(label, widget):
            ttk.Label(rail, text=label, style="Rail.TLabel").pack(anchor="w", padx=14, pady=(10, 2))
            widget.pack(fill="x", padx=14)
            self.entries.append(widget)
            return widget

        field("이름", ttk.Entry(rail, textvariable=self.name))
        field("포지션군", ttk.Combobox(rail, textvariable=self.pos, values=tuple(logic.POS_LABELS),
                                      state="readonly"))
        field("국적", ttk.Combobox(rail, textvariable=self.nat, values=("", *app.nationalities)))
        field("거쳐 간 구단 (이름 일부)", ttk.Entry(rail, textvariable=self.club))
        ttk.Label(rail, text="나이 범위 (기준일 만 나이)", style="Rail.TLabel").pack(anchor="w", padx=14, pady=(10, 2))
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
        self.search_btn.pack(fill="x", padx=14, pady=(18, 6))
        ttk.Button(rail, text="초기화", style="Rail.TButton", command=self.reset).pack(fill="x", padx=14)
        for widget in self.entries:
            widget.bind("<Return>", lambda _e: self.search(0))

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(14, 14), pady=12)
        top = ttk.Frame(right)
        top.pack(fill="x")
        self.count = ttk.Label(top, text=logic.DESCRIPTION, style="Muted.TLabel")
        self.count.pack(side="left")
        self.pager = ttk.Label(top, text="", style="Muted.TLabel")
        self.pager.pack(side="right")
        columns = (
            ("name", "이름", 170, True), ("pos", "포지션", 70), ("nat", "국적", 120, True),
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
            for i, row in enumerate(rows):
                self.tree.insert("", "end", iid=str(row["player_id"]), tags=(f"zebra{i % 2}",), values=(
                    row["name"], logic.POS_KO.get(row["pos_group"], "-"),
                    row["country_of_citizenship"] or "-", str("-" if row["age"] is None else row["age"]) + "  ",
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
