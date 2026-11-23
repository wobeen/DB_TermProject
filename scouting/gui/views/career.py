from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

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
        self.value_ax = None
        self.val_points: list[dict] = []
        self.val_nums: list[float] = []
        self.hover_marker = self.hover_line = None
        self.hover_tip = self.strip_tip = None
        self.last_motion = 0.0
        self.season_band = None
        self.band_seasons: list[int] = []
        self.band_ticks: list = []
        self.hl_label = None
        self.table_hover = None
        self.key_index = None
        self.row_tags: dict = {}
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
        ttk.Button(nav, text="검색 결과로", command=app.show_search).pack(side="left")
        self.pager = ttk.Frame(nav)
        self.prev_btn = ttk.Button(self.pager, text="이전 선수", command=lambda: self.step(-1))
        self.pos_label = ttk.Label(self.pager, text="", style="Pill.TLabel")
        self.next_btn = ttk.Button(self.pager, text="다음 선수", command=lambda: self.step(1))
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
        title_row = ttk.Frame(self)
        title_row.pack(fill="x", pady=(12, 2), **pad)
        ttk.Label(title_row, text="커리어 경로", style="Section.TLabel").pack(side="left")
        ttk.Label(title_row, style="Muted.TLabel", text="노란 표시는 이적료가 있는 이적입니다. "
                  "차트를 선택하고 좌우 방향키를 누르면 날짜별 값을 볼 수 있습니다.").pack(side="right")
        self.strip_fig = Figure(figsize=(8, 2.3), dpi=100, facecolor=theme.PITCH_LINE, constrained_layout=True)
        self.strip_canvas = FigureCanvasTkAgg(self.strip_fig, master=self)
        strip_widget = self.strip_canvas.get_tk_widget()
        strip_widget.configure(height=round(165 * scale), highlightthickness=round(2 * scale),
                               highlightbackground=theme.PITCH_LINE, highlightcolor=theme.CARD_YELLOW,
                               takefocus=1)
        strip_widget.pack(fill="x", **pad)
        self.strip_canvas.mpl_connect("resize_event", lambda _e: self.place_strip_labels())
        self.strip_canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.strip_canvas.mpl_connect("axes_leave_event", lambda _e: self.hide_hover())
        self.strip_canvas.mpl_connect("figure_leave_event", lambda _e: self.hide_hover())
        for key, delta in (("<Left>", -1), ("<Right>", 1)):
            strip_widget.bind(key, lambda _e, d=delta: self.key_hover(d))
        strip_widget.bind("<Escape>", lambda _e: self.hide_hover())
        strip_widget.bind("<FocusOut>", lambda _e: self.hide_hover())
        strip_widget.bind("<Button-1>", lambda _e: strip_widget.focus_set(), add="+")

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
            height=6, tree_column=("시즌", 100), style="Season.Treeview", left=("club",), pad=(0, 4),
        )
        tree = self.season_tree
        tree.tag_configure("parent", font=self.fonts.semibold())
        tree.tag_configure("zebra1", background=theme.PAPER)
        tree.tag_configure("hl", background=theme.mix(theme.CARD_YELLOW, theme.PITCH_LINE, 0.6))
        tree.bind("<<TreeviewSelect>>", lambda _e: self.on_table_select())
        tree.bind("<Motion>", self.on_table_motion)
        tree.bind("<Leave>", lambda _e: self.set_table_hover(None))
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
        # 펼쳐도 높이는 그대로 두고 스크롤로 보여 준다(위쪽 표와 그래프가 줄어들지 않게).
        self.transfer_tree.configure(height=LEDGER_COLLAPSED)
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
        self.row_tags = {}
        self.hl_label = None
        if self.seasons["league"]:
            self.no_league.pack_forget()
        elif self.card:
            self.no_league.pack(anchor="w", pady=(4, 0), before=tree.master)
        for i, group in enumerate(logic.season_groups(self.seasons[self.scope.get()])):
            parent = tree.insert("", "end", values=(group["club"], *self._pad(group["values"])),
                                 tags=("parent", f"zebra{i % 2}"))
            self.row_tags[parent] = ("parent", f"zebra{i % 2}")
            self.season_names[parent] = group["season"]
            self._set_open(parent, self.expanded)
            for name, values in group["children"]:
                tree.insert(parent, "end", text="", values=("    " + name, *self._pad(values)), tags=("child",))
        self.show_band(None)

    def _set_open(self, item, flag):
        marker = "▌" if self.season_names[item] == self.hl_label else ""
        self.season_tree.item(item, open=flag,
                              text=marker + ("－ " if flag else "＋ ") + self.season_names[item])

    # --- 차트 -> 표: hover 한 날짜의 시즌 행을 노란 막대(▌)와 배경으로 표시, 선택은 건드리지 않는다 ------------
    def highlight_season(self, label):
        if label == self.hl_label:
            return
        self.hl_label = label
        first = None
        for item in self.season_tree.get_children():
            hit = label is not None and self.season_names[item] == label
            base = self.row_tags[item]
            self.season_tree.item(item, tags=(base[0], "hl") if hit else base)
            self._set_open(item, bool(self.season_tree.item(item, "open")))
            if hit and first is None:
                first = item
        if first is not None:
            self.season_tree.see(first)

    # --- 표 -> 차트: 선택/hover 한 시즌의 띠 --------------------------------------------------------
    def _season_of_item(self, item):
        parent = self.season_tree.parent(item) or item
        return self.season_names.get(parent)

    def on_table_select(self):
        self._update_band()

    def on_table_motion(self, event):
        item = self.season_tree.identify_row(event.y)
        self.set_table_hover(self._season_of_item(item) if item else None)

    def set_table_hover(self, label):
        if label != self.table_hover:
            self.table_hover = label
            self._update_band()

    def _update_band(self):
        label = self.table_hover
        if label is None:
            selected = self.season_tree.selection()
            label = self._season_of_item(selected[0]) if selected else None
        self.show_band(int(label[:4]) if label else None)

    def show_band(self, season):
        if self.season_band is None:
            return
        shown = self.season_band.get_visible()
        if season is None:
            if shown:
                self.season_band.set_visible(False)
                self.strip_canvas.draw_idle()
            return
        start, end = logic.season_range(season)
        x0, x1 = _num(start), _num(f"{season + 1}-07-01")
        self.season_band.set_x(x0)
        self.season_band.set_width(x1 - x0)
        self.season_band.set_visible(True)
        self.strip_canvas.draw_idle()

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
        value.grid(False)                   # 시즌 띠가 이미 가로 구분을 하므로 격자선은 빼서 줄무늬가 겹치지 않게
        value.text(0, 1.04, "시장가치 (€M)", transform=value.transAxes, color=theme.MUTED, fontsize=9 * s,
                   ha="left", va="bottom")
        strip.set_axis_off()
        strip.set_ylim(0, 1)
        colors = (theme.TURF, theme.TURF_2, theme.YOUTH)
        for b in self.blocks:
            x0, x1 = _num(b["start"]), _num(b["end"])
            strip.broken_barh([(x0, x1 - x0)], (0, 1), facecolors=colors[b["color"]], edgecolor="none",
                              linewidth=0)                       # 블록은 [시작, 다음 시작) 그대로, 가장자리 여백 없음
            if (b["fee"] or 0) > 0:
                strip.plot([x0, x0], [0, 0.34], color=theme.CARD_YELLOW, linewidth=2.6 * s,
                           solid_capstyle="butt", zorder=4)
        if len(self.blocks) > 1:        # 경계마다 1px 흰 선 (틈이 아니라 선)
            strip.vlines([_num(b["start"]) for b in self.blocks[1:]], 0, 1, colors=theme.PITCH_LINE,
                         linewidth=0.72, zorder=3.5)
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
        else:
            value.text(0.5, 0.5, "시장가치 데이터 없음", ha="center", va="center", transform=value.transAxes,
                       color=theme.MUTED, fontsize=9 * s)
        if self.blocks:
            value.set_xlim(self.xlim_lo, _num(cutoff))
        self._draw_season_bands(value)
        self._make_hover(strip, value, s)
        self.place_strip_labels()

    # --- hover: 시장가치 선 위의 값 / 띠 블록의 구단·기간 -------------------------------------------
    def _make_hover(self, strip, value, s):
        self.value_ax = value
        self.val_points = sorted(self.valuations, key=lambda v: v["date"])
        self.val_nums = [_num(v["date"]) for v in self.val_points]
        box = {"boxstyle": "square,pad=0.45", "fc": theme.PITCH_LINE, "ec": theme.RULE, "lw": 1}
        self.hover_marker, = value.plot([], [], marker="o", markersize=7 * s, color=theme.CARD_YELLOW,
                                        markeredgecolor=theme.INK, markeredgewidth=0.8, linestyle="none",
                                        zorder=7, visible=False)
        self.hover_line = value.axvline(0, color=theme.RULE, linewidth=1.0, zorder=2, visible=False)
        self.hover_tip = value.annotate("", (0, 0), xytext=(10, 10), textcoords="offset points", fontsize=9 * s,
                                        color=theme.INK, bbox=box, zorder=12, visible=False, annotation_clip=False)
        self.strip_tip = strip.annotate("", (0, 0), xytext=(0, -8), textcoords="offset points", fontsize=9 * s,
                                        color=theme.INK, bbox=box, zorder=12, visible=False, annotation_clip=False)
        strip.set_zorder(3)                 # 띠 툴팁이 아래 시장가치 축 위에 그려지도록
        self.season_band = Rectangle((0, 0), 1, 1, transform=value.get_xaxis_transform(), zorder=1.5,
                                     facecolor=theme.CARD_YELLOW, alpha=0.35, edgecolor="none", visible=False)
        value.add_patch(self.season_band)
        # constrained layout 이 보이는 툴팁까지 자리 계산에 넣으면, 커서를 올릴 때마다 축이 움직여 띠가 들썩인다.
        for artist in (self.hover_marker, self.hover_line, self.hover_tip, self.strip_tip, self.season_band):
            artist.set_in_layout(False)

    def hide_hover(self):
        self.key_index = None
        changed = False
        for artist in (self.hover_marker, self.hover_line, self.hover_tip, self.strip_tip):
            if artist is not None and artist.get_visible():
                artist.set_visible(False)
                changed = True
        if changed:
            self.strip_canvas.draw_idle()
        self.highlight_season(None)

    def on_motion(self, event):
        now = time.monotonic()
        if now - self.last_motion < 1 / 30:          # 대략 30 fps 로 제한
            return
        self.last_motion = now
        if self.value_ax is None or event.inaxes is None or event.xdata is None:
            self.hide_hover()
            return
        if event.inaxes is self.value_ax and self.val_nums:
            self._hover_value(event.xdata)
        elif event.inaxes is self.strip_ax and self.blocks:
            self._hover_block(event.xdata)
        else:
            self.hide_hover()

    def _flip(self, ax, x):
        """축의 오른쪽 가까이면 툴팁을 왼쪽으로 뒤집는다."""
        lo, hi = ax.get_xlim()
        return (x - lo) / (hi - lo) > 0.65 if hi != lo else False

    def _hover_value(self, x):
        self._show_value(logic.nearest_index(self.val_nums, x))

    def key_hover(self, delta):
        """마우스 없이 시장가치 점을 훑는다: 처음 누르면 가장 최근 점, 이후 좌우로 한 점씩 (양 끝에서 멈춘다)."""
        if not self.val_nums:
            return
        last = len(self.val_nums) - 1
        index = last if self.key_index is None else min(max(self.key_index + delta, 0), last)
        self._show_value(index)

    def _show_value(self, i):
        self.key_index = i
        point = self.val_points[i]
        px, py = self.val_nums[i], point["market_value_eur"] / 1e6
        ax = self.value_ax
        self.hover_marker.set_data([px], [py])
        self.hover_line.set_xdata([px, px])
        tip = self.hover_tip
        tip.set_text("\n".join(logic.tooltip_lines(point)))
        tip.xy = (px, py)
        left = self._flip(ax, px)
        below = py > ax.get_ylim()[1] * 0.55
        tip.set_position((-12 if left else 12, -12 if below else 12))
        tip.set_ha("right" if left else "left")
        tip.set_va("top" if below else "bottom")
        for artist in (self.hover_marker, self.hover_line, tip):
            artist.set_visible(True)
        self.strip_tip.set_visible(False)
        self.highlight_season(logic.season_label(logic.season_of(point["date"])))
        self.strip_canvas.draw_idle()

    def _hover_block(self, x):
        cutoff = self.app.cutoff["game"]
        block = next((b for b in self.blocks if _num(b["start"]) <= x < _num(b["end"])), None)
        if block is None:
            self.hide_hover()
            return
        tip = self.strip_tip
        tip.set_text(logic.block_tooltip(block["club"], block["start"], block["end"], cutoff))
        tip.xy = (x, 0)
        left = self._flip(self.strip_ax, x)
        tip.set_ha("right" if left else "left")
        tip.set_position((-6 if left else 6, -8))
        tip.set_va("top")
        tip.set_visible(True)
        for artist in (self.hover_marker, self.hover_line, self.hover_tip):
            artist.set_visible(False)
        day = mdates.num2date(x).date().isoformat()
        self.highlight_season(logic.season_label(logic.season_of(day)))
        self.strip_canvas.draw_idle()

    def _draw_season_bands(self, value):
        """값 축 배경에 시즌(7/1~6/30)을 번갈아 아주 옅은 PAPER 띠로 깐다. 라벨은 place_strip_labels 에서 단다."""
        lo, hi = value.get_xlim()
        self.band_seasons = logic.season_bands(mdates.num2date(lo).date().isoformat(),
                                               mdates.num2date(hi).date().isoformat())
        for index, season in enumerate(self.band_seasons):
            if index % 2:
                value.axvspan(_num(f"{season}-07-01"), _num(f"{season + 1}-07-01"), facecolor=theme.PAPER,
                              edgecolor="none", zorder=0)
        value.set_xlim(lo, hi)

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
        self._place_season_ticks(measure_family=family, renderer=renderer)
        self.strip_canvas.draw_idle()

    def _place_season_ticks(self, *, measure_family, renderer):
        """연도 눈금 대신 각 시즌 띠 아래에 '20/21' 을 단다. 폭은 렌더러로 재고 겹치면 건너뛴다."""
        value = self.value_ax
        if value is None or not self.band_seasons:
            return
        s = self.chart_scale
        lo, hi = value.get_xlim()
        centers, labels, spans = [], [], []
        for season in self.band_seasons:
            x0, x1 = max(_num(f"{season}-07-01"), lo), min(_num(f"{season + 1}-07-01"), hi)
            if x1 <= x0:
                continue
            text = logic.short_season(season)
            probe = value.text(0, 0, text, fontsize=9 * s, fontfamily=measure_family)
            width = probe.get_window_extent(renderer).width
            probe.remove()
            px0, px1 = (value.transData.transform((x, 0))[0] for x in (x0, x1))
            if px1 - px0 < width:            # 보이는 폭이 라벨보다 좁은 시즌(축 끝의 잘린 시즌)은 라벨을 달지 않는다
                continue
            cx = (px0 + px1) / 2
            centers.append((x0 + x1) / 2)
            labels.append(text)
            spans.append((cx - width / 2, cx + width / 2))
        keep = logic.keep_uncolliding(spans, pad=6 * s)
        value.set_xticks([c for c, k in zip(centers, keep) if k], [t for t, k in zip(labels, keep) if k])
        value.tick_params(axis="x", length=0, labelsize=9 * s, labelcolor=theme.MUTED, pad=3 * s)

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
        ax.text(0, 1.03, "분", transform=ax.transAxes, color=theme.MUTED, fontsize=9 * s, ha="left", va="bottom")
        ax2 = ax.twinx()
        theme.style_axes(ax2, s, grid=False)
        ax2.spines["right"].set_visible(False)
        ax2.plot(xs, everything["ga"], color=theme.INK, linewidth=1.3, linestyle="--", label="공격포인트(전체)")
        ax2.plot(xs, [lg_ga.get(n, 0) for n in names], color=theme.INK, linewidth=1.8, marker="o",
                 markersize=3 * s, label="공격포인트(리그)")
        ax2.set_ylim(0, max(everything["ga"] + [1]) * 1.7)
        ax2.text(1, 1.03, "공격포인트", transform=ax2.transAxes, color=theme.MUTED, fontsize=9 * s,
                 ha="right", va="bottom")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax2.legend(h1[::-1] + h2[::-1], l1[::-1] + l2[::-1], loc="upper left", ncol=2, frameon=False,
                   fontsize=8.5 * s, labelcolor=theme.INK, columnspacing=1.0, handlelength=1.6)
