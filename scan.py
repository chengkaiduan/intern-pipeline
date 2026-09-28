#!/usr/bin/env python3
"""Pull SimplifyJobs listings.json and filter it down to tonight's candidates.

Deterministic: no model calls. Writes candidates.json plus per-stage counts to stderr so a
zero-candidate night is explainable from the log.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

import yaml

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
# Simplify's shorthand for common hubs, plus spelled-out forms that carry no state.
US_CITY_WORDS = {
    "nyc", "sf", "san francisco", "new york", "seattle", "austin", "boston", "chicago", "los angeles",
    "la", "bay area", "silicon valley", "washington", "denver", "atlanta", "dallas", "houston", "miami",
    "philadelphia", "phoenix", "san diego", "san jose", "portland", "pittsburgh", "minneapolis",
    "detroit", "raleigh", "durham", "nashville", "salt lake city", "las vegas", "united states", "usa",
    "u.s.", "us",
}
NON_US_MARKERS = re.compile(
    r"\b(uk|united kingdom|london|canada|toronto|vancouver|montreal|ontario|india|bangalore|bengaluru|"
    r"hyderabad|singapore|australia|sydney|germany|berlin|munich|france|paris|ireland|dublin|"
    r"netherlands|amsterdam|israel|tel aviv|japan|tokyo|china|shanghai|beijing|shenzhen|hong kong|"
    r"taiwan|taipei|korea|seoul|mexico|brazil|poland|warsaw|spain|madrid|switzerland|zurich|sweden|"
    r"stockholm|denmark|copenhagen|uae|dubai|nigeria|kenya|south africa|new zealand|philippines|"
    r"vietnam|thailand|indonesia|malaysia|argentina|chile|colombia|portugal|lisbon|italy|milan|"
    r"austria|vienna|belgium|brussels|czech|prague|hungary|budapest|romania|finland|helsinki|norway|oslo)\b",
    re.I,
)
REMOTE = re.compile(r"\bremote\b", re.I)


def load_config(path="config.yaml") -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def _is_us(loc: str) -> bool:
    s = loc.strip()
    if not s or NON_US_MARKERS.search(s):
        return False
    low = s.lower()
    if low in US_CITY_WORDS:
        return True
    parts = [p.strip() for p in s.split(",")]
    if any(p.upper() in US_STATES for p in parts):
        return True
    if any(p.lower() in US_CITY_WORDS for p in parts):
        return True
    # "Palo Alto, CA 94301" or "New York City"
    if re.search(r"\b[A-Z]{2}\b\s*\d{5}", s):
        return True
    return any(w in low for w in ("new york", "san francisco", "los angeles", "united states"))


def is_us_in_person(locations: list[str]) -> bool:
    """True when at least one location is a physical US place (remote-only listings fail)."""
    for loc in locations or []:
        if REMOTE.search(loc):
            continue
        if _is_us(loc):
            return True
    return False


def title_excluded(title: str, pattern: str) -> bool:
    return re.search(pattern, title or "", re.I) is not None


def degrees_ok(degrees: list[str]) -> bool:
    if not degrees:
        return True
    return any("bachelor" in d.lower() for d in degrees)


def slug_for(row: dict) -> str:
    base = f"{row.get('company_name', '')} {row.get('title', '')}".lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    base = base[:70].rstrip("-")
    tail = str(row.get("id", ""))[-6:]
    return f"{base}-{tail}"


def filter_listings(rows, cfg, seen: set, since_ts: int, now_ts: int):
    """Return (candidates, counts). since_ts is clamped to [now - window_max, now - window_min]."""
    win_max = int(cfg.get("window_hours_max", 72)) * 3600
    win_min = int(cfg.get("window_hours_min", 24)) * 3600
    since = max(since_ts, now_ts - win_max)
    since = min(since, now_ts - win_min)
    cats = set(cfg.get("categories", []))
    pat = cfg.get("title_exclude_regex", r"$^")
    counts = {
        "total": len(rows), "dropped_inactive": 0, "dropped_category": 0, "dropped_window": 0,
        "dropped_seen": 0, "dropped_location": 0, "dropped_title": 0, "dropped_degrees": 0, "kept": 0,
    }
    out = []
    for r in rows:
        if not r.get("active", False):
            counts["dropped_inactive"] += 1
            continue
        if r.get("category") not in cats:
            counts["dropped_category"] += 1
            continue
        if int(r.get("date_posted", 0)) < since:
            counts["dropped_window"] += 1
            continue
        if r.get("id") in seen:
            counts["dropped_seen"] += 1
            continue
        if not is_us_in_person(r.get("locations") or []):
            counts["dropped_location"] += 1
            continue
        if title_excluded(r.get("title", ""), pat):
            counts["dropped_title"] += 1
            continue
        if not degrees_ok(r.get("degrees") or []):
            counts["dropped_degrees"] += 1
            continue
        counts["kept"] += 1
        out.append({
            "id": r["id"],
            "slug": slug_for(r),
            "company": r.get("company_name", ""),
            "title": r.get("title", ""),
            "locations": r.get("locations") or [],
            "category": r.get("category", ""),
            "url": r.get("url", ""),
            "date_posted": int(r.get("date_posted", 0)),
            "degrees": r.get("degrees") or [],
            "terms": r.get("terms") or [],
            "sponsorship": r.get("sponsorship", ""),
        })
    out.sort(key=lambda c: -c["date_posted"])
    return out, counts


def _ssl_ctx():
    """Framework Python on this Mac ships no CA bundle; use certifi's when available."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_listings(url: str, min_rows: int) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "intern-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp:
        data = json.load(resp)
    if not isinstance(data, list) or len(data) < min_rows:
        raise SystemExit(f"listings feed looks broken: {type(data).__name__} with {len(data) if hasattr(data, '__len__') else '?'} rows (< {min_rows})")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seen", default="state/seen.json")
    ap.add_argument("--since-hours", type=float, default=None, help="override lookback (still clamped)")
    ap.add_argument("--last-run-file", default="state/last_success.txt")
    args = ap.parse_args(argv)

    cfg = load_config(args.config) if args.config != "config.yaml" else __import__("settings").settings(require_profile=False)
    now = int(time.time())
    if args.since_hours is not None:
        since = now - int(args.since_hours * 3600)
    else:
        try:
            since = int(Path(args.last_run_file).read_text().strip())
        except (FileNotFoundError, ValueError):
            since = now - int(cfg.get("window_hours_min", 24)) * 3600
    try:
        seen = set(json.loads(Path(args.seen).read_text()))
    except FileNotFoundError:
        seen = set()

    rows = fetch_listings(cfg["listings_url"], int(cfg.get("min_listing_rows", 1000)))
    cands, counts = filter_listings(rows, cfg, seen, since, now)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(cands, indent=1))
    print(json.dumps({"since": since, "now": now, **counts}), file=sys.stderr)
    print(f"wrote {len(cands)} candidates to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # fail loudly with a one-line reason for run.sh
        print(f"scan.py FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
