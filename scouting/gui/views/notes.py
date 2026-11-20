from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from scouting.services import notes
from .. import logic
from ..common import clear_tree, make_tree


class NotesView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=6)
        self.player = tk.StringVar()
        ttk.Label(bar, text="선수 ID").pack(side="left")
        ttk.Entry(bar, textvariable=self.player, width=10).pack(side="left")
        for label, command in (("작성", self.create), ("수정", self.edit), ("삭제", self.remove),
                               ("전체 조회", self.refresh), ("선수별 조회", self.by_player)):
            ttk.Button(bar, text=label, command=command).pack(side="left", padx=3)
        self.tree = make_tree(self, (
            ("note", "노트", 65), ("pid", "선수 ID", 75), ("name", "선수", 170, True),
            ("rating", "평점", 55), ("body", "내용", 380, True), ("updated", "수정", 145),
        ))

    def refresh(self):
        rows = notes.list_my_notes(self.app.conn, self.app.user.user_id) if self.app.user else []
        self._show(rows)

    def by_player(self):
        try:
            player_id = int(self.player.get())
        except ValueError:
            self.app.error(ValueError("선수 ID를 입력해 주세요."))
            return
        rows = notes.list_notes_for_player(self.app.conn, self.app.user.user_id, player_id)
        self._show([{**row, "player_name": "", "player_id": player_id} for row in rows])

    def _show(self, rows):
        clear_tree(self.tree)
        for row in rows:
            self.tree.insert("", "end", iid=str(row["note_id"]), values=(
                row["note_id"], row["player_id"], row.get("player_name", ""), row["rating"],
                row["body"].replace("\n", " "), logic.local_time(row["updated_at"]),
            ))

    def create(self):
        try:
            player_id = int(self.player.get())
        except ValueError:
            self.app.error(ValueError("선수 ID를 입력해 주세요."))
            return
        rating = simpledialog.askinteger("노트 작성", "평점(1~5):", minvalue=1, maxvalue=5, parent=self)
        if rating is None:
            return
        body = simpledialog.askstring("노트 작성", "내용(2000자 이하):", parent=self)
        if body is None:
            return
        try:
            notes.create_note(self.app.conn, self.app.user.user_id, player_id, rating, body)
        except Exception as exc:
            self.app.error(exc)
            return
        self.refresh()

    def edit(self):
        selection = self.tree.selection()
        if not selection:
            self.app.error(ValueError("노트를 선택해 주세요."))
            return
        rating = simpledialog.askinteger("노트 수정", "새 평점(1~5):", minvalue=1, maxvalue=5, parent=self)
        body = simpledialog.askstring("노트 수정", "새 내용(취소하면 기존 내용):", parent=self)
        if rating is not None or body is not None:
            notes.update_note(self.app.conn, self.app.user.user_id, int(selection[0]), rating=rating, body=body)
            self.refresh()

    def remove(self):
        selection = self.tree.selection()
        if selection and messagebox.askyesno("삭제", "노트를 삭제할까요?", parent=self):
            notes.delete_note(self.app.conn, self.app.user.user_id, int(selection[0]))
            self.refresh()
