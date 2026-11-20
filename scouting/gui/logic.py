"""Pure presentation and validation helpers used by the Tk career explorer."""

from __future__ import annotations

from datetime import date
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
            "label": f"{season_label(r['season'])} · {r['club_name']}", "children": [], "src": []})
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


def merge_close_moves(moves: Iterable[tuple], min_days: int = 180) -> list[tuple]:
    """앞 이적과 min_days 미만 간격이면 하나로 합친다(임대 후 복귀 등). 마지막 이적의 날짜·구단을 남기고,
    이적료는 합쳐진 이적 중 가장 큰 값을 가져간다(우선순위 판단용)."""
    out: list[tuple] = []
    for move in sorted(moves, key=lambda m: m[0]):
        if out and (date.fromisoformat(move[0]) - date.fromisoformat(out[-1][0])).days < min_days:
            fees = [f for f in (out[-1][2], move[2]) if f is not None]
            out[-1] = (move[0], move[1], max(fees) if fees else None)
        else:
            out.append(move)
    return out


def shorten(name: str, limit: int = 14) -> str:
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def chart_moves(transfers: Iterable[Mapping], lo: str, hi: str) -> list[tuple[str, str, float | None]]:
    """차트 마커: 시장가치 기간 [lo, hi] 안의 구단 이동만, 가까운 이동은 병합, 이름은 줄여서."""
    inside = [m for m in club_moves(transfers) if lo <= m[0] <= hi]
    return [(d, shorten(c), fee) for d, c, fee in merge_close_moves(inside)]


def label_priority(moves: Iterable[tuple]) -> list[int]:
    """라벨 배치 우선순위(인덱스): 이적료가 있는 이적(큰 순) → 나머지 최근 순."""
    moves = list(moves)
    paid = [i for i, m in enumerate(moves) if (m[2] or 0) > 0]
    paid.sort(key=lambda i: moves[i][0], reverse=True)       # 동률이면 최근 것이 먼저
    paid.sort(key=lambda i: -moves[i][2])
    rest = sorted((i for i in range(len(moves)) if i not in paid), key=lambda i: moves[i][0], reverse=True)
    return paid + rest


def assign_label_rows(spans: Iterable[tuple[float, float]], rows: int = 3, pad: float = 4.0,
                      order: Iterable[int] | None = None) -> list[int | None]:
    """x 구간(픽셀)에 라벨 줄을 배정한다. order(우선순위) 순으로 가장 위 줄부터 시도하고,
    같은 줄의 이미 배정된 라벨과 겹치면 다음 줄, 모두 겹치면 None(생략). 결과는 spans 와 같은 순서."""
    spans = list(spans)
    taken: list[list[tuple[float, float]]] = [[] for _ in range(rows)]
    out: list[int | None] = [None] * len(spans)
    for i in (list(order) if order is not None else range(len(spans))):
        x0, x1 = spans[i]
        for r in range(rows):
            if all(x0 >= e + pad or x1 <= s0 - pad for s0, e in taken[r]):
                taken[r].append((x0, x1))
                out[i] = r
                break
    return out


def identifier(value: object) -> str:
    return "-" if value is None else str(int(value))
