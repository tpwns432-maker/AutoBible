"""
BibleClip - Bible Verse Clipboard Monitor & Viewer
"""

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
# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class BibleClipApp:
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
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Top bar
        self._build_top_bar()

        # Notebook (tabs)
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        # Tab 1: Bible Viewer
        self.tab_viewer = tk.Frame(self.notebook)
        self.notebook.add(self.tab_viewer, text='  성경 보기  ')

        # Tab 2: Settings
        self.tab_settings = tk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text='  출력 설정  ')

        self._build_viewer_tab()
        self._build_settings_tab()

    def _build_top_bar(self):
        self.top_bar = tk.Frame(self.main_frame, height=48)
        self.top_bar.pack(fill=tk.X, padx=8, pady=6)

        self.title_label = tk.Label(self.top_bar, text="BibleClip",
                                      font=(UI_FONT, 16, 'bold'))
        self.title_label.pack(side=tk.LEFT, padx=(4, 20))

        self.monitor_btn = tk.Button(
            self.top_bar, text="  모니터링 시작  ", font=(UI_FONT, 10),
            relief=tk.FLAT, cursor='hand2', command=self._toggle_monitoring)
        self.monitor_btn.pack(side=tk.LEFT, padx=4)

        self.status_label = tk.Label(self.top_bar, text=" 대기 중 ",
                                       font=(UI_FONT, 9), padx=8, pady=2)
        self.status_label.pack(side=tk.LEFT, padx=8)

        self.dark_btn = tk.Button(
            self.top_bar, text="  다크 모드  ", font=(UI_FONT, 9),
            relief=tk.FLAT, cursor='hand2', command=self._toggle_dark_mode)
        self.dark_btn.pack(side=tk.RIGHT, padx=4)

        self.update_check_btn = tk.Button(
            self.top_bar, text=" 업데이트 확인 ", font=(UI_FONT, 9),
            relief=tk.FLAT, cursor='hand2', command=self._manual_update_check)
        self.update_check_btn.pack(side=tk.RIGHT, padx=4)

    # ---- Viewer Tab ----

    def _build_viewer_tab(self):
        # Layout:
        #   [version chips row + dict lang toggle on the right]
        #   [nav row: book/chap/prev/next/verse-jump/font]
        #   ├─ horizontal 3-panel: 본문 (50%) | 원어 (25%) | 사전 (25%) ─┤
        #   └─ activity log (full width across bottom)
        self.viewer_outer = self.tab_viewer

        # Version chip bar (multi-version parallel view + reorder) — top row
        version_bar = tk.Frame(self.tab_viewer)
        version_bar.pack(fill=tk.X, padx=4, pady=(4, 0))
        self.version_bar = version_bar

        tk.Label(version_bar, text="버전:", font=(UI_FONT, 9)).pack(side=tk.LEFT, padx=(0, 4))

        self.chip_frame = tk.Frame(version_bar)
        self.chip_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(version_bar, text="(클릭: 토글, 드래그: 순서 변경)",
                 font=(UI_FONT, 8)).pack(side=tk.LEFT, padx=(8, 0))

        # Initialize ordered viewer state from settings
        self._viewer_order = list(self.settings['viewer_version_order'])
        self._viewer_checked = set(self.settings['viewer_versions'])
        self._viewer_focused = self._viewer_order[0] if self._viewer_order else None
        self.viewer_chip_widgets = {}  # name -> outer Frame
        self.viewer_chip_labels = {}   # name -> inner Label
        self._render_viewer_versions()

        # Navigation
        nav = tk.Frame(self.tab_viewer)
        nav.pack(fill=tk.X, padx=4, pady=(4, 0))
        self.nav_frame = nav

        tk.Label(nav, text="책:", font=(UI_FONT, 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.book_var = tk.StringVar()
        self.book_combo = ttk.Combobox(nav, textvariable=self.book_var,
                                        state='readonly', width=14)
        self.book_combo.pack(side=tk.LEFT, padx=(0, 8))
        self.book_combo.bind('<<ComboboxSelected>>', self._on_book_changed)

        tk.Label(nav, text="장:", font=(UI_FONT, 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.chapter_var = tk.StringVar()
        self.chapter_combo = ttk.Combobox(nav, textvariable=self.chapter_var,
                                            state='readonly', width=5)
        self.chapter_combo.pack(side=tk.LEFT, padx=(0, 8))
        self.chapter_combo.bind('<<ComboboxSelected>>', self._on_chapter_changed)

        self.prev_btn = tk.Button(nav, text=" < ", font=(UI_FONT, 9),
                                    relief=tk.FLAT, cursor='hand2', command=self._prev_chapter)
        self.prev_btn.pack(side=tk.LEFT, padx=2)
        self.next_btn = tk.Button(nav, text=" > ", font=(UI_FONT, 9),
                                    relief=tk.FLAT, cursor='hand2', command=self._next_chapter)
        self.next_btn.pack(side=tk.LEFT, padx=2)

        tk.Label(nav, text="절:", font=(UI_FONT, 9)).pack(side=tk.LEFT, padx=(12, 4))
        self.verse_jump_var = tk.StringVar()
        self.verse_jump_entry = tk.Entry(nav, textvariable=self.verse_jump_var,
                                           width=5, font=(UI_FONT, 9))
        self.verse_jump_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.verse_jump_entry.bind('<Return>', self._on_verse_jump)
        self.jump_btn = tk.Button(nav, text="이동", font=(UI_FONT, 9),
                                    relief=tk.FLAT, cursor='hand2',
                                    command=lambda: self._on_verse_jump(None))
        self.jump_btn.pack(side=tk.LEFT)

        # Keyword search ( "#태초에" or just "태초에" )
        self.search_label = tk.Label(nav, text="검색:", font=(UI_FONT, 9))
        self.search_label.pack(side=tk.LEFT, padx=(14, 4))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(nav, textvariable=self.search_var,
                                     width=12, font=(UI_FONT, 9))
        self.search_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry.bind('<Return>', self._on_search_box)
        self.search_btn = tk.Button(nav, text="검색", font=(UI_FONT, 9),
                                    relief=tk.FLAT, cursor='hand2',
                                    command=lambda: self._on_search_box(None))
        self.search_btn.pack(side=tk.LEFT)

        # Font size controls (rightmost)
        self.font_plus_btn = tk.Button(nav, text=" A+ ", font=(UI_FONT, 9),
                                         relief=tk.FLAT, cursor='hand2',
                                         command=lambda: self._change_font_size(1))
        self.font_plus_btn.pack(side=tk.RIGHT, padx=2)
        self.font_minus_btn = tk.Button(nav, text=" A- ", font=(UI_FONT, 9),
                                          relief=tk.FLAT, cursor='hand2',
                                          command=lambda: self._change_font_size(-1))
        self.font_minus_btn.pack(side=tk.RIGHT, padx=2)

        # Dictionary language toggle (right side, before font buttons in pack order
        # so visually it appears to the left of A-/A+ since side=RIGHT stacks RTL)
        has_ko = self.lexicon_ko is not None
        has_en = self.lexicon_en is not None
        default_lang = 'ko' if has_ko else 'en'
        self.lex_lang_var = tk.StringVar(value=default_lang)
        self.lex_lang_en_rb = tk.Radiobutton(
            nav, text='영어', variable=self.lex_lang_var, value='en',
            font=(UI_FONT, 9),
            state=(tk.NORMAL if has_en else tk.DISABLED),
            command=self._on_lex_lang_changed)
        self.lex_lang_en_rb.pack(side=tk.RIGHT)
        self.lex_lang_ko_rb = tk.Radiobutton(
            nav, text='한글', variable=self.lex_lang_var, value='ko',
            font=(UI_FONT, 9),
            state=(tk.NORMAL if has_ko else tk.DISABLED),
            command=self._on_lex_lang_changed)
        self.lex_lang_ko_rb.pack(side=tk.RIGHT)
        self.lex_lang_label = tk.Label(nav, text="사전:", font=(UI_FONT, 9))
        self.lex_lang_label.pack(side=tk.RIGHT, padx=(8, 4))

        # Main vertical PanedWindow: 3-panel area (top) + activity log (bottom)
        vpw = tk.PanedWindow(self.tab_viewer, orient=tk.VERTICAL, sashwidth=4)
        vpw.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.viewer_pane = vpw

        # Top: horizontal PanedWindow with 3 panels
        main_top = tk.Frame(vpw)
        vpw.add(main_top, minsize=240, stretch="always")
        hpw = tk.PanedWindow(main_top, orient=tk.HORIZONTAL, sashwidth=4)
        hpw.pack(fill=tk.BOTH, expand=True)
        self.viewer_hpane = hpw

        # Panel 1: regular Bible viewer (existing)
        tf = tk.Frame(hpw)
        hpw.add(tf, minsize=300, stretch="always")
        self.viewer_text_frame = tf
        self.viewer_text = tk.Text(tf, font=(BODY_FONT, 11), wrap=tk.WORD,
                                     state=tk.DISABLED, spacing1=3, spacing3=4,
                                     padx=18, pady=14)
        self.viewer_scroll = tk.Scrollbar(tf, command=self.viewer_text.yview)
        self.viewer_text.configure(yscrollcommand=self._on_viewer_yscroll)
        self.viewer_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.viewer_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Panel 2: original-language Korean + Strong's code (clickable)
        mid = tk.Frame(hpw)
        hpw.add(mid, minsize=150, stretch="always")
        self.lex_mid_frame = mid
        self.lex_mid_label = tk.Label(mid, text="원어 (단어 클릭)", font=(UI_FONT, 9, 'bold'))
        self.lex_mid_label.pack(anchor=tk.W, padx=8, pady=(4, 0))
        mf = tk.Frame(mid)
        mf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.lex_mid_text = tk.Text(mf, font=(BODY_FONT, 10), wrap=tk.WORD,
                                      state=tk.DISABLED, spacing1=3, spacing3=3,
                                      padx=12, pady=10)
        self.lex_mid_scroll = tk.Scrollbar(mf, command=self.lex_mid_text.yview)
        self.lex_mid_text.configure(yscrollcommand=self.lex_mid_scroll.set)
        self.lex_mid_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lex_mid_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lex_mid_text.tag_configure('lex_vnum', font=(BODY_FONT, 9, 'bold'))
        self.lex_mid_text.tag_configure('lex_word')
        self.lex_mid_text.tag_bind('lex_word', '<Enter>',
                                    lambda e: self.lex_mid_text.configure(cursor='hand2'))
        self.lex_mid_text.tag_bind('lex_word', '<Leave>',
                                    lambda e: self.lex_mid_text.configure(cursor=''))
        self.lex_mid_text.bind('<Button-1>', self._on_lex_word_click)
        # Right-click (Win/Linux Button-3; macOS two-finger/right) opens a window.
        self.lex_mid_text.bind('<Button-3>', self._on_lex_word_popup)
        if sys.platform == 'darwin':
            self.lex_mid_text.bind('<Button-2>', self._on_lex_word_popup)
            self.lex_mid_text.bind('<Command-Button-1>', self._on_lex_word_popup)
        self.lex_mid_text.bind('<Motion>', self._on_lex_hover)
        self.lex_mid_text.bind('<Leave>', self._on_lex_hover_leave)

        # Panel 3: dictionary entry
        rg = tk.Frame(hpw)
        hpw.add(rg, minsize=150, stretch="always")
        self.lex_right_frame = rg
        self.lex_right_label = tk.Label(rg, text="사전", font=(UI_FONT, 9, 'bold'))
        self.lex_right_label.pack(anchor=tk.W, padx=8, pady=(4, 0))
        rgf = tk.Frame(rg)
        rgf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.lex_right_text = tk.Text(rgf, font=(BODY_FONT, 10), wrap=tk.WORD,
                                        state=tk.DISABLED, spacing1=3, spacing3=3,
                                        padx=12, pady=10)
        self.lex_right_scroll = tk.Scrollbar(rgf, command=self.lex_right_text.yview)
        self.lex_right_text.configure(yscrollcommand=self.lex_right_scroll.set)
        self.lex_right_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lex_right_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._current_lex_code = None

        # Bottom: activity log spanning the full width across the 3 panels
        log_frame = tk.Frame(vpw)
        vpw.add(log_frame, minsize=80, stretch="never")
        self.log_frame = log_frame

        log_header = tk.Frame(log_frame)
        log_header.pack(fill=tk.X, padx=8, pady=(4, 2))
        self.log_header = log_header
        log_lbl = tk.Label(log_header, text="활동 로그  (구절 클릭 → 이동)",
                           font=(UI_FONT, 9, 'bold'))
        log_lbl.pack(side=tk.LEFT)
        self._log_label = log_lbl

        log_inner = tk.Frame(log_frame)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
        self.log_text = tk.Text(log_inner, font=(MONO_FONT, 9), wrap=tk.WORD,
                                  state=tk.DISABLED, height=4)
        self.log_scroll = tk.Scrollbar(log_inner, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.tag_configure('logref', underline=True)
        self.log_text.tag_bind('logref', '<Enter>',
                               lambda e: self.log_text.configure(cursor='hand2'))
        self.log_text.tag_bind('logref', '<Leave>',
                               lambda e: self.log_text.configure(cursor=''))

        self._apply_viewer_font()

        # Search-result clickable styling
        self.viewer_text.tag_configure('search_head', font=(UI_FONT, 10, 'bold'))
        self.viewer_text.tag_bind('sr_click', '<Enter>',
                                  lambda e: self.viewer_text.configure(cursor='hand2'))
        self.viewer_text.tag_bind('sr_click', '<Leave>',
                                  lambda e: self.viewer_text.configure(cursor=''))

        # Click/drag → copy formatted; Ctrl+wheel → font size (all panels)
        self.viewer_text.bind('<ButtonRelease-1>', self._on_viewer_text_release)
        self.viewer_text.bind('<Control-MouseWheel>', self._on_ctrl_wheel)
        self.lex_mid_text.bind('<Control-MouseWheel>', self._on_ctrl_wheel)
        self.lex_right_text.bind('<Control-MouseWheel>', self._on_ctrl_wheel)

        # Arrow keys move between chapters (when not typing in a field)
        self.root.bind('<Left>', self._on_arrow_prev)
        self.root.bind('<Right>', self._on_arrow_next)

        self._populate_books()

    # ---- Settings Tab ----

    def _build_settings_tab(self):
        # Two columns: left = version order, right = format settings + preview
        pw = tk.PanedWindow(self.tab_settings, orient=tk.HORIZONTAL, sashwidth=4)
        pw.pack(fill=tk.BOTH, expand=True)
        self.settings_pane = pw

        # ===== LEFT: Version selection & ordering =====
        left = tk.Frame(pw)
        pw.add(left, minsize=400, stretch="never")
        self.settings_left = left

        # Title
        lbl = tk.Label(left, text="성경 버전 선택 / 출력 순서",
                        font=(UI_FONT, 10, 'bold'))
        lbl.pack(anchor=tk.W, padx=8, pady=(8, 4))

        # Dual listbox area
        dual_frame = tk.Frame(left)
        dual_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        # Available list
        avail_frame = tk.Frame(dual_frame)
        avail_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(avail_frame, text="성경 목록", font=(UI_FONT, 9)).pack(anchor=tk.W)
        self.avail_listbox = tk.Listbox(avail_frame, font=(UI_FONT, 9),
                                          selectmode=tk.EXTENDED, height=10)
        self.avail_listbox.pack(fill=tk.BOTH, expand=True)

        # Buttons between lists
        btn_frame = tk.Frame(dual_frame)
        btn_frame.pack(side=tk.LEFT, padx=8, pady=20)
        self.add_btn = tk.Button(btn_frame, text=" 추가 → ", font=(UI_FONT, 9),
                                   relief=tk.FLAT, cursor='hand2', command=self._add_to_order)
        self.add_btn.pack(pady=4)
        self.remove_btn = tk.Button(btn_frame, text=" ← 제거 ", font=(UI_FONT, 9),
                                      relief=tk.FLAT, cursor='hand2', command=self._remove_from_order)
        self.remove_btn.pack(pady=4)
        self.refresh_btn = tk.Button(btn_frame, text="새로고침", font=(UI_FONT, 9),
                                       relief=tk.FLAT, cursor='hand2', command=self._refresh_databases)
        self.refresh_btn.pack(pady=(12, 4))

        # Order list
        order_frame = tk.Frame(dual_frame)
        order_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(order_frame, text="성경 출력 순서", font=(UI_FONT, 9)).pack(anchor=tk.W)
        self.order_listbox = tk.Listbox(order_frame, font=(UI_FONT, 9),
                                          selectmode=tk.SINGLE, height=10)
        self.order_listbox.pack(fill=tk.BOTH, expand=True)

        # Order control buttons
        order_btn_frame = tk.Frame(left)
        order_btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.up_btn = tk.Button(order_btn_frame, text=" ▲ 위로 ", font=(UI_FONT, 9),
                                  relief=tk.FLAT, cursor='hand2', command=self._move_up)
        self.up_btn.pack(side=tk.LEFT, padx=4)
        self.down_btn = tk.Button(order_btn_frame, text=" ▼ 아래로 ", font=(UI_FONT, 9),
                                    relief=tk.FLAT, cursor='hand2', command=self._move_down)
        self.down_btn.pack(side=tk.LEFT, padx=4)
        self.clear_btn = tk.Button(order_btn_frame, text=" 모두 제거 ", font=(UI_FONT, 9),
                                     relief=tk.FLAT, cursor='hand2', command=self._clear_order)
        self.clear_btn.pack(side=tk.RIGHT, padx=4)

        # Populate lists
        self._refresh_available_list()
        for name in self.settings['output_order']:
            if name in self.bible_dbs:
                self.order_listbox.insert(tk.END, self.bible_dbs[name].display_name)

        # ===== RIGHT: Format settings + preview =====
        right = tk.Frame(pw)
        pw.add(right, minsize=420, stretch="always")
        self.settings_right = right

        # Scrollable settings area
        canvas = tk.Canvas(right, highlightthickness=0)
        scrollbar = tk.Scrollbar(right, orient=tk.VERTICAL, command=canvas.yview)
        self.settings_scroll_frame = tk.Frame(canvas)
        self.settings_canvas = canvas
        self.settings_scrollbar = scrollbar

        self.settings_scroll_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.settings_scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add='+')

        sf = self.settings_scroll_frame  # shorthand

        # --- 표기 설정 (한국어 버전용) ---
        tk.Label(sf, text="표기 설정 (한국어 버전용)", font=(UI_FONT, 10, 'bold')).pack(
            anchor=tk.W, padx=8, pady=(8, 4))
        tk.Label(sf, text="※ 영어 성경(ESV/NKJV 등)은 항상 영어식+하이픈으로 출력됩니다.",
                 font=(UI_FONT, 8)).pack(anchor=tk.W, padx=12)

        # Book name style
        f1 = tk.LabelFrame(sf, text=" 책 이름 ", font=(UI_FONT, 9))
        f1.pack(fill=tk.X, padx=12, pady=4)
        self.book_name_var = tk.StringVar(value=self.settings['book_name'])
        for val, txt in [('long_ko', '한글 정식'), ('short_ko', '한글 약칭'),
                         ('long_en', '영문 정식'), ('short_en', '영문 약칭')]:
            rb = tk.Radiobutton(f1, text=txt, variable=self.book_name_var, value=val,
                                font=(UI_FONT, 9), command=self._on_setting_changed)
            rb.pack(side=tk.LEFT, padx=8, pady=4)

        # Chapter:Verse format
        f2 = tk.LabelFrame(sf, text=" 장절 표기 ", font=(UI_FONT, 9))
        f2.pack(fill=tk.X, padx=12, pady=4)
        self.cv_format_var = tk.StringVar(value=self.settings['chapter_verse_format'])
        for val, txt in [('colon', '1:1'), ('korean', '1장 1절')]:
            rb = tk.Radiobutton(f2, text=txt, variable=self.cv_format_var, value=val,
                                font=(UI_FONT, 9), command=self._on_setting_changed)
            rb.pack(side=tk.LEFT, padx=8, pady=4)

        # Bracket style
        f3 = tk.LabelFrame(sf, text=" 괄호 ", font=(UI_FONT, 9))
        f3.pack(fill=tk.X, padx=12, pady=4)
        self.bracket_var = tk.StringVar(value=self.settings['bracket_style'])
        for val, txt in [('none', '없음'), ('[]', '[ ]'), ('()', '( )')]:
            rb = tk.Radiobutton(f3, text=txt, variable=self.bracket_var, value=val,
                                font=(UI_FONT, 9), command=self._on_setting_changed)
            rb.pack(side=tk.LEFT, padx=8, pady=4)

        # Reference position
        f4 = tk.LabelFrame(sf, text=" 표기 위치 ", font=(UI_FONT, 9))
        f4.pack(fill=tk.X, padx=12, pady=4)
        self.position_var = tk.StringVar(value=self.settings['ref_position'])
        for val, txt in [('before', '본문 앞'), ('after', '본문 뒤')]:
            rb = tk.Radiobutton(f4, text=txt, variable=self.position_var, value=val,
                                font=(UI_FONT, 9), command=self._on_setting_changed)
            rb.pack(side=tk.LEFT, padx=8, pady=4)

        # Range symbol
        f5 = tk.LabelFrame(sf, text=" 범위 연결 기호 ", font=(UI_FONT, 9))
        f5.pack(fill=tk.X, padx=12, pady=4)
        self.range_var = tk.StringVar(value=self.settings['range_symbol'])
        for val, txt in [('-', '-'), ('~', '~')]:
            rb = tk.Radiobutton(f5, text=txt, variable=self.range_var, value=val,
                                font=(UI_FONT, 9), command=self._on_setting_changed)
            rb.pack(side=tk.LEFT, padx=8, pady=4)

        # Ref-body separator
        f6 = tk.LabelFrame(sf, text=" 레퍼런스-본문 구분 기호 ", font=(UI_FONT, 9))
        f6.pack(fill=tk.X, padx=12, pady=4)
        self.sep_var = tk.StringVar(value=self.settings['ref_body_separator'])
        for val, txt in [(' - ', '하이픈 (-)'), (': ', '콜론 (:)'), (' ', '띄어쓰기')]:
            rb = tk.Radiobutton(f6, text=txt, variable=self.sep_var, value=val,
                                font=(UI_FONT, 9), command=self._on_setting_changed)
            rb.pack(side=tk.LEFT, padx=8, pady=4)

        # Output mode
        f7 = tk.LabelFrame(sf, text=" 다절 출력 방식 ", font=(UI_FONT, 9))
        f7.pack(fill=tk.X, padx=12, pady=4)
        self.output_mode_var = tk.StringVar(value=self.settings['output_mode'])
        for val, txt in [('inline', '여러 절을 한 줄로'), ('newline', '각 절을 줄마다')]:
            rb = tk.Radiobutton(f7, text=txt, variable=self.output_mode_var, value=val,
                                font=(UI_FONT, 9), command=self._on_setting_changed)
            rb.pack(side=tk.LEFT, padx=8, pady=4)

        # Newline sub-option: show chapter:verse
        self.newline_cv_var = tk.BooleanVar(value=self.settings['newline_show_cv'])
        self.newline_cv_check = tk.Checkbutton(
            f7, text='줄마다 장:절 표시', variable=self.newline_cv_var,
            font=(UI_FONT, 9), command=self._on_setting_changed)
        self.newline_cv_check.pack(side=tk.LEFT, padx=8, pady=4)

        # Misc checkboxes
        f8 = tk.LabelFrame(sf, text=" 기타 ", font=(UI_FONT, 9))
        f8.pack(fill=tk.X, padx=12, pady=4)
        self.version_header_var = tk.BooleanVar(value=self.settings['show_version_header'])
        cb1 = tk.Checkbutton(f8, text='버전 헤더 출력', variable=self.version_header_var,
                             font=(UI_FONT, 9), command=self._on_setting_changed)
        cb1.pack(side=tk.LEFT, padx=8, pady=4)
        self.hide_ref_var = tk.BooleanVar(value=self.settings['hide_reference'])
        cb2 = tk.Checkbutton(f8, text='장절 표기 숨기기 (본문만)', variable=self.hide_ref_var,
                             font=(UI_FONT, 9), command=self._on_setting_changed)
        cb2.pack(side=tk.LEFT, padx=8, pady=4)

        # Separator
        tk.Frame(sf, height=2, bg='#CCCCCC').pack(fill=tk.X, padx=8, pady=8)

        # Preview
        preview_header = tk.Frame(sf)
        preview_header.pack(fill=tk.X, padx=8)
        tk.Label(preview_header, text="미리보기 (예시: 요 1:1-3)",
                 font=(UI_FONT, 10, 'bold')).pack(side=tk.LEFT)
        self.preview_refresh_btn = tk.Button(
            preview_header, text="미리보기 새로고침", font=(UI_FONT, 8),
            relief=tk.FLAT, cursor='hand2', command=self._update_preview)
        self.preview_refresh_btn.pack(side=tk.RIGHT)

        self.preview_text = tk.Text(sf, font=(BODY_FONT, 10), wrap=tk.WORD,
                                      height=12, state=tk.DISABLED, padx=8, pady=8)
        self.preview_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        # Collect all labelframes and their children for theming
        self._settings_labelframes = [f1, f2, f3, f4, f5, f6, f7, f8]
        self._settings_header_labels = []
        for w in sf.winfo_children():
            if isinstance(w, tk.Label):
                self._settings_header_labels.append(w)

    # ---- Lexicon (원어 사전) helpers — used by viewer tab ----

    def _render_lex_middle(self, our_bn, chapter):
        text = self.lex_mid_text
        self._lex_hl_code = None   # tags are recreated below; clear stale highlight
        text.configure(state=tk.NORMAL)
        text.delete('1.0', tk.END)
        if not self.bethlehem_strongs:
            text.insert(tk.END, "원어 사전 데이터가 없습니다.\n"
                                f"{ORIGINAL_LANG_DIR} 폴더에 개역한글S.sdb가 필요합니다.")
            text.configure(state=tk.DISABLED)
            return
        verses = self.bethlehem_strongs.get_chapter_verses(our_bn, chapter)
        for vn, btext in verses:
            block = f'vb_{vn}'
            words = parse_korean_strongs(btext)
            text.insert(tk.END, f"{vn}  ", ('lex_vnum', block))
            for i, (word, code) in enumerate(words):
                if i > 0:
                    text.insert(tk.END, ' ', (block,))
                if code and code not in ('H0', 'G0'):
                    tag = f"sw_{code}"
                    text.tag_configure(tag)  # marker tag for click identification
                    text.insert(tk.END, f"{word}[{code}]", ('lex_word', tag, block))
                else:
                    text.insert(tk.END, word, (block,))
            text.insert(tk.END, '\n\n', (block,))
        text.configure(state=tk.DISABLED)

    def _lex_word_at(self, event):
        """Return (code, verse) for the word under the event, or (None, None)."""
        idx = self.lex_mid_text.index(f"@{event.x},{event.y}")
        code = verse = None
        for tag in self.lex_mid_text.tag_names(idx):
            if tag.startswith('sw_'):
                code = tag[3:]
            elif tag.startswith('vb_'):
                try:
                    verse = int(tag[3:])
                except ValueError:
                    pass
        return code, verse

    def _on_lex_word_click(self, event):
        code, verse = self._lex_word_at(event)
        if not code:
            return
        self._hide_tip()
        self._highlight_lex_code(code)
        if event.state & 0x0004:   # Control held → independent window
            self._open_lex_popup(code, verse)
        else:
            self._show_lex_entry(code, verse)

    def _on_lex_word_popup(self, event):
        """Right-click / Command-click → open an independent dictionary window."""
        code, verse = self._lex_word_at(event)
        if not code:
            return
        self._hide_tip()
        self._highlight_lex_code(code)
        self._open_lex_popup(code, verse)
        return 'break'

    def _highlight_lex_code(self, code):
        """Highlight every occurrence of `code` (same Strong's number) in the
        original-language panel by tinting its shared sw_<code> tag."""
        prev = getattr(self, '_lex_hl_code', None)
        if prev and prev != code:
            try:
                self.lex_mid_text.tag_configure(f'sw_{prev}', background='')
            except Exception:
                pass
        self._lex_hl_code = code
        if code:
            try:
                self.lex_mid_text.tag_configure(
                    f'sw_{code}', background=self.theme['lex_hl_bg'])
            except Exception:
                pass

    # ---- Hover preview ----

    def _on_lex_hover(self, event):
        idx = self.lex_mid_text.index(f"@{event.x},{event.y}")
        code = verse = None
        for tag in self.lex_mid_text.tag_names(idx):
            if tag.startswith('sw_'):
                code = tag[3:]
            elif tag.startswith('vb_'):
                try:
                    verse = int(tag[3:])
                except ValueError:
                    pass
        if code is None:
            self._tip_word = None
            self._hide_tip()
            return
        key = (code, verse)
        if key == self._tip_word:
            return  # already scheduled/shown for this word
        self._tip_word = key
        self._hide_tip()
        x, y = event.x_root + 16, event.y_root + 14
        self._tip_after = self.root.after(
            450, lambda c=code, v=verse, px=x, py=y: self._show_tip(c, v, px, py))

    def _on_lex_hover_leave(self, event):
        self._tip_word = None
        self._hide_tip()

    def _hover_summary(self, code, verse):
        lines = []
        if (self.bethlehem_wonjun and verse
                and getattr(self, '_lex_current_book', None)):
            try:
                rows = self.bethlehem_wonjun.get_chapter_verses(
                    self._lex_current_book, self._lex_current_chapter)
                bt = next((t for vn, t in rows if vn == verse), None)
            except Exception:
                bt = None
            if bt:
                for w in parse_wonjun_verse(bt):
                    if w['code'] == code:
                        s = w['lemma']
                        if w['translit']:
                            s += f" ({w['translit']})"
                        if w['gloss'] and w['gloss'] != '_':
                            s += f" — {w['gloss']}"
                        lines.append(s)
                        if w['pos']:
                            lines.append(w['pos'])
                        break
        if not lines:
            lex = self.lexicon_ko or self.lexicon_en
            entry = lex.lookup(code) if lex else None
            if entry:
                txt = re.sub(r'<[^>]+>', '', entry).replace('^', ' ')
                txt = re.sub(r'\s+', ' ', txt).strip()
                if txt:
                    lines.append(txt[:90] + ('…' if len(txt) > 90 else ''))
        head = f"[{code}]"
        return head + ('\n' + '\n'.join(lines) if lines else '')

    def _show_tip(self, code, verse, x, y):
        text = self._hover_summary(code, verse)
        if not text:
            return
        self._hide_tip()
        t = getattr(self, 'theme', LIGHT_THEME)
        tip = tk.Toplevel(self.root)
        tip.wm_overrideredirect(True)
        try:
            tip.wm_attributes('-topmost', True)
        except Exception:
            pass
        tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(tip, text=text, justify=tk.LEFT, font=(UI_FONT, 11),
                       bg=t['preview_bg'], fg=t['preview_fg'],
                       relief=tk.SOLID, borderwidth=1, padx=14, pady=12,
                       wraplength=520)
        lbl.pack(ipadx=6, ipady=4)
        self._tip = tip

    def _hide_tip(self):
        if self._tip_after:
            try:
                self.root.after_cancel(self._tip_after)
            except Exception:
                pass
            self._tip_after = None
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _on_lex_lang_changed(self):
        if self._current_lex_code:
            self._show_lex_entry(self._current_lex_code,
                                 getattr(self, '_current_lex_verse', None))

    def _morphology_html(self, code, verse):
        """Short morphology line(s) for `code` in `verse` from 원전분해.sdb."""
        if not (self.bethlehem_wonjun and verse
                and getattr(self, '_lex_current_book', None)):
            return ''
        try:
            rows = self.bethlehem_wonjun.get_chapter_verses(
                self._lex_current_book, self._lex_current_chapter)
        except Exception:
            return ''
        btext = next((t for vn, t in rows if vn == verse), None)
        if not btext:
            return ''
        matches = [w for w in parse_wonjun_verse(btext) if w['code'] == code]
        if not matches:
            return ''
        lines = []
        for w in matches:
            seg = f"<b>{w['lemma']}</b>"
            if w['translit']:
                seg += f" {w['translit']}"
            if w['pos']:
                seg += f"  ·  {w['pos']}"
            if w['gloss'] and w['gloss'] != '_':
                seg += f"  ·  {w['gloss']}"
            lines.append(seg)
        return ("<font color='#3286EA'>[형태소 분석]</font><br>"
                + '<br>'.join(lines) + "<br><br>")

    def _show_lex_entry(self, code, verse=None):
        self._current_lex_code = code
        self._current_lex_verse = verse
        lang = self.lex_lang_var.get()
        lex = self.lexicon_ko if lang == 'ko' else self.lexicon_en
        morph = self._morphology_html(code, verse)
        fg = self.theme['viewer_fg'] if hasattr(self, 'theme') else '#000000'
        entry = lex.lookup(code) if lex else None
        if entry is None:
            body = f"{morph}<b>[{code}]</b><br><br>사전 항목 없음"
        else:
            body = f"{morph}<b>[{code}]</b><br><br>{entry}"
        render_dict_html(self.lex_right_text, body, fg=fg, num_color=self.theme['accent'])

    # ---- Independent dictionary windows (Ctrl+click) ----

    def _open_lex_popup(self, code, verse):
        t = getattr(self, 'theme', LIGHT_THEME)
        top = tk.Toplevel(self.root)
        top.title(f"사전 - [{code}]")
        size = self.settings.get('lex_popup_size', '440x480')
        n = len(self._lex_popups)
        off = 36 + (n % 6) * 26
        try:
            top.geometry(f"{size}+{self.root.winfo_rootx() + off}"
                         f"+{self.root.winfo_rooty() + off}")
        except Exception:
            top.geometry(size)
        try:
            if IS_WINDOWS:
                top.iconbitmap(os.path.join(BASE_DIR, 'icon.ico'))
        except Exception:
            pass
        top.configure(bg=t['bg'])
        frame = tk.Frame(top, bg=t['bg'])
        frame.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(frame, font=(BODY_FONT, 11), wrap=tk.WORD, state=tk.DISABLED,
                      bg=t['viewer_bg'], fg=t['viewer_fg'], padx=10, pady=8,
                      insertbackground=t['fg'],
                      selectbackground=t['select_bg'], selectforeground=t['select_fg'])
        sb = tk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._style_scrollbar(sb)

        lang = self.lex_lang_var.get()
        lex = self.lexicon_ko if lang == 'ko' else self.lexicon_en
        morph = self._morphology_html(code, verse)
        entry = lex.lookup(code) if lex else None
        body = (f"{morph}<b>[{code}]</b><br><br>"
                + (entry if entry is not None else "사전 항목 없음"))
        render_dict_html(txt, body, fg=t['viewer_fg'], num_color=t['accent'])

        self._lex_popups.append(top)

        def on_close():
            try:
                sz = top.geometry().split('+')[0]
                if 'x' in sz:
                    self.settings['lex_popup_size'] = sz
            except Exception:
                pass
            try:
                self._lex_popups.remove(top)
            except ValueError:
                pass
            top.destroy()

        top.protocol("WM_DELETE_WINDOW", on_close)
        top.bind('<Escape>', lambda e: on_close())

    # ---- Version order management ----

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

    def _render_viewer_versions(self):
        """(Re)build the chip row according to self._viewer_order."""
        for w in self.chip_frame.winfo_children():
            w.destroy()
        self.viewer_chip_widgets = {}
        self.viewer_chip_labels = {}
        for name in self._viewer_order:
            self._build_chip(name)
        self._highlight_focused_chip()
        self._apply_viewer_chip_theme()

    def _build_chip(self, name):
        is_checked = name in self._viewer_checked
        outer = tk.Frame(self.chip_frame, relief=tk.SOLID, borderwidth=1,
                         padx=8, pady=3, cursor='fleur')
        label_text = f"{'☑' if is_checked else '☐'} {name}"
        lbl = tk.Label(outer, text=label_text, font=(UI_FONT, 9), cursor='fleur')
        lbl.pack()
        outer.pack(side=tk.LEFT, padx=3, pady=2)
        self.viewer_chip_widgets[name] = outer
        self.viewer_chip_labels[name] = lbl

        # Per-chip drag state
        state = {'press_x': 0, 'press_y': 0, 'dragging': False}

        def on_press(event):
            state['press_x'] = event.x_root
            state['press_y'] = event.y_root
            state['dragging'] = False
            self._set_viewer_focused(name)

        def on_motion(event):
            dx = abs(event.x_root - state['press_x'])
            dy = abs(event.y_root - state['press_y'])
            if not state['dragging'] and (dx > 4 or dy > 4):
                state['dragging'] = True
                outer.configure(relief=tk.SUNKEN)
            if state['dragging']:
                self._show_drop_indicator(name, event.x_root)

        def on_release(event):
            if state['dragging']:
                outer.configure(relief=tk.SOLID)
                pos = self._get_drop_position(event.x_root)
                self._clear_drop_indicator()
                if pos:
                    tgt_name, drop_after = pos
                    self._reorder_drop(name, tgt_name, drop_after)
            else:
                self._on_viewer_check_toggle(name)

        for w in (outer, lbl):
            w.bind('<ButtonPress-1>', on_press)
            w.bind('<B1-Motion>', on_motion)
            w.bind('<ButtonRelease-1>', on_release)

    def _set_viewer_focused(self, name):
        self._viewer_focused = name
        self._highlight_focused_chip()

    def _highlight_focused_chip(self):
        t = getattr(self, 'theme', None)
        if not t:
            return
        accent = t['accent']
        border = t['border']
        for n, w in self.viewer_chip_widgets.items():
            if n == self._viewer_focused:
                w.configure(highlightthickness=2,
                            highlightbackground=accent, highlightcolor=accent)
            else:
                w.configure(highlightthickness=0,
                            highlightbackground=border, highlightcolor=border)

    def _on_viewer_check_toggle(self, name):
        if name in self._viewer_checked:
            self._viewer_checked.discard(name)
        else:
            self._viewer_checked.add(name)
        self._viewer_focused = name
        self._save_viewer_state()
        self._render_viewer_versions()
        self._populate_books()
        self._on_book_changed(None)

    # ---- Drag-drop helpers ----

    def _get_drop_position(self, x_root):
        """Return (target_name, drop_after_target) for cursor x position, or None."""
        chips = [(n, self.viewer_chip_widgets[n]) for n in self._viewer_order
                 if n in self.viewer_chip_widgets]
        if not chips:
            return None
        for n, w in chips:
            try:
                wx = w.winfo_rootx()
                ww = w.winfo_width()
            except tk.TclError:
                continue
            if wx <= x_root <= wx + ww:
                return n, x_root > (wx + ww / 2)
        # Outside any chip — clamp to ends.
        try:
            first_n, first_w = chips[0]
            last_n, last_w = chips[-1]
            if x_root < first_w.winfo_rootx():
                return first_n, False
            return last_n, True
        except tk.TclError:
            return None

    def _show_drop_indicator(self, dragged_name, x_root):
        pos = self._get_drop_position(x_root)
        if not pos:
            self._clear_drop_indicator()
            return
        tgt_name, _ = pos
        if tgt_name == dragged_name:
            self._clear_drop_indicator()
            return
        accent = self.theme['accent']
        border = self.theme['border']
        for n, w in self.viewer_chip_widgets.items():
            if n == tgt_name:
                w.configure(highlightthickness=2,
                            highlightbackground=accent, highlightcolor=accent)
            elif n == self._viewer_focused:
                w.configure(highlightthickness=2,
                            highlightbackground=accent, highlightcolor=accent)
            else:
                w.configure(highlightthickness=0,
                            highlightbackground=border, highlightcolor=border)

    def _clear_drop_indicator(self):
        self._highlight_focused_chip()

    def _reorder_drop(self, src, target, drop_after):
        if src == target or src not in self._viewer_order or target not in self._viewer_order:
            return
        self._viewer_order.remove(src)
        tgt_idx = self._viewer_order.index(target)
        insert_idx = tgt_idx + 1 if drop_after else tgt_idx
        self._viewer_order.insert(insert_idx, src)
        self._save_viewer_state()
        self._render_viewer_versions()
        self._load_chapter()

    def _save_viewer_state(self):
        self.settings['viewer_version_order'] = list(self._viewer_order)
        self.settings['viewer_versions'] = [n for n in self._viewer_order if n in self._viewer_checked]
        self._save_settings()

    def _checked_in_order(self):
        return [n for n in self._viewer_order if n in self._viewer_checked]

    def _get_primary_version(self):
        """First checked version, used to populate book/chapter dropdowns."""
        for name in self._viewer_order:
            if name in self._viewer_checked:
                return name
        return None

    def _populate_books(self):
        primary = self._get_primary_version()
        if not primary or primary not in self.bible_dbs:
            self.book_combo['values'] = []
            self._book_number_map = {}
            return
        db = self.bible_dbs[primary]
        book_names = [f"{long_} ({short})" for bn, short, long_ in db.book_list]
        self._book_number_map = {f"{long_} ({short})": bn for bn, short, long_ in db.book_list}
        self.book_combo['values'] = book_names
        current = self.book_var.get()
        if current in book_names:
            return
        if book_names:
            self.book_var.set(book_names[0])

    def _restore_last_position(self):
        """Restore the last viewed book/chapter, else default to first book."""
        self._populate_books()
        bn = self.settings.get('last_book_num')
        chap = self.settings.get('last_chapter')
        primary = self._get_primary_version()
        if bn and primary and primary in self.bible_dbs:
            db = self.bible_dbs[primary]
            if bn in db.books:
                short, long_ = db.books[bn]
                target = f"{long_} ({short})"
                if target in (self.book_combo['values'] or []):
                    self.book_var.set(target)
                    chapters = db.get_chapters(bn)
                    self.chapter_combo['values'] = [str(c) for c in chapters]
                    if chap and str(chap) in self.chapter_combo['values']:
                        self.chapter_var.set(str(chap))
                    elif chapters:
                        self.chapter_var.set(str(chapters[0]))
                    self._load_chapter()
                    return
        self._on_book_changed(None)

    # ---- Panel split (sash) persistence ----

    def _restore_sash_positions(self):
        try:
            self.root.update_idletasks()
            hsash = self.settings.get('viewer_hsash') or []
            for i, x in enumerate(hsash):
                try:
                    self.viewer_hpane.sash_place(i, int(x), 1)
                except Exception:
                    pass
            vsash = self.settings.get('viewer_vsash')
            if vsash is not None:
                try:
                    self.viewer_pane.sash_place(0, 1, int(vsash))
                except Exception:
                    pass
        except Exception:
            pass

    def _capture_sash_positions(self):
        try:
            hsash = []
            # 3 panels -> 2 sashes
            for i in range(2):
                try:
                    hsash.append(self.viewer_hpane.sash_coord(i)[0])
                except Exception:
                    break
            if hsash:
                self.settings['viewer_hsash'] = hsash
            try:
                self.settings['viewer_vsash'] = self.viewer_pane.sash_coord(0)[1]
            except Exception:
                pass
        except Exception:
            pass

    def _on_book_changed(self, event):
        primary = self._get_primary_version()
        book_name = self.book_var.get()
        if not primary or not book_name or primary not in self.bible_dbs:
            self.viewer_text.configure(state=tk.NORMAL)
            self.viewer_text.delete('1.0', tk.END)
            self.viewer_text.configure(state=tk.DISABLED)
            return
        bn = self._book_number_map.get(book_name)
        if bn is None:
            return
        db = self.bible_dbs[primary]
        chapters = db.get_chapters(bn)
        self.chapter_combo['values'] = [str(c) for c in chapters]
        current_chap = self.chapter_var.get()
        if current_chap and current_chap in self.chapter_combo['values']:
            self._load_chapter()
        elif chapters:
            self.chapter_var.set(str(chapters[0]))
            self._load_chapter()

    def _on_chapter_changed(self, event):
        self._load_chapter()

    def _load_chapter(self, highlight_verses=None):
        primary = self._get_primary_version()
        book_name = self.book_var.get()
        self.viewer_text.configure(state=tk.NORMAL)
        self.viewer_text.delete('1.0', tk.END)
        self._current_verse_nums = []

        if not primary or not book_name or primary not in self.bible_dbs:
            self.viewer_text.configure(state=tk.DISABLED)
            return
        bn = self._book_number_map.get(book_name)
        chapter_str = self.chapter_var.get()
        if bn is None or not chapter_str:
            self.viewer_text.configure(state=tk.DISABLED)
            return

        chapter = int(chapter_str)
        checked = self._checked_in_order()

        # Remember position (persisted on close) + current context for lexicon.
        self._lex_current_book = bn
        self._lex_current_chapter = chapter
        self.settings['last_book_num'] = bn
        self.settings['last_chapter'] = chapter

        # Gather per-version verse maps; union all verse numbers across versions.
        version_verses = {}
        all_verse_nums = set()
        for name in checked:
            db = self.bible_dbs[name]
            if bn not in db.books:
                continue
            vd = dict(db.get_verses(bn, chapter))
            version_verses[name] = vd
            all_verse_nums.update(vd.keys())

        first_hl = None
        sorted_verses = sorted(all_verse_nums)
        self._current_verse_nums = sorted_verses
        for idx, verse_num in enumerate(sorted_verses):
            is_hl = highlight_verses and verse_num in highlight_verses
            mark = f'verse_{verse_num}'
            self.viewer_text.mark_set(mark, tk.INSERT)
            self.viewer_text.mark_gravity(mark, tk.LEFT)
            block_tag = f'vb_{verse_num}'

            for name in checked:
                vd = version_verses.get(name)
                if not vd or verse_num not in vd:
                    continue
                text = vd[verse_num]
                if is_hl:
                    self.viewer_text.insert(tk.END, f" [{name}] {verse_num} ",
                                            ('highlight_num', 'highlight', block_tag))
                    self.viewer_text.insert(tk.END, f"{text}\n",
                                            ('highlight', block_tag))
                    if first_hl is None:
                        first_hl = mark
                else:
                    self.viewer_text.insert(tk.END, f" [{name}] {verse_num} ",
                                            ('verse_num', block_tag))
                    self.viewer_text.insert(tk.END, f"{text}\n", (block_tag,))

            if idx < len(sorted_verses) - 1:
                self.viewer_text.insert(tk.END, "\n")

        self.viewer_text.configure(state=tk.DISABLED)

        # Render the original-language middle panel BEFORE scrolling so the sync
        # finds vb_* tags on the new chapter, not the previous one.
        if hasattr(self, 'lex_mid_text') and self._bethlehem_ready():
            self._render_lex_middle(bn, chapter)

        # Position the requested (or first) verse at the top of both panels.
        if highlight_verses:
            target_v = min(highlight_verses)
        elif sorted_verses:
            target_v = sorted_verses[0]
        else:
            target_v = None
        if target_v is not None:
            self.root.after(50, lambda v=target_v: self._scroll_both_to_verse(v))

    def _on_verse_jump(self, event):
        v = self.verse_jump_var.get().strip()
        if v.isdigit():
            try:
                self._scroll_both_to_verse(int(v))
            except Exception:
                pass

    # ---- Scroll sync (viewer → middle, one-way) ----

    def _scroll_text_to_verse(self, widget, verse_num):
        """Place vb_<verse_num>'s first line precisely at the top of the viewport.

        Uses display-line counts (wrap-aware) so the fraction passed to
        yview_moveto matches Tk's internal display-line interpretation. This
        avoids the top-edge clipping that happens when fractions are computed
        from logical line numbers while the widget wraps.
        """
        try:
            ranges = widget.tag_ranges(f'vb_{verse_num}')
        except Exception:
            return
        if not ranges:
            return
        idx = widget.index(ranges[0])
        try:
            widget.update_idletasks()
            above = widget.count('1.0', idx, 'displaylines')
            total = widget.count('1.0', 'end', 'displaylines')
        except Exception:
            return
        if isinstance(above, (list, tuple)):
            above = above[0] if above else 0
        if isinstance(total, (list, tuple)):
            total = total[0] if total else 0
        above = above or 0
        total = total or 0
        if total <= 0:
            return
        fraction = max(0.0, min(1.0, above / total))
        try:
            widget.yview_moveto(fraction)
        except Exception:
            pass

    def _topmost_verse_in_viewer(self):
        """First fully visible verse in viewer_text (Option B definition).

        A line is 'fully visible at top' when dlineinfo.y >= 0 (its top edge is
        at or below the viewport's top edge). Skip lines without a vb_* tag.
        """
        text = self.viewer_text
        try:
            text.update_idletasks()
            end_line = int(str(text.index('end-1c')).split('.')[0])
        except Exception:
            return None
        for ln in range(1, end_line + 1):
            info = text.dlineinfo(f'{ln}.0')
            if info is None:
                continue  # not in viewport
            y = info[1]
            if y < 0:
                continue  # top of this line is clipped — Option B skips it
            for tag in text.tag_names(f'{ln}.0'):
                if tag.startswith('vb_'):
                    try:
                        return int(tag[3:])
                    except ValueError:
                        pass
            # blank line (no vb_*) — walk forward
        return None

    def _on_viewer_yscroll(self, *args):
        """yscrollcommand wrapper: drive scrollbar + queue middle-panel sync."""
        try:
            self.viewer_scroll.set(*args)
        except Exception:
            pass
        if getattr(self, '_sync_lock', False):
            return
        if getattr(self, '_sync_pending', False):
            return
        self._sync_pending = True
        self.root.after(40, self._do_sync_middle_to_viewer)

    def _do_sync_middle_to_viewer(self):
        self._sync_pending = False
        if self._sync_lock or not hasattr(self, 'lex_mid_text'):
            return
        v = self._topmost_verse_in_viewer()
        if v is None:
            return
        self._sync_lock = True
        try:
            self._scroll_text_to_verse(self.lex_mid_text, v)
        finally:
            self._sync_lock = False

    def _scroll_both_to_verse(self, verse_num):
        """Programmatic scroll: place verse_num at the top of both panels."""
        self._sync_lock = True
        try:
            self._scroll_text_to_verse(self.viewer_text, verse_num)
            if hasattr(self, 'lex_mid_text'):
                self._scroll_text_to_verse(self.lex_mid_text, verse_num)
        finally:
            self._sync_lock = False

    # ---- Font size ----

    def _apply_viewer_font(self):
        size = int(self.settings.get('viewer_font_size', 11))
        num_size = max(8, size - 2)
        # Scripture body in serif; verse-number labels stay sans for clarity.
        self.viewer_text.configure(font=(SERIF_FONT, size + 1))
        self.viewer_text.tag_configure('verse_num', font=(UI_FONT, num_size, 'bold'))
        self.viewer_text.tag_configure('highlight', font=(SERIF_FONT, size + 1, 'bold'))
        self.viewer_text.tag_configure('highlight_num', font=(UI_FONT, num_size, 'bold'))
        # Apply the same size to the original-language and dictionary panels.
        if hasattr(self, 'lex_mid_text'):
            self.lex_mid_text.configure(font=(BODY_FONT, size))
            self.lex_mid_text.tag_configure('lex_vnum', font=(BODY_FONT, num_size, 'bold'))
        if hasattr(self, 'lex_right_text'):
            self.lex_right_text.configure(font=(BODY_FONT, size))

    def _change_font_size(self, delta):
        cur = int(self.settings.get('viewer_font_size', 11))
        new_size = max(8, min(30, cur + delta))
        if new_size == cur:
            return
        self.settings['viewer_font_size'] = new_size
        self._apply_viewer_font()
        self._save_settings()

    def _on_ctrl_wheel(self, event):
        self._change_font_size(1 if event.delta > 0 else -1)
        return 'break'

    # ---- Verse click/drag → copy formatted ----

    def _on_viewer_text_release(self, event):
        # Determine target verses: drag selection or single click.
        try:
            sel_start = self.viewer_text.index('sel.first')
            sel_end = self.viewer_text.index('sel.last')
            verses = self._verses_in_range(sel_start, sel_end)
        except tk.TclError:
            idx = self.viewer_text.index(f"@{event.x},{event.y}")
            v = self._verse_at_index(idx)
            verses = [v] if v is not None else []
        if verses:
            self._copy_verses_formatted(verses)

    def _verse_at_index(self, idx):
        for t in self.viewer_text.tag_names(idx):
            if t.startswith('vb_'):
                try:
                    return int(t[3:])
                except ValueError:
                    pass
        return None

    def _verses_in_range(self, start, end):
        verses = []
        text = self.viewer_text
        for v in getattr(self, '_current_verse_nums', []):
            ranges = text.tag_ranges(f'vb_{v}')
            for i in range(0, len(ranges), 2):
                r_start, r_end = ranges[i], ranges[i + 1]
                if text.compare(r_start, '<', end) and text.compare(r_end, '>', start):
                    verses.append(v)
                    break
        return verses

    def _copy_verses_formatted(self, verse_nums):
        if not verse_nums:
            return
        book_name = self.book_var.get()
        bn = self._book_number_map.get(book_name) if book_name else None
        chapter_str = self.chapter_var.get()
        if bn is None or not chapter_str:
            return
        chapter = int(chapter_str)

        # Use viewer's checked versions in viewer order; fall back to output_order.
        order = self._checked_in_order() or list(self.settings.get('output_order', []))
        if not order:
            return

        fmt = Formatter(self.settings, self.bible_dbs)
        parts = []
        for ver in order:
            if ver not in self.bible_dbs:
                continue
            db = self.bible_dbs[ver]
            if bn not in db.books:
                continue
            verse_data = [(v, db.get_verse_text(bn, chapter, v)) for v in verse_nums]
            verse_data = [(v, t) for v, t in verse_data if t]
            if not verse_data:
                continue
            actual = [v for v, _ in verse_data]
            text = fmt.format_version_output(db, bn, chapter, actual, verse_data)
            if text:
                parts.append(text)
        if not parts:
            return
        result = '\n\n'.join(parts)
        self._clipboard_write(result)
        self.last_clipboard = result
        verse_str = Formatter._format_verse_list(verse_nums, self.settings.get('range_symbol', '-'))
        self._append_log(f"[복사] {chapter}:{verse_str} → {len(parts)}개 버전\n")

    # ---- Keyword search ----

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
        self.notebook.select(self.tab_viewer)
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
        self.last_clipboard = result
        short = '?'
        for db in self.bible_dbs.values():
            if book_num in db.books:
                short = db.books[book_num][0]
                break
        self._append_log(f'[복사] {short} {chapter}:{verse}\n')

    def _nav_keys_allowed(self):
        """Arrow-key chapter nav only on the viewer tab and not while a field
        (entry / combobox / listbox) has focus."""
        try:
            if self.notebook.select() != str(self.tab_viewer):
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
        chapters = list(self.chapter_combo['values'])
        if not chapters:
            return
        cur = self.chapter_var.get()
        idx = chapters.index(cur) if cur in chapters else 0
        if idx > 0:
            self.chapter_var.set(chapters[idx - 1])
            self._load_chapter()

    def _next_chapter(self):
        chapters = list(self.chapter_combo['values'])
        if not chapters:
            return
        cur = self.chapter_var.get()
        idx = chapters.index(cur) if cur in chapters else 0
        if idx < len(chapters) - 1:
            self.chapter_var.set(chapters[idx + 1])
            self._load_chapter()

    # ---- Monitoring ----

    def _toggle_monitoring(self):
        if self.monitoring:
            self.monitoring = False
            self.monitor_btn.configure(text="  모니터링 시작  ")
            self._update_status("대기 중", False)
        else:
            self.monitoring = True
            self.monitor_btn.configure(text="  모니터링 중지  ")
            self._update_status("모니터링 중", True)
            self.last_clipboard = self._clipboard_read()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

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

    def _monitor_loop(self):
        while self.monitoring:
            try:
                current = self._clipboard_read()
                if current != self.last_clipboard and current.strip():
                    self.last_clipboard = current
                    self._process_clipboard(current.strip())
            except Exception:
                pass
            time.sleep(0.5)

    def _process_clipboard(self, text):
        # "#키워드" → keyword search (show results, copy the first verse)
        if text.startswith('#'):
            keyword = text[1:].strip()
            if keyword:
                self.last_clipboard = text
                self.root.after(0, lambda kw=keyword: self._run_search(kw, copy_first=True))
            return
        refs = Engine.parse_reference(text)
        if not refs:
            return
        book_num, short_name, long_name, chapter, verses = refs[0]
        order = self.settings['output_order']
        if not order:
            return

        fmt = Formatter(self.settings, self.bible_dbs)
        parts = []
        for ver_name in order:
            if ver_name not in self.bible_dbs:
                continue
            db = self.bible_dbs[ver_name]
            if book_num not in db.books:
                continue
            if verses:
                verse_data = [(v, db.get_verse_text(book_num, chapter, v)) for v in verses]
            else:
                verse_data = db.get_verses(book_num, chapter)
            verse_data = [(v, t) for v, t in verse_data if t]
            if not verse_data:
                continue
            actual_verses = [v for v, _ in verse_data]
            result = fmt.format_version_output(db, book_num, chapter, actual_verses, verse_data)
            if result:
                parts.append(result)

        if parts:
            result = '\n\n'.join(parts)
            self._clipboard_write(result)
            self.last_clipboard = result

            self.root.after(0, lambda: self._update_viewer_from_ref(book_num, chapter, verses))

            self.root.after(0, lambda: self._append_log_ref(
                book_num, chapter, verses, short_name, len(parts)))

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
        if target in (self.book_combo['values'] or []):
            self.book_var.set(target)
            chapters = db.get_chapters(book_num)
            self.chapter_combo['values'] = [str(c) for c in chapters]
            self.chapter_var.set(str(chapter))
            self._load_chapter(highlight_verses=verses if verses else None)
            self.notebook.select(self.tab_viewer)

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
        t = self.theme
        self.status_label.configure(text=f" {text} ")
        if active:
            self.status_label.configure(bg=t['status_bg'], fg=t['status_fg'])
        else:
            self.status_label.configure(bg=t['status_off_bg'], fg=t['status_off_fg'])

    # ---- Theme ----

    def _toggle_dark_mode(self):
        self.settings['dark_mode'] = not self.settings['dark_mode']
        self.theme = DARK_THEME if self.settings['dark_mode'] else LIGHT_THEME
        self.dark_btn.configure(
            text="  라이트 모드  " if self.settings['dark_mode'] else "  다크 모드  ")
        self._apply_theme()
        self._save_settings()

    def _apply_theme(self):
        t = self.theme
        dark = self.settings['dark_mode']

        # ttk Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background=t['bg'], borderwidth=0)
        style.configure('TNotebook.Tab', background=t['button_bg'], foreground=t['fg'],
                        padding=[12, 4], font=(UI_FONT, 9))
        style.map('TNotebook.Tab',
                  background=[('selected', t['accent']), ('!selected', t['button_bg'])],
                  foreground=[('selected', '#FFFFFF'), ('!selected', t['fg'])])
        style.configure('TCombobox', fieldbackground=t['entry_bg'],
                        background=t['button_bg'], foreground=t['entry_fg'],
                        selectbackground=t['accent'], selectforeground='#FFFFFF',
                        arrowcolor=t['fg'])
        style.map('TCombobox',
                  fieldbackground=[('readonly', t['entry_bg'])],
                  foreground=[('readonly', t['entry_fg'])])

        # Root
        self.root.configure(bg=t['bg'])
        self.main_frame.configure(bg=t['bg'])

        # Top bar
        self.top_bar.configure(bg=t['bg'])
        self.title_label.configure(bg=t['bg'], fg=t['accent'])
        self._style_button(self.monitor_btn)
        self._style_button(self.dark_btn)
        self._style_button(self.update_check_btn)
        self._update_status("모니터링 중" if self.monitoring else "대기 중", self.monitoring)

        # Tabs
        self.tab_viewer.configure(bg=t['bg'])
        self.tab_settings.configure(bg=t['bg'])

        # --- Viewer tab ---
        self.viewer_pane.configure(bg=t['bg'], sashrelief=tk.FLAT)
        self.log_frame.configure(bg=t['frame_bg'])
        self._log_label.configure(bg=t['frame_bg'], fg=t['fg'])
        if hasattr(self, 'log_header'):
            self.log_header.configure(bg=t['frame_bg'])
        # Log inner frame
        for w in self.log_frame.winfo_children():
            if isinstance(w, tk.Frame):
                w.configure(bg=t['frame_bg'])
                for c in w.winfo_children():
                    if isinstance(c, tk.Label):
                        c.configure(bg=t['frame_bg'], fg=t['fg'])
        self.log_text.configure(bg=t['entry_bg'], fg=t['entry_fg'],
                                insertbackground=t['fg'])
        self.log_text.tag_configure('logref', foreground=t['accent'])
        self._style_scrollbar(self.log_scroll)

        self.viewer_outer.configure(bg=t['bg'])
        self.version_bar.configure(bg=t['bg'])
        self.chip_frame.configure(bg=t['bg'])
        for w in self.version_bar.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(bg=t['bg'], fg=t['fg'])
            elif isinstance(w, tk.Frame):
                w.configure(bg=t['bg'])
        self._apply_viewer_chip_theme()
        self.nav_frame.configure(bg=t['bg'])
        for w in self.nav_frame.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(bg=t['bg'], fg=t['fg'])
        self._style_button(self.prev_btn)
        self._style_button(self.next_btn)
        self._style_button(self.jump_btn)
        self._style_button(self.search_btn)
        self._style_button(self.font_plus_btn)
        self._style_button(self.font_minus_btn)
        self.search_label.configure(bg=t['bg'], fg=t['fg'])
        for ent in (self.verse_jump_entry, self.search_entry):
            ent.configure(bg=t['entry_bg'], fg=t['entry_fg'],
                          insertbackground=t['fg'],
                          highlightthickness=1, highlightcolor=t['accent'],
                          highlightbackground=t['border'])
        self.viewer_text_frame.configure(bg=t['bg'])
        sel_bg, sel_fg = t['select_bg'], t['select_fg']
        self.viewer_text.configure(bg=t['viewer_bg'], fg=t['viewer_fg'],
                                     insertbackground=t['fg'],
                                     selectbackground=sel_bg, selectforeground=sel_fg)
        self.viewer_text.tag_configure('verse_num', foreground=t['verse_num'],
                                         selectbackground=sel_bg, selectforeground=sel_fg)
        self.viewer_text.tag_configure('highlight', background=t['highlight_bg'],
                                         foreground=t['highlight_fg'],
                                         selectbackground=sel_bg, selectforeground=sel_fg)
        self.viewer_text.tag_configure('highlight_num', foreground=t['highlight_fg'],
                                         background=t['highlight_bg'],
                                         selectbackground=sel_bg, selectforeground=sel_fg)
        self.viewer_text.tag_configure('search_head', foreground=t['fg'])
        self.viewer_text.tag_configure('search_ref', foreground=t['accent'])
        self._style_scrollbar(self.viewer_scroll)

        # --- Settings tab ---
        self.settings_pane.configure(bg=t['bg'], sashrelief=tk.FLAT)
        self.settings_left.configure(bg=t['frame_bg'])
        self.settings_right.configure(bg=t['bg'])
        self.settings_canvas.configure(bg=t['bg'])
        self._style_scrollbar(self.settings_scrollbar)
        self.settings_scroll_frame.configure(bg=t['bg'])

        # Left panel labels
        for w in self.settings_left.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(bg=t['frame_bg'], fg=t['fg'])
            elif isinstance(w, tk.Frame):
                w.configure(bg=t['frame_bg'])
                for c in w.winfo_children():
                    if isinstance(c, tk.Label):
                        c.configure(bg=t['frame_bg'], fg=t['fg'])

        # Dual listbox area
        for w in self.settings_left.winfo_children():
            if isinstance(w, tk.Frame):
                w.configure(bg=t['frame_bg'])
                for c in w.winfo_children():
                    if isinstance(c, tk.Frame):
                        c.configure(bg=t['frame_bg'])
                        for gc in c.winfo_children():
                            if isinstance(gc, tk.Label):
                                gc.configure(bg=t['frame_bg'], fg=t['fg'])

        self._apply_listbox_theme()

        # Buttons in settings
        for btn in [self.add_btn, self.remove_btn, self.refresh_btn,
                    self.up_btn, self.down_btn, self.clear_btn, self.preview_refresh_btn]:
            self._style_button(btn)

        # LabelFrames and their radio/check buttons
        for lf in self._settings_labelframes:
            lf.configure(bg=t['bg'], fg=t['fg'])
            for child in lf.winfo_children():
                if isinstance(child, (tk.Radiobutton, tk.Checkbutton)):
                    child.configure(bg=t['bg'], fg=t['fg'],
                                    selectcolor=t['radio_sel'],
                                    activebackground=t['bg'],
                                    activeforeground=t['fg'],
                                    highlightthickness=0)

        # Header labels in scroll frame
        for lbl in self._settings_header_labels:
            lbl.configure(bg=t['bg'], fg=t['fg'])

        # Separator in scroll frame
        for w in self.settings_scroll_frame.winfo_children():
            if isinstance(w, tk.Frame) and w not in self._settings_labelframes:
                # Could be separator or preview header
                w.configure(bg=t['bg'])
                for c in w.winfo_children():
                    if isinstance(c, tk.Label):
                        c.configure(bg=t['bg'], fg=t['fg'])

        # Preview
        self.preview_text.configure(bg=t['preview_bg'], fg=t['preview_fg'],
                                      insertbackground=t['fg'])

        # --- Lexicon panels inside viewer tab + dict language toggle ---
        if hasattr(self, 'lex_lang_label'):
            self.lex_lang_label.configure(bg=t['bg'], fg=t['fg'])
            for rb in (self.lex_lang_ko_rb, self.lex_lang_en_rb):
                rb.configure(bg=t['bg'], fg=t['fg'],
                             selectcolor=t['radio_sel'],
                             activebackground=t['bg'], activeforeground=t['fg'],
                             highlightthickness=0)
        if hasattr(self, 'viewer_hpane'):
            self.viewer_hpane.configure(bg=t['bg'], sashrelief=tk.FLAT)
        if hasattr(self, 'lex_mid_text'):
            sel_bg, sel_fg = t['select_bg'], t['select_fg']
            for frm, lbl, txt, scr in (
                (self.lex_mid_frame, self.lex_mid_label, self.lex_mid_text, self.lex_mid_scroll),
                (self.lex_right_frame, self.lex_right_label, self.lex_right_text, self.lex_right_scroll),
            ):
                frm.configure(bg=t['bg'])
                for c in frm.winfo_children():
                    if isinstance(c, tk.Frame):
                        c.configure(bg=t['bg'])
                lbl.configure(bg=t['bg'], fg=t['fg'])
                txt.configure(bg=t['viewer_bg'], fg=t['viewer_fg'],
                              insertbackground=t['fg'],
                              selectbackground=sel_bg, selectforeground=sel_fg)
                self._style_scrollbar(scr)
            self.lex_mid_text.tag_configure('lex_vnum', foreground=t['verse_num'])
            self.lex_mid_text.tag_configure('lex_word', foreground=t['accent'])
            hl = getattr(self, '_lex_hl_code', None)
            if hl:
                self.lex_mid_text.tag_configure(f'sw_{hl}', background=t['lex_hl_bg'])

    def _apply_viewer_chip_theme(self):
        t = getattr(self, 'theme', None)
        if not t:
            return
        for n, frame in self.viewer_chip_widgets.items():
            frame.configure(bg=t['button_bg'], highlightbackground=t['border'])
        for n, lbl in self.viewer_chip_labels.items():
            lbl.configure(bg=t['button_bg'], fg=t['button_fg'])
        self._highlight_focused_chip()

    def _apply_listbox_theme(self):
        t = self.theme
        for lb in [self.avail_listbox, self.order_listbox]:
            lb.configure(bg=t['listbox_bg'], fg=t['listbox_fg'],
                        selectbackground=t['listbox_sel_bg'],
                        selectforeground=t['listbox_sel_fg'],
                        highlightthickness=1, highlightcolor=t['accent'],
                        highlightbackground=t['border'])

    def _style_button(self, btn):
        t = self.theme
        btn.configure(bg=t['button_bg'], fg=t['button_fg'],
                     activebackground=t['button_active'], activeforeground=t['button_fg'],
                     highlightthickness=0, bd=0)

    def _style_scrollbar(self, sb):
        """Visible scrollbar: a contrasting thumb so position is obvious."""
        t = self.theme
        sb.configure(bg=t['scroll_thumb'], troughcolor=t['scroll_trough'],
                     activebackground=t['scroll_active'], width=14,
                     bd=0, relief=tk.FLAT, highlightthickness=0, elementborderwidth=0)

    # ---- Auto-update ----

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
            tmpdir = tempfile.mkdtemp(prefix='autobible_update_')
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
        self._capture_sash_positions()
        self._save_settings()
        for db in self.bible_dbs.values():
            try:
                db.close()
            except Exception:
                pass
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    BibleClipApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
