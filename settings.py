"""Merged settings: config.yaml (shared, committed) + profile.yaml (yours, gitignored).

Every script calls settings() and reads one dict. profile.yaml keys override config.yaml keys.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.yaml"
PROFILE = ROOT / "profile.yaml"
PROFILE_EXAMPLE = ROOT / "profile.example.yaml"

REQUIRED = ("name", "pdf_prefix", "email_to", "summary")


def _load(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def settings(require_profile: bool = True) -> dict:
    cfg = _load(CONFIG)
    if PROFILE.exists():
        cfg.update(_load(PROFILE))
    elif require_profile:
        sys.exit(f"profile.yaml not found. Copy {PROFILE_EXAMPLE.name} to profile.yaml and fill it in.")
    if require_profile:
        missing = [k for k in REQUIRED if not cfg.get(k)]
        if missing:
            sys.exit(f"profile.yaml is missing required keys: {', '.join(missing)}")
    cfg["root"] = str(ROOT)
    cfg["resume_dir"] = str((ROOT / cfg.get("resume_dir", "resume")).resolve())
    cfg["jobs_root"] = str(Path(cfg["resume_dir"]) / "jobs")
    return cfg


if __name__ == "__main__":
    import json
    s = settings()
    s.pop("summary", None)
    print(json.dumps(s, indent=1, default=str))
