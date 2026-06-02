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
from bibleclip.config import __version__
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

    # The monitor picks up its poll interval from settings and is live-tunable.
    assert api.lib._monitor is not None
    assert api.lib._monitor.poll_interval == api.lib.settings['poll_interval']
    api.lib.set_poll_interval(0.25)
    assert api.lib._monitor.poll_interval == 0.25

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
    assert isinstance(init['dark_mode'], bool) and isinstance(init['font_size'], int)
    assert init['lex_lang'] in ('ko', 'en'), init['lex_lang']
    assert isinstance(init['search_click_navigates'], bool)
    assert init['version'] == __version__, init['version']
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

    # ---- Output settings tab (get_settings / set_setting / order / preview) ----
    # save_settings is still the stub from above (no disk writes).
    gs = api.get_settings()
    assert set(gs['format']) == set(Api._FORMAT_KEYS), gs['format'].keys()
    assert isinstance(gs['output_order'], list)
    assert gs['versions'], "no versions in get_settings"

    # enum: valid accepted, invalid rejected
    assert api.set_setting('chapter_verse_format', 'korean')['ok']
    assert api.lib.settings['chapter_verse_format'] == 'korean'
    assert not api.set_setting('chapter_verse_format', 'bogus')['ok']
    assert not api.set_setting('no_such_key', 'x')['ok']
    # bool coercion
    assert api.set_setting('hide_reference', 1)['ok']
    assert api.lib.settings['hide_reference'] is True

    # output order: filter bogus, dedup, preserve given order
    picked = api.set_output_order([all_names[0], 'BOGUS', all_names[0]])
    assert picked == [all_names[0]], picked
    print(f"get_settings/set_setting/order OK -> order={picked}")

    # preview reflects the current order (요 1:1-3 → John 1:1-3 text)
    api.set_output_order([all_names[0]])
    prev = api.get_preview()
    assert prev and '(' != prev[0], f"preview empty/placeholder: {prev!r}"
    print(f"get_preview -> {prev[:32]}…")
    # empty order → placeholder, not a crash
    api.set_output_order([])
    assert api.get_preview() == '(출력할 성경 버전을 추가하세요)', api.get_preview()

    # markup converter unit checks
    assert markup_to_html('<num>H1</num> a^b') == '<span class="lex-num" data-code="H1">H1</span> a  b'
    assert markup_to_html('') == ''

    strong = api.lookup_strong('H3068')
    if strong is not None:
        assert strong['code'] == 'H3068' and '여호와' in strong['html']
        assert '<num>' not in strong['html'], "raw <num> leaked into html"
        # refined entry: headword (before '^') + reading (first <font>) extracted
        assert strong['headword'] and strong['headword'][0] >= '֐', strong['headword']
        assert 'Yhwh' in strong['reading'], strong['reading']
        # reading was lifted out of the body (not duplicated there)
        assert 'Yhwh' not in strong['html'], strong['html'][:40]
        assert isinstance(strong['morph'], list)
        print(f"lookup_strong('H3068') -> head={strong['headword']} reading={strong['reading'][:16]}…")
    else:
        print("(no lexicon data — skipped lookup_strong)")

    # hover summary (falls back to lexicon gloss when 원전분해 morphology absent)
    hov = api.hover_summary('H3068', 10, 1, 1)
    assert hov['code'] == 'H3068'
    print(f"hover_summary -> {len(hov['lines'])} line(s)")

    # keyword search + copy_reference (clipboard write stubbed out)
    import bibleclip.webui.api as apimod_local
    apimod_local.pyperclip = None  # don't touch the real clipboard
    # search an explicit Korean version (a prior test left primary on English)
    sr = api.search('태초', version=ver)
    assert sr['hits'] and sr['hits'][0]['short'] == '창', sr['hits'][:1]
    api.set_output_order([sr['version']])  # earlier test emptied output_order
    cp = api.copy_reference(sr['hits'][0]['book'], sr['hits'][0]['chapter'],
                            [sr['hits'][0]['verse']])
    assert cp['ok'] and '태초' in cp['text'], cp
    # explicit versions override output_order (viewer manual copy)
    cp2 = api.copy_reference(10, 1, [1], versions=[ver])
    assert cp2['ok'] and '태초' in cp2['text'], cp2
    print(f"search('태초') -> {len(sr['hits'])} hits; copy_reference ok")

    # refresh_databases returns the (unchanged here) version list
    rd = api.refresh_databases()
    assert isinstance(rd['added'], list) and rd['versions'], rd
    assert len(rd['versions']) == len(init['versions'])
    print(f"refresh_databases -> +{len(rd['added'])}, total {len(rd['versions'])}")

    # set_viewer_order trusts the given order (drag reorder)
    if len(all_names) >= 2:
        ordr = api.set_viewer_order([all_names[1], all_names[0]])
        assert ordr[:2] == [all_names[1], all_names[0]], ordr

    # open_dict_window is a no-op without a popup factory (headless)
    assert api.open_dict_window('H3068') == {'ok': False}

    # UI prefs (save_settings still stubbed): clamp + persist into settings
    assert api.set_font_size(40) == 30 and api.lib.settings['viewer_font_size'] == 30
    assert api.set_font_size(2) == 8
    api.set_dark_mode(True)
    assert api.lib.settings['dark_mode'] is True
    api.note_position(500, 3)
    assert api.lib.settings['last_book_num'] == 500 and api.lib.settings['last_chapter'] == 3
    print("ui prefs (font/dark/position) OK")

    # update check: stub the network so the test stays offline/deterministic
    apimod_local.fetch_latest_release = lambda timeout=8: (
        {'version': 'v99.0.0', 'download_url': 'http://x/a.zip',
         'asset_name': 'a.zip', 'body': 'notes'}, '')
    up = api.check_update()
    assert up['ok'] and up['has_update'] and up['latest'] == 'v99.0.0', up
    api.skip_update('v99.0.0')
    assert api.lib.settings['skip_update_version'] == 'v99.0.0'
    assert api.check_update()['skipped'] is True
    apimod_local.fetch_latest_release = lambda timeout=8: (None, '네트워크 오류')
    assert api.check_update()['ok'] is False
    # install only runs in a frozen build → graceful refusal under source mode
    assert api.install_update()['ok'] is False
    print("check_update (stubbed) + install source-mode guard OK")

    # ---- App settings (⚙ window): get / set / reset (save_settings stubbed) ----
    aset = api.get_app_settings()
    assert aset['version'] == __version__, aset['version']
    assert aset['lex_lang'] in ('ko', 'en'), aset
    assert isinstance(aset['poll_interval'], float), aset
    assert aset['repo_url'].startswith('https://'), aset['repo_url']
    # poll_interval: coerced to float and clamped to [0.1, 2.0]
    assert api.set_app_setting('poll_interval', 5)['value'] == 2.0
    assert api.set_app_setting('poll_interval', 0)['value'] == 0.1
    assert api.set_app_setting('poll_interval', 0.25)['value'] == 0.25
    assert api.lib.settings['poll_interval'] == 0.25
    # lex_lang enum: valid accepted, invalid rejected
    assert api.set_app_setting('lex_lang', 'en')['ok']
    assert api.lib.settings['lex_lang'] == 'en'
    assert not api.set_app_setting('lex_lang', 'fr')['ok']
    # boolean keys coerced
    assert api.set_app_setting('search_click_navigates', 1)['ok']
    assert api.lib.settings['search_click_navigates'] is True
    assert api.set_app_setting('auto_update_check', 0)['ok']
    assert api.lib.settings['auto_update_check'] is False
    # unknown key rejected
    assert not api.set_app_setting('no_such_app_key', 1)['ok']
    print("app settings get/set (poll clamp, lex enum, bool) OK")

    # reset restores every default
    api.reset_settings()
    assert api.lib.settings['poll_interval'] == Library.DEFAULT_SETTINGS['poll_interval']
    assert api.lib.settings['lex_lang'] == 'ko'
    assert api.lib.settings['search_click_navigates'] is False
    print("reset_settings -> defaults restored")

    monitor_check()

    print("\nALL WEBUI API CHECKS PASSED ✅")


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    os._exit(0)
