"""
매출/비용 추이 분석 및 로컬 리포트 저장.
컬럼 매핑을 우선 사용합니다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from modules.mapping import missing_roles, resolve_column
from modules.paths import REPORT_ETC, REPORT_MONTHLY, ensure_storage, stamp


def ensure_dirs() -> None:
    ensure_storage()


def _to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def analyze_ledger(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        raise ValueError("분석할 데이터가 비어 있습니다.")

    missing = missing_roles(df.columns, ["date", "revenue", "cost"])
    date_col = resolve_column(df.columns, "date")
    rev_col = resolve_column(df.columns, "revenue")
    cost_col = resolve_column(df.columns, "cost")

    work = df.copy()
    info = {
        "date_col": date_col,
        "revenue_col": rev_col,
        "cost_col": cost_col,
        "missing": missing,
    }

    if missing:
        return {
            "ok": False,
            "summary_text": (
                "분석을 위해 필요한 열을 찾지 못했습니다.\n"
                f"부족: {', '.join(missing)}\n"
                "『컬럼 매핑』에서 날짜·매출·비용 열을 지정해 주세요."
            ),
            "totals": {},
            "monthly": pd.DataFrame(),
            "columns_detected": info,
            "need_mapping": True,
        }

    work["_date"] = pd.to_datetime(work[date_col], errors="coerce")
    work["_revenue"] = _to_number(work[rev_col])
    work["_cost"] = _to_number(work[cost_col])
    work["_profit"] = work["_revenue"].fillna(0) - work["_cost"].fillna(0)

    total_rev = float(work["_revenue"].fillna(0).sum())
    total_cost = float(work["_cost"].fillna(0).sum())
    total_profit = float(work["_profit"].sum())

    monthly = pd.DataFrame()
    if work["_date"].notna().any():
        tmp = work.dropna(subset=["_date"]).copy()
        tmp["년월"] = tmp["_date"].dt.to_period("M").astype(str)
        monthly = (
            tmp.groupby("년월", as_index=False)
            .agg(매출=("_revenue", "sum"), 비용=("_cost", "sum"), 손익=("_profit", "sum"))
            .sort_values("년월")
        )

    lines = [
        f"분석 시각: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"총 행 수: {len(work)}",
        f"감지 컬럼 — 날짜: {date_col}, 매출: {rev_col}, 비용: {cost_col}",
        f"총 매출: {total_rev:,.0f} 원",
        f"총 비용: {total_cost:,.0f} 원",
        f"총 손익: {total_profit:,.0f} 원",
    ]
    if not monthly.empty:
        lines.append("")
        lines.append("[월별 요약]")
        for _, r in monthly.iterrows():
            lines.append(
                f"  {r['년월']}: 매출 {r['매출']:,.0f} / 비용 {r['비용']:,.0f} / 손익 {r['손익']:,.0f}"
            )

    return {
        "ok": True,
        "summary_text": "\n".join(lines),
        "totals": {
            "revenue": total_rev,
            "cost": total_cost,
            "profit": total_profit,
            "rows": len(work),
        },
        "monthly": monthly,
        "columns_detected": info,
        "need_mapping": False,
    }


def save_report(analysis: dict[str, Any], title: str = "장부_분석리포트") -> Path:
    ensure_storage()
    monthly: pd.DataFrame = analysis.get("monthly")
    is_monthly = monthly is not None and not monthly.empty
    dest_dir = REPORT_MONTHLY if is_monthly else REPORT_ETC
    dest_dir.mkdir(parents=True, exist_ok=True)

    ts = stamp()
    txt_path = dest_dir / f"{title}_{ts}.txt"
    try:
        txt_path.write_text(analysis.get("summary_text", ""), encoding="utf-8")
        if is_monthly:
            csv_path = dest_dir / f"{title}_{ts}_monthly.csv"
            monthly.to_csv(csv_path, index=False, encoding="utf-8-sig")
    except OSError as e:
        raise RuntimeError(f"리포트 저장 실패: {e}") from e
    return txt_path


def list_reports() -> list[Path]:
    ensure_storage()
    files: list[Path] = []
    for d in (REPORT_MONTHLY, REPORT_ETC):
        files.extend(d.glob("*.*"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
