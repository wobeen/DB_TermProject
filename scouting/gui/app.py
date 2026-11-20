"""Application shell for the Tkinter scouting client."""

from __future__ import annotations

import argparse
import sqlite3
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from matplotlib import rcParams

from scouting import db
from scouting.cli.main import describe_db_error
from scouting.services import recommend, users
from .common import BackgroundJobs, friendly_error
from .dpi import configure_tk_scaling, enable_dpi_awareness

enable_dpi_awareness()
rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


class ScoutingApp:
    def __init__(self, root: tk.Tk, db_path=None, *, show_login=True):
        from .views import (
            BreakoutView, LoginDialog, NotesView, ProfileView, RecommendView,
            RunsView, SearchView, SimilarView, WatchView,
        )

        self.LoginDialog = LoginDialog
        self.root = root
        dpi = configure_tk_scaling(root)
        self.dpi = dpi
        self.db_path = db.db_path(db_path)
        self.conn = db.connect(self.db_path)
        self.user = None
        self.font = "Malgun Gothic" if "Malgun Gothic" in tkfont.families(root) else "TkDefaultFont"
        root.title("축구 유망주 스카우팅")
        display_scale = dpi / 96.0
        root.geometry(f"{round(1280 * display_scale)}x{round(800 * display_scale)}")
        root.minsize(round(960 * display_scale), round(650 * display_scale))
        style = ttk.Style(root)
        preferred_theme = "vista" if "vista" in style.theme_names() else "clam"
        style.theme_use(preferred_theme)
        style.configure(".", font=(self.font, 9))
        tree_font_name = style.lookup("Treeview", "font") or "TkDefaultFont"
        named_fonts = set(tkfont.names(root))
        tree_font = (tkfont.nametofont(tree_font_name, root=root) if tree_font_name in named_fonts
                     else tkfont.Font(root=root, font=tree_font_name))
        heading_font_name = style.lookup("Treeview.Heading", "font") or tree_font_name
        heading_font = (tkfont.nametofont(heading_font_name, root=root) if heading_font_name in named_fonts
                        else tkfont.Font(root=root, font=heading_font_name))
        vertical_padding = max(4, round(3 * display_scale))
        style.configure("Treeview", rowheight=tree_font.metrics("linespace") + vertical_padding * 2)
        style.configure("Treeview.Heading", padding=(round(5 * display_scale), vertical_padding),
                        font=heading_font)
        style.configure("TNotebook.Tab", padding=(round(10 * display_scale), round(5 * display_scale)))
        root.option_add("*Font", (self.font, 9))
        self.snapshots = recommend.list_snapshots(self.conn, built_only=True)
        self.definitions = recommend.list_definitions(self.conn)
        self.metrics = recommend.list_metrics(self.conn)
        self.snapshot_names = tuple(row["name"] for row in self.snapshots)
        self.definition_codes = tuple(row["code"] for row in self.definitions)
        self.metric_codes = tuple(row["metric_code"] for row in self.metrics)
        self.metric_names = {row["metric_code"]: row["name_ko"] for row in self.metrics}
        self.default_snapshot = "current" if "current" in self.snapshot_names else (self.snapshot_names[-1] if self.snapshot_names else "")
        self.default_definition = "peak_value_50m" if "peak_value_50m" in self.definition_codes else (self.definition_codes[0] if self.definition_codes else "")
        header = ttk.Frame(root)
        header.pack(fill="x", padx=10, pady=5)
        ttk.Label(header, text="축구 유망주 스카우팅", font=(self.font, 16, "bold")).pack(side="left")
        self.user_label = ttk.Label(header, text="로그인 필요")
        self.user_label.pack(side="right", padx=8)
        ttk.Button(header, text="로그아웃", command=self.logout).pack(side="right")
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.search = SearchView(self, self.notebook)
        self.profile = ProfileView(self, self.notebook)
        self.similar = SimilarView(self, self.notebook)
        self.recommend = RecommendView(self, self.notebook)
        self.runs = RunsView(self, self.notebook)
        self.watch = WatchView(self, self.notebook)
        self.note = NotesView(self, self.notebook)
        self.breakout = BreakoutView(self, self.notebook)
        tabs = (
            ("선수 검색", self.search), ("선수 프로필", self.profile), ("유사 선수", self.similar),
            ("추천", self.recommend), ("내 추천 기록", self.runs), ("워치리스트", self.watch),
            ("스카우팅 노트", self.note), ("기준 돌파 유망주", self.breakout),
        )
        for label, view in tabs:
            self.notebook.add(view, text=label)
        self.status_var = tk.StringVar(value="준비")
        ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")
        self.jobs = BackgroundJobs(root, self.db_path, self.set_status)
        root.protocol("WM_DELETE_WINDOW", self.close)
        if show_login:
            root.after(0, lambda: LoginDialog(self))

    def set_status(self, text):
        self.status_var.set(text)

    def error(self, exc):
        text = friendly_error(exc)
        self.set_status(f"오류: {text}")
        if self.root.winfo_viewable():
            messagebox.showerror("오류", text, parent=self.root)

    def login(self, user):
        self.user = user
        self.user_label.configure(text=f"현재 사용자: {user.username} ({user.role})")
        self.set_status("로그인했습니다.")
        self.runs.refresh()
        self.watch.refresh()
        self.note.refresh()

    def login_credentials(self, username, password):
        user = users.authenticate(self.conn, username, password)
        if user:
            self.login(user)
        return user

    def logout(self):
        self.user = None
        self.user_label.configure(text="로그인 필요")
        self.LoginDialog(self)

    def snapshot(self, name):
        found = next((row for row in self.snapshots if row["name"] == name), None)
        if found is None:
            raise ValueError("존재하지 않거나 미빌드된 스냅샷입니다.")
        return found

    def definition(self, code, optional=False):
        if optional and not code.strip():
            return None
        found = next((row for row in self.definitions if row["code"] == code), None)
        if found is None:
            raise ValueError("존재하지 않는 월드클래스 정의입니다.")
        return found

    def close(self):
        try:
            self.conn.close()
        finally:
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scouting.gui", description="축구 유망주 스카우팅 GUI")
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
