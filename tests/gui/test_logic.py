from datetime import timedelta, timezone

import pytest

from scouting.gui import logic


def test_ranges_and_columns():
    assert logic.parse_int("21", "나이", 15, 30) == 21
    assert logic.parse_int("", "나이", 15, 30, blank=21) == 21
    with pytest.raises(ValueError): logic.parse_int("31", "나이", 15, 30)
    with pytest.raises(ValueError): logic.parse_int("x", "나이", 15, 30)
    assert "m_clean_sheet_rate" in dict(logic.season_columns("GK"))
    fw = dict(logic.season_columns("FW"))
    assert fw["m_goals_per90"] == "득점/90"
    assert fw["m_ga_per90"] == "공격P/90"
    assert fw["m_onpitch_gd_per90"] == "득실차/90"
    assert "m_goal_involvement_per90" not in fw
    assert logic.format_season_value("m_ga_per90", 0.7234) == "0.723"
    assert logic.format_season_value("m_minutes_share", 0.882679738) == "88.3%"


def test_chart_shaping_and_percentile_order():
    rows = [{"season": 2021, "age": 21, "m_goals_per90": .4, "m_minutes_share": .8},
            {"season": 2020, "age": 20, "m_goals_per90": .2, "m_minutes_share": .5}]
    shaped = logic.growth_series(rows, "FW")
    assert shaped["season"] == [2020, 2021]
    assert shaped["m_goals_per90"] == [.2, .4]
    values = logic.valuation_series([{"date":"2022-01-01","market_value_eur":10},
                                     {"date":"2021-01-01","market_value_eur":20}])
    assert values["dates"] == ["2021-01-01", "2022-01-01"]
    assert values["peak"]["market_value_eur"] == 20
    pct = logic.ordered_percentiles([{"metric_code":"b","weight":None},{"metric_code":"a","weight":2},
                                     {"metric_code":"c","weight":1}])
    assert [p["metric_code"] for p in pct] == ["a","c","b"]


def test_formatting():
    assert logic.eur(50_000_000) == "€50.0M"
    assert logic.identifier(1234567) == "1234567"
    assert logic.local_time("2020-01-01 00:00:00", timezone(timedelta(hours=9))) == "2020-01-01 09:00:00"


def test_recommendation_validation():
    assert logic.validate_recommendation({})["max_age"] == 21
    with pytest.raises(ValueError): logic.validate_recommendation({"k":"0"})
