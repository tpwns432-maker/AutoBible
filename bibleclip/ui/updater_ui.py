"""Update banner, download, and platform updater scripts."""
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import os
import sys
import re
import json
import threading
import time
import urllib.request
import urllib.error
import ssl
import zipfile
import tempfile
import subprocess
import datetime
import webbrowser
import shlex
try:
    import certifi as _certifi  # bundled CA store (top-level so PyInstaller includes it)
except Exception:
    _certifi = None

from bibleclip.config import (
    __version__, IS_WINDOWS,
    APP_FONT, UI_FONT, BODY_FONT, MONO_FONT, SERIF_FONT,
    GITHUB_OWNER, GITHUB_REPO, UPDATE_CHECK_URL, RELEASES_PAGE_URL,
    get_base_dir, get_resource_dir, system_env,
    BASE_DIR, SETTINGS_FILE, LEGACY_SETTINGS_FILE, BIBLE_DIR,
    candidate_data_roots, resolve_data_dir,
)

from bibleclip.constants import (
    QWERTY_TO_HANGUL, CHOSEONG, JUNGSEONG, JONGSEONG,
    COMPLEX_JUNGSEONG, COMPLEX_JONGSEONG,
    KOREAN_BOOK_MAP, ENGLISH_BOOK_MAP, ENGLISH_VERSIONS,
)


from bibleclip.text_utils import (
    qwerty_to_jamo, is_choseong, is_jungseong, assemble_hangul,
    convert_qwerty_to_hangul, clean_text, despace, trigrams,
)


from bibleclip.update import parse_version, fetch_latest_release, urlopen_resilient
from bibleclip.data.original_lang import (
    ORIGINAL_LANG_DIR, resolve_original_lang_dir,
    BethlehemDB, Lexicon,
    parse_korean_strongs, parse_wonjun_verse, render_dict_html,
)

from bibleclip.core.engine import Engine
from bibleclip.data.bible_db import BibleDB


from bibleclip.theme import LIGHT_THEME, DARK_THEME


from bibleclip.core.formatter import Formatter


class UpdateMixin:
    def _log_update(self, msg):
        try:
            path = os.path.join(BASE_DIR, 'update_check.log')
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] {msg}\n')
        except Exception:
            pass

    def _start_update_check(self):
        if not getattr(sys, 'frozen', False):
            self._log_update('자동 체크 스킵 (소스 모드)')
            return
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        self._log_update(f'자동 체크 시작 (현재 v{__version__})')
        info, error = fetch_latest_release()
        if not info:
            self._log_update(f'체크 실패: {error}')
            return
        self._log_update(f'최신 릴리스: {info["version"]}')
        latest = parse_version(info['version'])
        current = parse_version(__version__)
        if latest <= current:
            self._log_update('이미 최신 버전')
            return
        if self.settings.get('skip_update_version', '') == info['version']:
            self._log_update(f'사용자가 {info["version"]} 건너뛰기 설정')
            return
        self.update_info = info
        self.root.after(0, self._show_update_banner)

    def _manual_update_check(self):
        if hasattr(self, 'update_check_btn'):
            self.update_check_btn.configure(text=" 확인 중... ", state=tk.DISABLED)
        threading.Thread(target=self._manual_update_check_worker, daemon=True).start()

    def _manual_update_check_worker(self):
        self._log_update('수동 체크 시작')
        info, error = fetch_latest_release()
        self.root.after(0, lambda: self._manual_update_check_done(info, error))

    def _manual_update_check_done(self, info, error):
        if hasattr(self, 'update_check_btn'):
            self.update_check_btn.configure(text=" 업데이트 확인 ", state=tk.NORMAL)
        if error:
            self._log_update(f'수동 체크 실패: {error}')
            messagebox.showerror("업데이트 확인 실패",
                f"릴리스 정보를 가져오지 못했습니다.\n\n오류: {error}\n\n"
                f"로그: {os.path.join(BASE_DIR, 'update_check.log')}")
            return
        if not info:
            messagebox.showinfo("업데이트", "릴리스 정보가 없습니다.")
            return
        latest = parse_version(info['version'])
        current = parse_version(__version__)
        if latest <= current:
            self._log_update(f'수동 체크 결과: 이미 최신 (v{__version__})')
            messagebox.showinfo("업데이트",
                f"이미 최신 버전입니다 (v{__version__}).\n"
                f"GitHub 최신 릴리스: {info['version']}")
            return
        self._log_update(f'수동 체크 결과: 새 버전 {info["version"]} 발견')
        self.update_info = info
        self._show_update_banner()

    def _show_update_banner(self):
        info = self.update_info
        if not info:
            return
        if self.update_banner and self.update_banner.winfo_exists():
            self.update_banner.destroy()
        bg, fg = '#FFF3CD', '#856404'
        banner = tk.Frame(self.main_frame, bg=bg)
        banner.pack(fill=tk.X, before=self.top_bar)
        msg = f"새 버전 {info['version']} 사용 가능 (현재 v{__version__})"
        tk.Label(banner, text=msg, bg=bg, fg=fg,
                 font=(UI_FONT, 9, 'bold')).pack(side=tk.LEFT, padx=10, pady=4)
        tk.Button(banner, text=" 지금 업데이트 ", bg=bg, fg=fg,
                  font=(UI_FONT, 9, 'bold'), relief=tk.FLAT, cursor='hand2',
                  command=self._start_update).pack(side=tk.RIGHT, padx=4, pady=2)
        tk.Button(banner, text=" 나중에 ", bg=bg, fg=fg,
                  font=(UI_FONT, 9), relief=tk.FLAT, cursor='hand2',
                  command=banner.destroy).pack(side=tk.RIGHT, padx=4, pady=2)
        tk.Button(banner, text=" 이 버전 건너뛰기 ", bg=bg, fg=fg,
                  font=(UI_FONT, 9), relief=tk.FLAT, cursor='hand2',
                  command=self._skip_current_update).pack(side=tk.RIGHT, padx=4, pady=2)
        self.update_banner = banner

    def _skip_current_update(self):
        if self.update_info:
            self.settings['skip_update_version'] = self.update_info['version']
            self._save_settings()
        if self.update_banner and self.update_banner.winfo_exists():
            self.update_banner.destroy()

    def _start_update(self):
        info = self.update_info
        if not info:
            return
        is_mac = (sys.platform == 'darwin')
        if not getattr(sys, 'frozen', False):
            messagebox.showinfo("업데이트", "소스 실행 모드에서는 자동 업데이트가 적용되지 않습니다.")
            return
        if not (IS_WINDOWS or is_mac):
            # In-place update implemented for Windows + macOS only.
            ver = info.get('version', '')
            if messagebox.askyesno(
                    "업데이트",
                    f"새 버전 {ver}이(가) 있습니다.\n"
                    f"현재 OS에서는 자동 설치가 지원되지 않습니다.\n\n"
                    f"다운로드 페이지를 여시겠습니까?"):
                try:
                    webbrowser.open(RELEASES_PAGE_URL)
                except Exception:
                    pass
            return

        win = tk.Toplevel(self.root)
        win.title("업데이트")
        win.geometry("420x160")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        try:
            win.iconbitmap(os.path.join(BASE_DIR, "icon.ico"))
        except Exception:
            pass

        lbl = tk.Label(win, text=f"v{info['version']} 다운로드 중...", font=(UI_FONT, 10))
        lbl.pack(pady=(20, 8))
        pb = ttk.Progressbar(win, mode='determinate', length=360, maximum=100)
        pb.pack(pady=4)
        status = tk.Label(win, text="", font=(UI_FONT, 9))
        status.pack(pady=4)

        def worker():
            tmpdir = tempfile.mkdtemp(prefix='bibleclip_update_')
            try:
                zip_path = os.path.join(tmpdir, info['asset_name'] or 'update.zip')
                self._download_with_progress(info['download_url'], zip_path, pb, status, lbl)

                self.root.after(0, lambda: status.configure(text="압축 해제 중..."))
                extract_dir = os.path.join(tmpdir, 'extract')
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(extract_dir)

                # Resolve src dir = the folder that actually holds the payload.
                # The macOS zip's single top-level entry IS BibleClip.app, so a
                # naive "descend into the only folder" heuristic wrongly steps
                # INTO the bundle. Locate by payload instead.
                payload = 'BibleClip.app' if is_mac else 'BibleClip.exe'

                def _has_payload(d):
                    return os.path.exists(os.path.join(d, payload))

                src_dir = extract_dir
                if not _has_payload(src_dir):
                    for e in os.listdir(extract_dir):
                        cand = os.path.join(extract_dir, e)
                        if os.path.isdir(cand) and _has_payload(cand):
                            src_dir = cand
                            break
                if not _has_payload(src_dir):
                    raise RuntimeError(f"zip 파일에 {payload}이(가) 없습니다.")

                self.root.after(0, lambda: status.configure(text="앱 종료 후 교체합니다..."))
                if is_mac:
                    sh_path = os.path.join(tmpdir, 'updater.sh')
                    # Replace the ACTUAL running bundle (its name may differ,
                    # e.g. "BibleClip 2.app" on a name collision), not a
                    # hardcoded BibleClip.app.
                    app_dst = self._running_app_path() or os.path.join(BASE_DIR, 'BibleClip.app')
                    self._write_mac_updater_sh(sh_path, src_dir, app_dst, os.getpid())
                    subprocess.Popen(['/bin/bash', sh_path],
                                     start_new_session=True, close_fds=True)
                    self.root.after(300, self._quit_for_update)
                else:
                    bat_path = os.path.join(tmpdir, 'updater.bat')
                    self._write_updater_bat(bat_path, src_dir, BASE_DIR)
                    # Hidden console (CREATE_NO_WINDOW); do NOT add DETACHED_PROCESS
                    # (that conflict produced a visible, mis-behaving window).
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP
                    flags |= getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                    subprocess.Popen(['cmd', '/c', bat_path], creationflags=flags,
                                     close_fds=True)
                    self.root.after(300, self._quit_for_update)
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self._update_failed(err, win))

        threading.Thread(target=worker, daemon=True).start()

    def _running_app_path(self):
        """Path of the currently running .app bundle (handles a renamed bundle
        like 'BibleClip 2.app'), or None when not in a .app."""
        if sys.platform != 'darwin':
            return None
        p = os.path.dirname(sys.executable)
        while p and not p.endswith('.app'):
            parent = os.path.dirname(p)
            if parent == p:
                return None
            p = parent
        return p if p.endswith('.app') else None

    def _write_mac_updater_sh(self, path, src_dir, app_dst, pid):
        """Bash updater: wait for the app to quit, swap the .app + data, relaunch.

        app_dst is the FULL path of the bundle to replace (the running app,
        whatever its name). The new bundle is always extracted as BibleClip.app.
        """
        dst_parent = os.path.dirname(app_dst.rstrip('/'))
        lines = [
            '#!/bin/bash',
            f'SRC={shlex.quote(src_dir)}',
            f'DST={shlex.quote(dst_parent)}',
            f'APP={shlex.quote(app_dst)}',
            'LOG="$DST/update_apply.log"',
            'echo "[updater] start $(date)" > "$LOG"',
            # wait (max ~30s) for the running app to exit
            f'for i in $(seq 1 30); do kill -0 {int(pid)} 2>/dev/null || break; sleep 1; done',
            'sleep 1',
            'rm -rf "$APP"',
            'ditto "$SRC/BibleClip.app" "$APP" >> "$LOG" 2>&1',
            'RC=$?',
            '[ -d "$SRC/bible_versions" ] && ditto "$SRC/bible_versions" "$DST/bible_versions" >> "$LOG" 2>&1',
            '[ -d "$SRC/original_lang" ] && ditto "$SRC/original_lang" "$DST/original_lang" >> "$LOG" 2>&1',
            'xattr -dr com.apple.quarantine "$APP" >/dev/null 2>&1',
            'echo "[updater] ditto exit $RC" >> "$LOG"',
            'open "$APP"',
            'rm -f "$0"',
            'exit 0',
        ]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    def _quit_for_update(self):
        """Hard-exit used right before the external updater swaps files."""
        try:
            self.monitoring = False
            self.core.stop_monitoring()
            self._save_settings()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        # Guarantee the process terminates so the updater can overwrite the exe.
        os._exit(0)

    def _download_with_progress(self, url, dest, pb, status, lbl):
        req = urllib.request.Request(url, headers={
            'User-Agent': f'BibleClip/{__version__}',
            'Accept': 'application/octet-stream',
        })
        with urlopen_resilient(req, 30) as resp:
            total = int(resp.headers.get('Content-Length') or 0)
            downloaded = 0
            with open(dest, 'wb') as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100.0 / total
                        kb_d, kb_t = downloaded // 1024, total // 1024
                        self.root.after(0, lambda p=pct, d=kb_d, t=kb_t: (
                            pb.configure(value=p),
                            status.configure(text=f"{d:,} KB / {t:,} KB")))
                    else:
                        self.root.after(0, lambda d=downloaded: status.configure(
                            text=f"{d // 1024:,} KB"))

    def _write_updater_bat(self, path, src_dir, install_dir):
        # Robust updater:
        #  - wait for the app to fully exit (tasklist loop)
        #  - settle delay so OneDrive / AV / the just-exited process release
        #    file locks on BibleClip.exe and the _internal DLLs
        #  - robocopy (retries locked files; clear exit codes) instead of xcopy
        #    (xcopy can silently report success after copying 0 files)
        #  - robocopy success is exit code < 8; relaunch and log the outcome
        #
        # Paths may contain non-ASCII characters (Korean folder names). cmd.exe
        # reads a .bat using the console OEM codepage, so the file is written in
        # that codepage (cp949 on Korean Windows), not ASCII. The long install
        # path is bound to a variable so it appears only once.
        content = (
            "@echo off\r\n"
            "setlocal\r\n"
            f"set \"SRC={src_dir}\"\r\n"
            f"set \"DST={install_dir}\"\r\n"
            "set \"LOG=%DST%\\update_apply.log\"\r\n"
            "echo [updater] start %DATE% %TIME% > \"%LOG%\"\r\n"
            "set TRIES=0\r\n"
            ":wait\r\n"
            "tasklist /FI \"IMAGENAME eq BibleClip.exe\" 2>nul | find /I \"BibleClip.exe\" >nul\r\n"
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
            "  start \"\" \"%DST%\\BibleClip.exe\"\r\n"
            "  exit /b 1\r\n"
            ")\r\n"
            "echo [updater] OK >> \"%LOG%\"\r\n"
            "start \"\" \"%DST%\\BibleClip.exe\"\r\n"
            "(goto) 2>nul & del \"%~f0\"\r\n"
            "exit /b 0\r\n"
        )
        enc = 'utf-8'
        try:
            import ctypes
            oemcp = ctypes.windll.kernel32.GetOEMCP()
            candidate = f'cp{oemcp}'
            content.encode(candidate)  # validate all chars are representable
            enc = candidate
        except Exception:
            # Fall back to the locale's preferred encoding, then utf-8.
            try:
                import locale
                candidate = locale.getpreferredencoding(False)
                content.encode(candidate)
                enc = candidate
            except Exception:
                enc = 'utf-8'
        with open(path, 'w', encoding=enc, errors='replace') as f:
            f.write(content)

    def _update_failed(self, err, win):
        try:
            win.destroy()
        except Exception:
            pass
        self._log_update(f'업데이트 실패: {err}')
        if messagebox.askyesno(
                "업데이트 실패",
                f"자동 업데이트 중 오류가 발생했습니다:\n{err}\n\n"
                f"다운로드 페이지에서 직접 받으시겠습니까?"):
            try:
                webbrowser.open(RELEASES_PAGE_URL)
            except Exception:
                pass

    # ---- Close ----

    def _on_close(self):
        self.monitoring = False
        self.core.stop_monitoring()
        self._capture_sash_positions()
        self._save_settings()
        for db in self.bible_dbs.values():
            try:
                db.close()
            except Exception:
                pass
        self.root.destroy()


