"""
Windows App Reinstaller
-----------------------
1. Run BEFORE a Windows reset to scan & select which programs to keep.
2. Save the list to a JSON file (put it on USB / cloud).
3. Run AFTER the reset to reinstall everything via winget.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import ctypes
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from drive_sync import save_to_drive, load_from_drive, has_client_secret, import_client_secret
from app_data import backup_app_data, restore_app_data


def _dark_titlebar(win):
    """Force dark title bar and border via the Windows DWM API."""
    try:
        hwnd = ctypes.windll.user32.GetAncestor(win.winfo_id(), 2)  # GA_ROOT
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11=20, Win10=19)
            v = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        # DWMWA_BORDER_COLOR = 34, COLORREF is 0x00BBGGRR
        border_color = ctypes.c_int(0x00333333)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border_color), ctypes.sizeof(border_color))
    except Exception:
        pass

class _Tooltip:
    """
    Dark-themed tooltip that appears after a short hover delay.
    Usage: _Tooltip(widget, "text here")
    """
    _BG  = "#2d2d2d"
    _FG  = "#d4d4d4"
    _BD  = "#555555"
    _PAD = 6
    _DELAY = 550  # ms before showing

    def __init__(self, widget: tk.Widget, text: str):
        self._widget  = widget
        self._text    = text
        self._win: tk.Toplevel | None = None
        self._after_id: str | None   = None
        widget.bind("<Enter>",   self._on_enter,  add="+")
        widget.bind("<Leave>",   self._on_leave,  add="+")
        widget.bind("<Button>",  self._on_leave,  add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_enter(self, event):
        self._cancel()
        self._after_id = self._widget.after(self._DELAY, self._show)

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _on_destroy(self, event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._hide()
        try:
            x = self._widget.winfo_rootx() + 4
            y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        except Exception:
            return
        self._win = tk.Toplevel(self._widget)
        self._win.wm_overrideredirect(True)
        self._win.wm_geometry(f"+{x}+{y}")
        self._win.configure(bg=self._BD)   # thin border via outer frame colour
        frame = tk.Frame(self._win, bg=self._BG,
                         highlightthickness=1, highlightbackground=self._BD)
        frame.pack(padx=1, pady=1)
        tk.Label(
            frame, text=self._text,
            bg=self._BG, fg=self._FG,
            font=("Segoe UI", 9),
            wraplength=340,
            justify="left",
            padx=self._PAD, pady=self._PAD,
        ).pack()

    def _hide(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


DEFAULT_FILE = Path(__file__).parent / "app_list.json"
STEAM_WINGET_ID = "Valve.Steam"
_STEAM_APP_RE = re.compile(r"^ARP\\Machine(?:\\X64|\\X86)?\\Steam App (\d+)$", re.IGNORECASE)

# Winget ID prefixes and name patterns for built-in Windows / Microsoft system apps.
# These ship with Windows and get restored automatically after a reset.
# Substrings matched against the "bare" winget ID (after stripping MSIX\/ARP\ prefixes).
# Any ID that starts with one of these is considered a Windows built-in.
_IGNORED_ID_PREFIXES = (
    "Microsoft.UI.",
    "Microsoft.VCLibs",
    "Microsoft.NET.",
    "Microsoft.DirectX",
    "Microsoft.Windows",
    "Microsoft.DesktopAppInstaller",
    "Microsoft.StorePurchaseApp",
    "Microsoft.VP9VideoExtensions",
    "Microsoft.WebMediaExtensions",
    "Microsoft.WebpImageExtension",
    "Microsoft.HEIFImageExtension",
    "Microsoft.HEVCVideoExtension",
    "Microsoft.RawImageExtension",
    "Microsoft.AV1VideoExtension",
    "Microsoft.MPEG2VideoExtension",
    "Microsoft.ScreenSketch",
    "Microsoft.MicrosoftStickyNotes",
    "Microsoft.GetHelp",
    "Microsoft.Getstarted",
    "Microsoft.MicrosoftOfficeHub",
    "Microsoft.People",
    "Microsoft.ZuneMusic",
    "Microsoft.ZuneVideo",
    "Microsoft.Xbox",
    "Microsoft.GamingApp",
    "Microsoft.BingWeather",
    "Microsoft.BingNews",
    "Microsoft.Todos",
    "Microsoft.YourPhone",
    "Microsoft.549981C3F5F10",  # Cortana
    "MicrosoftWindows.",
    "MicrosoftCorporationII.",
    "Microsoft.MicrosoftEdge",
    "Microsoft.Paint",
    "Microsoft.Whiteboard",
    "Microsoft.WindowsStore",
    "Microsoft.WindowsCalculator",
    "Microsoft.WindowsCamera",
    "Microsoft.WindowsAlarms",
    "Microsoft.WindowsMaps",
    "Microsoft.WindowsSoundRecorder",
    "Microsoft.WindowsFeedbackHub",
    "Microsoft.WindowsNotepad",
    "Microsoft.WindowsTerminal",
    "Microsoft.WindowsAppRuntime",
    "Microsoft.Photos",
    "Microsoft.MSPaint",
    "Microsoft.SkypeApp",
    "Microsoft.Clipchamp",
    "Microsoft.OutlookForWindows",
    "Microsoft.PowerAutomateDesktop",
    "Microsoft.DevHome",
    "Microsoft.Copilot",
    "Microsoft.ApplicationCompatibility",
    "Microsoft.SecHealth",
    "Microsoft.SolitaireCollection",
    "Microsoft.StartExperiencesApp",
    "Microsoft.WidgetsPlatformRuntime",
    "Microsoft.Winget.",
    "Microsoft.WSL",
    "Microsoft.CorporationII",
    "Microsoft.WinAppRuntime",
    "Microsoft.QuickAssist",
    # Drivers & hardware components
    "Intel.",
    "Realtek.",
    "NVIDIA.",
    "AMD.",
    "Qualcomm.",
    "Broadcom.",
    "Synaptics.",
    "Dell.",
    "HP.",
    "Lenovo.",
    "ASUS.",
    "Acer.",
    "Toshiba.",
    "Samsung.Display",
    "Samsung.Drivers",
    "Logitech.Options",          # often reinstalls via Windows Update
    "Microsoft.HDAudio",
    "Microsoft.WHQL",
)

_IGNORED_NAME_KEYWORDS = (
    "microsoft edge",
    "microsoft update",
    "windows driver",
    "windows sdk",
    "microsoft visual c++ 20",  # VC++ redistributables
    "update for windows",
    "security update",
    "hotfix for windows",
    "microsoft .net",
    ".net runtime",
    ".net desktop runtime",
    ".net host",
    "asp.net",
    "windows app runtime",
    "windowsappruntime",
    "winappruntime",
    "msvc",
    "microsoft onedrive",
    "snipping tool",
    "solitaire",
    "phone link",
    "quick assist",
    "windows calculator",
    "windows camera",
    "windows clock",
    "windows notepad",
    "windows media player",
    "windows sound recorder",
    "windows security",
    "windows subsystem for linux",
    "windows web experience",
    "windows package manager",
    "windows application compatibility",
    "xbox",
    "widgets platform",
    "start experiences",
    "store experience",
    "web media extensions",
    "webp image extension",
    "raw image extension",
    "vp9 video extension",
    "paint",
    # Drivers & hardware components (reinstalled by Windows Update)
    "driver",
    "realtek",
    "intel(r)",
    "intel ",
    "nvidia graphics",
    "nvidia hd audio",
    "nvidia usb",
    "nvidia framev",
    "nvidia physx",
    "nvidia geforce experience",
    "geforce game ready",
    "amd software",
    "amd chipset",
    "amd radeon",
    "amd gpio",
    "amd psp",
    "amd sata",
    "amd smbus",
    "qualcomm",
    "broadcom",
    "synaptics",
    "elan ",
    "goodix",
    "tobii",
    "wacom",
    "dell ",
    "dell supportassist",
    "dell update",
    "dell command",
    "hp ",
    "lenovo ",
    "asus ",
    "acer ",
    "toshiba ",
    "firmware",
    "chipset",
    "thunderbolt",
    "bluetooth",
    "wi-fi ",
    "wifi ",
    "wlan ",
    "ethernet",
    "lan manager",
    "card reader",
    "sd host",
    "audio controller",
    "sound blaster",
    "conexant",
    "maxxaudio",
    "dolby",
    "waves maxxaudio",
    "touchpad",
    "pointing device",
    "i2c hid",
    "hid event filter",
    "serial io",
    "management engine",
    "dptf",
    "dynamic platform",
    "thermal framework",
    "icc profile",
    "integrated sensor",
    "rapid storage",
    "optane",
    "rst ",
    "smart connect",
    "smart sound",
    "power gadget",
    "system interface foundation",
    "control center",
    "killer ",                    # Killer networking
    "rivet networks",
)


def _strip_winget_prefix(winget_id: str) -> str:
    """Strip MSIX\\, ARP\\Machine\\X64\\, etc. prefixes to get the bare package ID."""
    # Common prefixes: "MSIX\\", "ARP\\Machine\\X64\\", "ARP\\Machine\\X86\\"
    for marker in ("MSIX\\", "ARP\\Machine\\X64\\", "ARP\\Machine\\X86\\", "ARP\\Machine\\"):
        if winget_id.startswith(marker):
            return winget_id[len(marker):]
    # Also handle { MSIX } style
    if winget_id.startswith("{"):
        inner = winget_id.strip("{ }")
        for marker in ("MSIX\\", "ARP\\Machine\\X64\\", "ARP\\Machine\\X86\\", "ARP\\Machine\\"):
            if inner.startswith(marker):
                return inner[len(marker):]
    return winget_id


def _is_windows_builtin(name: str, winget_id: str | None) -> bool:
    """Return True if this looks like a built-in Windows / system component."""
    name_lower = name.lower()

    # Check name keywords
    for kw in _IGNORED_NAME_KEYWORDS:
        if kw in name_lower:
            return True

    # Check winget ID prefixes (strip MSIX\/ARP\ wrappers first)
    if winget_id:
        bare_id = _strip_winget_prefix(winget_id)
        for prefix in _IGNORED_ID_PREFIXES:
            if bare_id.startswith(prefix):
                return True

    return False


def _extract_steam_appid(winget_id: str | None) -> str | None:
    """Return the Steam AppID from an ARP-style Steam entry, if present."""
    if not winget_id:
        return None
    match = _STEAM_APP_RE.match(winget_id)
    if match:
        return match.group(1)
    return None


def _scan_exported_winget_ids() -> set[str]:
    """Return the set of package identifiers that winget can export/reinstall."""
    export_path = Path(tempfile.gettempdir()) / f"woaster-winget-export-{os.getpid()}.json"
    try:
        if export_path.exists():
            export_path.unlink()
        subprocess.run(
            ["winget", "export", "-o", str(export_path), "--include-versions", "--disable-interactivity"],
            capture_output=True, text=True, timeout=180,
        )
        if not export_path.exists():
            return set()
        data = json.loads(export_path.read_text(encoding="utf-8-sig"))
        ids: set[str] = set()
        for source in data.get("Sources", []):
            for package in source.get("Packages", []):
                package_id = package.get("PackageIdentifier")
                if package_id:
                    ids.add(package_id)
        return ids
    except Exception:
        return set()
    finally:
        try:
            if export_path.exists():
                export_path.unlink()
        except OSError:
            pass


def _install_type(app: dict) -> str:
    """Return the install mechanism for a saved app entry."""
    if app.get("install_type"):
        return app["install_type"]
    if app.get("steam_appid"):
        return "steam_game"
    if app.get("winget_id"):
        return "winget"
    return ""


def _display_target(app: dict) -> str:
    """Return the text shown in the install target column."""
    install_type = _install_type(app)
    if install_type == "steam_game":
        return f"Steam App {app.get('steam_appid', '')}"
    return app.get("winget_id", "")


def _summarize_install_plan(apps: list[dict]) -> tuple[int, int]:
    """Return (winget_count, steam_game_count) for a list of saved app entries."""
    winget_count = 0
    steam_game_count = 0
    for app in apps:
        install_type = _install_type(app)
        if install_type == "steam_game" and app.get("steam_appid"):
            steam_game_count += 1
        elif install_type == "winget" and app.get("winget_id"):
            winget_count += 1
    return winget_count, steam_game_count


# ── Scanning ────────────────────────────────────────────────────────────────

def scan_winget() -> list[dict]:
    """Return installed entries from winget list with exact winget packages plus Steam games."""
    try:
        result = subprocess.run(
            ["winget", "list", "--disable-interactivity"],
            capture_output=True, text=True, timeout=60,
        )
        installable_ids = _scan_exported_winget_ids()
        apps = []
        seen: set[tuple[str, str]] = set()
        lines = result.stdout.splitlines()
        # Find the header separator line (dashes)
        sep_idx = None
        for i, line in enumerate(lines):
            if line.startswith("---"):
                sep_idx = i
                break
        if sep_idx is None:
            return apps
        header = lines[sep_idx - 1]
        # Determine column positions from header
        id_col = header.index("Id")
        ver_col = header.index("Version")
        for line in lines[sep_idx + 1:]:
            if len(line.strip()) == 0:
                continue
            name = line[:id_col].strip()
            winget_id = line[id_col:ver_col].strip()
            if name and winget_id:
                steam_appid = _extract_steam_appid(winget_id)
                if winget_id in installable_ids:
                    key = ("winget", winget_id)
                    if key not in seen:
                        seen.add(key)
                        apps.append({"name": name, "winget_id": winget_id, "install_type": "winget"})
                elif steam_appid:
                    key = ("steam_game", steam_appid)
                    if key not in seen:
                        seen.add(key)
                        apps.append({"name": name, "steam_appid": steam_appid, "install_type": "steam_game"})
        return apps
    except Exception:
        return []


def scan_all(include_windows: bool = False) -> list[dict]:
    """Return reinstallable apps and Steam games (non-builtins by default)."""
    winget_apps = scan_winget()
    apps = []
    for app in sorted(winget_apps, key=lambda x: x["name"].lower()):
        name = app["name"]
        wid = app.get("winget_id")
        if wid and not include_windows and _is_windows_builtin(name, wid):
            continue
        apps.append(app)
    return apps


# ── GUI ─────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Woaster")
        self.geometry("820x620")
        self.minsize(600, 400)
        # Set window icon
        icon_path = Path(__file__).parent / "app.ico"
        if not icon_path.exists() and getattr(sys, "frozen", False):
            icon_path = Path(sys._MEIPASS) / "app.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))
        self.apps: list[dict] = []
        self.check_vars: list[tk.BooleanVar] = []
        self._backup_win: tk.Toplevel | None = None
        self._apply_dark_theme()
        self._build_ui()
        self.bind("<Map>", lambda _: (_dark_titlebar(self), self.unbind("<Map>")))
        self.bind("<FocusIn>", self._on_main_focus)

    # ── dark theme ──────────────────────────────────────────────────────

    _BG       = "#1e1e1e"
    _FG       = "#d4d4d4"
    _BTN_BG   = "#3c3c3c"
    _BTN_ACT  = "#505050"
    _ENTRY_BG = "#2d2d2d"
    _TREE_BG  = "#252526"
    _TREE_SEL = "#094771"
    _BORDER   = "#555555"

    def _apply_dark_theme(self):
        self.configure(bg=self._BG)
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".",
            background=self._BG, foreground=self._FG,
            fieldbackground=self._ENTRY_BG, bordercolor=self._BORDER,
            troughcolor=self._BG, font=("Segoe UI", 9))
        s.configure("TFrame", background=self._BG)
        s.configure("TLabel", background=self._BG, foreground=self._FG)
        s.configure("TButton",
            background=self._BTN_BG, foreground=self._FG,
            bordercolor=self._BORDER, lightcolor=self._BTN_BG,
            darkcolor=self._BTN_BG, padding=4)
        s.map("TButton",
            background=[("active", self._BTN_ACT), ("pressed", self._BTN_ACT)],
            foreground=[("active", self._FG)])
        s.configure("TEntry",
            fieldbackground=self._ENTRY_BG, foreground=self._FG,
            insertcolor=self._FG, bordercolor=self._BORDER)
        s.configure("TCheckbutton", background=self._BG, foreground=self._FG)
        s.map("TCheckbutton",
            background=[("active", self._BG)],
            foreground=[("active", self._FG)])
        s.configure("TLabelframe", background=self._BG, bordercolor=self._BORDER)
        s.configure("TLabelframe.Label", background=self._BG, foreground=self._FG)
        s.configure("TSeparator", background=self._BORDER)
        s.configure("Treeview",
            background=self._TREE_BG, foreground=self._FG,
            fieldbackground=self._TREE_BG, bordercolor=self._BORDER)
        s.map("Treeview",
            background=[("selected", self._TREE_SEL)],
            foreground=[("selected", self._FG)])
        s.configure("Treeview.Heading",
            background=self._BTN_BG, foreground=self._FG,
            bordercolor=self._BORDER)
        s.map("Treeview.Heading",
            background=[("active", self._BTN_ACT)])
        s.configure("TScrollbar",
            background=self._BTN_BG, troughcolor=self._BG,
            bordercolor=self._BORDER, arrowcolor=self._FG)
        s.map("TScrollbar", background=[("active", self._BTN_ACT)])

    # ── layout ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # App title header — "WindOws App reinSTallER" with W O A S T E R highlighted
        title_frame = tk.Frame(self, bg=self._BG)
        title_frame.pack(pady=(10, 2))
        highlight_color = "#e74c3c"
        normal_color = "#999999"
        # Each tuple: (char, highlighted?)
        title_chars = [
            ("W", True), ("i", False), ("n", False), ("d", False),
            ("O", True), ("w", False), ("s", False), (" ", False),
            ("A", True), ("p", False), ("p", False), (" ", False),
            ("r", False), ("e", False), ("i", False), ("n", False),
            ("S", True), ("T", True), ("a", False), ("l", False),
            ("l", False), ("E", True), ("R", True),
        ]
        for char, highlighted in title_chars:
            tk.Label(
                title_frame,
                text=char,
                font=("Segoe UI", 22, "bold" if highlighted else "normal"),
                fg=highlight_color if highlighted else normal_color,
                bg=self._BG,
            ).pack(side="left")

        # ── Toolbar: grouped sections ─────────────────────────────────────────
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        T = self._HELP_TOPICS  # shorthand

        # Google Drive
        grp_drive = ttk.LabelFrame(toolbar, text="Google Drive")
        grp_drive.pack(side="left", padx=(0, 6), pady=2)
        b = ttk.Button(grp_drive, text="Setup",          command=self._on_setup_drive); b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Setup Google Drive"])
        b = ttk.Button(grp_drive, text="Save",           command=self._on_save_drive);  b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Save to Drive"])
        b = ttk.Button(grp_drive, text="Load & Install", command=self._on_load_drive_install); b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Load from Drive & Install"])

        # Local — app list only
        grp_local = ttk.LabelFrame(toolbar, text="Local List")
        grp_local.pack(side="left", padx=(0, 6), pady=2)
        b = ttk.Button(grp_local, text="Save",           command=self._on_save);         b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Save Local"])
        b = ttk.Button(grp_local, text="Load & Install", command=self._on_load_install); b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Load Local & Install"])

        # Full backup — app list + AppData + registry
        grp_full = ttk.LabelFrame(toolbar, text="Full Backup  (List + App Data)")
        grp_full.pack(side="left", padx=(0, 6), pady=2)
        b = ttk.Button(grp_full, text="Save",           command=self._on_full_save);          b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Full Backup: Save"])
        b = ttk.Button(grp_full, text="Load & Install", command=self._on_full_load_install);  b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Full Backup: Load & Install"])

        # Personal files backup
        grp_files = ttk.LabelFrame(toolbar, text="My Files")
        grp_files.pack(side="left", padx=(0, 6), pady=2)
        b = ttk.Button(grp_files, text="Backup", command=self._on_backup_files); b.pack(side="left", padx=2, pady=2); _Tooltip(b, T["Backup Files"])

        # Info bar
        info_frame = ttk.LabelFrame(self, text="Quick guide")
        info_frame.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Label(
            info_frame,
            text=(
                "Google Drive \u2014 store your app list in the cloud; accessible from any PC after a reset (one-time setup required).\n"
                "Local List \u2014 save just the app list to a JSON file on a USB drive or external storage.\n"
                "Full Backup \u2014 saves the app list AND each app\u2019s settings/data (AppData + registry); incremental, safe to re-run.\n"
                "My Files \u2014 browse your personal folders and copy them to an external drive."
            ),
            wraplength=820, justify="left",
        ).pack(anchor="w", padx=6, pady=4)

        # List controls bar (scan, filter, select)
        list_bar = ttk.Frame(self)
        list_bar.pack(fill="x", padx=8, pady=(6, 2))

        T = self._HELP_TOPICS
        b = ttk.Button(list_bar, text="Scan Programs", command=self._on_scan);    b.pack(side="left", padx=2); _Tooltip(b, T["Scan Programs"])
        b = ttk.Button(list_bar, text="Select All",   command=self._select_all);  b.pack(side="left", padx=2); _Tooltip(b, T["Select All / Deselect All"])
        b = ttk.Button(list_bar, text="Deselect All", command=self._deselect_all); b.pack(side="left", padx=2); _Tooltip(b, T["Select All / Deselect All"])
        ttk.Separator(list_bar, orient="vertical").pack(side="left", fill="y", padx=6)

        lbl = ttk.Label(list_bar, text="Filter:"); lbl.pack(side="left"); _Tooltip(lbl, T["Filter"])
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refresh_tree())
        fe = ttk.Entry(list_bar, textvariable=self.filter_var); fe.pack(side="left", fill="x", expand=True, padx=4); _Tooltip(fe, T["Filter"])

        self.show_builtins = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(
            list_bar, text="Show Windows built-ins",
            variable=self.show_builtins,
            command=self._on_scan,
        ); cb.pack(side="left"); _Tooltip(cb, T["Show Windows built-ins"])

        # Treeview
        cols = ("selected", "name", "winget_id")
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=8, pady=4)

        self.tree = ttk.Treeview(container, columns=cols, show="headings", selectmode="none")
        self.tree.heading("selected", text="Keep")
        self.tree.heading("name", text="Program Name")
        self.tree.heading("winget_id", text="Install Target")
        self.tree.column("selected", width=50, anchor="center", stretch=False)
        self.tree.column("name", width=350)
        self.tree.column("winget_id", width=350)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Status bar
        self.status_var = tk.StringVar(value="Click 'Scan Programs' to begin.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(
            fill="x", padx=8, pady=(0, 8),
        )

    # ── tree helpers ────────────────────────────────────────────────────

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        filt = self.filter_var.get().lower()
        for i, app in enumerate(self.apps):
            target = _display_target(app)
            if filt and filt not in app["name"].lower() and filt not in target.lower():
                continue
            check = "\u2611" if self.check_vars[i].get() else "\u2610"
            self.tree.insert(
                "", "end", iid=str(i),
                values=(check, app["name"], target),
            )

    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        idx = int(row_id)
        self.check_vars[idx].set(not self.check_vars[idx].get())
        check = "\u2611" if self.check_vars[idx].get() else "\u2610"
        vals = list(self.tree.item(row_id, "values"))
        vals[0] = check
        self.tree.item(row_id, values=vals)
        self._update_status_count()

    def _update_status_count(self):
        total = len(self.apps)
        selected = sum(v.get() for v in self.check_vars)
        self.status_var.set(f"{total} programs found  |  {selected} selected")

    def _select_all(self):
        for v in self.check_vars:
            v.set(True)
        self._refresh_tree()
        self._update_status_count()

    def _deselect_all(self):
        for v in self.check_vars:
            v.set(False)
        self._refresh_tree()
        self._update_status_count()

    # ── actions ─────────────────────────────────────────────────────────

    def _on_scan(self):
        self.status_var.set("Scanning reinstallable programs and Steam games (this may take a moment)...")
        self.update_idletasks()

        def _do_scan():
            self.apps = scan_all(include_windows=self.show_builtins.get())
            self.check_vars = [tk.BooleanVar(value=True) for _ in self.apps]
            self.after(0, self._refresh_tree)
            self.after(0, self._update_status_count)

        threading.Thread(target=_do_scan, daemon=True).start()

    def _get_selected_apps(self) -> list[dict]:
        return [app for i, app in enumerate(self.apps) if self.check_vars[i].get()]

    def _do_install_list(self, install_apps: list[dict]):
        """Install a list of apps via winget and Steam. Runs in a background thread."""
        results = {"winget_ok": [], "winget_fail": [], "steam_ok": [], "steam_fail": []}

        winget_apps = [a for a in install_apps if _install_type(a) == "winget" and a.get("winget_id")]
        steam_games = [a for a in install_apps if _install_type(a) == "steam_game" and a.get("steam_appid")]

        if steam_games and not any(a.get("winget_id") == STEAM_WINGET_ID for a in winget_apps):
            winget_apps = [{"name": "Steam", "winget_id": STEAM_WINGET_ID, "install_type": "winget"}] + winget_apps

        for app in winget_apps:
            self.after(0, lambda a=app: self.status_var.set(f"Installing {a['name']}..."))
            try:
                proc = subprocess.run(
                    [
                        "winget", "install", "--id", app["winget_id"],
                        "--accept-package-agreements", "--accept-source-agreements",
                        "--disable-interactivity",
                    ],
                    capture_output=True, text=True, timeout=300,
                )
                if proc.returncode == 0:
                    results["winget_ok"].append(app["name"])
                else:
                    results["winget_fail"].append(app["name"])
            except Exception:
                results["winget_fail"].append(app["name"])

        if steam_games:
            try:
                os.startfile("steam://open/main")
                time.sleep(3)
            except Exception:
                pass

        for app in steam_games:
            self.after(0, lambda a=app: self.status_var.set(f"Queueing {a['name']} in Steam..."))
            try:
                os.startfile(f"steam://install/{app['steam_appid']}")
                results["steam_ok"].append(app["name"])
                time.sleep(1)
            except Exception:
                results["steam_fail"].append(app["name"])

        def _show_results():
            lines = []
            if results["winget_ok"]:
                lines.append(f"Installed via winget: {len(results['winget_ok'])}")
            if results["steam_ok"]:
                lines.append(f"Queued in Steam: {len(results['steam_ok'])}")
            if results["winget_fail"]:
                lines.append(f"Winget failed: {', '.join(results['winget_fail'])}")
            if results["steam_fail"]:
                lines.append(f"Steam queue failed: {', '.join(results['steam_fail'])}")
            total_ok = len(results["winget_ok"]) + len(results["steam_ok"])
            total_fail = len(results["winget_fail"]) + len(results["steam_fail"])
            self.status_var.set(f"Done — {total_ok} completed, {total_fail} failed")
            messagebox.showinfo("Install Complete", "\n".join(lines))

        self.after(0, _show_results)

    # ── Local save/load ────────────────────────────────────────────────

    # ── full save / full restore ─────────────────────────────────────────────

    def _on_full_save(self):
        if not self.apps:
            messagebox.showwarning("Nothing to save", "Scan for programs first.")
            return
        folder = filedialog.askdirectory(title="Choose folder for Full Save")
        if not folder:
            return
        dest = Path(folder)
        selected = self._get_selected_apps()
        # Write quick app list so restore can find it
        (dest / "app_list.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
        self._run_full_backup(selected, dest)

    def _run_full_backup(self, apps: list, dest: Path):
        """Open a progress window and run backup_app_data in a background thread."""
        win = tk.Toplevel(self)
        win.title("Full Save — Backing up app data…")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        _dark_titlebar(win)
        self.after(50, lambda: _dark_titlebar(win))

        msg_var = tk.StringVar(value="Starting…")
        prog_var = tk.IntVar(value=0)

        ttk.Label(win, text="Saving app list and application data:").pack(padx=16, pady=(12, 4))
        ttk.Label(win, textvariable=msg_var, wraplength=400).pack(padx=16)
        bar = ttk.Progressbar(win, variable=prog_var, maximum=max(len(apps), 1))
        bar.pack(fill="x", padx=16, pady=8)

        def _progress(cur, total, msg):
            prog_var.set(cur)
            bar.config(maximum=max(total, 1))
            msg_var.set(msg)
            win.update_idletasks()

        def _worker():
            try:
                backup_app_data(apps, dest, progress_cb=_progress)
                self.after(0, lambda: (
                    messagebox.showinfo(
                        "Full Save Complete",
                        f"App list + data saved to:\n{dest}",
                        parent=win,
                    ),
                    win.destroy(),
                    self.status_var.set(f"Full save complete → {dest}"),
                ))
            except Exception as exc:
                self.after(0, lambda: (
                    messagebox.showerror("Error", str(exc), parent=win),
                    win.destroy(),
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_full_load_install(self):
        folder = filedialog.askdirectory(title="Choose Full Save folder to restore from")
        if not folder:
            return
        dest = Path(folder)
        list_file = dest / "app_list.json"
        if not list_file.exists():
            messagebox.showerror(
                "Invalid folder",
                "No app_list.json found in that folder.\n"
                "Please select the folder created by \"Full Save Local\"."
            )
            return
        data = json.loads(list_file.read_text(encoding="utf-8"))
        winget_count, steam_count = _summarize_install_plan(data)

        msg = (
            f"{winget_count} apps will be installed via winget"
            f" and {steam_count} Steam games will be queued in Steam, "
            "then their AppData and registry will be restored.\n\nProceed?"
        )
        if not messagebox.askyesno("Confirm Full Restore", msg):
            return

        self.status_var.set("Full restore: installing apps…")
        self.update_idletasks()

        def _worker():
            # Step 1: install apps
            self._do_install_list(data)
            # Step 2: restore data
            self.after(0, lambda: self._run_full_restore(dest))

        threading.Thread(target=_worker, daemon=True).start()

    def _run_full_restore(self, backup_root: Path):
        """Open a progress window and run restore_app_data in a background thread."""
        win = tk.Toplevel(self)
        win.title("Full Restore — Restoring app data…")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        _dark_titlebar(win)
        self.after(50, lambda: _dark_titlebar(win))

        msg_var = tk.StringVar(value="Starting…")
        prog_var = tk.IntVar(value=0)

        ttk.Label(win, text="Restoring application data:").pack(padx=16, pady=(12, 4))
        ttk.Label(win, textvariable=msg_var, wraplength=400).pack(padx=16)
        bar = ttk.Progressbar(win, variable=prog_var)
        bar.pack(fill="x", padx=16, pady=8)

        def _progress(cur, total, msg):
            prog_var.set(cur)
            bar.config(maximum=max(total, 1))
            msg_var.set(msg)
            win.update_idletasks()

        def _worker():
            try:
                errors = restore_app_data(backup_root, progress_cb=_progress)
                def _done():
                    if errors:
                        detail = "\n".join(errors[:10])
                        if len(errors) > 10:
                            detail += f"\n… and {len(errors) - 10} more"
                        messagebox.showwarning(
                            "Restore Complete (with errors)",
                            f"Some items could not be restored:\n\n{detail}",
                            parent=win,
                        )
                    else:
                        messagebox.showinfo(
                            "Restore Complete",
                            "All app data restored successfully.",
                            parent=win,
                        )
                    win.destroy()
                    self.status_var.set("Full restore complete.")
                self.after(0, _done)
            except Exception as exc:
                self.after(0, lambda: (
                    messagebox.showerror("Error", str(exc), parent=win),
                    win.destroy(),
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_save(self):
        if not self.apps:
            messagebox.showwarning("Nothing to save", "Scan for programs first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile=DEFAULT_FILE.name,
            initialdir=DEFAULT_FILE.parent,
        )
        if not path:
            return
        # Warn if saving to the same drive Windows is installed on
        win_drive = os.environ.get("SystemDrive", "C:").upper()
        save_drive = Path(path).resolve().drive.upper()
        if save_drive == win_drive:
            if not messagebox.askyesno(
                "Same Drive as Windows",
                f"You're saving to {save_drive}\\, which is the drive Windows is installed on.\n\n"
                "This file will be lost if you reset Windows. "
                "Consider saving to a USB drive or external storage instead.\n\n"
                "Save here anyway?",
            ):
                return
        selected = self._get_selected_apps()
        Path(path).write_text(json.dumps(selected, indent=2), encoding="utf-8")
        self.status_var.set(f"Saved {len(selected)} programs to {path}")

    def _on_load_install(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")],
            initialdir=DEFAULT_FILE.parent,
        )
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        winget_count, steam_count = _summarize_install_plan(data)

        if not (winget_count or steam_count):
            messagebox.showwarning("Nothing to install", "No reinstallable apps or Steam games found in the list.")
            return

        msg = (
            f"{winget_count} apps will be installed via winget"
            f" and {steam_count} Steam games will be queued in Steam.\n\nProceed?"
        )
        if not messagebox.askyesno("Confirm Install", msg):
            return

        self.status_var.set("Installing...")
        self.update_idletasks()
        threading.Thread(target=self._do_install_list, args=(data,), daemon=True).start()

    # ── Google Drive setup & save/load ───────────────────────────────

    def _on_setup_drive(self):
        if has_client_secret():
            if not messagebox.askyesno(
                "Already Configured",
                "Google Drive credentials are already set up.\n\n"
                "Replace with a different client_secret.json?"
            ):
                return

        messagebox.showinfo(
            "Setup Google Drive",
            "To use Google Drive sync, you need your own Google Cloud credentials.\n\n"
            "1. A browser will open to the Google Cloud Console\n"
            "2. Create a project (or select an existing one)\n"
            "3. Enable the Google Drive API\n"
            "4. Go to APIs & Services > Credentials\n"
            "5. Create an OAuth 2.0 Client ID (type: Desktop app)\n"
            "6. Download the JSON file\n\n"
            "After downloading, select that file in the next dialog."
        )

        webbrowser.open("https://console.cloud.google.com/apis/credentials")

        path = filedialog.askopenfilename(
            title="Select your client_secret.json",
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return

        try:
            import_client_secret(path)
            messagebox.showinfo("Success", "Google Drive credentials saved.\n\nYou can now use Save/Load to Drive.")
            self.status_var.set("Google Drive configured.")
        except (ValueError, FileNotFoundError) as e:
            messagebox.showerror("Invalid File", str(e))

    def _ensure_drive_configured(self) -> bool:
        if has_client_secret():
            return True
        messagebox.showwarning(
            "Drive Not Configured",
            "Google Drive is not set up yet.\n\n"
            "Click 'Setup Google Drive' first to provide your credentials."
        )
        return False

    def _on_save_drive(self):
        if not self._ensure_drive_configured():
            return
        if not self.apps:
            messagebox.showwarning("Nothing to save", "Scan for programs first.")
            return
        selected = self._get_selected_apps()
        if not selected:
            messagebox.showwarning("Nothing selected", "Select at least one program.")
            return

        self.status_var.set("Saving to Google Drive...")
        self.update_idletasks()

        def _do_save():
            try:
                msg = save_to_drive(selected)
                self.after(0, lambda: self.status_var.set(msg))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Drive Error",
                    f"Failed to save to Google Drive:\n{e}"))
                self.after(0, lambda: self.status_var.set("Drive save failed."))

        threading.Thread(target=_do_save, daemon=True).start()

    def _on_load_drive_install(self):
        if not self._ensure_drive_configured():
            return
        self.status_var.set("Loading from Google Drive...")
        self.update_idletasks()

        def _do_load():
            try:
                data = load_from_drive()
            except FileNotFoundError as e:
                self.after(0, lambda: messagebox.showwarning("Not Found", str(e)))
                self.after(0, lambda: self.status_var.set("No list found on Drive."))
                return
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Drive Error",
                    f"Failed to load from Google Drive:\n{e}"))
                self.after(0, lambda: self.status_var.set("Drive load failed."))
                return

            winget_count, steam_count = _summarize_install_plan(data)
            if not (winget_count or steam_count):
                self.after(0, lambda: messagebox.showwarning(
                    "Nothing to install",
                    "No reinstallable apps or Steam games found in the Drive list."))
                return

            def _confirm_and_install():
                msg = (
                    f"{winget_count} apps and {steam_count} Steam games loaded from Drive.\n\n"
                    "Proceed with install?"
                )
                if not messagebox.askyesno("Confirm Install", msg):
                    self.status_var.set("Install cancelled.")
                    return
                self.status_var.set("Installing...")
                threading.Thread(
                    target=self._do_install_list, args=(data,), daemon=True
                ).start()

            self.after(0, _confirm_and_install)

        threading.Thread(target=_do_load, daemon=True).start()

    # ── Backup Files ──────────────────────────────────────────────────

    def _on_main_focus(self, _event):
        """If a BackupWindow is open, redirect focus to it."""
        if self._backup_win and self._backup_win.winfo_exists():
            self._backup_win.lift()
            self._backup_win.focus_force()

    def _on_backup_files(self):
        from backup_files import BackupWindow
        if self._backup_win and self._backup_win.winfo_exists():
            self._backup_win.lift()
            self._backup_win.focus_force()
            return
        self._backup_win = BackupWindow(self)
        self._backup_win.bind("<Destroy>", lambda _: setattr(self, "_backup_win", None))

    # ── Help ───────────────────────────────────────────────────────────

    _HELP_TOPICS = {
        "Full Backup: Save": (
            "Saves your selected app list AND each app\u2019s settings/data to a folder "
            "you choose (e.g. an external drive).\n\n"
            "What gets saved:\n"
            "  \u2022 app_list.json \u2014 the list of programs\n"
            "  \u2022 AppData\\Roaming, AppData\\Local, ProgramData folders for each app\n"
            "  \u2022 HKCU registry keys for each app\n\n"
            "Incremental: re-running only copies files that are new or changed, "
            "so it\u2019s fast and safe to repeat."
        ),
        "Full Backup: Load & Install": (
            "Reinstalls all apps via winget, then automatically restores "
            "each app\u2019s AppData folders and registry keys from the folder "
            "created by Full Backup \u2192 Save.\n\n"
            "Use this after a Windows reset to get everything back exactly as it was."
        ),
        "Scan Programs": (
            "Scans your computer for programs that can actually be restored.\n\n"
            "Exact winget packages are included automatically, and Steam games "
            "are detected separately so they can be queued in Steam after the "
            "Steam client is installed. Windows built-ins and driver components "
            "are filtered out by default."
        ),
        "Select All / Deselect All": (
            "Quickly check or uncheck every program in the list.\n\n"
            "Click individual rows in the list to toggle specific programs."
        ),
        "Filter": (
            "Type to instantly filter the list by program name or install target.\n\n"
            "Useful when you have many programs and want to find a specific one."
        ),
        "Show Windows built-ins": (
            "When checked, the scan will also include Windows system apps, "
            "drivers, and Microsoft components that normally get reinstalled "
            "automatically after a reset.\n\n"
            "Usually you can leave this unchecked."
        ),
        "Setup Google Drive": (
            "Opens the Google Cloud Console in your browser so you can create "
            "your own free OAuth credentials.\n\n"
            "Steps:\n"
            "1. Create a Google Cloud project\n"
            "2. Enable the Google Drive API\n"
            "3. Create an OAuth 2.0 Client ID (Desktop app)\n"
            "4. Download the JSON file and select it when prompted\n\n"
            "This is a one-time setup. No billing is required."
        ),
        "Save to Drive": (
            "Uploads your selected app list to your Google Drive.\n\n"
            "The file is stored as 'windows_app_reinstaller_list.json' "
            "in your Drive. After a Windows reset, you can load it from "
            "any computer signed into your Google account."
        ),
        "Load from Drive & Install": (
            "Downloads your previously saved app list from Google Drive "
            "and automatically restores them. Winget apps are installed first, "
            "then Steam games are queued through Steam.\n\n"
            "Use this after a fresh Windows reset to restore your programs."
        ),
        "Save Local": (
            "Saves your selected app list as a JSON file to your computer.\n\n"
            "Save it to a USB drive or other external storage so it survives "
            "a Windows reset. You can then use 'Load Local & Install' to "
            "restore everything."
        ),
        "Load Local & Install": (
            "Opens a JSON file (previously saved with 'Save Local') and "
            "automatically restores them. Winget apps are installed first, "
            "then Steam games are queued through Steam.\n\n"
            "Point it to your USB drive or wherever you saved the file."
        ),
        "Backup Files": (
            "Opens a file browser rooted at your user profile folder.\n\n"
            "Expand folders to browse, check the ones you want to back up, "
            "then pick an external/USB drive as the destination.\n\n"
            "Use this before a Windows reset to preserve your personal files."
        ),
    }


if __name__ == "__main__":
    App().mainloop()
