from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from scouting.services import players
from .. import logic
from ..common import clear_tree, make_tree


class SimilarView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=8)
        self.player = tk.StringVar()
        self.snapshot = tk.StringVar(value=app.default_snapshot)
        self.season = tk.StringVar()
        self.k = tk.StringVar(value="10")
        self.definition = tk.StringVar(value=app.default_definition)
        ttk.Label(bar, text="선수 ID").grid(row=0, column=0, padx=3)
        ttk.Entry(bar, textvariable=self.player, width=10).grid(row=0, column=1)
        ttk.Label(bar, text="스냅샷").grid(row=0, column=2, padx=3)
        ttk.Combobox(bar, textvariable=self.snapshot, values=app.snapshot_names, width=14, state="readonly").grid(row=0, column=3)
        ttk.Label(bar, text="시즌").grid(row=0, column=4, padx=3)
        ttk.Entry(bar, textvariable=self.season, width=8).grid(row=0, column=5)
        ttk.Label(bar, text="k").grid(row=0, column=6, padx=3)
        ttk.Entry(bar, textvariable=self.k, width=5).grid(row=0, column=7)
        ttk.Label(bar, text="정의").grid(row=0, column=8, padx=3)
        ttk.Combobox(bar, textvariable=self.definition, values=app.definition_codes, width=18, state="readonly").grid(row=0, column=9)
        self.btn = ttk.Button(bar, text="유사 선수 찾기", command=self.run)
        self.btn.grid(row=0, column=10, padx=8)
        columns = (
            ("rank", "순위", 50), ("id", "ID", 80), ("name", "이름", 180, True),
            ("season", "시즌", 65), ("age", "나이", 55), ("club", "구단", 180, True),
            ("distance", "거리", 90), ("wc", "월클", 55),
        )
        self.tree = make_tree(self, columns)

    def run(self):
        try:
            player_id = int(self.player.get())
            k = int(logic.parse_int(self.k.get(), "k", 1, 50) or 10)
            snapshot = self.app.snapshot(self.snapshot.get())
            definition = self.app.definition(self.definition.get())
            season = int(self.season.get()) if self.season.get().strip() else None
            if season is None:
                season = players.latest_snapshot_season(self.app.conn, snapshot["snapshot_id"], player_id)
            if season is None:
                raise ValueError("이 스냅샷 기준 완료된 시즌이 없습니다.")
        except (ValueError, TypeError) as exc:
            self.app.error(exc)
            return
        self.season.set(str(season))
        self.app.jobs.submit(
            "유사 선수 계산",
            lambda connection: players.similar_players(
                connection, snapshot["snapshot_id"], player_id, season, k, def_id=definition["def_id"],
            ),
            self._show,
            button=self.btn,
        )

    def _show(self, rows):
        clear_tree(self.tree)
        for rank, row in enumerate(rows, 1):
            self.tree.insert("", "end", values=(
                rank, logic.identifier(row["player_id"]), row["name"], row["season"], row["age"],
                row["club_name"], f"{row['distance']:.4f}", "O" if row["is_wc"] else "-",
            ))
