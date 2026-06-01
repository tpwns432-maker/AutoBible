"""Hebrew/Greek original-language data: Strong's Bible, lexicons, parsers."""
import os
import re
import sqlite3

from bibleclip.config import BASE_DIR, candidate_data_roots, BODY_FONT


ORIGINAL_LANG_DIR = "original_lang"
LEGACY_ORIGINAL_LANG_DIRS = ["BethlehemWin"]


def resolve_original_lang_dir(base_dir=None):
    """Find the original-language data dir across candidate roots.

    Checks 'original_lang' then legacy names, in each candidate root (next to
    the app, then inside a macOS .app bundle). Falls back to BASE_DIR/original_lang.
    """
    names = [ORIGINAL_LANG_DIR] + LEGACY_ORIGINAL_LANG_DIRS
    for root in candidate_data_roots():
        for name in names:
            p = os.path.join(root, name)
            if os.path.isdir(p):
                return p
    return os.path.join(BASE_DIR, ORIGINAL_LANG_DIR)

# Bethlehem dbs use 1..66 Protestant numbering. Map to/from our 10..730 scheme
# (deuterocanonical slots 170,180,200,210,270,280,320 are skipped).
PROTESTANT_BOOK_ORDER = [
    10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
    110, 120, 130, 140, 150, 160, 190,
    220, 230, 240, 250, 260,
    290, 300, 310, 330, 340,
    350, 360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460,
    470, 480, 490, 500, 510, 520, 530, 540, 550, 560,
    570, 580, 590, 600, 610, 620, 630, 640, 650, 660,
    670, 680, 690, 700, 710, 720, 730,
]
OUR_TO_BETHLEHEM = {b: i + 1 for i, b in enumerate(PROTESTANT_BOOK_ORDER)}
BETHLEHEM_TO_OUR = {i + 1: b for i, b in enumerate(PROTESTANT_BOOK_ORDER)}


class BethlehemDB:
    """Thin wrapper around a Bethlehem SQLite Bible (Bible(book,chapter,verse,btext))."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.name = os.path.splitext(os.path.basename(db_path))[0]
        self.conn = sqlite3.connect(db_path, check_same_thread=False)

    def get_chapter_verses(self, our_book_num, chapter):
        bn = OUR_TO_BETHLEHEM.get(our_book_num)
        if bn is None:
            return []
        cur = self.conn.cursor()
        cur.execute("SELECT verse, btext FROM Bible WHERE book=? AND chapter=? ORDER BY verse",
                    (bn, chapter))
        return cur.fetchall()

    def get_chapter_count(self, our_book_num):
        bn = OUR_TO_BETHLEHEM.get(our_book_num)
        if bn is None:
            return 0
        cur = self.conn.cursor()
        cur.execute("SELECT MAX(chapter) FROM Bible WHERE book=?", (bn,))
        row = cur.fetchone()
        return row[0] if row and row[0] else 0

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


class Lexicon:
    """Strong's dictionary (Lexicon(scode, dtext)). scode is 'H1234' or 'G1234'."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)

    def lookup(self, code):
        cur = self.conn.cursor()
        cur.execute("SELECT dtext FROM Lexicon WHERE scode=?", (code,))
        row = cur.fetchone()
        return row[0] if row else None

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# Each word block in 원전분해.sdb btext looks like:
#   [surface] (기본 <WH7225> [lemma] translit)@POS # gloss*
# Blocks are separated by '*' followed by newline/space.
WONJUN_BLOCK = re.compile(
    r'\[(?P<surface>[^\]]+)\]\s*'
    r'\(\s*기본\s*<W(?P<lang>[HG])(?P<num>\d+)>\s*'
    r'\[(?P<lemma>[^\]]+)\]\s*(?P<translit>[^)]*)\)\s*'
    r'@\s*(?P<pos>[^#*]*?)\s*'
    r'(?:#\s*(?P<gloss>[^*]*?))?\s*\*',
    re.DOTALL,
)


KOREAN_STRONG_TAG = re.compile(r'<W([HG])(\d+)>')


def parse_korean_strongs(text):
    """Parse Korean Strong's-tagged text into a list of (word, code) tuples.

    Each '<WHxxxx>' or '<WGxxxx>' tag belongs to the text immediately before it
    (which may include spaces, e.g. '위에 있고<WH5921>'). Trailing text without
    a tag is appended with code=None.
    """
    out = []
    last_end = 0
    for m in KOREAN_STRONG_TAG.finditer(text or ''):
        word = (text[last_end:m.start()]).strip()
        if word:
            out.append((word, f"{m.group(1)}{m.group(2)}"))
        last_end = m.end()
    trail = (text[last_end:] if text else '').strip()
    if trail:
        out.append((trail, None))
    return out


def parse_wonjun_verse(text):
    """Parse 원전분해 verse text into list of word dicts."""
    out = []
    if not text:
        return out
    for m in WONJUN_BLOCK.finditer(text):
        out.append({
            'surface': m.group('surface').strip(),
            'code': f"{m.group('lang')}{m.group('num')}",
            'lemma': m.group('lemma').strip(),
            'translit': (m.group('translit') or '').strip(),
            'pos': (m.group('pos') or '').strip(),
            'gloss': (m.group('gloss') or '').strip(),
        })
    return out


def render_dict_html(text_widget, html, base_font=(BODY_FONT, 10), fg='#000000',
                     num_color='#6D4DFF'):
    """Render HTML-marked dictionary text into a Tk Text widget.

    Handles a small subset: <font color>, <b>, <br>, <sup>, <num>, '^' separator.
    """
    import tkinter as tk  # local: keeps this module importable without a display
    from html.parser import HTMLParser

    text_widget.configure(state=tk.NORMAL)
    text_widget.delete('1.0', tk.END)

    bold_font = (base_font[0], base_font[1], 'bold')
    text_widget.tag_configure('_b', font=bold_font)
    text_widget.tag_configure('_sup', offset=4, font=(base_font[0], max(7, base_font[1] - 3)))
    text_widget.tag_configure('_num', foreground=num_color, underline=True)

    counter = [0]

    class _R(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack = []

        def handle_starttag(self, tag, attrs):
            tag = tag.lower()
            ad = dict(attrs)
            if tag == 'br':
                text_widget.insert(tk.END, '\n')
                return
            if tag == 'font':
                color = ad.get('color') or fg
                tname = f'_fc_{counter[0]}'
                counter[0] += 1
                text_widget.tag_configure(tname, foreground=color)
                self.stack.append((tag, tname))
            elif tag == 'b':
                self.stack.append((tag, '_b'))
            elif tag == 'sup':
                self.stack.append((tag, '_sup'))
            elif tag == 'num':
                self.stack.append((tag, '_num'))

        def handle_endtag(self, tag):
            tag = tag.lower()
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    self.stack.pop(i)
                    return

        def handle_data(self, data):
            if not data:
                return
            # '^' is used as a separator in some entries; replace with newline.
            data = data.replace('^', '  ')
            tags = tuple(t[1] for t in self.stack)
            text_widget.insert(tk.END, data, tags)

    _R().feed(html or '')
    text_widget.configure(state=tk.DISABLED)
