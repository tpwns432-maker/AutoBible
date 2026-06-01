"""Clipboard monitoring loop, reference handling, activity log."""
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


from bibleclip.theme import LIGHT_THEME, DARK_THEME, CTK


from bibleclip.core.formatter import Formatter


class MonitorMixin:
    def _toggle_monitoring(self):
        if self.monitoring:
            self.monitoring = False
            self.core.stop_monitoring()
            self.monitor_btn.configure(text="모니터링 시작")
            self._update_status("대기 중", False)
        else:
            self.monitoring = True
            self.monitor_btn.configure(text="모니터링 중지")
            self._update_status("모니터링 중", True)
            # The core owns the watch loop; we inject the platform clipboard
            # backend and receive structured callbacks (on this worker thread).
            self.core.start_monitoring(
                self._clipboard_read, self._clipboard_write,
                self._on_reference_caught, self._on_keyword_caught)

    def _clipboard_read(self):
        """Read clipboard text. On macOS, tkinter's clipboard_get can't fetch
        text copied by other apps, so use pbpaste; elsewhere use tkinter."""
        if sys.platform == 'darwin':
            try:
                r = subprocess.run(['/usr/bin/pbpaste'], capture_output=True,
                                   timeout=2, env=system_env())
                return r.stdout.decode('utf-8', 'replace')
            except Exception as e:
                self._log_update(f'pbpaste 실패: {e}')
                return ''
        try:
            return self.root.clipboard_get()
        except Exception:
            return ''

    def _clipboard_write(self, text):
        if sys.platform == 'darwin':
            try:
                subprocess.run(['/usr/bin/pbcopy'], input=text.encode('utf-8'),
                               timeout=2, env=system_env())
            except Exception as e:
                self._log_update(f'pbcopy 실패: {e}')
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except Exception:
            pass

    # ---- Core monitor callbacks (invoked on the watch worker thread) ----

    def _on_reference_caught(self, r):
        """A reference was caught and its formatted multi-version output was
        already written to the clipboard by the core; reflect it in the UI."""
        book_num, chapter, verses = r['book_num'], r['chapter'], r['verses']
        short_name, n_parts = r['short_name'], r['n_parts']
        self.root.after(0, lambda: self._update_viewer_from_ref(book_num, chapter, verses))
        self.root.after(0, lambda: self._append_log_ref(
            book_num, chapter, verses, short_name, n_parts))

    def _on_keyword_caught(self, keyword):
        """A '#keyword' query was caught — run the in-app search (copies first)."""
        self.root.after(0, lambda kw=keyword: self._run_search(kw, copy_first=True))

    def _update_viewer_from_ref(self, book_num, chapter, verses):
        primary = self._get_primary_version()
        # Fall back to any DB containing this book if primary doesn't have it.
        db = None
        if primary and primary in self.bible_dbs and book_num in self.bible_dbs[primary].books:
            db = self.bible_dbs[primary]
        else:
            for name in self._checked_in_order():
                if book_num in self.bible_dbs[name].books:
                    db = self.bible_dbs[name]
                    break
        if db is None:
            return
        short, long_ = db.books[book_num]
        target = f"{long_} ({short})"
        if target in (self.book_combo.cget('values') or []):
            self.book_var.set(target)
            chapters = db.get_chapters(book_num)
            self.chapter_combo.configure(values=[str(c) for c in chapters])
            self.chapter_var.set(str(chapter))
            self._load_chapter(highlight_verses=verses if verses else None)
            self._show_tab('viewer')

    def _append_log(self, text):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ---- Clickable log references (session only) ----

    def _append_log_ref(self, book_num, chapter, verses, short_name, n_versions):
        """Append a caught reference as a clickable log line."""
        idx = len(self._log_refs)
        self._log_refs.append((book_num, chapter, list(verses or [])))
        verse_str = Formatter._format_verse_list(verses) if verses else "전체"
        label = f"[{short_name} {chapter}:{verse_str}] → {n_versions}개 버전\n"
        tag = f"logref_{idx}"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, label, ('logref', tag))
        self.log_text.tag_bind(tag, '<Button-1>',
                               lambda e, i=idx: self._on_log_ref_click(i))
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _on_log_ref_click(self, idx):
        if 0 <= idx < len(self._log_refs):
            book_num, chapter, verses = self._log_refs[idx]
            self._update_viewer_from_ref(book_num, chapter, verses)

    def _update_status(self, text, active):
        # CTk badge (top bar) — colors switch with appearance mode via tuples.
        self.status_label.configure(text=text)
        if active:
            self.status_label.configure(fg_color=CTK['status_on_bg'],
                                        text_color=CTK['status_on_fg'])
        else:
            self.status_label.configure(fg_color=CTK['status_off_bg'],
                                        text_color=CTK['status_off_fg'])

    # ---- Theme ----

