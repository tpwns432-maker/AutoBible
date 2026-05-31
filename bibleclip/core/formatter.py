"""Formatter: build output text for one bible version from settings."""


class Formatter:
    """Generates formatted bible output text based on user settings."""

    def __init__(self, settings, dbs=None):
        self.s = settings  # dict of all settings
        self.dbs = dbs or {}

    def _foreign_book_name(self, book_num, want_english):
        """Find a (short, long) name pair from a loaded DB matching the requested language."""
        for db in self.dbs.values():
            if db.is_english == want_english and book_num in db.books:
                return db.books[book_num]
        return None

    def format_version_output(self, db, book_num, chapter, verses, all_verse_data):
        """Format output for a single bible version.

        Args:
            db: BibleDB instance
            book_num: book number
            chapter: chapter number
            verses: list of verse numbers
            all_verse_data: list of (verse_num, text) tuples
        Returns:
            formatted string
        """
        s = self.s
        is_eng = db.is_english

        # --- Determine book display name (apply same setting to all versions) ---
        db_short, db_long = db.books.get(book_num, ('?', '?'))
        style = s['book_name']
        if style in ('long_ko', 'short_ko'):
            if is_eng:
                foreign = self._foreign_book_name(book_num, want_english=False)
                if foreign:
                    f_short, f_long = foreign
                    book_display = f_long if style == 'long_ko' else f_short
                else:
                    book_display = db_long if style == 'long_ko' else db_short
            else:
                book_display = db_long if style == 'long_ko' else db_short
        elif style in ('long_en', 'short_en'):
            if is_eng:
                book_display = db_long if style == 'long_en' else db_short
            else:
                foreign = self._foreign_book_name(book_num, want_english=True)
                if foreign:
                    f_short, f_long = foreign
                    book_display = f_long if style == 'long_en' else f_short
                else:
                    book_display = db_long if style == 'long_en' else db_short
        else:
            book_display = db_short

        # --- Build reference string ---
        range_sym = s.get('range_symbol', '-')
        verse_list_str = self._format_verse_list(verses, range_sym) if verses else ''

        if s['chapter_verse_format'] == 'korean':
            if verse_list_str:
                ref_str = f"{book_display} {chapter}장 {verse_list_str}절"
            else:
                ref_str = f"{book_display} {chapter}장"
        else:
            if verse_list_str:
                ref_str = f"{book_display} {chapter}:{verse_list_str}"
            else:
                ref_str = f"{book_display} {chapter}"

        # --- Build version header ---
        version_header = ""
        if s.get('show_version_header', True):
            version_header = f"[{db.name}]"

        # --- Build body ---
        multiline = s['output_mode'] == 'newline'
        show_chapterverse = s.get('newline_show_cv', False)

        if multiline and len(all_verse_data) > 1:
            lines = []
            for v_num, v_text in all_verse_data:
                if show_chapterverse:
                    lines.append(f"{chapter}:{v_num} {v_text}")
                else:
                    lines.append(f"{v_num} {v_text}")
            body = '\n'.join(lines)
        else:
            # inline - join all texts
            body = ' '.join(text for _, text in all_verse_data)

        # --- Assemble with brackets/position ---
        hide_ref = s.get('hide_reference', False)
        if hide_ref:
            # Text only, no reference
            if version_header:
                return f"{version_header}\n{body}"
            return body

        # Bracket style
        bracket = s.get('bracket_style', 'none')
        if bracket == '[]':
            ref_display = f"[{ref_str}]"
        elif bracket == '()':
            ref_display = f"({ref_str})"
        else:
            ref_display = ref_str

        # Separator between ref and body
        ref_sep = s.get('ref_body_separator', ' ')

        # Position
        position = s.get('ref_position', 'before')

        if position == 'before':
            if version_header:
                main_line = f"{version_header} {ref_display}{ref_sep}{body}"
            else:
                main_line = f"{ref_display}{ref_sep}{body}"
        else:  # after
            if version_header:
                main_line = f"{version_header} {body}{ref_sep}{ref_display}"
            else:
                main_line = f"{body}{ref_sep}{ref_display}"

        return main_line

    @staticmethod
    def _format_verse_list(verses, range_sym='-'):
        if not verses:
            return ''
        ranges = []
        start = end = verses[0]
        for v in verses[1:]:
            if v == end + 1:
                end = v
            else:
                ranges.append(f"{start}{range_sym}{end}" if start != end else str(start))
                start = end = v
        ranges.append(f"{start}{range_sym}{end}" if start != end else str(start))
        return ','.join(ranges)

