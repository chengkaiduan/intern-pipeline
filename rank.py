#!/usr/bin/env python3
"""One model call: candidates.json → picks.json (picks, close cuts, hard drops)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from settings import settings

JD_EXCERPT_CHARS = 1500
CLAUDE = "claude"
ROOT = Path(__file__).resolve().parent


class RankParseError(Exception):
    pass


def split_hard_drops(cands):
    keep, dropped = [], []
    for c in cands:
        if c.get("citizenship_only"):
            dropped.append({**c, "reason": "citizenship/clearance"})
        else:
            keep.append(c)
    return keep, dropped


def _tier(company: str, cfg: dict) -> str:
    low = (company or "").lower()
    for t in ("tier1", "tier2"):
        for name in cfg.get(t, []) or []:
            if name.lower() in low:
                return t
    return "tier3"


def build_rank_input(cands, cfg) -> str:
    blocks = []
    for i, c in enumerate(cands, 1):
        jd_path = Path(c.get("jd_path") or "/nonexistent")
        if c.get("jd_status") == "ok" and jd_path.exists():
            raw = jd_path.read_text()
            excerpt = re.sub(r"\s+", " ", raw)[:JD_EXCERPT_CHARS]
            jd = f"JD ({len(raw)} chars): {excerpt}"
        else:
            jd = "JD: unavailable"
        terms = ", ".join(c.get("terms") or []) or "unspecified"
        src = f" | source: {c['source']}" if c.get("source") else ""
        blocks.append(
            f"### {i}. {c['company']} — {c['title']} [{_tier(c['company'], cfg)}]\n"
            f"slug: {c['slug']}\nlocations: {', '.join(c.get('locations') or [])} | category: {c.get('category')} | terms: {terms}{src}\n"
            f"url: {c.get('url')}\n{jd}\n"
        )
    return "\n".join(blocks)


def pick_band(max_jobs: int) -> tuple[int, int]:
    """Quality band around the target: 10 → (6, 14); 2 → (1, 3)."""
    return max(1, round(max_jobs * 0.6)), max(max_jobs, round(max_jobs * 1.4))


def render_prompt(template: str, candidates_text: str, cfg: dict) -> str:
    lo, hi = pick_band(int(cfg.get("max_jobs", 10)))
    return (template.replace("{{MAX_JOBS}}", str(cfg.get("max_jobs", 10)))
            .replace("{{MIN_PICKS}}", str(lo)).replace("{{MAX_PICKS}}", str(hi))
            .replace("{{NAME}}", str(cfg.get("name", "the candidate")))
            .replace("{{PROFILE_SUMMARY}}", str(cfg.get("summary", "")).strip())
            .replace("{{RANKING_RULES}}", str(cfg.get("ranking_rules", "")).strip())
            .replace("{{CLOSE_CUTS}}", str(cfg.get("close_cuts", 6)))
            .replace("{{CANDIDATES}}", candidates_text))


def parse_rank_output(text: str, valid_slugs: set) -> dict:
    # take the last {...} that parses
    candidates = []
    for m in re.finditer(r"\{", text):
        start = m.start()
        depth = 0
        for j in range(start, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:j + 1])
                    break
    parsed = None
    for chunk in reversed(candidates):
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "picks" in obj:
            parsed = obj
            break
    if parsed is None:
        raise RankParseError("no JSON object with 'picks' found in model output")
    for k in ("picks", "close_cuts"):
        if k not in parsed or not isinstance(parsed[k], list):
            raise RankParseError(f"missing or non-list key: {k}")

    def clean(items, exclude):
        out, seen = [], set()
        for it in items:
            if not isinstance(it, dict) or "slug" not in it:
                raise RankParseError(f"bad item: {it!r}")
            s = it["slug"]
            if s not in valid_slugs:
                raise RankParseError(f"unknown slug: {s}")
            if s in seen or s in exclude:
                continue
            seen.add(s)
            out.append({"slug": s, "reason": str(it.get("reason", "")).strip()})
        return out

    picks = clean(parsed["picks"], set())
    cuts = clean(parsed["close_cuts"], {p["slug"] for p in picks})
    return {"picks": picks, "close_cuts": cuts, "notes": str(parsed.get("notes", "")).strip()}


def assemble_picks(parsed: dict, cands, dropped, run_date: str) -> dict:
    by_slug = {c["slug"]: c for c in cands}

    def enrich(items, key):
        return [{**by_slug[i["slug"]], key: i["reason"]} for i in items]

    return {
        "date": run_date,
        "notes": parsed.get("notes", ""),
        "picks": enrich(parsed["picks"], "rank_reason"),
        "close_cuts": enrich(parsed["close_cuts"], "cut_reason"),
        "dropped_hard": [{k: d.get(k) for k in ("slug", "company", "title", "url", "reason")} for d in dropped],
    }


def call_claude(prompt: str, model: str | None = None, timeout: int = 600) -> str:
    from tailor import run_with_deadline
    cmd = [CLAUDE, "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    rc, out, err = run_with_deadline(cmd, prompt, timeout)
    if rc != 0:
        raise RuntimeError(f"claude exited {rc}: {err[-500:]}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--dump-prompt", default=None, help="write the rendered prompt here (debug)")
    args = ap.parse_args(argv)

    cfg = settings()
    if args.max:
        cfg["max_jobs"] = args.max
    cands = json.loads(Path(args.candidates).read_text())
    keep, dropped = split_hard_drops(cands)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not keep:
        out_path.write_text(json.dumps(assemble_picks({"picks": [], "close_cuts": [], "notes": "no candidates"}, cands, dropped, args.date), indent=1))
        print("rank: zero candidates after hard drops", file=sys.stderr)
        return 0

    template = (ROOT / "prompts" / "rank_prompt.md").read_text()
    prompt = render_prompt(template, build_rank_input(keep, cfg), cfg)
    if args.dump_prompt:
        Path(args.dump_prompt).write_text(prompt)
    valid = {c["slug"] for c in keep}

    last_err = None
    for attempt in (1, 2):
        text = call_claude(prompt if attempt == 1 else prompt + f"\n\nYour previous answer was rejected: {last_err}. Answer with only the JSON object.", args.model)
        try:
            parsed = parse_rank_output(text, valid)
            break
        except RankParseError as e:
            last_err = str(e)
            print(f"rank attempt {attempt} rejected: {e}", file=sys.stderr)
            Path(str(out_path) + f".raw{attempt}.txt").write_text(text)
    else:
        print(f"rank FAILED after 2 attempts: {last_err}", file=sys.stderr)
        return 3

    result = assemble_picks(parsed, cands, dropped, args.date)
    out_path.write_text(json.dumps(result, indent=1))
    print(json.dumps({"picks": len(result["picks"]), "close_cuts": len(result["close_cuts"]),
                      "dropped_hard": len(result["dropped_hard"]), "candidates": len(keep)}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
