"""Builds the scripture viewer tab (3-panel + log)."""
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

from bibleclip.ui.widgets import ScrollDropdown
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

        # Version chip bar card (multi-version parallel view + reorder)
        version_bar = ctk.CTkFrame(self.tab_viewer, fg_color=CTK['card'],
                                   corner_radius=12, bg_color=CTK['app_bg'])
        version_bar.pack(fill=tk.X, padx=14, pady=(2, 4))
        self.version_bar = version_bar

        ctk.CTkLabel(version_bar, text="버전", font=(UI_FONT, 11),
                     text_color=CTK['muted']).pack(side=tk.LEFT, padx=(14, 8), pady=6)

        # tk.Frame so the chips can be placed by absolute x (drag-reorder).
        self.chip_frame = tk.Frame(version_bar, bd=0, highlightthickness=0)
        self.chip_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=6)

        ctk.CTkLabel(version_bar, text="(클릭: 토글 · 드래그: 순서 변경)",
                     font=(UI_FONT, 10), text_color=CTK['muted']).pack(side=tk.LEFT, padx=(8, 14))

        # Initialize ordered viewer state from settings
        self._viewer_order = list(self.settings['viewer_version_order'])
        self._viewer_checked = set(self.settings['viewer_versions'])
        self._viewer_focused = self._viewer_order[0] if self._viewer_order else None
        self.viewer_chip_widgets = {}  # name -> outer Frame
        self.viewer_chip_labels = {}   # name -> inner Label
        self._render_viewer_versions()

        # Navigation card
        nav = ctk.CTkFrame(self.tab_viewer, fg_color=CTK['card'], corner_radius=12,
                           bg_color=CTK['app_bg'])
        nav.pack(fill=tk.X, padx=14, pady=(2, 6))
        self.nav_frame = nav

        BTN = dict(corner_radius=8, height=30, fg_color=CTK['btn'],
                   hover_color=CTK['btn_hover'], text_color=CTK['btn_text'],
                   font=(UI_FONT, 11))
        LBL = dict(font=(UI_FONT, 11), text_color=CTK['muted'])
        ENT = dict(height=30, corner_radius=8, fg_color=CTK['app_bg'],
                   border_color=CTK['card_border'], text_color=CTK['text'],
                   font=(UI_FONT, 11))
        OPT = dict(height=30, corner_radius=8, fg_color=CTK['btn'],
                   hover_color=CTK['btn_hover'], text_color=CTK['btn_text'],
                   font=(UI_FONT, 11))

        ctk.CTkLabel(nav, text="책", **LBL).pack(side=tk.LEFT, padx=(14, 4), pady=8)
        self.book_var = tk.StringVar()
        self.book_combo = ScrollDropdown(nav, variable=self.book_var, width=160,
                                         command=self._on_book_picked, **OPT)
        self.book_combo.pack(side=tk.LEFT, padx=(0, 10), pady=8)

        ctk.CTkLabel(nav, text="장", **LBL).pack(side=tk.LEFT, padx=(0, 4))
        self.chapter_var = tk.StringVar()
        self.chapter_combo = ScrollDropdown(nav, variable=self.chapter_var, width=80,
                                            command=self._on_chapter_changed,
                                            max_visible=16, **OPT)
        self.chapter_combo.pack(side=tk.LEFT, padx=(0, 6))

        self.prev_btn = ctk.CTkButton(nav, text="‹", width=32,
                                      command=self._prev_chapter, **BTN)
        self.prev_btn.pack(side=tk.LEFT, padx=2)
        self.next_btn = ctk.CTkButton(nav, text="›", width=32,
                                      command=self._next_chapter, **BTN)
        self.next_btn.pack(side=tk.LEFT, padx=2)

        ctk.CTkLabel(nav, text="절", **LBL).pack(side=tk.LEFT, padx=(12, 4))
        self.verse_jump_var = tk.StringVar()
        self.verse_jump_entry = ctk.CTkEntry(nav, textvariable=self.verse_jump_var,
                                             width=54, **ENT)
        self.verse_jump_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.verse_jump_entry.bind('<Return>', self._on_verse_jump)
        self.jump_btn = ctk.CTkButton(nav, text="이동", width=48,
                                      command=lambda: self._on_verse_jump(None), **BTN)
        self.jump_btn.pack(side=tk.LEFT)

        # Keyword search ( "#태초에" or just "태초에" )
        ctk.CTkLabel(nav, text="검색", **LBL).pack(side=tk.LEFT, padx=(14, 4))
        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(nav, textvariable=self.search_var, width=120,
                                         placeholder_text="#키워드", **ENT)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry.bind('<Return>', self._on_search_box)
        self.search_btn = ctk.CTkButton(nav, text="검색", width=48,
                                        command=lambda: self._on_search_box(None), **BTN)
        self.search_btn.pack(side=tk.LEFT)

        # Font size controls (rightmost)
        self.font_plus_btn = ctk.CTkButton(nav, text="A+", width=40,
                                           command=lambda: self._change_font_size(1), **BTN)
        self.font_plus_btn.pack(side=tk.RIGHT, padx=(2, 14))
        self.font_minus_btn = ctk.CTkButton(nav, text="A−", width=40,
                                            command=lambda: self._change_font_size(-1), **BTN)
        self.font_minus_btn.pack(side=tk.RIGHT, padx=2)

        # Dictionary language toggle (segmented). side=RIGHT stacks RTL, so the
        # "사전" label is packed last to sit to the left of the toggle.
        has_ko = self.lexicon_ko is not None
        has_en = self.lexicon_en is not None
        default_lang = 'ko' if has_ko else 'en'
        self.lex_lang_var = tk.StringVar(value=default_lang)
        self.lex_lang_seg = ctk.CTkSegmentedButton(
            nav, values=["한글", "영어"], command=self._on_lex_lang_seg,
            height=30, corner_radius=8, font=(UI_FONT, 11),
            fg_color=CTK['btn'], selected_color=CTK['accent'],
            selected_hover_color=CTK['accent_hover'], unselected_color=CTK['btn'],
            unselected_hover_color=CTK['btn_hover'], text_color=CTK['btn_text'])
        self.lex_lang_seg.set("한글" if default_lang == 'ko' else "영어")
        self._restyle_segmented(self.lex_lang_seg)
        self.lex_lang_seg.pack(side=tk.RIGHT, padx=(0, 10))
        ctk.CTkLabel(nav, text="사전", **LBL).pack(side=tk.RIGHT, padx=(8, 4))

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

