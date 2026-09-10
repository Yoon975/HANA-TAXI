# HANA-TAXI

택시 회사 업무용 데스크톱 앱 (Streamlit + PyInstaller).  
배차일지·차량/기사 마스터·Teams 수익 반영·공문 초안·AI 채팅을 지원합니다.

## 주요 기능

- **AI 채팅**: 차량·기사 등록, 배차일지 기입, 공문 초안 (미리보기 후 적용)
- **배차일지**: 월별 xlsx, 영업일 06시 기준, 제출용 xlsx/HWP(한글 설치 시)
- **TIMS 수익 엑셀**: 차량별 당월수익·초과지급, 무운행/0원 → 휴차  
  (담당 기사 미등록 차량은 일자 기입 안 함)
- **시급·초과금**: 전원 동일 시급, 월수입 ≥ 기준액 시 `(X−기준)×지급비율` (설정 변경 가능)

## 데이터 위치

프로그램과 데이터가 분리되어 있습니다.

| 구분 | 경로 |
|------|------|
| 프로그램 | `TaxiApp.exe` (배포 폴더) |
| 데이터 | `문서\택시자동화\` |

예: `_config\vehicles.json`, `drivers.json`, `excel_장부\배차일지\`

GitHub에는 **소스만** 포함됩니다. 기사·차량·배차일지 실데이터는 올리지 않습니다.

## 개발 실행

```bat
setup_and_run.bat
```

또는:

```bat
py -3.12 -m pip install -r requirements.txt
py -3.12 -m streamlit run app.py
```

Gemini API 키는 앱 안내에 따라 `문서\택시자동화\_config\`에 저장합니다.

## 실행 파일 빌드

```bat
build_exe.bat
```

결과: `dist\TaxiApp\` 폴더 전체 (exe만 복사하면 안 됨)

## 다른 PC로 옮기기

1. `dist\TaxiApp` 폴더 전체를 압축해 전달
2. 기존 데이터를 쓰려면 `문서\택시자동화`도 함께 복사

## 기술 스택

- Python 3.12, Streamlit, pandas, openpyxl
- Google Gemini (`google-generativeai`)
- PyInstaller (onedir)
