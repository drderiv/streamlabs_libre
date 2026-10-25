"""Pure helpers that normalise the loosely-structured StreamLabs API payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Final

# Per period: (keys inside the nested ``usage[period]`` object, keys on the flat usage object)
_USAGE_KEYS: Final[dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "day": (
        ("todayTotal", "total", "today", "value", "volume"),
        ("today", "todayTotal", "daily", "dailyTotal"),
    ),
    "month": (
        ("thisMonthTotal", "total", "thisMonth", "value", "volume"),
        ("thisMonth", "thisMonthTotal", "monthly", "monthlyTotal", "monthTotal"),
    ),
    "year": (
        ("thisYearTotal", "total", "thisYear", "value", "volume"),
        ("thisYear", "thisYearTotal", "yearly", "yearlyTotal", "yearTotal"),
    ),
}


def first_present(*sources: Mapping[str, Any], keys: Iterable[str]) -> Any:
    """Return the first value that is not None, looking through ``sources`` then ``keys``.

    Unlike an ``or`` chain this keeps legitimate zero readings.
    """
    keys = tuple(keys)
    for source in sources:
        for key in keys:
            if (value := source.get(key)) is not None:
                return value
    return None


def _first_positive(source: Mapping[str, Any], keys: Iterable[str]) -> float:
    for key in keys:
        try:
            if (value := float(source[key])) > 0:
                return value
        except (KeyError, TypeError, ValueError):
            continue
    return 0.0


def _extract_period(usage: Mapping[str, Any], period: str) -> float:
    nested_keys, flat_keys = _USAGE_KEYS[period]
    nested = usage.get(period)
    if isinstance(nested, Mapping):
        if value := _first_positive(nested, nested_keys):
            return value
    elif isinstance(nested, (int, float)) and not isinstance(nested, bool) and nested:
        return float(nested)
    return _first_positive(usage, flat_keys)


def extract_usage(usage: Mapping[str, Any] | None) -> tuple[float, float, float]:
    """Extract daily, monthly and yearly water consumption totals."""
    if not usage or not isinstance(usage, Mapping):
        return 0.0, 0.0, 0.0

    daily = _extract_period(usage, "day")
    monthly = _extract_period(usage, "month")
    yearly = _extract_period(usage, "year")

    # Timeseries array: {"data": [...], "interval": "hour" | "day" | "month"}
    series = usage.get("data")
    if isinstance(series, list):
        numbers = [float(x) for x in series if isinstance(x, (int, float))]
        if numbers:
            interval = str(usage.get("interval", "")).lower()
            if interval == "month" and yearly == 0.0:
                yearly = round(sum(numbers), 1)
            elif interval == "day" and monthly == 0.0:
                monthly = round(sum(numbers), 1)
            elif interval == "hour" and daily == 0.0:
                daily = round(sum(numbers), 1)
        elif daily == 0.0:
            daily = sum(
                float(pt.get("volume", 0.0) or 0.0) for pt in series if isinstance(pt, Mapping)
            )

    # A calendar year's usage cannot be less than the current month's usage.
    if yearly == 0.0 and monthly > 0.0:
        yearly = monthly

    return daily, monthly, yearly


def parse_year_history(
    response: Mapping[str, Any] | None, now: datetime
) -> tuple[list[float], str] | None:
    """Parse a rolling-year response into (monthly values, "used since" label)."""
    if not isinstance(response, Mapping):
        return None
    raw = response.get("data")
    if not isinstance(raw, list):
        return None
    values = [float(x) for x in raw if isinstance(x, (int, float))]
    if not values:
        return None

    start_time = response.get("startTime")
    if isinstance(start_time, (int, float)) and start_time > 0:
        used_since = datetime.fromtimestamp(start_time, timezone.utc).strftime("%b, %Y")
    else:
        used_since = (now - timedelta(days=365)).strftime("%b, %Y")
    return values, used_since
