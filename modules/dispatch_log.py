"""
배차일지 — 월별 엑셀 (HWP 양식 대응).
열: 순서, 차번, 차종, 성명, 1~31, 근무일수
저장: 문서\\택시자동화\\excel_장부\\배차일지\\배차일지_YYYY-MM.xlsx
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from modules import master_data
from modules.business_day import business_date, next_month
from modules.paths import BACKUP_DIR, CONFIG_DIR, DISPATCH_ROOT, copy_with_stamp, ensure_storage

FIXED_COLS = ["순서", "차번", "차종", "성명"]
DAY_COLS = [str(i) for i in range(1, 32)]
TAIL_COLS = ["근무일수"]
ALL_COLS = FIXED_COLS + DAY_COLS + TAIL_COLS


def dispatch_dir() -> Path:
    ensure_storage()
    DISPATCH_ROOT.mkdir(parents=True, exist_ok=True)
    return DISPATCH_ROOT


def month_path(year: int, month: int) -> Path:
    return dispatch_dir() / f"배차일지_{year:04d}-{month:02d}.xlsx"


def list_dispatch_files() -> list[Path]:
    return sorted(dispatch_dir().glob("배차일지_*.xlsx"), key=lambda p: p.name, reverse=True)


def parse_year_month_from_name(path: Path) -> tuple[int, int] | None:
    m = re.search(r"배차일지_(\d{4})-(\d{2})", path.name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _empty_row(order: int, plate: str = "", vtype: str = "", name: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {
        "순서": order,
        "차번": plate,
        "차종": vtype,
        "성명": name,
        "근무일수": 0,
    }
    for d in DAY_COLS:
        row[d] = ""
    return row


def _recompute_work_days(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for i in out.index:
        n = 0
        for d in DAY_COLS:
            val = out.at[i, d]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            s = str(val).strip()
            if not s or s.lower() in {"nan", "none"}:
                continue
            if s in {"퇴사", "-", "휴차"}:
                continue
            n += 1
        out.at[i, "근무일수"] = n
    return out


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # 숫자 열명이 1.0 등으로 읽힌 경우 보정
    rename = {}
    for c in list(out.columns):
        s = str(c).strip()
        if re.fullmatch(r"\d+(\.0+)?", s):
            rename[c] = str(int(float(s)))
    if rename:
        out = out.rename(columns=rename)
    for c in ALL_COLS:
        if c not in out.columns:
            out[c] = "" if c not in {"순서", "근무일수"} else 0
    out = out[ALL_COLS]
    out["순서"] = pd.to_numeric(out["순서"], errors="coerce").fillna(0).astype(int)
    for c in ["차번", "차종", "성명"] + DAY_COLS:
        out[c] = out[c].fillna("").astype(str).replace({"nan": "", "None": ""})
    out = _recompute_work_days(out)
    return out


def _read_dispatch_excel(path: Path) -> pd.DataFrame:
    peek = pd.read_excel(path, sheet_name=0, engine="openpyxl", header=None)
    if len(peek) >= 2 and "배차일지" in str(peek.iloc[0, 0]):
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl", header=1)
    else:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")
    return _normalize_df(df)


def create_month_from_master(year: int, month: int, *, overwrite: bool = False) -> Path:
    path = month_path(year, month)
    if path.exists() and not overwrite:
        return path

    vehicles = master_data.load_vehicles()
    rows = [
        _empty_row(
            i,
            plate=str(v.get("plate") or ""),
            vtype=str(v.get("vehicle_type") or v.get("type") or ""),
            name=str(v.get("driver_name") or ""),
        )
        for i, v in enumerate(vehicles, start=1)
    ]
    if not rows:
        rows.append(_empty_row(1))

    df = _normalize_df(pd.DataFrame(rows))
    _write_excel(df, path, year, month)
    return path


def ensure_month(year: int, month: int) -> Path:
    path = month_path(year, month)
    if path.exists():
        return path
    return create_month_from_master(year, month)


def load_month(year: int, month: int) -> tuple[Path, pd.DataFrame]:
    path = ensure_month(year, month)
    return path, _read_dispatch_excel(path)


def load_path(path: Path) -> pd.DataFrame:
    return _read_dispatch_excel(path)


def _write_excel(df: pd.DataFrame, path: Path, year: int, month: int) -> None:
    ensure_storage()
    path.parent.mkdir(parents=True, exist_ok=True)
    last = calendar.monthrange(year, month)[1]
    title = f"배차일지 ({year}년 {month}월 1일 ~ {month}월 {last}일)"
    df = _normalize_df(df).reset_index(drop=True)
    df["순서"] = range(1, len(df) + 1)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="배차일지", startrow=1)
        writer.sheets["배차일지"].cell(1, 1, title)


def save_month(df: pd.DataFrame, year: int, month: int, *, backup: bool = True) -> Path:
    path = month_path(year, month)
    if backup and path.exists():
        copy_with_stamp(path, BACKUP_DIR, prefix="dispatch_")
    _write_excel(df, path, year, month)
    return path


def save_path(df: pd.DataFrame, path: Path, *, backup: bool = True) -> Path:
    ym = parse_year_month_from_name(path)
    if ym:
        year, month = ym
    else:
        now = datetime.now()
        year, month = now.year, now.month
    if backup and path.exists():
        copy_with_stamp(path, BACKUP_DIR, prefix="dispatch_")
    _write_excel(df, path, year, month)
    return path


def _find_row(df: pd.DataFrame, plate: str) -> int | None:
    target = re.sub(r"\s+", "", str(plate or "")).upper()
    if not target:
        return None
    for i, row in df.iterrows():
        p = re.sub(r"\s+", "", str(row.get("차번", ""))).upper()
        if p == target or target in p or p.endswith(target) or target.endswith(p):
            return int(i)
    return None


def _has_registered_driver(plate: str, row_name: str = "") -> bool:
    """배차일지 성명 또는 마스터 담당기사가 있으면 True."""
    name = str(row_name or "").strip()
    if name and name.lower() not in {"nan", "none"}:
        return True
    target = re.sub(r"\s+", "", str(plate or "")).upper()
    if not target:
        return False
    for v in master_data.load_vehicles():
        vp = re.sub(r"\s+", "", str(v.get("plate") or "")).upper()
        if not vp:
            continue
        if vp == target or target in vp or vp.endswith(target) or target.endswith(vp):
            dn = str(v.get("driver_name") or "").strip()
            if dn:
                return True
    return False


def describe_dispatch_ops(ops: list[dict[str, Any]], year: int, month: int) -> list[dict[str, str]]:
    rows = []
    for op in ops:
        action = (op.get("action") or "").lower()
        plate = op.get("plate") or ""
        if action == "ensure_month":
            rows.append({"동작": "월 파일 생성/열기", "차번": "-", "내용": f"{year}-{month:02d}"})
        elif action == "set_driver":
            rows.append({"동작": "성명(기사) 지정", "차번": str(plate), "내용": str(op.get("name") or "")})
        elif action == "set_type":
            rows.append({"동작": "차종 지정", "차번": str(plate), "내용": str(op.get("vehicle_type") or "")})
        elif action == "set_day":
            rows.append(
                {
                    "동작": f"{op.get('day')}일 기입",
                    "차번": str(plate),
                    "내용": str(op.get("value") if op.get("value") is not None else "1"),
                }
            )
        elif action == "set_days":
            days = op.get("days") or []
            rows.append(
                {
                    "동작": "여러 날 기입",
                    "차번": str(plate),
                    "내용": f"일={days} 값={op.get('value', '1')}",
                }
            )
        elif action == "add_row":
            rows.append(
                {
                    "동작": "행 추가",
                    "차번": str(plate),
                    "내용": f"차종={op.get('vehicle_type','')} 성명={op.get('name','')}",
                }
            )
        elif action == "clear_day":
            rows.append({"동작": f"{op.get('day')}일 비우기", "차번": str(plate), "내용": ""})
        else:
            rows.append({"동작": action or "?", "차번": str(plate), "내용": str(op)})
    return rows


def apply_dispatch_ops(
    ops: list[dict[str, Any]],
    year: int,
    month: int,
) -> tuple[Path, list[str]]:
    path = ensure_month(year, month)
    _, df = load_month(year, month)
    results: list[str] = []

    for op in ops:
        action = (op.get("action") or "").lower()
        plate = str(op.get("plate") or "").strip()

        if action == "ensure_month":
            results.append(f"월 파일 준비: {path.name}")
            continue

        if action == "add_row":
            if not plate:
                results.append("행 추가 실패: 차번 없음")
                continue
            if _find_row(df, plate) is not None:
                results.append(f"행 추가 건너뜀(이미 있음): {plate}")
                continue
            order = int(df["순서"].max()) + 1 if len(df) else 1
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        [
                            _empty_row(
                                order,
                                plate=plate,
                                vtype=str(op.get("vehicle_type") or ""),
                                name=str(op.get("name") or ""),
                            )
                        ]
                    ),
                ],
                ignore_index=True,
            )
            results.append(f"행 추가: {plate}")
            continue

        idx = _find_row(df, plate)
        if idx is None and action in {
            "set_driver",
            "set_type",
            "set_day",
            "set_days",
            "clear_day",
        }:
            order = int(df["순서"].max()) + 1 if len(df) else 1
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        [
                            _empty_row(
                                order,
                                plate=plate,
                                vtype=str(op.get("vehicle_type") or ""),
                                name=str(op.get("name") or ""),
                            )
                        ]
                    ),
                ],
                ignore_index=True,
            )
            idx = _find_row(df, plate)
            results.append(f"행 자동 추가: {plate}")

        if idx is None:
            results.append(f"대상 행 없음: {plate}")
            continue

        if action == "set_driver":
            df.at[idx, "성명"] = str(op.get("name") or "")
            results.append(f"{plate} 성명 → {op.get('name')}")
        elif action == "set_type":
            df.at[idx, "차종"] = str(op.get("vehicle_type") or "")
            results.append(f"{plate} 차종 → {op.get('vehicle_type')}")
        elif action == "set_day":
            day = int(op.get("day") or 0)
            if day < 1 or day > 31:
                results.append(f"잘못된 일자: {day}")
                continue
            row_name = str(df.at[idx, "성명"] or "")
            if not _has_registered_driver(plate, row_name):
                results.append(f"{plate} 일자 기입 건너뜀(기사 미등록)")
                continue
            val = op.get("value")
            if val is None or val == "":
                val = "1"
            df.at[idx, str(day)] = str(val)
            results.append(f"{plate} {day}일 ← {val}")
        elif action == "set_days":
            row_name = str(df.at[idx, "성명"] or "")
            if not _has_registered_driver(plate, row_name):
                results.append(f"{plate} 여러 날 기입 건너뜀(기사 미등록)")
                continue
            days = op.get("days") or []
            val = op.get("value")
            if val is None or val == "":
                val = "1"
            for d in days:
                day = int(d)
                if 1 <= day <= 31:
                    df.at[idx, str(day)] = str(val)
            results.append(f"{plate} 여러 날 기입: {days}")
        elif action == "clear_day":
            day = int(op.get("day") or 0)
            if 1 <= day <= 31:
                df.at[idx, str(day)] = ""
                results.append(f"{plate} {day}일 비움")
        else:
            results.append(f"알 수 없는 동작: {action}")

    path = save_month(df, year, month, backup=True)
    return path, results


LAST_BIZ_FILE = "last_business_date.txt"


def _last_biz_path() -> Path:
    ensure_storage()
    return CONFIG_DIR / LAST_BIZ_FILE


def load_last_business_date() -> str:
    path = _last_biz_path()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_last_business_date(d) -> None:
    _last_biz_path().write_text(str(d), encoding="utf-8")


def ensure_current_and_next_months() -> tuple[Path, Path, bool]:
    """
    앱/탭을 열 때 호출: 현재 영업일(06시 기준)로 이번 달·다음 달 파일이
    없으면 생성, 있으면 유지. 영업일이 바뀌었으면 True.
    """
    bd = business_date()
    y, m = bd.year, bd.month
    ny, nm = next_month(y, m)
    p1 = ensure_month(y, m)
    p2 = ensure_month(ny, nm)
    last = load_last_business_date()
    is_new = last != str(bd)
    if is_new:
        save_last_business_date(bd)
    return p1, p2, is_new


def apply_revenue_to_dispatch(
    agg: pd.DataFrame,
    *,
    overwrite_work: bool = True,
) -> list[str]:
    """
    agg: business_date, plate, revenue

    Teams 엑셀에 **나온 영업일** 기준으로:
    - 해당 일·차량 수익 > 0 → '1'
    - 수익 0 이거나 **운행 행이 없음** → '휴차'
    - 기존 '퇴사'는 유지
    - **담당 기사(성명) 미등록 차량은 일자 기입 안 함**

    (엑셀에 아예 안 나온 날짜는 건드리지 않음 — 아직 안 온 날/미포함 구간)
    """
    if agg is None or agg.empty:
        return ["반영할 수익 행이 없습니다."]

    results: list[str] = []
    # 월별로 묶기
    month_rows: dict[tuple[int, int], list] = {}
    for _, r in agg.iterrows():
        bd = r["business_date"]
        if hasattr(bd, "year"):
            key = (int(bd.year), int(bd.month))
        else:
            continue
        month_rows.setdefault(key, []).append(r)

    for (year, month), rows in month_rows.items():
        path = ensure_month(year, month)
        _, df = load_month(year, month)

        # 영업일·차번별 수익 맵 (정규화 차번)
        rev_map: dict[tuple[str, int], float] = {}
        days_present: set[int] = set()
        plates_in_agg: set[str] = set()
        for r in rows:
            plate = re.sub(r"\s+", "", str(r["plate"] or "")).upper()
            day = int(r["business_date"].day)
            rev = float(r["revenue"])
            if not plate:
                continue
            days_present.add(day)
            plates_in_agg.add(plate)
            key = (plate, day)
            rev_map[key] = rev_map.get(key, 0.0) + rev

        def _rev_for(plate: str, day: int) -> tuple[bool, float]:
            """(엑셀에 해당 일 기록 여부, 수익합). 끝자리 매칭 포함."""
            direct = rev_map.get((plate, day))
            if direct is not None:
                return True, float(direct)
            total = 0.0
            found = False
            for (p, d), v in rev_map.items():
                if d != day:
                    continue
                if plate.endswith(p) or p.endswith(plate):
                    total += float(v)
                    found = True
            return found, total

        # 배차일지에 없는 Teams 차량 행 추가 (기사 있는 경우만)
        for plate in sorted(plates_in_agg):
            if _find_row(df, plate) is not None:
                continue
            if not _has_registered_driver(plate, ""):
                results.append(f"행 추가 건너뜀(기사 미등록): {plate}")
                continue
            order = int(df["순서"].max()) + 1 if len(df) else 1
            vtype, name = "", ""
            for v in master_data.load_vehicles():
                vp = re.sub(r"\s+", "", str(v.get("plate") or "")).upper()
                if vp == plate or plate in vp or vp.endswith(plate) or plate.endswith(vp):
                    vtype = str(v.get("vehicle_type") or "")
                    name = str(v.get("driver_name") or "")
                    break
            df = pd.concat(
                [df, pd.DataFrame([_empty_row(order, plate=plate, vtype=vtype, name=name)])],
                ignore_index=True,
            )
            results.append(f"행 추가: {plate}")

        last_day = calendar.monthrange(year, month)[1]
        days = sorted(d for d in days_present if 1 <= d <= last_day)
        filled = 0
        off_count = 0
        work_count = 0
        skipped_no_driver = 0

        for i in list(df.index):
            plate_raw = str(df.at[i, "차번"] or "")
            plate = re.sub(r"\s+", "", plate_raw).upper()
            if not plate:
                continue
            row_name = str(df.at[i, "성명"] or "")
            if not _has_registered_driver(plate, row_name):
                skipped_no_driver += 1
                continue
            for day in days:
                cur = str(df.at[i, str(day)] or "").strip()
                if cur == "퇴사":
                    continue
                _found, rev = _rev_for(plate, day)
                # 엑셀에 없거나 수익 0 → 휴차 (무운행)
                new_val = "1" if rev > 0 else "휴차"
                if not overwrite_work and cur and cur not in {"휴차", ""}:
                    continue
                if cur == new_val:
                    continue
                df.at[i, str(day)] = new_val
                filled += 1
                if new_val == "휴차":
                    off_count += 1
                else:
                    work_count += 1

        save_month(df, year, month, backup=True)
        results.append(
            f"{year}-{month:02d}: Teams 영업일 {len(days)}일 · "
            f"갱신 {filled}칸 (근무 {work_count} / 휴차·무운행 {off_count}) · "
            f"기사미등록 건너뜀 {skipped_no_driver}대 → {path.name}"
        )
    return results
