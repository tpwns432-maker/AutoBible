"""UI-agnostic clipboard watch loop.

Polls the clipboard via injected read/write callables (so it works under any
UI — tkinter, pywebview, headless tests) and routes matches through a
`build_output` callable to the supplied reference/keyword callbacks.
"""
import threading
import time


class ClipboardMonitor:
    POLL_INTERVAL = 0.5

    def __init__(self, read_fn, write_fn, build_output, on_reference, on_keyword,
                 poll_interval=None):
        """
        Args:
            read_fn():  returns current clipboard text.
            write_fn(text): writes text to the clipboard.
            build_output(text): -> result dict (see Library.build_output) or None.
            on_reference(result): called with a 'reference' result after the
                formatted text has been written to the clipboard.
            on_keyword(keyword): called with the bare keyword for a '#…' query.
            poll_interval: seconds between clipboard reads (defaults to
                POLL_INTERVAL). Mutable at runtime via the attribute so the app
                settings can re-tune a live monitor.
        """
        self.read_fn = read_fn
        self.write_fn = write_fn
        self.build_output = build_output
        self.on_reference = on_reference
        self.on_keyword = on_keyword
        self.poll_interval = poll_interval or self.POLL_INTERVAL
        # `last` guards against re-processing our own output. It is also updated
        # externally (Library.notify_clipboard_written) when other code copies.
        self.last = ''
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        try:
            self.last = self.read_fn()
        except Exception:
            self.last = ''
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                current = self.read_fn()
                if current != self.last and current.strip():
                    self.last = current
                    self._handle(current.strip())
            except Exception:
                pass
            time.sleep(self.poll_interval)

    def _handle(self, text):
        result = self.build_output(text)
        if not result:
            return
        kind = result.get('kind')
        if kind == 'keyword':
            self.on_keyword(result['keyword'])
        elif kind == 'reference':
            self.write_fn(result['text'])
            self.last = result['text']
            self.on_reference(result)
