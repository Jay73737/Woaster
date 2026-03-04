"""
app_data.py -- discover, back up, and restore application data for installed programs.

Data locations checked per app:
  - %APPDATA%/<name variants>        (AppData/Roaming)
  - %LOCALAPPDATA%/<name variants>   (AppData/Local)
  - %PROGRAMDATA%/<name variants>    (ProgramData)
  - HKCU/Software/<publisher>/...   (Registry -- exported as .reg files)

A manifest.json is saved alongside the data so restore knows exactly what to
put back where.  Backups are incremental: files already present at the
destination with the same size and modification time are skipped, so re-running
a backup only copies what has changed or is new.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# ── name tokenisation ────────────────────────────────────────────────────────

_SKIP = {"the", "a", "an", "and", "or", "for", "of", "to", "by", "in", "on",
         "at", "with", "is", "it", "its", "app", "pro", "inc", "llc", "ltd"}


def _tokens(name: str, winget_id: str) -> list[str]:
    """Return meaningful lowercase tokens from display name + winget ID."""
    raw: set[str] = set()
    for text in (name, winget_id):
        for part in re.split(r"[\s\-_./\\]+", text.lower()):
            part = re.sub(r"[^a-z0-9]", "", part)
            if part and part not in _SKIP and len(part) > 2:
                raw.add(part)
    return list(raw)


def _bare_id(winget_id: str) -> str:
    for prefix in ("MSIX\\", "ARP\\Machine\\X64\\", "ARP\\Machine\\X86\\", "ARP\\Machine\\"):
        if winget_id.startswith(prefix):
            return winget_id[len(prefix):]
    return winget_id


def _publisher(winget_id: str) -> str | None:
    bid = _bare_id(winget_id)
    if "." in bid:
        return bid.split(".")[0]
    return None


# ── folder matching ──────────────────────────────────────────────────────────

def _match_dirs(base: Path, tokens: list[str], publisher: str | None) -> list[Path]:
    """Return subdirs of base whose name matches a token or the publisher."""
    if not base.exists():
        return []
    results: list[Path] = []
    seen: set[str] = set()

    candidates = list(tokens)
    if publisher:
        candidates.insert(0, publisher.lower())

    try:
        entries = list(base.iterdir())
    except PermissionError:
        return []

    for entry in entries:
        if not entry.is_dir():
            continue
        name_lower = entry.name.lower()
        name_clean = re.sub(r"[^a-z0-9]", "", name_lower)
        for tok in candidates:
            if tok in name_clean or tok in name_lower:
                key = str(entry)
                if key not in seen:
                    seen.add(key)
                    results.append(entry)
                break

    # Also search one level deeper inside a publisher subfolder
    if publisher:
        pub_dir = base / publisher
        if pub_dir.exists():
            for sub in _match_dirs(pub_dir, tokens, None):
                key = str(sub)
                if key not in seen:
                    seen.add(key)
                    results.append(sub)

    return results


# ── incremental file copy ────────────────────────────────────────────────────

_IGNORE_NAMES = {"cache", "Cache", "CachedData", "GPUCache", "Code Cache",
                 "Service Worker", "Temp", "temp"}
_IGNORE_EXTS  = {".tmp", ".log", ".lock"}


def _should_skip_file(src: Path, dst: Path) -> bool:
    """Return True if dst exists and is identical to src (size + mtime match)."""
    try:
        ss = src.stat()
        ds = dst.stat()
        # Same size AND modification time within 2 seconds (FAT32 rounding)
        return (ss.st_size == ds.st_size and
                abs(ss.st_mtime - ds.st_mtime) <= 2.0)
    except OSError:
        return False


class _CopyStats:
    __slots__ = ("copied", "skipped", "errors")
    def __init__(self):
        self.copied  = 0
        self.skipped = 0
        self.errors  = 0


def _copy_incremental(
    src: Path,
    dst: Path,
    stats: _CopyStats,
    file_cb=None,  # (src_path) -> None  called for each file actually copied
) -> None:
    """
    Recursively copy src -> dst, skipping files that are already up-to-date.
    Directories that don't exist yet are created.  Files with ignored names or
    extensions are skipped entirely.
    """
    dst.mkdir(parents=True, exist_ok=True)
    try:
        entries = list(src.iterdir())
    except PermissionError:
        return

    for entry in entries:
        # Skip noisy cache / temp entries
        if entry.name in _IGNORE_NAMES or entry.suffix in _IGNORE_EXTS:
            continue
        dst_entry = dst / entry.name
        if entry.is_symlink():
            continue
        if entry.is_dir():
            _copy_incremental(entry, dst_entry, stats, file_cb)
        else:
            if _should_skip_file(entry, dst_entry):
                stats.skipped += 1
            else:
                try:
                    shutil.copy2(entry, dst_entry)
                    stats.copied += 1
                    if file_cb:
                        file_cb(entry)
                except Exception:
                    stats.errors += 1


# ── public API ───────────────────────────────────────────────────────────────

def find_app_data(name: str, winget_id: str) -> dict:
    """
    Discover data locations for one app.  Returns:
        {
            "roaming":     [str, ...],
            "local":       [str, ...],
            "programdata": [str, ...],
            "registry":    [str, ...],   # HKCU key paths
        }
    """
    toks = _tokens(name, winget_id)
    pub  = _publisher(winget_id)

    roaming   = Path(os.environ.get("APPDATA",      ""))
    local     = Path(os.environ.get("LOCALAPPDATA", ""))
    progdata  = Path(os.environ.get("PROGRAMDATA",  ""))

    found: dict[str, list[str]] = {
        "roaming": [], "local": [], "programdata": [], "registry": []
    }

    section_map = [
        ("roaming",     roaming),
        ("local",       local),
        ("programdata", progdata),
    ]
    for section, base in section_map:
        for d in _match_dirs(base, toks, pub):
            found[section].append(str(d))

    # Registry: HKCU\Software\<publisher> and \Software\<app-name-token>
    reg_cands: set[str] = set()
    if pub:
        reg_cands.add(f"HKCU\\Software\\{pub}")
    for tok in toks[:4]:
        reg_cands.add(f"HKCU\\Software\\{tok}")

    for key in reg_cands:
        try:
            r = subprocess.run(["reg", "query", key],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                found["registry"].append(key)
        except Exception:
            pass

    return found


def backup_app_data(
    apps: list[dict],
    dest: Path,
    progress_cb=None,   # (current: int, total: int, msg: str) -> None
) -> dict:
    """
    Back up AppData + registry for every app in `apps` to `dest`.
    Incremental: files already at dest with matching size+mtime are skipped,
    so re-running only copies what has changed or is new.
    Merges with any existing manifest.json so previous entries are preserved.
    Returns the merged manifest dict and writes manifest.json inside dest.
    """
    dest.mkdir(parents=True, exist_ok=True)
    total = len(apps)

    # Load existing manifest so a resumed backup keeps previously-saved entries
    manifest_path = dest / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    section_bases = {
        "roaming":     Path(os.environ.get("APPDATA",      "")),
        "local":       Path(os.environ.get("LOCALAPPDATA", "")),
        "programdata": Path(os.environ.get("PROGRAMDATA",  "")),
    }

    all_stats = _CopyStats()

    for i, app in enumerate(apps):
        name = app["name"]
        wid  = app.get("winget_id", "")
        if progress_cb:
            progress_cb(i, total, f"Locating data for {name}…")

        data = find_app_data(name, wid)

        # Preserve any sections already recorded from a previous run
        prev      = manifest.get(name, {})
        prev_data = prev.get("data", {"roaming": [], "local": [],
                                      "programdata": [], "registry": []})
        app_manifest: dict = {
            "winget_id": wid,
            "data": {
                "roaming":     list(prev_data.get("roaming",     [])),
                "local":       list(prev_data.get("local",       [])),
                "programdata": list(prev_data.get("programdata", [])),
                "registry":    list(prev_data.get("registry",    [])),
            }
        }

        # ── copy data folders (incremental) ─────────────────────────────
        for section in ("roaming", "local", "programdata"):
            for src_str in data[section]:
                src = Path(src_str)
                if not src.exists():
                    continue
                try:
                    rel = src.relative_to(section_bases[section])
                except ValueError:
                    rel = Path(src.name)
                rel_str = str(rel)
                dst = dest / "appdata" / section / rel

                stats = _CopyStats()

                def _file_cb(p, _sec=section, _rel=rel_str, _i=i):
                    if progress_cb:
                        progress_cb(_i, total,
                                    f"Copying {p.name}  [{_sec}/{_rel}]…")

                _copy_incremental(src, dst, stats, file_cb=_file_cb)
                all_stats.copied  += stats.copied
                all_stats.skipped += stats.skipped
                all_stats.errors  += stats.errors

                if rel_str not in app_manifest["data"][section]:
                    app_manifest["data"][section].append(rel_str)

        # ── export registry keys (always re-export — cheap) ─────────────
        for reg_key in data["registry"]:
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", reg_key) + ".reg"
            reg_file  = dest / "registry" / safe_name
            reg_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                r = subprocess.run(
                    ["reg", "export", reg_key, str(reg_file), "/y"],
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0 and safe_name not in app_manifest["data"]["registry"]:
                    app_manifest["data"]["registry"].append(safe_name)
            except Exception:
                pass

        manifest[name] = app_manifest

        if progress_cb:
            progress_cb(
                i + 1, total,
                f"{name}: {all_stats.copied} new, "
                f"{all_stats.skipped} unchanged"
            )

    if progress_cb:
        progress_cb(
            total, total,
            f"Done — {all_stats.copied} files copied, "
            f"{all_stats.skipped} skipped (already up-to-date), "
            f"{all_stats.errors} errors"
        )

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def restore_app_data(
    backup_root: Path,
    progress_cb=None,   # (current: int, total: int, msg: str) -> None
) -> list[str]:
    """
    Restore app data from a backup created by backup_app_data.
    Returns a list of error strings (empty = all good).
    """
    manifest_path = backup_root / "manifest.json"
    if not manifest_path.exists():
        return ["manifest.json not found — is this a valid full backup folder?"]

    manifest: dict = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    total = len(manifest)

    section_bases = {
        "roaming":     Path(os.environ.get("APPDATA",      "")),
        "local":       Path(os.environ.get("LOCALAPPDATA", "")),
        "programdata": Path(os.environ.get("PROGRAMDATA",  "")),
    }

    for i, (app_name, info) in enumerate(manifest.items()):
        if progress_cb:
            progress_cb(i, total, f"Restoring data for {app_name}…")

        app_data = info.get("data", {})

        # ── restore data folders (incremental) ──────────────────────────
        for section, base in section_bases.items():
            for rel_str in app_data.get(section, []):
                src = backup_root / "appdata" / section / rel_str
                dst = base / rel_str
                if not src.exists():
                    continue
                try:
                    stats = _CopyStats()
                    _copy_incremental(src, dst, stats)
                except Exception as e:
                    errors.append(f"{app_name} / {section} / {rel_str}: {e}")

        # ── import registry ──────────────────────────────────────────────
        for reg_name in app_data.get("registry", []):
            reg_file = backup_root / "registry" / reg_name
            if not reg_file.exists():
                continue
            try:
                subprocess.run(["reg", "import", str(reg_file)],
                               capture_output=True, text=True, timeout=10)
            except Exception as e:
                errors.append(f"{app_name} / registry / {reg_name}: {e}")

    if progress_cb:
        progress_cb(total, total, "App data restore complete.")

    return errors
