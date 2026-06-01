"""JS-facing bridge API for the pywebview front-end.

Each public method is callable from JavaScript as ``pywebview.api.<method>(...)``
and must return JSON-serializable values. This module deliberately does NOT
import `webview`, so it can be unit-tested headlessly against a plain Library.
Events that originate in Python (caught clipboard references) are pushed to the
front-end via the injected window's ``evaluate_js`` — still no `webview` import.
"""
import json
import re

try:
    import pyperclip
except Exception:  # pragma: no cover - clipboard backend optional at import
    pyperclip = None


# Dictionary entries are stored as a small pseudo-HTML markup (the same dialect
# rendered into tk tags by data.original_lang.render_dict_html). For the web we
# only need to translate the two non-standard pieces — '^' separators and the
# custom <num> tag; <b>/<br>/<sup>/<font color> render natively in a browser.
_NUM_RE = re.compile(r'<\s*num\s*>(.*?)<\s*/\s*num\s*>', re.S | re.I)


def markup_to_html(markup):
    if not markup:
        return ''
    html = markup.replace('^', '  ')
    html = _NUM_RE.sub(r'<span class="lex-num" data-code="\1">\1</span>', html)
    return html


class Api:
    """Thin, JSON-friendly facade over Library for the web front-end."""

    def __init__(self, library):
        self.lib = library
        self._window = None      # pywebview window, injected by webui.app.main()
        self.monitoring = False

    def set_window(self, window):
        """Receive the pywebview window so Python-side events can reach JS.

        Kept separate from __init__ so headless tests construct an Api with no
        window (pushes become no-ops)."""
        self._window = window

    def _push(self, fn, *args):
        """Invoke ``window.bibleclip.<fn>(...args)`` in the web view.

        Safe to call from the monitor worker thread (pywebview marshals
        evaluate_js to the UI thread) and a no-op when no window is attached."""
        if self._window is None:
            return
        payload = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
        js = f"window.bibleclip && window.bibleclip.{fn}({payload})"
        try:
            self._window.evaluate_js(js)
        except Exception:
            pass

    # ---- Clipboard monitoring ----

    def start_monitoring(self):
        """Begin watching the system clipboard. Caught references are converted
        in place (the formatted multi-version text replaces the clipboard) and
        pushed to JS via window.bibleclip.onReference; '#keyword' queries go to
        onKeyword."""
        if pyperclip is None:
            return {'ok': False, 'error': 'pyperclip unavailable'}
        self.lib.start_monitoring(
            self._clip_read, self._clip_write,
            self._on_reference, self._on_keyword)
        self.monitoring = True
        return {'ok': True}

    def stop_monitoring(self):
        self.lib.stop_monitoring()
        self.monitoring = False
        return {'ok': True}

    def _clip_read(self):
        try:
            return pyperclip.paste() or ''
        except Exception:
            return ''

    def _clip_write(self, text):
        try:
            pyperclip.copy(text)
        except Exception:
            pass

    def _on_reference(self, result):
        # result is already JSON-serializable (see Library.build_output).
        self._push('onReference', result)

    def _on_keyword(self, keyword):
        self._push('onKeyword', keyword)

    # ---- Bootstrap ----

    def get_initial(self):
        """Everything the UI needs on load, in one round-trip."""
        primary = self.lib.primary_version()
        s = self.lib.settings
        last_book = s.get('last_book_num')
        last_chapter = s.get('last_chapter')
        # Fall back to the first available book/chapter of the primary version.
        books = self.lib.books(primary) if primary else []
        if not (last_book and any(b['num'] == last_book for b in books)):
            last_book = books[0]['num'] if books else None
            last_chapter = None
        if last_book is not None and not last_chapter:
            chs = self.lib.get_chapters(primary, last_book)
            last_chapter = chs[0] if chs else 1
        return {
            'versions': self.lib.versions(),
            'primary': primary,
            'viewer': list(self.lib.settings.get('viewer_versions', [])),
            'books': books,
            'last': {'version': primary, 'book': last_book, 'chapter': last_chapter},
        }

    def set_viewer_versions(self, names):
        """Replace the set of versions shown in parallel in the viewer.

        The given names are filtered to loaded versions and re-sorted by the
        persistent ``viewer_version_order`` so the on-screen order stays stable
        regardless of toggle order. At least one version is always kept.
        Returns the cleaned, ordered list."""
        order = (self.lib.settings.get('viewer_version_order')
                 or list(self.lib.dbs.keys()))
        valid = {n for n in names if n in self.lib.dbs}
        ordered = [n for n in order if n in valid]
        for n in names:           # preserve any valid name missing from order
            if n in self.lib.dbs and n not in ordered:
                ordered.append(n)
        if not ordered:
            return list(self.lib.settings.get('viewer_versions', []))
        self.lib.settings['viewer_versions'] = ordered
        self.lib.save_settings()
        return ordered

    # ---- Output settings (the "출력 설정" tab) ----

    # Format keys the settings tab may write. Enums carry their allowed values;
    # bool keys map to None (coerced to a real bool on write).
    _FORMAT_KEYS = {
        'book_name': {'long_ko', 'short_ko', 'long_en', 'short_en'},
        'chapter_verse_format': {'colon', 'korean'},
        'bracket_style': {'none', '[]', '()'},
        'ref_position': {'before', 'after'},
        'range_symbol': {'-', '~'},
        'ref_body_separator': {' - ', ': ', ' '},
        'output_mode': {'inline', 'newline'},
        'newline_show_cv': None,
        'show_version_header': None,
        'hide_reference': None,
    }

    def get_settings(self):
        """The format settings + output order the settings tab needs."""
        s = self.lib.settings
        return {
            'format': {k: s.get(k) for k in self._FORMAT_KEYS},
            'output_order': list(s.get('output_order', [])),
            'versions': self.lib.versions(),  # name + display for label lookups
        }

    def set_setting(self, key, value):
        """Update one whitelisted format setting and persist. Returns {ok}."""
        if key not in self._FORMAT_KEYS:
            return {'ok': False, 'error': f'unknown key: {key}'}
        allowed = self._FORMAT_KEYS[key]
        if allowed is None:               # boolean setting
            value = bool(value)
        elif value not in allowed:
            return {'ok': False, 'error': f'invalid value for {key}: {value!r}'}
        self.lib.settings[key] = value
        self.lib.save_settings()
        return {'ok': True}

    def set_output_order(self, names):
        """Replace the clipboard output order (versions used when a reference is
        caught/copied). Filtered to loaded versions, dedup, order preserved as
        given. Returns the cleaned list."""
        seen = set()
        cleaned = []
        for n in names:
            if n in self.lib.dbs and n not in seen:
                seen.add(n)
                cleaned.append(n)
        self.lib.settings['output_order'] = cleaned
        self.lib.save_settings()
        return cleaned

    def get_preview(self):
        """Formatted output for the fixed sample (요 1:1-3) under current
        settings — exactly what would land on the clipboard."""
        r = self.lib.build_output('요 1:1-3')
        if r and r.get('kind') == 'reference':
            return r['text']
        if not self.lib.settings.get('output_order'):
            return '(출력할 성경 버전을 추가하세요)'
        return '(데이터를 찾을 수 없습니다)'

    # ---- Navigation data ----

    def get_books(self, version):
        return self.lib.books(version)

    def get_chapters(self, version, book):
        return self.lib.get_chapters(version, int(book))

    def get_chapter(self, version, book, chapter):
        book, chapter = int(book), int(chapter)
        db = self.lib.dbs.get(version)
        short = long_ = '?'
        if db and book in db.books:
            short, long_ = db.books[book]
        verses = [{'n': n, 'text': t}
                  for n, t in self.lib.get_chapter(version, book, chapter)]
        return {
            'ref': {'version': version, 'book': book,
                    'short': short, 'long': long_, 'chapter': chapter},
            'verses': verses,
        }

    def get_interlinear(self, book, chapter):
        """Strong's-tagged words per verse (KRV 개역한글S; version-independent)."""
        return [{'n': n, 'words': [{'w': w, 'code': c} for (w, c) in words]}
                for n, words in self.lib.interlinear(int(book), int(chapter))]

    # ---- Lexicon ----

    def lookup_strong(self, code, lang='ko'):
        markup = self.lib.lookup_strong(code, lang)
        if not markup:
            return None
        return {'code': code, 'html': markup_to_html(markup)}
