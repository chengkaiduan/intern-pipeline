#!/usr/bin/env python3
"""Upload tonight's PDFs to the 'Internship Pipeline Resumes' Drive folder (date subfolder).

Service-account auth, raw Drive v3 REST via google-auth AuthorizedSession. Adds `drive_url` to
each pick with a PDF. Deterministic, no model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from settings import settings

SCOPES = ["https://www.googleapis.com/auth/drive"]
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink&supportsAllDrives=true"


ADC = Path.home() / ".config/gcloud/application_default_credentials.json"


def session(sa_key: str):
    """Service accounts have no Drive storage quota (uploads 403), so uploads need a real user's
    OAuth credentials (application-default credentials with the drive scope; Google blocks gcloud's
    default client for that scope, so you need your own OAuth client — see setup/google.md).
    Falls back to the service account if ADC is absent, which only works on a Shared Drive."""
    from google.auth.transport.requests import AuthorizedSession
    if ADC.exists():
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(ADC), scopes=SCOPES)
        return AuthorizedSession(creds)
    from google.oauth2 import service_account
    print("drive_upload: no user ADC at ~/.config/gcloud/application_default_credentials.json; "
          "run `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/drive,"
          "https://www.googleapis.com/auth/cloud-platform` (uploads will 403 until then)", file=sys.stderr)
    creds = service_account.Credentials.from_service_account_file(str(Path(sa_key).expanduser()), scopes=SCOPES)
    return AuthorizedSession(creds)


def ensure_subfolder(s, parent_id: str, name: str) -> str:
    q = f"name = '{name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    r = s.get(f"{API}/files", params={"q": q, "fields": "files(id)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
    r.raise_for_status()
    files = r.json().get("files", [])
    if files:
        return files[0]["id"]
    r = s.post(f"{API}/files", params={"supportsAllDrives": "true"},
               json={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]})
    r.raise_for_status()
    return r.json()["id"]


def upload_pdf(s, folder_id: str, path: Path) -> str:
    meta = json.dumps({"name": path.name, "parents": [folder_id]})
    files = {
        "metadata": ("metadata", meta, "application/json; charset=UTF-8"),
        "file": (path.name, path.read_bytes(), "application/pdf"),
    }
    r = s.post(UPLOAD, files=files)
    r.raise_for_status()
    return r.json()["webViewLink"]


def upload_picks(s, picks: dict, root_folder: str) -> int:
    sub = ensure_subfolder(s, root_folder, picks["date"])
    picks["drive_folder_url"] = f"https://drive.google.com/drive/folders/{sub}"
    n = 0
    for p in picks.get("picks", []):
        pdf = p.get("pdf")
        if not pdf or not Path(pdf).exists() or p.get("drive_url"):
            continue
        try:
            p["drive_url"] = upload_pdf(s, sub, Path(pdf))
            n += 1
        except Exception as e:  # one bad upload must not sink the night
            p["drive_error"] = f"{type(e).__name__}: {e}"[:200]
            print(f"upload failed {Path(pdf).name}: {p['drive_error']}", file=sys.stderr)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", required=True)
    args = ap.parse_args(argv)
    cfg = settings()
    if not cfg.get("drive_folder_id"):
        print("drive_upload: disabled (profile.yaml drive_folder_id empty); email links local paths", file=sys.stderr)
        return 0
    picks_path = Path(args.picks)
    picks = json.loads(picks_path.read_text())
    s = session(cfg.get("sa_key", "secrets/sa.json"))
    n = upload_picks(s, picks, cfg["drive_folder_id"])
    picks_path.write_text(json.dumps(picks, indent=1))
    print(json.dumps({"drive_uploaded": n, "folder": picks.get("drive_folder_url")}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"drive_upload.py FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
