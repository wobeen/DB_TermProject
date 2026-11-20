"""Application shell for the Tkinter player career explorer."""

from __future__ import annotations

import argparse
import sqlite3
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from matplotlib import rcParams

from scouting import db
from scouting.cli.main import describe_db_error
from scouting.services import players
from . import logic
from .common import BackgroundJobs, friendly_error
from .dpi import configure_tk_scaling, enable_dpi_awareness

enable_dpi_awareness()
rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


class ScoutingApp:
    def __init__(self, root: tk.Tk, db_path=None):
        from .views import CareerView, SearchView

        self.root = root
        self.dpi = configure_tk_scaling(root)
        self.db_path = db.db_path(db_path)
        self.conn = db.connect(self.db_path)
        self.font = "Malgun Gothic" if "Malgun Gothic" in tkfont.families(root) else "TkDefaultFont"
        root.title(logic.TITLE)
        display_scale = self.dpi / 96.0
        root.geometry(f"{round(1280 * display_scale)}x{round(800 * display_scale)}")
        root.minsize(round(960 * display_scale), round(650 * display_scale))
        self._configure_style(root, display_scale)
        root.option_add("*Font", (self.font, 9))

        self.cutoff = players.data_cutoff(self.conn)
        self.coverage = players.coverage_summary(self.conn)
        self.nationalities = players.nationalities(self.conn)

        header = ttk.Frame(root)
        header.pack(fill="x", padx=12, pady=(8, 2))
        ttk.Label(header, text=logic.TITLE, font=(self.font, 16, "bold")).pack(anchor="w")
        ttk.Label(header, text=logic.DESCRIPTION).pack(anchor="w")
        ttk.Label(header, text=logic.banner_text(self.cutoff), foreground="#a33a00",
                  font=(self.font, 9, "bold")).pack(anchor="w", pady=(2, 0))

        self.status_var = tk.StringVar(value="준비")
        ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")
        self.stage = ttk.Frame(root)
        self.stage.pack(fill="both", expand=True)
        self.search = SearchView(self, self.stage)
        self.career = CareerView(self, self.stage)
        for view in (self.search, self.career):
            view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.history: list[int] = []     # 연 순서대로의 선수 ID
        self.pos = -1                    # history 안의 현재 위치
        self.jobs = BackgroundJobs(root, self.db_path, self.set_status)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.show_search()

    def _configure_style(self, root, display_scale):
        style = ttk.Style(root)
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        style.configure(".", font=(self.font, 9))
        tree_font_name = style.lookup("Treeview", "font") or "TkDefaultFont"
        named = set(tkfont.names(root))
        tree_font = (tkfont.nametofont(tree_font_name, root=root) if tree_font_name in named
                     else tkfont.Font(root=root, font=tree_font_name))
        heading_name = style.lookup("Treeview.Heading", "font") or tree_font_name
        heading_font = (tkfont.nametofont(heading_name, root=root) if heading_name in named
                        else tkfont.Font(root=root, font=heading_name))
        pad = max(3, round(2 * display_scale))
        style.configure("Treeview", rowheight=tree_font.metrics("linespace") + pad * 2)
        style.configure("Treeview.Heading", padding=(round(4 * display_scale), pad), font=heading_font)
        self.tree_font = tree_font

    # --- navigation -------------------------------------------------------
    def show_search(self):
        self.search.tkraise()
        self.search.refresh_nav()

    def show_career(self):
        self.career.tkraise()
        self.career.refresh_nav()

    def open_career(self, player_id: int):
        """검색 결과에서 선수를 연다. 뒤로 간 상태였다면 앞쪽 기록은 버린다."""
        del self.history[self.pos + 1:]
        if not self.history or self.history[-1] != int(player_id):
            self.history.append(int(player_id))
        self.pos = len(self.history) - 1
        self.career.load(self.history[self.pos])
        self.show_career()

    def step(self, delta: int):
        target = self.pos + delta
        if 0 <= target < len(self.history):
            self.pos = target
            self.career.load(self.history[target])
            self.show_career()

    # --- misc ---------------------------------------------------------------
    def set_status(self, text):
        self.status_var.set(text)

    def error(self, exc):
        text = friendly_error(exc)
        self.set_status(f"오류: {text}")
        if self.root.winfo_viewable():
            messagebox.showerror("오류", text, parent=self.root)

    def close(self):
        try:
            self.conn.close()
        finally:
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scouting.gui", description=logic.TITLE)
    parser.add_argument("--db")
    args = parser.parse_args(argv)
    root = tk.Tk()
    root.withdraw()
    try:
        ScoutingApp(root, args.db)
    except (sqlite3.Error, RuntimeError) as exc:
        messagebox.showerror("DB 오류", describe_db_error(exc, args.db), parent=root)
        root.destroy()
        return 1
    root.deiconify()
    root.mainloop()
    return 0
