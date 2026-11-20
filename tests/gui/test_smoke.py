import time
import tkinter as tk

import pytest

from scouting.gui.app import ScoutingApp


@pytest.fixture(scope="module")
def tk_root():
    """모듈 하나에 Tk 하나만 만든다 (같은 프로세스에서 Tk 를 거듭 만들고 없애면 가끔 tcl_findLibrary 오류가 난다)."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk 디스플레이를 초기화할 수 없음: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def _dispose(app):
    """앱이 만든 위젯과 DB 연결만 정리하고 root 는 남긴다."""
    app.conn.close()
    for child in app.root.winfo_children():
        child.destroy()


def _wait(root, predicate, timeout=10):
    until = time.time() + timeout
    while time.time() < until and not predicate():
        root.update()
        time.sleep(.01)
    assert predicate()


def test_search_open_career_and_back(career_path, tk_root):
    root = tk_root
    app = ScoutingApp(root, career_path)
    try:
        assert app.cutoff["game"] == "2025-06-01"
        app.search.nat.set("Korea, South")
        app.search.search()
        _wait(root, lambda: len(app.search.tree.get_children()) == 2)
        assert "결과 2명" in app.search.count.cget("text")
        app.search.tree.selection_set("301")
        app.search.open_selected()
        _wait(root, lambda: app.career.card is not None)
        assert app.career.card["name"] == "Career Guy" and app.career.index == 0
        assert len(app.career.transfer_tree.get_children()) == 4
        # 시즌 표는 시즌·구단별 부모 행 한 줄씩(기본 접힘), 자식이 대회별 행
        tree = app.career.season_tree
        parents = tree.get_children()
        assert [(tree.item(p, "text"), tree.set(p, "club")) for p in parents] == [
            ("＋ 2023/24", "Alpha FC"), ("＋ 2024/25", "Beta United"), ("＋ 2025/26", "Alpha FC")]
        assert not any(tree.item(p, "open") for p in parents)
        assert len(tree.get_children(parents[0])) == 2
        app.career.toggle_item(parents[0])                       # 한 시즌만 펼치기
        assert tree.item(parents[0], "open") and tree.item(parents[0], "text") == "－ 2023/24"
        assert not tree.item(parents[1], "open")
        app.career.toggle_all()
        assert all(tree.item(p, "open") for p in tree.get_children())
        assert all(tree.item(p, "text").startswith("－ ") for p in tree.get_children())
        app.career.seg_buttons["league"].invoke()               # 두 칸 토글
        assert str(app.career.seg_buttons["league"].cget("style")) == "SegOn.TButton"
        assert str(app.career.seg_buttons["all"].cget("style")) == "SegOff.TButton"
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
        _dispose(app)


def test_next_player_crosses_page_boundary(career_path, tk_root):
    from scouting.db import connect

    conn = connect(career_path)
    for i in range(22):     # 301, 303 + 22 = 24명, 이름순(가치 없음)으로 정렬되며 301 은 가치가 있어 맨 앞
        conn.execute("INSERT INTO player (player_id, name, date_of_birth, position, country_of_citizenship) "
                     "VALUES (?,?,?,?,?)", (400 + i, f"Zed {i:02d}", "2001-01-01", "Attack", "Korea, South"))
    conn.commit()
    conn.close()
    root = tk_root
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
        _dispose(app)
