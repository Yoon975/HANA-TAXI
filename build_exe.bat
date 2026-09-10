@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [빌드] Python 3.12 기준 TaxiApp.exe 생성...
where py >nul 2>&1
if errorlevel 1 (
  echo [오류] py 런처가 없습니다. Python 3.12를 설치하세요.
  pause
  exit /b 1
)

py -3.12 -m pip install -r requirements.txt
if errorlevel 1 (
  echo [오류] pip 설치 실패
  pause
  exit /b 1
)

py -3.12 -m PyInstaller --noconfirm TaxiApp.spec
if errorlevel 1 (
  echo [오류] PyInstaller 빌드 실패
  pause
  exit /b 1
)

echo.
echo 완료: dist\TaxiApp\TaxiApp.exe
echo TaxiApp 폴더 전체를 회사 PC에 복사한 뒤 TaxiApp.exe 를 실행하세요.
echo.
pause
endlocal
