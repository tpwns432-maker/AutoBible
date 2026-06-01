"""Builds the output-settings tab."""
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


class SettingsTabMixin:
    def _build_settings_tab(self):
        # Two columns: left = version order (card), right = format settings + preview
        # (scrollable). Mirrors the viewer tab's CTk card layout.
        pw = tk.PanedWindow(self.tab_settings, orient=tk.HORIZONTAL, sashwidth=8,
                            bd=0, relief=tk.FLAT)
        pw.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))
        self.settings_pane = pw

        # Shared CTk style dicts
        SBTN = dict(width=88, height=30, corner_radius=8, font=(UI_FONT, 11),
                    fg_color=CTK['btn'], hover_color=CTK['btn_hover'],
                    text_color=CTK['btn_text'])

        # ===== LEFT: Version selection & ordering (card) =====
        left = ctk.CTkFrame(pw, fg_color=CTK['card'], corner_radius=14,
                            bg_color=CTK['app_bg'], border_width=1,
                            border_color=CTK['card_border'])
        pw.add(left, minsize=400, stretch="never")
        self.settings_left = left

        ctk.CTkLabel(left, text="성경 버전 선택 / 출력 순서",
                     font=(UI_FONT, 12, 'bold'), text_color=CTK['text'],
                     anchor='w').pack(anchor=tk.W, padx=16, pady=(12, 6))

        # Dual listbox area (tk.Listbox has no CTk equivalent; keep but flatten)
        dual = tk.Frame(left, bd=0, highlightthickness=0)
        dual.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

        avail_frame = tk.Frame(dual, bd=0, highlightthickness=0)
        avail_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ctk.CTkLabel(avail_frame, text="성경 목록", font=(UI_FONT, 11),
                     text_color=CTK['muted'], anchor='w').pack(anchor=tk.W, pady=(0, 2))
        self.avail_listbox = tk.Listbox(avail_frame, font=(UI_FONT, 10),
                                        selectmode=tk.EXTENDED, height=10,
                                        relief=tk.FLAT, borderwidth=0, highlightthickness=1)
        self.avail_listbox.pack(fill=tk.BOTH, expand=True)

        # Buttons between lists
        btn_col = tk.Frame(dual, bd=0, highlightthickness=0)
        btn_col.pack(side=tk.LEFT, padx=8, pady=20)
        self.add_btn = ctk.CTkButton(btn_col, text="추가 →", command=self._add_to_order, **SBTN)
        self.add_btn.pack(pady=4)
        self.remove_btn = ctk.CTkButton(btn_col, text="← 제거", command=self._remove_from_order, **SBTN)
        self.remove_btn.pack(pady=4)
        self.refresh_btn = ctk.CTkButton(btn_col, text="새로고침", command=self._refresh_databases, **SBTN)
        self.refresh_btn.pack(pady=(12, 4))

        order_frame = tk.Frame(dual, bd=0, highlightthickness=0)
        order_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ctk.CTkLabel(order_frame, text="성경 출력 순서", font=(UI_FONT, 11),
                     text_color=CTK['muted'], anchor='w').pack(anchor=tk.W, pady=(0, 2))
        self.order_listbox = tk.Listbox(order_frame, font=(UI_FONT, 10),
                                        selectmode=tk.SINGLE, height=10,
                                        relief=tk.FLAT, borderwidth=0, highlightthickness=1)
        self.order_listbox.pack(fill=tk.BOTH, expand=True)

        # Order control buttons
        order_btns = tk.Frame(left, bd=0, highlightthickness=0)
        order_btns.pack(fill=tk.X, padx=12, pady=(4, 12))
        self.up_btn = ctk.CTkButton(order_btns, text="▲ 위로", command=self._move_up, **SBTN)
        self.up_btn.pack(side=tk.LEFT, padx=4)
        self.down_btn = ctk.CTkButton(order_btns, text="▼ 아래로", command=self._move_down, **SBTN)
        self.down_btn.pack(side=tk.LEFT, padx=4)
        self.clear_btn = ctk.CTkButton(order_btns, text="모두 제거", command=self._clear_order, **SBTN)
        self.clear_btn.pack(side=tk.RIGHT, padx=4)

        # Populate lists
        self._refresh_available_list()
        for name in self.settings['output_order']:
            if name in self.bible_dbs:
                self.order_listbox.insert(tk.END, self.bible_dbs[name].display_name)

        # ===== RIGHT: Format settings + preview (scrollable) =====
        # CTkScrollableFrame wraps itself in an internal canvas, so it can't be a
        # direct PanedWindow child — host it in a plain tk.Frame holder.
        right_holder = tk.Frame(pw, bd=0, highlightthickness=0)
        pw.add(right_holder, minsize=440, stretch="always")
        self.settings_right_holder = right_holder
        right = ctk.CTkScrollableFrame(
            right_holder, fg_color=CTK['app_bg'], corner_radius=0,
            scrollbar_button_color=CTK['btn'],
            scrollbar_button_hover_color=CTK['btn_hover'])
        right.pack(fill=tk.BOTH, expand=True)
        self.settings_right = right
        sf = right

        self._settings_segs = []  # segmented buttons to re-skin on theme toggle

        SEG = dict(height=30, corner_radius=8, font=(UI_FONT, 11),
                   fg_color=CTK['btn'], selected_color=CTK['accent'],
                   selected_hover_color=CTK['accent_hover'],
                   unselected_color=CTK['btn'], unselected_hover_color=CTK['btn_hover'],
                   text_color=CTK['btn_text'])
        CHK = dict(font=(UI_FONT, 11), text_color=CTK['text'], checkbox_width=20,
                   checkbox_height=20, corner_radius=5, fg_color=CTK['accent'],
                   hover_color=CTK['accent_hover'], checkmark_color=CTK['on_accent'],
                   border_color=CTK['card_border'], border_width=2)

        def _section(title, hint=None):
            card = ctk.CTkFrame(sf, fg_color=CTK['card'], corner_radius=12,
                                border_width=1, border_color=CTK['card_border'])
            card.pack(fill=tk.X, padx=4, pady=6)
            ctk.CTkLabel(card, text=title, font=(UI_FONT, 12, 'bold'),
                         text_color=CTK['text'], anchor='w').pack(
                anchor=tk.W, padx=14, pady=(10, 2))
            if hint:
                ctk.CTkLabel(card, text=hint, font=(UI_FONT, 10), justify=tk.LEFT,
                             text_color=CTK['muted'], anchor='w', wraplength=440).pack(
                    anchor=tk.W, padx=14, pady=(0, 2))
            return card

        def _seg_row(card, label, var, options):
            """A label + CTkSegmentedButton bound to `var`.
            options = [(value, display_label), ...]."""
            row = ctk.CTkFrame(card, fg_color='transparent')
            row.pack(fill=tk.X, padx=14, pady=5)
            ctk.CTkLabel(row, text=label, font=(UI_FONT, 11), text_color=CTK['muted'],
                         width=110, anchor='w').pack(side=tk.LEFT)
            val2lbl = {v: l for v, l in options}
            lbl2val = {l: v for v, l in options}
            seg = ctk.CTkSegmentedButton(row, values=[l for _, l in options], **SEG)
            seg.set(val2lbl.get(var.get(), options[0][1]))

            def _on(chosen, vr=var, m=lbl2val, sg=seg):
                vr.set(m.get(chosen, chosen))
                self._restyle_segmented(sg)
                self._on_setting_changed()
            seg.configure(command=_on)
            self._restyle_segmented(seg)
            seg.pack(side=tk.LEFT)
            self._settings_segs.append(seg)
            return seg

        # --- 표기 설정 (한국어 버전용) ---
        c_fmt = _section("표기 설정 (한국어 버전용)",
                         "※ 영어 성경(ESV/NKJV 등)은 항상 영어식+하이픈으로 출력됩니다.")
        self.book_name_var = tk.StringVar(value=self.settings['book_name'])
        _seg_row(c_fmt, "책 이름", self.book_name_var,
                 [('long_ko', '한글 정식'), ('short_ko', '한글 약칭'),
                  ('long_en', '영문 정식'), ('short_en', '영문 약칭')])
        self.cv_format_var = tk.StringVar(value=self.settings['chapter_verse_format'])
        _seg_row(c_fmt, "장절 표기", self.cv_format_var,
                 [('colon', '1:1'), ('korean', '1장 1절')])
        self.bracket_var = tk.StringVar(value=self.settings['bracket_style'])
        _seg_row(c_fmt, "괄호", self.bracket_var,
                 [('none', '없음'), ('[]', '[ ]'), ('()', '( )')])
        self.position_var = tk.StringVar(value=self.settings['ref_position'])
        _seg_row(c_fmt, "표기 위치", self.position_var,
                 [('before', '본문 앞'), ('after', '본문 뒤')])
        self.range_var = tk.StringVar(value=self.settings['range_symbol'])
        _seg_row(c_fmt, "범위 기호", self.range_var,
                 [('-', '-'), ('~', '~')])
        self.sep_var = tk.StringVar(value=self.settings['ref_body_separator'])
        _seg_row(c_fmt, "구분 기호", self.sep_var,
                 [(' - ', '하이픈 (-)'), (': ', '콜론 (:)'), (' ', '띄어쓰기')])
        ctk.CTkFrame(c_fmt, fg_color='transparent', height=4).pack()  # bottom pad

        # --- 다절 출력 방식 ---
        c_out = _section("다절 출력 방식")
        self.output_mode_var = tk.StringVar(value=self.settings['output_mode'])
        _seg_row(c_out, "출력 방식", self.output_mode_var,
                 [('inline', '여러 절을 한 줄로'), ('newline', '각 절을 줄마다')])
        self.newline_cv_var = tk.BooleanVar(value=self.settings['newline_show_cv'])
        self.newline_cv_check = ctk.CTkCheckBox(
            c_out, text='줄마다 장:절 표시', variable=self.newline_cv_var,
            command=self._on_setting_changed, **CHK)
        self.newline_cv_check.pack(anchor=tk.W, padx=14, pady=(2, 12))

        # --- 기타 ---
        c_misc = _section("기타")
        self.version_header_var = tk.BooleanVar(value=self.settings['show_version_header'])
        ctk.CTkCheckBox(c_misc, text='버전 헤더 출력', variable=self.version_header_var,
                        command=self._on_setting_changed, **CHK).pack(
            anchor=tk.W, padx=14, pady=(2, 6))
        self.hide_ref_var = tk.BooleanVar(value=self.settings['hide_reference'])
        ctk.CTkCheckBox(c_misc, text='장절 표기 숨기기 (본문만)', variable=self.hide_ref_var,
                        command=self._on_setting_changed, **CHK).pack(
            anchor=tk.W, padx=14, pady=(2, 12))

        # --- 미리보기 ---
        pcard = ctk.CTkFrame(sf, fg_color=CTK['card'], corner_radius=12,
                             border_width=1, border_color=CTK['card_border'])
        pcard.pack(fill=tk.BOTH, expand=True, padx=4, pady=6)
        phead = ctk.CTkFrame(pcard, fg_color='transparent')
        phead.pack(fill=tk.X, padx=14, pady=(10, 4))
        ctk.CTkLabel(phead, text="미리보기  (예시: 요 1:1-3)", font=(UI_FONT, 12, 'bold'),
                     text_color=CTK['text']).pack(side=tk.LEFT)
        self.preview_refresh_btn = ctk.CTkButton(
            phead, text="새로고침", width=72, height=26, corner_radius=8,
            font=(UI_FONT, 10), fg_color=CTK['btn'], hover_color=CTK['btn_hover'],
            text_color=CTK['btn_text'], command=self._update_preview)
        self.preview_refresh_btn.pack(side=tk.RIGHT)
        self.preview_text = tk.Text(pcard, font=(BODY_FONT, 11), wrap=tk.WORD,
                                    height=10, state=tk.DISABLED, relief=tk.FLAT,
                                    borderwidth=0, highlightthickness=0, padx=12, pady=10)
        self.preview_text.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 12))

    # ---- Lexicon (원어 사전) helpers — used by viewer tab ----

