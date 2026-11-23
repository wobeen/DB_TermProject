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


def _motion(canvas, ax, x, y):
    """데이터 좌표 (x, y) 위에서 마우스가 움직인 것처럼 matplotlib 이벤트를 만든다."""
    from matplotlib.backend_bases import MouseEvent

    px, py = ax.transData.transform((x, y))
    return MouseEvent("motion_notify_event", canvas, px, py)


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


def test_league_club_pick_and_tenure_column(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        s = app.search
        assert str(s.club_box.cget("state")) == "disabled"                  # 리그를 고르기 전에는 비활성
        assert "재직 기간" not in [s.tree.heading(c, "text") for c in s.tree.cget("displaycolumns")]
        s.league.set("Premier League (England)")
        s.on_league()
        assert str(s.club_box.cget("state")) == "readonly"
        assert list(s.club_box.cget("values")) == ["리그 전체", "Alpha FC", "Beta United", "Gamma SC"]
        s.club_pick.set("Alpha FC")
        s.refresh_club_note()
        assert s.club_note.cget("text") == "적용: Alpha FC (구단 선택)"
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 2)
        shown = [s.tree.heading(c, "text") for c in s.tree.cget("displaycolumns")]
        assert shown[shown.index("현재 구단") + 1] == "재직 기간"                    # 현재 구단 바로 뒤
        tenures = {int(i): s.tree.set(i, "tenure") for i in s.tree.get_children()}
        assert tenures == {301: "2022-07 ~ 2024-07", 302: "2023-09 ~ 2023-09"}       # 2013/14 이후 출전 기반은 표시 없음
        s.club_pick.set("리그 전체")                                           # 리그 전체 -> 그 리그 구단 전부
        s.refresh_club_note()
        assert s.club_note.cget("text") == "적용: Premier League (England) 전체 구단"
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 3)
        assert all(s.tree.set(i, "tenure") not in ("", "-") for i in s.tree.get_children())
        s.club.set("Gamma")                                                    # 이름 일부가 리그 전체보다 우선
        s.refresh_club_note()
        assert "이름에 'Gamma'" in s.club_note.cget("text")
        s.club_pick.set("Alpha FC")                                            # 직접 고른 구단이 이름 일부보다 우선
        s.refresh_club_note()
        assert s.club_note.cget("text") == "적용: Alpha FC (구단 선택)"
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 2)
        s.reset()                                                              # 초기화하면 구단 조건과 열이 사라진다
        assert str(s.club_box.cget("state")) == "disabled" and s.league.get() == "전체"
        s.search()
        _wait(root, lambda: len(s.tree.get_children()) == 3)
        assert "tenure" not in s.tree.cget("displaycolumns")
        s.club.set("nosuchclub")
        s.search()
        _wait(root, lambda: s.total == 0 and not s.pending)
    finally:
        _dispose(app)


def test_value_hover_tooltip_and_block_tooltip(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        c = app.career
        app.open_career(301)
        _wait(root, lambda: c.card is not None)
        root.update()
        num = lambda day: __import__("matplotlib.dates", fromlist=["date2num"]).date2num(
            __import__("datetime").datetime.fromisoformat(day))
        c.last_motion = 0
        c.on_motion(_motion(c.strip_canvas, c.value_ax, num("2025-04-20"), 12.0))     # 2025-05-01 점에 가장 가깝다
        text = c.hover_tip.get_text()
        assert c.hover_tip.get_visible() and c.hover_marker.get_visible() and c.hover_line.get_visible()
        assert text.split("\n") == ["2025-05-01 (2024/25)", "€12.0M", "Alpha FC"]
        assert tuple(c.hover_marker.get_xdata()) == (num("2025-05-01"),)
        c.last_motion = 0
        c.on_motion(_motion(c.strip_canvas, c.value_ax, num("2023-02-01"), 3.0))      # 2023-01-01 점
        assert c.hover_tip.get_text().split("\n")[:2] == ["2023-01-01 (2022/23)", "€3.0M"]
        c.last_motion = 0
        c.on_motion(_motion(c.strip_canvas, c.strip_ax, num("2023-06-01"), 0.5))      # 띠 블록 위
        assert c.strip_tip.get_visible() and not c.hover_tip.get_visible()
        assert c.strip_tip.get_text() == "Alpha FC / 2022-07 ~ 2024-07 (2년)"
        c.last_motion = 0
        c.on_motion(_motion(c.strip_canvas, c.strip_ax, num("2024-12-01"), 0.5))
        assert c.strip_tip.get_text() == "Beta United / 2024-07 ~ 현재 (11개월)"
        c.last_motion = 0
        c.on_motion(type("Leave", (), {"inaxes": None, "xdata": None})())            # 축 밖으로 나가면 모두 숨김
        assert not any(a.get_visible() for a in (c.hover_marker, c.hover_line, c.hover_tip, c.strip_tip))
        c.on_motion(_motion(c.strip_canvas, c.value_ax, num("2025-04-20"), 12.0))     # 30 fps 제한: 바로 다음 이벤트는 무시
        assert not c.hover_tip.get_visible()
    finally:
        _dispose(app)


def test_season_link_between_chart_and_table(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        c = app.career
        app.open_career(301)
        _wait(root, lambda: c.card is not None)
        root.update()
        num = lambda day: __import__("matplotlib.dates", fromlist=["date2num"]).date2num(
            __import__("datetime").datetime.fromisoformat(day))
        tree = c.season_tree
        parents = tree.get_children()
        assert [c.season_names[p] for p in parents] == ["2023/24", "2024/25", "2025/26"]
        # 차트 -> 표: 2025-05-01 점(2024/25 시즌)에 hover 하면 그 시즌 행만 표시되고 선택은 그대로
        assert not tree.selection()
        c.last_motion = 0
        c.on_motion(_motion(c.strip_canvas, c.value_ax, num("2025-04-20"), 12.0))
        assert "hl" in tree.item(parents[1], "tags") and tree.item(parents[1], "text").startswith("▌")
        assert "hl" not in tree.item(parents[0], "tags") and "hl" not in tree.item(parents[2], "tags")
        assert not tree.selection()                                    # 선택은 건드리지 않는다
        c.last_motion = 0
        c.on_motion(_motion(c.strip_canvas, c.strip_ax, num("2023-10-01"), 0.5))      # 띠 위: 날짜의 시즌 2023/24
        assert "hl" in tree.item(parents[0], "tags") and "hl" not in tree.item(parents[1], "tags")
        c.last_motion = 0
        c.on_motion(type("Leave", (), {"inaxes": None, "xdata": None})())            # 나가면 표시 해제
        assert not any("hl" in tree.item(p, "tags") for p in parents)
        assert not tree.item(parents[0], "text").startswith("▌")
        # 표 -> 차트: 행을 선택하면 그 시즌 띠(2024/25)와 띠 윤곽이 생기고, 선택을 해제하면 사라진다
        assert not c.season_band.get_visible()
        tree.selection_set(parents[1])
        root.update()
        assert c.season_band.get_visible() and c.season_outline.get_visible()
        assert c.season_band.get_x() == num("2024-07-01") and c.season_band.get_width() == num("2025-07-01") - num("2024-07-01")
        tree.selection_remove(parents[1])
        root.update()
        assert not c.season_band.get_visible() and not c.season_outline.get_visible()
        c.set_table_hover("2023/24")                                     # 행 위에 마우스만 올려도 띠
        assert c.season_band.get_visible() and c.season_band.get_x() == num("2023-07-01")
        c.set_table_hover(None)
        assert not c.season_band.get_visible()
    finally:
        _dispose(app)


def test_strip_is_drawn_without_gaps_and_axis_has_season_labels(career_path, tk_root):
    root = tk_root
    _show(root)
    app = ScoutingApp(root, career_path)
    try:
        c = app.career
        app.open_career(301)
        _wait(root, lambda: c.card is not None)
        root.update()
        bars = [coll for coll in c.strip_ax.collections if coll.get_facecolor().shape[0] == 1
                and coll.get_paths() and len(coll.get_paths()[0].vertices) >= 4]
        spans = sorted((p.get_paths()[0].vertices[:, 0].min(), p.get_paths()[0].vertices[:, 0].max())
                       for p in bars if p.get_linewidth().size and p.get_linewidth()[0] == 0)
        assert spans, "블록이 그려지지 않았다"
        for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
            assert a1 == b0                                           # 그려진 블록도 서로 맞닿는다
        # 가장자리 여백(흰 테두리)이 없다
        assert all(p.get_linewidth()[0] == 0 for p in bars if p.get_linewidth().size)
        labels = [t.get_text() for t in c.value_ax.get_xticklabels()]
        assert labels and all("/" in text and len(text) == 5 for text in labels)          # '24/25' 꼴 시즌 라벨
    finally:
        _dispose(app)
