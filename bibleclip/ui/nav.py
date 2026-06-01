"""Arrow-key previous/next chapter navigation."""
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


class NavMixin:
    def _nav_keys_allowed(self):
        """Arrow-key chapter nav only on the viewer tab and not while a field
        (entry / combobox / listbox) has focus."""
        try:
            if getattr(self, '_current_tab', 'viewer') != 'viewer':
                return False
            w = self.root.focus_get()
            if isinstance(w, (tk.Entry, ttk.Combobox, tk.Listbox)):
                return False
        except Exception:
            pass
        return True

    def _on_arrow_prev(self, event):
        if self._nav_keys_allowed():
            self._prev_chapter()

    def _on_arrow_next(self, event):
        if self._nav_keys_allowed():
            self._next_chapter()

    def _prev_chapter(self):
        chapters = list(self.chapter_combo.cget('values'))
        if not chapters:
            return
        cur = self.chapter_var.get()
        idx = chapters.index(cur) if cur in chapters else 0
        if idx > 0:
            self.chapter_var.set(chapters[idx - 1])
            self._load_chapter()

    def _next_chapter(self):
        chapters = list(self.chapter_combo.cget('values'))
        if not chapters:
            return
        cur = self.chapter_var.get()
        idx = chapters.index(cur) if cur in chapters else 0
        if idx < len(chapters) - 1:
            self.chapter_var.set(chapters[idx + 1])
            self._load_chapter()

    # ---- Monitoring ----

