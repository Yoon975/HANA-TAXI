"""
로컬 OCR 유틸.
- pytesseract + (가능하면) pdf2image
- Tesseract/Poppler 미설치 시 안내 메시지 반환 (앱은 계속 동작)
"""

from __future__ import annotations

from pathlib import Path


def ocr_available() -> tuple[bool, str]:
    """OCR 사용 가능 여부와 안내 문구."""
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError as e:
        return False, f"OCR 패키지 없음: {e}"

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return (
            False,
            "Tesseract OCR 엔진이 없습니다. "
            "https://github.com/UB-Mannheim/tesseract/wiki 에서 설치 후 "
            "PATH에 등록하거나 환경변수 TESSERACT_CMD를 설정하세요. "
            "(한국어: kor 언어팩 권장)",
        )
    return True, "OCR 사용 가능"


def ocr_pdf_pages(pdf_path: str | Path, max_pages: int = 5) -> str:
    """
    PDF 페이지를 이미지로 변환 후 Tesseract OCR.
    poppler(pdf2image) 또는 pypdf 렌더링이 없으면 예외/안내.
    """
    pdf_path = Path(pdf_path)
    ok, msg = ocr_available()
    if not ok:
        return f"[OCR 불가] {msg}"

    import pytesseract
    from PIL import Image

    images: list = []
    # 1) pdf2image + poppler
    try:
        from pdf2image import convert_from_path

        images = convert_from_path(str(pdf_path), first_page=1, last_page=max_pages, dpi=200)
    except Exception as e1:
        # 2) pypage 실패 시 안내
        return (
            f"[OCR 변환 실패] PDF→이미지 변환에 Poppler가 필요할 수 있습니다.\n"
            f"오류: {e1}\n"
            f"(Windows: poppler for Windows 설치 후 PATH 등록)"
        )

    parts: list[str] = []
    for i, img in enumerate(images):
        if not isinstance(img, Image.Image):
            img = Image.fromarray(img)
        try:
            text = pytesseract.image_to_string(img, lang="kor+eng")
        except Exception:
            # kor 없으면 eng만
            try:
                text = pytesseract.image_to_string(img, lang="eng")
            except Exception as e:
                text = f"(페이지 {i + 1} OCR 오류: {e})"
        if text.strip():
            parts.append(f"[OCR 페이지 {i + 1}]\n{text.strip()}")

    return "\n\n".join(parts) if parts else "[OCR] 인식된 텍스트 없음"
