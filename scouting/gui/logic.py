"""Pure presentation and validation helpers used by the Tk career explorer."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Iterable, Mapping

# 화면 라벨 -> DB pos_group (빈 값 = 전체)
POS_LABELS = {"": "", "골키퍼": "GK", "수비수": "DF", "미드필더": "MF", "공격수": "FW"}
POS_KO = {"GK": "골키퍼", "DF": "수비수", "MF": "미드필더", "FW": "공격수"}

TITLE = "축구 선수 커리어 탐색기"
DESCRIPTION = "Transfermarkt 공개 데이터로 선수의 이적, 시즌 기록, 시장가치 커리어를 찾아봅니다."

_WORD_FIX = {
    "uefa": "UEFA", "fa": "FA", "dfb": "DFB", "knvb": "KNVB", "laliga": "LaLiga", "j1": "J1",
    "hnl": "HNL", "supersport": "SuperSport", "liga-mx": "Liga MX", "mls": "MLS",
}


def parse_int(value: object, label: str, lo: int, hi: int, *, blank: int | None = None) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return blank
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(f"{label}: 숫자를 입력해 주세요.") from exc
    if not lo <= number <= hi:
        raise ValueError(f"{label}: 범위({lo}~{hi}) 안의 값을 입력해 주세요.")
    return number


def pos_group_of(label: str) -> str | None:
    return POS_LABELS.get(label or "") or None


def season_label(season: object) -> str:
    """2024 -> '2024/25' (시즌 시작 연도)."""
    if season is None or season == "":
        return "-"
    y = int(season)
    return f"{y}/{(y + 1) % 100:02d}"


def competition_name(slug: str | None) -> str:
    """'premier-league' -> 'Premier League', 'uefa-champions-league' -> 'UEFA Champions League'."""
    if not slug:
        return "-"
    words = []
    for w in slug.split("-"):
        words.append(_WORD_FIX.get(w, w[:1].upper() + w[1:]))
    return " ".join(words)


def eur(value: object) -> str:
    if value is None:
        return "-"
    amount = float(value)
    if abs(amount) >= 1_000_000:
        return f"€{amount / 1_000_000:.1f}M"
    if amount == 0:
        return "€0"
    return f"€{amount / 1_000:.0f}K"


def fee_text(fee: object) -> str:
    """이적료: 알 수 없으면 '-'. 데이터에 이적 유형 컬럼이 없으므로 '자유 이적'/'임대'는 추정하지 않는다."""
    return "-" if fee is None else eur(fee)


def banner_text(cutoff: Mapping) -> str:
    season = cutoff.get("season")
    tail = f"({season_label(season)} 시즌까지, 이후 이적 미반영)" if season is not None else "(이후 이적 미반영)"
    return f"데이터 기준 경기 {cutoff.get('game') or '-'}, 시장가치 {cutoff.get('valuation') or '-'} {tail}"


def coverage_note(summary: Mapping) -> str:
    parts = [f"유럽 1부 {summary.get('covered_leagues', 0)}개 리그"]
    types = set(summary.get("types", ()))
    if "domestic_cup" in types:
        parts.append("국내컵")
    if summary.get("has_uefa"):
        parts.append("UEFA 대회")
    if "national_team_competition" in types:
        parts.append("주요 국가대항전")
    return ", ".join(parts) + "만 수록. 그 외 리그(MLS, K리그 등) 기록은 없음."


def no_league_note(summary: Mapping) -> str:
    return (f"이 선수는 수록된 리그(유럽 1부 {summary.get('covered_leagues', 0)}개) 경기 기록이 없습니다. "
            "이적 이력과 시장가치만 표시합니다.")


EMPTY_SEARCH = "조건에 맞는 선수가 없습니다. 이름 일부나 구단 이름으로 다시 찾아보세요."


def transfer_rows(rows: Iterable[Mapping]) -> list[tuple]:
    """transfer_history 결과 -> 표 행 (날짜, 시즌, 이전 → 이후, 이적료, 당시 시장가치)."""
    out = []
    for r in rows:
        date = r["transfer_date"] + (" (예정)" if r.get("upcoming") else "")
        out.append((date, r.get("transfer_season") or "-",
                    f"{r.get('from_club') or '-'} → {r.get('to_club') or '-'}",
                    fee_text(r.get("fee_eur")), eur(r.get("market_value_eur"))))
    return out


def season_groups(rows: Iterable[Mapping]) -> list[dict]:
    """career_seasons 결과 -> 시즌·구단별 부모 행(합계)과 대회별 자식 행.

    값 순서: 출전, 선발, 분, 골, 도움, 경고, 퇴장. 선발은 라인업 데이터가 없으면 '-'.
    """
    keys = ("apps", "starts", "minutes", "goals", "assists", "yellow", "red")
    groups: dict[tuple, dict] = {}
    for r in rows:
        if r.get("is_subtotal"):
            continue
        g = groups.setdefault((r["season"], r["club_id"]), {
            "season": season_label(r["season"]), "club": r["club_name"], "children": [], "src": []})
        g["children"].append((competition_name(r["competition_slug"]), tuple(_cell(r[k]) for k in keys)))
        g["src"].append(r)
    out = []
    for g in groups.values():
        src = g.pop("src")
        totals = []
        for k in keys:
            vals = [r[k] for r in src if r[k] is not None]
            totals.append(_cell(sum(vals) if vals else None))
        g["values"] = tuple(totals)
        out.append(g)
    return out


def _cell(value: object) -> object:
    return "-" if value is None else value


def season_chart_series(rows: Iterable[Mapping]) -> dict:
    """소계 행에서 시즌별 (분, 골+도움) 시리즈. 리그만/전체 대회 두 벌을 만들 때 각각 호출."""
    subs = [r for r in rows if r.get("is_subtotal")]
    subs.sort(key=lambda r: r["season"])
    return {"seasons": [season_label(r["season"]) for r in subs],
            "minutes": [r["minutes"] for r in subs],
            "ga": [r["goals"] + r["assists"] for r in subs]}


def valuation_series(rows: Iterable[Mapping]) -> dict:
    ordered = sorted(rows, key=lambda row: row.get("date") or "")
    dates = [row.get("date") for row in ordered]
    values = [row.get("market_value_eur") for row in ordered]
    peak = None
    if ordered:
        peak = dict(max(ordered, key=lambda row: (row.get("market_value_eur") or -1, row.get("date") or "")))
    return {"dates": dates, "values": values, "peak": peak}


def club_moves(transfers: Iterable[Mapping]) -> list[tuple[str, str, float | None]]:
    """구단이 바뀐 이적의 (날짜, 도착 구단, 이적료). 도착 구단이 없는 행은 제외."""
    return [(t["transfer_date"], t["to_club"], t.get("fee_eur")) for t in transfers
            if t.get("to_club") and t.get("from_club_id") != t.get("to_club_id")]


def tenures(transfers: Iterable[Mapping], cutoff: str) -> list[dict]:
    """이적 이력 -> 구단 재직 구간. 첫 이적일부터 cutoff 까지 빈틈·겹침 없이 이어진다.

    각 구간: club, start, end(ISO 날짜), color(0/1, 처음 등장한 구단 순서로 번갈아 부여하고 복귀한 구단은
    첫 재직 때의 색을 유지), fee(그 구간을 시작한 이적의 이적료). cutoff 이후(예정) 이적과 도착 구단이 없는 행은 무시한다.
    """
    moves = sorted((t for t in transfers if t.get("to_club") and t["transfer_date"] <= cutoff),
                   key=lambda t: (t["transfer_date"], t.get("transfer_id") or 0))
    kept: list[Mapping] = []
    for t in moves:
        if kept and kept[-1]["transfer_date"] == t["transfer_date"]:
            kept[-1] = t                       # 같은 날 여러 이적이면 마지막 도착지만
        else:
            kept.append(t)
    colors: dict = {}
    out: list[dict] = []
    for i, t in enumerate(kept):
        key = t.get("to_club_id") if t.get("to_club_id") is not None else t["to_club"]
        if key not in colors:
            colors[key] = len(colors) % 2
        end = kept[i + 1]["transfer_date"] if i + 1 < len(kept) else cutoff
        if end <= t["transfer_date"]:
            continue
        out.append({"club": t["to_club"], "start": t["transfer_date"], "end": end,
                    "color": colors[key], "fee": t.get("fee_eur")})
    return out


YOUTH_LABEL = "유스"
_PHRASES = ("Club de Fútbol", "Football Club", "de Fútbol", "Bayer 04")
_GENERIC = {"FC", "CF", "AFC", "SC", "SL", "SV", "Club", "Football", "Calcio"}
_NUMBER = re.compile(r"^\d+\.?$")          # 04, 1909, '1.' 같은 숫자 토큰


def shorten_club(name: str) -> str:
    """차트 띠 전용 이름 줄이기: 'Los Angeles Football Club' -> 'Los Angeles', 'Bayer 04 Leverkusen' -> 'Leverkusen'.

    구 표기(Football Club, de Fútbol …)와 앞뒤의 FC/SC/SL/SV 같은 일반 토큰, 설립 연도 숫자를 뗀다. 다 떼면 원래 이름.
    """
    text = name
    for phrase in _PHRASES:
        text = text.replace(phrase, " ")
    words = text.split()
    while words and (words[0] in _GENERIC or _NUMBER.match(words[0])):
        words.pop(0)
    while words and (words[-1] in _GENERIC or _NUMBER.match(words[-1])):
        words.pop()
    return " ".join(words) or name


def strip_start(first_transfer: str, first_valuation: str | None) -> str:
    """띠/시장가치 공통 x 축 시작일: max(첫 이적일, 첫 시장가치일 - 1년)."""
    if not first_valuation:
        return first_transfer
    earliest = (date.fromisoformat(first_valuation) - timedelta(days=365)).isoformat()
    return max(first_transfer, earliest)


def collapse_youth(blocks: list[dict], first_valuation: str | None, first_appearance: str | None) -> list[dict]:
    """첫 시장가치일/첫 출전일 중 이른 날 이전에 끝난 재직 구간을 하나의 '유스' 블록(color=2)으로 합친다."""
    marks = [d for d in (first_valuation, first_appearance) if d]
    if not marks or not blocks:
        return blocks
    boundary = min(marks)
    youth = [b for b in blocks if b["end"] <= boundary]
    if not youth:
        return blocks
    merged = {"club": YOUTH_LABEL, "start": youth[0]["start"], "end": youth[-1]["end"], "color": 2,
              "fee": None, "youth": True}
    return [merged] + blocks[len(youth):]


def fit_label(name: str, available: float, measure, min_chars: int = 3) -> str | None:
    """블록 폭(available) 안에 들어가는 라벨. 안 들어가면 '…' 로 줄이고, 3글자('…' 포함)도 안 들어가면 None.

    measure(text) -> 그 글자열의 폭(같은 단위). 폭은 렌더러가 잰 값을 넣는다.
    """
    if not name:
        return None
    if measure(name) <= available:
        return name
    for total in range(len(name) - 1, min_chars - 1, -1):      # total: '…' 를 포함한 글자 수
        text = name[: total - 1].rstrip() + "…"
        if measure(text) <= available:
            return text
    return None


def position_text(card: Mapping) -> str:
    """'공격수 (Left Winger)'. 세부 포지션이 없으면 그룹 이름만."""
    pos = POS_KO.get(card.get("pos_group"), card.get("position") or "-")
    return f"{pos} ({card['sub_position']})" if card.get("sub_position") else pos


def identifier(value: object) -> str:
    return "-" if value is None else str(int(value))
