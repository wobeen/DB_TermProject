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
        assert app.career.card["name"] == "Career Guy" and app.career.index == 0
        assert len(app.career.transfer_tree.get_children()) == 4
        # 시즌 표는 시즌·구단별 부모 행 한 줄씩(기본 접힘), 자식이 대회별 행
        tree = app.career.season_tree
        parents = tree.get_children()
        assert [tree.item(p, "text") for p in parents] == [
            "2023/24 · Alpha FC", "2024/25 · Beta United", "2025/26 · Alpha FC"]
        assert not any(tree.item(p, "open") for p in parents)
        assert len(tree.get_children(parents[0])) == 2
        app.career.toggle_all()
        assert all(tree.item(p, "open") for p in tree.get_children())
        app.career.scope.set("league")
        app.career.render_seasons()
        assert len(tree.get_children()) == 2
        # 검색으로 돌아가도 결과가 남고, 다음 선수는 검색 결과의 다음 행이다
        app.show_search()
        assert len(app.search.tree.get_children()) == 2
        app.career.step(1)
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == 303)
        assert app.career.index == 1 and app.career.pos_label.cget("text") == "2 / 2"
        assert str(app.career.next_btn.cget("state")) == "disabled"
        app.career.step(-1)
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == 301)
        assert str(app.career.prev_btn.cget("state")) == "disabled"
        # 검색 없이 연 커리어에는 이전/다음 선수 버튼이 없다
        app.open_career(302)
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == 302)
        assert not app.career.prev_btn.winfo_ismapped() and app.career.index is None
    finally:
        app.close()


def test_next_player_crosses_page_boundary(career_path):
    from scouting.db import connect

    conn = connect(career_path)
    for i in range(22):     # 301, 303 + 22 = 24명, 이름순(가치 없음)으로 정렬되며 301 은 가치가 있어 맨 앞
        conn.execute("INSERT INTO player (player_id, name, date_of_birth, position, country_of_citizenship) "
                     "VALUES (?,?,?,?,?)", (400 + i, f"Zed {i:02d}", "2001-01-01", "Attack", "Korea, South"))
    conn.commit()
    conn.close()
    root = _root()
    app = ScoutingApp(root, career_path)
    try:
        app.search.nat.set("Korea, South")
        app.search.search()
        _wait(root, lambda: len(app.search.tree.get_children()) == 20)
        assert app.search.total == 24
        app.search.select_row(19)                               # 1페이지의 20번째
        app.search.open_selected()
        twentieth = int(app.search.tree.selection()[0])
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == twentieth)
        assert app.career.index == 19 and app.career.pos_label.cget("text") == "20 / 24"
        app.career.step(1)                                      # 2페이지 첫 행 = 21번째
        _wait(root, lambda: app.career.index == 20 and app.career.card is not None
              and app.career.card["player_id"] != twentieth)
        assert app.search.page == 1
        assert app.career.card["player_id"] == int(app.search.tree.get_children()[0])
        assert app.career.pos_label.cget("text") == "21 / 24"
        app.career.step(-1)                                     # 다시 1페이지 20번째
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == twentieth)
        assert app.search.page == 0 and app.career.index == 19
    finally:
        app.close()
