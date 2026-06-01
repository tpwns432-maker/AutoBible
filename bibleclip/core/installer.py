"""UI-agnostic self-update installer helpers.

Pure, testable pieces shared by the web UI's in-app updater: download a release
zip, locate the payload inside the extracted tree, and write the external
updater script (Windows .bat / macOS .sh) that waits for the app to exit, swaps
the install directory, and relaunches. Spawning the script and quitting the app
is left to the caller (it's UI/process specific).

Nothing here imports webview or tkinter, so the swap mechanics can be tested
headlessly by running the generated .bat against a throwaway directory.
"""
import os
import zipfile
import urllib.request

from bibleclip.update import urlopen_resilient
from bibleclip.config import __version__


def download_file(url, dest, on_progress=None, timeout=30):
    """Stream a URL to ``dest``. ``on_progress(downloaded, total)`` is called as
    bytes arrive (total may be 0 when the server omits Content-Length)."""
    req = urllib.request.Request(url, headers={
        'User-Agent': f'BibleClip/{__version__}',
        'Accept': 'application/octet-stream',
    })
    with urlopen_resilient(req, timeout) as resp:
        total = int(resp.headers.get('Content-Length') or 0)
        downloaded = 0
        with open(dest, 'wb') as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    return dest


def stage_payload(zip_path, extract_dir, payload_name):
    """Extract ``zip_path`` into ``extract_dir`` and return the directory that
    actually contains ``payload_name`` (handles a single wrapping folder, e.g.
    a zip whose top level is ``BibleClipWeb/``). Raises if the payload is
    missing."""
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    def has_payload(d):
        return os.path.exists(os.path.join(d, payload_name))

    if has_payload(extract_dir):
        return extract_dir
    for entry in os.listdir(extract_dir):
        cand = os.path.join(extract_dir, entry)
        if os.path.isdir(cand) and has_payload(cand):
            return cand
    raise RuntimeError(f"zip에 {payload_name}이(가) 없습니다.")


def write_windows_bat(bat_path, src_dir, install_dir, exe_name):
    """Write an updater .bat: wait for ``exe_name`` to exit, robocopy ``src_dir``
    over ``install_dir``, relaunch, and self-delete. Written in the console OEM
    codepage so cmd.exe reads non-ASCII (Korean) paths correctly."""
    content = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"set \"SRC={src_dir}\"\r\n"
        f"set \"DST={install_dir}\"\r\n"
        f"set \"EXE={exe_name}\"\r\n"
        "set \"LOG=%DST%\\update_apply.log\"\r\n"
        "echo [updater] start %DATE% %TIME% > \"%LOG%\"\r\n"
        "set TRIES=0\r\n"
        ":wait\r\n"
        "tasklist /FI \"IMAGENAME eq %EXE%\" 2>nul | find /I \"%EXE%\" >nul\r\n"
        "if errorlevel 1 goto ready\r\n"
        "set /a TRIES+=1\r\n"
        "if %TRIES% GEQ 30 goto ready\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto wait\r\n"
        ":ready\r\n"
        "ping -n 3 127.0.0.1 >nul\r\n"
        "robocopy \"%SRC%\" \"%DST%\" /E /R:8 /W:1 >> \"%LOG%\" 2>&1\r\n"
        "set RC=%ERRORLEVEL%\r\n"
        "echo [updater] robocopy exit %RC% >> \"%LOG%\"\r\n"
        "if %RC% GEQ 8 (\r\n"
        "  echo [updater] FAILED >> \"%LOG%\"\r\n"
        "  start \"\" \"%DST%\\%EXE%\"\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "echo [updater] OK >> \"%LOG%\"\r\n"
        "start \"\" \"%DST%\\%EXE%\"\r\n"
        "(goto) 2>nul & del \"%~f0\"\r\n"
        "exit /b 0\r\n"
    )
    enc = 'utf-8'
    try:
        import ctypes
        candidate = f'cp{ctypes.windll.kernel32.GetOEMCP()}'
        content.encode(candidate)
        enc = candidate
    except Exception:
        try:
            import locale
            candidate = locale.getpreferredencoding(False)
            content.encode(candidate)
            enc = candidate
        except Exception:
            enc = 'utf-8'
    with open(bat_path, 'w', encoding=enc, errors='replace') as f:
        f.write(content)
    return bat_path


def write_mac_sh(sh_path, src_dir, app_dst, pid, data_names=()):
    """Write a bash updater: wait for ``pid`` to exit, swap the .app bundle, and
    relaunch. ``app_dst`` is the running bundle's full path; the new bundle is
    extracted as BibleClipWeb.app inside ``src_dir``."""
    dst_parent = os.path.dirname(app_dst.rstrip('/'))
    new_app = os.path.join(src_dir, 'BibleClipWeb.app')
    lines = [
        '#!/bin/bash',
        f'PID={pid}',
        'for i in $(seq 1 60); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done',
        'sleep 1',
        f'rm -rf "{app_dst}"',
        f'ditto "{new_app}" "{app_dst}"',
        f'open "{app_dst}"',
        'rm -- "$0"',
    ]
    with open(sh_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(sh_path, 0o755)
    return sh_path
