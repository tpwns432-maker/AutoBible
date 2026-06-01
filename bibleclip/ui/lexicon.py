"""Original-language panel: word click/hover/morphology/popup."""
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


class LexiconMixin:
    def _on_main_activate(self, event=None):
        """Main window came forward → the open dict popups are now behind it.
        Non-Windows fallback only; on Windows the real z-order is read at close."""
        if event is not None and event.widget is not self.root:
            return
        if getattr(self, '_closing_popup', False):
            return
        for p in getattr(self, '_lex_popups', []):
            try:
                p._above_main = False
            except Exception:
                pass

    # ---- Win32 z-order query (replaces the flaky <Activate> tracking) ----

    def _win_zorder_map(self):
        """{HWND: z-index} for every top-level window, 0 = frontmost.
        EnumWindows enumerates top-level windows in z-order (top → bottom)."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        order = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                         wintypes.LPARAM)

        def _cb(hwnd, lparam):
            order.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return {h: i for i, h in enumerate(order)}

    def _win_root_hwnd(self, win):
        """Top-level (title-bar) HWND owning a Tk window."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        GA_ROOT = 2
        return user32.GetAncestor(win.winfo_id(), GA_ROOT)

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

    def _on_lex_lang_seg(self, value):
        """Segmented dict-language toggle ('한글'/'영어') → lex_lang_var ('ko'/'en')."""
        self.lex_lang_var.set('ko' if value == '한글' else 'en')
        self._restyle_segmented(self.lex_lang_seg)
        self._on_lex_lang_changed()

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
        # On non-Windows we approximate "is this popup above main?" with <Activate>
        # events (see _on_main_activate). On Windows we read the true OS z-order at
        # close time instead, so this flaky tracking is skipped entirely.
        top._above_main = True
        if not IS_WINDOWS:
            top.bind('<Activate>', lambda e, w=top: setattr(w, '_above_main', True))
            if not getattr(self, '_main_activate_bound', False):
                self.root.bind('<Activate>', self._on_main_activate, add='+')
                self._main_activate_bound = True

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
            # Re-raise ONLY the popups that sit above the main window; leave the
            # ones the user pushed behind main where they are.
            if IS_WINDOWS:
                # Read the real z-order BEFORE destroying — destroy() perturbs the
                # stack and triggers a main-window activation.
                try:
                    zmap = self._win_zorder_map()
                    main_z = zmap.get(self._win_root_hwnd(self.root), 1 << 30)
                    ranked = [(zmap.get(self._win_root_hwnd(p), 1 << 30), p)
                              for p in self._lex_popups]
                    # bottom-most first so the final lift lands the true top on top
                    above = [p for z, p in sorted(ranked, key=lambda zp: zp[0],
                                                  reverse=True) if z < main_z]
                except Exception:
                    above = list(self._lex_popups)
                top.destroy()
            else:
                # Snapshot before destroy; flag so the activation the close fires
                # on main doesn't wrongly mark everything "behind".
                above = [p for p in self._lex_popups
                         if getattr(p, '_above_main', True)]
                self._closing_popup = True
                top.destroy()
                self.root.after(250,
                                lambda: setattr(self, '_closing_popup', False))

            for p in above:
                try:
                    p.lift()
                except Exception:
                    pass
            if above:
                try:
                    above[-1].focus_set()
                except Exception:
                    pass

        top.protocol("WM_DELETE_WINDOW", on_close)
        top.bind('<Escape>', lambda e: on_close())

    # ---- Version order management ----

