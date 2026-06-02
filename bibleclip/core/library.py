"""Library: the UI-agnostic core of BibleClip.

Owns every piece of non-UI state and logic — loaded bible databases, the
original-language data (Strong's bible + lexicons), user settings, the
reference→formatted-output pipeline, search, and clipboard monitoring.

Both the CustomTkinter desktop app (`bibleclip.ui`) and the future web UI
consume this same object; nothing here imports tkinter or touches a window,
so a `Library()` can be constructed and exercised headlessly.
"""
import os
import json

from bibleclip.config import (
    BASE_DIR, SETTINGS_FILE, LEGACY_SETTINGS_FILE, BIBLE_DIR,
    resolve_data_dir,
)
from bibleclip.core.engine import Engine
from bibleclip.core.formatter import Formatter
from bibleclip.core.clipboard_monitor import ClipboardMonitor
from bibleclip.data.bible_db import BibleDB
from bibleclip.data.original_lang import (
    resolve_original_lang_dir, BethlehemDB, Lexicon, parse_korean_strongs,
    parse_wonjun_verse,
)


class Library:
    DEFAULT_SETTINGS = {
        'book_name': 'short_ko',         # short_ko, long_ko, short_en, long_en
        'chapter_verse_format': 'colon',  # colon, korean
        'bracket_style': 'none',          # none, [], ()
        'ref_position': 'before',         # before, after
        'range_symbol': '-',              # -, ~
        'ref_body_separator': ' ',        # ' ' (space), ' - ' (hyphen), ': ' (colon)
        'show_version_header': True,
        'hide_reference': False,
        'output_mode': 'inline',          # inline, newline
        'newline_show_cv': False,         # show chapter:verse on each line
        'output_order': [],               # ordered list of version names
        'viewer_versions': [],            # checked versions in viewer (ordered subset)
        'viewer_version_order': [],       # full viewer ordering (checked + unchecked)
        'viewer_font_size': 11,
        'auto_update_check': True,
        'skip_update_version': '',
        'lex_lang': 'ko',                 # default dictionary language (ko/en)
        'poll_interval': 0.5,             # clipboard polling interval (seconds)
        'search_click_navigates': False,  # search hit click also jumps the viewer
        'dark_mode': False,
        'geometry': '1100x780',
        'last_book_num': None,            # remember last viewed book/chapter
        'last_chapter': None,
        'viewer_hsash': [],               # horizontal 3-panel sash x positions
        'viewer_vsash': None,             # vertical (panels/log) sash y position
        'lex_popup_size': '440x480',      # size for new independent dict windows
        'web_geometry': None,             # {w,h,x,y} for the web UI window (web-only;
                                          # kept separate from tk 'geometry')
    }

    def __init__(self):
        self.dbs = {}
        self.bethlehem_strongs = None  # 개역한글S — KRV-based, drives middle panel
        self.bethlehem_wonjun = None   # 원전분해 — kept for potential future use
        self.lexicon_ko = None
        self.lexicon_en = None
        self.settings = dict(self.DEFAULT_SETTINGS)
        self._monitor = None

        self.load_databases()
        self.load_bethlehem()
        self.load_settings()

    # ---- Database loading ----

    def load_databases(self):
        db_dir = resolve_data_dir(BIBLE_DIR)
        if not os.path.isdir(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            return
        for fname in sorted(os.listdir(db_dir)):
            if fname.lower().endswith(('.sqlite3', '.sqlite', '.db')):
                path = os.path.join(db_dir, fname)
                try:
                    db = BibleDB(path)
                    self.dbs[db.name] = db
                except Exception as e:
                    print(f"Error loading {fname}: {e}")

    def load_bethlehem(self):
        """Load KRV-with-Strong's + lexicons from the original_lang folder."""
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

    def bethlehem_ready(self):
        return bool(self.bethlehem_strongs and (self.lexicon_ko or self.lexicon_en))

    def refresh_databases(self):
        """Rescan the bible_versions folder for new DB files.

        Returns the list of newly loaded version names (so a UI can refresh its
        own version lists).
        """
        db_dir = resolve_data_dir(BIBLE_DIR)
        if not os.path.isdir(db_dir):
            return []
        existing = set(self.dbs.keys())
        added = []
        for fname in sorted(os.listdir(db_dir)):
            if fname.lower().endswith(('.sqlite3', '.sqlite', '.db')):
                name = os.path.splitext(fname)[0]
                if name not in existing:
                    path = os.path.join(db_dir, fname)
                    try:
                        db = BibleDB(path)
                        self.dbs[db.name] = db
                        added.append(db.name)
                    except Exception:
                        pass
        return added

    # ---- Settings ----

    def load_settings(self):
        """Load + validate settings from disk. UI concerns (window geometry)
        are left to the caller, which reads ``self.settings['geometry']``."""
        path = os.path.join(BASE_DIR, SETTINGS_FILE)
        # One-time migration: if the new file doesn't exist yet but the legacy
        # autobible_settings.json does, read from it. The next save_settings
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
            except Exception:
                pass

        # Validate output_order. When empty (fresh install), default to a
        # Korean version so clipboard monitoring produces output immediately
        # instead of silently doing nothing.
        valid_order = [n for n in self.settings['output_order'] if n in self.dbs]
        if not valid_order and self.dbs:
            versions = list(self.dbs.keys())
            korean_pref = [v for v in ('KRV', 'NRKV', 'KNRSV') if v in versions]
            valid_order = [korean_pref[0] if korean_pref else versions[0]]
        self.settings['output_order'] = valid_order

        # Validate viewer_versions; default to KRV (or next-best Korean) when empty.
        valid_viewer = [n for n in self.settings.get('viewer_versions', []) if n in self.dbs]
        # Migration from v1.0.0: previous default was alphabetical ['KNRSV'].
        # If the saved choice is exactly that default and KRV is available, switch.
        if valid_viewer == ['KNRSV'] and 'KRV' in self.dbs:
            valid_viewer = ['KRV']
        if not valid_viewer and self.dbs:
            versions = list(self.dbs.keys())
            korean_pref = [v for v in ('KRV', 'NRKV', 'KNRSV') if v in versions]
            valid_viewer = [korean_pref[0] if korean_pref else versions[0]]
        self.settings['viewer_versions'] = valid_viewer

        # Validate viewer_version_order: must contain all loaded DBs in some order.
        saved_order = [n for n in self.settings.get('viewer_version_order', []) if n in self.dbs]
        for n in self.dbs:
            if n not in saved_order:
                saved_order.append(n)
        if not saved_order:
            saved_order = list(self.dbs.keys())
        self.settings['viewer_version_order'] = saved_order

        # Clamp font size
        try:
            self.settings['viewer_font_size'] = int(self.settings.get('viewer_font_size', 11))
        except (TypeError, ValueError):
            self.settings['viewer_font_size'] = 11
        self.settings['viewer_font_size'] = max(8, min(30, self.settings['viewer_font_size']))

    def save_settings(self):
        """Persist settings to disk. The caller is responsible for stamping any
        UI-only fields (e.g. ``settings['geometry']``) before calling."""
        path = os.path.join(BASE_DIR, SETTINGS_FILE)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---- Read API (UI-agnostic) ----

    def versions(self):
        """[{'name', 'display'}] for every loaded version, in load order."""
        return [{'name': name, 'display': db.display_name}
                for name, db in self.dbs.items()]

    def books(self, version):
        """[{'num', 'short', 'long'}] for one version (canonical book order)."""
        db = self.dbs.get(version)
        if not db:
            return []
        return [{'num': bn, 'short': short, 'long': long_}
                for bn, short, long_ in db.book_list]

    def primary_version(self):
        """Best default version: first checked viewer version, else first DB."""
        for n in self.settings.get('viewer_versions', []):
            if n in self.dbs:
                return n
        return next(iter(self.dbs), None)

    def parse_reference(self, text):
        return Engine.parse_reference(text)

    def get_chapters(self, version, book_num):
        db = self.dbs.get(version)
        return db.get_chapters(book_num) if db else []

    def get_chapter(self, version, book_num, chapter):
        """Return [(verse, text), ...] for one chapter of one version."""
        db = self.dbs.get(version)
        return db.get_verses(book_num, chapter) if db else []

    def search(self, version, keyword):
        db = self.dbs.get(version)
        return db.search(keyword) if db else []

    def lookup_strong(self, code, lang='ko'):
        """Raw lexicon entry (pseudo-HTML markup) for a Strong's code, or None.

        Rendering the markup is a UI concern (tk: original_lang.render_dict_html;
        web: a markup→HTML converter)."""
        lex = self.lexicon_en if lang == 'en' else self.lexicon_ko
        return lex.lookup(code) if lex else None

    def interlinear(self, book_num, chapter):
        """[(verse, [(word, code), ...]), ...] from the Strong's-tagged KRV."""
        if not self.bethlehem_strongs:
            return []
        out = []
        for verse, btext in self.bethlehem_strongs.get_chapter_verses(book_num, chapter):
            out.append((verse, parse_korean_strongs(btext)))
        return out

    def morphology(self, code, book_num, chapter, verse):
        """Morphological analysis entries for one Strong's code in one verse,
        from 원전분해.sdb: [{'lemma','translit','pos','gloss'}, ...] (possibly
        empty when the data isn't loaded or the word isn't present)."""
        if not (self.bethlehem_wonjun and verse and book_num):
            return []
        try:
            rows = self.bethlehem_wonjun.get_chapter_verses(book_num, chapter)
        except Exception:
            return []
        btext = next((t for vn, t in rows if vn == verse), None)
        if not btext:
            return []
        return [{'lemma': w['lemma'], 'translit': w['translit'],
                 'pos': w['pos'], 'gloss': w['gloss']}
                for w in parse_wonjun_verse(btext) if w['code'] == code]

    # ---- Reference → output pipeline ----

    def build_output(self, text):
        """Turn clipboard text into a structured result, or None.

        Returns one of:
          {'kind': 'keyword', 'keyword': str}
          {'kind': 'reference', 'book_num', 'chapter', 'verses', 'short_name',
           'text' (multi-version formatted string), 'n_parts'}
          None  — no reference matched, or matched but no loaded version had it.
        """
        text = (text or '').strip()
        if not text:
            return None

        if text.startswith('#'):
            keyword = text[1:].strip()
            if keyword:
                return {'kind': 'keyword', 'keyword': keyword}
            return None

        refs = Engine.parse_reference(text)
        if not refs:
            return None
        book_num, short_name, long_name, chapter, verses = refs[0]

        text_out, n_parts = self.format_reference(book_num, chapter, verses)
        if not text_out:
            return None
        return {
            'kind': 'reference',
            'book_num': book_num,
            'chapter': chapter,
            'verses': verses,
            'short_name': short_name,
            'text': text_out,
            'n_parts': n_parts,
        }

    def format_reference(self, book_num, chapter, verses, order=None):
        """Format one reference across a list of versions.

        ``order`` defaults to the configured ``output_order`` (clipboard
        output); callers may pass an explicit list (e.g. the viewer's versions
        for manual copy). ``verses`` may be a list or empty/None for the whole
        chapter. Returns ``(text, n_parts)`` — ``('', 0)`` when nothing matched."""
        if order is None:
            order = self.settings.get('output_order') or []
        if not order:
            return '', 0
        fmt = Formatter(self.settings, self.dbs)
        parts = []
        for ver_name in order:
            db = self.dbs.get(ver_name)
            if db is None or book_num not in db.books:
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
        if not parts:
            return '', 0
        return '\n\n'.join(parts), len(parts)

    # ---- Clipboard monitoring ----

    def start_monitoring(self, read_fn, write_fn, on_reference, on_keyword):
        self.stop_monitoring()
        interval = (self.settings.get('poll_interval')
                    or ClipboardMonitor.POLL_INTERVAL)
        self._monitor = ClipboardMonitor(read_fn, write_fn, self.build_output,
                                         on_reference, on_keyword,
                                         poll_interval=interval)
        self._monitor.start()

    def stop_monitoring(self):
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    def set_poll_interval(self, seconds):
        """Re-tune a running monitor's polling interval (no restart needed)."""
        if self._monitor is not None:
            self._monitor.poll_interval = seconds

    def notify_clipboard_written(self, text):
        """Tell an active monitor that `text` was just placed on the clipboard
        by other code, so it isn't re-detected as fresh input."""
        if self._monitor is not None:
            self._monitor.last = text
