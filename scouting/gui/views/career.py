from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

import matplotlib.dates as mdates
import matplotlib.transforms as mtransforms
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from scouting.services import players
from .. import logic
from ..common import clear_tree, make_tree

FOOT_KO = {"left": "왼발", "right": "오른발", "both": "양발"}
LABEL_ROWS = 3


class CareerView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.player_id = None
        self.index = None                 # 검색 결과 안의 0-based 위치 (검색 없이 열면 None)
        self.card = None
        self.seasons = {"all": [], "league": []}
        self.transfers: list[dict] = []
        self.valuations: list[dict] = []
        self.label_artists: list = []
        self.moves: list[tuple] = []
        self.value_ax = None

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=10, pady=(6, 2))
        ttk.Button(nav, text="← 검색 결과", command=app.show_search).pack(side="left")
        self.prev_btn = ttk.Button(nav, text="◀ 이전 선수", command=lambda: self.step(-1))
        self.next_btn = ttk.Button(nav, text="다음 선수 ▶", command=lambda: self.step(1))
        self.pos_label = ttk.Label(nav, text="")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=2)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=5)
        body.add(right, weight=4)

        card_box = ttk.LabelFrame(left, text="프로필")
        card_box.pack(fill="x", padx=4, pady=2)
        self.name_label = ttk.Label(card_box, text="", font=(app.font, 13, "bold"))
        self.name_label.pack(anchor="w", padx=8, pady=(2, 0))
        self.info = [ttk.Label(card_box, text="", justify="left") for _ in range(3)]
        for label in self.info:
            label.pack(anchor="w", padx=8)
        ttk.Frame(card_box, height=2).pack()

        trans_box = ttk.LabelFrame(left, text="이적 이력")
        trans_box.pack(fill="both", expand=True, padx=4, pady=2)
        self.transfer_tree = make_tree(
            trans_box,
            (("date", "날짜", 105), ("season", "시즌", 52), ("route", "이적 (이전 → 이후)", 230, True),
             ("fee", "이적료", 70), ("value", "당시 가치", 75)),
            height=6, left=("route",),
        )
        self.transfer_tree.tag_configure("upcoming", foreground="#a33a00")

        season_box = ttk.LabelFrame(left, text="시즌별 기록")
        season_box.pack(fill="both", expand=True, padx=4, pady=2)
        bar = ttk.Frame(season_box)
        bar.pack(fill="x", padx=8)
        self.scope = tk.StringVar(value="all")
        ttk.Radiobutton(bar, text="전체 대회", variable=self.scope, value="all",
                        command=self.render_seasons).pack(side="left")
        ttk.Radiobutton(bar, text="리그만", variable=self.scope, value="league",
                        command=self.render_seasons).pack(side="left", padx=8)
        self.expanded = False
        self.toggle_btn = ttk.Button(bar, text="모두 펼치기", command=self.toggle_all)
        self.toggle_btn.pack(side="right")
        self.season_tree = make_tree(
            season_box,
            (("apps", "출전", 54), ("starts", "선발", 54), ("min", "분", 66), ("g", "골", 48),
             ("a", "도움", 52), ("y", "경고", 52), ("r", "퇴장", 52)),
            height=9, tree_column=("시즌 · 구단 / 대회", 250), style="Season.Treeview",
        )
        tree = self.season_tree
        tree.tag_configure("parent", font=(app.font, 9, "bold"))
        tree.tag_configure("zebra0", background="#ffffff")
        tree.tag_configure("zebra1", background="#e8eef7")
        tree.tag_configure("child", foreground="#333333")
        tree.bind("<Button-1>", self.on_click)
        tree.bind("<Double-1>", lambda e: "break" if tree.identify_row(e.y) in tree.get_children() else None)
        ttk.Label(season_box, text=logic.coverage_note(app.coverage), foreground="#555",
                  wraplength=int(560 * app.dpi / 96.0)).pack(anchor="w", padx=8, pady=(0, 4))

        self.chart_scale = max(1.0, app.dpi / 96.0)
        self.figure = Figure(figsize=(6, 6), dpi=100, constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("resize_event", lambda _e: self.place_labels())

    # --- navigation (검색 결과 안의 이전/다음 선수) ---------------------------
    def refresh_nav(self):
        for widget in (self.prev_btn, self.next_btn, self.pos_label):
            widget.pack_forget()
        total = self.app.search.total
        if self.index is None or not total:
            return
        self.prev_btn.pack(side="left", padx=(12, 2))
        self.next_btn.pack(side="left", padx=2)
        self.pos_label.pack(side="left", padx=8)
        self.prev_btn.configure(state="normal" if self.index > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.index < total - 1 else "disabled")
        self.pos_label.configure(text=f"{self.index + 1:,} / {total:,}")

    def step(self, delta: int):
        if self.index is not None:
            self.app.search.open_index(self.index + delta)

    # --- loading ------------------------------------------------------------
    def load(self, player_id, index=None):
        self.player_id = int(player_id)
        self.index = index
        self.card = None
        pid = self.player_id
        cutoff = self.app.cutoff["game"]
        self.refresh_nav()

        def job(connection):
            return (
                players.player_card(connection, pid),
                players.transfer_history(connection, pid, cutoff=cutoff),
                players.valuation_history(connection, pid),
                players.career_seasons(connection, pid),
                players.career_seasons(connection, pid, league_only=True),
            )

        def done(data):
            if pid != self.player_id:   # 그 사이 다른 선수를 열었다면 버린다.
                return
            self._render(*data)

        self.app.jobs.submit("커리어 불러오기", job, done)

    def _render(self, card, transfers, valuations, all_rows, league_rows):
        if not card:
            self.app.error(ValueError("존재하지 않는 선수입니다."))
            return
        self.card, self.transfers, self.valuations = card, transfers, valuations
        self.seasons = {"all": all_rows, "league": league_rows}
        series = logic.valuation_series(valuations)
        peak = series["peak"]
        age = "-" if card["age"] is None else f"만 {card['age']}세"
        pos = logic.POS_KO.get(card["pos_group"], card["position"])
        if card.get("sub_position"):
            pos += f" / {card['sub_position']}"
        height = f"{card['height_cm']}cm" if card.get("height_cm") else "-"
        self.name_label.configure(text=card["name"])
        self.info[0].configure(text=(
            f"생년월일 {card['date_of_birth'] or '-'} ({age})  ·  국적 {card['country_of_citizenship'] or '-'}"
            f"  ·  ID {logic.identifier(card['player_id'])}"))
        self.info[1].configure(text=(
            f"포지션 {pos}  ·  주발 {FOOT_KO.get(card['foot'], '-')}  ·  키 {height}"
            f"  ·  현재 구단 {card['current_club_name'] or '-'}"))
        peak_text = (f"{logic.eur(card['peak_value_eur'])} ({peak['date']})" if peak else "-")
        self.info[2].configure(text=f"현재 시장가치 {logic.eur(card['latest_value_eur'])}  ·  최고 시장가치 {peak_text}")
        clear_tree(self.transfer_tree)
        for row, src in zip(logic.transfer_rows(transfers), transfers):
            self.transfer_tree.insert("", "end", values=row, tags=("upcoming",) if src["upcoming"] else ())
        self.render_seasons()
        self.draw_charts()
        self.refresh_nav()

    # --- season hierarchy -----------------------------------------------------
    @staticmethod
    def _pad(values):
        return tuple(f"{v}   " for v in values)      # 오른쪽 여백

    def render_seasons(self):
        tree = self.season_tree
        clear_tree(tree)
        for i, group in enumerate(logic.season_groups(self.seasons[self.scope.get()])):
            parent = tree.insert("", "end", text=group["label"], values=self._pad(group["values"]),
                                 open=self.expanded, tags=("parent", f"zebra{i % 2}"))
            for name, values in group["children"]:
                tree.insert(parent, "end", text="    " + name, values=self._pad(values), tags=("child",))

    def toggle_all(self):
        self.expanded = not self.expanded
        for item in self.season_tree.get_children():
            self.season_tree.item(item, open=self.expanded)
        self.toggle_btn.configure(text="모두 접기" if self.expanded else "모두 펼치기")

    def on_click(self, event):
        tree = self.season_tree
        item = tree.identify_row(event.y)
        if not item or item not in tree.get_children():
            return None
        if tree.identify_element(event.x, event.y).endswith("indicator"):
            return None                          # 기본 동작이 이미 토글한다
        tree.item(item, open=not tree.item(item, "open"))
        tree.selection_set(item)
        return "break"

    # --- charts -------------------------------------------------------------
    def draw_charts(self):
        # Tk already reports physical pixels in a per-monitor-aware process; without this
        # matplotlib's Tk backend applies the monitor ratio again and clips the figure.
        self.canvas._set_device_pixel_ratio(1)
        s = self.chart_scale
        self.figure.clear()
        self.label_artists = []
        self.moves = []
        value_ax, season_ax = self.figure.subplots(2, 1, height_ratios=[1, 1])
        self.value_ax = value_ax
        self._draw_value(value_ax, s)
        self._draw_seasons(season_ax, s)
        self.place_labels()
        self.canvas.draw_idle()

    def _draw_value(self, ax, s):
        ax.set_title("시장가치 추이 (€M) · 이적 시점", fontsize=10 * s)
        series = logic.valuation_series(self.valuations)
        if not series["dates"]:
            ax.text(0.5, 0.5, "시장가치 데이터 없음", ha="center", va="center", transform=ax.transAxes,
                    fontsize=9 * s)
            return
        dates = [datetime.fromisoformat(v) for v in series["dates"]]
        values = [v / 1e6 for v in series["values"]]
        ax.plot(dates, values, color="#2780c2")
        ax.set_ylim(0, (max(values) * 1.05 or 1) / 0.68)    # 위쪽 32%는 이적 라벨 자리
        ax.set_yticks([t for t in ax.get_yticks() if t <= max(values) * 1.08])
        lo, hi = dates[0], dates[-1]
        self.moves = logic.chart_moves(self.transfers, series["dates"][0], series["dates"][-1])
        for day, _name, _fee in self.moves:
            ax.axvline(datetime.fromisoformat(day), color="#888", linestyle=":", linewidth=0.9)
        peak = series["peak"]
        peak_date = datetime.fromisoformat(peak["date"])
        peak_value = peak["market_value_eur"] / 1e6
        ax.scatter([peak_date], [peak_value], color="crimson", zorder=3)
        ax.annotate(f"최고 {logic.eur(peak['market_value_eur'])}\n{peak['date']}", (peak_date, peak_value),
                    xytext=(6, -26), textcoords="offset points", fontsize=8 * s, color="crimson")
        ax.xaxis.set_major_locator(mdates.YearLocator(2 if (hi - lo).days > 365 * 12 else 1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.tick_params(labelsize=8 * s)
        ax.set_ylabel("€M", fontsize=8 * s)

    def place_labels(self):
        """이적 라벨을 가로로, 최대 3줄에 엇갈려 배치한다. 글자 폭은 렌더러로 직접 재고, 겹치면 생략한다."""
        for artist in self.label_artists:
            artist.remove()
        self.label_artists = []
        ax = self.value_ax
        if ax is None or not self.moves:
            return
        s = self.chart_scale
        self.figure.draw_without_rendering()           # constrained layout 을 먼저 적용
        renderer = self.figure.canvas.get_renderer()
        trans = mtransforms.blended_transform_factory(ax.transData, ax.transAxes)
        axes_box = ax.get_window_extent(renderer)
        gap = 3 * s
        items = []
        for day, name, _fee in self.moves:
            x = ax.transData.transform((mdates.date2num(datetime.fromisoformat(day)), 0))[0]
            probe = ax.text(0, 0, name, fontsize=7 * s, transform=ax.transAxes)
            width = probe.get_window_extent(renderer).width
            probe.remove()
            if x + gap + width > axes_box.x1:           # 오른쪽 끝이면 선 왼쪽에 둔다
                items.append((day, name, x - gap - width, x - gap, "right", x))
            else:
                items.append((day, name, x + gap, x + gap + width, "left", x))
        rows = logic.assign_label_rows([(it[2], it[3]) for it in items], rows=LABEL_ROWS, pad=4 * s,
                                       order=logic.label_priority(self.moves))
        for (day, name, _x0, _x1, align, _x), row in zip(items, rows):
            if row is None:
                continue
            dx = gap if align == "left" else -gap
            shift = mtransforms.ScaledTranslation(dx / self.figure.dpi, 0, self.figure.dpi_scale_trans)
            self.label_artists.append(ax.text(
                mdates.date2num(datetime.fromisoformat(day)), 0.975 - row * 0.095, name,
                transform=trans + shift, fontsize=7 * s, color="#333", ha=align, va="top"))
        self.canvas.draw_idle()

    def _draw_seasons(self, ax, s):
        ax.set_title("시즌별 출전 시간(막대)과 골+도움(선)", fontsize=10 * s)
        everything = logic.season_chart_series(self.seasons["all"])
        if not everything["seasons"]:
            ax.text(0.5, 0.5, "시즌 기록 없음", ha="center", va="center", transform=ax.transAxes, fontsize=9 * s)
            return
        league = logic.season_chart_series(self.seasons["league"])
        lg_min = dict(zip(league["seasons"], league["minutes"]))
        lg_ga = dict(zip(league["seasons"], league["ga"]))
        names = everything["seasons"]
        xs = list(range(len(names)))
        ax.bar(xs, everything["minutes"], width=0.8, color="#bcd4ec", label="출전 분 (전체)")
        ax.bar(xs, [lg_min.get(n, 0) for n in names], width=0.5, color="#2780c2", label="출전 분 (리그)")
        ax.set_ylabel("분", fontsize=8 * s)
        step = 1 if len(names) <= 12 else 2
        ax.set_xticks(xs[::step])
        ax.set_xticklabels(names[::step], rotation=60, ha="right")
        ax.tick_params(labelsize=7 * s)
        ax2 = ax.twinx()
        ax2.plot(xs, everything["ga"], color="#e07b00", marker="o", markersize=3 * s, linestyle="--",
                 label="골+도움 (전체)")
        ax2.plot(xs, [lg_ga.get(n, 0) for n in names], color="crimson", marker="o", markersize=3 * s,
                 label="골+도움 (리그)")
        ax2.set_ylabel("골+도움", fontsize=8 * s)
        ax2.tick_params(labelsize=7 * s)
        ax2.set_ylim(bottom=0)
        handles = ax.get_legend_handles_labels()
        handles2 = ax2.get_legend_handles_labels()
        ax.legend(handles[0] + handles2[0], handles[1] + handles2[1], fontsize=7 * s, loc="upper left", ncol=2)
        ax.set_ylim(0, max(everything["minutes"]) * 1.3 or 1)
