"""Design tokens, font resolution and ttk/matplotlib styling for the career explorer.

Matchday-kit palette: turf green, white pitch lines, one yellow-card accent.
"""

from __future__ import annotations

from dataclasses import dataclass

TURF = "#1F4D3A"
TURF_2 = "#3F8A66"
PITCH_LINE = "#FFFFFF"
PAPER = "#EEF1EE"
INK = "#1C2B24"
MUTED = "#66756D"
RULE = "#CBD5CE"
CARD_YELLOW = "#F2C230"
CARD_RED = "#C23B33"


def mix(hex_color: str, with_color: str = PITCH_LINE, amount: float = 0.55) -> str:
    """hex_color 를 with_color 쪽으로 amount 만큼 섞는다 (amount=0.55 -> 원색 45% 틴트)."""
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(with_color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(a, b))


ZEBRA = mix(PAPER, PITCH_LINE, 0.3)       # 흰 표 위의 얇은 줄무늬
TURF_2_TINT = mix(TURF_2)                 # 전체 대회 막대 (45% 틴트)
YOUTH = "#A9C7B5"                         # 커리어 띠의 유스 블록 (INK 글씨)

KO_ORDER = ("Noto Sans KR", "맑은 고딕", "Malgun Gothic", "Segoe UI")
DISPLAY_ORDER = ("Bahnschrift SemiBold Condensed", "Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold")
NUM_ORDER = ("Bahnschrift", "Segoe UI")

SIZES = {"name": 28, "section": 13, "body": 10, "label": 9, "big": 18}


def _first(available, order, default):
    for family in order:
        if family in available:
            return family
    return default


@dataclass(frozen=True)
class Fonts:
    ko: str
    ko_semibold: str | None        # 별도 패밀리로 존재할 때만 (예: "Noto Sans KR Medium")
    display: str
    num: str

    def spec(self, kind: str) -> tuple:
        size = SIZES[kind]
        if kind == "name":
            return (self.display, size)
        if kind == "big":
            return (self.num, size)
        if kind == "section":
            return (self.ko_semibold, size) if self.ko_semibold else (self.ko, size, "bold")
        return (self.ko, size)

    def semibold(self, size: int = SIZES["body"]) -> tuple:
        return (self.ko_semibold, size) if self.ko_semibold else (self.ko, size, "bold")

    def summary(self) -> dict:
        return {"ko": self.ko, "ko_semibold": self.ko_semibold, "display": self.display, "num": self.num}


def resolve_fonts(root) -> Fonts:
    """tkinter 에 실제로 설치된 패밀리에서 폴백 순서대로 고른다."""
    import tkinter.font as tkfont

    available = set(tkfont.families(root))
    ko = _first(available, KO_ORDER, "TkDefaultFont")
    medium = f"{ko} Medium"
    return Fonts(
        ko=ko,
        ko_semibold=medium if medium in available else None,
        display=_first(available, DISPLAY_ORDER, ko),
        num=_first(available, NUM_ORDER, ko),
    )


def configure_matplotlib(fonts: Fonts) -> dict:
    """matplotlib 도 같은 폴백 순서를 쓴다. 숫자/라틴은 Bahnschrift, 한글은 Noto Sans KR 로 글리프 단위 폴백."""
    from matplotlib import font_manager, rcParams

    names = {f.name for f in font_manager.fontManager.ttflist}
    ko = _first(names, ("Noto Sans KR", "Malgun Gothic", "Segoe UI"), "DejaVu Sans")
    num = _first(names, ("Bahnschrift", ko), ko)
    rcParams["font.family"] = [num, ko, "DejaVu Sans"] if num != ko else [ko, "DejaVu Sans"]
    rcParams["axes.unicode_minus"] = False
    return {"ko": ko, "num": num}


def style_axes(ax, scale: float = 1.0, *, grid: bool = True) -> None:
    """모든 차트가 쓰는 공통 스타일: 흰 바탕, 위/오른쪽 선 없음, y 격자만 RULE, 눈금은 MUTED."""
    ax.set_facecolor(PITCH_LINE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=8 * scale, length=3 * scale, color=RULE)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    if grid:
        ax.grid(axis="y", color=RULE, linewidth=0.7)
        ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)


def configure_ttk(style, fonts: Fonts, display_scale: float, tree_linespace: int) -> None:
    """clam 기반으로 색을 입힌다. 선택 행/포커스 링은 CARD_YELLOW."""
    style.theme_use("clam")
    body, label = fonts.spec("body"), fonts.spec("label")
    pad = max(3, round(2 * display_scale))
    style.configure(".", background=PAPER, foreground=INK, font=body, bordercolor=RULE,
                    lightcolor=PAPER, darkcolor=PAPER, troughcolor=PAPER, focuscolor=CARD_YELLOW,
                    selectbackground=CARD_YELLOW, selectforeground=INK)
    style.configure("TFrame", background=PAPER)
    style.configure("Band.TFrame", background=TURF)
    style.configure("Rail.TFrame", background=TURF)
    style.configure("Surface.TFrame", background=PITCH_LINE)
    style.configure("TLabel", background=PAPER, foreground=INK, font=body)
    style.configure("Muted.TLabel", foreground=MUTED, font=label)
    style.configure("Band.TLabel", background=TURF, foreground=PITCH_LINE, font=fonts.semibold(15))
    style.configure("BandSmall.TLabel", background=TURF, foreground=PITCH_LINE, font=label)
    style.configure("Rail.TLabel", background=TURF, foreground=PITCH_LINE, font=label)
    style.configure("RailNote.TLabel", background=TURF, foreground=mix(TURF, PITCH_LINE, 0.7), font=label)
    style.configure("RailError.TLabel", background=PAPER, foreground=CARD_RED, font=label, padding=(4, 1))
    style.configure("RailTitle.TLabel", background=TURF, foreground=PITCH_LINE, font=fonts.spec("section"))
    style.configure("Name.TLabel", font=fonts.spec("name"))
    style.configure("Section.TLabel", font=fonts.spec("section"))
    style.configure("Big.TLabel", font=fonts.spec("big"))
    style.configure("Pill.TLabel", background=CARD_YELLOW, foreground=INK, font=fonts.semibold(10),
                    padding=(round(10 * display_scale), 1))
    style.configure("Error.TLabel", foreground=CARD_RED)
    style.configure("Empty.TLabel", background=PITCH_LINE, foreground=MUTED, font=body)

    arrow = round(14 * display_scale)        # clam 은 arrowsize 를 DPI 에 맞춰 키워 주지 않는다
    btn_pad = (round(12 * display_scale), round(4 * display_scale))
    style.configure("TButton", background=PITCH_LINE, foreground=INK, bordercolor=RULE, relief="flat",
                    padding=btn_pad, focuscolor=CARD_YELLOW, lightcolor=PITCH_LINE, darkcolor=PITCH_LINE)
    style.map("TButton", background=[("active", PAPER), ("disabled", PAPER)],
              foreground=[("disabled", MUTED)], bordercolor=[("focus", CARD_YELLOW)])
    style.configure("Primary.TButton", background=TURF, foreground=PITCH_LINE, bordercolor=TURF,
                    lightcolor=TURF, darkcolor=TURF, font=fonts.semibold(10))
    style.map("Primary.TButton", background=[("active", TURF_2), ("disabled", mix(TURF))],
              foreground=[("disabled", PITCH_LINE)], bordercolor=[("focus", CARD_YELLOW)],
              lightcolor=[("active", TURF_2)], darkcolor=[("active", TURF_2)])
    # 초록 레일 위에서는 TURF 단추가 보이지 않으므로 색을 뒤집는다.
    style.configure("RailPrimary.TButton", background=PITCH_LINE, foreground=TURF, bordercolor=PITCH_LINE,
                    font=fonts.semibold(10))
    style.map("RailPrimary.TButton", background=[("active", PAPER), ("disabled", mix(TURF))],
              foreground=[("disabled", PITCH_LINE)], bordercolor=[("focus", CARD_YELLOW)])
    # 전체 대회 / 리그만 같은 두 칸 토글: 선택은 TURF 바탕 흰 글씨, 비선택은 흰 바탕 RULE 테두리
    style.configure("SegOn.TButton", background=TURF, foreground=PITCH_LINE, bordercolor=TURF,
                    lightcolor=TURF, darkcolor=TURF, font=fonts.semibold(10))
    style.map("SegOn.TButton", background=[("active", TURF_2)], bordercolor=[("focus", CARD_YELLOW)])
    style.configure("SegOff.TButton", background=PITCH_LINE, foreground=INK, bordercolor=RULE)
    style.map("SegOff.TButton", background=[("active", PAPER)], bordercolor=[("focus", CARD_YELLOW)])
    style.configure("Rail.TButton", background=TURF, foreground=PITCH_LINE, bordercolor=TURF_2,
                    lightcolor=TURF, darkcolor=TURF)
    style.map("Rail.TButton", background=[("active", TURF_2)], bordercolor=[("focus", CARD_YELLOW)])

    for name in ("TEntry", "TCombobox"):
        style.configure(name, fieldbackground=PITCH_LINE, background=PITCH_LINE, foreground=INK,
                        bordercolor=RULE, lightcolor=PITCH_LINE, darkcolor=PITCH_LINE, insertcolor=INK,
                        arrowcolor=MUTED, padding=(4, 3), arrowsize=arrow)
        style.map(name, bordercolor=[("focus", CARD_YELLOW)], lightcolor=[("focus", CARD_YELLOW)],
                  darkcolor=[("focus", CARD_YELLOW)], fieldbackground=[("readonly", PITCH_LINE)],
                  foreground=[("readonly", INK)], selectbackground=[("readonly", PITCH_LINE)],
                  selectforeground=[("readonly", INK)])
    style.configure("TRadiobutton", background=PAPER, foreground=INK, indicatorcolor=PITCH_LINE,
                    focuscolor=CARD_YELLOW)
    style.map("TRadiobutton", indicatorcolor=[("selected", TURF)], background=[("active", PAPER)])
    style.configure("TScrollbar", background=RULE, troughcolor=PAPER, bordercolor=PAPER, arrowcolor=MUTED,
                    lightcolor=RULE, darkcolor=RULE, arrowsize=arrow, width=arrow)
    style.map("TScrollbar", background=[("active", MUTED)])

    tree_kw = dict(background=PITCH_LINE, fieldbackground=PITCH_LINE, foreground=INK, bordercolor=RULE,
                   lightcolor=PITCH_LINE, darkcolor=PITCH_LINE, rowheight=tree_linespace + pad * 2, font=body)
    style.configure("Treeview", **tree_kw)
    style.configure("Season.Treeview", **{**tree_kw, "rowheight": round(tree_linespace * 1.4)})
    # 기본 펼침 화살표는 작아서 빼고, 시즌 칸의 ＋/－ 글자가 그 역할을 한다 (행 어디를 눌러도 토글).
    style.layout("Season.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
        ("Treeitem.image", {"side": "left", "sticky": ""}),
        ("Treeitem.focus", {"side": "left", "sticky": "", "children": [
            ("Treeitem.text", {"side": "left", "sticky": ""})]})]})])
    style.map("Treeview", background=[("selected", CARD_YELLOW)], foreground=[("selected", INK)])
    style.map("Season.Treeview", background=[("selected", CARD_YELLOW)], foreground=[("selected", INK)])
    style.configure("Treeview.Heading", background=PAPER, foreground=MUTED, relief="flat", borderwidth=0,
                    font=fonts.semibold(9), padding=(round(4 * display_scale), pad), lightcolor=PAPER,
                    darkcolor=PAPER, bordercolor=RULE)
    style.map("Treeview.Heading", background=[("active", PAPER)], relief=[("pressed", "flat")])
