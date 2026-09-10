"""
시급·초과금 설정 (전원 동일, 언제든 변경 가능).
초과금: 월수입 X >= 기준액 → (X - 기준액) * 기사지급비율
월별로 요율 스냅샷·차번별 수익을 남겨 과거 정산이 안 바뀌게 함.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

from modules.dispatch_export import load_month_meta, month_key, save_month_meta
from modules.paths import CONFIG_DIR, ensure_storage

SETTINGS_FILE = "wage_settings.json"

DEFAULT_SETTINGS: dict[str, float] = {
    "hourly_wage": 0.0,
    "excess_threshold": 4_000_000.0,
    "driver_share_rate": 0.90,
}


def _settings_path():
    ensure_storage()
    return CONFIG_DIR / SETTINGS_FILE


def _norm_plate(plate: str) -> str:
    return re.sub(r"\s+", "", str(plate or "")).upper()


def load_settings() -> dict[str, float]:
    path = _settings_path()
    out = dict(DEFAULT_SETTINGS)
    if not path.exists():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k in DEFAULT_SETTINGS:
                if k in data and data[k] is not None:
                    out[k] = float(data[k])
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return out


def save_settings(
    *,
    hourly_wage: float | None = None,
    excess_threshold: float | None = None,
    driver_share_rate: float | None = None,
) -> dict[str, float]:
    cur = load_settings()
    if hourly_wage is not None:
        cur["hourly_wage"] = float(hourly_wage)
    if excess_threshold is not None:
        cur["excess_threshold"] = float(excess_threshold)
    if driver_share_rate is not None:
        rate = float(driver_share_rate)
        if rate > 1:
            rate = rate / 100.0
        cur["driver_share_rate"] = max(0.0, min(1.0, rate))
    _settings_path().write_text(
        json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cur


def excess_payout(revenue: float, settings: dict[str, float] | None = None) -> float:
    """(X - 기준) * 지급비율, 기준 미만이면 0."""
    s = settings or load_settings()
    x = float(revenue or 0)
    thr = float(s.get("excess_threshold") or 0)
    rate = float(s.get("driver_share_rate") or 0)
    if x <= thr:
        return 0.0
    return (x - thr) * rate


def company_cut(revenue: float, settings: dict[str, float] | None = None) -> float:
    """초과분에서 회사가 떼는 금액."""
    s = settings or load_settings()
    x = float(revenue or 0)
    thr = float(s.get("excess_threshold") or 0)
    rate = float(s.get("driver_share_rate") or 0)
    if x <= thr:
        return 0.0
    return (x - thr) * (1.0 - rate)


def snapshot_dict(settings: dict[str, float] | None = None) -> dict[str, float]:
    s = settings or load_settings()
    return {
        "hourly_wage": float(s.get("hourly_wage") or 0),
        "excess_threshold": float(s.get("excess_threshold") or 0),
        "driver_share_rate": float(s.get("driver_share_rate") or 0),
    }


def get_month_rates(year: int, month: int) -> dict[str, float]:
    """해당 월 스냅샷이 있으면 사용, 없으면 현재 설정."""
    meta = load_month_meta().get(month_key(year, month)) or {}
    snap = meta.get("wage_snapshot")
    if isinstance(snap, dict) and snap:
        out = dict(DEFAULT_SETTINGS)
        for k in DEFAULT_SETTINGS:
            if k in snap and snap[k] is not None:
                try:
                    out[k] = float(snap[k])
                except (TypeError, ValueError):
                    pass
        return out
    return load_settings()


def save_month_snapshot(year: int, month: int, settings: dict[str, float] | None = None) -> None:
    data = load_month_meta()
    key = month_key(year, month)
    item = dict(data.get(key) or {})
    item["wage_snapshot"] = snapshot_dict(settings)
    data[key] = item
    save_month_meta(data)


def get_plate_revenues(year: int, month: int) -> dict[str, float]:
    meta = load_month_meta().get(month_key(year, month)) or {}
    raw = meta.get("by_plate") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[_norm_plate(k)] = float(v or 0)
        except (TypeError, ValueError):
            continue
    return out


def set_plate_revenues(year: int, month: int, by_plate: dict[str, float]) -> None:
    data = load_month_meta()
    key = month_key(year, month)
    item = dict(data.get(key) or {})
    clean = {_norm_plate(k): float(v or 0) for k, v in by_plate.items() if _norm_plate(k)}
    item["by_plate"] = clean
    item["revenue_total"] = float(sum(clean.values()))
    data[key] = item
    save_month_meta(data)


def lookup_plate_revenue(plate: str, by_plate: dict[str, float]) -> float:
    target = _norm_plate(plate)
    if not target:
        return 0.0
    if target in by_plate:
        return float(by_plate[target])
    for k, v in by_plate.items():
        if target.endswith(k) or k.endswith(target) or target in k or k in target:
            return float(v)
    return 0.0


def save_revenues_from_agg(agg: pd.DataFrame, *, snapshot_wage: bool = True) -> dict[str, Any]:
    """
    Teams 집계(business_date, plate, revenue) → 월·차번별 합 저장.
    반환: { '2026-09': {'total': ..., 'plates': n}, ... }
    """
    if agg is None or agg.empty:
        return {}
    work = agg.copy()
    work["_ym"] = work["business_date"].map(
        lambda d: month_key(int(d.year), int(d.month)) if hasattr(d, "year") else ""
    )
    work["_plate"] = work["plate"].map(_norm_plate)
    result: dict[str, Any] = {}
    settings = load_settings()
    for ym, g in work.groupby("_ym"):
        if not ym:
            continue
        y, m = int(ym[:4]), int(ym[5:7])
        by_plate = (
            g.groupby("_plate", as_index=True)["revenue"].sum().astype(float).to_dict()
        )
        by_plate = {k: float(v) for k, v in by_plate.items() if k}
        set_plate_revenues(y, m, by_plate)
        if snapshot_wage:
            save_month_snapshot(y, m, settings)
        result[ym] = {"total": float(sum(by_plate.values())), "plates": len(by_plate)}
    return result


def attach_revenue_columns(
    df: pd.DataFrame,
    year: int,
    month: int,
) -> pd.DataFrame:
    """배차일지 df에 당월수익·초과지급 열 추가 (표시용)."""
    out = df.copy()
    by_plate = get_plate_revenues(year, month)
    rates = get_month_rates(year, month)
    revenues: list[float] = []
    payouts: list[float] = []
    for _, row in out.iterrows():
        plate = str(row.get("차번") or "")
        rev = lookup_plate_revenue(plate, by_plate)
        revenues.append(rev)
        payouts.append(excess_payout(rev, rates))
    out["당월수익"] = revenues
    out["초과지급"] = payouts
    return out


def rates_caption(year: int, month: int) -> str:
    r = get_month_rates(year, month)
    share_pct = float(r["driver_share_rate"]) * 100
    cut_pct = 100 - share_pct
    return (
        f"적용 요율({year}-{month:02d}): 시급 {r['hourly_wage']:,.0f}원 · "
        f"초과기준 {r['excess_threshold']:,.0f}원 · "
        f"초과분 기사 {share_pct:g}% / 공제 {cut_pct:g}%"
    )
