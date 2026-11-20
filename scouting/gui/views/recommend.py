from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from scouting.services import recommend
from .. import logic
from ..common import clear_tree, make_tree


class RecommendView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.vars = {}
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)
        self._combo(top, "snapshot", "스냅샷", app.default_snapshot, app.snapshot_names, 0)
        self._combo(top, "definition", "정의", app.default_definition, app.definition_codes, 2)
        self._combo(top, "pos_group", "포지션군", "FW", logic.POS_GROUPS, 4)
        self._combo(top, "method", "방식", "similarity", recommend.METHODS, 6)
        advanced = ttk.LabelFrame(self, text="고급 설정")
        advanced.pack(fill="x", padx=8)
        defaults = {
            "max_age": "21", "min_minutes": "900", "k": "25", "top_n": "20",
            "pool_lag_seasons": "3", "seed": "42",
        }
        for index, (key, default) in enumerate(defaults.items()):
            self.vars[key] = tk.StringVar(value=default)
            ttk.Label(advanced, text=key).grid(row=0, column=index * 2, padx=3, pady=5)
            ttk.Entry(advanced, textvariable=self.vars[key], width=7).grid(row=0, column=index * 2 + 1)
        self.btn = ttk.Button(self, text="추천 실행", command=self.run)
        self.btn.pack(anchor="w", padx=10, pady=6)
        columns = (
            ("rank", "순위", 55), ("id", "ID", 80), ("name", "이름", 180, True),
            ("club", "구단", 180, True), ("score", "점수", 100), ("wc", "월클 이웃", 85),
            ("value", "시장가치(as_of)", 140),
        )
        self.tree = make_tree(self, columns)

    def _combo(self, parent, key, label, default, values, column):
        self.vars[key] = tk.StringVar(value=default)
        ttk.Label(parent, text=label).grid(row=0, column=column, padx=3)
        ttk.Combobox(
            parent, textvariable=self.vars[key], values=values, width=16, state="readonly",
        ).grid(row=0, column=column + 1)

    def run(self):
        try:
            snapshot = self.app.snapshot(self.vars["snapshot"].get())
            definition = self.app.definition(self.vars["definition"].get())
            params = logic.validate_recommendation({key: variable.get() for key, variable in self.vars.items()})
            pos_group = self.vars["pos_group"].get()
            method = self.vars["method"].get()
        except ValueError as exc:
            self.app.error(exc)
            return

        def job(connection):
            run_id = recommend.run_recommendation(
                connection, user_id=self.app.user.user_id, snapshot_id=snapshot["snapshot_id"],
                def_id=definition["def_id"], pos_group=pos_group, method=method, **params,
            )
            return run_id, recommend.run_items(connection, run_id)

        self.app.jobs.submit("추천 계산", job, self._show, button=self.btn)

    def _show(self, data):
        run_id, rows = data
        clear_tree(self.tree)
        for row in rows:
            self.tree.insert("", "end", iid=str(row["player_id"]), values=(
                row["rank"], logic.identifier(row["player_id"]), row["name"], row["club_name"],
                f"{row['score']:.4f}", row["wc_neighbors"] if row["wc_neighbors"] is not None else "-",
                logic.eur(row["value_eur"]),
            ))
        self.app.set_status(f"추천 완료: run #{run_id}")
        self.app.runs.refresh()
