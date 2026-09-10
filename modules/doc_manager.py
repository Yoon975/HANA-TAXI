"""
PDF 공문 저장·목록·텍스트 추출·(선택) OCR·Gemini 요약.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from modules.ai_client import DEFAULT_MODEL, has_api_key, invoke_llm, setup_guide_plain
from modules.ocr_utils import ocr_pdf_pages
from modules.paths import PDF_ROOT, ensure_storage, pdf_dest_dir, stamp

META_FILE_NAME = "_meta.json"


def _meta_path() -> Path:
    ensure_storage()
    return PDF_ROOT / META_FILE_NAME


def _load_meta() -> list[dict[str, Any]]:
    path = _meta_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save_meta(items: list[dict[str, Any]]) -> None:
    _meta_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def save_uploaded_pdf(uploaded_file) -> dict[str, Any]:
    """Streamlit UploadedFile 저장 + 메타 기록."""
    from modules.paths import save_bytes

    ensure_storage()
    name = Path(uploaded_file.name).name
    dest_dir = pdf_dest_dir(name)
    path = save_bytes(dest_dir, name, bytes(uploaded_file.getbuffer()))

    record = {
        "id": stamp(),
        "original_name": name,
        "saved_name": path.name,
        "path": str(path),
        "category": dest_dir.name,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "summary": "",
        "file_type": "pdf",
        "source": "upload",
    }
    meta = _load_meta()
    meta.insert(0, record)
    _save_meta(meta)
    return record


def save_text_document(
    title: str,
    body: str,
    *,
    source: str = "ai_chat",
) -> dict[str, Any]:
    """AI/수동 작성 공문을 .txt 로 저장하고 목록(meta)에 추가."""
    ensure_storage()
    title = (title or "").strip() or "무제_공문"
    body = (body or "").strip()
    if not body:
        raise RuntimeError("본문이 비어 있어 저장할 수 없습니다.")

    safe = re.sub(r'[<>:"/\\|?*]', "_", title.strip()) or "무제_공문"
    if not safe.lower().endswith(".txt"):
        fname_base = f"{safe}.txt"
    else:
        fname_base = safe
    dest_dir = pdf_dest_dir(f"{title}.txt")
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{stamp()}_{fname_base}"
    content = f"{title}\n\n{body}\n"
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"공문 저장 실패: {e}") from e

    record = {
        "id": stamp(),
        "original_name": fname_base,
        "saved_name": path.name,
        "path": str(path),
        "category": dest_dir.name,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "summary": "",
        "file_type": "txt",
        "source": source,
        "title": title,
    }
    meta = _load_meta()
    meta.insert(0, record)
    _save_meta(meta)
    return record


def list_pdfs() -> list[dict[str, Any]]:
    return _load_meta()


def extract_text_native(pdf_path: str | Path, max_pages: int = 20) -> str:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"파일 없음: {path}")

    # AI 작성 txt 공문
    if path.suffix.lower() in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise RuntimeError(f"텍스트 공문 읽기 실패: {e}") from e

    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for i, page in enumerate(reader.pages[:max_pages]):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"[페이지 {i + 1}]\n{text}")
        return "\n\n".join(parts).strip()
    except Exception as e:
        raise RuntimeError(f"PDF 텍스트 추출 실패: {e}") from e


def extract_text(pdf_path: str | Path, use_ocr_fallback: bool = True, max_pages: int = 20) -> str:
    """텍스트 추출. 비어 있으면 OCR 시도."""
    native = extract_text_native(pdf_path, max_pages=max_pages)
    if native:
        return native
    if use_ocr_fallback:
        ocr = ocr_pdf_pages(pdf_path, max_pages=min(5, max_pages))
        return ocr or "(추출된 텍스트 없음)"
    return "(추출된 텍스트 없음 — 스캔본일 수 있습니다. OCR을 켜 보세요.)"


def summarize_pdf(pdf_path: str | Path, model: str = DEFAULT_MODEL, update_meta: bool = True) -> str:
    if not has_api_key():
        return f"[AI 요약 비활성] API 키 없음\n\n{setup_guide_plain()}"

    text = extract_text(pdf_path)
    clipped = text[:8000]
    prompt = f"""당신은 택시 사업자용 공문 요약 도우미입니다.
아래 공문에서 한국어로 짧게 정리하세요.
1) 문서 제목/성격
2) 시행일·적용 기간
3) 금액·단가·보조금 등 핵심 수치
4) 사업자가 해야 할 일

공문:
{clipped}
"""
    try:
        summary = invoke_llm(prompt, model=model)
    except Exception as e:
        summary = f"[요약 실패] {e}"

    if update_meta:
        meta = _load_meta()
        target = Path(pdf_path).resolve()
        for item in meta:
            try:
                if Path(item.get("path", "")).resolve() == target:
                    item["summary"] = summary
                    break
            except OSError:
                continue
        _save_meta(meta)
    return summary


def get_latest_pdf() -> dict[str, Any] | None:
    items = list_pdfs()
    return items[0] if items else None


def get_pdf_context_for_agent(max_chars: int = 6000) -> str:
    latest = get_latest_pdf()
    if not latest:
        return "(업로드된 PDF 공문 없음)"
    try:
        text = extract_text(latest["path"])
    except Exception as e:
        text = f"(텍스트 추출 실패: {e})"
    summary = latest.get("summary") or ""
    blob = f"파일: {latest.get('original_name')}\n분류: {latest.get('category')}\n요약:\n{summary}\n\n본문:\n{text}"
    return blob[:max_chars]
