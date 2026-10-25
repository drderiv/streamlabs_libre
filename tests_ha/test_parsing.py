"""Pure-logic tests: usage parsing and flow-rate estimation."""

from datetime import datetime, timezone

from custom_components.streamlabs_libre.flow import FlowRateEstimator
from custom_components.streamlabs_libre.parsing import (
    extract_usage,
    first_present,
    parse_year_history,
)


def test_extract_usage_flat_summary():
    assert extract_usage({"today": 10.5, "thisMonth": 100.2, "thisYear": 1200.0}) == (10.5, 100.2, 1200.0)


def test_extract_usage_comparative():
    usage = {"day": {"todayTotal": 7.8}, "month": {"thisMonthTotal": 70.0}, "year": {"thisYearTotal": 700.0}}
    assert extract_usage(usage) == (7.8, 70.0, 700.0)


def test_extract_usage_scalar_periods_and_garbage():
    assert extract_usage({"day": 3, "month": 30, "year": 300}) == (3.0, 30.0, 300.0)
    assert extract_usage({"day": {"todayTotal": "bad"}}) == (0.0, 0.0, 0.0)
    assert extract_usage(None) == (0.0, 0.0, 0.0)


def test_extract_usage_timeseries():
    assert extract_usage({"data": [1.0, 2.0, 3.5], "interval": "hour"}) == (6.5, 0.0, 0.0)
    assert extract_usage({"data": [10, 20], "interval": "month"}) == (0.0, 0.0, 30.0)
    assert extract_usage({"data": [{"volume": 2}, {"volume": 3}]}) == (5.0, 0.0, 0.0)


def test_year_floor_is_current_month():
    assert extract_usage({"month": {"total": 40.0}}) == (0.0, 40.0, 40.0)


def test_first_present_keeps_zero():
    assert first_present({"a": 0}, {"a": 5}, keys=("a",)) == 0
    assert first_present({"a": None}, {"b": 2}, keys=("a", "b")) == 2
    assert first_present({}, keys=("a",)) is None


def test_parse_year_history():
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    assert parse_year_history({"data": [1, 2, "x"], "startTime": 1_700_000_000}, now) == (
        [1.0, 2.0],
        "Nov, 2023",
    )
    assert parse_year_history({"data": [1]}, now) == ([1.0], "Oct, 2025")
    assert parse_year_history({"data": []}, now) is None
    assert parse_year_history(None, now) is None


def test_flow_rate_waits_for_cloud_flush_then_smooths():
    est = FlowRateEstimator()
    assert est.update(True, 100.0, 0) == 0.0  # first poll: baseline only
    assert est.update(True, 100.0, 15) == 0.0  # cloud hasn't flushed yet
    assert est.update(True, 101.0, 30) == 0.0  # backlog flushed, baseline established
    assert est.update(True, 102.5, 45) == 6.0  # 1.5 gal / 15 s
    assert est.update(True, 104.0, 60) == 6.0  # window of two intervals: 3 gal / 30 s
    assert est.update(False, 104.0, 75) == 0.0


def test_flow_rate_handles_midnight_rollover():
    est = FlowRateEstimator()
    est.update(True, 500.0, 0)
    est.update(True, 501.0, 15)
    est.update(True, 502.0, 30)
    assert est.update(True, 1.0, 45) == 0.0
    assert est.samples == []
