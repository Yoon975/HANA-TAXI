"""
TIMS 수익 엑셀 → 배차일지 반영.
영업일(06시) 기준, 차량별 합계 0원이면 '휴차'.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from modules.business_day import to_business_date
from modules.paths import CONFIG_DIR, ensure_storage

REVENUE_MAP_FILE = "revenue_column_mapping.json"

DATE_ALIASES = [
    "날짜", "일자", "운행일", "영업일", "일시", "시간", "발생일시", "date", "datetime", "time"
]
PLATE_ALIASES = [
    "차번", "차량", "차량번호", "차량번", "번호", "plate", "car", "택시번호"
]
REVENUE_ALIASES = [
    "수익", "수익금", "매출", "수입", "요금", "금액", "합계", "revenue", "income", "fare"
]


def _map_path() -> Path:
    ensure_storage()
    return CONFIG_DIR / REVENUE_MAP_FILE


def load_revenue_mapping() -> dict[str, str | None]:
    path = _map_path()
    default = {"date": None, "plate": None, "revenue": None}
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out = dict(default)
        out.update({k: data.get(k) for k in default})
        return out
    except (OSError, json.JSONDecodeError):
        return default


def save_revenue_mapping(mapping: dict[str, str | None]) -> Path:
    path = _map_path()
    path.write_text(
        json.dumps(
            {k: mapping.get(k) for k in ("date", "plate", "revenue")},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _guess_col(columns: list[str], aliases: list[str]) -> str | None:
    lower = {str(c).strip().lower(): str(c) for c in columns}
    for a in aliases:
        if a.lower() in lower:
            return lower[a.lower()]
    for key, orig in lower.items():
        for a in aliases:
            if a.lower() in key:
                return orig
    return None


def suggest_columns(df: pd.DataFrame) -> dict[str, str | None]:
    cols = [str(c) for c in df.columns]
    saved = load_revenue_mapping()
    return {
        "date": saved.get("date") if saved.get("date") in cols else _guess_col(cols, DATE_ALIASES),
        "plate": saved.get("plate") if saved.get("plate") in cols else _guess_col(cols, PLATE_ALIASES),
        "revenue": saved.get("revenue")
        if saved.get("revenue") in cols
        else _guess_col(cols, REVENUE_ALIASES),
    }


def _norm_plate(plate: str) -> str:
    return re.sub(r"\s+", "", str(plate or "").strip()).upper()


def _parse_money(val: Any) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("원", "")
    if not s or s.lower() in {"nan", "none", "-"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def aggregate_revenue(
    df: pd.DataFrame,
    *,
    date_col: str,
    plate_col: str,
    revenue_col: str,
) -> pd.DataFrame:
    """영업일·차번별 수익 합계. 컬럼: business_date, plate, revenue."""
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        bd = to_business_date(r.get(date_col))
        plate = _norm_plate(r.get(plate_col))
        if not bd or not plate:
            continue
        rows.append(
            {
                "business_date": bd,
                "plate": plate,
                "revenue": _parse_money(r.get(revenue_col)),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["business_date", "plate", "revenue"])
    out = pd.DataFrame(rows)
    return (
        out.groupby(["business_date", "plate"], as_index=False)["revenue"]
        .sum()
        .sort_values(["business_date", "plate"])
    )
