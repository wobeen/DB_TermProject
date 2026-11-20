"""Shared Tk widgets and background-service execution."""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from scouting import db
from scouting.cli.main import is_locked, translate_integrity


def clear_tree(tree: ttk.Treeview) -> None:
    tree.delete(*tree.get_children())


def make_tree(parent, columns, *, height=12, horizontal=False, left=(), tree_column=None,
              style=None) -> ttk.Treeview:
    """tree_column=(label, width) 를 주면 #0 열을 계층 표시용으로 쓴다."""
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True, padx=8, pady=6)
    keys = [column[0] for column in columns]
    options = {"style": style} if style else {}
    tree = ttk.Treeview(frame, columns=keys, show="tree headings" if tree_column else "headings",
                        height=height, **options)
    try:
        width_scale = float(parent.winfo_fpixels("1i")) / 96.0
    except Exception:
        width_scale = 1.0
    if tree_column:
        tree.heading("#0", text=tree_column[0], anchor="w")
        tree.column("#0", width=round(tree_column[1] * width_scale), anchor="w", stretch=True)
    text_columns = set(left)
    centered_columns = set()
    for key, label, width, *stretch in columns:
        anchor = "w" if key in text_columns else ("center" if key in centered_columns else "e")
        tree.heading(key, text=label)
        tree.column(
            key, width=round(width * width_scale), anchor=anchor, stretch=bool(stretch and stretch[0]),
        )
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vertical.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    if horizontal:
        horizontal_bar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=horizontal_bar.set)
        horizontal_bar.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return tree


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, sqlite3.IntegrityError):
        return translate_integrity(exc)
    if isinstance(exc, sqlite3.OperationalError) and is_locked(exc):
        return "다른 작업이 DB를 사용 중입니다"
    return str(exc) or exc.__class__.__name__


class BackgroundJobs:
    def __init__(self, root, db_path: Path, status):
        self.root = root
        self.db_path = db_path
        self.status = status

    def submit(self, label, job, on_success=lambda _result: None, *, button=None, on_error=None):
        start = time.perf_counter()
        delivery = queue.Queue(maxsize=1)
        ready = threading.Event()
        if button is not None:
            button.configure(state="disabled")
        self.status(f"{label} 중...")

        def worker():
            connection = None
            try:
                connection = db.connect(self.db_path)
                delivery.put((job(connection), None))
            except Exception as exc:
                delivery.put((None, exc))
            finally:
                if connection is not None:
                    connection.close()
                ready.set()

        def finish(result, error):
            if button is not None:
                button.configure(state="normal")
            elapsed = time.perf_counter() - start
            if error is None:
                self.status(f"{label} 완료 ({elapsed:.1f}초)")
                on_success(result)
                return
            text = friendly_error(error)
            self.status(f"오류: {text}")
            if (isinstance(error, sqlite3.OperationalError) and is_locked(error)
                    and isinstance(self.root, tk.Misc)
                    and messagebox.askretrycancel("DB 사용 중", text, parent=self.root)):
                self.submit(label, job, on_success, button=button, on_error=on_error)
                return
            if on_error:
                on_error(error)

        def poll():
            try:
                result, error = delivery.get_nowait()
            except queue.Empty:
                self.status(f"{label} 중... ({time.perf_counter() - start:.1f}초)")
                self.root.after(100, poll)
            else:
                finish(result, error)

        thread = threading.Thread(target=worker, daemon=True, name=f"scouting-{label}")
        thread.start()
        ready.wait(0.05)
        self.root.after(0, poll)
        return thread
