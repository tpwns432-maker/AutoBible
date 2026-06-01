"""Reusable CTk widgets."""
import tkinter as tk
import customtkinter as ctk

from bibleclip.config import UI_FONT
from bibleclip.theme import CTK


class ScrollDropdown(ctk.CTkButton):
    """A button that opens a scrollable, wheel-friendly popup list.

    Drop-in replacement for the subset of CTkOptionMenu the app uses:
      configure(values=...), cget('values'), set(v), get(), `variable`, `command`.
    Unlike CTkOptionMenu its list scrolls with the mouse wheel, uses the app UI
    font, and clicking the button again closes an open list (toggle).
    """

    def __init__(self, master, values=None, variable=None, command=None,
                 width=150, max_visible=14, **kw):
        self._values = list(values or [])
        self._variable = variable
        self._user_command = command
        self._popup = None
        self._root_click_id = None
        self._reopen_guard = False
        self._max_visible = max_visible
        kw.setdefault('anchor', 'w')
        kw.setdefault('font', (UI_FONT, 11))
        super().__init__(master, width=width, text='', command=self._toggle, **kw)
        if variable is not None:
            variable.trace_add('write', self._on_var)
        self._refresh_text()

    # --- display ---
    def _refresh_text(self):
        try:
            super().configure(text=(f"{self.get()}   ▾" if self.get() else "▾"))
        except Exception:
            pass

    def _on_var(self, *_):
        self._refresh_text()

    # --- CTkOptionMenu-compatible API ---
    def cget(self, key):
        if key == 'values':
            return list(self._values)
        return super().cget(key)

    def configure(self, **kw):
        if 'values' in kw:
            self._values = list(kw.pop('values') or [])
        if 'command' in kw:
            self._user_command = kw.pop('command')
        if kw:
            super().configure(**kw)

    def set(self, value):
        if self._variable is not None:
            self._variable.set(value)
        else:
            self._refresh_text_with(value)

    def _refresh_text_with(self, value):
        super().configure(text=f"{value}   ▾")

    def get(self):
        if self._variable is not None:
            return self._variable.get()
        # strip the trailing arrow we add for display
        return super().cget('text').replace('   ▾', '').strip()

    # --- popup list ---
    def _toggle(self):
        if self._reopen_guard:
            self._reopen_guard = False
            return
        if self._popup is not None and self._popup.winfo_exists():
            self._close()
        else:
            self._open()

    def _close(self):
        if self._root_click_id is not None:
            try:
                self.winfo_toplevel().unbind('<Button-1>', self._root_click_id)
            except Exception:
                pass
            self._root_click_id = None
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None

    def _on_root_click(self, _event=None):
        # Any click on the main window closes the list; guard the button's own
        # command so the same click doesn't immediately reopen it.
        self._reopen_guard = True
        self._close()
        self.after(220, lambda: setattr(self, '_reopen_guard', False))

    def _select(self, value):
        self._close()
        self.set(value)
        if self._user_command:
            try:
                self._user_command(value)
            except Exception:
                pass

    def _open(self):
        if not self._values:
            return
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        w = max(self.winfo_width(), 120)
        item_h = 30
        rows = min(len(self._values), self._max_visible)
        h = rows * item_h + 10
        # flip above the button if it would fall off the bottom of the screen
        if y + h > self.winfo_screenheight() - 10:
            y = self.winfo_rooty() - h - 2

        self._popup = top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.attributes('-topmost', True)
        top.geometry(f"{w}x{h}+{x}+{y}")
        frame = ctk.CTkScrollableFrame(
            top, fg_color=CTK['card'], corner_radius=8,
            border_width=1, border_color=CTK['card_border'])
        frame.pack(fill=tk.BOTH, expand=True)

        cur = self.get()
        sel_btn = None
        for v in self._values:
            is_sel = (v == cur)
            b = ctk.CTkButton(
                frame, text=v, height=item_h - 4, anchor='w', corner_radius=6,
                font=(UI_FONT, 11),
                fg_color=(CTK['accent'] if is_sel else 'transparent'),
                text_color=(CTK['on_accent'] if is_sel else CTK['text']),
                hover_color=CTK['btn_hover'],
                command=lambda val=v: self._select(val))
            b.pack(fill=tk.X, padx=4, pady=1)
            if is_sel:
                sel_btn = b

        top.bind('<Escape>', lambda e: self._close())
        # Close when the main window is clicked anywhere (the popup is a separate
        # toplevel, so its own clicks don't trigger this).
        self._root_click_id = self.winfo_toplevel().bind(
            '<Button-1>', self._on_root_click, add='+')
        # Bring the selected row into view.
        if sel_btn is not None:
            top.after(20, lambda b=sel_btn: self._scroll_to(frame, b))

    @staticmethod
    def _scroll_to(frame, widget):
        try:
            frame.update_idletasks()
            canvas = frame._parent_canvas
            total = frame.winfo_height() or 1
            yoff = widget.winfo_y()
            canvas.yview_moveto(max(0.0, min(1.0, yoff / total)))
        except Exception:
            pass
