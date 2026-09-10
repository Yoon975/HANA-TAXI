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
        return list(data) if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_vehicles(items: list[dict[str, Any]]) -> Path:
    path = _vehicles_path()
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_drivers() -> list[dict[str, Any]]:
    path = _drivers_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data) if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_drivers(items: list[dict[str, Any]]) -> Path:
    path = _drivers_path()
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def master_summary_text() -> str:
    vehicles = load_vehicles()
    drivers = load_drivers()
    v_lines = [
        f"- {v.get('plate','')} (id={v.get('id','')}"
        + (f", 차종={v.get('vehicle_type')}" if v.get("vehicle_type") else "")
        + (f", 담당기사={v.get('driver_name')}" if v.get("driver_name") else "")
        + (f", 메모={v.get('note')}" if v.get("note") else "")
        + ")"
        for v in vehicles
    ] or ["- (없음)"]
    d_lines = [
        f"- {d.get('name','')} (id={d.get('id','')}"
        + (f", 전화={d.get('phone')}" if d.get("phone") else "")
        + (f", 메모={d.get('note')}" if d.get("note") else "")
        + ")"
        for d in drivers
    ] or ["- (없음)"]
    return (
        "등록 차량:\n"
        + "\n".join(v_lines)
        + "\n등록 기사:\n"
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
1) 차량/기사 마스터 등록·추가·수정·삭제·이름·번호·차종 변경 → mode="master_ops"
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
      "set": {{"plate": "", "name": "", "phone": "", "note": "", "vehicle_type": "", "driver_name": ""}}
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
    vehicles = load_vehicles()
    drivers = load_drivers()
    results: list[str] = []

    for op in ops:
        entity = (op.get("entity") or "").lower()
        action = (op.get("action") or "").lower()
        match = op.get("match") or {}
        aset = {k: v for k, v in (op.get("set") or {}).items() if v not in (None, "")}

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
                    {
                        "id": _new_id(),
                        "plate": str(plate).strip(),
                        "vehicle_type": str(aset.get("vehicle_type") or ""),
                        "driver_name": str(aset.get("driver_name") or aset.get("name") or ""),
                        "note": str(aset.get("note") or ""),
                        "updated_at": _now(),
                    }
                )
                # 1차량 1기사: 같은 기사가 다른 차에 있으면 해제
                dname = vehicles[-1]["driver_name"]
                if dname:
                    for i, v in enumerate(vehicles[:-1]):
                        if _norm_name(str(v.get("driver_name") or "")) == _norm_name(dname):
                            vehicles[i]["driver_name"] = ""
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
                if "driver_name" in aset or "name" in aset:
                    dname = str(aset.get("driver_name") or aset.get("name") or "")
                    vehicles[idx]["driver_name"] = dname
                    if dname:
                        for i, v in enumerate(vehicles):
                            if i == idx:
                                continue
                            if _norm_name(str(v.get("driver_name") or "")) == _norm_name(dname):
                                vehicles[i]["driver_name"] = ""
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
                drivers.append(
                    {
                        "id": _new_id(),
                        "name": str(name).strip(),
                        "phone": str(aset.get("phone") or ""),
                        "note": str(aset.get("note") or ""),
                        "updated_at": _now(),
                    }
                )
                results.append(f"기사 추가: {name}")
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
                if "note" in aset:
                    drivers[idx]["note"] = str(aset["note"])
                drivers[idx]["updated_at"] = _now()
                results.append(f"기사 수정: {drivers[idx].get('name')}")
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
