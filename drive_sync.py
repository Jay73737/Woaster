"""
Google Drive sync for Windows App Reinstaller.
Handles OAuth2 authentication and file upload/download.

Users must provide their own client_secret.json from Google Cloud Console.
On first use, the app prompts them to select the file, then remembers its location.
"""

import json
import os
import shutil
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

DRIVE_FILENAME = "windows_app_reinstaller_list.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WindowsAppReinstaller"
_TOKEN_PATH = _APP_DIR / "token.json"
_CLIENT_SECRET_PATH = _APP_DIR / "client_secret.json"


def has_client_secret() -> bool:
    """Return True if the user has already provided a client_secret.json."""
    return _CLIENT_SECRET_PATH.exists()


def import_client_secret(source_path: str) -> None:
    """Copy the user's client_secret.json into the app data directory."""
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"File not found: {source_path}")
    # Validate it looks like a Google OAuth client secret
    data = json.loads(src.read_text(encoding="utf-8"))
    if "installed" not in data and "web" not in data:
        raise ValueError(
            "This doesn't look like a Google OAuth client_secret.json file.\n"
            "Download one from Google Cloud Console > APIs & Services > Credentials."
        )
    _APP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, _CLIENT_SECRET_PATH)


def authenticate() -> Credentials:
    if not _CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            "No client_secret.json configured.\n"
            "Use 'Setup Google Drive' to provide your credentials."
        )

    creds = None

    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(_CLIENT_SECRET_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

    _APP_DIR.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _get_drive_service(creds: Credentials):
    return build("drive", "v3", credentials=creds)


def _find_file_on_drive(service) -> str | None:
    query = f"name = '{DRIVE_FILENAME}' and trashed = false"
    response = service.files().list(
        q=query, spaces="drive", fields="files(id, name)", pageSize=1
    ).execute()
    files = response.get("files", [])
    return files[0]["id"] if files else None


def save_to_drive(app_list: list[dict]) -> str:
    creds = authenticate()
    service = _get_drive_service(creds)

    json_bytes = json.dumps(app_list, indent=2).encode("utf-8")
    media = MediaInMemoryUpload(json_bytes, mimetype="application/json")

    file_id = _find_file_on_drive(service)

    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
        return f"Updated '{DRIVE_FILENAME}' on Google Drive ({len(app_list)} apps)"
    else:
        metadata = {"name": DRIVE_FILENAME}
        service.files().create(body=metadata, media_body=media, fields="id").execute()
        return f"Created '{DRIVE_FILENAME}' on Google Drive ({len(app_list)} apps)"


def load_from_drive() -> list[dict]:
    creds = authenticate()
    service = _get_drive_service(creds)

    file_id = _find_file_on_drive(service)
    if not file_id:
        raise FileNotFoundError(
            f"'{DRIVE_FILENAME}' not found on Google Drive.\n"
            "Save a list first from another machine."
        )

    content = service.files().get_media(fileId=file_id).execute()
    return json.loads(content.decode("utf-8"))
