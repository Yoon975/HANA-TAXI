"""영업일: 당일 06:00 ~ 익일 06:00."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

DAY_START_HOUR = 6


def business_date(dt: datetime | None = None) -> date:
    """시각 기준 영업일 (06시 미만이면 전일)."""
    dt = dt or datetime.now()
    if dt.hour < DAY_START_HOUR:
        return (dt - timedelta(days=1)).date()
    return dt.date()


def to_business_date(value: Any) -> date | None:
    """날짜/시각/문자열 → 영업일. 시각이 있으면 06시 규칙, 날짜만 있으면 그 날짜."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return business_date(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    # pandas Timestamp
    if hasattr(value, "to_pydatetime"):
        try:
            return business_date(value.to_pydatetime())
        except Exception:
            pass
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "nat"}:
        return None
    # 날짜만 (YYYY-MM-DD 등)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%y.%m.%d",
        "%Y%m%d",
    ):
        try:
            parsed = datetime.strptime(s[:19], fmt) if len(fmt) > 10 else datetime.strptime(s[:10], fmt)
            if "%H" in fmt:
                return business_date(parsed)
            return parsed.date()
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(s, errors="coerce")
        if pd.isna(ts):
            return None
        pdt = ts.to_pydatetime()
        if pdt.hour or pdt.minute or pdt.second:
            return business_date(pdt)
        return pdt.date()
    except Exception:
        return None


def next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1
