"""Text helpers: hangul assembly, cleaning, and search shingles."""
import re

from bibleclip.constants import (
    QWERTY_TO_HANGUL, CHOSEONG, JUNGSEONG, JONGSEONG,
    COMPLEX_JUNGSEONG, COMPLEX_JONGSEONG,
)

def qwerty_to_jamo(text):
    return [QWERTY_TO_HANGUL.get(c, c) for c in text]

def is_choseong(j): return j in CHOSEONG
def is_jungseong(j): return j in JUNGSEONG

def assemble_hangul(jamo_list):
    result = []
    i = 0
    while i < len(jamo_list):
        j = jamo_list[i]
        if is_choseong(j) and i + 1 < len(jamo_list) and is_jungseong(jamo_list[i + 1]):
            cho = CHOSEONG.index(j)
            i += 1
            jung_char = jamo_list[i]
            if i + 1 < len(jamo_list) and is_jungseong(jamo_list[i + 1]):
                pair = (jung_char, jamo_list[i + 1])
                if pair in COMPLEX_JUNGSEONG:
                    jung_char = COMPLEX_JUNGSEONG[pair]
                    i += 1
            jung = JUNGSEONG.index(jung_char)
            jong = 0
            if i + 1 < len(jamo_list) and is_choseong(jamo_list[i + 1]):
                potential_jong = jamo_list[i + 1]
                if i + 2 < len(jamo_list) and is_jungseong(jamo_list[i + 2]):
                    pass
                elif potential_jong in JONGSEONG:
                    if (i + 2 < len(jamo_list) and is_choseong(jamo_list[i + 2])
                            and (potential_jong, jamo_list[i + 2]) in COMPLEX_JONGSEONG):
                        if i + 3 < len(jamo_list) and is_jungseong(jamo_list[i + 3]):
                            jong = JONGSEONG.index(potential_jong)
                            i += 1
                        else:
                            complex_jong = COMPLEX_JONGSEONG[(potential_jong, jamo_list[i + 2])]
                            jong = JONGSEONG.index(complex_jong)
                            i += 2
                    else:
                        jong = JONGSEONG.index(potential_jong)
                        i += 1
            code = 0xAC00 + cho * 21 * 28 + jung * 28 + jong
            result.append(chr(code))
        else:
            result.append(j)
        i += 1
    return ''.join(result)

def convert_qwerty_to_hangul(text):
    if all(c in QWERTY_TO_HANGUL for c in text):
        jamo = qwerty_to_jamo(text)
        return assemble_hangul(jamo)
    return None

def clean_text(text):
    if not text:
        return ''
    # Remove footnote tags <f>...</f>
    text = re.sub(r'<f>[^<]*</f>', '', text)
    # Remove section title tags <n>...</n> and their bracket content
    text = re.sub(r'<n>\[?[^\]<]*\]?</n>', '', text)
    # Remove any remaining HTML tags
    text = re.sub(r'<[^>]+/?>', '', text)
    # Remove leftover bracketed section titles like [말씀이 육신이 되시다]
    text = re.sub(r'\[[가-힣a-zA-Z0-9\s,.:]+\]\s*', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def despace(s):
    """Strip ALL whitespace so search ignores spacing differences."""
    return re.sub(r'\s+', '', s or '')


def trigrams(s):
    """Set of 3-character shingles of s (used for fuzzy-match scoring)."""
    if not s:
        return set()
    if len(s) < 3:
        return {s}
    return {s[i:i + 3] for i in range(len(s) - 2)}
