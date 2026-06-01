"""Headless smoke test for the UI-agnostic core (bibleclip.core.library.Library).

Run with:  python -X utf8 tests/test_core.py

No test framework needed. This NEVER calls save_settings (which would write the
user's real settings file) — it only reads. Exits via os._exit(0) to avoid any
interpreter-shutdown side effects.
"""
import os
import sys

# Make the repo root importable when run as `python tests/test_core.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibleclip.core.library import Library


def main():
    lib = Library()
    assert lib.dbs, "no bible databases loaded — run from the repo root"
    print(f"loaded versions: {sorted(lib.dbs)}")

    # 1) reference parsing: 창 1:1 -> book 10 (창세기), chapter 1, verse [1]
    refs = lib.parse_reference('창 1:1')
    assert refs, "창 1:1 did not parse"
    book_num, short, long_, chapter, verses = refs[0]
    assert book_num == 10 and chapter == 1 and verses == [1], refs[0]
    print(f"parse_reference('창 1:1') -> {refs[0]}")

    # 2) chapter fetch (prefer KRV, else first loaded version)
    version = 'KRV' if 'KRV' in lib.dbs else sorted(lib.dbs)[0]
    chap = lib.get_chapter(version, 10, 1)
    assert chap and chap[0][0] == 1 and chap[0][1].strip(), chap[:1]
    print(f"get_chapter({version!r},10,1) -> {len(chap)} verses; v1: {chap[0][1][:24]}…")

    # 3) build_output: a real reference yields a 'reference' result with text
    out = lib.build_output('요 3:16')
    assert out and out['kind'] == 'reference' and out['text'].strip(), out
    print(f"build_output('요 3:16') -> kind=reference, n_parts={out['n_parts']}")
    print(f"   text: {out['text'][:48]}…")

    # 4) build_output: '#keyword' is a keyword query
    kw = lib.build_output('#사랑')
    assert kw and kw['kind'] == 'keyword' and kw['keyword'] == '사랑', kw
    print(f"build_output('#사랑') -> {kw}")

    # 5) build_output: garbage yields None
    assert lib.build_output('점심 뭐먹지') is None
    print("build_output('점심 뭐먹지') -> None")

    # 6) search returns hits
    hits = lib.search(version, '태초')
    assert hits, "search('태초') returned nothing"
    print(f"search({version!r},'태초') -> {len(hits)} hits; first: {hits[0][:3]}")

    # 7) Strong's lexicon lookup (only if original-language data is present)
    if lib.lexicon_ko:
        entry = lib.lookup_strong('H3068')
        assert entry, "lookup_strong('H3068') returned nothing"
        print(f"lookup_strong('H3068') -> {len(entry)} chars of markup")
        inter = lib.interlinear(10, 1)
        assert inter and inter[0][1], "interlinear(10,1) empty"
        print(f"interlinear(10,1) -> {len(inter)} verses; "
              f"v1 first word/code: {inter[0][1][0]}")
    else:
        print("(original_lang data absent — skipping lexicon/interlinear checks)")

    print("\nALL CORE CHECKS PASSED ✅")


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    os._exit(0)
