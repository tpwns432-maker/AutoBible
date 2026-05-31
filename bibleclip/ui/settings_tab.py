"""Builds the output-settings tab."""
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


class SettingsTabMixin:
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

