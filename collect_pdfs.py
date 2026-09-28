#!/usr/bin/env python3
"""Copy tonight's labeled PDFs into <desktop_folder>/<date>/ so one folder holds the day's resumes."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from settings import settings

DEST_ROOT = Path.home() / "Desktop" / "Internship Resumes"


def collect(picks: dict, dest_root: Path = DEST_ROOT) -> Path:
    day = dest_root / picks["date"]
    day.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in picks.get("picks", []):
        src = Path(p["pdf"]) if p.get("pdf") else None
        if src and src.exists():
            shutil.copy2(src, day / src.name)
            n += 1
    picks["desktop_folder"] = str(day)
    print(json.dumps({"collected": n, "folder": str(day)}), file=sys.stderr)
    return day


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", required=True)
    args = ap.parse_args(argv)
    path = Path(args.picks)
    picks = json.loads(path.read_text())
    cfg = settings()
    collect(picks, Path(cfg.get("desktop_folder") or DEST_ROOT).expanduser())
    path.write_text(json.dumps(picks, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
