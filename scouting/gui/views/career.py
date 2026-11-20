from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from scouting.services import players
from .. import logic, theme
from ..common import clear_tree, make_tree

FOOT_KO = {"left": "왼발", "right": "오른발", "both": "양발"}
LEDGER_COLLAPSED = 5


def _num(day: str) -> float:
    return mdates.date2num(datetime.fromisoformat(day))


class CareerView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.fonts = app.fonts
        self.player_id = None
        self.index = None                 # 검색 결과 안의 0-based 위치 (검색 없이 열면 None)
        self.card = None
        self.seasons = {"all": [], "league": []}
        self.transfers: list[dict] = []
        self.valuations: list[dict] = []
        self.blocks: list[dict] = []
        self.strip_ax = None
        self.label_artists: list = []
        self.first_appearance = None
        self.xlim_lo = None
        self.season_names: dict = {}
        self.ledger_open = False
        scale = app.dpi / 96.0
        self.chart_scale = max(1.0, scale)
        pad = {"padx": 14}

        # --- 위쪽 줄: 검색으로 돌아가기 / 이전·다음 선수 -------------------------
        nav = ttk.Frame(self)
        nav.pack(fill="x", pady=(10, 0), **pad)
        ttk.Button(nav, text="← 검색 결과", command=app.show_search).pack(side="left")
        self.pager = ttk.Frame(nav)
        self.prev_btn = ttk.Button(self.pager, text="◀", width=3, command=lambda: self.step(-1))
        self.pos_label = ttk.Label(self.pager, text="", style="Pill.TLabel")
        self.next_btn = ttk.Button(self.pager, text="▶", width=3, command=lambda: self.step(1))
        self.prev_btn.pack(side="left")
        self.pos_label.pack(side="left", padx=8)
        self.next_btn.pack(side="left")

        # --- 이름과 기본 정보 ----------------------------------------------------
        title = ttk.Frame(self)
        title.pack(fill="x", pady=(2, 2), **pad)
        self.name_label = ttk.Label(title, text="", style="Name.TLabel")
        self.name_label.pack(side="left")
        money = ttk.Frame(title)
        money.pack(side="right", anchor="s", pady=(0, 6))
        ttk.Label(money, text="현재 가치", style="Muted.TLabel").grid(row=0, column=0, sticky="sw")
        self.now_value = ttk.Label(money, text="-", style="Big.TLabel")
        self.now_value.grid(row=0, column=1, sticky="sw", padx=(8, 36))
        ttk.Label(money, text="최고 가치", style="Muted.TLabel").grid(row=0, column=2, sticky="sw")
        self.peak_value = ttk.Label(money, text="-", style="Big.TLabel")
        self.peak_value.grid(row=0, column=3, sticky="sw", padx=(8, 6))
        self.peak_date = ttk.Label(money, text="", style="Muted.TLabel")
        self.peak_date.grid(row=0, column=4, sticky="sw")
        facts = ttk.Frame(self)
        facts.pack(fill="x", **pad)
        self.fact_labels = {}
        for col, key in enumerate(("생년월일", "국적", "포지션", "주발", "키", "현재 구단")):
            ttk.Label(facts, text=key, style="Muted.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 28))
            value = ttk.Label(facts, text="")
            value.grid(row=1, column=col, sticky="w", padx=(0, 28))
            self.fact_labels[key] = value

        # --- 커리어 경로 (구단 띠 + 시장가치) -----------------------------------------
        ttk.Label(self, text="커리어 경로", style="Section.TLabel").pack(anchor="w", pady=(12, 2), **pad)
        self.strip_fig = Figure(figsize=(8, 2.3), dpi=100, facecolor=theme.PITCH_LINE, constrained_layout=True)
        self.strip_canvas = FigureCanvasTkAgg(self.strip_fig, master=self)
        strip_widget = self.strip_canvas.get_tk_widget()
        strip_widget.configure(height=round(165 * scale), highlightthickness=0)
        strip_widget.pack(fill="x", **pad)
        self.strip_canvas.mpl_connect("resize_event", lambda _e: self.place_strip_labels())

        # --- 아래쪽: 이적 이력 (항상 5줄, 펼치면 전부) ------------------------------------
        ledger = ttk.Frame(self)
        ledger.pack(side="bottom", fill="x", pady=(4, 10), **pad)
        head = ttk.Frame(ledger)
        head.pack(fill="x")
        ttk.Label(head, text="이적 이력", style="Section.TLabel").pack(side="left")
        self.ledger_btn = ttk.Button(head, text="전체 보기", command=self.toggle_ledger)
        self.ledger_btn.pack(side="right")
        self.transfer_tree = make_tree(
            ledger,
            (("date", "날짜", 120), ("season", "시즌", 60), ("route", "이적 (이전 → 이후)", 360, True),
             ("fee", "이적료", 90), ("value", "당시 가치", 90)),
            height=LEDGER_COLLAPSED, left=("route", "date", "season"), pad=(0, 4),
        )
        self.transfer_tree.tag_configure("upcoming", foreground=theme.MUTED)

        # --- 가운데: 시즌별 기록 표 / 시즌별 차트 ---------------------------------------
        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True, pady=(8, 0), **pad)
        middle.columnconfigure(0, weight=5, uniform="mid")
        middle.columnconfigure(1, weight=4, uniform="mid")
        middle.rowconfigure(0, weight=1)
        season_box = ttk.Frame(middle)
        season_box.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        bar = ttk.Frame(season_box)
        bar.pack(fill="x")
        ttk.Label(bar, text="시즌별 기록", style="Section.TLabel").pack(side="left")
        self.expanded = False
        self.toggle_btn = ttk.Button(bar, text="모두 펼치기", command=self.toggle_all)
        self.toggle_btn.pack(side="right")
        self.scope = tk.StringVar(value="all")
        seg = ttk.Frame(bar)
        seg.pack(side="right", padx=10)
        self.seg_buttons = {}
        for value, text in (("all", "전체 대회"), ("league", "리그만")):
            btn = ttk.Button(seg, text=text, command=lambda v=value: self.set_scope(v))
            btn.pack(side="left")
            self.seg_buttons[value] = btn
        self.scope.trace_add("write", lambda *_: self.style_scope())
        self.style_scope()
        self.no_league = ttk.Label(season_box, text=logic.no_league_note(app.coverage),
                                   wraplength=round(560 * scale))
        self.season_tree = make_tree(
            season_box,
            (("club", "구단 / 대회", 190, True), ("apps", "출전", 54), ("starts", "선발", 54), ("min", "분", 66),
             ("g", "골", 46), ("a", "도움", 52), ("y", "경고", 52), ("r", "퇴장", 52)),
            height=6, tree_column=("시즌", 78), style="Season.Treeview", left=("club",), pad=(0, 4),
        )
        tree = self.season_tree
        tree.tag_configure("parent", font=self.fonts.semibold())
        tree.tag_configure("zebra1", background=theme.PAPER)
        tree.bind("<Button-1>", self.on_click)
        tree.bind("<Return>", self.on_key)
        tree.bind("<space>", self.on_key)
        tree.bind("<Double-1>", lambda e: "break" if tree.identify_row(e.y) in tree.get_children() else None)
        ttk.Label(season_box, text=logic.coverage_note(app.coverage), style="Muted.TLabel",
                  wraplength=round(560 * scale)).pack(anchor="w")

        chart_box = ttk.Frame(middle)
        chart_box.grid(row=0, column=1, sticky="nsew")
        ttk.Label(chart_box, text="시즌별 출전 시간과 공격포인트", style="Section.TLabel").pack(anchor="w")
        self.figure = Figure(figsize=(5, 3), dpi=100, facecolor=theme.PITCH_LINE, constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=chart_box)
        self.canvas.get_tk_widget().configure(highlightthickness=0)
        for canvas in (self.strip_canvas, self.canvas):
            # Tk 이 이미 물리 픽셀로 보고하므로 matplotlib 의 배율 보정을 끈다 (켜 두면 위젯이 두 배로 커지고
            # 그림이 절반만 그려진다). <Map> 에 걸린 자동 보정을 풀고 비율을 1 로 고정한다.
            canvas.get_tk_widget().unbind("<Map>")
            canvas._set_device_pixel_ratio(1)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=(6, 0))

    # --- navigation (검색 결과 안의 이전/다음 선수) ---------------------------
    def refresh_nav(self):
        self.pager.pack_forget()
        total = self.app.search.total
        if self.index is None or not total:
            return
        self.pager.pack(side="right")
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
                players.first_appearance_date(connection, pid),
            )

        def done(data):
            if pid != self.player_id:   # 그 사이 다른 선수를 열었다면 버린다.
                return
            self._render(*data)

        self.app.jobs.submit(
            "커리어 불러오기", job, done, busy="커리어를 불러오는 중",
            done=lambda result, t: (f"{result[0]['name']} 커리어를 불러왔습니다 ({t:.1f}초)"
                                    if result[0] else "선수 정보를 찾지 못했습니다"))

    def _render(self, card, transfers, valuations, all_rows, league_rows, first_appearance=None):
        if not card:
            self.app.error(ValueError("존재하지 않는 선수입니다."))
            return
        self.card, self.transfers, self.valuations = card, transfers, valuations
        self.seasons = {"all": all_rows, "league": league_rows}
        self.first_appearance = first_appearance
        peak = logic.valuation_series(valuations)["peak"]
        age = "" if card["age"] is None else f" (만 {card['age']}세)"
        self.name_label.configure(text=card["name"])
        values = {
            "생년월일": f"{card['date_of_birth'] or '-'}{age}",
            "국적": card["country_of_citizenship"] or "-",
            "포지션": logic.position_text(card),
            "주발": FOOT_KO.get(card["foot"], "-"),
            "키": f"{card['height_cm']}cm" if card.get("height_cm") else "-",
            "현재 구단": card["current_club_name"] or "-",
        }
        for key, text in values.items():
            self.fact_labels[key].configure(text=text)
        self.now_value.configure(text=logic.eur(card["latest_value_eur"]))
        self.peak_value.configure(text=logic.eur(card["peak_value_eur"]))
        self.peak_date.configure(text=f"({peak['date'][:7]})" if peak else "")
        self.render_ledger()
        self.render_seasons()
        self.draw_charts()
        self.refresh_nav()

    # --- 이적 이력 ledger -------------------------------------------------------
    def render_ledger(self):
        clear_tree(self.transfer_tree)
        rows = list(zip(logic.transfer_rows(self.transfers), self.transfers))[::-1]      # 최신 순
        shown = rows if self.ledger_open else rows[:LEDGER_COLLAPSED]
        for row, src in shown:
            tags = ["upcoming"] if src["upcoming"] else []
            self.transfer_tree.insert("", "end", values=row, tags=tags)
        self.transfer_tree.configure(height=max(LEDGER_COLLAPSED, min(len(shown), 12)) if self.ledger_open
                                     else LEDGER_COLLAPSED)
        self.ledger_btn.configure(text="접기" if self.ledger_open else f"전체 보기 ({len(rows)})")
        self.ledger_btn.state(["!disabled"] if len(rows) > LEDGER_COLLAPSED else ["disabled"])

    def toggle_ledger(self):
        self.ledger_open = not self.ledger_open
        self.render_ledger()

    def set_scope(self, value):
        self.scope.set(value)
        self.render_seasons()

    def style_scope(self):
        for value, btn in self.seg_buttons.items():
            btn.configure(style="SegOn.TButton" if self.scope.get() == value else "SegOff.TButton")

    # --- season hierarchy -----------------------------------------------------
    @staticmethod
    def _pad(values):
        return tuple(f"{v}   " for v in values)      # 오른쪽 여백

    def render_seasons(self):
        tree = self.season_tree
        clear_tree(tree)
        self.season_names = {}
        if self.seasons["league"]:
            self.no_league.pack_forget()
        elif self.card:
            self.no_league.pack(anchor="w", pady=(4, 0), before=tree.master)
        for i, group in enumerate(logic.season_groups(self.seasons[self.scope.get()])):
            parent = tree.insert("", "end", values=(group["club"], *self._pad(group["values"])),
                                 tags=("parent", f"zebra{i % 2}"))
            self.season_names[parent] = group["season"]
            self._set_open(parent, self.expanded)
            for name, values in group["children"]:
                tree.insert(parent, "end", text="", values=("    " + name, *self._pad(values)), tags=("child",))

    def _set_open(self, item, flag):
        self.season_tree.item(item, open=flag, text=("－ " if flag else "＋ ") + self.season_names[item])

    def toggle_all(self):
        self.expanded = not self.expanded
        for item in self.season_tree.get_children():
            self._set_open(item, self.expanded)
        self.toggle_btn.configure(text="모두 접기" if self.expanded else "모두 펼치기")

    def toggle_item(self, item):
        self._set_open(item, not self.season_tree.item(item, "open"))

    def on_click(self, event):
        tree = self.season_tree
        item = tree.identify_row(event.y)
        if not item or item not in tree.get_children():
            return None
        self.toggle_item(item)
        tree.selection_set(item)
        return "break"

    def on_key(self, _event):
        selection = self.season_tree.selection()
        if selection and selection[0] in self.season_tree.get_children():
            self.toggle_item(selection[0])
        return "break"

    # --- charts -------------------------------------------------------------
    def draw_charts(self):
        self._draw_strip()
        self._draw_seasons()
        self.canvas.draw_idle()
        self.strip_canvas.draw_idle()

    def _draw_strip(self):
        s = self.chart_scale
        fig = self.strip_fig
        fig.clear()
        self.label_artists = []
        strip, value = fig.subplots(2, 1, sharex=True, height_ratios=[1, 3.4])
        self.strip_ax = strip
        cutoff = self.app.cutoff["game"]
        series = logic.valuation_series(self.valuations)
        first_val = series["dates"][0] if series["dates"] else None
        self.blocks = logic.collapse_youth(logic.tenures(self.transfers, cutoff), first_val, self.first_appearance)
        self.xlim_lo = _num(logic.strip_start(self.blocks[0]["start"], first_val)) if self.blocks else None

        theme.style_axes(value, s)
        value.text(0, 1.04, "시장가치 (€M)", transform=value.transAxes, color=theme.MUTED, fontsize=8 * s,
                   ha="left", va="bottom")
        strip.set_axis_off()
        strip.set_ylim(0, 1)
        colors = (theme.TURF, theme.TURF_2, theme.YOUTH)
        for b in self.blocks:
            x0, x1 = _num(b["start"]), _num(b["end"])
            strip.broken_barh([(x0, x1 - x0)], (0, 1), facecolors=colors[b["color"]],
                              edgecolor=theme.PITCH_LINE, linewidth=1.2 * s)
            if (b["fee"] or 0) > 0:
                strip.plot([x0, x0], [0, 0.34], color=theme.CARD_YELLOW, linewidth=2.6 * s,
                           solid_capstyle="butt", zorder=4)
        if series["dates"]:
            dates = [datetime.fromisoformat(d) for d in series["dates"]]
            values = [v / 1e6 for v in series["values"]]
            value.plot(dates, values, color=theme.TURF, linewidth=1.6)
            value.set_ylim(0, max(values) * 1.12 or 1)
            peak = series["peak"]
            peak_x, peak_y = datetime.fromisoformat(peak["date"]), peak["market_value_eur"] / 1e6
            value.scatter([peak_x], [peak_y], s=46 * s, color=theme.CARD_YELLOW, edgecolor=theme.INK,
                          linewidth=0.8, zorder=5)
            value.annotate(f"최고 {logic.eur(peak['market_value_eur'])}", (peak_x, peak_y),
                           xytext=(8 * s, -2 * s), textcoords="offset points", color=theme.INK,
                           fontsize=9 * s, va="center")
            lo, hi = series["dates"][0], series["dates"][-1]
            for b in self.blocks[1:]:
                if lo <= b["start"] <= hi:
                    value.axvline(_num(b["start"]), color=theme.RULE, linewidth=0.8, zorder=1)
        else:
            value.text(0.5, 0.5, "시장가치 데이터 없음", ha="center", va="center", transform=value.transAxes,
                       color=theme.MUTED, fontsize=9 * s)
        if self.blocks:
            value.set_xlim(self.xlim_lo, _num(cutoff))
        value.xaxis.set_major_locator(mdates.YearLocator(2 if self._span_years() > 12 else 1))
        value.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        self.place_strip_labels()

    def _span_years(self) -> float:
        if not self.blocks:
            return 0
        return (_num(self.blocks[-1]["end"]) - _num(self.blocks[0]["start"])) / 365.25

    def place_strip_labels(self):
        """구단 이름을 블록 안에 흰 글씨로. 폭은 렌더러로 직접 재고, 안 들어가면 '…' 로 줄이거나 생략한다."""
        for artist in self.label_artists:
            artist.remove()
        self.label_artists = []
        ax = self.strip_ax
        if ax is None or not self.blocks:
            return
        s = self.chart_scale
        self.strip_fig.draw_without_rendering()           # constrained layout 을 먼저 적용
        renderer = self.strip_fig.canvas.get_renderer()
        family = self.app.mpl_fonts["ko"]
        cache: dict[str, float] = {}

        def measure(text: str) -> float:
            if text not in cache:
                probe = ax.text(0, 0, text, fontsize=9 * s, fontfamily=family)
                cache[text] = probe.get_window_extent(renderer).width
                probe.remove()
            return cache[text]

        pad = 4 * s
        lo = self.xlim_lo
        for b in self.blocks:
            x0, x1 = max(_num(b["start"]), lo), _num(b["end"])      # 축 시작 앞쪽은 잘려 보이지 않는다
            width = ax.transData.transform((x1, 0))[0] - ax.transData.transform((x0, 0))[0]
            name = b["club"] if b.get("youth") else logic.shorten_club(b["club"])
            text = logic.fit_label(name, width - 2 * pad, measure)
            if text:
                self.label_artists.append(ax.text(
                    (x0 + x1) / 2, 0.5, text, color=theme.INK if b.get("youth") else theme.PITCH_LINE,
                    fontsize=9 * s, fontfamily=family, ha="center", va="center", zorder=6))
        self.strip_canvas.draw_idle()

    def _draw_seasons(self):
        s = self.chart_scale
        fig = self.figure
        fig.clear()
        ax = fig.subplots()
        theme.style_axes(ax, s)
        everything = logic.season_chart_series(self.seasons["all"])
        if not everything["seasons"]:
            ax.set_axis_off()
            ax.text(0.5, 0.5, "시즌 기록 없음", ha="center", va="center", transform=ax.transAxes,
                    color=theme.MUTED, fontsize=9 * s)
            return
        league = logic.season_chart_series(self.seasons["league"])
        lg_min = dict(zip(league["seasons"], league["minutes"]))
        lg_ga = dict(zip(league["seasons"], league["ga"]))
        names = everything["seasons"]
        xs = list(range(len(names)))
        ax.bar(xs, everything["minutes"], width=0.8, color=theme.TURF_2_TINT, label="출전 시간(전체)")
        ax.bar(xs, [lg_min.get(n, 0) for n in names], width=0.8, color=theme.TURF_2, label="출전 시간(리그)")
        step = 1 if len(names) <= 10 else 2
        ax.set_xticks(xs[::step])
        ax.set_xticklabels(names[::step], rotation=45, ha="right")
        ax.set_ylim(0, max(everything["minutes"]) * 1.7 or 1)
        ax.text(0, 1.03, "분", transform=ax.transAxes, color=theme.MUTED, fontsize=8 * s, ha="left", va="bottom")
        ax2 = ax.twinx()
        theme.style_axes(ax2, s, grid=False)
        ax2.spines["right"].set_visible(False)
        ax2.plot(xs, everything["ga"], color=theme.INK, linewidth=1.3, linestyle="--", label="공격포인트(전체)")
        ax2.plot(xs, [lg_ga.get(n, 0) for n in names], color=theme.INK, linewidth=1.8, marker="o",
                 markersize=3 * s, label="공격포인트(리그)")
        ax2.set_ylim(0, max(everything["ga"] + [1]) * 1.7)
        ax2.text(1, 1.03, "공격포인트", transform=ax2.transAxes, color=theme.MUTED, fontsize=8 * s,
                 ha="right", va="bottom")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax2.legend(h1[::-1] + h2[::-1], l1[::-1] + l2[::-1], loc="upper left", ncol=2, frameon=False,
                   fontsize=7.5 * s, labelcolor=theme.INK, columnspacing=1.0, handlelength=1.6)
