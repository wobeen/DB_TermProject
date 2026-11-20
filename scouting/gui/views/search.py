from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk

from scouting.services import players, watchlist
from .. import logic
from ..common import clear_tree, make_tree

PAGE_SIZE = 20


class SearchView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.page = 0
        self.total = 0
        bar = ttk.LabelFrame(self, text="검색 조건")
        bar.pack(fill="x", padx=8, pady=8)
        self.name = tk.StringVar()
        self.pos = tk.StringVar()
        self.age = tk.StringVar()
        self.league = tk.StringVar()
        fields = (("이름", self.name), ("포지션군", self.pos), ("최대 나이", self.age), ("리그 ID", self.league))
        for index, (label, variable) in enumerate(fields):
            ttk.Label(bar, text=label).grid(row=0, column=index * 2, padx=4, pady=6)
            if variable is self.pos:
                widget = ttk.Combobox(bar, textvariable=variable, values=("", *logic.POS_GROUPS), width=8, state="readonly")
            else:
                widget = ttk.Entry(bar, textvariable=variable, width=16)
            widget.grid(row=0, column=index * 2 + 1)
        self.search_btn = ttk.Button(bar, text="검색", command=lambda: self.search(0))
        self.search_btn.grid(row=0, column=8, padx=8)
        columns = (
            ("id", "ID", 80), ("name", "이름", 180, True), ("pos", "포지션", 70),
            ("age", "나이", 55), ("club", "현 구단", 180, True), ("value", "시장가치", 100),
        )
        self.tree = make_tree(self, columns)
        self.tree.bind("<Double-1>", lambda _event: self.open_profile())
        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=8, pady=5)
        self.count = ttk.Label(foot, text="총 0명")
        self.count.pack(side="left")
        self.prev = ttk.Button(foot, text="이전", command=lambda: self.search(self.page - 1))
        self.prev.pack(side="right")
        self.next = ttk.Button(foot, text="다음", command=lambda: self.search(self.page + 1))
        self.next.pack(side="right", padx=4)
        ttk.Button(foot, text="프로필", command=self.open_profile).pack(side="right", padx=4)
        ttk.Button(foot, text="워치리스트 추가", command=self.add_watch).pack(side="right", padx=4)

    def filters(self):
        max_age = logic.parse_int(self.age.get(), "최대 나이", 1, 100) if self.age.get().strip() else None
        league = self.league.get().strip() or None
        if league and not players.competition_exists(self.app.conn, league):
            raise ValueError("존재하지 않는 리그 ID입니다.")
        return {
            "name": self.name.get().strip() or None,
            "pos_group": self.pos.get() or None,
            "max_age": max_age,
            "competition_id": league,
        }

    def search(self, page=0):
        try:
            filters = self.filters()
        except ValueError as exc:
            self.app.error(exc)
            return
        page = max(0, page)

        def job(connection):
            total = players.count_players(connection, **filters)
            rows = players.search_players(connection, **filters, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
            return total, rows

        def done(data):
            self.total, rows = data
            self.page = page
            clear_tree(self.tree)
            for row in rows:
                self.tree.insert("", "end", iid=str(row["player_id"]), values=(
                    logic.identifier(row["player_id"]), row["name"], row["pos_group"], row["age"],
                    row["current_club_name"], logic.eur(row["latest_value_eur"]),
                ))
            self.count.configure(text=f"총 {self.total}명 · {page + 1}페이지")
            self.prev.configure(state="normal" if page else "disabled")
            self.next.configure(state="normal" if (page + 1) * PAGE_SIZE < self.total else "disabled")

        self.app.jobs.submit("선수 검색", job, done, button=self.search_btn)

    def selected_pid(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def open_profile(self):
        player_id = self.selected_pid()
        if player_id is None:
            self.app.error(ValueError("선수를 선택해 주세요."))
            return
        self.app.profile.load(player_id)
        self.app.notebook.select(self.app.profile)

    def add_watch(self):
        player_id = self.selected_pid()
        if player_id is None:
            self.app.error(ValueError("선수를 선택해 주세요."))
            return
        memo = simpledialog.askstring("워치리스트 추가", "메모(200자 이하, 선택):", parent=self)
        if memo is None:
            return
        try:
            watchlist.add_to_watchlist(self.app.conn, self.app.user.user_id, player_id, memo or None)
        except Exception as exc:
            self.app.error(exc)
            return
        self.app.set_status("워치리스트에 추가했습니다.")
        self.app.watch.refresh()
