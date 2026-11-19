"""CLI 입출력 도우미: 고정폭(한글 전각 폭 반영) 표, 재질문 프롬프트."""

from __future__ import annotations

import getpass
import sys
import unicodedata
from datetime import datetime, timezone
from collections.abc import Callable, Sequence


INT_MAX = 2**63 - 1


class Quit(Exception):
    """입력 종료(EOF/Ctrl-C). 최상위에서 조용히 종료한다."""


def display_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def pad(s: str, width: int, right: bool = False) -> str:
    gap = max(0, width - display_width(s))
    return (" " * gap + s) if right else (s + " " * gap)


def fmt(v, digits: int = 3) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}" if abs(v) >= 10_000 else str(v)
    return str(v)


def eur(v) -> str:
    if v is None:
        return "-"
    return f"€{v / 1_000_000:.1f}M" if v >= 1_000_000 else f"€{v / 1_000:.0f}K"


def local_time(s: str | None, tz=None) -> str:
    """DB 의 UTC 'YYYY-MM-DD HH:MM:SS' 를 로컬 시각 문자열로 (저장 방식은 그대로). tz=None 이면 시스템 로컬."""
    if not s:
        return "-"
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return s
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


class R(str):
    """미리 서식을 정한 문자열을 표에서 오른쪽 정렬하기 위한 표식."""


def _is_id_col(header: str) -> bool:
    return "ID" in header or header in ("run", "노트", "순위", "시즌")


def table(headers: Sequence[str], rows: Sequence[Sequence], max_col: int = 40) -> str:
    cells = [
        [str(c) if _is_id_col(headers[i]) and isinstance(c, int) else fmt(c) for i, c in enumerate(r)]
        for r in rows
    ]
    nums = [
        all(isinstance(r[i], (int, float, R)) and not isinstance(r[i], bool) or r[i] is None for r in rows)
        and rows != []
        for i in range(len(headers))
    ]
    cells = [[_clip(c, max_col) for c in r] for r in cells]
    widths = [max([display_width(h)] + [display_width(r[i]) for r in cells]) for i, h in enumerate(headers)]
    line = "-+-".join("-" * w for w in widths)
    out = [" | ".join(pad(h, widths[i], nums[i]) for i, h in enumerate(headers)), line]
    for r in cells:
        out.append(" | ".join(pad(r[i], widths[i], nums[i]) for i in range(len(headers))))
    return "\n".join(out)


def _clip(s: str, width: int) -> str:
    if display_width(s) <= width:
        return s
    out = ""
    for ch in s:
        if display_width(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


class IO:
    """input_fn 주입이 가능한 입출력. 잘못된 입력은 메시지를 내고 다시 묻는다."""

    def __init__(self, input_fn: Callable[[str], str] = input, print_fn: Callable[..., None] = print):
        self._input = input_fn
        self.say = print_fn
        # 파이프 입력에서는 getpass(Windows 콘솔 직접 읽기)가 동작하지 않으므로 tty일 때만 쓴다.
        self._use_getpass = input_fn is input and sys.stdin is not None and sys.stdin.isatty()

    def _read(self, prompt: str) -> str:
        try:
            return self._input(prompt)
        except (EOFError, KeyboardInterrupt) as e:
            raise Quit from e

    def text(self, prompt: str, *, blank_ok: bool = False) -> str:
        while True:
            s = self._read(prompt).strip()
            if s or blank_ok:
                return s
            self.say("값을 입력해 주세요.")

    def secret(self, prompt: str) -> str:
        if self._use_getpass:
            try:
                return getpass.getpass(prompt)
            except (EOFError, KeyboardInterrupt) as e:
                raise Quit from e
        return self._read(prompt)

    def integer(self, prompt: str, lo: int | None = None, hi: int | None = None, *, blank_ok: bool = False) -> int | None:
        while True:
            s = self._read(prompt).strip().replace(",", "")  # 1,185,888 도 허용
            if not s and blank_ok:
                return None
            try:
                v = int(s)
            except ValueError:
                self.say("숫자를 입력해 주세요.")
                continue
            lo_eff = 1 if lo is None else lo                 # ID·정수 입력은 1..2**63-1 (SQLite INTEGER 범위)
            hi_eff = INT_MAX if hi is None else min(hi, INT_MAX)
            if v < lo_eff or v > hi_eff:
                rng = f"{lo_eff}~{hi_eff}"
                self.say(f"범위({rng}) 안의 값을 입력해 주세요.")
                continue
            return v

    def choose(self, title: str, options: Sequence[tuple[object, str]], *, cancel: bool = True):
        """번호로 고르기. 0 = 취소(None 반환)."""
        while True:
            self.say(title)
            for i, (_, label) in enumerate(options, 1):
                self.say(f"  {i}. {label}")
            if cancel:
                self.say("  0. 취소")
            n = self.integer("번호> ", 0 if cancel else 1, len(options))
            if n == 0:
                return None
            return options[n - 1][0]

    def confirm(self, prompt: str) -> bool:
        while True:
            s = self._read(prompt + " (y/n) ").strip().lower()
            if s in ("y", "yes", "예", "ㅛ"):
                return True
            if s in ("n", "no", "아니오", "ㅜ"):
                return False
            self.say("y 또는 n 으로 답해 주세요.")
