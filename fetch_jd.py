#!/usr/bin/env python3
"""Turn a posting URL into jd.txt.

Order of attempts: ATS JSON API (Greenhouse / Lever / Ashby / Workday) → plain HTML fetch →
Playwright-rendered HTML. Deterministic, no model. Writes jd.txt verbatim into the job dir and
annotates each candidate with jd_status / jd_method / jd_chars / citizenship_only.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

def _ssl_ctx():
    """Framework Python on this Mac ships no CA bundle; use certifi's when available."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = _ssl_ctx()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
MIN_JD_CHARS = 600
JD_WORDS = re.compile(r"\b(intern|internship|responsibilities|qualifications|requirements|what you.ll do)\b", re.I)
CITIZEN = re.compile(
    r"(must be (a |an )?u\.?s\.? citizen|u\.?s\.? citizenship (is )?required|"
    r"(active |current )?(secret|top secret|ts/sci|dod|government)? ?security clearance (is )?required|"
    r"requires? (an? )?(active )?(secret|top secret|ts/sci) (security )?clearance|"
    r"ability to obtain (and maintain )?(a |an )?(secret|top secret|ts/sci|dod|government|security) clearance|"
    r"citizenship (is )?required|only u\.?s\.? citizens)",
    re.I,
)


class FetchError(Exception):
    pass


# ---------------------------------------------------------------- detection

def detect(url: str):
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower()
    path = u.path
    qs = urllib.parse.parse_qs(u.query)

    m = re.match(r"^/([^/]+)/jobs/(\d+)", path)
    if host.endswith("greenhouse.io") and m:
        return "greenhouse", {"board": m.group(1), "id": m.group(2)}
    if "gh_jid" in qs:
        parts = host.split(".")
        guess = parts[-2] if len(parts) >= 2 else parts[0]
        return "greenhouse", {"board": None, "id": qs["gh_jid"][0], "domain_guess": guess, "page": url}

    m = re.match(r"^/([^/]+)/([0-9a-f-]{36})", path)
    if host == "jobs.lever.co" and m:
        return "lever", {"co": m.group(1), "id": m.group(2)}
    if host == "jobs.ashbyhq.com" and m:
        return "ashby", {"co": m.group(1), "id": m.group(2)}

    m = re.match(r"^([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if m:
        tenant = m.group(1)
        segs = [s for s in path.split("/") if s]
        if segs and re.match(r"^[a-z]{2}-[A-Z]{2}$", segs[0]):
            segs = segs[1:]  # drop locale like en-US
        if len(segs) >= 3 and segs[1] == "job":
            site = segs[0]
            rest = "/".join(segs[2:])
            api = f"https://{host}/wday/cxs/{tenant}/{site}/job/{rest}"
            return "workday", {"api": api}
    return "generic", {}


# ---------------------------------------------------------------- html → text

def html_to_text(raw: str) -> str:
    s = raw
    s = re.sub(r"(?is)<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)</(p|div|li|ul|ol|h[1-6]|tr|section|article|header|footer)>", "\n", s)
    s = re.sub(r"(?i)<(p|div|h[1-6]|tr|section|article)[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


MAX_JD_CHARS = 60_000
MAX_BRACES = 40


def looks_like_jd(text: str) -> bool:
    """Long enough, mentions JD-ish words, and is prose rather than a leaked JSON/JS blob."""
    if len(text) < MIN_JD_CHARS or len(text) > MAX_JD_CHARS:
        return False
    if text.count("{") > MAX_BRACES:
        return False
    return JD_WORDS.search(text) is not None


def citizenship_only(text: str) -> bool:
    return CITIZEN.search(text or "") is not None


# ---------------------------------------------------------------- parsers

def parse_greenhouse(j: dict) -> str:
    content = htmllib.unescape(j.get("content") or "")
    body = html_to_text(content)
    loc = (j.get("location") or {}).get("name", "")
    head = "\n".join(x for x in [j.get("title", ""), loc] if x)
    return f"{head}\n\n{body}".strip()


def parse_lever(j: dict) -> str:
    parts = [j.get("text", "")]
    if j.get("descriptionPlain"):
        parts.append(j["descriptionPlain"])
    elif j.get("description"):
        parts.append(html_to_text(j["description"]))
    for lst in j.get("lists") or []:
        parts.append(lst.get("text", ""))
        parts.append(html_to_text(lst.get("content", "")))
    if j.get("additionalPlain"):
        parts.append(j["additionalPlain"])
    elif j.get("additional"):
        parts.append(html_to_text(j["additional"]))
    return "\n\n".join(p for p in parts if p).strip()


def parse_ashby(j: dict, job_id: str) -> str:
    for job in j.get("jobs") or []:
        if job.get("id") == job_id:
            loc = job.get("location") or ""
            body = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
            return f"{job.get('title', '')}\n{loc}\n\n{body}".strip()
    raise FetchError(f"ashby job {job_id} not in board")


def parse_workday(j: dict) -> str:
    info = j.get("jobPostingInfo") or {}
    if not info:
        raise FetchError("workday response has no jobPostingInfo")
    head = "\n".join(x for x in [info.get("title", ""), info.get("location", "")] if x)
    return f"{head}\n\n{html_to_text(info.get('jobDescription', ''))}".strip()


def extract_generic(raw_html: str) -> str:
    # Prefer <main>/<article>, else body; nav/footer removed first.
    s = re.sub(r"(?is)<(nav|footer|header|aside)[^>]*>.*?</\1>", " ", raw_html)
    m = re.search(r"(?is)<(main|article)[^>]*>(.*?)</\1>", s)
    core = m.group(2) if m else s
    return html_to_text(core)


# ---------------------------------------------------------------- network

def _get(url: str, accept: str = "*/*", timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


def _get_json(url: str) -> dict:
    return json.loads(_get(url, accept="application/json").decode("utf-8", "ignore"))


def _greenhouse_board_from_page(page_url: str) -> str | None:
    try:
        html = _get(page_url).decode("utf-8", "ignore")
    except Exception:
        return None
    for pat in (r"greenhouse\.io/(?:embed/job_(?:app|board)\?for=|v1/boards/)([A-Za-z0-9_-]+)",
                r"boards\.greenhouse\.io/([A-Za-z0-9_-]+)"):
        for tok in re.findall(pat, html):
            if tok not in ("embed", "v1"):
                return tok
    return None


def fetch_api(kind: str, info: dict) -> str:
    if kind == "greenhouse":
        boards = []
        if info.get("board"):
            boards.append(info["board"])
        else:
            found = _greenhouse_board_from_page(info["page"])
            if found:
                boards.append(found)
            boards.append(info["domain_guess"])
        last = None
        for b in boards:
            try:
                return parse_greenhouse(_get_json(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs/{info['id']}?content=true"))
            except Exception as e:  # try next board guess
                last = e
        raise FetchError(f"greenhouse: no board worked ({last})")
    if kind == "lever":
        return parse_lever(_get_json(f"https://api.lever.co/v0/postings/{info['co']}/{info['id']}"))
    if kind == "ashby":
        return parse_ashby(_get_json(f"https://api.ashbyhq.com/posting-api/job-board/{info['co']}"), info["id"])
    if kind == "workday":
        return parse_workday(_get_json(info["api"]))
    raise FetchError(f"no api for {kind}")


def _playwright_text(p, url: str, channel: str | None) -> str:
    kwargs = {"headless": True}
    if channel:
        kwargs.update(channel=channel, args=["--disable-blink-features=AutomationControlled"])
    b = p.chromium.launch(**kwargs)
    try:
        ctx = b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            pg.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass  # many career sites never go idle; proceed with what rendered
        pg.wait_for_timeout(1500)
        best = ""
        for attempt in range(6):  # bot-check interstitials resolve within a few seconds
            for fr in pg.frames:
                try:
                    for sel in ("main", "article", "[role=main]", "body"):
                        loc = fr.locator(sel).first
                        if loc.count():
                            t = loc.inner_text(timeout=5_000)
                            if looks_like_jd(t) and len(t) > len(best):
                                best = t
                                break
                except Exception:
                    continue
            if best or not channel:
                break
            pg.wait_for_timeout(2500)
        text = best or pg.inner_text("body")
    finally:
        b.close()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_JD_CHARS]


def fetch_playwright(url: str) -> str:
    """Bundled Chromium first; if that yields no JD (bot wall), retry with the installed Chrome
    and automation flags hidden, which gets past Citadel-style checks."""
    from playwright.sync_api import sync_playwright  # imported lazily; slow

    with sync_playwright() as p:
        text = _playwright_text(p, url, None)
        if looks_like_jd(text):
            return text
        try:
            text2 = _playwright_text(p, url, "chrome")
            if looks_like_jd(text2):
                return text2
        except Exception:
            pass  # no installed Chrome or launch failure; fall through with first result
        return text


def fetch(url: str, allow_playwright: bool = True):
    """Return (text, method). Raise FetchError if every method fails."""
    errors = []
    kind, info = detect(url)
    if kind != "generic":
        try:
            text = fetch_api(kind, info)
            if len(text) >= 200:
                return text, kind
            errors.append(f"{kind}: too short ({len(text)})")
        except Exception as e:
            errors.append(f"{kind}: {type(e).__name__}: {e}")
    try:
        text = extract_generic(_get(url).decode("utf-8", "ignore"))
        if looks_like_jd(text):
            return text, "html"
        errors.append(f"html: not a JD ({len(text)} chars)")
    except Exception as e:
        errors.append(f"html: {type(e).__name__}: {e}")
    if allow_playwright:
        try:
            text = fetch_playwright(url)
            if looks_like_jd(text):
                return text, "playwright"
            errors.append(f"playwright: not a JD ({len(text)} chars)")
        except Exception as e:
            errors.append(f"playwright: {type(e).__name__}: {e}")
    raise FetchError("; ".join(errors))


# ---------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True, help="candidates.json; updated in place")
    ap.add_argument("--jd-dir", required=True, help="where <slug>.txt files go (state/<date>/jd)")
    ap.add_argument("--no-playwright", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    root = Path(args.jd_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path = Path(args.candidates)
    cands = json.loads(path.read_text())
    todo = cands if args.limit is None else cands[: args.limit]
    ok = failed = 0
    for c in todo:
        jd_path = root / f"{c['slug']}.txt"
        c["jd_path"] = str(jd_path)
        if jd_path.exists() and jd_path.stat().st_size > 200:
            text = jd_path.read_text()
            c.update(jd_status="ok", jd_method=c.get("jd_method", "cached"), jd_chars=len(text),
                     citizenship_only=citizenship_only(text))
            ok += 1
            continue
        try:
            text, method = fetch(c["url"], allow_playwright=not args.no_playwright)
            jd_path.write_text(text)
            c.update(jd_status="ok", jd_method=method, jd_chars=len(text), citizenship_only=citizenship_only(text))
            ok += 1
            print(f"ok   {method:10s} {c['slug']} ({len(text)} chars)", file=sys.stderr)
        except Exception as e:
            c.update(jd_status="failed", jd_method=None, jd_chars=0, citizenship_only=False, jd_error=str(e)[:300])
            failed += 1
            print(f"FAIL {c['slug']}: {str(e)[:200]}", file=sys.stderr)
        path.write_text(json.dumps(cands, indent=1))  # checkpoint after each
    print(json.dumps({"jd_ok": ok, "jd_failed": failed}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
