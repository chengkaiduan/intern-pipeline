#!/usr/bin/env python3
"""Instagram stories as a job source (default account: zero2sudo).

Stories expire after 24h and highlights persist; both are read through Instagram's web API using
your own logged-in session cookies (secrets/instagram_cookies.json, see setup/instagram.md).
Link stickers give posting URLs directly. Image-only stories are downloaded and, unless
--no-model is passed, read by one `claude -p` call that extracts company / role / URL.

Output: candidate dicts in the same shape scan.py produces, tagged source="zero2sudo", merged
into an existing candidates.json with --merge. Never fatal to the night: any failure prints a
one-line reason and exits 0 with no candidates.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from settings import settings  # noqa: E402

APP_ID = "936619743392459"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")
COOKIE_FILE = ROOT / "secrets" / "instagram_cookies.json"


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class IGError(Exception):
    pass


def load_cookies(path: Path = COOKIE_FILE) -> dict:
    """secrets/instagram_cookies.json: {"sessionid": "...", "csrftoken": "...", "ds_user_id": "..."}.
    Falls back to decrypting Chrome's cookie jar (needs Keychain approval once)."""
    if path.exists():
        c = json.loads(path.read_text())
        if c.get("sessionid"):
            return c
    try:
        import browser_cookie3
        jar = browser_cookie3.chrome(domain_name="instagram.com")
        c = {ck.name: ck.value for ck in jar if ck.name in ("sessionid", "csrftoken", "ds_user_id", "mid", "ig_did")}
        if c.get("sessionid"):
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(c))
            return c
    except Exception as e:  # noqa: BLE001
        raise IGError(f"no instagram cookies: {type(e).__name__}: {str(e)[:120]}")
    raise IGError("no instagram cookies (secrets/instagram_cookies.json missing)")


def api(path: str, cookies: dict) -> dict:
    url = "https://www.instagram.com" + path
    hdr = {
        "User-Agent": UA, "x-ig-app-id": APP_ID, "x-requested-with": "XMLHttpRequest",
        "x-csrftoken": cookies.get("csrftoken", ""), "Referer": "https://www.instagram.com/",
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=40, context=_ctx()) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    if data.get("status") not in (None, "ok"):
        raise IGError(f"api {path}: {str(data)[:200]}")
    return data


def user_id(username: str, cookies: dict) -> str:
    d = api(f"/api/v1/users/web_profile_info/?username={username}", cookies)
    uid = (d.get("data") or {}).get("user", {}).get("id")
    if not uid:
        raise IGError(f"could not resolve user id for {username} (logged out?)")
    return uid


def unwrap_link(u: str) -> str:
    """l.instagram.com/?u=<encoded>&e=... → the real URL."""
    p = urllib.parse.urlparse(u)
    if p.netloc.endswith("l.instagram.com"):
        q = urllib.parse.parse_qs(p.query).get("u")
        if q:
            return q[0]
    return u


def story_items(uid: str, cookies: dict, include_highlights: bool, since_ts: int) -> list[dict]:
    items = []
    d = api(f"/api/v1/feed/reels_media/?reel_ids={uid}", cookies)
    for reel in (d.get("reels") or {}).values():
        items += reel.get("items") or []
    if include_highlights:
        tray = api(f"/api/v1/highlights/{uid}/highlights_tray/", cookies)
        ids = [t["id"] for t in tray.get("tray") or [] if str(t.get("id", "")).startswith("highlight:")]
        for i in range(0, len(ids), 5):
            d = api("/api/v1/feed/reels_media/?" + "&".join(f"reel_ids={urllib.parse.quote(x)}" for x in ids[i:i + 5]), cookies)
            for reel in (d.get("reels") or {}).values():
                items += reel.get("items") or []
    seen, out = set(), []
    for it in items:
        pk = str(it.get("pk") or it.get("id"))
        if pk in seen or int(it.get("taken_at", 0)) < since_ts:
            continue
        seen.add(pk)
        links = [unwrap_link(s["story_link"]["url"]) for s in it.get("story_link_stickers") or [] if s.get("story_link", {}).get("url")]
        img = ((it.get("image_versions2") or {}).get("candidates") or [{}])[0].get("url")
        out.append({"pk": pk, "taken_at": int(it.get("taken_at", 0)), "links": links, "image": img,
                    "caption": it.get("accessibility_caption") or ""})
    return out


def download(url: str, dest: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40, context=_ctx()) as r:
        dest.write_bytes(r.read())
    return dest


EXTRACT_PROMPT = """Each image below is an Instagram story screenshot from an account that reposts internship
openings. For every image, read it and extract the job(s) it shows. Answer with ONLY a JSON array:

[{"file": "<image file name>", "company": "...", "title": "...", "location": "...", "term": "...",
  "url": "<application URL if visible in the image, else empty string>"}]

One object per job; skip images that show no job posting (memes, announcements). Use "" for
anything not visible. Do not guess URLs.

Images:
"""


def extract_with_model(images: list[Path]) -> list[dict]:
    prompt = EXTRACT_PROMPT + "\n".join(str(p) for p in images) + \
        "\n\nRead each file with the Read tool, then answer with the JSON array only."
    res = subprocess.run(["claude", "-p", "--dangerously-skip-permissions", "--output-format", "text"],
                         input=prompt, capture_output=True, text=True, timeout=600)
    m = re.search(r"\[.*\]", res.stdout, re.S)
    if not m:
        raise IGError("model returned no JSON array")
    return json.loads(m.group(0))


def to_candidates(stories: list[dict], extracted: list[dict], username: str) -> list[dict]:
    by_file = {}
    for e in extracted:
        by_file.setdefault(e.get("file", ""), []).append(e)
    out = []
    for s in stories:
        exts = by_file.get(f"{s['pk']}.jpg", []) or by_file.get(s.get("_file", ""), [])
        story_url = f"https://www.instagram.com/stories/{username}/{s['pk']}/"
        links = [l for l in s["links"] if not re.search(r"instagram\.com|linktr\.ee|discord\.gg", l)]
        if not exts and not links:
            continue
        if not exts:
            exts = [{"company": "", "title": "", "location": "", "term": ""}]
        for j, e in enumerate(exts):
            url = e.get("url") or (links[j] if j < len(links) else (links[0] if links else story_url))
            company = e.get("company") or urllib.parse.urlparse(url).netloc.replace("www.", "").split(".")[0].title()
            title = e.get("title") or "Internship (see story)"
            slug = re.sub(r"[^a-z0-9]+", "-", f"{company} {title}".lower()).strip("-")[:70] + f"-ig{s['pk'][-6:]}"
            out.append({
                "id": f"ig-{s['pk']}-{j}", "slug": slug, "company": company, "title": title,
                "locations": [e.get("location")] if e.get("location") else ["United States"],
                "category": "Software", "url": url, "date_posted": s["taken_at"], "degrees": [],
                "terms": [e["term"]] if e.get("term") else [], "sponsorship": "",
                "source": f"instagram:{username}", "story_url": story_url,
            })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default=None)
    ap.add_argument("--since-hours", type=float, default=48)
    ap.add_argument("--no-highlights", action="store_true")
    ap.add_argument("--no-model", action="store_true", help="link stickers only; do not read images")
    ap.add_argument("--work-dir", default="state/ig")
    ap.add_argument("--merge", default=None, help="candidates.json to append into (dedupes by id/url)")
    ap.add_argument("--out", default=None, help="write candidates here (default: print count)")
    args = ap.parse_args(argv)

    cfg = settings(require_profile=False)
    username = args.username or cfg.get("instagram_source") or "zero2sudo"
    try:
        cookies = load_cookies()
        uid = user_id(username, cookies)
        since = int(time.time() - args.since_hours * 3600)
        stories = story_items(uid, cookies, not args.no_highlights, since)
        work = Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)
        images = []
        for s in stories:
            if s["image"]:
                s["_file"] = f"{s['pk']}.jpg"
                p = work / s["_file"]
                if not p.exists():
                    download(s["image"], p)
                images.append(p)
        extracted = [] if (args.no_model or not images) else extract_with_model(images)
        cands = to_candidates(stories, extracted, username)
        print(json.dumps({"instagram_stories": len(stories), "images": len(images), "candidates": len(cands)}), file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"zero2sudo source skipped: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        cands = []

    if args.merge:
        path = Path(args.merge)
        existing = json.loads(path.read_text()) if path.exists() else []
        have_ids = {c["id"] for c in existing}
        have_urls = {c.get("url", "").rstrip("/") for c in existing}
        try:
            seen = set(json.loads((ROOT / "state/seen.json").read_text()))
        except FileNotFoundError:
            seen = set()
        added = [c for c in cands if c["id"] not in have_ids and c["id"] not in seen and c["url"].rstrip("/") not in have_urls]
        path.write_text(json.dumps(existing + added, indent=1))
        print(json.dumps({"instagram_added": len(added)}), file=sys.stderr)
    elif args.out:
        Path(args.out).write_text(json.dumps(cands, indent=1))
    else:
        print(json.dumps(cands, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
