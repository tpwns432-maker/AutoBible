"""Headless test for the self-update installer mechanics (core.installer).

Verifies, WITHOUT any GitHub release or running app:
  - stage_payload() locates the payload through a wrapping folder,
  - write_windows_bat() emits the expected swap script,
  - the generated .bat actually swaps an install dir (Windows only); the
    relaunch target is a harmless copy of whoami.exe.

Run:  python -X utf8 tests/test_installer.py
"""
import os
import sys
import shutil
import zipfile
import tempfile
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibleclip.core.installer import stage_payload, write_windows_bat


def test_stage_payload():
    tmp = tempfile.mkdtemp(prefix='bc_inst_')
    try:
        # zip whose single top-level entry is the BibleClipWeb/ folder
        payload_root = os.path.join(tmp, 'BibleClipWeb')
        os.makedirs(payload_root)
        open(os.path.join(payload_root, 'BibleClipWeb.exe'), 'w').close()
        open(os.path.join(payload_root, 'marker.txt'), 'w').write('v2')
        zip_path = os.path.join(tmp, 'pkg.zip')
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.write(os.path.join(payload_root, 'BibleClipWeb.exe'), 'BibleClipWeb/BibleClipWeb.exe')
            zf.write(os.path.join(payload_root, 'marker.txt'), 'BibleClipWeb/marker.txt')
        extract = os.path.join(tmp, 'extract')
        src = stage_payload(zip_path, extract, 'BibleClipWeb.exe')
        assert os.path.exists(os.path.join(src, 'BibleClipWeb.exe')), src
        assert os.path.basename(src) == 'BibleClipWeb', src
        print(f"stage_payload -> found payload in {os.path.basename(src)}/")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bat_content():
    tmp = tempfile.mkdtemp(prefix='bc_inst_')
    try:
        bat = os.path.join(tmp, 'updater.bat')
        write_windows_bat(bat, r'C:\src', r'C:\dst', 'BibleClipWeb.exe')
        with open(bat, encoding='cp949', errors='replace') as f:
            txt = f.read()
        for needle in ('set "EXE=BibleClipWeb.exe"', 'robocopy "%SRC%" "%DST%" /E',
                       'IMAGENAME eq %EXE%', 'start "" "%DST%\\%EXE%"', 'del "%~f0"'):
            assert needle in txt, needle
        print("write_windows_bat -> content OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_swap_integration():
    if sys.platform != 'win32':
        print("(non-Windows — skipped swap integration)")
        return
    whoami = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32', 'whoami.exe')
    if not os.path.exists(whoami):
        print("(whoami.exe not found — skipped swap integration)")
        return
    tmp = tempfile.mkdtemp(prefix='bc_inst_')
    try:
        dst = os.path.join(tmp, 'install'); os.makedirs(dst)
        src = os.path.join(tmp, 'newver'); os.makedirs(src)
        # old install: a stale file + a benign "exe" (renamed whoami) to relaunch
        open(os.path.join(dst, 'stale.txt'), 'w').write('old')
        shutil.copy(whoami, os.path.join(dst, 'BibleClipWeb.exe'))
        # new version payload: updated content
        open(os.path.join(src, 'marker.txt'), 'w').write('v2')
        shutil.copy(whoami, os.path.join(src, 'BibleClipWeb.exe'))
        bat = os.path.join(tmp, 'updater.bat')
        write_windows_bat(bat, src, dst, 'BibleClipWeb.exe')
        subprocess.run(['cmd', '/c', bat], timeout=40,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        # robocopy /E mirrors-in (doesn't delete extras): new file must appear
        deadline = time.time() + 10
        while time.time() < deadline and not os.path.exists(os.path.join(dst, 'marker.txt')):
            time.sleep(0.3)
        assert os.path.exists(os.path.join(dst, 'marker.txt')), "new file not copied"
        assert open(os.path.join(dst, 'marker.txt')).read() == 'v2'
        print("swap integration -> install dir updated (marker.txt=v2)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    test_stage_payload()
    test_bat_content()
    test_swap_integration()
    print("\nALL INSTALLER CHECKS PASSED ✅")
    sys.stdout.flush()
    os._exit(0)
