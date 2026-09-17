# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — TaxiApp onedir (Streamlit + pandas/numpy 완전 수집)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

block_cipher = None
root = Path(SPECPATH)

datas = [
    (str(root / "app.py"), "."),
    (str(root / "modules"), "modules"),
    (str(root / ".streamlit"), ".streamlit"),
]
binaries = []
hiddenimports = [
    "streamlit",
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "pandas",
    "pandas._libs",
    "pandas._libs._cyutility",
    "pandas._libs.interval",
    "pandas._libs.hashtable",
    "pandas._libs.missing",
    "pandas._libs.algos",
    "pandas._libs.ops",
    "pandas._libs.lib",
    "pandas._libs.tslibs",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.timestamps",
    "pandas._libs.tslibs.timezones",
    "pandas._libs.tslibs.fields",
    "pandas._libs.tslibs.dtypes",
    "pandas._libs.tslibs.ccalendar",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.offsets",
    "pandas._libs.tslibs.parsing",
    "pandas._libs.tslibs.period",
    "pandas._libs.tslibs.strptime",
    "pandas._libs.tslibs.vectorized",
    "numpy",
    "numpy.core",
    "numpy.linalg",
    "numpy.linalg._umath_linalg",
    "openpyxl",
    "pypdf",
    "plotly",
    "pystray",
    "PIL",
    "pytesseract",
    "pdf2image",
    "google.generativeai",
    "requests",
    "modules",
    "modules.paths",
    "modules.doc_manager",
    "modules.excel_agent",
    "modules.analyzer",
    "modules.mapping",
    "modules.ocr_utils",
    "modules.gemini_llm",
    "modules.ai_client",
    "modules.master_data",
    "modules.dispatch_log",
    "modules.dispatch_export",
    "modules.business_day",
    "modules.revenue_import",
    "modules.wage_settings",
    "modules.plate_utils",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
]

# pandas / numpy / streamlit 등 전체 수집
for pkg in (
    "pandas",
    "numpy",
    "streamlit",
    "altair",
    "pydeck",
    "jsonschema",
    "openpyxl",
    "google.generativeai",
    "google.ai.generativelanguage",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# pandas._libs 하위 모듈 전부 수집 (_cyutility 포함)
try:
    hiddenimports += collect_submodules("pandas._libs")
except Exception:
    pass
try:
    hiddenimports += collect_submodules("numpy")
except Exception:
    pass

for meta_pkg in (
    "streamlit",
    "altair",
    "pydeck",
    "jsonschema",
    "google-generativeai",
    "protobuf",
    "packaging",
    "click",
    "tornado",
    "watchdog",
    "pandas",
    "numpy",
    "pillow",
    "blinker",
    "cachetools",
    "tenacity",
    "toml",
    "typing-extensions",
    "gitpython",
    "pyarrow",
    "rich",
    "markdown-it-py",
    "mdurl",
    "Pygments",
    "smmap",
    "gitdb",
    "openpyxl",
    "et-xmlfile",
):
    try:
        datas += copy_metadata(meta_pkg)
    except Exception:
        pass

# 중복 제거 (순서 유지)
_seen = set()
_unique_hidden = []
for name in hiddenimports:
    if name not in _seen:
        _seen.add(name)
        _unique_hidden.append(name)
hiddenimports = _unique_hidden

a = Analysis(
    ["launcher.py"],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TaxiApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # pandas/numpy 바이너리 깨짐 방지
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TaxiApp",
)
