"""BibleClip application window: assembles the UI mixins."""
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
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

from bibleclip.ui.viewer_tab import ViewerTabMixin
from bibleclip.ui.settings_tab import SettingsTabMixin
from bibleclip.ui.lexicon import LexiconMixin
from bibleclip.ui.order import OrderMixin
from bibleclip.ui.viewer_ops import ViewerOpsMixin
from bibleclip.ui.search import SearchMixin
from bibleclip.ui.nav import NavMixin
from bibleclip.ui.monitor import MonitorMixin
from bibleclip.ui.theming import ThemeMixin
from bibleclip.ui.updater_ui import UpdateMixin


class BibleClipApp(
    ViewerTabMixin,
    SettingsTabMixin,
    LexiconMixin,
    OrderMixin,
    ViewerOpsMixin,
    SearchMixin,
    NavMixin,
    MonitorMixin,
    ThemeMixin,
    UpdateMixin,
):
    DEFAULT_SETTINGS = {
        'book_name': 'short_ko',        # short_ko, long_ko, short_en, long_en
        'chapter_verse_format': 'colon', # colon, korean
        'bracket_style': 'none',         # none, [], ()
        'ref_position': 'before',        # before, after
        'range_symbol': '-',             # -, ~
        'ref_body_separator': ' ',       # ' ' (space), ' - ' (hyphen), ': ' (colon)
        'show_version_header': True,
        'hide_reference': False,
        'output_mode': 'inline',         # inline, newline
        'newline_show_cv': False,        # show chapter:verse on each line
        'output_order': [],              # ordered list of version names
        'viewer_versions': [],           # checked versions in viewer (ordered subset)
        'viewer_version_order': [],      # full viewer ordering (checked + unchecked)
        'viewer_font_size': 11,
        'auto_update_check': True,
        'skip_update_version': '',
        'dark_mode': False,
        'geometry': '1100x780',
        'last_book_num': None,           # remember last viewed book/chapter
        'last_chapter': None,
        'viewer_hsash': [],              # horizontal 3-panel sash x positions
        'viewer_vsash': None,            # vertical (panels/log) sash y position
        'lex_popup_size': '440x480',     # size for new independent dict windows
    }

    def __init__(self, root):
        self.root = root
        self.root.title(f"BibleClip v{__version__}")
        self.root.minsize(900, 650)

        icon_path = os.path.join(BASE_DIR, "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        # State
        self.bible_dbs = {}
        self.monitoring = False
        self.monitor_thread = None
        self.last_clipboard = ''
        self.settings = dict(self.DEFAULT_SETTINGS)
        self._sync_lock = False        # viewer ↔ middle scroll sync guard
        self._sync_pending = False     # debounce pending
        self._tip = None               # hover tooltip window
        self._tip_after = None         # scheduled tooltip callback id
        self._tip_word = None          # (code, verse) under the cursor
        self._log_refs = []            # session-only clickable log references
        self._lex_popups = []          # open independent dictionary windows
        self._search_results = []      # current search results (book, chap, verse)

        # Load databases
        self._load_databases()
        self._load_bethlehem()

        # Load settings
        self._load_settings()

        self.theme = DARK_THEME if self.settings['dark_mode'] else LIGHT_THEME
        ctk.set_appearance_mode('dark' if self.settings['dark_mode'] else 'light')

        # Collect all themed widgets for easy re-theming
        self._themed_widgets = []

        # Build UI
        self._build_ui()
        self._apply_theme()

        # Initial viewer load — restore last position if available
        if self.bible_dbs:
            self._restore_last_position()

        # Update preview
        self._update_preview()

        # Restore panel split positions once the layout is realized
        self.root.after(120, self._restore_sash_positions)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Update banner placeholder + background check
        self.update_banner = None
        self.update_info = None
        if self.settings.get('auto_update_check', True):
            self._start_update_check()

    # ---- Database ----

    def _load_databases(self):
        db_dir = resolve_data_dir(BIBLE_DIR)
        if not os.path.isdir(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            return
        for fname in sorted(os.listdir(db_dir)):
            if fname.lower().endswith(('.sqlite3', '.sqlite', '.db')):
                path = os.path.join(db_dir, fname)
                try:
                    db = BibleDB(path)
                    self.bible_dbs[db.name] = db
                except Exception as e:
                    print(f"Error loading {fname}: {e}")

    def _load_bethlehem(self):
        """Load KRV-with-Strong's + lexicons from the original_lang folder."""
        self.bethlehem_strongs = None  # 개역한글S — KRV-based, drives middle panel
        self.bethlehem_wonjun = None   # 원전분해 — kept for potential future use
        self.lexicon_ko = None
        self.lexicon_en = None
        bdir = resolve_original_lang_dir(BASE_DIR)
        if not os.path.isdir(bdir):
            return
        strongs_path = os.path.join(bdir, '개역한글S.sdb')
        if os.path.exists(strongs_path):
            try:
                self.bethlehem_strongs = BethlehemDB(strongs_path)
            except Exception as e:
                print(f"개역한글S load error: {e}")
        wonjun_path = os.path.join(bdir, '원전분해.sdb')
        if os.path.exists(wonjun_path):
            try:
                self.bethlehem_wonjun = BethlehemDB(wonjun_path)
            except Exception as e:
                print(f"원전분해 load error: {e}")
        for fname, attr in (('HebGrkKo.dct', 'lexicon_ko'),
                            ('HebGrkEn.dct', 'lexicon_en')):
            p = os.path.join(bdir, fname)
            if os.path.exists(p):
                try:
                    setattr(self, attr, Lexicon(p))
                except Exception as e:
                    print(f"{fname} load error: {e}")

    def _bethlehem_ready(self):
        return bool(self.bethlehem_strongs and (self.lexicon_ko or self.lexicon_en))

    def _refresh_databases(self):
        """Rescan bible_versions folder for new DB files."""
        db_dir = resolve_data_dir(BIBLE_DIR)
        if not os.path.isdir(db_dir):
            return
        existing = set(self.bible_dbs.keys())
        for fname in sorted(os.listdir(db_dir)):
            if fname.lower().endswith(('.sqlite3', '.sqlite', '.db')):
                name = os.path.splitext(fname)[0]
                if name not in existing:
                    path = os.path.join(db_dir, fname)
                    try:
                        db = BibleDB(path)
                        self.bible_dbs[db.name] = db
                    except Exception:
                        pass
        # Update available list
        self._refresh_available_list()

    # ---- Settings ----

    def _load_settings(self):
        path = os.path.join(BASE_DIR, SETTINGS_FILE)
        # One-time migration: if the new file doesn't exist yet but the legacy
        # autobible_settings.json does, read from it. The next _save_settings
        # writes the new file; the legacy file is left untouched (rollback-safe).
        if not os.path.exists(path):
            legacy = os.path.join(BASE_DIR, LEGACY_SETTINGS_FILE)
            if os.path.exists(legacy):
                path = legacy
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                for k, v in saved.items():
                    if k in self.settings:
                        self.settings[k] = v
                geo = self.settings.get('geometry', '1100x780')
                self.root.geometry(geo)
            except Exception:
                self.root.geometry('1100x780')
        else:
            self.root.geometry('1100x780')

        # Validate output_order. When empty (fresh install), default to a
        # Korean version so clipboard monitoring produces output immediately
        # instead of silently doing nothing.
        valid_order = [n for n in self.settings['output_order'] if n in self.bible_dbs]
        if not valid_order and self.bible_dbs:
            versions = list(self.bible_dbs.keys())
            korean_pref = [v for v in ('KRV', 'NRKV', 'KNRSV') if v in versions]
            valid_order = [korean_pref[0] if korean_pref else versions[0]]
        self.settings['output_order'] = valid_order

        # Validate viewer_versions; default to KRV (or next-best Korean) when empty.
        valid_viewer = [n for n in self.settings.get('viewer_versions', []) if n in self.bible_dbs]
        # Migration from v1.0.0: previous default was alphabetical ['KNRSV'].
        # If the saved choice is exactly that default and KRV is available, switch.
        if valid_viewer == ['KNRSV'] and 'KRV' in self.bible_dbs:
            valid_viewer = ['KRV']
        if not valid_viewer and self.bible_dbs:
            versions = list(self.bible_dbs.keys())
            korean_pref = [v for v in ('KRV', 'NRKV', 'KNRSV') if v in versions]
            valid_viewer = [korean_pref[0] if korean_pref else versions[0]]
        self.settings['viewer_versions'] = valid_viewer

        # Validate viewer_version_order: must contain all loaded DBs in some order.
        saved_order = [n for n in self.settings.get('viewer_version_order', []) if n in self.bible_dbs]
        # Append any DBs missing from saved order (new files since last run)
        for n in self.bible_dbs:
            if n not in saved_order:
                saved_order.append(n)
        # Ensure checked versions appear in the order they were saved as checked
        if not saved_order:
            saved_order = list(self.bible_dbs.keys())
        self.settings['viewer_version_order'] = saved_order

        # Clamp font size
        try:
            self.settings['viewer_font_size'] = int(self.settings.get('viewer_font_size', 11))
        except (TypeError, ValueError):
            self.settings['viewer_font_size'] = 11
        self.settings['viewer_font_size'] = max(8, min(30, self.settings['viewer_font_size']))

    def _save_settings(self):
        self.settings['geometry'] = self.root.geometry()
        path = os.path.join(BASE_DIR, SETTINGS_FILE)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _get_format_settings(self):
        """Read current UI state into settings dict."""
        return dict(self.settings)

    # ---- UI ----

    def _build_ui(self):
        self.main_frame = ctk.CTkFrame(self.root, corner_radius=0,
                                       fg_color=CTK['app_bg'])
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Top bar
        self._build_top_bar()

        # Segmented tab switcher (replaces ttk.Notebook)
        self.tab_bar = ctk.CTkSegmentedButton(
            self.main_frame, values=["성경 보기", "출력 설정"],
            command=self._on_tab_change, font=(UI_FONT, 12, 'bold'),
            height=34, corner_radius=10,
            fg_color=CTK['btn'], selected_color=CTK['accent'],
            selected_hover_color=CTK['accent_hover'], unselected_color=CTK['btn'],
            unselected_hover_color=CTK['btn_hover'], text_color=CTK['btn_text'])
        self.tab_bar.pack(anchor='w', padx=14, pady=(0, 8))

        # Tab content container (tab frames remain tk so existing builders work)
        self.tab_container = ctk.CTkFrame(self.main_frame, corner_radius=0,
                                          fg_color=CTK['app_bg'])
        self.tab_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        self.tab_viewer = tk.Frame(self.tab_container)
        self.tab_settings = tk.Frame(self.tab_container)
        self._current_tab = 'viewer'
        self.tab_viewer.pack(fill=tk.BOTH, expand=True)

        self._build_viewer_tab()
        self._build_settings_tab()
        self.tab_bar.set("성경 보기")

    def _on_tab_change(self, value):
        self._show_tab('viewer' if value == "성경 보기" else 'settings')

    def _show_tab(self, name):
        """Switch the visible tab frame (replaces ttk.Notebook.select)."""
        self.tab_viewer.pack_forget()
        self.tab_settings.pack_forget()
        frame = self.tab_viewer if name == 'viewer' else self.tab_settings
        frame.pack(fill=tk.BOTH, expand=True)
        self._current_tab = name
        # .set() updates the segment without firing the command callback
        self.tab_bar.set("성경 보기" if name == 'viewer' else "출력 설정")

    def _build_top_bar(self):
        self.top_bar = ctk.CTkFrame(self.main_frame, fg_color=CTK['card'],
                                    corner_radius=14)
        self.top_bar.pack(fill=tk.X, padx=14, pady=(12, 8))

        self.title_label = ctk.CTkLabel(
            self.top_bar, text="BibleClip", font=(UI_FONT, 18, 'bold'),
            text_color=CTK['accent'])
        self.title_label.pack(side=tk.LEFT, padx=(18, 18), pady=9)

        self.monitor_btn = ctk.CTkButton(
            self.top_bar, text="모니터링 시작", command=self._toggle_monitoring,
            font=(UI_FONT, 12, 'bold'), corner_radius=999, width=128, height=34,
            fg_color=CTK['accent'], hover_color=CTK['accent_hover'],
            text_color=CTK['on_accent'])
        self.monitor_btn.pack(side=tk.LEFT, padx=4, pady=9)

        self.status_label = ctk.CTkLabel(
            self.top_bar, text="대기 중", font=(UI_FONT, 11, 'bold'),
            corner_radius=999, height=28,
            fg_color=CTK['status_off_bg'], text_color=CTK['status_off_fg'])
        self.status_label.pack(side=tk.LEFT, padx=10, pady=9, ipadx=8)

        self.dark_btn = ctk.CTkButton(
            self.top_bar,
            text="라이트 모드" if self.settings['dark_mode'] else "다크 모드",
            command=self._toggle_dark_mode,
            font=(UI_FONT, 11), corner_radius=999, width=94, height=32,
            fg_color=CTK['btn'], hover_color=CTK['btn_hover'],
            text_color=CTK['btn_text'])
        self.dark_btn.pack(side=tk.RIGHT, padx=(4, 18), pady=9)

        self.update_check_btn = ctk.CTkButton(
            self.top_bar, text="업데이트 확인", command=self._manual_update_check,
            font=(UI_FONT, 11), corner_radius=999, width=110, height=32,
            fg_color=CTK['btn'], hover_color=CTK['btn_hover'],
            text_color=CTK['btn_text'])
        self.update_check_btn.pack(side=tk.RIGHT, padx=4, pady=9)

    # ---- Viewer Tab ----



def main():
    # CustomTkinter root (Medium redesign). Appearance mode is set from the
    # saved dark_mode setting inside BibleClipApp.__init__.
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    BibleClipApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
