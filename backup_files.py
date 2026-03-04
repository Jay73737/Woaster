"""
Backup Files window — browse the user profile folder tree and copy
selected folders/files to an external drive before a Windows reset.
"""

import os
import shutil
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path


def _format_size(size: int) -> str:
    """Human-readable size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} PB"


def _get_folder_size(path: Path) -> int:
    """Recursively sum file sizes. Skips inaccessible entries."""
    total = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


class BackupWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Backup Files")
        self.geometry("900x650")
        self.minsize(700, 450)

        self.root_path = Path.home()
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self._populated: set[str] = set()
        self._sizes: dict[str, int | None] = {}

        self.overrideredirect(True)
        self._drag_x = 0
        self._drag_y = 0
        self._build_ui()
        self._populate_root()
        self.lift()
        self.focus_force()

    # ── layout ──────────────────────────────────────────────────────────

    def _build_ui(self):
        _BG     = "#1e1e1e"
        _TB     = "#2d2d2d"
        _FG     = "#d4d4d4"
        _BORDER = "#3c3c3c"

        # Outer 1-px border frame
        outer = tk.Frame(self, bg=_BORDER)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Custom title bar
        tb = tk.Frame(inner, bg=_TB, height=32)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="Backup Files", bg=_TB, fg=_FG,
                 font=("Segoe UI", 10), anchor="w", padx=10).pack(side="left", fill="y")
        close_btn = tk.Label(tb, text="✕", bg=_TB, fg=_FG,
                             font=("Segoe UI", 11), width=4, cursor="hand2", anchor="center")
        close_btn.pack(side="right")
        close_btn.bind("<Enter>",           lambda _: close_btn.config(bg="#c0392b"))
        close_btn.bind("<Leave>",           lambda _: close_btn.config(bg=_TB))
        close_btn.bind("<ButtonRelease-1>", lambda _: self.destroy())
        tb.bind("<ButtonPress-1>",  self._drag_start)
        tb.bind("<B1-Motion>",       self._drag_move)

        # Top bar: source + destination picker
        top = ttk.Frame(inner)
        top.pack(fill="x", padx=8, pady=(8, 4))

        # Row 1: source folder
        src_row = ttk.Frame(top)
        src_row.pack(fill="x", pady=(0, 4))
        ttk.Label(src_row, text="Source:").pack(side="left")
        self.src_var = tk.StringVar(value=str(self.root_path))
        ttk.Entry(src_row, textvariable=self.src_var, width=50, state="readonly").pack(side="left", padx=4)
        ttk.Button(src_row, text="Change...", command=self._pick_source).pack(side="left", padx=2)

        # Row 2: destination folder
        dst_row = ttk.Frame(top)
        dst_row.pack(fill="x")
        ttk.Label(dst_row, text="Destination:").pack(side="left")
        self.dest_var = tk.StringVar()
        ttk.Entry(dst_row, textvariable=self.dest_var, width=50).pack(side="left", padx=4)
        ttk.Button(dst_row, text="Browse...", command=self._pick_destination).pack(side="left", padx=2)
        ttk.Button(dst_row, text="Start Backup", command=self._on_start_backup).pack(side="right", padx=2)

        # Treeview
        container = ttk.Frame(inner)
        container.pack(fill="both", expand=True, padx=8, pady=4)

        self.tree = ttk.Treeview(
            container,
            columns=("checked", "size"),
            show="tree headings",
            selectmode="none",
        )
        self.tree.heading("#0", text="Name", anchor="w")
        self.tree.heading("checked", text="Select")
        self.tree.heading("size", text="Size")
        self.tree.column("#0", width=500, stretch=True)
        self.tree.column("checked", width=60, anchor="center", stretch=False)
        self.tree.column("size", width=100, anchor="e", stretch=False)

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewOpen>>", self._on_expand)
        self.tree.bind("<ButtonRelease-1>", self._on_click)

        # Progress bar + status
        bottom = ttk.Frame(inner)
        bottom.pack(fill="x", padx=8, pady=(0, 8))

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x", pady=(4, 2))

        self.status_var = tk.StringVar(value="Select folders to back up, then pick a destination.")
        ttk.Label(bottom, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x")
        self.eta_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.eta_var, anchor="e").pack(fill="x")

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def _pick_source(self):
        folder = filedialog.askdirectory(title="Select source folder to browse",
                                         initialdir=str(self.root_path))
        if not folder:
            return
        self.root_path = Path(folder)
        self.src_var.set(str(self.root_path))
        self._reload_root()

    def _reload_root(self):
        """Clear the tree and repopulate from self.root_path."""
        self.tree.delete(*self.tree.get_children())
        self.check_vars.clear()
        self._populated.clear()
        self._sizes.clear()
        self._populate_root()

    # ── tree population (lazy) ──────────────────────────────────────────

    def _populate_root(self):
        root_iid = str(self.root_path)
        self.tree.insert("", "end", iid=root_iid, text=self.root_path.name,
                         values=("\u2610", ""), open=True)
        self.check_vars[root_iid] = tk.BooleanVar(value=False)
        self._populate_children(root_iid)

    def _populate_children(self, parent_iid: str):
        if parent_iid in self._populated:
            return
        self._populated.add(parent_iid)

        # Remove dummy child
        for child in self.tree.get_children(parent_iid):
            if self.tree.item(child, "text") == "":
                self.tree.delete(child)

        parent_path = Path(parent_iid)
        try:
            entries = sorted(parent_path.iterdir(),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            iid = str(entry)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            self.check_vars[iid] = tk.BooleanVar(value=False)

            if is_dir:
                self.tree.insert(parent_iid, "end", iid=iid, text=entry.name,
                                 values=("\u2610", "..."))
                # Dummy child so the expand arrow appears
                self.tree.insert(iid, "end", text="")
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                self.tree.insert(parent_iid, "end", iid=iid, text=entry.name,
                                 values=("\u2610", _format_size(size)))
                self._sizes[iid] = size

    def _on_expand(self, event):
        iid = self.tree.focus()
        if not iid:
            return
        self._populate_children(iid)
        self._calc_size_async(iid)

    # ── size calculation ────────────────────────────────────────────────

    def _calc_size_async(self, iid: str):
        def _calc():
            total = _get_folder_size(Path(iid))
            self._sizes[iid] = total
            self.after(0, lambda: self._update_size_display(iid, total))
        threading.Thread(target=_calc, daemon=True).start()

    def _update_size_display(self, iid: str, size: int):
        if self.tree.exists(iid):
            vals = list(self.tree.item(iid, "values"))
            vals[1] = _format_size(size)
            self.tree.item(iid, values=vals)

    # ── checkbox toggling ───────────────────────────────────────────────

    def _on_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        col = self.tree.identify_column(event.x)
        if region != "cell" or col != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self.check_vars:
            return
        new_val = not self.check_vars[iid].get()
        self._set_checked(iid, new_val)

    def _set_checked(self, iid: str, checked: bool):
        self.check_vars[iid].set(checked)
        symbol = "\u2611" if checked else "\u2610"
        vals = list(self.tree.item(iid, "values"))
        vals[0] = symbol
        self.tree.item(iid, values=vals)
        # Propagate to loaded children
        for child in self.tree.get_children(iid):
            if child in self.check_vars:
                self._set_checked(child, checked)

    # ── destination ─────────────────────────────────────────────────────

    def _pick_destination(self):
        path = filedialog.askdirectory(
            title="Select backup destination (USB / external drive)",
            parent=self,
        )
        if path:
            self.dest_var.set(path)

    def _validate_destination(self) -> Path | None:
        dest = self.dest_var.get().strip()
        if not dest:
            messagebox.showwarning("No Destination",
                                   "Pick a destination folder first.", parent=self)
            return None

        dest_path = Path(dest)
        if not dest_path.exists():
            messagebox.showerror("Invalid Path",
                                 f"Destination does not exist:\n{dest}", parent=self)
            return None

        win_drive = os.environ.get("SystemDrive", "C:").upper()
        dest_drive = dest_path.resolve().drive.upper()
        if dest_drive == win_drive:
            messagebox.showwarning(
                "Same Drive as Windows",
                f"The destination is on {dest_drive}\\, which is the Windows drive.\n\n"
                "Please select an external or USB drive.",
                parent=self,
            )
            return None

        return dest_path

    # ── backup execution ────────────────────────────────────────────────

    def _get_selected_paths(self) -> list[Path]:
        result: list[Path] = []
        self._collect_checked(str(self.root_path), result)
        return result

    def _collect_checked(self, parent_iid: str, result: list[Path]):
        for iid in self.tree.get_children(parent_iid):
            if iid not in self.check_vars:
                continue
            if not self.check_vars[iid].get():
                continue

            path = Path(iid)
            is_dir = path.is_dir()

            if is_dir and iid not in self._populated:
                # Folder checked but never expanded — take it all
                result.append(path)
            elif is_dir:
                # Check if all loaded children are checked
                children = self.tree.get_children(iid)
                all_checked = all(
                    self.check_vars.get(c, tk.BooleanVar(value=False)).get()
                    for c in children if c in self.check_vars
                )
                if all_checked:
                    result.append(path)
                else:
                    self._collect_checked(iid, result)
            else:
                result.append(path)

    def _on_start_backup(self):
        dest = self._validate_destination()
        if dest is None:
            return

        selected = self._get_selected_paths()
        if not selected:
            messagebox.showwarning("Nothing Selected",
                                   "Check at least one folder or file.", parent=self)
            return

        msg = f"{len(selected)} items selected for backup.\n\nProceed?"
        if not messagebox.askyesno("Confirm Backup", msg, parent=self):
            return

        self.status_var.set("Counting files...")
        self.update_idletasks()

        def _do_backup():
            # Count total bytes
            total_bytes = 0
            for p in selected:
                if p.is_file():
                    try:
                        total_bytes += p.stat().st_size
                    except OSError:
                        pass
                elif p.is_dir():
                    total_bytes += _get_folder_size(p)
            if total_bytes == 0:
                total_bytes = 1

            self.after(0, lambda: (
                self.progress.configure(maximum=total_bytes, value=0),
                self.eta_var.set(""),
            ))

            state = {"bytes": 0, "files": 0, "start": time.monotonic()}
            errors: list[str] = []
            backup_root = dest / f"Backup_{self.root_path.name}"

            def _update_ui():
                elapsed = time.monotonic() - state["start"]
                b = state["bytes"]
                self.progress.configure(value=min(b, total_bytes))
                pct = min(100.0, b / total_bytes * 100)
                if elapsed > 1 and b > 0:
                    eta_secs = int((total_bytes - b) / (b / elapsed))
                    h, rem = divmod(eta_secs, 3600)
                    m, s = divmod(rem, 60)
                    if h:
                        eta_str = f"ETA: {h}h {m}m {s}s"
                    elif m:
                        eta_str = f"ETA: {m}m {s}s"
                    else:
                        eta_str = f"ETA: {s}s"
                else:
                    eta_str = "ETA: calculating..."
                self.status_var.set(
                    f"Copied {state['files']} files  •  "
                    f"{_format_size(b)} / {_format_size(total_bytes)}  ({pct:.1f}%)"
                )
                self.eta_var.set(eta_str)

            def _copy_file(src: Path, dst: Path):
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                try:
                    state["bytes"] += src.stat().st_size
                except OSError:
                    pass
                state["files"] += 1
                if state["files"] % 10 == 0:
                    self.after(0, _update_ui)

            for src_path in selected:
                try:
                    rel = src_path.relative_to(self.root_path)
                except ValueError:
                    rel = Path(src_path.name)
                dst = backup_root / rel

                try:
                    if src_path.is_file():
                        _copy_file(src_path, dst)
                    elif src_path.is_dir():
                        for f in src_path.rglob("*"):
                            try:
                                if f.is_file(follow_symlinks=False):
                                    rel_f = f.relative_to(src_path)
                                    _copy_file(f, dst / rel_f)
                            except OSError:
                                pass
                except Exception as e:
                    errors.append(f"{src_path.name}: {e}")

            final_files = state["files"]
            final_bytes = state["bytes"]

            def _show_done():
                self.progress.configure(value=total_bytes)
                self.eta_var.set("")
                if errors:
                    self.status_var.set(f"Done with {len(errors)} error(s) — {final_files} files copied.")
                    messagebox.showwarning(
                        "Backup Complete (with errors)",
                        f"Copied {final_files} files ({_format_size(final_bytes)}) to:\n{backup_root}\n\n"
                        f"Errors ({len(errors)}):\n" + "\n".join(errors[:10]),
                        parent=self,
                    )
                else:
                    self.status_var.set(f"Backup complete — {final_files} files ({_format_size(final_bytes)}) copied.")
                    messagebox.showinfo(
                        "Backup Complete",
                        f"Successfully copied {final_files} files ({_format_size(final_bytes)}) to:\n{backup_root}",
                        parent=self,
                    )

            self.after(0, _show_done)

        threading.Thread(target=_do_backup, daemon=True).start()
