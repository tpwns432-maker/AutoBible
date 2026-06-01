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
from bibleclip.core.library import Library
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
    # Settings schema/defaults now live on Library (the UI-agnostic core).
    # Kept as a class alias for any code that referenced BibleClipApp.DEFAULT_SETTINGS.
    DEFAULT_SETTINGS = Library.DEFAULT_SETTINGS

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

        # Core: the UI-agnostic engine (bible DBs, original-language data,
        # settings, reference→output pipeline, clipboard monitor). The alias
        # attributes below share the same dicts/objects by reference, so the
        # existing mixin code keeps working unchanged.
        self.core = Library()
        self.bible_dbs = self.core.dbs
        self.settings = self.core.settings
        self.bethlehem_strongs = self.core.bethlehem_strongs
        self.bethlehem_wonjun = self.core.bethlehem_wonjun
        self.lexicon_ko = self.core.lexicon_ko
        self.lexicon_en = self.core.lexicon_en

        # UI-only state
        self.monitoring = False
        self._sync_lock = False        # viewer ↔ middle scroll sync guard
        self._sync_pending = False     # debounce pending
        self._tip = None               # hover tooltip window
        self._tip_after = None         # scheduled tooltip callback id
        self._tip_word = None          # (code, verse) under the cursor
        self._log_refs = []            # session-only clickable log references
        self._lex_popups = []          # open independent dictionary windows
        self._search_results = []      # current search results (book, chap, verse)

        # Apply saved window geometry (Library loads/validates settings headlessly).
        self.root.geometry(self.settings.get('geometry', '1100x780'))

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

    # ---- Database / settings (delegated to the core) ----
    # The heavy lifting lives in bibleclip.core.library.Library; these thin
    # wrappers remain because UI mixins call them and they bridge UI-only
    # concerns (window geometry, refreshing the version list).

    def _bethlehem_ready(self):
        return self.core.bethlehem_ready()

    def _refresh_databases(self):
        """Rescan for new DB files, then refresh the available-version list."""
        self.core.refresh_databases()
        self._refresh_available_list()

    def _save_settings(self):
        # Stamp the live window size before persisting (UI-only field).
        self.settings['geometry'] = self.root.geometry()
        self.core.save_settings()

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
        self._restyle_tabs()

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
        self._restyle_tabs()

    def _restyle_segmented(self, seg):
        """White text on the selected segment (CTkSegmentedButton has no
        per-state text color, so paint its internal buttons directly)."""
        try:
            cur = seg.get()
            for val, btn in seg._buttons_dict.items():
                btn.configure(text_color=CTK['on_accent'] if val == cur
                              else CTK['btn_text'])
        except Exception:
            pass

    def _restyle_tabs(self):
        self._restyle_segmented(self.tab_bar)

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
