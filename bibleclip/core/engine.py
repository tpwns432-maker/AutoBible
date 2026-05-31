"""Bible reference parser: Korean/English styles -> book/chapter/verses."""
import re

from bibleclip.constants import KOREAN_BOOK_MAP, ENGLISH_BOOK_MAP
from bibleclip.text_utils import convert_qwerty_to_hangul


class Engine:
    VERSE_PATTERN = re.compile(
        # Book name: letters, with a digit allowed only when followed by more
        # letters (e.g. 요2서). A trailing digit must NOT be eaten as part of
        # the name, or "요15:4" would parse as book "요1", chapter 5.
        r'([가-힣a-zA-Z]+(?:\d[가-힣a-zA-Z]+)*)'
        r'\s*'
        r'(\d+)'
        r'\s*(?:장\s*)?'
        r'(?:'
        r'[:：]\s*(\d+(?:\s*[-~]\s*\d+)?(?:\s*[,，]\s*\d+(?:\s*[-~]\s*\d+)?)*)'
        r'|'
        r'(?:편\s*)?(\d+)\s*절'
        r')?'
        r'(?:\s*절)?'
    )

    KOREAN_STYLE_PATTERN = re.compile(
        r'([가-힣]+(?:\d[가-힣]+)*)'
        r'\s*(\d+)\s*장'
        r'(?:\s*(\d+(?:\s*[-~]\s*\d+)?(?:\s*[,，]\s*\d+(?:\s*[-~]\s*\d+)?)*)\s*절?)?'
    )

    ENGLISH_PATTERN = re.compile(
        r'(\d?\s*[a-zA-Z]+)'
        r'\s+'
        r'(\d+)'
        r'(?:'
        r'[:]\s*(\d+(?:\s*[-~]\s*\d+)?(?:\s*[,]\s*\d+(?:\s*[-~]\s*\d+)?)*)'
        r')?'
    )

    @staticmethod
    def parse_verses(verse_str):
        if not verse_str:
            return []
        verses = []
        verse_str = verse_str.replace(' ', '')
        parts = re.split(r'[,，]', verse_str)
        for part in parts:
            if '-' in part or '~' in part:
                bounds = re.split(r'[-~]', part)
                if len(bounds) == 2:
                    start, end = int(bounds[0]), int(bounds[1])
                    verses.extend(range(start, end + 1))
            else:
                verses.append(int(part))
        return sorted(set(verses))

    @staticmethod
    def resolve_ambiguous_book(book_str, has_verse_separator):
        if book_str == '요일': return KOREAN_BOOK_MAP['요일']
        if book_str == '요이': return KOREAN_BOOK_MAP['요이']
        if book_str == '요삼': return KOREAN_BOOK_MAP['요삼']
        if book_str == '요':  return KOREAN_BOOK_MAP['요']
        return None

    @classmethod
    def parse_reference(cls, text):
        text = text.strip()
        if not text:
            return []
        results = []

        m = cls.KOREAN_STYLE_PATTERN.search(text)
        if m:
            book_str, chapter = m.group(1), int(m.group(2))
            verse_str = m.group(3)
            verses = cls.parse_verses(verse_str) if verse_str else []
            book_info = cls._lookup_book(book_str, bool(verse_str))
            if book_info:
                results.append((*book_info, chapter, verses))
                return results

        m = cls.VERSE_PATTERN.search(text)
        if m:
            book_str, chapter = m.group(1), int(m.group(2))
            verse_str = m.group(3) or m.group(4)
            has_sep = m.group(3) is not None
            verses = cls.parse_verses(verse_str) if verse_str else []
            book_info = cls._lookup_book(book_str, has_sep)
            if book_info:
                results.append((*book_info, chapter, verses))
                return results

        m = cls.ENGLISH_PATTERN.search(text)
        if m:
            book_str, chapter = m.group(1).strip(), int(m.group(2))
            verse_str = m.group(3)
            verses = cls.parse_verses(verse_str) if verse_str else []
            book_info = cls._lookup_english_book(book_str)
            if book_info:
                results.append((*book_info, chapter, verses))
                return results
        return results

    @classmethod
    def _lookup_book(cls, book_str, has_verse_separator=True):
        if book_str in KOREAN_BOOK_MAP:
            resolved = cls.resolve_ambiguous_book(book_str, has_verse_separator)
            return resolved if resolved else KOREAN_BOOK_MAP[book_str]
        converted = convert_qwerty_to_hangul(book_str)
        if converted and converted in KOREAN_BOOK_MAP:
            resolved = cls.resolve_ambiguous_book(converted, has_verse_separator)
            return resolved if resolved else KOREAN_BOOK_MAP[converted]
        return None

    @classmethod
    def _lookup_english_book(cls, book_str):
        key = book_str.lower().replace(' ', '')
        if key in ENGLISH_BOOK_MAP:
            bn = ENGLISH_BOOK_MAP[key]
            for v in KOREAN_BOOK_MAP.values():
                if v[0] == bn:
                    return v
        return None
