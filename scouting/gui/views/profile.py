from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from datetime import datetime

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from scouting.services import players, watchlist
from .. import logic
from ..common import make_tree


class ProfileView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.player_id = None
        self.card = None
        self.header = ttk.Label(self, text="검색 결과에서 선수를 선택하세요.", font=(app.font, 13, "bold"))
        self.header.pack(fill="x", padx=12, pady=5)
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=10)
        ttk.Button(actions, text="유사 선수", command=self.to_similar).pack(side="left")
        ttk.Button(actions, text="워치리스트", command=self.add_watch).pack(side="left", padx=5)
        ttk.Button(actions, text="노트 작성", command=self.add_note).pack(side="left")
        self.snap = tk.StringVar(value=app.default_snapshot)
        self.snap_box = ttk.Combobox(
            actions, textvariable=self.snap, values=app.snapshot_names, state="readonly", width=16,
        )
        self.snap_box.pack(side="right")
        self.snap_box.bind("<<ComboboxSelected>>", lambda _event: self.load(self.player_id))
        ttk.Label(actions, text="백분위 스냅샷").pack(side="right", padx=4)
        self.pane = ttk.Panedwindow(self, orient="vertical")
        self.pane.pack(fill="both", expand=True, padx=4, pady=3)
        self.table_frame = ttk.Frame(self.pane, height=185)
        self.chart_frame = ttk.Frame(self.pane)
        self.pane.add(self.table_frame, weight=1)
        self.pane.add(self.chart_frame, weight=3)
        self.season_tree = None
        self.chart_scale = max(1.0, app.dpi / 96.0)
        # Tk's DPI scaling also scales the Agg canvas request on Windows. A
        # half-size request expands cleanly to the 1280x800 logical viewport.
        self.figure = Figure(figsize=(6, 2.2), dpi=100, constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def load(self, player_id):
        if player_id is None:
            return
        self.player_id = int(player_id)
        snapshot = self.app.snapshot(self.snap.get())

        def job(connection):
            card = players.player_card(connection, self.player_id)
            history = players.season_history(connection, self.player_id)
            valuations = players.valuation_history(connection, self.player_id)
            season = players.latest_snapshot_season(connection, snapshot["snapshot_id"], self.player_id)
            percentiles = []
            if season is not None:
                percentiles = players.cohort_percentiles(connection, snapshot["snapshot_id"], self.player_id, season)
            return card, history, valuations, season, percentiles

        self.app.jobs.submit("프로필 불러오기", job, self._render)

    def _render(self, data):
        card, history, valuations, season, percentiles = data
        self.card = card
        if not card:
            self.app.error(ValueError("존재하지 않는 선수입니다."))
            return
        self.header.configure(text=(
            f"{card['name']} · ID {logic.identifier(card['player_id'])} · {card['pos_group']} · "
            f"{card['age']}세 · {card['current_club_name']} · {logic.eur(card['latest_value_eur'])}"
        ))
        for child in self.table_frame.winfo_children():
            child.destroy()
        columns = logic.season_columns(card.get("pos_group"))
        tree_columns = tuple(self._tree_column(key, label) for key, label in columns)
        self.season_tree = make_tree(self.table_frame, tree_columns, height=6)
        for row in history:
            values = [logic.format_season_value(key, row.get(key)) for key, _label in columns]
            self.season_tree.insert("", "end", values=values)
        self._draw_charts(history, valuations, season, percentiles, card.get("pos_group") or "")

    @staticmethod
    def _tree_column(key, label):
        if key == "club_name":
            return key, label, 150, True
        if key == "m_minutes_share":
            return key, label, 88
        if key.startswith("m_"):
            return key, label, 84
        return key, label, 68

    def _draw_charts(self, history, valuations, season, percentiles, pos_group):
        # Tk already reports physical widget pixels in a per-monitor-aware
        # process. Matplotlib's Tk backend otherwise applies the monitor ratio
        # a second time and renders only the upper-left half of the figure.
        self.canvas._set_device_pixel_ratio(1)
        self.figure.clear()
        axes = self.figure.subplot_mosaic(
            [["growth", "value"], ["percentile", "percentile"]],
            height_ratios=[1.0, 1.15],
        )
        growth_ax = axes["growth"]
        value_ax = axes["value"]
        percentile_ax = axes["percentile"]
        growth = logic.growth_series(history, pos_group)
        for key, values in growth.items():
            if key in ("season", "age") or not any(value is not None for value in values):
                continue
            metric_code = key.removeprefix("m_")
            label = self.app.metric_names.get(metric_code, metric_code)
            growth_ax.plot(growth["age"], values, marker="o", label=label)
        growth_ax.set_title("나이별 성장", fontsize=10 * self.chart_scale)
        growth_ax.set_xlabel("나이", fontsize=9 * self.chart_scale)
        growth_ax.tick_params(labelsize=8 * self.chart_scale)
        if growth_ax.lines:
            growth_ax.legend(fontsize=8 * self.chart_scale)
        series = logic.valuation_series(valuations)
        if series["dates"]:
            dates = [datetime.fromisoformat(value) for value in series["dates"]]
            value_ax.plot(dates, [value / 1e6 for value in series["values"]], color="#2780c2")
            peak = series["peak"]
            peak_date = datetime.fromisoformat(peak["date"])
            peak_value = peak["market_value_eur"] / 1e6
            value_ax.scatter([peak_date], [peak_value], color="crimson", zorder=3)
            value_ax.annotate(
                f"최고 {logic.eur(peak['market_value_eur'])}", (peak_date, peak_value),
                fontsize=8 * self.chart_scale,
            )
            value_ax.xaxis.set_major_locator(mdates.YearLocator())
            value_ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            value_ax.tick_params(axis="x", rotation=45, labelsize=8 * self.chart_scale)
            value_ax.tick_params(axis="y", labelsize=8 * self.chart_scale)
        value_ax.set_title("시장가치 추이 (€M)", fontsize=10 * self.chart_scale)
        ordered = logic.ordered_percentiles(percentiles)[:10]
        if ordered:
            reversed_rows = list(reversed(ordered))
            names = [row["name_ko"] for row in reversed_rows]
            values = [row["percentile"] for row in reversed_rows]
            colors = ["#2a9d8f" if value >= 50 else "#e9c46a" for value in values]
            bars = percentile_ax.barh(names, values, color=colors)
            percentile_ax.set_xlim(0, 100)
            percentile_ax.set_title(
                f"코호트 백분위 · {season} 시즌", fontsize=10 * self.chart_scale,
            )
            percentile_ax.tick_params(labelsize=8 * self.chart_scale)
            for bar, value in zip(bars, values):
                x = min(value + 1, 98)
                align = "right" if value > 94 else "left"
                percentile_ax.text(x, bar.get_y() + bar.get_height() / 2, f"{value:.1f}",
                                   va="center", ha=align, fontsize=8 * self.chart_scale)
        else:
            percentile_ax.text(
                0.5, 0.5, "백분위 데이터 없음", ha="center", va="center",
                fontsize=9 * self.chart_scale,
            )
            percentile_ax.set_title("코호트 백분위", fontsize=10 * self.chart_scale)
        self.canvas.draw_idle()

    def to_similar(self):
        if not self.player_id:
            self.app.error(ValueError("선수를 먼저 선택해 주세요."))
            return
        self.app.similar.player.set(str(self.player_id))
        self.app.notebook.select(self.app.similar)

    def add_watch(self):
        if not self.player_id:
            return
        try:
            watchlist.add_to_watchlist(self.app.conn, self.app.user.user_id, self.player_id)
        except Exception as exc:
            self.app.error(exc)
            return
        self.app.set_status("워치리스트에 추가했습니다.")
        self.app.watch.refresh()

    def add_note(self):
        if self.player_id:
            self.app.note.player.set(str(self.player_id))
            self.app.notebook.select(self.app.note)
            self.app.note.create()
