"""Pure presentation and validation helpers used by the Tk career explorer."""

from __future__ import annotations

from typing import Iterable, Mapping

# 화면 라벨 -> DB pos_group (빈 값 = 전체)
POS_LABELS = {"": "", "골키퍼": "GK", "수비수": "DF", "미드필더": "MF", "공격수": "FW"}
POS_KO = {"GK": "골키퍼", "DF": "수비수", "MF": "미드필더", "FW": "공격수"}

TITLE = "축구 선수 커리어 탐색기"
DESCRIPTION = "Transfermarkt 공개 데이터로 선수의 이적·시즌 기록·시장가치 커리어를 찾아봅니다."

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
    return f"데이터 기준: 경기 {cutoff.get('game') or '-'} · 시장가치 {cutoff.get('valuation') or '-'} {tail}"


def coverage_note(summary: Mapping) -> str:
    parts = [f"유럽 1부 {summary.get('covered_leagues', 0)}개 리그"]
    types = set(summary.get("types", ()))
    if "domestic_cup" in types:
        parts.append("국내컵")
    if summary.get("has_uefa"):
        parts.append("UEFA 대회")
    if "national_team_competition" in types:
        parts.append("주요 국가대항전")
    return "·".join(parts) + "만 수록. 그 외 리그(MLS, K리그 등) 기록은 없음."


def transfer_rows(rows: Iterable[Mapping]) -> list[tuple]:
    """transfer_history 결과 -> 표 행 (날짜, 시즌, 이전 → 이후, 이적료, 당시 시장가치)."""
    out = []
    for r in rows:
        date = r["transfer_date"] + (" (예정)" if r.get("upcoming") else "")
        out.append((date, r.get("transfer_season") or "-",
                    f"{r.get('from_club') or '-'} → {r.get('to_club') or '-'}",
                    fee_text(r.get("fee_eur")), eur(r.get("market_value_eur"))))
    return out


def season_rows(rows: Iterable[Mapping]) -> list[tuple[tuple, bool]]:
    """career_seasons 결과 -> [(표 행, 소계 여부)]."""
    out = []
    for r in rows:
        sub = bool(r.get("is_subtotal"))
        starts = "-" if r.get("starts") is None else r["starts"]
        out.append(((season_label(r["season"]),
                     "소계" if sub else r["club_name"],
                     "" if sub else competition_name(r["competition_slug"]),
                     r["apps"], starts, r["minutes"], r["goals"], r["assists"], r["yellow"], r["red"]), sub))
    return out


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


def club_moves(transfers: Iterable[Mapping]) -> list[tuple[str, str]]:
    """차트 마커용: 구단이 바뀐 이적의 (날짜, 도착 구단). 도착 구단이 없는 행은 제외."""
    return [(t["transfer_date"], t["to_club"]) for t in transfers
            if t.get("to_club") and t.get("from_club_id") != t.get("to_club_id")]


def identifier(value: object) -> str:
    return "-" if value is None else str(int(value))
