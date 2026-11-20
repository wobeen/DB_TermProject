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


def _show(root):
    root.deiconify()
    root.update()


def _type(root, auto, text, entry_var):
    """입력 칸에 글자를 넣은 것처럼 연관검색어 흐름을 돌린다 (150 ms 디바운스 포함)."""
    entry_var.set(text)
    auto.last_text = ""                                        # 새로 입력한 것처럼
    auto.on_key(type("Key", (), {"keysym": "x"})())
    _wait(root, lambda: auto.is_open(), timeout=5)


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


def test_name_suggestions_open_career_on_accept(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        auto = app.search.name_auto
        _type(root, auto, "guy", app.search.name)
        assert [i["player_id"] for i in auto.items] == [301, 302]
        assert auto.listbox.get(0) == "Career Guy  ST 공격수 · Alpha FC  2000"
        auto.on_down(None)                                     # 첫 줄 강조
        assert auto.index == 0
        auto.on_return(None)                                   # 선택하면 그 선수의 커리어가 바로 열린다
        _wait(root, lambda: app.career.card is not None and app.career.card["player_id"] == 301)
        assert not auto.is_open() and app.career.index is None
        # 고르지 않은 Enter 는 팝업만 닫고 일반 검색으로 넘어간다 (Esc 는 닫기만)
        app.show_search()
        _type(root, auto, "guy", app.search.name)
        assert auto.on_escape(None) == "break" and not auto.is_open()
        _type(root, auto, "guy", app.search.name)
        assert auto.on_return(None) is None and not auto.is_open()
        # 한 글자는 제안하지 않는다
        app.search.name.set("g")
        auto.last_text = ""
        auto.on_key(type("Key", (), {"keysym": "g"})())
        root.update()
        assert not auto.is_open()
    finally:
        _dispose(app)


def test_stale_suggestions_are_dropped(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        auto = app.search.name_auto
        app.search.name.set("guy")
        auto.deliver(auto.token + 5, "guy", [{"player_id": 1}])          # 토큰이 다른 오래된 결과
        assert not auto.is_open()
        auto.token += 1
        auto.deliver(auto.token, "something else", [{"player_id": 1}])   # 입력이 이미 바뀐 결과
        assert not auto.is_open()
    finally:
        _dispose(app)


def test_nationality_autocomplete_and_invalid_value_blocks_search(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        s = app.search
        _type(root, s.nat_auto, "kor", s.nat)
        assert s.nat_auto.items == ["Korea, South"]
        s.nat_auto.on_down(None)
        s.nat_auto.on_tab(None)                                # Tab 은 고른 항목을 받아들인다
        assert s.nat.get() == "Korea, South"
        s.nat.set("sds")                                       # 목록에 없는 값
        s.search()
        root.update()
        assert s.nat_error.winfo_manager() == "pack" and s.nat_error.cget("text") == "국적 목록에서 골라 주세요"
        assert not s.tree.get_children() and not s.pending       # 검색하지 않았다
        s.nat.set("한국")                                        # 한글 별칭은 정식 이름으로 풀린다
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 2)
        assert s.nat.get() == "Korea, South" and s.nat_error.winfo_manager() == ""
    finally:
        _dispose(app)


def test_club_suggestions_fill_field(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        s = app.search
        _type(root, s.club_auto, "gam", s.club)
        assert s.club_auto.items[0]["name"] == "Gamma SC"
        s.club_auto.accept(0)
        assert s.club.get() == "Gamma SC"
        s.search()                                              # 구단 칸은 일반 부분 일치 검색으로 이어진다
        _wait(root, lambda: len(s.tree.get_children()) == 2)
    finally:
        _dispose(app)


def test_formation_picker_filters_by_position(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        s = app.search
        s.set_formation("4-3-3")
        assert len(s.picker.slots) == 11
        s.picker.toggle("AMR")
        s.picker.toggle("ST")
        assert s.picker.codes() == ["AMR", "ST"] and s.picked_label.cget("text") == "선택한 포지션: AMR, ST"
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 2)
        codes = {s.tree.item(i, "values")[1].split()[0] for i in s.tree.get_children()}
        assert codes == {"AMR", "ST"}
        s.picker.toggle("ST")                                  # 선택 해제
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 1)
        assert s.tree.item(s.tree.get_children()[0], "values")[1] == "AMR 공격수"
        # 캔버스의 점을 직접 눌러도 같은 코드가 토글된다 (CB 는 두 점이지만 한 번만 선택)
        s.picker.clear()
        x, y = next((x, y) for code, x, y in s.picker.slots if code == "AMR")
        s.picker.on_click(type("Click", (), {"x": int(x), "y": int(y)})())
        assert s.picker.codes() == ["AMR"]
        s.picker.on_click(type("Click", (), {"x": int(x), "y": int(y)})())
        assert s.picker.codes() == []
        cb = [(x, y) for code, x, y in s.picker.slots if code == "CB"]
        assert len(cb) == 2
        s.picker.on_click(type("Click", (), {"x": int(cb[1][0]), "y": int(cb[1][1])})())
        assert s.picker.codes() == ["CB"]
        s.set_formation("")                                    # 포메이션을 끄면 선택이 사라지고 필터도 없다
        assert s.picker.codes() == [] and s.picker.slots == []
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 3)
    finally:
        _dispose(app)
