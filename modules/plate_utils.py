"""차번 정규화 — 공백 제거 후 정확 일치 비교."""

from __future__ import annotations

import re


def norm_plate(plate: str | None) -> str:
    return re.sub(r"\s+", "", str(plate or "")).strip().upper()


def plates_equal(a: str | None, b: str | None) -> bool:
    na, nb = norm_plate(a), norm_plate(b)
    return bool(na) and na == nb
