"""Capture three deterministic GUI report figures without changing the source DB."""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab

from scouting import db
from scouting.gui.dpi import enable_dpi_awareness

enable_dpi_awareness()

from scouting.gui.app import ScoutingApp
from scouting.services import users


def wait(root, predicate, timeout=180):
    until = time.time() + timeout
    while time.time() < until:
        root.update()
        if predicate(): return
        time.sleep(.03)
    raise TimeoutError("GUI 작업 제한 시간을 초과했습니다")


def capture(root, path):
    root.attributes("-topmost", True); root.lift(); root.focus_force()
    root.update_idletasks(); root.update(); time.sleep(.8); root.update_idletasks()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    image = ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height()))
    path.parent.mkdir(parents=True, exist_ok=True); image.save(path)
    print(f"{path}: {image.size[0]}x{image.size[1]}")


def main():
    source = db.db_path(); out = ROOT / "report" / "figures"
    if not source.is_file(): raise SystemExit(f"DB가 없습니다: {source}")
    with tempfile.TemporaryDirectory(prefix="scouting-gui-") as temp:
        copied = Path(temp) / "scouting.sqlite"; shutil.copy2(source, copied)
        conn = db.connect(copied)
        username = f"gui_capture_{int(time.time())}"
        users.register(conn, username, "capture-pass"); conn.close()
        root = tk.Tk(); app = ScoutingApp(root, copied, show_login=False); app.login_credentials(username, "capture-pass")
        root.deiconify(); root.attributes("-topmost", True); root.lift(); root.focus_force(); root.update()

        app.notebook.select(app.profile); app.profile.snap.set("current"); app.profile.load(91845)
        wait(root, lambda: app.profile.card is not None and "완료" in app.status_var.get())
        capture(root, out / "gui_profile.png")

        app.notebook.select(app.recommend); app.recommend.vars["snapshot"].set("current")
        app.recommend.vars["definition"].set("peak_value_50m"); app.recommend.vars["pos_group"].set("FW")
        app.recommend.vars["method"].set("similarity"); app.recommend.run()
        wait(root, lambda: bool(app.recommend.tree.get_children()) and "run #" in app.status_var.get(), 300)
        capture(root, out / "gui_recommend.png")

        app.notebook.select(app.similar); app.similar.player.set("91845")
        app.similar.snapshot.set("bt2018"); app.similar.definition.set("peak_value_50m")
        app.similar.season.set(""); app.similar.run()
        wait(root, lambda: bool(app.similar.tree.get_children()) and "완료" in app.status_var.get(), 180)
        capture(root, out / "gui_similar.png")

        app.notebook.select(app.breakout); app.breakout.vars["snapshot"].set("current")
        app.breakout.vars["definition"].set("peak_value_50m"); app.breakout.vars["pos"].set("FW")
        app.breakout.vars["metric"].set("minutes_share"); app.breakout.vars["mode"].set("some"); app.breakout.run()
        wait(root, lambda: "완료" in app.status_var.get(), 180)
        capture(root, out / "gui_breakout.png")
        app.close()


if __name__ == "__main__": main()
