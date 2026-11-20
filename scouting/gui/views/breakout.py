from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from scouting.services import recommend
from .. import logic
from ..common import clear_tree, make_tree


class BreakoutView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.vars = {}
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=8)
        self._combo(bar, "snapshot", "스냅샷", app.default_snapshot, app.snapshot_names, 0, 13)
        self._combo(bar, "definition", "정의", app.default_definition, app.definition_codes, 2, 16)
        self._combo(bar, "pos", "포지션군", "FW", logic.POS_GROUPS, 4, 7)
        self._combo(bar, "metric", "지표", "minutes_share", app.metric_codes, 6, 18)
        self._combo(bar, "mode", "비교", "some", ("all", "some"), 8, 7)
        self.vars["age"] = tk.StringVar(value="21")
        ttk.Label(bar, text="최대 나이").grid(row=0, column=10, padx=2)
        ttk.Entry(bar, textvariable=self.vars["age"], width=5).grid(row=0, column=11)
        self.btn = ttk.Button(bar, text="기준 돌파 찾기", command=self.run)
        self.btn.grid(row=0, column=12, padx=6)
        self.summary = ttk.Label(self)
        self.summary.pack(fill="x", padx=10)
        columns = (
            ("rank", "순위", 55), ("id", "ID", 80), ("name", "이름", 190, True),
            ("age", "나이", 55), ("value", "값", 90), ("n", "비교 월클 수", 105),
            ("max", "월클 최댓값", 115), ("min", "월클 최솟값", 115),
        )
        self.tree = make_tree(self, columns)

    def _combo(self, parent, key, label, default, values, column, width):
        self.vars[key] = tk.StringVar(value=default)
        ttk.Label(parent, text=label).grid(row=0, column=column, padx=2)
        ttk.Combobox(
            parent, textvariable=self.vars[key], values=values, width=width, state="readonly",
        ).grid(row=0, column=column + 1)

    def run(self):
        try:
            snapshot = self.app.snapshot(self.vars["snapshot"].get())
            definition = self.app.definition(self.vars["definition"].get())
            max_age = int(logic.parse_int(self.vars["age"].get(), "최대 나이", 15, 30) or 21)
        except ValueError as exc:
            self.app.error(exc)
            return
        mode = self.vars["mode"].get()
        kwargs = {
            "snapshot_id": snapshot["snapshot_id"], "def_id": definition["def_id"],
            "pos_group": self.vars["pos"].get(), "metric_code": self.vars["metric"].get(),
        }

        def job(connection):
            return recommend.breakout_prospects(connection, max_age=max_age, mode=mode, **kwargs)

        self.app.jobs.submit("기준 돌파 계산", job, self._show, button=self.btn)

    def _show(self, rows):
        clear_tree(self.tree)
        cohorts = len({row["age"] for row in rows})
        self.summary.configure(text=f"결과 {len(rows)}명 · 비교 가능한 나이 코호트 {cohorts}개")
        for rank, row in enumerate(rows, 1):
            self.tree.insert("", "end", values=(
                rank, row["player_id"], row["name"], row["age"], f"{row['value']:.3f}", row["n_wc"],
                f"{row['wc_max']:.3f}", f"{row['wc_min']:.3f}",
            ))
