"""Reusable widgets: autocomplete entry popup and the formation pitch picker."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import logic, theme

DEBOUNCE_MS = 150
MAX_ROWS = 8
_IGNORED_KEYS = {"Down", "Up", "Return", "Escape", "Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L",
                 "Control_R", "Alt_L", "Alt_R", "Left", "Right", "Home", "End"}


class Autocomplete:
    """ttk.Entry 에 붙이는 연관검색어 팝업.

    - 입력이 멈추고 150 ms 뒤에 조회한다. job(text) -> (connection -> 목록) 이면 백그라운드 작업으로, local(text) -> 목록 이면
      바로 계산한다. 늦게 도착한 오래된 결과는 버린다.
    - ↓/↑ 이동, Enter 선택(고르지 않았다면 그대로 통과해 일반 검색), Esc 닫기, Tab 은 고른 항목을 받아들이고 포커스를 넘긴다.
    - 팝업은 테두리 없는 Toplevel + Listbox(최대 8줄). 포커스를 잃거나 창이 움직이거나 크기가 바뀌면 닫힌다.
    """

    def __init__(self, entry, app, *, render, on_accept, job=None, local=None, min_chars=2, rows=MAX_ROWS):
        self.entry, self.app = entry, app
        self.render, self.on_accept = render, on_accept
        self.job, self.local = job, local
        self.min_chars, self.rows = min_chars, rows
        self.popup = None
        self.listbox = None
        self.items: list = []
        self.index = -1
        self.token = 0
        self.after_id = None
        self.last_text = ""
        entry.bind("<KeyRelease>", self.on_key, add="+")
        entry.bind("<Down>", self.on_down, add="+")
        entry.bind("<Up>", self.on_up, add="+")
        entry.bind("<Return>", self.on_return, add="+")
        entry.bind("<Escape>", self.on_escape, add="+")
        entry.bind("<Tab>", self.on_tab, add="+")
        entry.bind("<FocusOut>", self.on_focus_out, add="+")
        entry.bind("<Unmap>", lambda _e: self.close(), add="+")
        entry.bind("<Destroy>", lambda _e: self.close(), add="+")
        self.toplevel = entry.winfo_toplevel()
        self.toplevel.bind("<Configure>", self.on_window_change, add="+")

    # --- 입력 -----------------------------------------------------------------
    def text(self) -> str:
        return self.entry.get()

    def on_key(self, event):
        if event.keysym in _IGNORED_KEYS:
            return None
        text = self.text()
        if text == self.last_text:
            return None
        self.last_text = text
        if self.after_id is not None:
            self.entry.after_cancel(self.after_id)
            self.after_id = None
        if len(text.strip()) < self.min_chars:
            self.close()
            return None
        self.after_id = self.entry.after(DEBOUNCE_MS, self.query)
        return None

    def query(self):
        self.after_id = None
        text = self.text()
        if len(text.strip()) < self.min_chars:
            self.close()
            return
        self.token += 1
        token = self.token
        if self.local is not None:
            self.deliver(token, text, self.local(text))
            return
        self.app.jobs.submit("연관검색", self.job(text), lambda items: self.deliver(token, text, items),
                             quiet=True, on_error=lambda _e: None)

    def deliver(self, token, text, items):
        if token != self.token or text != self.text():      # 오래된 결과는 버린다
            return
        self.show(list(items)[: self.rows])

    # --- 팝업 ------------------------------------------------------------------
    def show(self, items):
        if not items or not self.entry.winfo_exists() or not self.entry.winfo_ismapped():
            self.close()
            return
        self.items = items
        self.index = -1
        if self.popup is None:
            self.popup = tk.Toplevel(self.entry)
            self.popup.withdraw()
            self.popup.overrideredirect(True)
            self.popup.configure(background=theme.RULE)
            try:
                self.popup.attributes("-topmost", True)
            except tk.TclError:
                pass
            font = self.app.fonts.spec("body")
            self.listbox = tk.Listbox(
                self.popup, font=font, background=theme.PITCH_LINE, foreground=theme.INK,
                selectbackground=theme.CARD_YELLOW, selectforeground=theme.INK, activestyle="none",
                borderwidth=0, highlightthickness=0, exportselection=False, takefocus=0)
            self.listbox.pack(fill="both", expand=True, padx=1, pady=1)
            self.listbox.bind("<Button-1>", self.on_click)
            self.listbox.bind("<Motion>", self.on_hover)
        self.listbox.delete(0, "end")
        font = tkfont.Font(root=self.entry, font=self.app.fonts.spec("body"))
        widest = 0
        for item in items:
            row = self.render(item)
            self.listbox.insert("end", row)
            widest = max(widest, font.measure(row))
        self.listbox.configure(height=len(items))
        scale = self.app.dpi / 96.0
        width = max(self.entry.winfo_width(), min(widest + round(28 * scale), round(620 * scale)))
        self.popup.update_idletasks()
        height = self.listbox.winfo_reqheight() + 2
        x, y = self.entry.winfo_rootx(), self.entry.winfo_rooty() + self.entry.winfo_height() + 1
        self.popup.geometry(f"{width}x{height}+{x}+{y}")
        self.popup.deiconify()
        self.popup.lift()

    def close(self):
        self.token += 1                       # 진행 중인 조회 결과도 무효
        if self.popup is not None:
            try:
                self.popup.destroy()
            except tk.TclError:
                pass
        self.popup = self.listbox = None
        self.items = []
        self.index = -1

    def is_open(self) -> bool:
        return self.popup is not None

    def highlight(self, index):
        if not self.is_open():
            return
        self.listbox.selection_clear(0, "end")
        self.index = index
        if index >= 0:
            self.listbox.selection_set(index)
            self.listbox.see(index)

    def accept(self, index):
        if not 0 <= index < len(self.items):
            return
        item = self.items[index]
        self.close()
        self.last_text = ""
        self.on_accept(item)
        self.last_text = self.text()

    # --- 키/마우스 -------------------------------------------------------------------
    def on_down(self, _event):
        if not self.is_open():
            if len(self.text().strip()) >= self.min_chars:
                self.query()
            return "break"
        self.highlight(min(self.index + 1, len(self.items) - 1))
        return "break"

    def on_up(self, _event):
        if self.is_open():
            self.highlight(self.index - 1)
            return "break"
        return None

    def on_return(self, _event):
        if self.is_open() and self.index >= 0:
            self.accept(self.index)
            return "break"
        self.close()                          # 고르지 않은 Enter 는 일반 검색으로 넘어간다
        return None

    def on_escape(self, _event):
        if self.is_open():
            self.close()
            return "break"
        return None

    def on_tab(self, _event):
        if self.is_open() and self.index >= 0:
            self.accept(self.index)           # 받아들이고 포커스는 그대로 다음 칸으로
        else:
            self.close()
        return None

    def on_click(self, event):
        self.accept(self.listbox.nearest(event.y))
        return "break"                        # 클릭이 포커스를 가져가지 못하게

    def on_hover(self, event):
        index = self.listbox.nearest(event.y)
        if index != self.index:
            self.highlight(index)

    def on_focus_out(self, _event):
        self.entry.after(150, self._close_if_unfocused)

    def _close_if_unfocused(self):
        try:
            focused = self.entry.focus_displayof()
        except (tk.TclError, KeyError):
            focused = None
        if focused is not self.entry:
            self.close()

    def on_window_change(self, event):
        if event.widget is self.toplevel and self.is_open():
            self.close()


class PitchPicker(ttk.Frame):
    """포메이션을 골라 그 포메이션의 자리(슬롯)를 점으로 보여 주고, 점을 눌러 원하는 포지션 코드를 고른다.

    공격이 위쪽, GK 가 아래쪽. 같은 코드의 점(예: CB 둘)은 하나의 선택으로 묶인다.
    """

    def __init__(self, parent, app, on_change=None):
        super().__init__(parent, style="Rail.TFrame")
        self.app = app
        self.on_change = on_change
        scale = app.dpi / 96.0
        self.scale = scale
        self.width = round(250 * scale) - 28       # 레일 너비 - 좌우 여백(padx 14 픽셀 x 2)
        self.height = round(self.width * 0.88)
        self.formation = ""
        self.selected: list[str] = []
        self.slots: list[tuple[str, float, float]] = []
        self.cursor = 0
        self.canvas = tk.Canvas(self, width=self.width, height=self.height, background=theme.TURF,
                                highlightthickness=round(2 * scale), highlightbackground=theme.TURF,
                                highlightcolor=theme.CARD_YELLOW, takefocus=1, borderwidth=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Left>", lambda _e: self.move_cursor(-1))
        self.canvas.bind("<Right>", lambda _e: self.move_cursor(1))
        self.canvas.bind("<space>", lambda _e: self.toggle_cursor())
        self.canvas.bind("<Return>", lambda _e: self.toggle_cursor())
        self.canvas.bind("<FocusIn>", lambda _e: self.redraw())
        self.canvas.bind("<FocusOut>", lambda _e: self.redraw())
        self.redraw()

    # --- 상태 --------------------------------------------------------------------
    def set_formation(self, name: str) -> None:
        self.formation = name if name in logic.FORMATIONS else ""
        self.selected = []
        self.cursor = 0
        self.redraw()
        self._changed()

    def toggle(self, code: str) -> None:
        if code not in logic.POSITION_SUBS:
            return
        if code in self.selected:
            self.selected.remove(code)
        else:
            self.selected.append(code)
        self.redraw()
        self._changed()

    def clear(self) -> None:
        self.selected = []
        self.redraw()
        self._changed()

    def codes(self) -> list[str]:
        return list(self.selected)

    def _changed(self):
        if self.on_change:
            self.on_change()

    # --- 키보드 ------------------------------------------------------------------
    def move_cursor(self, delta: int):
        if self.slots:
            self.cursor = (self.cursor + delta) % len(self.slots)
            self.redraw()
        return "break"

    def toggle_cursor(self):
        if self.slots:
            self.toggle(self.slots[self.cursor][0])
        return "break"

    # --- 마우스 ------------------------------------------------------------------
    def on_click(self, event):
        self.canvas.focus_set()
        for item in reversed(self.canvas.find_overlapping(event.x - 1, event.y - 1, event.x + 1, event.y + 1)):
            for tag in self.canvas.gettags(item):
                if tag.startswith("code:"):
                    self.toggle(tag[5:])
                    return "break"
        return "break"

    # --- 그리기 ------------------------------------------------------------------
    def redraw(self):
        c, s = self.canvas, self.scale
        c.delete("all")
        pad = round(5 * s)
        x0, y0, x1, y1 = pad, pad, self.width - pad, self.height - pad
        line = max(1, round(s))
        c.create_rectangle(x0, y0, x1, y1, fill=theme.TURF_2, outline=theme.PITCH_LINE, width=line)
        cx, w, h = (x0 + x1) / 2, x1 - x0, y1 - y0
        c.create_rectangle(cx - w * 0.28, y1 - h * 0.15, cx + w * 0.28, y1, outline=theme.PITCH_LINE, width=line)
        c.create_rectangle(cx - w * 0.12, y1 - h * 0.06, cx + w * 0.12, y1, outline=theme.PITCH_LINE, width=line)
        r_arc = h * 0.11
        c.create_arc(cx - r_arc, y0 - r_arc, cx + r_arc, y0 + r_arc, start=180, extent=180,
                     style="arc", outline=theme.PITCH_LINE, width=line)
        rows = logic.formation_rows(self.formation)
        self.slots = []
        if not rows:
            c.create_text(cx, (y0 + y1) / 2, text="포메이션을 고르면\n자리가 나타납니다",
                          fill=theme.PITCH_LINE, font=self.app.fonts.spec("label"), justify="center")
            return
        radius = 14 * s
        margin = radius + 5 * s
        focused = self.canvas.focus_get() is self.canvas
        for i, row in enumerate(rows):
            y = y1 - margin - i * ((h - 2 * margin) / (len(rows) - 1))
            for j, code in enumerate(row):
                x = x0 + (j + 0.5) * (w / len(row))
                self.slots.append((code, x, y))
        for index, (code, x, y) in enumerate(self.slots):
            picked = code in self.selected
            ring = focused and index == self.cursor
            c.create_oval(x - radius, y - radius, x + radius, y + radius,
                          fill=theme.CARD_YELLOW if picked else theme.PITCH_LINE,
                          outline=theme.INK if (picked or ring) else theme.TURF,
                          width=max(2, round(2.5 * s)) if ring else line, tags=("slot", f"code:{code}"))
            c.create_text(x, y, text=code, fill=theme.INK if picked else theme.TURF,
                          font=(self.app.fonts.num, 8, "bold"), tags=("slot", f"code:{code}"))
