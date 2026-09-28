#!/usr/bin/env python3
"""Run the tailor-resume skill once per pick (fresh `claude -p` each), record results in picks.json."""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from settings import settings

CLAUDE = "claude"
ROOT = Path(__file__).resolve().parent
PER_JOB_TIMEOUT = 20 * 60
QUOTA = re.compile(r"(usage limit|rate limit|out of extra usage|limit reached|429|overloaded)", re.I)


class QuotaError(Exception):
    pass


def pdf_name(prefix: str, company: str, title: str) -> str:
    """<prefix>_<Company>_<Role>.pdf, alphanumerics and underscores only, at most 80 chars."""
    def clean(s):
        s = re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_")
        return s
    body = f"{clean(company)}_{clean(title)}"
    prefix = clean(prefix) + "_"
    room = 80 - len(prefix) - len(".pdf")
    body = body[:room].rstrip("_")
    return f"{prefix}{body}.pdf"


def render_prompt(template: str, pick: dict, cfg: dict) -> str:
    jd_note = ""
    if pick.get("jd_status") != "ok":
        jd_note = ("NOTE: the JD could not be fetched automatically. Open the posting URL yourself (WebFetch or "
                   "Playwright), save the description verbatim to jd.txt, then continue. If the page is "
                   "unreachable, write a resume for the role title and company as best you can and say so in report.md.")
    job_dir = Path(cfg["jobs_root"]) / pick["slug"]
    return (template.replace("{{SLUG}}", pick["slug"])
            .replace("{{JOB_DIR}}", str(job_dir.relative_to(ROOT)) if str(job_dir).startswith(str(ROOT)) else str(job_dir))
            .replace("{{RESUME_DIR}}", str(Path(cfg["resume_dir"]).relative_to(ROOT)) if cfg["resume_dir"].startswith(str(ROOT)) else cfg["resume_dir"])
            .replace("{{COMPANY}}", pick.get("company", ""))
            .replace("{{TITLE}}", pick.get("title", ""))
            .replace("{{LOCATIONS}}", ", ".join(pick.get("locations") or []))
            .replace("{{URL}}", pick.get("url", ""))
            .replace("{{PDF_NAME}}", pdf_name(cfg["pdf_prefix"], pick.get("company", ""), pick.get("title", "")))
            .replace("{{JD_NOTE}}", jd_note))


def extract_result_line(stdout: str):
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "score" in obj:
            return obj
    return None


def is_quota_error(text: str) -> bool:
    return QUOTA.search(text or "") is not None


def classify_run(returncode: int, stdout: str, pdf_exists: bool, stderr: str = "") -> dict:
    if returncode != 0 and is_quota_error(stdout + stderr):
        raise QuotaError((stdout + stderr)[-300:])
    res = extract_result_line(stdout) or {}
    out = {
        "score": res.get("score"), "required": res.get("required"), "preferred": res.get("preferred"),
        "grad": res.get("grad"), "gaps": res.get("gaps") or [], "review_count": res.get("review_count"),
    }
    if not pdf_exists:
        out.update(tailor_status="failed", tailor_error=f"no pdf produced (exit {returncode}): {(stderr or stdout)[-300:]}")
    else:
        out.update(tailor_status="ok", tailor_error=None)
    return out


def stage_job_dir(pick: dict, jobs_root: Path) -> Path:
    """Create <jobs_root>/<slug>/ and drop jd.txt in it (only picks get a job dir)."""
    job_dir = Path(jobs_root) / pick["slug"]
    job_dir.mkdir(parents=True, exist_ok=True)
    src = Path(pick.get("jd_path") or "/nonexistent")
    dst = job_dir / "jd.txt"
    if pick.get("jd_status") == "ok" and src.exists() and not dst.exists():
        dst.write_text(src.read_text())
    return job_dir


def run_with_deadline(cmd: list[str], stdin_text: str, seconds: int, cwd=None):
    """Run cmd with a hard wall-clock cap. The child gets its own process group; on deadline the
    whole group (claude + MCP servers + Chrome) is SIGKILLed so no grandchild can hold the pipes
    open. Returns (returncode, stdout, stderr); returncode 124 on timeout."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=cwd, start_new_session=True)
    killed = {"yes": False}

    def _kill():
        killed["yes"] = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    timer = threading.Timer(seconds, _kill)
    timer.start()
    try:
        out, err = proc.communicate(stdin_text)
    finally:
        timer.cancel()
    rc = proc.returncode
    if killed["yes"]:
        rc, err = 124, (err or "") + f"\n[timeout after {seconds}s: process group killed]"
    return rc, out or "", err or ""


def run_once(pick: dict, template: str, model: str | None, log_dir: Path, cfg: dict) -> dict:
    prompt = render_prompt(template, pick, cfg)
    pdf = stage_job_dir(pick, cfg["jobs_root"]) / pdf_name(cfg["pdf_prefix"], pick["company"], pick["title"])
    cmd = [CLAUDE, "-p", "--dangerously-skip-permissions", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    t0 = time.time()
    rc, out, err = run_with_deadline(cmd, prompt, PER_JOB_TIMEOUT, cwd=ROOT)  # repo root: .claude/skills applies
    (log_dir / f"tailor-{pick['slug']}.log").write_text(f"$ {' '.join(cmd)}\n--- prompt ---\n{prompt}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n")
    result = classify_run(rc, out, pdf.exists(), err)
    result["pdf"] = str(pdf) if pdf.exists() else None
    result["tailor_seconds"] = int(time.time() - t0)
    return result


def run_tailor(pick: dict, template: str, model: str | None, log_dir: Path, cfg: dict) -> dict:
    r = run_once(pick, template, model, log_dir, cfg)
    if r["tailor_status"] == "ok":
        return r
    print(f"  retrying {pick['slug']}: {r['tailor_error'][:120]}", file=sys.stderr)
    r2 = run_once(pick, template, model, log_dir, cfg)
    r2["tailor_seconds"] += r["tailor_seconds"]
    return r2


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", required=True, help="picks.json; updated in place after each job")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--log-dir", default=None)
    args = ap.parse_args(argv)

    cfg = settings()
    picks_path = Path(args.picks)
    data = json.loads(picks_path.read_text())
    log_dir = Path(args.log_dir or picks_path.parent)
    log_dir.mkdir(parents=True, exist_ok=True)
    template = (ROOT / "prompts" / "tailor_prompt.md").read_text()
    model = args.model or cfg.get("tailor_model")

    todo = [p for p in data["picks"] if p.get("tailor_status") != "ok"]
    if args.limit is not None:
        todo = todo[: args.limit]
    ok = failed = 0
    for i, pick in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] tailoring {pick['slug']}", file=sys.stderr)
        try:
            pick.update(run_tailor(pick, template, model, log_dir, cfg))
        except QuotaError as e:
            pick.update(tailor_status="skipped", tailor_error="quota: " + str(e)[:200])
            data["stopped_reason"] = "quota"
            for rest in todo[i:]:
                rest.update(tailor_status="skipped", tailor_error="quota hit earlier tonight")
            picks_path.write_text(json.dumps(data, indent=1))
            print(f"QUOTA hit; stopping after {ok} ok / {failed} failed", file=sys.stderr)
            return 4
        ok += pick["tailor_status"] == "ok"
        failed += pick["tailor_status"] != "ok"
        print(f"  {pick['tailor_status']} score={pick.get('score')} {pick.get('tailor_seconds')}s", file=sys.stderr)
        picks_path.write_text(json.dumps(data, indent=1))
    print(json.dumps({"tailor_ok": ok, "tailor_failed": failed}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
