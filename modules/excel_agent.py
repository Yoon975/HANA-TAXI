"""
Pandas 기반 엑셀 장부 관리 + AI 수정 계획/적용.
미리보기 → 적용, 백업, 되돌리기. 수정본은 새 파일로 저장.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from modules.doc_manager import get_pdf_context_for_agent
from modules.ai_client import DEFAULT_MODEL, has_api_key, invoke_llm
from modules.paths import (
    BACKUP_DIR,
    EXCEL_EDIT,
    EXCEL_ORIG,
    EXCEL_TMPL,
    copy_with_stamp,
    ensure_storage,
    master_pointer_file,
    stamp,
)


def ensure_dirs() -> None:
    ensure_storage()


def get_current_master() -> Path | None:
    ptr = master_pointer_file()
    if not ptr.exists():
        return None
    try:
        p = Path(ptr.read_text(encoding="utf-8").strip())
        return p if p.exists() else None
    except OSError:
        return None


def set_current_master(path: Path) -> None:
    master_pointer_file().write_text(str(path.resolve()), encoding="utf-8")


def save_uploaded_excel(uploaded_file) -> Path:
    """업로드 엑셀을 원본 폴더에 저장하고 현재 마스터로 지정."""
    ensure_storage()
    name = Path(uploaded_file.name).name
    dest = EXCEL_ORIG / f"{stamp()}_{name}"
    try:
        dest.write_bytes(bytes(uploaded_file.getbuffer()))
    except OSError as e:
        raise RuntimeError(f"엑셀 저장 실패: {e}") from e
    set_current_master(dest)
    return dest


def list_excel_files() -> dict[str, list[Path]]:
    ensure_storage()
    return {
        "원본": sorted(EXCEL_ORIG.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True),
        "수정본": sorted(EXCEL_EDIT.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True),
        "템플릿": sorted(EXCEL_TMPL.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True),
        "백업": sorted(BACKUP_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True),
    }


def list_sheet_names(path: Path | None = None) -> list[str]:
    path = path or get_current_master()
    if not path or not path.exists():
        raise FileNotFoundError("마스터 엑셀이 없습니다.")
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        return list(xl.sheet_names)
    except Exception as e:
        raise RuntimeError(f"시트 목록 읽기 실패: {e}") from e


def load_excel(path: Path | None = None, sheet_name: str | int = 0) -> pd.DataFrame:
    path = path or get_current_master()
    if not path or not path.exists():
        raise FileNotFoundError(
            "마스터 엑셀이 없습니다. '엑셀 장부 관리' 탭에서 업로드하거나 템플릿을 만드세요."
        )
    try:
        return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    except Exception as e:
        raise RuntimeError(f"엑셀 읽기 실패: {e}") from e


def backup_current() -> Path | None:
    """현재 마스터를 백업 폴더에 복사."""
    src = get_current_master()
    if not src or not src.exists():
        return None
    return copy_with_stamp(src, BACKUP_DIR, prefix="backup_")


def save_as_edited(df: pd.DataFrame, label: str = "수정") -> Path:
    """수정본 폴더에 새 파일로 저장하고 마스터 포인터 갱신. 저장 전 백업."""
    ensure_storage()
    src = get_current_master()
    if src and src.exists():
        copy_with_stamp(src, BACKUP_DIR, prefix="pre_edit_")

    base = src.stem if src else "ledger"
    # 원본 타임스탬프 접두 제거에 가까운 짧은 이름
    short = re.sub(r"^\d{8}_\d{6}_", "", base)
    dest = EXCEL_EDIT / f"{stamp()}_{label}_{short}.xlsx"
    try:
        df.to_excel(dest, index=False, engine="openpyxl")
    except Exception as e:
        raise RuntimeError(f"수정본 저장 실패: {e}") from e
    set_current_master(dest)
    return dest


def undo_last_backup() -> Path:
    """가장 최근 백업을 수정본으로 복원해 마스터로 지정."""
    ensure_storage()
    backups = sorted(BACKUP_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        raise FileNotFoundError("복구할 백업이 없습니다.")
    latest = backups[0]
    dest = EXCEL_EDIT / f"{stamp()}_되돌리기_{latest.name}"
    shutil.copy2(latest, dest)
    set_current_master(dest)
    return dest


def create_template() -> Path:
    """표준 장부 템플릿 생성."""
    ensure_storage()
    df = pd.DataFrame(
        columns=["날짜", "구분", "매출", "비용", "유가보조금단가", "비고"]
    )
    # 예시 1행
    df.loc[0] = [datetime.now().strftime("%Y-%m-%d"), "운행", 0, 0, 0, "예시행(삭제 가능)"]
    path = EXCEL_TMPL / "장부_템플릿.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    set_current_master(path)
    return path


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


def plan_edit_from_nl(
    user_command: str,
    df: pd.DataFrame,
    model: str = DEFAULT_MODEL,
    use_pdf_context: bool = True,
) -> dict[str, Any]:
    if not has_api_key():
        raise RuntimeError("AI 수정 비활성 — Gemini API 키가 없습니다. 사이드바에서 키를 저장하세요.")

    columns = list(df.columns.astype(str))
    sample = df.head(8).fillna("").astype(str).to_dict(orient="records")
    pdf_ctx = get_pdf_context_for_agent() if use_pdf_context else "(PDF 미사용)"

    prompt = f"""당신은 택시 장부(엑셀) 편집 어시스턴트입니다.
반드시 JSON만 출력하세요. 설명 문장 금지.

컬럼: {columns}
샘플 행(최대 8개): {json.dumps(sample, ensure_ascii=False)}

관련 공문 컨텍스트:
{pdf_ctx}

사용자 명령: {user_command}

규칙:
- action은 update, append, noop 중 하나
- 컬럼명은 위 목록에 있는 이름만 사용
- 숫자는 숫자 타입으로
- 확신이 없으면 action=noop 과 reason 작성
- 유가보조금 단가처럼 공문에 수치가 있으면 그 값을 set_values/new_row에 반영

JSON 스키마:
{{"action":"update|append|noop","reason":"...","filters":{{}},"set_values":{{}},"new_row":{{}}}}
"""
    raw = invoke_llm(prompt, model=model)
    return _extract_json(raw)


def apply_plan(df: pd.DataFrame, plan: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    action = (plan.get("action") or "noop").lower()
    reason = plan.get("reason") or ""
    out = df.copy()

    if action == "noop":
        return out, f"변경 없음: {reason}"

    if action == "update":
        filters = plan.get("filters") or {}
        set_values = plan.get("set_values") or {}
        if not filters or not set_values:
            return out, "update에 filters/set_values가 비어 있습니다."
        mask = pd.Series([True] * len(out))
        for col, val in filters.items():
            if col not in out.columns:
                return out, f"알 수 없는 필터 컬럼: {col}"
            mask &= out[col].astype(str) == str(val)
        matched = int(mask.sum())
        if matched == 0:
            return out, f"조건에 맞는 행이 없습니다. filters={filters}"
        for col, val in set_values.items():
            if col not in out.columns:
                return out, f"알 수 없는 수정 컬럼: {col}"
            out.loc[mask, col] = val
        return out, f"{matched}행 수정. {reason}"

    if action == "append":
        new_row = plan.get("new_row") or {}
        if not new_row:
            return out, "append에 new_row가 비어 있습니다."
        row = {c: new_row.get(c, None) for c in out.columns}
        out = pd.concat([out, pd.DataFrame([row])], ignore_index=True)
        return out, f"1행 추가. {reason}"

    return out, f"지원하지 않는 action: {action}"
