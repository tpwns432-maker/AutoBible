"""JS-facing bridge API for the pywebview front-end.

Each public method is callable from JavaScript as ``pywebview.api.<method>(...)``
and must return JSON-serializable values. This module deliberately does NOT
import `webview`, so it can be unit-tested headlessly against a plain Library.
Events that originate in Python (caught clipboard references) are pushed to the
front-end via the injected window's ``evaluate_js`` — still no `webview` import.
"""
import os
import sys
import json
import re
import threading
import tempfile
import subprocess
import webbrowser

from bibleclip.config import (
    __version__, RELEASES_PAGE_URL, IS_WINDOWS, get_base_dir,
    GITHUB_OWNER, GITHUB_REPO,
)

REPO_HOME_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
from bibleclip.update import fetch_latest_release, parse_version
from bibleclip.core.installer import (
    download_file, stage_payload, write_windows_bat, write_mac_sh,
)

try:
    import pyperclip
except Exception:  # pragma: no cover - clipboard backend optional at import
    pyperclip = None


# Dictionary entries are stored as a small pseudo-HTML markup (the same dialect
# rendered into tk tags by data.original_lang.render_dict_html). For the web we
# only need to translate the two non-standard pieces — '^' separators and the
# custom <num> tag; <b>/<br>/<sup>/<font color> render natively in a browser.
_NUM_RE = re.compile(r'<\s*num\s*>(.*?)<\s*/\s*num\s*>', re.S | re.I)
# A lexicon entry starts: HEADWORD^<font ...>reading</font><br>... The first
# font holds the romanization/Korean reading; the rest is the gloss + body.
_FIRST_FONT_RE = re.compile(r'^\s*<font[^>]*>(.*?)</font>', re.S | re.I)
_TAGS_RE = re.compile(r'<[^>]+>')
_LEAD_BR_RE = re.compile(r'^(?:\s*<br\s*/?>\s*)+', re.I)


def markup_to_html(markup):
    if not markup:
        return ''
    html = markup.replace('^', '  ')
    html = _NUM_RE.sub(r'<span class="lex-num" data-code="\1">\1</span>', html)
    return html


def parse_entry(markup):
    """Split a raw lexicon entry into headword / reading / body-HTML.

    Layout: ``HEADWORD^<font>reading</font><br><font>gloss</font>…body``.
    Falls back gracefully (empty headword/reading) for entries that don't
    follow it."""
    if not markup:
        return {'headword': '', 'reading': '', 'html': ''}
    headword, rest = '', markup
    if '^' in markup:
        headword, rest = markup.split('^', 1)
        headword = headword.strip()
    reading = ''
    m = _FIRST_FONT_RE.match(rest)
    if m:
        reading = _TAGS_RE.sub('', m.group(1)).strip()
        rest = _LEAD_BR_RE.sub('', rest[m.end():])
    return {'headword': headword, 'reading': reading, 'html': markup_to_html(rest)}


def _morph_html(morph):
    """Render a morphology list (Library.morphology) to the 형태소 분석 block."""
    if not morph:
        return ''
    rows = []
    for w in morph:
        seg = f"<b>{w['lemma']}</b>"
        if w.get('translit'):
            seg += f" {w['translit']}"
        if w.get('pos'):
            seg += f" · {w['pos']}"
        if w.get('gloss') and w['gloss'] != '_':
            seg += f" · {w['gloss']}"
        rows.append(seg)
    return ('<div class="morph"><div class="morph-h">형태소 분석</div>'
            + '<br>'.join(rows) + '</div>')


# Self-contained styles for the right-click dict window. It's created with
# inline HTML (no base URL), so it can't link the bundled CSS/fonts — the font
# stacks fall back to system Korean/Hebrew fonts, which is fine for a popup.
_DICT_THEMES = {
    'light': dict(bg='#FAF9FC', card='#FFFFFF', border='#EFEBF6', text='#241D33',
                  muted='#6A6086', dim='#A99FC0', accent='#6D4DFF',
                  chipbg='#F3EFFE', heb='#1A1330'),
    'dark': dict(bg='#0F0B1A', card='#171127', border='#2A2140', text='#ECE9F5',
                 muted='#A99FC6', dim='#7D7399', accent='#9A86FF',
                 chipbg='#241A3F', heb='#ECE9F5'),
}


def _dict_page_html(code, entry, theme='light'):
    t = _DICT_THEMES.get(theme, _DICT_THEMES['light'])
    if not entry:
        head = body = ''
        reading = ''
        morph = ''
    else:
        head = entry.get('headword', '')
        reading = entry.get('reading', '')
        body = entry.get('html', '') or '사전 항목 없음'
        morph = _morph_html(entry.get('morph'))
    head_block = ''
    if head:
        head_block = (f'<div class="head"><span class="heb">{head}</span>'
                      f'<span class="rom">{reading}</span></div>')
    font_ui = ('"Pretendard","Apple SD Gothic Neo","Malgun Gothic",'
               '"Segoe UI","Noto Sans KR",system-ui,sans-serif')
    font_heb = '"SBL Hebrew","Times New Roman","Noto Serif Hebrew",serif'
    return f"""<!DOCTYPE html><html lang="ko" data-theme="{theme}"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>사전 · {code}</title><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:{font_ui};background:{t['bg']};color:{t['text']};
 padding:20px;line-height:1.8;-webkit-font-smoothing:antialiased}}
.chip{{display:inline-block;font-size:11px;font-weight:700;color:{t['accent']};
 background:{t['chipbg']};border-radius:8px;padding:3px 10px;margin-bottom:12px}}
.head{{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}}
.head .heb{{font-family:{font_heb};font-size:48px;line-height:1.15;color:{t['heb']}}}
.head .rom{{color:{t['accent']};font-weight:700;font-size:15px}}
.morph{{border:1px solid {t['border']};border-radius:10px;padding:10px 12px;
 margin-bottom:14px;font-size:13px;color:{t['muted']}}}
.morph-h{{color:{t['accent']};font-weight:700;font-size:11px;margin-bottom:4px}}
.body{{font-size:13px;color:{t['muted']}}}
.body b{{color:{t['text']}}}
.lex-num{{color:{t['accent']};text-decoration:underline}}
</style></head><body>
<span class="chip">{code}</span>{head_block}{morph}<div class="body">{body}</div>
</body></html>"""


class Api:
    """Thin, JSON-friendly facade over Library for the web front-end."""

    def __init__(self, library):
        self.lib = library
        self._window = None        # pywebview window, injected by webui.app.main()
        self._popup_factory = None  # callable(title, html) -> new native window
        self._update = None        # last fetch_latest_release info (for install)
        self.monitoring = False

    def set_window(self, window):
        """Receive the pywebview window so Python-side events can reach JS.

        Kept separate from __init__ so headless tests construct an Api with no
        window (pushes become no-ops)."""
        self._window = window

    def set_popup_factory(self, factory):
        """Receive a callable that opens a new native window from (title, html).
        Supplied by webui.app (which owns `webview`); None in headless tests."""
        self._popup_factory = factory

    def _push(self, fn, *args):
        """Invoke ``window.bibleclip.<fn>(...args)`` in the web view.

        Safe to call from the monitor worker thread (pywebview marshals
        evaluate_js to the UI thread) and a no-op when no window is attached."""
        if self._window is None:
            return
        payload = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
        js = f"window.bibleclip && window.bibleclip.{fn}({payload})"
        try:
            self._window.evaluate_js(js)
        except Exception:
            pass

    # ---- Clipboard monitoring ----

    def start_monitoring(self):
        """Begin watching the system clipboard. Caught references are converted
        in place (the formatted multi-version text replaces the clipboard) and
        pushed to JS via window.bibleclip.onReference; '#keyword' queries go to
        onKeyword."""
        if pyperclip is None:
            return {'ok': False, 'error': 'pyperclip unavailable'}
        self.lib.start_monitoring(
            self._clip_read, self._clip_write,
            self._on_reference, self._on_keyword)
        self.monitoring = True
        return {'ok': True}

    def stop_monitoring(self):
        self.lib.stop_monitoring()
        self.monitoring = False
        return {'ok': True}

    def _clip_read(self):
        try:
            return pyperclip.paste() or ''
        except Exception:
            return ''

    def _clip_write(self, text):
        try:
            pyperclip.copy(text)
        except Exception:
            pass

    def _on_reference(self, result):
        # result is already JSON-serializable (see Library.build_output).
        self._push('onReference', result)

    def _on_keyword(self, keyword):
        self._push('onKeyword', keyword)

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
            'viewer': list(self.lib.settings.get('viewer_versions', [])),
            'books': books,
            'last': {'version': primary, 'book': last_book, 'chapter': last_chapter},
            'dark_mode': bool(s.get('dark_mode')),
            'font_size': int(s.get('viewer_font_size', 11)),
            'auto_update_check': bool(s.get('auto_update_check', True)),
            'lex_lang': 'en' if s.get('lex_lang') == 'en' else 'ko',
            'search_click_navigates': bool(s.get('search_click_navigates', False)),
            'version': __version__,
        }

    # ---- UI preferences (persisted; shared with the desktop app) ----

    def set_dark_mode(self, on):
        self.lib.settings['dark_mode'] = bool(on)
        self.lib.save_settings()
        return {'ok': True}

    def set_font_size(self, size):
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 11
        size = max(8, min(30, size))
        self.lib.settings['viewer_font_size'] = size
        self.lib.save_settings()
        return size

    def refresh_databases(self):
        """Rescan the bible_versions folder for newly added DB files (no restart
        needed). Returns {added:[names], versions:[...]} for the UI to refresh."""
        added = self.lib.refresh_databases()
        return {'added': added, 'versions': self.lib.versions()}

    # ---- App-wide settings (the gear ⚙ window — distinct from 출력 설정) ----

    # Whitelisted app settings. Enums carry allowed values; None = boolean;
    # 'poll_interval' is a float clamped on write.
    _APP_KEYS = {
        'auto_update_check': None,
        'search_click_navigates': None,
        'lex_lang': {'ko', 'en'},
        'poll_interval': 'float',
    }

    def get_app_settings(self):
        """Everything the ⚙ settings window shows."""
        s = self.lib.settings
        return {
            'auto_update_check': bool(s.get('auto_update_check', True)),
            'search_click_navigates': bool(s.get('search_click_navigates', False)),
            'lex_lang': 'en' if s.get('lex_lang') == 'en' else 'ko',
            'poll_interval': float(s.get('poll_interval', 0.5) or 0.5),
            'version': __version__,
            'repo_url': REPO_HOME_URL,
        }

    def set_app_setting(self, key, value):
        """Update one whitelisted app setting and persist. A poll-interval change
        is also applied to a running monitor live. Returns {ok, value}."""
        if key not in self._APP_KEYS:
            return {'ok': False, 'error': f'unknown key: {key}'}
        spec = self._APP_KEYS[key]
        if spec == 'float':
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = 0.5
            value = round(max(0.1, min(2.0, value)), 2)
        elif spec is None:
            value = bool(value)
        elif value not in spec:
            return {'ok': False, 'error': f'invalid value for {key}: {value!r}'}
        self.lib.settings[key] = value
        self.lib.save_settings()
        if key == 'poll_interval':
            self.lib.set_poll_interval(value)
        return {'ok': True, 'value': value}

    def reset_settings(self):
        """Restore every setting to its default (the "설정 초기화" button). The
        front-end reloads afterwards to re-read the fresh state."""
        self.lib.settings = dict(self.lib.DEFAULT_SETTINGS)
        self.lib.save_settings()
        return {'ok': True}

    def open_data_folder(self):
        """Open the folder that holds bible_versions/original_lang in the OS file
        manager (so the user can drop in new .db files)."""
        path = get_base_dir()
        try:
            if IS_WINDOWS:
                os.startfile(path)  # noqa: S606 - user-initiated
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
            return {'ok': True}
        except Exception:
            return {'ok': False}

    def open_github(self):
        try:
            webbrowser.open(REPO_HOME_URL)
            return {'ok': True}
        except Exception:
            return {'ok': False}

    # ---- Update check (GitHub releases) ----

    def check_update(self):
        """Check GitHub for a newer release. Returns {ok, has_update, current,
        latest, notes, url, skipped} or {ok:False, error}. (Download/install of
        a frozen build is deferred to packaging — see HANDOFF.)"""
        info, error = fetch_latest_release()
        if error or not info:
            return {'ok': False, 'error': error or '응답 없음'}
        self._update = info  # remembered for install_update()
        has = parse_version(info['version']) > parse_version(__version__)
        return {
            'ok': True, 'has_update': has,
            'current': __version__, 'latest': info['version'],
            'notes': info.get('body') or '', 'url': info.get('download_url') or '',
            'skipped': self.lib.settings.get('skip_update_version') == info['version'],
        }

    def open_releases_page(self):
        try:
            webbrowser.open(RELEASES_PAGE_URL)
            return {'ok': True}
        except Exception:
            return {'ok': False}

    def skip_update(self, version):
        self.lib.settings['skip_update_version'] = version
        self.lib.save_settings()
        return {'ok': True}

    def install_update(self):
        """Download the latest release and apply it in place (the desktop app's
        self-update). Runs in a worker thread; progress/result are pushed to JS
        as window.bibleclip.onUpdateProgress / onUpdateReady / onUpdateError.
        Only works in a frozen build on Windows/macOS."""
        if not getattr(sys, 'frozen', False):
            return {'ok': False, 'error': '소스 실행 모드에서는 자동 설치가 안 됩니다. 릴리스 페이지를 이용하세요.'}
        info = self._update
        if not info or not info.get('download_url'):
            return {'ok': False, 'error': '업데이트 정보가 없습니다. 먼저 업데이트 확인을 해주세요.'}
        if not (IS_WINDOWS or sys.platform == 'darwin'):
            return {'ok': False, 'error': '이 OS에서는 자동 설치가 지원되지 않습니다.'}
        threading.Thread(target=self._run_install, args=(info,), daemon=True).start()
        return {'ok': True, 'started': True}

    def _run_install(self, info):
        try:
            tmp = tempfile.mkdtemp(prefix='bibleclip_update_')
            zip_path = os.path.join(tmp, info.get('asset_name') or 'update.zip')

            def prog(done, total):
                pct = round(done * 100.0 / total, 1) if total else 0
                self._push('onUpdateProgress', pct, done // 1024,
                           (total // 1024) if total else 0)

            download_file(info['download_url'], zip_path, prog)
            self._push('onUpdateProgress', 100, 0, 0)

            is_mac = sys.platform == 'darwin'
            payload = 'BibleClipWeb.app' if is_mac else 'BibleClipWeb.exe'
            src = stage_payload(zip_path, os.path.join(tmp, 'extract'), payload)

            if is_mac:
                sh = os.path.join(tmp, 'updater.sh')
                write_mac_sh(sh, src, self._running_app_path(), os.getpid())
                subprocess.Popen(['/bin/bash', sh], start_new_session=True, close_fds=True)
            else:
                bat = os.path.join(tmp, 'updater.bat')
                write_windows_bat(bat, src, get_base_dir(), 'BibleClipWeb.exe')
                flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                         | getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000))
                subprocess.Popen(['cmd', '/c', bat], creationflags=flags, close_fds=True)

            self._push('onUpdateReady')
            self._quit_for_update()
        except Exception as e:
            self._push('onUpdateError', str(e))

    def _running_app_path(self):
        """Full path of the running .app bundle (macOS), for in-place replace."""
        p = os.path.dirname(sys.executable)
        while p and not p.endswith('.app'):
            parent = os.path.dirname(p)
            if parent == p:
                return os.path.join(get_base_dir(), 'BibleClipWeb.app')
            p = parent
        return p

    def _quit_for_update(self):
        try:
            self.lib.stop_monitoring()
            self.lib.save_settings()
        except Exception:
            pass
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:
            pass
        os._exit(0)  # ensure the process exits so the updater can overwrite files

    def note_position(self, book, chapter):
        """Remember the last viewed book/chapter (saved to disk on window close
        or on the next settings write — cheap, no immediate disk I/O)."""
        try:
            self.lib.settings['last_book_num'] = int(book)
            self.lib.settings['last_chapter'] = int(chapter)
        except (TypeError, ValueError):
            pass

    def set_viewer_versions(self, names):
        """Replace the set of versions shown in parallel in the viewer.

        The given names are filtered to loaded versions and re-sorted by the
        persistent ``viewer_version_order`` so the on-screen order stays stable
        regardless of toggle order. At least one version is always kept.
        Returns the cleaned, ordered list."""
        order = (self.lib.settings.get('viewer_version_order')
                 or list(self.lib.dbs.keys()))
        valid = {n for n in names if n in self.lib.dbs}
        ordered = [n for n in order if n in valid]
        for n in names:           # preserve any valid name missing from order
            if n in self.lib.dbs and n not in ordered:
                ordered.append(n)
        if not ordered:
            return list(self.lib.settings.get('viewer_versions', []))
        self.lib.settings['viewer_versions'] = ordered
        self.lib.save_settings()
        return ordered

    def set_viewer_order(self, names):
        """Set the explicit display order of the viewer's versions (chip drag).

        Unlike set_viewer_versions this trusts the given order verbatim (it's a
        reorder of the already-checked set) and pushes it to the front of the
        persistent viewer_version_order. Returns the cleaned list."""
        valid = [n for n in names if n in self.lib.dbs]
        if not valid:
            return list(self.lib.settings.get('viewer_versions', []))
        self.lib.settings['viewer_versions'] = valid
        rest = [n for n in (self.lib.settings.get('viewer_version_order') or [])
                if n in self.lib.dbs and n not in valid]
        self.lib.settings['viewer_version_order'] = valid + rest
        self.lib.save_settings()
        return valid

    # ---- Output settings (the "출력 설정" tab) ----

    # Format keys the settings tab may write. Enums carry their allowed values;
    # bool keys map to None (coerced to a real bool on write).
    _FORMAT_KEYS = {
        'book_name': {'long_ko', 'short_ko', 'long_en', 'short_en'},
        'chapter_verse_format': {'colon', 'korean'},
        'bracket_style': {'none', '[]', '()'},
        'ref_position': {'before', 'after'},
        'range_symbol': {'-', '~'},
        'ref_body_separator': {' - ', ': ', ' '},
        'output_mode': {'inline', 'newline'},
        'newline_show_cv': None,
        'show_version_header': None,
        'hide_reference': None,
    }

    def get_settings(self):
        """The format settings + output order the settings tab needs."""
        s = self.lib.settings
        return {
            'format': {k: s.get(k) for k in self._FORMAT_KEYS},
            'output_order': list(s.get('output_order', [])),
            'versions': self.lib.versions(),  # name + display for label lookups
        }

    def set_setting(self, key, value):
        """Update one whitelisted format setting and persist. Returns {ok}."""
        if key not in self._FORMAT_KEYS:
            return {'ok': False, 'error': f'unknown key: {key}'}
        allowed = self._FORMAT_KEYS[key]
        if allowed is None:               # boolean setting
            value = bool(value)
        elif value not in allowed:
            return {'ok': False, 'error': f'invalid value for {key}: {value!r}'}
        self.lib.settings[key] = value
        self.lib.save_settings()
        return {'ok': True}

    def set_output_order(self, names):
        """Replace the clipboard output order (versions used when a reference is
        caught/copied). Filtered to loaded versions, dedup, order preserved as
        given. Returns the cleaned list."""
        seen = set()
        cleaned = []
        for n in names:
            if n in self.lib.dbs and n not in seen:
                seen.add(n)
                cleaned.append(n)
        self.lib.settings['output_order'] = cleaned
        self.lib.save_settings()
        return cleaned

    def get_preview(self):
        """Formatted output for the fixed sample (요 1:1-3) under current
        settings — exactly what would land on the clipboard."""
        r = self.lib.build_output('요 1:1-3')
        if r and r.get('kind') == 'reference':
            return r['text']
        if not self.lib.settings.get('output_order'):
            return '(출력할 성경 버전을 추가하세요)'
        return '(데이터를 찾을 수 없습니다)'

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

    # ---- Keyword search ----

    def _search_version(self):
        ver = self.lib.primary_version()
        if ver and ver in self.lib.dbs:
            return ver
        for v in ('KRV', 'NRKV', 'KNRSV'):
            if v in self.lib.dbs:
                return v
        return next(iter(self.lib.dbs), None)

    def search(self, keyword, version=None, limit=200):
        """Keyword search in one version (defaults to the primary/Korean one).

        Returns {keyword, version, display, hits:[{book,chapter,verse,short,text}]}."""
        keyword = (keyword or '').strip().lstrip('#').strip()
        if not keyword:
            return {'keyword': '', 'version': None, 'display': '', 'hits': []}
        ver = version if (version and version in self.lib.dbs) else self._search_version()
        db = self.lib.dbs.get(ver)
        if not db:
            return {'keyword': keyword, 'version': None, 'display': '', 'hits': []}
        rows = db.search(keyword, limit=limit)
        hits = [{'book': b, 'chapter': c, 'verse': v,
                 'short': db.books[b][0] if b in db.books else '?', 'text': t}
                for (b, c, v, t) in rows]
        return {'keyword': keyword, 'version': ver,
                'display': db.display_name, 'hits': hits}

    def copy_reference(self, book, chapter, verses, versions=None):
        """Format book/chapter/verses via the output pipeline, place it on the
        clipboard, and tell the monitor (so it isn't re-detected). ``verses`` is
        a list (empty = whole chapter). ``versions`` overrides output_order
        (the viewer passes its displayed versions for manual copy). Returns
        {ok, text} or {ok:False}."""
        vs = [int(v) for v in (verses or [])]
        order = [v for v in versions if v in self.lib.dbs] if versions else None
        text, _ = self.lib.format_reference(int(book), int(chapter), vs, order)
        if not text:
            return {'ok': False}
        if pyperclip is not None:
            try:
                pyperclip.copy(text)
            except Exception:
                pass
        self.lib.notify_clipboard_written(text)
        return {'ok': True, 'text': text}

    # ---- Lexicon ----

    def lookup_strong(self, code, lang='ko', book=None, chapter=None, verse=None):
        """Full lexicon entry for a Strong's code: {code, headword, reading,
        html, morph}. ``morph`` (형태소 분석) is filled when verse context is
        given. Returns None only when there's neither a dict entry nor morph."""
        markup = self.lib.lookup_strong(code, lang)
        morph = []
        if book and chapter and verse:
            morph = self.lib.morphology(code, int(book), int(chapter), int(verse))
        if not markup:
            if morph:
                return {'code': code, 'headword': '', 'reading': '',
                        'html': '', 'morph': morph}
            return None
        entry = parse_entry(markup)
        entry['code'] = code
        entry['morph'] = morph
        return entry

    def hover_summary(self, code, book=None, chapter=None, verse=None):
        """Short preview for a Strong's word (hover tooltip): the original-
        language headword (shown large by the UI) + reading + a short gloss
        line. Prefers verse morphology, falls back to the lexicon entry.
        {code, headword, reading, lines:[...]}."""
        headword = reading = ''
        lines = []
        if book and chapter and verse:
            morph = self.lib.morphology(code, int(book), int(chapter), int(verse))
            if morph:
                w = morph[0]
                headword = w['lemma']
                reading = w['translit']
                parts = []
                if w['pos']:
                    parts.append(w['pos'])
                if w['gloss'] and w['gloss'] != '_':
                    parts.append(w['gloss'])
                if parts:
                    lines.append(' · '.join(parts))
        if not headword and not lines:
            markup = self.lib.lookup_strong(code, 'ko') or self.lib.lookup_strong(code, 'en')
            if markup:
                e = parse_entry(markup)
                headword, reading = e['headword'], e['reading']
                txt = _TAGS_RE.sub('', e['html']).replace('^', ' ')
                txt = re.sub(r'\s+', ' ', txt).strip()
                if txt:
                    lines.append(txt[:80] + ('…' if len(txt) > 80 else ''))
        return {'code': code, 'headword': headword, 'reading': reading, 'lines': lines}

    def open_dict_window(self, code, lang='ko', book=None, chapter=None,
                         verse=None, theme='light'):
        """Open an independent native window with the full dict entry (the
        right-click behaviour from the desktop app). No-op without a factory."""
        if self._popup_factory is None:
            return {'ok': False}
        entry = self.lookup_strong(code, lang, book, chapter, verse)
        html = _dict_page_html(code, entry, theme)
        try:
            self._popup_factory(f"사전 · {code}", html)
        except Exception:
            return {'ok': False}
        return {'ok': True}
