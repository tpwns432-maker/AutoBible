"""Dark/light toggle and widget theming."""
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


from bibleclip.theme import LIGHT_THEME, DARK_THEME


from bibleclip.core.formatter import Formatter


class ThemeMixin:
    def _toggle_dark_mode(self):
        self.settings['dark_mode'] = not self.settings['dark_mode']
        self.theme = DARK_THEME if self.settings['dark_mode'] else LIGHT_THEME
        # Switch CTk widgets (top bar, tabs) to the matching appearance.
        ctk.set_appearance_mode('dark' if self.settings['dark_mode'] else 'light')
        self.dark_btn.configure(
            text="라이트 모드" if self.settings['dark_mode'] else "다크 모드")
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

        # Root — CustomTkinter's CTk root takes fg_color, not tk's bg.
        try:
            self.root.configure(bg=t['bg'])
        except (tk.TclError, ValueError):
            self.root.configure(fg_color=t['bg'])
        # main_frame, top_bar, title, monitor/dark/update buttons and the tab
        # bar are CTk widgets — they re-skin automatically via appearance mode.
        self._update_status("모니터링 중" if self.monitoring else "대기 중", self.monitoring)

        # Tab content frames remain tk
        self.tab_viewer.configure(bg=t['bg'])
        self.tab_settings.configure(bg=t['bg'])

        # --- Viewer tab ---
        self.viewer_pane.configure(bg=t['bg'], sashrelief=tk.FLAT)
        # log card + label are CTk (auto-skin); only the tk.Text needs colors
        self.log_text.configure(bg=t['viewer_bg'], fg=t['viewer_fg'],
                                insertbackground=t['fg'])
        self.log_text.tag_configure('logref', foreground=t['accent'])

        self.viewer_outer.configure(bg=t['bg'])
        # version_bar is a CTk card (auto-skin); chip_frame is a tk holder that
        # blends with the card so the placed chips sit on the card surface.
        self.chip_frame.configure(bg=t['viewer_bg'])
        self._apply_viewer_chip_theme()
        # nav is a CTk card with CTk controls (option menus, buttons, entries,
        # segmented dict toggle) — all auto-skin via appearance mode.
        # viewer_text_frame is a CTk card (auto-skin)
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
        # viewer_scroll is a CTkScrollbar (auto-skin)

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

        # --- Lexicon panels inside viewer tab ---
        # dict language toggle is a CTkSegmentedButton (auto-skin)
        if hasattr(self, 'viewer_hpane'):
            self.viewer_hpane.configure(bg=t['bg'], sashrelief=tk.FLAT)
        if hasattr(self, 'lex_mid_text'):
            sel_bg, sel_fg = t['select_bg'], t['select_fg']
            # cards / headers / scrollbars are CTk (auto-skin); theme the tk.Text only
            for txt in (self.lex_mid_text, self.lex_right_text):
                txt.configure(bg=t['viewer_bg'], fg=t['viewer_fg'],
                              insertbackground=t['fg'],
                              selectbackground=sel_bg, selectforeground=sel_fg)
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

