# Woaster

**Wind<u>O</u>ws <u>A</u>pp rein<u>ST</u>all<u>ER</u>**

A dark-themed desktop tool for backing up your installed programs and files before a Windows reset, then restoring everything automatically afterwards.

---

## Features

- **Scan Programs** — detects all winget-installable apps on your machine, filtering out built-in Windows components
- **Save / Load via Google Drive** — store your app list in the cloud so it survives a wipe and can be loaded on any PC
- **Save / Load Locally** — export your list to a JSON file on a USB drive or external storage
- **One-click Reinstall** — loads a saved list and reinstalls every app via `winget` automatically
- **Backup Files** — browse your user profile folder, select folders to back up, and copy them to an external drive
- **Full Save Local** — saves the app list *and* each app's AppData folders (Roaming, Local, ProgramData) plus HKCU registry keys to a folder you choose; **incremental** — re-running only copies files that are new or have changed
- **Full Load & Install** — reinstalls all apps via winget then automatically restores AppData and registry from a previous Full Save
- **Dark mode UI** throughout

---

## Usage

### Before a Windows reset

1. Launch `Woaster.exe`
2. Click **Scan Programs** to detect installed apps
3. Uncheck anything you don't want to restore
4. Save your list:
   - **Save to Drive** — uploads to your Google Drive (requires one-time setup, see below)
   - **Save Local** — saves a `app_list.json` file; put it on a USB drive
   - **Full Save Local** — saves the app list **and** all app data to a folder on an external drive (incremental; safe to re-run)
5. Click **Backup Files**, select important folders, and copy them to an external drive

### After a Windows reset

1. Launch `Woaster.exe` on the fresh install
2. Restore your apps:
   - **Load from Drive & Install** — downloads your list from Google Drive and installs everything
   - **Load Local & Install** — point it to your saved JSON file and it installs everything
   - **Full Load & Install** — point it to the folder created by Full Save; reinstalls all apps *and* restores their AppData and registry

---

## Google Drive Setup (one-time)

1. Click **Setup Google Drive** — your browser will open to the Google Cloud Console
2. Create a project (or select an existing one)
3. Enable the **Google Drive API**
4. Go to **APIs & Services → Credentials** and create an **OAuth 2.0 Client ID** (type: Desktop app)
5. Download the `client_secret.json` file
6. Select it in the dialog that appears in Woaster

No billing is required. The file is stored as `windows_app_reinstaller_list.json` in your Drive root.

---

## Download

**[Woaster.exe](Woaster.exe)**

| Property | Value |
|---|---|
| Version | 1.0.0 |
| Size | ~33 MB |
| MD5 | `DE2885B6277E2762B050DE34E310185C` |

You can verify the integrity of the download by running:
```powershell
Get-FileHash Woaster.exe -Algorithm MD5
```

---

## Requirements

- Windows 10 (1809+) or Windows 11
- [winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/) (included with modern Windows)

---

## Building from source

```powershell
# Install dependencies
pip install pyinstaller google-api-python-client google-auth-oauthlib

# Build
pyinstaller app.spec
```

Output: `dist\Woaster.exe`
