from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from scouting.services import users
from ..common import friendly_error


class LoginDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("로그인 / 회원가입")
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        ttk.Label(self, text="사용자명").grid(row=0, column=0, padx=10, pady=8)
        ttk.Entry(self, textvariable=self.username, width=25).grid(row=0, column=1, padx=10)
        ttk.Label(self, text="비밀번호").grid(row=1, column=0, padx=10, pady=8)
        ttk.Entry(self, textvariable=self.password, show="•", width=25).grid(row=1, column=1, padx=10)
        self.msg = ttk.Label(self, foreground="firebrick")
        self.msg.grid(row=2, column=0, columnspan=2)
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, columnspan=2, pady=10)
        ttk.Button(buttons, text="로그인", command=self.login).pack(side="left", padx=4)
        ttk.Button(buttons, text="회원가입", command=self.register).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", app.root.destroy)

    def login(self):
        user = users.authenticate(self.app.conn, self.username.get(), self.password.get())
        if user:
            self.app.login(user)
            self.destroy()
        else:
            self.msg.configure(text="사용자명 또는 비밀번호가 올바르지 않습니다.")

    def register(self):
        problem = users.username_problem(self.app.conn, self.username.get())
        if problem:
            self.msg.configure(text=problem)
            return
        if len(self.password.get()) < users.MIN_PASSWORD_LEN:
            self.msg.configure(text=f"비밀번호는 {users.MIN_PASSWORD_LEN}자 이상이어야 합니다.")
            return
        try:
            users.register(self.app.conn, self.username.get(), self.password.get())
        except Exception as exc:
            self.msg.configure(text=friendly_error(exc))
            return
        self.msg.configure(text="가입 완료. 로그인해 주세요.", foreground="darkgreen")
