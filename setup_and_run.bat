@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [개발 실행] Python 3.12로 라이브러리 설치 후 런처 기동...
py -3.12 -m pip install -r requirements.txt
if errorlevel 1 (
  echo [오류] 설치 실패
  pause
  exit /b 1
)

echo 런처를 시작합니다. 종료는 트레이 아이콘에서.
py -3.12 launcher.py
pause
endlocal
