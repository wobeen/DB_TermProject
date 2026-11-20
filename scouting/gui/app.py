"""Application shell for the Tkinter player career explorer."""

from __future__ import annotations

import argparse
import sqlite3
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from scouting import db
from scouting.cli.main import describe_db_error
from scouting.services import players
from . import logic, theme
from .common import BackgroundJobs, friendly_error
from .dpi import configure_tk_scaling, enable_dpi_awareness

enable_dpi_awareness()


class ScoutingApp:
    def __init__(self, root: tk.Tk, db_path=None):
        from .views import CareerView, SearchView

        self.root = root
        self.dpi = configure_tk_scaling(root)
        self.db_path = db.db_path(db_path)
        self.conn = db.connect(self.db_path)
        root.title(logic.TITLE)
        display_scale = self.dpi / 96.0
        root.geometry(f"{round(1280 * display_scale)}x{round(800 * display_scale)}")
        root.minsize(round(960 * display_scale), round(650 * display_scale))
        root.configure(background=theme.PAPER)

        self.fonts = theme.resolve_fonts(root)
        self.mpl_fonts = theme.configure_matplotlib(self.fonts)
        self.font = self.fonts.ko
        self._configure_style(root, display_scale)
        root.option_add("*TCombobox*Listbox.font", self.fonts.spec("body"))
        root.option_add("*TCombobox*Listbox.selectBackground", theme.CARD_YELLOW)
        root.option_add("*TCombobox*Listbox.selectForeground", theme.INK)

        self.cutoff = players.data_cutoff(self.conn)
        self.coverage = players.coverage_summary(self.conn)
        self.nationalities = players.nationalities(self.conn)

        band = ttk.Frame(root, style="Band.TFrame")
        band.pack(fill="x")
        ttk.Label(band, text=logic.TITLE, style="Band.TLabel").pack(side="left", padx=14, pady=8)
        ttk.Label(band, text=logic.banner_text(self.cutoff), style="BandSmall.TLabel").pack(
            side="right", padx=14)

        self.status_var = tk.StringVar(value="준비")
        ttk.Label(root, textvariable=self.status_var, style="Muted.TLabel", anchor="w").pack(
            fill="x", side="bottom", padx=12, pady=3)
        ttk.Separator(root, orient="horizontal").pack(fill="x", side="bottom")
        self.stage = ttk.Frame(root)
        self.stage.pack(fill="both", expand=True)
        self.search = SearchView(self, self.stage)
        self.career = CareerView(self, self.stage)
        for view in (self.search, self.career):
            view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.jobs = BackgroundJobs(root, self.db_path, self.set_status)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.show_search()

    def _configure_style(self, root, display_scale):
        style = ttk.Style(root)
        body = tkfont.Font(root=root, font=self.fonts.spec("body"))
        theme.configure_ttk(style, self.fonts, display_scale, body.metrics("linespace"))
        self.tree_font = body

    # --- navigation -------------------------------------------------------
    def show_search(self):
        self.search.tkraise()
        self.search.refresh_nav()

    def show_career(self):
        self.career.tkraise()
        self.career.refresh_nav()

    def open_career(self, player_id: int, index: int | None = None):
        """index: 검색 결과 안의 위치(이전/다음 선수용). 검색 없이 열면 None."""
        self.career.load(player_id, index)
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
