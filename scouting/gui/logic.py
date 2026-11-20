"""Pure presentation and validation helpers used by the Tk views."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping

POS_GROUPS = ("GK", "DF", "MF", "FW")

BASE_SEASON_COLUMNS = (
    ("season", "시즌"), ("age", "나이"), ("club_name", "구단"),
    ("league_apps", "경기"), ("league_starts", "선발"), ("league_minutes", "분"),
    ("m_minutes_share", "출전비율"),
)
POSITION_COLUMNS = {
    "GK": BASE_SEASON_COLUMNS + (("m_onpitch_ga_per90", "실점/90"), ("m_clean_sheet_rate", "무실점률")),
    "DF": BASE_SEASON_COLUMNS + (("m_onpitch_ga_per90", "실점/90"), ("m_clean_sheet_rate", "무실점률"),
                                  ("m_onpitch_gd_per90", "득실차/90")),
    "MF": BASE_SEASON_COLUMNS + (("m_ga_per90", "공격P/90"), ("m_assists_per90", "도움/90"),
                                  ("m_onpitch_gd_per90", "득실차/90")),
    "FW": BASE_SEASON_COLUMNS + (("m_goals_per90", "득점/90"), ("m_ga_per90", "공격P/90"),
                                  ("m_onpitch_gd_per90", "득실차/90")),
}
GROWTH_METRICS = {
    "GK": ("m_onpitch_ga_per90", "m_clean_sheet_rate", "m_minutes_share"),
    "DF": ("m_onpitch_ga_per90", "m_clean_sheet_rate", "m_onpitch_gd_per90", "m_minutes_share"),
    "MF": ("m_ga_per90", "m_assists_per90", "m_onpitch_gd_per90", "m_minutes_share"),
    "FW": ("m_goals_per90", "m_ga_per90", "m_onpitch_gd_per90", "m_minutes_share"),
}


def parse_int(value: object, label: str, lo: int, hi: int, *, blank: int | None = None) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text and blank is not None:
        return blank
    if not text and blank is None:
        return None
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(f"{label}: 숫자를 입력해 주세요.") from exc
    if not lo <= number <= hi:
        raise ValueError(f"{label}: 범위({lo}~{hi}) 안의 값을 입력해 주세요.")
    return number


def validate_recommendation(values: Mapping[str, object]) -> dict[str, int]:
    rules = {
        "max_age": ("최대 나이", 15, 30, 21), "min_minutes": ("최소 출전 분", 0, 5000, 900),
        "k": ("k", 1, 200, 25), "top_n": ("top_n", 1, 200, 20),
        "pool_lag_seasons": ("pool_lag", 0, 10, 3), "seed": ("seed", 1, 2**63 - 1, 42),
    }
    return {key: int(parse_int(values.get(key), rule[0], rule[1], rule[2], blank=rule[3]) or rule[3])
            for key, rule in rules.items()}


def season_columns(pos_group: str | None) -> tuple[tuple[str, str], ...]:
    return POSITION_COLUMNS.get(pos_group or "", BASE_SEASON_COLUMNS)


def format_season_value(key: str, value: object) -> str:
    if value is None:
        return "-"
    if key == "m_minutes_share":
        return f"{float(value) * 100:.1f}%"
    if key.startswith("m_"):
        return f"{float(value):.3f}"
    return str(value)


def growth_series(rows: Iterable[Mapping], pos_group: str) -> dict[str, list]:
    ordered = sorted(rows, key=lambda row: (row.get("season", 0), row.get("age", 0)))
    out: dict[str, list] = {"season": [], "age": []}
    metrics = GROWTH_METRICS.get(pos_group, ("m_minutes_share",))
    for metric in metrics:
        out[metric] = []
    for row in ordered:
        out["season"].append(row.get("season")); out["age"].append(row.get("age"))
        for metric in metrics:
            out[metric].append(row.get(metric))
    return out


def valuation_series(rows: Iterable[Mapping]) -> dict:
    ordered = sorted(rows, key=lambda row: row.get("date") or "")
    dates = [row.get("date") for row in ordered]
    values = [row.get("market_value_eur") for row in ordered]
    peak = None
    if ordered:
        peak = dict(max(ordered, key=lambda row: (row.get("market_value_eur") or -1, row.get("date") or "")))
    return {"dates": dates, "values": values, "peak": peak}


def ordered_percentiles(rows: Iterable[Mapping]) -> list[dict]:
    return sorted((dict(row) for row in rows),
                  key=lambda row: (row.get("weight") is None, -(row.get("weight") or 0), row.get("metric_code", "")))


def eur(value: object) -> str:
    if value is None:
        return "-"
    amount = float(value)
    if abs(amount) >= 1_000_000:
        return f"€{amount / 1_000_000:.1f}M"
    return f"€{amount / 1_000:.0f}K"


def local_time(value: str | None, tz=None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def identifier(value: object) -> str:
    return "-" if value is None else str(int(value))


def metric_display(row: Mapping) -> str:
    value = row.get("display_value")
    return "-" if value is None else f"{float(value):.2f}{row.get('unit', '')}"
