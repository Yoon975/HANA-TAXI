"""
기사·차량 마스터 데이터.
저장: 문서\\택시자동화\\_config\\vehicles.json, drivers.json
채팅으로 추가/수정/삭제 계획 → 미리보기 후 적용.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.ai_client import DEFAULT_MODEL, has_api_key, invoke_llm
from modules.paths import CONFIG_DIR, ensure_storage

VEHICLES_FILE = "vehicles.json"
DRIVERS_FILE = "drivers.json"


def _vehicles_path() -> Path:
    ensure_storage()
    return CONFIG_DIR / VEHICLES_FILE


def _drivers_path() -> Path:
    ensure_storage()
    return CONFIG_DIR / DRIVERS_FILE


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _norm_plate(plate: str) -> str:
    return re.sub(r"\s+", "", (plate or "").strip()).upper()


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip())


def load_vehicles() -> list[dict[str, Any]]:
    path = _vehicles_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = list(data) if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []
    return [_normalize_vehicle(v) for v in items]


def save_vehicles(items: list[dict[str, Any]]) -> Path:
    path = _vehicles_path()
    cleaned = [_normalize_vehicle(v) for v in items]
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_drivers() -> list[dict[str, Any]]:
    path = _drivers_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = list(data) if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []
    return [_normalize_driver(d) for d in items]


def save_drivers(items: list[dict[str, Any]]) -> Path:
    path = _drivers_path()
    cleaned = [_normalize_driver(d) for d in items]
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _normalize_vehicle(v: dict[str, Any]) -> dict[str, Any]:
    """차량: 차번·차종·상태메모. 담당기사 필드는 제거."""
    out = {
        "id": str(v.get("id") or _new_id()),
        "plate": str(v.get("plate") or "").strip(),
        "vehicle_type": str(v.get("vehicle_type") or v.get("type") or ""),
        "note": str(v.get("note") or ""),
        "updated_at": str(v.get("updated_at") or ""),
    }
    return out


def _normalize_driver(d: dict[str, Any]) -> dict[str, Any]:
    """기사: 배정차량·변동사항·특이사항."""
    changes = str(d.get("changes") or "")
    note = str(d.get("note") or "")
    # 예전 note에 [배정]만 있던 경우 변동사항으로 분리
    if not changes and "[배정]" in note:
        change_lines = []
        other_lines = []
        for line in note.splitlines():
            if "[배정]" in line:
                change_lines.append(line.strip())
            elif line.strip():
                other_lines.append(line.strip())
        changes = "\n".join(change_lines)
        note = "\n".join(other_lines)
    return {
        "id": str(d.get("id") or _new_id()),
        "name": str(d.get("name") or "").strip(),
        "phone": str(d.get("phone") or ""),
        "assigned_plate": str(
            d.get("assigned_plate") or d.get("plate") or ""
        ).strip(),
        "changes": changes,
        "note": note,
        "updated_at": str(d.get("updated_at") or ""),
    }


def migrate_master_schema() -> list[str]:
    """
    차량.driver_name → 기사.assigned_plate 로 이전.
    차량에서 담당기사 필드 제거. 앱 시작·로드 시 호출.
    """
    msgs: list[str] = []
    raw_v_path = _vehicles_path()
    raw_d_path = _drivers_path()
    vehicles_raw: list[dict[str, Any]] = []
    drivers_raw: list[dict[str, Any]] = []
    if raw_v_path.exists():
        try:
            data = json.loads(raw_v_path.read_text(encoding="utf-8"))
            vehicles_raw = list(data) if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            vehicles_raw = []
    if raw_d_path.exists():
        try:
            data = json.loads(raw_d_path.read_text(encoding="utf-8"))
            drivers_raw = list(data) if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            drivers_raw = []

    drivers = [_normalize_driver(d) for d in drivers_raw]
    changed = False

    for v in vehicles_raw:
        dname = str(v.get("driver_name") or "").strip()
        plate = str(v.get("plate") or "").strip()
        if not dname or not plate:
            if "driver_name" in v:
                changed = True
            continue
        idx = _find_driver(drivers, {"name": dname})
        if idx is None:
            drivers.append(
                _normalize_driver(
                    {
                        "id": _new_id(),
                        "name": dname,
                        "assigned_plate": plate,
                        "phone": "",
                        "changes": "",
                        "note": "",
                        "updated_at": _now(),
                    }
                )
            )
            msgs.append(f"마이그레이션: 기사 추가 {dname} ← {plate}")
            changed = True
        else:
            cur = str(drivers[idx].get("assigned_plate") or "").strip()
            if not cur:
                drivers[idx]["assigned_plate"] = plate
                drivers[idx]["updated_at"] = _now()
                msgs.append(f"마이그레이션: {dname} 배정차량={plate}")
                changed = True
            elif _norm_plate(cur) != _norm_plate(plate):
                # 이미 다른 차가 있으면 차량 쪽 담당은 버리고 기사 배정 유지
                msgs.append(
                    f"마이그레이션 건너뜀: {dname} 이미 {cur} 배정 (차량 {plate} 무시)"
                )
        if "driver_name" in v:
            changed = True

    vehicles = [_normalize_vehicle(v) for v in vehicles_raw]
    # 1차 1기사: 같은 배정차량이 여러 기사면 마지막만 유지
    seen_plates: dict[str, int] = {}
    for i, d in enumerate(drivers):
        p = _norm_plate(d.get("assigned_plate") or "")
        if not p:
            continue
        if p in seen_plates:
            drivers[seen_plates[p]]["assigned_plate"] = ""
            changed = True
        seen_plates[p] = i

    if changed or any("driver_name" in v for v in vehicles_raw):
        save_vehicles(vehicles)
        save_drivers(drivers)
        if not msgs:
            msgs.append("마스터 스키마 정리 완료 (차량 담당기사 → 기사 배정차량)")
    return msgs


def plate_to_driver_name() -> dict[str, str]:
    """정규화 차번 → 기사 이름 (현재 배정)."""
    out: dict[str, str] = {}
    for d in load_drivers():
        p = _norm_plate(d.get("assigned_plate") or "")
        name = str(d.get("name") or "").strip()
        if p and name:
            out[p] = name
    return out


def driver_name_to_plate() -> dict[str, str]:
    """정규화 이름 → 배정 차번."""
    out: dict[str, str] = {}
    for d in load_drivers():
        name = _norm_name(d.get("name") or "")
        plate = str(d.get("assigned_plate") or "").strip()
        if name and plate:
            out[name] = plate
    return out


def master_summary_text() -> str:
    migrate_master_schema()
    vehicles = load_vehicles()
    drivers = load_drivers()
    v_lines = [
        f"- {v.get('plate','')} (id={v.get('id','')}"
        + (f", 차종={v.get('vehicle_type')}" if v.get("vehicle_type") else "")
        + (f", 상태={v.get('note')}" if v.get("note") else "")
        + ")"
        for v in vehicles
    ] or ["- (없음)"]
    d_lines = [
        f"- {d.get('name','')} (id={d.get('id','')}"
        + (f", 전화={d.get('phone')}" if d.get("phone") else "")
        + (f", 배정차량={d.get('assigned_plate')}" if d.get("assigned_plate") else "")
        + (f", 변동={d.get('changes')}" if d.get("changes") else "")
        + (f", 특이={d.get('note')}" if d.get("note") else "")
        + ")"
        for d in drivers
    ] or ["- (없음)"]
    return (
        "등록 차량 (상태메모만, 담당기사는 기사쪽에):\n"
        + "\n".join(v_lines)
        + "\n등록 기사 (배정차량·변동사항·특이사항):\n"
        + "\n".join(d_lines)
    )


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise ValueError("LLM 응답에서 JSON을 찾지 못했습니다.")
        return json.loads(m.group(0))


def interpret_user_message(user_command: str, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """
    사용자 말을 해석.
    반환: {
      mode: "master_ops" | "doc_draft" | "dispatch_ops" | "chat",
      reply, ops, doc, year, month, dispatch_ops
    }
    """
    if not has_api_key():
        raise RuntimeError("Gemini API 키가 없습니다.")

    summary = master_summary_text()
    now = datetime.now()
    prompt = f"""당신은 택시 회사 업무 도우미입니다.
반드시 JSON만 출력하세요.

오늘(참고): {now.year}-{now.month:02d}-{now.day:02d}
현재 등록 차량·기사:
{summary}

사용자 말: {user_command}

판단 규칙 (우선순위):
1) 차량/기사 마스터 등록·추가·수정·삭제·이름·번호·차종·배정·상태 변경 → mode="master_ops"
   - 차량: 차번·차종·상태메모(고장 등). 담당기사는 차량에 두지 않음.
   - 기사: 이름·전화·배정차량(assigned_plate)·변동사항(changes)·특이사항(note)
   - 대차/배정 변경: 기사 entity update 로 assigned_plate 변경, changes에
     "[배정] YYYY-MM-DD 이전차→이후차" 한 줄 추가
2) 공문·안내문·공고 초안/작성 → mode="doc_draft" (title, body)
3) 배차일지 작성·기입·근무표시·성명 지정·월 일지 만들기 → mode="dispatch_ops"
   - year, month 필수 (언급 없으면 오늘 연월)
   - dispatch_ops 배열:
     ensure_month | add_row | set_driver | set_type | set_day | set_days | clear_day
   - set_day/set_days: day(s)는 1~31, value 기본 "1", 퇴사면 value="퇴사"
   - plate는 차번 (예: 9801)
4) 그 외 → mode="chat"
- 확신이 없으면 mode="chat"
- 저장은 앱에서 미리보기 후 적용. 이미 저장됐다고 쓰지 마세요.

JSON 스키마:
{{
  "mode": "master_ops" | "doc_draft" | "dispatch_ops" | "chat",
  "reply": "짧은 한국어 설명",
  "year": {now.year},
  "month": {now.month},
  "ops": [
    {{
      "entity": "vehicle" | "driver",
      "action": "add" | "update" | "delete",
      "match": {{"id": "", "plate": "", "name": ""}},
      "set": {{"plate": "", "name": "", "phone": "", "note": "", "vehicle_type": "", "assigned_plate": "", "changes": ""}}
    }}
  ],
  "doc": {{"title": "", "body": ""}},
  "dispatch_ops": [
    {{
      "action": "ensure_month|add_row|set_driver|set_type|set_day|set_days|clear_day",
      "plate": "",
      "name": "",
      "vehicle_type": "",
      "day": 1,
      "days": [1, 2],
      "value": "1"
    }}
  ]
}}
"""
    raw = invoke_llm(prompt, model=model)
    data = _extract_json(raw)
    mode = (data.get("mode") or "chat").strip().lower()
    if mode not in ("master_ops", "doc_draft", "dispatch_ops", "chat"):
        mode = "chat"
    ops = data.get("ops") if isinstance(data.get("ops"), list) else []
    doc = data.get("doc") if isinstance(data.get("doc"), dict) else {}
    dispatch_ops = data.get("dispatch_ops") if isinstance(data.get("dispatch_ops"), list) else []
    reply = (data.get("reply") or "").strip()

    try:
        year = int(data.get("year") or now.year)
        month = int(data.get("month") or now.month)
    except (TypeError, ValueError):
        year, month = now.year, now.month
    if month < 1 or month > 12:
        month = now.month

    if mode == "master_ops" and not ops:
        mode = "chat"
    if mode == "dispatch_ops":
        if not dispatch_ops:
            dispatch_ops = [{"action": "ensure_month"}]
        if not reply:
            reply = f"{year}년 {month}월 배차일지 변경 미리보기입니다."
    if mode == "doc_draft":
        title = str(doc.get("title") or "").strip()
        body = str(doc.get("body") or "").strip()
        if not body:
            mode = "chat"
            reply = reply or "공문 본문을 만들지 못했습니다. 다시 요청해 주세요."
        else:
            if not title:
                title = "AI작성_공문"
            if not reply:
                reply = "공문 초안입니다. 아래에서 수정한 뒤 저장하세요."
            doc = {"title": title, "body": body}

    if not reply:
        reply = {
            "master_ops": "마스터 변경 미리보기입니다.",
            "doc_draft": "공문 초안입니다.",
            "dispatch_ops": "배차일지 변경 미리보기입니다.",
        }.get(mode, "요청을 확인했습니다.")

    return {
        "mode": mode,
        "reply": reply,
        "ops": ops,
        "doc": doc if mode == "doc_draft" else None,
        "year": year,
        "month": month,
        "dispatch_ops": dispatch_ops if mode == "dispatch_ops" else [],
    }


def describe_ops(ops: list[dict[str, Any]]) -> list[dict[str, str]]:
    """UI 미리보기용 행 목록."""
    rows: list[dict[str, str]] = []
    for op in ops:
        entity = "차량" if op.get("entity") == "vehicle" else "기사"
        action_map = {"add": "추가", "update": "수정", "delete": "삭제"}
        action = action_map.get((op.get("action") or "").lower(), op.get("action") or "")
        match = op.get("match") or {}
        aset = op.get("set") or {}
        target = (
            match.get("plate")
            or match.get("name")
            or match.get("id")
            or aset.get("plate")
            or aset.get("name")
            or "-"
        )
        detail = ", ".join(f"{k}={v}" for k, v in aset.items() if v not in (None, ""))
        rows.append(
            {
                "대상": entity,
                "동작": action,
                "식별": str(target),
                "변경내용": detail or "(삭제/없음)",
            }
        )
    return rows


def _find_vehicle(items: list[dict[str, Any]], match: dict[str, Any]) -> int | None:
    mid = (match.get("id") or "").strip()
    plate = _norm_plate(match.get("plate") or "")
    for i, v in enumerate(items):
        if mid and v.get("id") == mid:
            return i
        if plate and _norm_plate(str(v.get("plate", ""))) == plate:
            return i
    return None


def _find_driver(items: list[dict[str, Any]], match: dict[str, Any]) -> int | None:
    mid = (match.get("id") or "").strip()
    name = _norm_name(match.get("name") or "")
    for i, d in enumerate(items):
        if mid and d.get("id") == mid:
            return i
        if name and _norm_name(str(d.get("name", ""))) == name:
            return i
    # 부분 일치 (한 명만)
    if name:
        hits = [i for i, d in enumerate(items) if name in _norm_name(str(d.get("name", "")))]
        if len(hits) == 1:
            return hits[0]
    return None


def apply_ops(ops: list[dict[str, Any]]) -> list[str]:
    """ops 적용 후 결과 메시지 목록."""
    migrate_master_schema()
    vehicles = load_vehicles()
    drivers = load_drivers()
    results: list[str] = []

    def _clear_plate_from_other_drivers(plate: str, keep_idx: int | None) -> None:
        target = _norm_plate(plate)
        if not target:
            return
        for i, d in enumerate(drivers):
            if keep_idx is not None and i == keep_idx:
                continue
            if _norm_plate(str(d.get("assigned_plate") or "")) == target:
                drivers[i]["assigned_plate"] = ""

    for op in ops:
        entity = (op.get("entity") or "").lower()
        action = (op.get("action") or "").lower()
        match = op.get("match") or {}
        aset = {k: v for k, v in (op.get("set") or {}).items() if v not in (None, "")}

        # 예전: 차량에 담당기사 지정 → 기사 배정차량으로 변환
        if entity == "vehicle" and "driver_name" in aset:
            dname = str(aset.get("driver_name") or "").strip()
            plate = str(aset.get("plate") or match.get("plate") or "").strip()
            if not plate:
                idx_v = _find_vehicle(vehicles, match)
                if idx_v is not None:
                    plate = str(vehicles[idx_v].get("plate") or "")
            if dname and plate:
                entity = "driver"
                action = (
                    "update"
                    if _find_driver(drivers, {"name": dname}) is not None
                    else "add"
                )
                match = {"name": dname}
                aset = {"name": dname, "assigned_plate": plate}
                results.append(f"(변환) 차량 담당기사 → 기사 배정: {dname}={plate}")
            else:
                aset.pop("driver_name", None)

        if entity == "vehicle":
            if action == "add":
                plate = aset.get("plate") or match.get("plate")
                if not plate:
                    results.append("차량 추가 실패: 차량번호 없음")
                    continue
                if _find_vehicle(vehicles, {"plate": plate}) is not None:
                    results.append(f"차량 추가 건너뜀(이미 있음): {plate}")
                    continue
                vehicles.append(
                    _normalize_vehicle(
                        {
                            "id": _new_id(),
                            "plate": str(plate).strip(),
                            "vehicle_type": str(aset.get("vehicle_type") or ""),
                            "note": str(aset.get("note") or ""),
                            "updated_at": _now(),
                        }
                    )
                )
                results.append(f"차량 추가: {plate}")
            elif action == "update":
                idx = _find_vehicle(vehicles, match) or _find_vehicle(
                    vehicles, {"plate": aset.get("plate")}
                )
                if idx is None:
                    results.append(f"차량 수정 실패(없음): {match}")
                    continue
                if "plate" in aset:
                    vehicles[idx]["plate"] = str(aset["plate"]).strip()
                if "vehicle_type" in aset:
                    vehicles[idx]["vehicle_type"] = str(aset["vehicle_type"])
                if "note" in aset:
                    vehicles[idx]["note"] = str(aset["note"])
                vehicles[idx]["updated_at"] = _now()
                results.append(f"차량 수정: {vehicles[idx].get('plate')}")
            elif action == "delete":
                idx = _find_vehicle(vehicles, match)
                if idx is None:
                    results.append(f"차량 삭제 실패(없음): {match}")
                    continue
                removed = vehicles.pop(idx)
                results.append(f"차량 삭제: {removed.get('plate')}")
            else:
                results.append(f"알 수 없는 차량 동작: {action}")

        elif entity == "driver":
            if action == "add":
                name = aset.get("name") or match.get("name")
                if not name:
                    results.append("기사 추가 실패: 이름 없음")
                    continue
                if _find_driver(drivers, {"name": name}) is not None:
                    results.append(f"기사 추가 건너뜀(이미 있음): {name}")
                    continue
                plate = str(aset.get("assigned_plate") or aset.get("plate") or "").strip()
                drivers.append(
                    _normalize_driver(
                        {
                            "id": _new_id(),
                            "name": str(name).strip(),
                            "phone": str(aset.get("phone") or ""),
                            "assigned_plate": plate,
                            "changes": str(aset.get("changes") or ""),
                            "note": str(aset.get("note") or ""),
                            "updated_at": _now(),
                        }
                    )
                )
                if plate:
                    _clear_plate_from_other_drivers(plate, len(drivers) - 1)
                results.append(f"기사 추가: {name}" + (f" / 배정 {plate}" if plate else ""))
            elif action == "update":
                idx = _find_driver(drivers, match) or _find_driver(
                    drivers, {"name": aset.get("name")}
                )
                if idx is None:
                    results.append(f"기사 수정 실패(없음): {match}")
                    continue
                if "name" in aset:
                    drivers[idx]["name"] = str(aset["name"]).strip()
                if "phone" in aset:
                    drivers[idx]["phone"] = str(aset["phone"])
                if "assigned_plate" in aset or "plate" in aset:
                    plate = str(aset.get("assigned_plate") or aset.get("plate") or "").strip()
                    old_plate = str(drivers[idx].get("assigned_plate") or "").strip()
                    drivers[idx]["assigned_plate"] = plate
                    if plate:
                        _clear_plate_from_other_drivers(plate, idx)
                    # 배정 변경 시 변동사항에 [배정] 자동 추가 (changes에 직접 안 넣은 경우)
                    if (
                        old_plate
                        and plate
                        and _norm_plate(old_plate) != _norm_plate(plate)
                        and "changes" not in aset
                    ):
                        today = datetime.now().strftime("%Y-%m-%d")
                        line = f"[배정] {today} {old_plate}→{plate}"
                        prev = str(drivers[idx].get("changes") or "").strip()
                        drivers[idx]["changes"] = (prev + "\n" + line).strip() if prev else line
                if "changes" in aset:
                    drivers[idx]["changes"] = str(aset["changes"])
                if "note" in aset:
                    drivers[idx]["note"] = str(aset["note"])
                drivers[idx]["updated_at"] = _now()
                results.append(
                    f"기사 수정: {drivers[idx].get('name')}"
                    + (
                        f" / 배정 {drivers[idx].get('assigned_plate')}"
                        if drivers[idx].get("assigned_plate")
                        else ""
                    )
                )
            elif action == "delete":
                idx = _find_driver(drivers, match)
                if idx is None:
                    results.append(f"기사 삭제 실패(없음): {match}")
                    continue
                removed = drivers.pop(idx)
                results.append(f"기사 삭제: {removed.get('name')}")
            else:
                results.append(f"알 수 없는 기사 동작: {action}")
        else:
            results.append(f"알 수 없는 대상: {entity}")

    save_vehicles(vehicles)
    save_drivers(drivers)
    return results
