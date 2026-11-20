from __future__ import annotations

from tkinter import messagebox, simpledialog, ttk

from scouting.services import watchlist
from .. import logic
from ..common import clear_tree, make_tree


class WatchView(ttk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=6)
        ttk.Button(bar, text="새로고침", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="메모 수정", command=self.edit).pack(side="left", padx=4)
        ttk.Button(bar, text="삭제", command=self.remove).pack(side="left")
        self.tree = make_tree(self, (
            ("id", "ID", 75), ("name", "이름", 180, True), ("pos", "포지션", 70),
            ("club", "구단", 180, True), ("value", "시장가치", 100), ("memo", "메모", 260, True),
        ))

    def refresh(self):
        clear_tree(self.tree)
        if not self.app.user:
            return
        for row in watchlist.list_watchlist(self.app.conn, self.app.user.user_id):
            self.tree.insert("", "end", iid=str(row["player_id"]), values=(
                row["player_id"], row["name"], row["pos_group"], row["current_club_name"],
                logic.eur(row["latest_value_eur"]), row["memo"] or "",
            ))

    def edit(self):
        selection = self.tree.selection()
        if not selection:
            self.app.error(ValueError("선수를 선택해 주세요."))
            return
        memo = simpledialog.askstring("메모 수정", "새 메모:", parent=self)
        if memo is not None:
            watchlist.update_watch_memo(self.app.conn, self.app.user.user_id, int(selection[0]), memo or None)
            self.refresh()

    def remove(self):
        selection = self.tree.selection()
        if selection and messagebox.askyesno("삭제", "워치리스트에서 삭제할까요?", parent=self):
            watchlist.remove_from_watchlist(self.app.conn, self.app.user.user_id, int(selection[0]))
            self.refresh()
