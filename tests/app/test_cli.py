import os
import subprocess
import sys
from pathlib import Path

from scouting.cli import main as cli_main
from scouting.cli.ui import display_width, table
from scouting.db import connect
from scouting.services import users

ROOT = Path(__file__).resolve().parents[2]


def run_cli(db, lines, *extra):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    p = subprocess.run(
        [sys.executable, "-m", "scouting", "--db", str(db), *extra],
        input="\n".join(lines) + "\n", capture_output=True, text=True, encoding="utf-8",
        cwd=ROOT, env=env, timeout=120,
    )
    return p


def inject(db, lines):
    """프로세스 안에서 입력 주입. (종료코드, 출력 문자열)"""
    it = iter(lines)
    out: list[str] = []

    def fake_input(prompt=""):
        out.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    code = cli_main.main(["--db", str(db)], input_fn=fake_input, print_fn=lambda *a: out.append(" ".join(map(str, a))))
    return code, "\n".join(out)


def test_cli_invalid_input_sequence_reaches_exit(db_path):
    path, _ = db_path
    lines = [
        "abc", "99", "", "-1", "1.5",          # 메인 메뉴 잘못된 입력
        "2", "ab", "",                   # 너무 짧은 사용자명
        "2", "newuser", "12", "",                  # 너무 짧은 비밀번호
        "2", "newuser", "pw1234",              # 정상 가입
        "2", "newuser", "",                    # 중복 가입(비밀번호 전에 거부)
        "1", "newuser", "wrongpw",             # 로그인 실패
        "1", "newuser", "pw1234",              # 로그인
        "zz", "14", "9", "13", "99",            # 스카우트에게 없는 메뉴 / 잘못된 번호
        "1", "Cand", "xx", "FW", "", "", "",   # 검색: 잘못된 포지션 → 메시지 후 복귀
        "1", "Cand", "", "abc", "19", "",      # 검색: 나이에 숫자 아님 → 다시 묻기
        "3", "nosuchplayer", "", "",           # 유사 선수: 검색 결과 없음 → 취소
        "7", "3", "101", "abc", "9", "4", "좋은 수비수",       # 노트 작성
        "4", "x", "1", "", "더 좋은 수비수",                   # 노트 수정
        "5", "999",                            # 없는 노트 삭제
        "5", "1", "y",                       # 삭제(확인)
        "5", "1",                              # 이미 삭제됨 → 권한 없음 또는 없음
        "0",                                   # 노트 메뉴 뒤로
        "6", "2", "424242", "", "2", "101", "x" * 201,   # 없는 선수 / 메모 200자 초과
        "0", "0", "0",                         # 워치 뒤로, 로그아웃, 종료
    ]
    p = run_cli(path, lines)
    assert p.returncode == 0, p.stderr
    assert "Traceback" not in p.stdout and "Traceback" not in p.stderr
    assert "종료합니다" in p.stdout
    for msg in ("숫자를 입력해 주세요", "잘못된 선택입니다", "이미 사용 중인 사용자명", "올바르지 않습니다",
                "노트 #1 를 저장했습니다", "수정했습니다", "권한 없음 또는 없음", "허용 범위를 벗어났습니다"):
        assert msg in p.stdout, msg
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM scouting_note").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0
    conn.close()


def test_cli_scout_cannot_use_admin_menu(db_path):
    path, _ = db_path
    code, out = inject(path, ["2", "scout1", "pw1234", "1", "scout1", "pw1234", "9", "10", "13", "0", "0"])
    assert code == 0 and "잘못된 선택입니다" in out and "데이터 현황" not in out


def test_cli_eof_midway_is_clean(db_path):
    path, _ = db_path
    for cut in range(0, 6):
        lines = ["2", "eofuser", "pw1234", "1", "eofuser", "pw1234"][:cut]
        p = run_cli(path, lines)
        assert p.returncode == 0 and "Traceback" not in p.stderr


def test_cli_integrity_error_message_and_unexpected_error(db_path, monkeypatch):
    path, _ = db_path
    # 워치리스트 중복(IntegrityError) → 한국어 메시지
    code, out = inject(path, ["2", "user1", "pw1234", "1", "user1", "pw1234",
                              "6", "2", "101", "", "2", "101", "", "0", "0", "0"])
    assert code == 0 and "이미 워치리스트에 있는 선수입니다" in out
    # 서비스에서 예상 못한 예외가 나도 traceback 없이 메뉴로 복귀
    from scouting.services import players

    monkeypatch.setattr(players, "search_players", lambda *a, **k: 1 / 0)
    code, out = inject(path, ["1", "user1", "pw1234", "1", "", "", "", "", "0", "0"])
    assert code == 0 and "예상치 못한 오류" in out and "종료합니다" in out


def test_cli_admin_flow_and_create_admin(db_path):
    path, ids = db_path
    p = run_cli(path, [], "create-admin", "boss", "--password", "admin1234")
    assert p.returncode == 0 and "생성 완료" in p.stdout
    p = run_cli(path, [], "create-admin", "boss", "--password", "admin1234")
    assert p.returncode == 1 and "이미" in p.stdout and "Traceback" not in p.stderr
    conn = connect(path)
    assert users.authenticate(conn, "boss", "admin1234").role == "admin"
    conn.close()
    lines = [
        "1", "boss", "admin1234",
        "4", "1", "1", "2", "2", "y",                # 추천 실행: 스냅샷1, 정의1, DF, method 2(market_value)
        "5", "1", "",                           # 내 기록 상세
        "9",                                    # 데이터 현황
        "12", "1", "2",                         # 백테스트: run 1 → outcome current(2번째)
        "13", "999", "1",                       # 존재하지 않는 사용자 역할 변경
        "11", "1", "0",                         # 정의 조회
        "10", "99", "0",                         # 재계산: 잘못된 번호 후 취소
        "0", "0",
    ]
    p = run_cli(path, lines)
    assert p.returncode == 0 and "Traceback" not in p.stdout + p.stderr
    for msg in ("추천 완료: run #1", "precision", "스냅샷", "존재하지 않는 사용자"):
        assert msg in p.stdout, msg


def test_table_is_fixed_width_with_korean():
    t = table(["ID", "이름", "값"], [[1, "홍길동", 1.5], [22, "Cand", None]])
    widths = {display_width(line) for line in t.splitlines()}
    assert len(widths) == 1
