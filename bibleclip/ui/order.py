"""Output version order editing + live preview."""
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


class OrderMixin:
    def _refresh_available_list(self):
        self.avail_listbox.delete(0, tk.END)
        # Show all DBs that are NOT in the order list
        order_names = self._get_order_names()
        for name, db in self.bible_dbs.items():
            if name not in order_names:
                self.avail_listbox.insert(tk.END, db.display_name)

    def _get_order_names(self):
        """Get version names from order listbox."""
        names = []
        for i in range(self.order_listbox.size()):
            display = self.order_listbox.get(i)
            # Extract name from "description [NAME]"
            m = re.search(r'\[(\w+)\]', display)
            if m:
                names.append(m.group(1))
        return names

    def _display_to_name(self, display_str):
        m = re.search(r'\[(\w+)\]', display_str)
        return m.group(1) if m else None

    def _add_to_order(self):
        sel = self.avail_listbox.curselection()
        if not sel:
            return
        for i in sorted(sel, reverse=True):
            display = self.avail_listbox.get(i)
            self.order_listbox.insert(tk.END, display)
            self.avail_listbox.delete(i)
        self._sync_order_to_settings()
        self._update_preview()

    def _remove_from_order(self):
        sel = self.order_listbox.curselection()
        if not sel:
            return
        for i in sorted(sel, reverse=True):
            display = self.order_listbox.get(i)
            self.order_listbox.delete(i)
            self.avail_listbox.insert(tk.END, display)
        self._sync_order_to_settings()
        self._update_preview()

    def _move_up(self):
        sel = self.order_listbox.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        text = self.order_listbox.get(idx)
        self.order_listbox.delete(idx)
        self.order_listbox.insert(idx - 1, text)
        self.order_listbox.selection_set(idx - 1)
        self._sync_order_to_settings()
        self._update_preview()
        self._apply_listbox_theme()

    def _move_down(self):
        sel = self.order_listbox.curselection()
        if not sel or sel[0] >= self.order_listbox.size() - 1:
            return
        idx = sel[0]
        text = self.order_listbox.get(idx)
        self.order_listbox.delete(idx)
        self.order_listbox.insert(idx + 1, text)
        self.order_listbox.selection_set(idx + 1)
        self._sync_order_to_settings()
        self._update_preview()
        self._apply_listbox_theme()

    def _clear_order(self):
        while self.order_listbox.size() > 0:
            display = self.order_listbox.get(0)
            self.order_listbox.delete(0)
            self.avail_listbox.insert(tk.END, display)
        self._sync_order_to_settings()
        self._update_preview()

    def _sync_order_to_settings(self):
        self.settings['output_order'] = self._get_order_names()
        self._save_settings()

    # ---- Setting changed callback ----

    def _on_setting_changed(self):
        self.settings['book_name'] = self.book_name_var.get()
        self.settings['chapter_verse_format'] = self.cv_format_var.get()
        self.settings['bracket_style'] = self.bracket_var.get()
        self.settings['ref_position'] = self.position_var.get()
        self.settings['range_symbol'] = self.range_var.get()
        self.settings['ref_body_separator'] = self.sep_var.get()
        self.settings['output_mode'] = self.output_mode_var.get()
        self.settings['newline_show_cv'] = self.newline_cv_var.get()
        self.settings['show_version_header'] = self.version_header_var.get()
        self.settings['hide_reference'] = self.hide_ref_var.get()
        self._save_settings()
        self._update_preview()

    # ---- Preview ----

    def _update_preview(self):
        """Generate preview using John 1:1-3."""
        self.preview_text.configure(state=tk.NORMAL)
        self.preview_text.delete('1.0', tk.END)

        order = self.settings['output_order']
        if not order:
            self.preview_text.insert(tk.END, "(출력할 성경 버전을 추가하세요)")
            self.preview_text.configure(state=tk.DISABLED)
            return

        book_num = 500  # 요한복음
        chapter = 1
        verses = [1, 2, 3]

        fmt = Formatter(self.settings, self.bible_dbs)
        parts = []
        for ver_name in order:
            if ver_name not in self.bible_dbs:
                continue
            db = self.bible_dbs[ver_name]
            if book_num not in db.books:
                continue
            verse_data = [(v, db.get_verse_text(book_num, chapter, v)) for v in verses]
            verse_data = [(v, t) for v, t in verse_data if t]
            if not verse_data:
                continue
            text = fmt.format_version_output(db, book_num, chapter, verses, verse_data)
            if text:
                parts.append(text)

        result = '\n\n'.join(parts) if parts else "(데이터를 찾을 수 없습니다)"
        self.preview_text.insert(tk.END, result)
        self.preview_text.configure(state=tk.DISABLED)

    # ---- Viewer navigation ----

    # ---- Viewer version chips / ordering ----

