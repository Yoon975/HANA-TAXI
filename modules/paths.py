"""
데이터 저장 경로: 문서\\택시자동화\\
파일 종류별 분리 + 이름 키워드로 세부 분류.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

# 문서\\택시자동화
DATA_ROOT = Path.home() / "Documents" / "택시자동화"

PDF_ROOT = DATA_ROOT / "pdf_공문"
EXCEL_ROOT = DATA_ROOT / "excel_장부"
EXCEL_ORIG = EXCEL_ROOT / "원본"
EXCEL_EDIT = EXCEL_ROOT / "수정본"
EXCEL_TMPL = EXCEL_ROOT / "템플릿"
DISPATCH_ROOT = EXCEL_ROOT / "배차일지"
REPORT_ROOT = DATA_ROOT / "analysis_리포트"
REPORT_MONTHLY = REPORT_ROOT / "월별"
REPORT_ETC = REPORT_ROOT / "기타"
CONFIG_DIR = DATA_ROOT / "_config"
BACKUP_DIR = EXCEL_ROOT / "백업"

# PDF 세부 분류 키워드 (파일명에 포함되면 해당 폴더)
PDF_CATEGORIES: dict[str, list[str]] = {
    "유가보조금": ["유가보조금", "유가 보조금", "유류보조금", "유류 보조금", "연료보조금"],
    "운송약관": ["운송약관", "약관", "요금"],
    "세금계산서": ["세금계산서", "계산서", "부가세"],
    "공고_고시": ["공고", "고시", "안내문"],
}

ALL_DIRS = [
    PDF_ROOT,
    EXCEL_ORIG,
    EXCEL_EDIT,
    EXCEL_TMPL,
    DISPATCH_ROOT,
    REPORT_MONTHLY,
    REPORT_ETC,
    CONFIG_DIR,
    BACKUP_DIR,
    *[PDF_ROOT / name for name in list(PDF_CATEGORIES.keys()) + ["기타"]],
]


def ensure_storage() -> Path:
    """필요 폴더를 모두 생성하고 루트를 반환."""
    try:
        for d in ALL_DIRS:
            d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"저장 폴더 생성 실패 ({DATA_ROOT}): {e}") from e
    return DATA_ROOT


def _safe_filename(name: str) -> str:
    name = Path(name).name
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def classify_pdf_category(filename: str) -> str:
    """파일명 키워드로 PDF 세부 폴더명 결정."""
    lower = filename.lower()
    for category, keywords in PDF_CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in lower or kw in filename:
                return category
    return "기타"


def pdf_dest_dir(filename: str) -> Path:
    ensure_storage()
    return PDF_ROOT / classify_pdf_category(filename)


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_bytes(dest_dir: Path, original_name: str, data: bytes, prefix: str = "") -> Path:
    """바이트를 dest_dir에 타임스탬프 파일명으로 저장."""
    ensure_storage()
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(original_name)
    fname = f"{prefix}{stamp()}_{safe}" if prefix else f"{stamp()}_{safe}"
    path = dest_dir / fname
    try:
        path.write_bytes(data)
    except OSError as e:
        raise RuntimeError(f"파일 저장 실패: {path} ({e})") from e
    return path


def copy_with_stamp(src: Path, dest_dir: Path, prefix: str = "") -> Path:
    ensure_storage()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{prefix}{stamp()}_{src.name}"
    try:
        shutil.copy2(src, dest)
    except OSError as e:
        raise RuntimeError(f"파일 복사 실패: {e}") from e
    return dest


def mapping_file() -> Path:
    ensure_storage()
    return CONFIG_DIR / "column_mapping.json"


def master_pointer_file() -> Path:
    """현재 작업 중인 마스터 엑셀 경로를 기록."""
    ensure_storage()
    return CONFIG_DIR / "current_master.txt"
