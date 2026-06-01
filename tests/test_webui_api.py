"""Headless test for the web bridge (bibleclip.webui.api.Api).

Run with:  python -X utf8 tests/test_webui_api.py

Does NOT import `webview` (the Api is deliberately backend-free) and never
calls save_settings. Exits via os._exit(0).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bibleclip.webui.api as apimod
from bibleclip.core.library import Library
from bibleclip.webui.api import Api, markup_to_html


class FakeClipboard:
    """In-memory stand-in for pyperclip (no real system clipboard touched)."""
    def __init__(self):
        self.text = ''

    def paste(self):
        return self.text

    def copy(self, text):
        self.text = text


class FakeWindow:
    """Captures the JS pushed via window.evaluate_js (the Python→JS channel)."""
    def __init__(self):
        self.calls = []

    def evaluate_js(self, js):
        self.calls.append(js)


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def monitor_check():
    """Drive the clipboard monitor end-to-end against fakes: a reference is
    converted in place and pushed to JS as onReference; a '#keyword' as
    onKeyword. Never touches the real clipboard or imports webview."""
    fake = FakeClipboard()
    apimod.pyperclip = fake          # swap the module's clipboard backend
    win = FakeWindow()
    api = Api(Library())
    api.set_window(win)

    res = api.start_monitoring()
    assert res.get('ok'), res

    # A reference: should be converted in place and pushed as onReference.
    fake.text = '창 1:1'
    assert wait_for(lambda: any('onReference' in c for c in win.calls)), \
        "onReference was never pushed"
    assert '태초' in fake.text, f"clipboard not converted in place: {fake.text!r}"
    print(f"monitor: '창 1:1' -> onReference; clipboard now: {fake.text[:24]}…")

    # A '#keyword' query: should be pushed as onKeyword.
    n_ref = sum('onReference' in c for c in win.calls)
    fake.text = '#사랑'
    assert wait_for(lambda: any('onKeyword' in c for c in win.calls)), \
        "onKeyword was never pushed"
    assert sum('onReference' in c for c in win.calls) == n_ref, \
        "keyword wrongly produced a reference"
    print("monitor: '#사랑' -> onKeyword")

    api.stop_monitoring()
    assert api.monitoring is False


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

    assert isinstance(init['viewer'], list) and init['viewer'], init['viewer']
    assert init['primary'] in init['viewer'], (init['primary'], init['viewer'])

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

    # set_viewer_versions: validation + ordering, WITHOUT touching the real
    # settings file (save_settings stubbed — see headless-test-no-save rule).
    saved = []
    api.lib.save_settings = lambda: saved.append(True)
    all_names = [v['name'] for v in init['versions']]
    if len(all_names) >= 2:
        picked = api.set_viewer_versions([all_names[1], all_names[0], 'BOGUS'])
        assert 'BOGUS' not in picked, picked
        assert set(picked) == {all_names[0], all_names[1]}, picked
        # order follows viewer_version_order, not the argument order
        order = api.lib.settings.get('viewer_version_order') or all_names
        assert picked == [n for n in order if n in (all_names[0], all_names[1])], picked
        assert saved, "save_settings not called"
        # refuse to drop to an empty set
        kept = api.set_viewer_versions([])
        assert kept == picked, kept
        print(f"set_viewer_versions -> {picked} (empty rejected)")

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

    monitor_check()

    print("\nALL WEBUI API CHECKS PASSED ✅")


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    os._exit(0)
