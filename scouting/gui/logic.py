"""Pure presentation and validation helpers used by the Tk career explorer."""

from __future__ import annotations

import re
from bisect import bisect_left
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

    각 구간: club, start, end(ISO 날짜), color(0/1: 위치 기준으로 번갈아 — 이웃 블록과 색이 겹치지 않게 —,
    복귀한 구단은 그게 이웃과 같은 색이 되지 않을 때만 첫 재직 때의 색을 유지), fee(그 구간을 시작한 이적의 이적료). cutoff 이후(예정) 이적과 도착 구단이 없는 행은 무시한다.
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
        end = kept[i + 1]["transfer_date"] if i + 1 < len(kept) else cutoff
        if end <= t["transfer_date"]:
            continue
        prev = out[-1]["color"] if out else None
        if key in colors:
            color = colors[key]
            if color == prev:              # 이웃 블록과 같은 색이 되면 다른 색으로 (이번 블록만)
                color = 1 - color
        else:
            color = 0 if prev is None else 1 - prev
            colors[key] = color
        out.append({"club": t["to_club"], "start": t["transfer_date"], "end": end,
                    "color": color, "fee": t.get("fee_eur")})
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


# --- 포메이션과 포지션 코드 ---------------------------------------------------------------
# 코드 -> player.sub_position (Transfermarkt 등록 주 포지션). 순서는 화면 표시 순서.
POSITION_SUBS = {
    "GK": ("Goalkeeper",),
    "LB": ("Left-Back",), "RB": ("Right-Back",), "CB": ("Centre-Back",),
    "LWB": ("Left-Back", "Left Midfield"), "RWB": ("Right-Back", "Right Midfield"),
    "DM": ("Defensive Midfield",), "CM": ("Central Midfield",),
    "LM": ("Left Midfield", "Left Winger"), "RM": ("Right Midfield", "Right Winger"),
    "AMC": ("Attacking Midfield", "Second Striker"),
    "AML": ("Left Winger",), "AMR": ("Right Winger",),
    "ST": ("Centre-Forward", "Second Striker"),
}
# sub_position -> 대표 코드 (결과 표/프로필에 보이는 코드). 여러 코드에 걸치면 가장 흔한 쪽.
SUB_TO_CODE = {
    "Goalkeeper": "GK", "Left-Back": "LB", "Right-Back": "RB", "Centre-Back": "CB",
    "Defensive Midfield": "DM", "Central Midfield": "CM", "Left Midfield": "LM", "Right Midfield": "RM",
    "Attacking Midfield": "AMC", "Left Winger": "AML", "Right Winger": "AMR",
    "Centre-Forward": "ST", "Second Striker": "ST",
}
NO_FORMATION = "선택 안 함"
# 아래(수비)에서 위(공격) 순서. GK 줄은 모든 포메이션에 공통으로 맨 아래에 붙는다.
FORMATIONS = {
    "4-4-2": (("LB", "CB", "CB", "RB"), ("LM", "CM", "CM", "RM"), ("ST", "ST")),
    "4-3-3": (("LB", "CB", "CB", "RB"), ("CM", "DM", "CM"), ("AML", "ST", "AMR")),
    "4-2-3-1": (("LB", "CB", "CB", "RB"), ("DM", "DM"), ("AML", "AMC", "AMR"), ("ST",)),
    "4-1-4-1": (("LB", "CB", "CB", "RB"), ("DM",), ("LM", "CM", "CM", "RM"), ("ST",)),
    "4-4-1-1": (("LB", "CB", "CB", "RB"), ("LM", "CM", "CM", "RM"), ("AMC",), ("ST",)),
    "3-5-2": (("CB", "CB", "CB"), ("LWB", "CM", "DM", "CM", "RWB"), ("ST", "ST")),
    "3-4-3": (("CB", "CB", "CB"), ("LWB", "CM", "CM", "RWB"), ("AML", "ST", "AMR")),
    "5-3-2": (("LWB", "CB", "CB", "CB", "RWB"), ("CM", "DM", "CM"), ("ST", "ST")),
    "5-4-1": (("LWB", "CB", "CB", "CB", "RWB"), ("LM", "CM", "CM", "RM"), ("ST",)),
}


def formation_rows(formation: str) -> list[tuple[str, ...]]:
    """GK 줄을 포함한 줄 목록(아래 -> 위). 모르는 이름이면 빈 목록."""
    rows = FORMATIONS.get(formation)
    return [("GK",), *rows] if rows else []


def sub_positions_for(codes: Iterable[str]) -> list[str]:
    """선택한 코드들의 sub_position 합집합 (중복 없이, 코드 순서대로)."""
    out: list[str] = []
    for code in codes:
        for sub in POSITION_SUBS.get(code, ()):
            if sub not in out:
                out.append(sub)
    return out


def position_code(sub_position: str | None) -> str | None:
    return SUB_TO_CODE.get(sub_position or "")


def position_label(pos_group: str | None, sub_position: str | None) -> str:
    """결과 표의 포지션 칸: 'AMR 공격수'. 코드가 없으면 그룹 이름만."""
    group = POS_KO.get(pos_group, "-")
    code = position_code(sub_position)
    return f"{code} {group}" if code else group


# --- 국적 연관검색 ------------------------------------------------------------------------
COUNTRY_ALIASES = {
    "한국": "Korea, South", "대한민국": "Korea, South", "남한": "Korea, South", "북한": "Korea, North",
    "일본": "Japan", "중국": "China", "잉글랜드": "England", "영국": "England", "스코틀랜드": "Scotland",
    "웨일스": "Wales", "스페인": "Spain", "독일": "Germany", "프랑스": "France", "이탈리아": "Italy",
    "브라질": "Brazil", "아르헨티나": "Argentina", "포르투갈": "Portugal", "네덜란드": "Netherlands",
    "벨기에": "Belgium", "크로아티아": "Croatia", "세르비아": "Serbia", "폴란드": "Poland",
    "스위스": "Switzerland", "덴마크": "Denmark", "스웨덴": "Sweden", "노르웨이": "Norway",
    "우루과이": "Uruguay", "콜롬비아": "Colombia", "멕시코": "Mexico", "미국": "United States",
    "나이지리아": "Nigeria", "세네갈": "Senegal", "모로코": "Morocco", "이집트": "Egypt",
    "호주": "Australia", "튀르키예": "Turkey", "터키": "Turkey", "러시아": "Russia", "우크라이나": "Ukraine",
}


def suggest_nationalities(text: str, nationalities: Iterable[str], limit: int = 8) -> list[str]:
    """영문은 대소문자 무시 부분 일치, 한글은 별칭 부분 일치. 접두 일치를 먼저, 그다음 부분 일치(목록 순서 유지)."""
    q = (text or "").strip().lower()
    if not q:
        return []
    known = list(nationalities)
    present = set(known)
    first: list[str] = []
    for alias, country in COUNTRY_ALIASES.items():          # 별칭: 입력이 별칭의 앞부분이면 그 나라
        if alias.startswith(q) and country in present and country not in first:
            first.append(country)
    prefix = [n for n in known if n.lower().startswith(q) and n not in first]
    inner = [n for n in known if q in n.lower() and not n.lower().startswith(q) and n not in first]
    contains_alias = [c for a, c in COUNTRY_ALIASES.items()
                      if q in a and not a.startswith(q) and c in present and c not in first + prefix + inner]
    out = first + prefix + contains_alias + inner
    return list(dict.fromkeys(out))[:limit]


def resolve_nationality(text: str, nationalities: Iterable[str]) -> str | None:
    """입력 문자열이 목록의 나라(대소문자 무시)나 한글 별칭과 정확히 같을 때만 그 나라를 돌려준다."""
    q = (text or "").strip()
    if not q:
        return None
    known = list(nationalities)
    for n in known:
        if n.lower() == q.lower():
            return n
    alias = COUNTRY_ALIASES.get(q)
    return alias if alias in known else None


NATIONALITY_ERROR = "국적 목록에서 골라 주세요"


def suggestion_row(item: Mapping) -> str:
    """이름 제안 목록의 한 줄: 'Heung-min Son  AML 공격수 · Los Angeles FC  1992' (모르는 항목은 생략)."""
    label = position_label(item.get("pos_group"), item.get("sub_position"))
    meta = " · ".join(part for part in (label if label != "-" else "", item.get("current_club_name") or "") if part)
    text = item.get("name") or "-"
    if meta:
        text += "  " + meta
    if item.get("birth_year"):
        text += "  " + str(item["birth_year"])
    return text


def position_text(card: Mapping) -> str:
    """'AML 공격수 (Left Winger)'. 세부 포지션이 없으면 그룹 이름만."""
    label = position_label(card.get("pos_group"), card.get("sub_position"))
    if label == "-":
        label = card.get("position") or "-"
    return f"{label} ({card['sub_position']})" if card.get("sub_position") else label


# --- 차트 hover: 가장 가까운 시장가치 점, 툴팁 문구, 재직 기간 -------------------------------
def nearest_index(days: list[float], x: float) -> int | None:
    """오름차순 날짜(일 단위 숫자) 목록에서 x 에 가장 가까운 점의 인덱스. 같은 거리면 앞쪽(더 이른 날짜)."""
    if not days:
        return None
    i = bisect_left(days, x)
    if i == 0:
        return 0
    if i == len(days):
        return len(days) - 1
    return i - 1 if x - days[i - 1] <= days[i] - x else i


def season_of(day: str) -> int:
    """날짜가 속한 시즌의 시작 연도. 시즌은 7/1 에 시작한다: 2021-03-18 -> 2020 (2020/21)."""
    d = date.fromisoformat(day)
    return d.year if d.month >= 7 else d.year - 1


def season_range(season: int) -> tuple[str, str]:
    """시즌 시작 연도 -> (시작일, 종료일) ISO: 2020 -> ('2020-07-01', '2021-06-30')."""
    return f"{season}-07-01", f"{season + 1}-06-30"


def short_season(season: int) -> str:
    return f"{season % 100:02d}/{(season + 1) % 100:02d}"


def season_bands(lo: str, hi: str) -> list[int]:
    """[lo, hi] 와 겹치는 시즌들의 시작 연도."""
    return list(range(season_of(lo), season_of(hi) + 1))


def keep_uncolliding(spans: list[tuple[float, float]], pad: float = 4.0) -> list[bool]:
    """왼쪽부터 보며 앞서 남긴 라벨과 겹치는(여백 pad 포함) 라벨은 건너뛴다. 결과는 spans 와 같은 순서."""
    keep: list[bool] = []
    last_end = float("-inf")
    for x0, x1 in spans:
        ok = x0 >= last_end + pad
        keep.append(ok)
        if ok:
            last_end = x1
    return keep


def tooltip_lines(point: Mapping) -> list[str]:
    """시장가치 점 툴팁 세 줄: '날짜 (시즌)', 금액, 그 시점의 구단."""
    day = point["date"]
    return [f"{day} ({season_label(season_of(day))})", eur(point["market_value_eur"]), point.get("club_name") or "-"]


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month      # 화면에 보이는 '연-월' 기준


def duration_text(start: str, end: str) -> str:
    """'1개월 미만' / '11개월' / '1년' / '5년 6개월'."""
    months = _months_between(date.fromisoformat(start), date.fromisoformat(end))
    if months < 1:
        return "1개월 미만"
    years, rest = divmod(months, 12)
    if not years:
        return f"{rest}개월"
    return f"{years}년" + (f" {rest}개월" if rest else "")


def block_tooltip(club: str, start: str, end: str, cutoff: str) -> str:
    """커리어 띠 블록 툴팁: 'Liverpool FC / 2025-07 ~ 현재 (1년)'."""
    last = "현재" if end >= cutoff else end[:7]
    return f"{club} / {start[:7]} ~ {last} ({duration_text(start, min(end, cutoff))})"


# 출전 기록은 2012/13 시즌부터 있다. 출전 기록으로만 잡은 구간이 그 첫 시즌 안에서 시작하면
# 실제로는 더 일찍 시작했을 수 있으므로 그때만 표시한다(이후 시즌에서 시작한 구간은 출전 기록이 정확하다).
COVERAGE_FIRST_SEASON_END = "2013-07-01"
TRUNCATED_NOTE = "2012/13 이전 미수록"


def tenure_text(stint: tuple) -> str:
    """한 구간의 글: '2022-07 ~ 2025-07', '2025-07 ~ 현재'.

    근거가 출전 기록이고 수록 첫 시즌 안에서 시작하면 ' (2012/13 이전 미수록)' 을 붙인다.
    """
    start, end = stint[0], stint[1]
    source = stint[2] if len(stint) > 2 else "transfer"
    text = f"{(start[:7] if start else '시작 미상')} ~ {(end[:7] if end else '현재')}"
    truncated = source == "appearance" and start is not None and start < COVERAGE_FIRST_SEASON_END
    return f"{text} ({TRUNCATED_NOTE})" if truncated else text


def stint_text(stints: Iterable[tuple], max_shown: int = 2) -> str:
    """재직 기간 칸: 여러 번이면 ', ' 로 잇고 최근 2개만, 나머지는 ' 외 N회'. (시작, 끝[, 근거]) 튜플을 받는다."""
    stints = list(stints)
    if not stints:
        return "-"
    text = ", ".join(tenure_text(s) for s in stints[-max_shown:])
    extra = len(stints) - max_shown
    return f"{text} 외 {extra}회" if extra > 0 else text


# --- 리그 -> 구단 고르기 --------------------------------------------------------------------
LEAGUE_ALL = "전체"
CLUB_ALL = "리그 전체"
LEAGUE_SEPARATOR = "──── 그 외 리그 ────"


def league_label(row: Mapping) -> str:
    """'Premier League (England)'."""
    name = competition_name(row.get("name"))
    return f"{name} ({row['country_name']})" if row.get("country_name") else name


def league_options(rows: Iterable[Mapping]) -> list[tuple[str, str | None]]:
    """[(라벨, competition_id)]: '전체', 수록 14개 리그(이름순), 구분선, 나머지 리그(이름순). 구분선과 '전체'는 id 가 None."""
    rows = list(rows)
    covered = sorted((r for r in rows if r.get("is_covered")), key=league_label)
    others = sorted((r for r in rows if not r.get("is_covered")), key=league_label)
    out: list[tuple[str, str | None]] = [(LEAGUE_ALL, None)]
    out += [(league_label(r), r["competition_id"]) for r in covered]
    if covered and others:
        out.append((LEAGUE_SEPARATOR, None))
    out += [(league_label(r), r["competition_id"]) for r in others]
    return out


def club_options(clubs: Iterable[Mapping]) -> list[tuple[str, int | None]]:
    """[(라벨, club_id)]: '리그 전체' 다음에 이름순 구단. 이름이 같은 구단은 id 를 붙여 구분한다."""
    clubs = list(clubs)
    seen: dict[str, int] = {}
    for c in clubs:
        seen[c["name"]] = seen.get(c["name"], 0) + 1
    out: list[tuple[str, int | None]] = [(CLUB_ALL, None)]
    for c in clubs:
        label = c["name"] if seen[c["name"]] == 1 else f"{c['name']} (#{c['club_id']})"
        out.append((label, c["club_id"]))
    return out


def club_filter(picked_club_id, league_club_ids, text: str | None) -> tuple[str | None, list[int] | None]:
    """구단 조건 우선순위: 직접 고른 구단 > 이름 일부 > 리그 전체. (적용 방식, 구단 id 목록) — 이름 일부는 id 를 나중에 푼다."""
    if picked_club_id is not None:
        return "club", [int(picked_club_id)]
    if text and text.strip():
        return "text", None
    if league_club_ids:
        return "league", [int(i) for i in league_club_ids]
    return None, None


def club_filter_note(mode: str | None, *, club: str = "", league: str = "", text: str = "") -> str:
    if mode == "club":
        return f"적용: {club} (구단 선택)"
    if mode == "text":
        return f"적용: 이름에 '{text.strip()}' 포함 구단"
    if mode == "league":
        return f"적용: {league} 전체 구단"
    return "적용 안 함"


def identifier(value: object) -> str:
    return "-" if value is None else str(int(value))
