"""Capture the two GUI report figures (search, career) from a DB copy, DPI-aware."""

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


def wait(root, predicate, timeout=180):
    until = time.time() + timeout
    while time.time() < until:
        root.update()
        if predicate():
            return
        time.sleep(.03)
    raise TimeoutError("GUI 작업 제한 시간을 초과했습니다")


def capture(root, path):
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    root.update_idletasks()
    root.update()
    time.sleep(.8)
    root.update_idletasks()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    image = ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height()))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"{path}: {image.size[0]}x{image.size[1]}")


def main():
    source = db.db_path()
    out = ROOT / "report" / "figures"
    if not source.is_file():
        raise SystemExit(f"DB가 없습니다: {source}")
    with tempfile.TemporaryDirectory(prefix="scouting-gui-") as temp:
        copied = Path(temp) / "scouting.sqlite"
        shutil.copy2(source, copied)
        root = tk.Tk()
        app = ScoutingApp(root, copied)
        root.geometry("+0+0")   # 화면 밖으로 밀려 아래쪽이 검게 캡처되는 것을 막는다
        root.deiconify()
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        root.update()

        app.search.nat.set("Korea, South")
        app.search.pos.set("공격수")
        app.search.search()
        wait(root, lambda: bool(app.search.tree.get_children()) and "완료" in app.status_var.get())
        capture(root, out / "gui_search.png")

        app.open_career(91845)
        wait(root, lambda: app.career.card is not None and "완료" in app.status_var.get())
        capture(root, out / "gui_career.png")

        # 라벨 겹침 점검용 최악 사례: 유소년·임대 이동이 많은 Jan Oblak (저장소에 커밋하지 않는다)
        app.show_search()
        app.search.reset()
        app.search.name.set("Oblak")
        app.search.search()
        wait(root, lambda: bool(app.search.tree.get_children()) and "완료" in app.status_var.get())
        app.search.select_row(0)
        app.search.open_selected()
        wait(root, lambda: app.career.card is not None and "Oblak" in app.career.card["name"])
        app.career.toggle_all()
        capture(root, ROOT / "data" / "tasks" / "gui_oblak.png")
        app.close()


if __name__ == "__main__":
    main()
