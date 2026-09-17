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
from modules.plate_utils import norm_plate, plates_equal


class FileLockedError(RuntimeError):
    """엑셀 등에서 파일이 열려 저장할 수 없을 때."""


def _locked_message(path: Path) -> str:
    return (
        f"`{path.name}` 파일이 다른 프로그램(엑셀 등)에서 열려 있어 저장할 수 없습니다. "
        "파일을 닫은 뒤 「다시 저장」을 눌러 주세요."
    )

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
    plate_driver = master_data.plate_to_driver_name()
    rows = []
    for i, v in enumerate(vehicles, start=1):
        plate = str(v.get("plate") or "")
        rows.append(
            _empty_row(
                i,
                plate=plate,
                vtype=str(v.get("vehicle_type") or v.get("type") or ""),
                name=plate_driver.get(norm_plate(plate), ""),
            )
        )
    # 차량 마스터에 없는 배정차량도 행 추가
    known = {norm_plate(r["차번"]) for r in rows}
    for d in master_data.load_drivers():
        plate = str(d.get("assigned_plate") or "").strip()
        name = str(d.get("name") or "").strip()
        if not plate or not name:
            continue
        if norm_plate(plate) in known:
            continue
        rows.append(
            _empty_row(len(rows) + 1, plate=plate, vtype="", name=name)
        )
        known.add(norm_plate(plate))
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
    try:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="배차일지", startrow=1)
            writer.sheets["배차일지"].cell(1, 1, title)
    except PermissionError as e:
        raise FileLockedError(_locked_message(path)) from e
    except OSError as e:
        # Windows에서 잠금이 OSError로 오기도 함
        if getattr(e, "winerror", None) == 32 or "Permission" in str(e) or "denied" in str(e).lower():
            raise FileLockedError(_locked_message(path)) from e
        raise


def save_month(df: pd.DataFrame, year: int, month: int, *, backup: bool = True) -> Path:
    path = month_path(year, month)
    try:
        if backup and path.exists():
            copy_with_stamp(path, BACKUP_DIR, prefix="dispatch_")
        _write_excel(df, path, year, month)
    except FileLockedError:
        raise
    except PermissionError as e:
        raise FileLockedError(_locked_message(path)) from e
    return path


def save_path(df: pd.DataFrame, path: Path, *, backup: bool = True) -> Path:
    ym = parse_year_month_from_name(path)
    if ym:
        year, month = ym
    else:
        now = datetime.now()
        year, month = now.year, now.month
    try:
        if backup and path.exists():
            copy_with_stamp(path, BACKUP_DIR, prefix="dispatch_")
        _write_excel(df, path, year, month)
    except FileLockedError:
        raise
    except PermissionError as e:
        raise FileLockedError(_locked_message(path)) from e
    return path


def _find_row(df: pd.DataFrame, plate: str) -> int | None:
    target = norm_plate(plate)
    if not target:
        return None
    for i, row in df.iterrows():
        if plates_equal(row.get("차번", ""), target):
            return int(i)
    return None


def _has_registered_driver(plate: str, row_name: str = "") -> bool:
    """배차일지 성명 또는 기사 배정차량이 있으면 True."""
    name = str(row_name or "").strip()
    if name and name.lower() not in {"nan", "none"}:
        return True
    target = norm_plate(plate)
    if not target:
        return False
    return bool(master_data.plate_to_driver_name().get(target))


# [배정] YYYY-MM-DD 이전차→이후차  (연도 생략 시 호출 측 year 사용)
_ASSIGN_RE = re.compile(
    r"\[배정\]\s*"
    r"(?:(\d{4})[-./])?(\d{1,2})[-./](\d{1,2})\s+"
    r"([^\s→\-~]+)\s*(?:→|->|➜|⇒)\s*([^\s,，]+)",
)


def parse_assignment_memos(*, default_year: int | None = None) -> list[dict[str, Any]]:
    """기사 변동사항(changes)·특이사항(note)에서 [배정] 줄을 파싱."""
    from datetime import date as date_cls

    items: list[dict[str, Any]] = []
    for d in master_data.load_drivers():
        name = str(d.get("name") or "").strip()
        text = "\n".join(
            [
                str(d.get("changes") or ""),
                str(d.get("note") or ""),
            ]
        )
        if "[배정]" not in text:
            continue
        for m in _ASSIGN_RE.finditer(text):
            y_s, mo_s, d_s, from_p, to_p = m.groups()
            year = int(y_s) if y_s else (default_year or datetime.now().year)
            try:
                dt = date_cls(year, int(mo_s), int(d_s))
            except ValueError:
                continue
            items.append(
                {
                    "date": dt,
                    "from_plate": norm_plate(from_p),
                    "to_plate": norm_plate(to_p),
                    "from_raw": from_p.strip(),
                    "to_raw": to_p.strip(),
                    "source": "driver",
                    "source_id": name,
                    "driver_name": name,
                    "raw": m.group(0).strip(),
                }
            )
    items.sort(key=lambda x: (x["date"], x["from_plate"], x["to_plate"]))
    return items


def list_assignment_changes(year: int, month: int) -> list[str]:
    """해당 월에 걸친 [배정] 요약 문자열."""
    lines: list[str] = []
    for item in parse_assignment_memos(default_year=year):
        dt = item["date"]
        if dt.year != year or dt.month != month:
            continue
        who = item.get("driver_name") or item.get("source_id") or ""
        prefix = f"{who}: " if who else ""
        lines.append(
            f"{dt.month}/{dt.day} {prefix}{item['from_raw']} → {item['to_raw']}"
        )
    return lines


def _master_driver_by_plate() -> dict[str, str]:
    return master_data.plate_to_driver_name()


def _master_type_by_plate() -> dict[str, str]:
    out: dict[str, str] = {}
    for v in master_data.load_vehicles():
        p = norm_plate(v.get("plate"))
        if p:
            out[p] = str(v.get("vehicle_type") or v.get("type") or "").strip()
    return out


def _ensure_plate_row(
    df: pd.DataFrame, plate: str, *, vtype: str = "", name: str = ""
) -> tuple[pd.DataFrame, int]:
    idx = _find_row(df, plate)
    if idx is not None:
        return df, idx
    order = int(df["순서"].max()) + 1 if len(df) else 1
    df = pd.concat(
        [df, pd.DataFrame([_empty_row(order, plate=plate, vtype=vtype, name=name)])],
        ignore_index=True,
    )
    idx = _find_row(df, plate)
    assert idx is not None
    return df, idx


def sync_driver_names_from_master(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """등록 차량 행 + 기사 배정차량 기준 성명 맞추기."""
    out = df.copy()
    msgs: list[str] = []
    plate_driver = _master_driver_by_plate()
    types = _master_type_by_plate()
    vehicle_plates = set(types.keys())

    # 등록 차량 행
    for v in master_data.load_vehicles():
        plate = str(v.get("plate") or "").strip()
        if not plate:
            continue
        key = norm_plate(plate)
        vtype = types.get(key, "")
        name = plate_driver.get(key, "")
        idx = _find_row(out, plate)
        if idx is None:
            order = int(out["순서"].max()) + 1 if len(out) else 1
            out = pd.concat(
                [
                    out,
                    pd.DataFrame(
                        [_empty_row(order, plate=plate, vtype=vtype, name=name)]
                    ),
                ],
                ignore_index=True,
            )
            msgs.append(f"행 추가(마스터): {plate}" + (f" / {name}" if name else ""))
            continue
        if vtype and str(out.at[idx, "차종"] or "") != vtype:
            out.at[idx, "차종"] = vtype
        prev = str(out.at[idx, "성명"] or "").strip()
        if prev != name:
            out.at[idx, "성명"] = name
            msgs.append(f"성명 맞춤: {plate} → {name or '(비움)'}")

    # 배정만 있고 차량 목록에 없는 차
    for key, name in plate_driver.items():
        if _find_row(out, key) is not None:
            continue
        # 표시용 원본 차번
        raw_plate = key
        for d in master_data.load_drivers():
            if norm_plate(d.get("assigned_plate")) == key:
                raw_plate = str(d.get("assigned_plate") or key)
                break
        order = int(out["순서"].max()) + 1 if len(out) else 1
        out = pd.concat(
            [
                out,
                pd.DataFrame(
                    [_empty_row(order, plate=raw_plate, vtype=types.get(key, ""), name=name)]
                ),
            ],
            ignore_index=True,
        )
        msgs.append(f"행 추가(배정): {raw_plate} / {name}")

    # 등록 차량인데 배정 없으면 성명 비움
    for i in list(out.index):
        p = norm_plate(str(out.at[i, "차번"] or ""))
        if p and p in vehicle_plates and p not in plate_driver:
            if str(out.at[i, "성명"] or "").strip():
                out.at[i, "성명"] = ""
                msgs.append(f"성명 비움(배정 없음): {out.at[i, '차번']}")

    return out, msgs


def apply_assignment_memos_to_df(
    df: pd.DataFrame, year: int, month: int
) -> tuple[pd.DataFrame, list[str]]:
    """
    해당 월 기사 변동사항 [배정]을 날짜순 적용.
    이후차에 기사명, 이전차 성명 제거. 일자(1/휴차)는 건드리지 않음.
    """
    out = df.copy()
    msgs: list[str] = []
    drivers_map = _master_driver_by_plate()
    types = _master_type_by_plate()
    memos = [
        m
        for m in parse_assignment_memos(default_year=year)
        if m["date"].year == year and m["date"].month == month
    ]
    for item in memos:
        from_p = item["from_plate"]
        to_p = item["to_plate"]
        if not from_p or not to_p:
            continue
        driver = (
            str(item.get("driver_name") or "").strip()
            or drivers_map.get(to_p)
            or drivers_map.get(from_p)
            or ""
        )
        if not driver:
            fi = _find_row(out, from_p)
            if fi is not None:
                driver = str(out.at[fi, "성명"] or "").strip()
        if not driver:
            ti = _find_row(out, to_p)
            if ti is not None:
                driver = str(out.at[ti, "성명"] or "").strip()
        if not driver:
            msgs.append(
                f"배정 건너뜀(기사 불명): {item['date']} {item['from_raw']}→{item['to_raw']}"
            )
            continue

        out, to_idx = _ensure_plate_row(
            out, item["to_raw"], vtype=types.get(to_p, ""), name=driver
        )
        out.at[to_idx, "성명"] = driver
        if types.get(to_p):
            out.at[to_idx, "차종"] = types[to_p]

        from_idx = _find_row(out, from_p)
        if from_idx is not None:
            cur = str(out.at[from_idx, "성명"] or "").strip()
            if not cur or cur == driver:
                out.at[from_idx, "성명"] = ""

        msgs.append(
            f"배정 반영: {item['date'].month}/{item['date'].day} "
            f"{item['from_raw']}→{item['to_raw']} ({driver})"
        )
    return out, msgs


def sync_assignments(
    df: pd.DataFrame, year: int, month: int
) -> tuple[pd.DataFrame, list[str]]:
    """기사 배정차량 맞춤 → [배정] 변동 → 배정차량 최종 맞춤."""
    msgs: list[str] = []
    out, m1 = sync_driver_names_from_master(df)
    msgs.extend(m1)
    out, m2 = apply_assignment_memos_to_df(out, year, month)
    msgs.extend(m2)
    out, m3 = sync_driver_names_from_master(out)
    for line in m3:
        if line not in msgs:
            msgs.append(line)
    return out, msgs


def apply_assignments_to_month(year: int, month: int) -> list[str]:
    """월 배차일지에 기사 배정·변동사항 반영 후 저장."""
    path = ensure_month(year, month)
    _, df = load_month(year, month)
    df, msgs = sync_assignments(df, year, month)
    try:
        save_month(df, year, month, backup=True)
    except FileLockedError as e:
        return [str(e)]
    if not msgs:
        msgs.append(f"{year}-{month:02d}: 배정 변경 없음 → {path.name}")
    else:
        msgs.append(f"{year}-{month:02d}: 배정 저장 → {path.name}")
    return msgs


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

    TIMS 엑셀에 **나온 영업일** 기준으로:
    - 먼저 기사 배정차량·변동사항 [배정]으로 성명 최신화
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

        # 1) 기사 배정·변동사항 최신화
        df, assign_msgs = sync_assignments(df, year, month)
        results.extend(assign_msgs)

        # 영업일·차번별 수익 맵 (정규화 차번)
        rev_map: dict[tuple[str, int], float] = {}
        days_present: set[int] = set()
        plates_in_agg: set[str] = set()
        for r in rows:
            plate = norm_plate(r["plate"])
            day = int(r["business_date"].day)
            rev = float(r["revenue"])
            if not plate:
                continue
            days_present.add(day)
            plates_in_agg.add(plate)
            key = (plate, day)
            rev_map[key] = rev_map.get(key, 0.0) + rev

        def _rev_for(plate: str, day: int) -> tuple[bool, float]:
            """정확 일치 차번의 해당 일 수익."""
            p = norm_plate(plate)
            direct = rev_map.get((p, day))
            if direct is not None:
                return True, float(direct)
            return False, 0.0

        # 배차일지에 없는 TIMS 차량 행 추가 (기사 있는 경우만)
        for plate in sorted(plates_in_agg):
            if _find_row(df, plate) is not None:
                continue
            if not _has_registered_driver(plate, ""):
                results.append(f"행 추가 건너뜀(기사 미등록): {plate}")
                continue
            order = int(df["순서"].max()) + 1 if len(df) else 1
            vtype = ""
            name = master_data.plate_to_driver_name().get(plate, "")
            for v in master_data.load_vehicles():
                if plates_equal(v.get("plate"), plate):
                    vtype = str(v.get("vehicle_type") or "")
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
            plate = norm_plate(str(df.at[i, "차번"] or ""))
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

        try:
            save_month(df, year, month, backup=True)
        except FileLockedError as e:
            results.append(str(e))
            return results
        results.append(
            f"{year}-{month:02d}: TIMS 영업일 {len(days)}일 · "
            f"갱신 {filled}칸 (근무 {work_count} / 휴차·무운행 {off_count}) · "
            f"기사미등록 건너뜀 {skipped_no_driver}대 → {path.name}"
        )
    return results
