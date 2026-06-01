"""Viewer: version chips, drag-reorder, chapter load, scroll-sync, font, copy."""
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


class ViewerOpsMixin:
    def _render_viewer_versions(self):
        """(Re)build the chip row according to self._viewer_order."""
        for w in self.chip_frame.winfo_children():
            w.destroy()
        self.viewer_chip_widgets = {}
        self.viewer_chip_labels = {}
        # reset chip-animation state (the widgets were just recreated)
        if getattr(self, '_chip_anim_job', None):
            try:
                self.root.after_cancel(self._chip_anim_job)
            except Exception:
                pass
        self._chip_anim_job = None
        self._chip_cur_x = {}
        for name in self._viewer_order:
            self._build_chip(name)
        self._layout_chips(animate=False)
        self._highlight_focused_chip()
        self._apply_viewer_chip_theme()

    def _build_chip(self, name):
        is_checked = name in self._viewer_checked
        # highlightthickness is kept constant (2) so focusing never changes the
        # chip's size — that would make the drag reflow jitter.
        outer = tk.Frame(self.chip_frame, relief=tk.SOLID, borderwidth=1,
                         padx=8, pady=3, cursor='fleur', highlightthickness=2)
        label_text = f"{'☑' if is_checked else '☐'} {name}"
        lbl = tk.Label(outer, text=label_text, font=(UI_FONT, 9), cursor='fleur')
        lbl.pack()
        # NOTE: not packed — _layout_chips() places every chip by absolute x.
        self.viewer_chip_widgets[name] = outer
        self.viewer_chip_labels[name] = lbl

        # Per-chip drag state
        state = {'press_x': 0, 'dragging': False, 'grab_dx': 0}

        def on_press(event):
            state['press_x'] = event.x_root
            state['dragging'] = False
            # cursor offset within the chip, so it doesn't jump when grabbed
            state['grab_dx'] = event.x_root - outer.winfo_rootx()
            # current insertion slot among the others = chip's home index
            self._drag_idx = self._viewer_order.index(name)
            self._set_viewer_focused(name)

        def on_motion(event):
            if not state['dragging'] and abs(event.x_root - state['press_x']) > 4:
                state['dragging'] = True
                outer.configure(relief=tk.SUNKEN)
                outer.lift()
            if state['dragging']:
                fx = event.x_root - self.chip_frame.winfo_rootx() - state['grab_dx']
                self._layout_chips(drag_name=name, drag_x=fx)

        def on_release(event):
            if state['dragging']:
                outer.configure(relief=tk.SOLID)
                self._commit_drag(name)
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
            c = accent if n == self._viewer_focused else border
            w.configure(highlightbackground=c, highlightcolor=c)

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

    # ---- Chip layout + live drag-reorder ----

    def _layout_chips(self, drag_name=None, drag_x=None, animate=True):
        """Compute each chip's target x and (optionally) ease them there.

        "Gravity pulls left": every chip wants to sit packed at the left. The
        dragged chip is exempt — it follows the cursor (drag_x) — and the rest
        smoothly slide to open a gap at the insertion slot. The insertion index
        is decided by the dragged chip's CENTER vs the others' fixed resting
        centers, so it's symmetric regardless of drag direction (no hysteresis).
        """
        order = [n for n in self._viewer_order if n in self.viewer_chip_widgets]
        if not order:
            self.chip_frame.configure(height=1)
            return
        self.chip_frame.update_idletasks()
        gap, pad = 6, 2
        wd = {n: self.viewer_chip_widgets[n].winfo_reqwidth() for n in order}
        h = max(self.viewer_chip_widgets[n].winfo_reqheight() for n in order)
        self.chip_frame.configure(height=h + 6)
        try:
            self.chip_frame.pack_propagate(False)
        except tk.TclError:
            pass

        targets = {}
        if drag_name is None or drag_name not in order:
            x = pad
            for n in order:
                targets[n] = x
                x += wd[n] + gap
            self._drag_target_order = order
        else:
            others = [n for n in order if n != drag_name]
            m = len(others)
            dw = wd[drag_name]
            drag_center = drag_x + dw / 2
            # compact left positions of the others (dragged removed)
            pre, xx = [], pad
            for n in others:
                pre.append(xx)
                xx += wd[n] + gap
            pre.append(xx)
            # Shift the insertion slot one neighbour at a time. Swap when the
            # dragged CENTER crosses the midpoint between its current empty slot
            # center and the adjacent neighbour's CURRENT (gap-aware) center.
            # The boundary is identical in both directions → symmetric, and it
            # tracks where chips actually are, so moved/unmoved chips behave the
            # same (no "must reach the far edge" feel).
            idx = max(0, min(getattr(self, '_drag_idx', m), m))
            while idx < m:                       # consider moving right
                gap_c = pre[idx] + dw / 2
                right_c = pre[idx] + dw + gap + wd[others[idx]] / 2
                if drag_center > (gap_c + right_c) / 2:
                    idx += 1
                else:
                    break
            while idx > 0:                       # consider moving left
                gap_c = pre[idx] + dw / 2
                left_c = pre[idx - 1] + wd[others[idx - 1]] / 2
                if drag_center < (gap_c + left_c) / 2:
                    idx -= 1
                else:
                    break
            self._drag_idx = idx
            insert_idx = idx
            x = pad
            for i, n in enumerate(others):
                if i == insert_idx:
                    x += dw + gap          # leave room for the dragged chip
                targets[n] = x
                x += wd[n] + gap
            # dragged chip tracks the cursor immediately (no easing), clamped
            fw = max(self.chip_frame.winfo_width(), int(x + gap))
            clamped = max(pad, min(int(drag_x), fw - dw - pad))
            self._chip_cur_x[drag_name] = clamped
            w = self.viewer_chip_widgets[drag_name]
            w.place(x=clamped, y=3)
            w.lift()
            self._drag_target_order = (others[:insert_idx] + [drag_name]
                                       + others[insert_idx:])

        self._chip_targets = targets
        self._chip_drag_name = drag_name
        if animate:
            self._start_chip_anim()
        else:
            for n, tx in targets.items():
                self._chip_cur_x[n] = tx
                self.viewer_chip_widgets[n].place(x=tx, y=3)

    def _start_chip_anim(self):
        if getattr(self, '_chip_anim_job', None):
            return                      # a tween loop is already running
        self._chip_anim_step()

    def _chip_anim_step(self):
        """Ease each non-dragged chip toward its target x (gravity → left)."""
        self._chip_anim_job = None
        targets = getattr(self, '_chip_targets', {})
        drag = getattr(self, '_chip_drag_name', None)
        moving = False
        for n, tx in targets.items():
            if n == drag:
                continue
            w = self.viewer_chip_widgets.get(n)
            if not w:
                continue
            cur = self._chip_cur_x.get(n, tx)
            d = tx - cur
            if abs(d) <= 1:
                cur = tx
            else:
                cur += d * 0.35          # ~160ms ease-out
                moving = True
            self._chip_cur_x[n] = cur
            try:
                w.place(x=int(round(cur)), y=3)
            except tk.TclError:
                pass
        if moving:
            self._chip_anim_job = self.root.after(16, self._chip_anim_step)

    def _commit_drag(self, drag_name):
        new_order = getattr(self, '_drag_target_order', None)
        if new_order and list(new_order) != list(self._viewer_order):
            self._viewer_order = list(new_order)
            self._save_viewer_state()
            self._load_chapter()
        # animate everyone (incl. the released chip) into their resting slots
        self._layout_chips(animate=True)
        self._highlight_focused_chip()

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
            self.book_combo.configure(values=[])
            self._book_number_map = {}
            return
        db = self.bible_dbs[primary]
        book_names = [f"{long_} ({short})" for bn, short, long_ in db.book_list]
        self._book_number_map = {f"{long_} ({short})": bn for bn, short, long_ in db.book_list}
        self.book_combo.configure(values=book_names)
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
                if target in (self.book_combo.cget('values') or []):
                    self.book_var.set(target)
                    chapters = db.get_chapters(bn)
                    self.chapter_combo.configure(values=[str(c) for c in chapters])
                    if chap and str(chap) in self.chapter_combo.cget('values'):
                        self.chapter_var.set(str(chap))
                    elif chapters:
                        self.chapter_var.set(str(chapters[0]))
                    self._load_chapter()
                    return
        self._on_book_changed(None)

    # ---- Panel split (sash) persistence ----

    def _restore_sash_positions(self, _tries=0):
        try:
            self.root.update_idletasks()
            hsash = self.settings.get('viewer_hsash') or []
            vsash = self.settings.get('viewer_vsash')
            # CTk cards realize their size late; if we place the sashes before the
            # panes are big enough, tk clamps them and the layout looks "reset".
            # Retry until the panes can actually honor the saved positions.
            need_w = (max(hsash) + 40) if hsash else 0
            need_h = (int(vsash) + 40) if vsash else 0
            pane_w = self.viewer_hpane.winfo_width()
            pane_h = self.viewer_pane.winfo_height()
            if _tries < 25 and ((need_w and pane_w < need_w)
                                or (need_h and pane_h < need_h)):
                self.root.after(60, lambda: self._restore_sash_positions(_tries + 1))
                return
            for i, x in enumerate(hsash):
                try:
                    self.viewer_hpane.sash_place(i, int(x), 1)
                except Exception:
                    pass
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

    def _on_book_picked(self, *_):
        """User chose a book from the dropdown → always jump to chapter 1."""
        self._on_book_changed(None, reset_chapter=True)

    def _on_book_changed(self, event=None, reset_chapter=False):
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
        self.chapter_combo.configure(values=[str(c) for c in chapters])
        current_chap = self.chapter_var.get()
        if (not reset_chapter and current_chap
                and current_chap in self.chapter_combo.cget('values')):
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
        # Tell the monitor we wrote this, so it isn't re-detected as input.
        self.core.notify_clipboard_written(result)
        verse_str = Formatter._format_verse_list(verse_nums, self.settings.get('range_symbol', '-'))
        self._append_log(f"[복사] {chapter}:{verse_str} → {len(parts)}개 버전\n")

    # ---- Keyword search ----

