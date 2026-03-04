"""
CustomTitleBar — reusable frameless window mixin with a fully custom title bar.

Usage (Tk):
    class App(CustomTitleBar, tk.Tk):
        def __init__(self):
            tk.Tk.__init__(self)
            CustomTitleBar.__init__(self, title="My App", resizable=True)
            # pack your content into  self.content  instead of self

Usage (Toplevel):
    class MyDialog(CustomTitleBar, tk.Toplevel):
        def __init__(self, parent):
            tk.Toplevel.__init__(self, parent)
            CustomTitleBar.__init__(self, title="Dialog", has_maximize=False)
"""

import tkinter as tk
import ctypes
import sys

# ── colour palette (matches App._BG etc.) ─────────────────────────────────────
_BG        = "#1e1e1e"
_TITLEBAR  = "#2d2d2d"
_FG        = "#d4d4d4"
_BTN_HOVER = "#3c3c3c"
_CLOSE_HOV = "#c0392b"
_BORDER    = "#3c3c3c"


class CustomTitleBar:
    """
    Mixin that replaces the native OS title bar with a custom tkinter one.
    Must be mixed in *before* tk.Tk / tk.Toplevel in the MRO so that
    __init__ is called explicitly on the tk base class first.
    """

    # height of the custom title-bar strip
    _TB_H = 36

    def __init__(
        self,
        title: str = "",
        has_maximize: bool = True,
        resizable: bool = True,
    ):
        self._title_text = title
        self._has_maximize = has_maximize
        self._resizable = resizable
        self._maximized = False
        self._restore_geometry: str | None = None

        # Remove native decorations
        self.overrideredirect(True)

        # Outer border frame (gives a 1-px border)
        self._outer = tk.Frame(self, bg=_BORDER, bd=0)
        self._outer.pack(fill="both", expand=True, padx=1, pady=1)

        # Title bar strip
        self._tb = tk.Frame(self._outer, bg=_TITLEBAR, height=self._TB_H)
        self._tb.pack(fill="x", side="top")
        self._tb.pack_propagate(False)

        # Title label
        self._title_lbl = tk.Label(
            self._tb, text=title, bg=_TITLEBAR, fg=_FG,
            font=("Segoe UI", 10), anchor="w", padx=10,
        )
        self._title_lbl.pack(side="left", fill="y")

        # Window control buttons (right side)
        btn_font = ("Segoe UI", 11)
        self._close_btn = _TitleBtn(
            self._tb, text="✕", font=btn_font,
            normal_bg=_TITLEBAR, hover_bg=_CLOSE_HOV, fg=_FG,
            command=self.destroy,
        )
        self._close_btn.pack(side="right")

        if has_maximize:
            self._max_btn = _TitleBtn(
                self._tb, text="□", font=btn_font,
                normal_bg=_TITLEBAR, hover_bg=_BTN_HOVER, fg=_FG,
                command=self._toggle_maximize,
            )
            self._max_btn.pack(side="right")

        self._min_btn = _TitleBtn(
            self._tb, text="–", font=btn_font,
            normal_bg=_TITLEBAR, hover_bg=_BTN_HOVER, fg=_FG,
            command=self._minimize,
        )
        self._min_btn.pack(side="right")

        # Content area — callers should pack/grid their widgets here
        self.content = tk.Frame(self._outer, bg=_BG)
        self.content.pack(fill="both", expand=True)

        # Resize grip (bottom-right corner)
        if resizable:
            self._grip = tk.Label(
                self._outer, text="⠿", bg=_BG, fg="#555555",
                font=("Segoe UI", 9), cursor="size_nw_se",
            )
            self._grip.place(relx=1.0, rely=1.0, anchor="se")
            self._grip.bind("<ButtonPress-1>",   self._on_resize_start)
            self._grip.bind("<B1-Motion>",        self._on_resize_drag)

        # Drag bindings on title bar
        self._tb.bind("<ButtonPress-1>",   self._on_drag_start)
        self._tb.bind("<B1-Motion>",        self._on_drag_move)
        self._tb.bind("<Double-Button-1>",  self._toggle_maximize)
        self._title_lbl.bind("<ButtonPress-1>",  self._on_drag_start)
        self._title_lbl.bind("<B1-Motion>",       self._on_drag_move)
        self._title_lbl.bind("<Double-Button-1>", self._toggle_maximize)

        self._drag_x = 0
        self._drag_y = 0
        self._resize_start_x = 0
        self._resize_start_y = 0
        self._resize_start_w = 0
        self._resize_start_h = 0

        # Re-add to taskbar (overrideredirect removes it)
        self.after(10, self._add_to_taskbar)

    # ── public helpers ────────────────────────────────────────────────────────

    def set_title(self, text: str) -> None:
        self._title_text = text
        self._title_lbl.config(text=text)
        self.title(text)   # also sets taskbar / alt-tab text

    # ── drag ─────────────────────────────────────────────────────────────────

    def _on_drag_start(self, event):
        if self._maximized:
            return
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _on_drag_move(self, event):
        if self._maximized:
            return
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    # ── resize ────────────────────────────────────────────────────────────────

    def _on_resize_start(self, event):
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_start_w = self.winfo_width()
        self._resize_start_h = self.winfo_height()

    def _on_resize_drag(self, event):
        dx = event.x_root - self._resize_start_x
        dy = event.y_root - self._resize_start_y
        nw = max(400, self._resize_start_w + dx)
        nh = max(300, self._resize_start_h + dy)
        self.geometry(f"{nw}x{nh}")

    # ── minimize / maximize ───────────────────────────────────────────────────

    def _minimize(self):
        # Temporarily restore native decorations, iconify, then go back
        self.overrideredirect(False)
        self.iconify()
        self.bind("<Map>", self._on_restore_from_minimize)

    def _on_restore_from_minimize(self, _event):
        self.unbind("<Map>")
        self.overrideredirect(True)
        self.after(10, self._add_to_taskbar)

    def _toggle_maximize(self, _event=None):
        if self._maximized:
            self._maximized = False
            if self._restore_geometry:
                self.geometry(self._restore_geometry)
            if self._has_maximize:
                self._max_btn.config(text="□")
        else:
            self._restore_geometry = self.geometry()
            self._maximized = True
            # Fill work area (excludes taskbar)
            w = self.winfo_screenwidth()
            h = self.winfo_screenheight()
            # Try to get work area height via SystemMetrics (SM_CYFULLSCREEN = 117)
            try:
                work_h = ctypes.windll.user32.GetSystemMetrics(117)
            except Exception:
                work_h = h - 40
            self.geometry(f"{w}x{work_h}+0+0")
            if self._has_maximize:
                self._max_btn.config(text="❐")

    # ── taskbar entry ─────────────────────────────────────────────────────────

    def _add_to_taskbar(self):
        """Make the frameless window appear in the taskbar / alt-tab switcher."""
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            # Add WS_EX_APPWINDOW (0x40000), remove WS_EX_TOOLWINDOW (0x80)
            style = (style | 0x00040000) & ~0x00000080
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
            # Force a frame change so the taskbar picks it up
            ctypes.windll.user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                0x0002 | 0x0001 | 0x0004 | 0x0020,  # SWP_NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED
            )
        except Exception:
            pass


# ── helper widget ─────────────────────────────────────────────────────────────

class DarkToplevel(CustomTitleBar, tk.Toplevel):
    """Convenience: a Toplevel with a custom dark title bar already applied."""

    def __init__(self, parent, title: str, width: int, height: int, resizable: bool = False):
        tk.Toplevel.__init__(self, parent)
        self.geometry(f"{width}x{height}")
        self.transient(parent)
        CustomTitleBar.__init__(self, title=title, has_maximize=False, resizable=resizable)


class _TitleBtn(tk.Label):
    """A hover-highlighted title-bar button."""

    def __init__(self, parent, *, text, font, normal_bg, hover_bg, fg, command):
        super().__init__(
            parent, text=text, font=font, bg=normal_bg, fg=fg,
            width=4, cursor="hand2", anchor="center",
        )
        self._normal_bg = normal_bg
        self._hover_bg  = hover_bg
        self._cmd       = command
        self.bind("<Enter>",           lambda _e: self.config(bg=hover_bg))
        self.bind("<Leave>",           lambda _e: self.config(bg=normal_bg))
        self.bind("<ButtonRelease-1>", lambda _e: command())
