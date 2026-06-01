"""JS-facing bridge API for the pywebview front-end.

Each public method is callable from JavaScript as ``pywebview.api.<method>(...)``
and must return JSON-serializable values. This module deliberately does NOT
import `webview`, so it can be unit-tested headlessly against a plain Library.
"""
import re


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
            'books': books,
            'last': {'version': primary, 'book': last_book, 'chapter': last_chapter},
        }

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
