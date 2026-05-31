"""BibleDB: one SQLite bible version + lazy whitespace/fuzzy search index."""
import os
import sqlite3

from bibleclip.constants import ENGLISH_VERSIONS
from bibleclip.text_utils import clean_text, despace, trigrams


class BibleDB:
    def __init__(self, db_path):
        self.db_path = db_path
        self.name = os.path.splitext(os.path.basename(db_path))[0]
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.is_english = self.name.upper() in ENGLISH_VERSIONS
        self._search_index = None   # built lazily on first search
        self._load_info()
        self._load_books()

    def _load_info(self):
        cur = self.conn.cursor()
        cur.execute("SELECT name, value FROM info")
        self.info = dict(cur.fetchall())
        self.description = self.info.get('description', self.name)
        self.language = self.info.get('language', 'ko')
        if self.language == 'en':
            self.is_english = True

    def _load_books(self):
        cur = self.conn.cursor()
        cur.execute("SELECT book_number, short_name, long_name FROM books ORDER BY book_number")
        self.books = {}
        self.book_list = []
        for bn, short, long_ in cur.fetchall():
            self.books[bn] = (short, long_)
            self.book_list.append((bn, short, long_))

    def get_chapters(self, book_number):
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT chapter FROM verses WHERE book_number=? ORDER BY chapter",
                     (book_number,))
        return [r[0] for r in cur.fetchall()]

    def get_verses(self, book_number, chapter):
        cur = self.conn.cursor()
        cur.execute("SELECT verse, text FROM verses WHERE book_number=? AND chapter=? ORDER BY verse",
                     (book_number, chapter))
        return [(v, clean_text(t)) for v, t in cur.fetchall()]

    def get_verse_text(self, book_number, chapter, verse):
        cur = self.conn.cursor()
        cur.execute("SELECT text FROM verses WHERE book_number=? AND chapter=? AND verse=?",
                     (book_number, chapter, verse))
        row = cur.fetchone()
        return clean_text(row[0]) if row else ''

    def _build_search_index(self):
        """Cache (book, chap, verse, cleaned, despaced, trigrams) once."""
        if self._search_index is not None:
            return
        cur = self.conn.cursor()
        cur.execute("SELECT book_number, chapter, verse, text FROM verses "
                    "ORDER BY book_number, chapter, verse")
        idx = []
        for b, c, v, t in cur.fetchall():
            ct = clean_text(t)
            dt = despace(ct)
            idx.append((b, c, v, ct, dt, trigrams(dt)))
        self._search_index = idx

    def search(self, keyword, limit=300, fuzzy_threshold=0.7):
        """Whitespace-insensitive verse search with a fuzzy fallback.

        1) Exact (spacing-ignored) substring matches, in canonical order.
        2) If none, rank verses by trigram overlap with the query (handles
           particle changes / minor typos) and return those above a threshold.
        Returns a list of (book_number, chapter, verse, cleaned_text).
        """
        keyword = (keyword or '').strip()
        if not keyword:
            return []
        self._build_search_index()
        qd = despace(keyword)
        if not qd:
            return []
        exact = [(b, c, v, ct) for (b, c, v, ct, dt, tri) in self._search_index
                 if qd in dt]
        if exact:
            return exact[:limit]
        qtri = trigrams(qd)
        if not qtri:
            return []
        scored = []
        for (b, c, v, ct, dt, tri) in self._search_index:
            if not tri:
                continue
            inter = len(qtri & tri)
            if not inter:
                continue
            score = inter / len(qtri)
            if score >= fuzzy_threshold:
                scored.append((score, b, c, v, ct))
        scored.sort(key=lambda r: (-r[0], r[1], r[2], r[3]))
        return [(b, c, v, ct) for _, b, c, v, ct in scored[:limit]]

    def close(self):
        self.conn.close()

    @property
    def display_name(self):
        return f"{self.description} [{self.name}]"
