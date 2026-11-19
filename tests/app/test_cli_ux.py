"""CLI UX 회귀 테스트 (follow-up 항목 1~8). 입력 주입 방식."""

from datetime import timedelta, timezone

import pytest

import synth
from scouting.cli import main as cli_main
from scouting.cli import ui
from scouting.db import connect
from scouting.services import notes, users, watchlist
from test_cli import inject


def login(name="scout1"):
    return ["1", name, "pw1234"]


@pytest.fixture()
def two_users(db_path):
    path, ids = db_path
    conn = connect(path)
    a = users.register(conn, "scout1", "pw1234")
    b = users.register(conn, "scout2", "pw1234")
    conn.close()
    return path, ids, a, b


# 1. 회원가입: 사용자명 검사를 비밀번호 앞에서
def test_signup_validates_username_before_password(two_users):
    path, *_ = two_users
    code, out = inject(path, ["2", "ab", "scout1", "", "0"])
    assert code == 0
    assert "사용자명은 3~32자여야 합니다." in out and "이미 사용 중인 사용자명입니다." in out
    assert "비밀번호(4자" not in out                      # 비밀번호는 한 번도 묻지 않음
    assert out.count("사용자명(3~32자") == 3              # 틀릴 때마다 사용자명을 다시 묻는다
    code, out = inject(path, ["2", "newbie", "12", "pw1234", "0"])  # 짧은 비밀번호도 다시 묻기
    assert "비밀번호는 4자 이상" in out and "회원가입 완료" in out
    conn = connect(path)
    assert users.authenticate(conn, "newbie", "pw1234")
    conn.close()


# 2. 검색: 잘못된 하위 입력은 같은 항목을 다시 묻는다
def test_search_reprompts_each_field(two_users):
    path, *_ = two_users
    seq = [*login(), "1", "Cand", "XX", "fw", "abc", "5", "19", "ZZZ9", "gb1", "0", "0"]
    code, out = inject(path, seq)
    assert code == 0
    assert out.count("포지션군 GK/DF/MF/FW") == 2 and "포지션군은 GK/DF/MF/FW 중 하나여야 합니다." in out
    assert "숫자를 입력해 주세요." in out and "범위(10~60)" in out
    assert out.count("리그 ID 예:") == 2 and "competition 테이블에 없는 리그 ID" in out
    assert "메인 메뉴 (scout1)" in out.split("competition 테이블에 없는 리그 ID")[1]
    assert "=== 스카우팅 DB ===" in out  # 로그아웃 후 정상 종료까지 도달


# 3. 소유권/존재 확인이 추가 입력보다 먼저
def test_owner_check_happens_before_further_prompts(two_users):
    path, ids, a, b = two_users
    conn = connect(path)
    nid = notes.create_note(conn, a, 101, 4, "A의 노트")
    watchlist.add_to_watchlist(conn, a, 101, "A 메모")
    conn.close()
    seq = [*login("scout2"),
           "7", "4", str(nid), "5", str(nid), "0",
           "6", "3", "101", "4", "101", "0", "0", "0"]
    code, out = inject(path, seq)
    assert code == 0
    assert out.count("권한 없음 또는 없음") == 4
    for later_prompt in ("새 평점", "새 내용", "새 메모", "삭제할까요"):
        assert later_prompt not in out
    conn = connect(path)
    assert notes.list_notes_for_player(conn, a, 101)[0]["body"] == "A의 노트"
    assert watchlist.list_watchlist(conn, a)[0]["memo"] == "A 메모"
    conn.close()


# 4. 삭제는 y/n 확인
def test_delete_requires_confirmation(two_users):
    path, ids, a, b = two_users
    conn = connect(path)
    nid = notes.create_note(conn, a, 101, 4, "지울 노트")
    watchlist.add_to_watchlist(conn, a, 101)
    conn.close()
    seq = [*login(), "7", "5", str(nid), "maybe", "n", "0", "6", "4", "101", "n", "0"]
    code, out = inject(path, seq + ["0", "0"])
    assert "y 또는 n 으로 답해 주세요." in out and "삭제했습니다." not in out
    conn = connect(path)
    assert notes.note_owned(conn, a, nid) and watchlist.is_watched(conn, a, 101)
    conn.close()
    seq = [*login(), "7", "5", str(nid), "y", "0", "6", "4", "101", "y", "0", "0", "0"]
    code, out = inject(path, seq)
    assert out.count("삭제했습니다.") == 2
    conn = connect(path)
    assert not notes.note_owned(conn, a, nid) and not watchlist.is_watched(conn, a, 101)
    conn.close()


# 5. UTC 저장값을 로컬 시각으로 표시
def test_local_time_conversion(two_users, monkeypatch):
    kst = timezone(timedelta(hours=9))
    assert ui.local_time("2026-01-01 00:30:00", kst) == "2026-01-01 09:30:00"
    assert ui.local_time("2026-12-31 20:00:00", kst) == "2027-01-01 05:00:00"
    assert ui.local_time(None) == "-" and ui.local_time("이상한 값") == "이상한 값"
    path, ids, a, b = two_users
    conn = connect(path)
    conn.execute("INSERT INTO scouting_note (user_id, player_id, rating, body, created_at, updated_at) "
                 "VALUES (?,?,?,?,?,?)", (a, 101, 3, "시각 노트", "2026-01-01 00:30:00", "2026-01-01 00:30:00"))
    conn.close()
    monkeypatch.setattr(cli_main, "local_time", lambda s: ui.local_time(s, kst))
    code, out = inject(path, [*login(), "7", "1", "0", "0", "0"])
    assert "2026-01-01 09:30:00" in out and "2026-01-01 00:30:00" not in out
    conn = connect(path)  # 저장값은 UTC 그대로
    assert conn.execute("SELECT updated_at FROM scouting_note").fetchone()[0] == "2026-01-01 00:30:00"
    conn.close()


# 6. 0행 표는 빈 헤더 대신 안내
def test_empty_tables_show_hint(two_users):
    path, *_ = two_users
    seq = [*login(),
           "1", "zzzzzzzz", "", "", "",                 # 검색 0건
           "5",                                         # 추천 기록 없음
           "6", "1", "0",                               # 워치리스트 비어 있음
           "7", "1", "0",                               # 노트 없음
           "2", "101", "n", "1",                             # 프로필: 지표 없는 선수 → 백분위 0행
           "0", "0"]
    code, out = inject(path, seq)
    assert out.count("표시할 데이터가 없습니다.") >= 5
    assert "출전 시간이 지표 최소 출전 시간에 못 미치거나" in out
    assert "아직 실행한 추천이 없습니다" in out and "워치리스트가 비어 있습니다" in out
    assert "ID | 이름" not in out.split("조건을 줄여 보세요")[1].split("메인 메뉴")[0]


# 7. 추천 실행: 기본값 / 고급 설정
def test_recommend_default_and_advanced(two_users):
    path, *_ = two_users
    base = ["4", "1", "1", "2", "2"]  # bt2018, 정의1, DF, market_value
    code, out = inject(path, [*login(), *base, "y", "0", "0"])
    assert "추천 완료: run #1" in out
    seq = [*login(), *base, "n",
           "99", "abc", "19",     # max_age: 범위 밖, 숫자 아님 → 19
           "-5", "100",           # min_minutes: 범위 밖 → 100
           "0", "3",              # k
           "", "",                # top_n, pool_lag 기본값
           "", "0", "0"]          # seed 기본값, 로그아웃, 종료
    code, out = inject(path, seq)
    assert "범위(15~30)" in out and "숫자를 입력해 주세요." in out and "범위(1~200)" in out
    conn = connect(path)
    rows = conn.execute("SELECT max_age, min_minutes, k, top_n, pool_lag_seasons, seed FROM recommendation_run "
                        "ORDER BY run_id").fetchall()
    conn.close()
    assert tuple(rows[0]) == (21, 900, 25, 20, 3, 42)
    assert tuple(rows[1]) == (19, 100, 3, 20, 3, 42)


# 8. 추천 결과의 시장가치는 as_of 기준
def test_recommendation_value_column_is_as_of(two_users):
    path, *_ = two_users
    conn = connect(path)
    synth.add_val(conn, 102, "2020-01-01", 900_000_000)  # bt 스냅샷(2018-07-01) 이후의 미래 값
    conn.close()
    code, out = inject(path, [*login(), "4", "1", "1", "2", "2", "y", "0", "0"])
    assert "시장가치(as_of)" in out
    assert "€30.0M" in out and "€900.0M" not in out
