"""BibleClip web UI entry point — launches the pywebview window.

Runs the High-redesign front-end (web/) in a native window, exposing the
Library core to JavaScript via the Api bridge. The CustomTkinter app
(bibleclip.ui.app) is unaffected; this is a separate, parallel entry point.
"""
import os

from bibleclip.config import __version__, get_resource_dir
from bibleclip.core.library import Library
from bibleclip.webui.api import Api


def _index_path():
    return os.path.join(get_resource_dir(), 'web', 'index.html')


def main():
    import webview  # imported lazily so api.py stays headless-testable

    library = Library()
    api = Api(library)
    window = webview.create_window(
        f"BibleClip v{__version__}",
        url=_index_path(),
        js_api=api,
        width=1100, height=780,
        min_size=(900, 650),
    )
    api.set_window(window)  # lets the clipboard monitor push events back to JS

    _popup_count = [0]

    def _open_popup(title, html):
        # Independent dict window (right-click). Unique name per call so
        # pywebview doesn't reuse/replace an existing window.
        _popup_count[0] += 1
        webview.create_window(title, html=html, width=460, height=560,
                              min_size=(360, 360))

    api.set_popup_factory(_open_popup)
    webview.start()


if __name__ == "__main__":
    main()
