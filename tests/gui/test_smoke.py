import time
import tkinter as tk

import pytest

from scouting.gui.app import ScoutingApp
from scouting.services import users
from tests.app.synth import build_main, new_db


def _root():
    try:
        root = tk.Tk(); root.withdraw(); return root
    except tk.TclError:
        pytest.skip("Tk 디스플레이를 초기화할 수 없음")


def test_build_login_tabs_search_profile(tmp_path):
    path = tmp_path / "gui.sqlite"; conn = new_db(path); build_main(conn); users.register(conn,"tester","pass"); conn.close()
    root = _root(); app = ScoutingApp(root,path,show_login=False); assert app.login_credentials("tester","pass")
    assert app.notebook.index("end") == 8
    for i in range(8): app.notebook.select(i); root.update()
    app.search.name.set("Cand One"); app.search.search()
    deadline=time.time()+5
    while time.time()<deadline and not app.search.tree.get_children(): root.update(); time.sleep(.01)
    assert app.search.tree.get_children()
    app.profile.load(101)
    deadline=time.time()+5
    while time.time()<deadline and app.profile.card is None: root.update(); time.sleep(.01)
    assert app.profile.card["name"] == "Cand One"
    app.close()
