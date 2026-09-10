"""엑셀 컬럼 매핑 저장/로드."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.paths import mapping_file

# 논리 역할 → 실제 엑셀 컬럼명
DEFAULT_ROLES = {
    "date": None,
    "revenue": None,
    "cost": None,
    "fuel_subsidy": None,
    "note": None,
}

ROLE_LABELS = {
    "date": "날짜",
    "revenue": "매출/수입",
    "cost": "비용/지출",
    "fuel_subsidy": "유가보조금(단가)",
    "note": "비고",
}


def load_mapping() -> dict[str, Any]:
    path = mapping_file()
    if not path.exists():
        return dict(DEFAULT_ROLES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out = dict(DEFAULT_ROLES)
        out.update({k: v for k, v in data.items() if k in DEFAULT_ROLES})
        return out
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_ROLES)


def save_mapping(mapping: dict[str, Any]) -> Path:
    path = mapping_file()
    clean = {k: mapping.get(k) for k in DEFAULT_ROLES}
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def resolve_column(df_columns, role: str, mapping: dict[str, Any] | None = None) -> str | None:
    """매핑 우선, 없으면 별칭 추정."""
    import pandas as pd

    mapping = mapping or load_mapping()
    mapped = mapping.get(role)
    cols = [str(c) for c in df_columns]
    if mapped and mapped in cols:
        return mapped

    aliases = {
        "date": ["날짜", "일자", "date", "거래일", "운행일"],
        "revenue": ["매출", "수입", "요금", "revenue", "income", "매출액", "운임"],
        "cost": ["비용", "지출", "원가", "cost", "expense", "유류비", "경비"],
        "fuel_subsidy": ["유가보조금", "유가보조금단가", "보조금단가", "유류보조금"],
        "note": ["비고", "메모", "note", "적요"],
    }
    lower_map = {c.strip().lower(): c for c in cols}
    for a in aliases.get(role, []):
        if a.lower() in lower_map:
            return lower_map[a.lower()]
    for key, orig in lower_map.items():
        for a in aliases.get(role, []):
            if a.lower() in key:
                return orig
    return None


def missing_roles(df_columns, roles: list[str] | None = None) -> list[str]:
    roles = roles or ["date", "revenue", "cost"]
    mapping = load_mapping()
    missing = []
    for r in roles:
        if not resolve_column(df_columns, r, mapping):
            missing.append(ROLE_LABELS.get(r, r))
    return missing
