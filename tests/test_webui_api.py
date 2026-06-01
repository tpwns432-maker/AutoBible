"""Headless test for the web bridge (bibleclip.webui.api.Api).

Run with:  python -X utf8 tests/test_webui_api.py

Does NOT import `webview` (the Api is deliberately backend-free) and never
calls save_settings. Exits via os._exit(0).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibleclip.core.library import Library
from bibleclip.webui.api import Api, markup_to_html


def main():
    api = Api(Library())

    init = api.get_initial()
    assert init['versions'], "no versions"
    assert init['primary'], "no primary version"
    assert init['books'], "no books"
    last = init['last']
    assert last['book'] and last['chapter'], last
    print(f"get_initial: primary={init['primary']} versions={len(init['versions'])} "
          f"books={len(init['books'])} last={last['book']}:{last['chapter']}")

    ver = init['primary']
    books = api.get_books(ver)
    assert any(b['num'] == 10 for b in books), "Genesis (10) missing"

    chs = api.get_chapters(ver, 10)
    assert chs and chs[0] == 1
    print(f"get_chapters({ver},10) -> {len(chs)} chapters")

    ch = api.get_chapter(ver, 10, 1)
    assert ch['ref']['chapter'] == 1 and ch['verses'], ch['ref']
    assert ch['verses'][0]['n'] == 1 and '태초' in ch['verses'][0]['text'], ch['verses'][0]
    print(f"get_chapter({ver},10,1) -> {len(ch['verses'])} verses; "
          f"v1: {ch['verses'][0]['text'][:24]}…")

    inter = api.get_interlinear(10, 1)
    assert inter and inter[0]['words'], "interlinear empty"
    first = inter[0]['words'][0]
    assert first['w'] and first['code'], first
    print(f"get_interlinear(10,1) -> {len(inter)} verses; "
          f"v1 first word: {first['w']}/{first['code']}")

    # markup converter unit checks
    assert markup_to_html('<num>H1</num> a^b') == '<span class="lex-num" data-code="H1">H1</span> a  b'
    assert markup_to_html('') == ''

    strong = api.lookup_strong('H3068')
    if strong is not None:
        assert strong['code'] == 'H3068' and '여호와' in strong['html']
        assert '<num>' not in strong['html'], "raw <num> leaked into html"
        print(f"lookup_strong('H3068') -> {len(strong['html'])} chars html")
    else:
        print("(no lexicon data — skipped lookup_strong)")

    print("\nALL WEBUI API CHECKS PASSED ✅")


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    os._exit(0)
