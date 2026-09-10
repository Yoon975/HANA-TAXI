"""
TaxiApp 런처
- Streamlit을 별도 프로세스(메인 스레드)로 기동
- 콘솔 숨김 + 시스템 트레이
- 브라우저 앱 모드 자동 오픈
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8501
URL = f"http://{HOST}:{PORT}"
ROLE_ENV = "TAXIAPP_ROLE"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_app_py() -> Path:
    root = app_dir()
    p = root / "app.py"
    if p.exists():
        return p
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p2 = Path(meipass) / "app.py"
        if p2.exists():
            return p2
    return p


def prepare_paths() -> Path:
    root = app_dir()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in sys.path:
        sys.path.insert(0, meipass)
    return root


def apply_streamlit_runtime_env() -> None:
    """exe 패키징 시 developmentMode=true 로 잡혀 port 옵션과 충돌하는 문제 방지."""
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_SERVER_ADDRESS"] = HOST
    os.environ["STREAMLIT_SERVER_PORT"] = str(PORT)


def ensure_streamlit_config(root: Path) -> None:
    """작업 폴더에 .streamlit/config.toml 보장."""
    cfg_dir = root / ".streamlit"
    cfg = cfg_dir / "config.toml"
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        if not cfg.exists():
            cfg.write_text(
                "\n".join(
                    [
                        "[global]",
                        "developmentMode = false",
                        "",
                        "[browser]",
                        "gatherUsageStats = false",
                        "",
                        "[server]",
                        "headless = true",
                        f'address = "{HOST}"',
                        f"port = {PORT}",
                        "enableCORS = false",
                        "enableXsrfProtection = false",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
    except OSError:
        pass


def hide_console() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def open_browser() -> None:
    candidates = [
        [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            f"--app={URL}",
        ],
        [
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            f"--app={URL}",
        ],
        [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            f"--app={URL}",
        ],
    ]
    for cmd in candidates:
        if Path(cmd[0]).exists():
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                continue
    webbrowser.open(URL)


def wait_and_open(timeout: float = 120.0) -> None:
    import urllib.request

    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(URL, timeout=1) as r:
                if r.status == 200:
                    open_browser()
                    return
        except Exception:
            time.sleep(0.4)
    open_browser()


def write_error(root: Path, message: str) -> None:
    try:
        (root / "_launcher_error.txt").write_text(message, encoding="utf-8")
    except OSError:
        pass


def run_streamlit_main() -> None:
    """자식 프로세스: Streamlit을 메인 스레드에서 실행."""
    root = prepare_paths()
    apply_streamlit_runtime_env()
    ensure_streamlit_config(root)
    app_path = resource_app_py()
    try:
        from streamlit.web import cli as stcli

        sys.argv = [
            "streamlit",
            "run",
            str(app_path),
            f"--server.address={HOST}",
            f"--server.port={str(PORT)}",
            "--server.headless=true",
            "--global.developmentMode=false",
            "--browser.gatherUsageStats=false",
        ]
        stcli.main()
    except SystemExit:
        pass
    except Exception as e:
        write_error(root, f"Streamlit 기동 실패:\n{e}")
        raise


def start_streamlit_process() -> subprocess.Popen:
    """부모: Streamlit 역할로 자기 자신(또는 python -m streamlit)을 자식으로 실행."""
    root = prepare_paths()
    ensure_streamlit_config(root)
    env = os.environ.copy()
    env["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_SERVER_ADDRESS"] = HOST
    env["STREAMLIT_SERVER_PORT"] = str(PORT)
    env[ROLE_ENV] = "streamlit"

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    if getattr(sys, "frozen", False):
        # 같은 exe를 자식으로 — ROLE_ENV 로 분기
        cmd = [sys.executable]
    else:
        app_path = resource_app_py()
        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            f"--server.address={HOST}",
            f"--server.port={str(PORT)}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ]
        # 개발 모드에서는 ROLE 분기 없이 streamlit 모듈 직접 실행
        env.pop(ROLE_ENV, None)

    try:
        return subprocess.Popen(
            cmd,
            cwd=str(root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception as e:
        write_error(root, f"Streamlit 프로세스 시작 실패:\n{e}")
        raise


def terminate_process(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    except Exception:
        pass


def make_tray_icon(on_quit):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    img = Image.new("RGB", (64, 64), color=(30, 90, 160))
    d = ImageDraw.Draw(img)
    d.rectangle((12, 28, 52, 48), fill=(255, 200, 60))
    d.ellipse((16, 44, 28, 56), fill=(40, 40, 40))
    d.ellipse((40, 44, 52, 56), fill=(40, 40, 40))

    menu = pystray.Menu(
        pystray.MenuItem("화면 열기", lambda: open_browser()),
        pystray.MenuItem("종료", on_quit),
    )
    return pystray.Icon("TaxiApp", img, "택시 사업 자동화", menu)


def main() -> None:
    # 자식 프로세스: Streamlit만 실행
    if os.environ.get(ROLE_ENV) == "streamlit":
        run_streamlit_main()
        return

    hide_console()
    proc = start_streamlit_process()
    threading.Thread(target=wait_and_open, daemon=True).start()

    def quit_app(icon=None, _item=None):
        terminate_process(proc)
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        os._exit(0)

    icon = make_tray_icon(quit_app)
    if icon is not None:
        icon.run()
    else:
        try:
            proc.wait()
        except KeyboardInterrupt:
            quit_app()


if __name__ == "__main__":
    main()
