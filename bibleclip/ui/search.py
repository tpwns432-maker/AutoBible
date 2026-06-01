"""Keyword (#) search input, results, click-to-copy."""
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


class SearchMixin:
    def _on_search_box(self, event):
        self._run_search(self.search_var.get(), copy_first=False)

    def _search_version(self):
        ver = self._get_primary_version()
        if ver and ver in self.bible_dbs:
            return ver
        for v in ('KRV', 'NRKV', 'KNRSV'):
            if v in self.bible_dbs:
                return v
        return next(iter(self.bible_dbs), None)

    def _run_search(self, raw, copy_first=False):
        keyword = (raw or '').strip().lstrip('#').strip()
        if not keyword:
            return
        ver = self._search_version()
        if not ver:
            return
        results = self.bible_dbs[ver].search(keyword, limit=300)
        self._render_search_results(keyword, ver, results)
        self._show_tab('viewer')
        if copy_first and results:
            b, c, v, _ = results[0]
            self._copy_single_ref(b, c, v)
            self._append_log(f'[검색 복사] {keyword} → 첫 구절\n')

    def _render_search_results(self, keyword, ver, results):
        self._search_results = [(b, c, v) for b, c, v, _ in results]
        text = self.viewer_text
        text.configure(state=tk.NORMAL)
        text.delete('1.0', tk.END)
        self._current_verse_nums = []
        db = self.bible_dbs.get(ver)
        if not results:
            text.insert(tk.END, f'"{keyword}" 검색 결과 없음  ({ver})')
            text.configure(state=tk.DISABLED)
            return
        text.insert(tk.END,
                    f'"{keyword}" 검색 결과 {len(results)}건  ({ver}) — 구절 클릭 시 복사\n\n',
                    ('search_head',))
        for idx, (b, c, v, t) in enumerate(results):
            short = db.books.get(b, ('?', '?'))[0] if db else '?'
            tag = f'sr_{idx}'
            text.tag_configure(tag)
            text.insert(tk.END, f'({short} {c}:{v}) ', ('search_ref', 'sr_click', tag))
            text.insert(tk.END, f'{t}\n\n', ('sr_click', tag))
            text.tag_bind(tag, '<Button-1>', lambda e, i=idx: self._on_search_result_click(i))
        text.configure(state=tk.DISABLED)
        text.yview_moveto(0)

    def _on_search_result_click(self, idx):
        if 0 <= idx < len(self._search_results):
            b, c, v = self._search_results[idx]
            self._copy_single_ref(b, c, v)

    def _format_single_ref(self, book_num, chapter, verse):
        order = self._checked_in_order() or list(self.settings.get('output_order', []))
        fmt = Formatter(self.settings, self.bible_dbs)
        parts = []
        for ver in order:
            db = self.bible_dbs.get(ver)
            if not db or book_num not in db.books:
                continue
            t = db.get_verse_text(book_num, chapter, verse)
            if not t:
                continue
            txt = fmt.format_version_output(db, book_num, chapter, [verse], [(verse, t)])
            if txt:
                parts.append(txt)
        return '\n\n'.join(parts)

    def _copy_single_ref(self, book_num, chapter, verse):
        result = self._format_single_ref(book_num, chapter, verse)
        if not result:
            return
        self._clipboard_write(result)
        self.core.notify_clipboard_written(result)
        short = '?'
        for db in self.bible_dbs.values():
            if book_num in db.books:
                short = db.books[book_num][0]
                break
        self._append_log(f'[복사] {short} {chapter}:{verse}\n')

