from __future__ import annotations

from tkinter import ttk

from scouting.services import recommend
from .. import logic
from ..common import clear_tree, make_tree


class RunsView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        ttk.Button(self, text="새로고침", command=self.refresh).pack(anchor="w", padx=8, pady=5)
        self.runs = make_tree(self, (
            ("run", "run", 65), ("created", "생성", 145), ("snap", "스냅샷", 90),
            ("def", "정의", 130), ("method", "방식", 90), ("pos", "포지션", 70),
        ), height=6)
        self.runs.bind("<<TreeviewSelect>>", lambda _event: self.show_items())
        self.items = make_tree(self, (
            ("rank", "순위", 55), ("id", "ID", 70), ("name", "이름", 170, True),
            ("score", "점수", 90), ("value", "시장가치", 100),
        ), height=6)
        self.items.bind("<<TreeviewSelect>>", lambda _event: self.show_evidence())
        self.evidence = make_tree(self, (
            ("id", "이웃 ID", 80), ("name", "이름", 170, True), ("season", "시즌", 65),
            ("distance", "거리", 90), ("wc", "월클", 55),
        ), height=5)

    def refresh(self):
        clear_tree(self.runs)
        if not self.app.user:
            return
        for row in recommend.list_runs(self.app.conn, self.app.user.user_id):
            self.runs.insert("", "end", iid=str(row["run_id"]), values=(
                row["run_id"], logic.local_time(row["created_at"]), row["snapshot"], row["def_code"],
                row["method"], row["pos_group"],
            ))

    def show_items(self):
        clear_tree(self.items)
        clear_tree(self.evidence)
        selection = self.runs.selection()
        if not selection:
            return
        for row in recommend.run_items(self.app.conn, int(selection[0])):
            self.items.insert("", "end", iid=str(row["player_id"]), values=(
                row["rank"], row["player_id"], row["name"], f"{row['score']:.4f}", logic.eur(row["value_eur"]),
            ))

    def show_evidence(self):
        clear_tree(self.evidence)
        run_selection = self.runs.selection()
        player_selection = self.items.selection()
        if not run_selection or not player_selection:
            return
        rows = recommend.run_evidence(self.app.conn, int(run_selection[0]), int(player_selection[0]))
        for row in rows:
            self.evidence.insert("", "end", values=(
                row["neighbor_player_id"], row["name"], row["neighbor_season"],
                f"{row['distance']:.4f}", "O" if row["neighbor_is_wc"] else "-",
            ))
