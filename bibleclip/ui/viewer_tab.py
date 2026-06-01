"""Builds the scripture viewer tab (3-panel + log)."""
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


class ViewerTabMixin:
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
        vpw = tk.PanedWindow(self.tab_viewer, orient=tk.VERTICAL, sashwidth=8,
                             bd=0, relief=tk.FLAT)
        vpw.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))
        self.viewer_pane = vpw

        # Top: horizontal PanedWindow with 3 card panels
        main_top = tk.Frame(vpw, bd=0, highlightthickness=0)
        vpw.add(main_top, minsize=240, stretch="always")
        hpw = tk.PanedWindow(main_top, orient=tk.HORIZONTAL, sashwidth=10,
                             bd=0, relief=tk.FLAT)
        hpw.pack(fill=tk.BOTH, expand=True)
        self.viewer_hpane = hpw

        def _card(parent, title, minsize):
            # bg_color = app bg so the rounded-corner notches blend with the
            # PanedWindow background (otherwise CTk fills them with a mismatched
            # color since the tk.PanedWindow parent isn't a CTk widget).
            card = ctk.CTkFrame(parent, fg_color=CTK['card'], corner_radius=14,
                                bg_color=CTK['app_bg'],
                                border_width=1, border_color=CTK['card_border'])
            parent.add(card, minsize=minsize, stretch="always")
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(1, weight=1)
            head = ctk.CTkLabel(card, text=title, font=(UI_FONT, 11, 'bold'),
                                text_color=CTK['muted'], anchor='w')
            head.grid(row=0, column=0, columnspan=2, sticky='ew', padx=16, pady=(11, 3))
            return card, head

        def _panel_text(card, **kw):
            txt = tk.Text(card, wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT,
                          borderwidth=0, highlightthickness=0, **kw)
            scr = ctk.CTkScrollbar(card, command=txt.yview)
            txt.grid(row=1, column=0, sticky='nsew', padx=(12, 0), pady=(0, 12))
            scr.grid(row=1, column=1, sticky='ns', padx=(2, 10), pady=(0, 12))
            return txt, scr

        # Panel 1: regular Bible viewer (card)
        card1, self.viewer_panel_header = _card(hpw, "성경 본문", 300)
        self.viewer_text_frame = card1
        self.viewer_text, self.viewer_scroll = _panel_text(
            card1, font=(BODY_FONT, 11), spacing1=3, spacing3=4, padx=16, pady=10)
        self.viewer_text.configure(yscrollcommand=self._on_viewer_yscroll)

        # Panel 2: original-language Korean + Strong's code (clickable)
        card2, self.lex_mid_label = _card(hpw, "원어 (단어 클릭)", 150)
        self.lex_mid_frame = card2
        self.lex_mid_text, self.lex_mid_scroll = _panel_text(
            card2, font=(BODY_FONT, 10), spacing1=3, spacing3=3, padx=12, pady=8)
        self.lex_mid_text.configure(yscrollcommand=self.lex_mid_scroll.set)
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

        # Panel 3: dictionary entry (card)
        card3, self.lex_right_label = _card(hpw, "사전", 150)
        self.lex_right_frame = card3
        self.lex_right_text, self.lex_right_scroll = _panel_text(
            card3, font=(BODY_FONT, 10), spacing1=3, spacing3=3, padx=12, pady=8)
        self.lex_right_text.configure(yscrollcommand=self.lex_right_scroll.set)

        self._current_lex_code = None

        # Bottom: activity log card spanning the full width
        logcard = ctk.CTkFrame(vpw, fg_color=CTK['card'], corner_radius=14,
                               bg_color=CTK['app_bg'],
                               border_width=1, border_color=CTK['card_border'])
        vpw.add(logcard, minsize=92, stretch="never")
        self.log_frame = logcard
        logcard.grid_columnconfigure(0, weight=1)
        logcard.grid_rowconfigure(1, weight=1)
        self._log_label = ctk.CTkLabel(logcard, text="활동 로그  (구절 클릭 → 이동)",
                                       font=(UI_FONT, 11, 'bold'),
                                       text_color=CTK['muted'], anchor='w')
        self._log_label.grid(row=0, column=0, columnspan=2, sticky='ew',
                             padx=16, pady=(10, 3))
        self.log_header = self._log_label
        self.log_text = tk.Text(logcard, font=(MONO_FONT, 9), wrap=tk.WORD,
                                state=tk.DISABLED, height=4, relief=tk.FLAT,
                                borderwidth=0, highlightthickness=0)
        self.log_scroll = ctk.CTkScrollbar(logcard, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_text.grid(row=1, column=0, sticky='nsew', padx=(12, 0), pady=(0, 12))
        self.log_scroll.grid(row=1, column=1, sticky='ns', padx=(2, 10), pady=(0, 12))
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

