import time
import tkinter as tk

import pytest

from scouting.gui.app import ScoutingApp


def _root():
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError:
        pytest.skip("Tk 디스플레이를 초기화할 수 없음")


def _wait(root, predicate, timeout=10):
    until = time.time() + timeout
    while time.time() < until and not predicate():
        root.update()
        time.sleep(.01)
    assert predicate()


def test_search_open_career_and_back(career_path):
    root = _root()
    app = ScoutingApp(root, career_path)
    try:
        assert app.cutoff["game"] == "2025-06-01"
        app.search.nat.set("Korea, South")
        app.search.search()
        _wait(root, lambda: len(app.search.tree.get_children()) == 2)
        assert "총 2명" in app.search.count.cget("text")
        app.search.tree.selection_set("301")
        app.search.open_selected()
        _wait(root, lambda: app.career.card is not None)
        assert app.career.card["name"] == "Career Guy"
        assert len(app.career.transfer_tree.get_children()) == 4
        all_rows = len(app.career.season_tree.get_children())
        app.career.scope.set("league")
        app.career.render_seasons()
        assert len(app.career.season_tree.get_children()) < all_rows
        # 검색으로 돌아가도 결과가 남고, 두 번째 선수도 열 수 있다
        app.show_search()
        assert len(app.search.tree.get_children()) == 2
        app.search.tree.selection_set("303")
        app.search.open_selected()
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == 303)
        assert app.history == [301, 303] and app.pos == 1
        app.step(-1)
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == 301)
        assert app.pos == 0
    finally:
        app.close()
