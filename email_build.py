#!/usr/bin/env python3
"""Render the nightly digest (subject, HTML, plain text) from picks.json. Deterministic, no model."""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def subject(p: dict) -> str:
    picks = p.get("picks", [])
    if not picks:
        return f"Internships {p['date']}: nothing new"
    ready = sum(1 for x in picks if x.get("tailor_status") == "ok")
    link_only = len(picks) - ready
    parts = [f"{ready} ready"]
    if link_only:
        parts.append(f"{link_only} link-only")
    return f"Internships {p['date']}: " + ", ".join(parts)


def _pick_row(x: dict) -> str:
    loc = ", ".join(x.get("locations") or [])
    score = f"{float(x['score']):.1f}" if x.get("score") is not None else "—"
    req = x.get("required") or ""
    flags = []
    if x.get("tailor_status") != "ok":
        flags.append(f"<b style='color:#b00'>Resume failed</b>: {_e((x.get('tailor_error') or '')[:100])}")
    if x.get("jd_status") != "ok":
        flags.append("JD not fetched (read the posting)")
    if x.get("gaps"):
        flags.append("gaps: " + _e(", ".join(x["gaps"][:6])))
    if x.get("review_count") is not None:
        flags.append(f"{x['review_count']} flagged bullets to prune")
    if x.get("drive_url"):
        resume = f"<a href='{_e(x['drive_url'])}'>{_e(Path(x['pdf']).name)}</a>"
    elif x.get("pdf"):
        resume = f"<code>{_e(x['pdf'])}</code>"
    else:
        resume = "—"
    return (
        "<tr>"
        f"<td><b>{_e(x.get('company'))}</b><br><span style='color:#555'>{_e(loc)}</span></td>"
        f"<td><a href='{_e(x.get('url'))}'>{_e(x.get('title'))}</a><br><span style='color:#555;font-size:12px'>{_e(x.get('rank_reason', ''))}</span></td>"
        f"<td style='text-align:center'>{score}<br><span style='color:#555;font-size:12px'>{_e(req)}</span></td>"
        f"<td>{resume}</td>"
        f"<td style='font-size:12px'>{'<br>'.join(flags) or '—'}</td>"
        "</tr>"
    )


def build_html(p: dict) -> str:
    picks = p.get("picks", [])
    cuts = p.get("close_cuts", [])
    hard = p.get("dropped_hard", [])
    css = "font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:14px;color:#111"
    out = [f"<div style='{css}'>"]
    out.append(f"<h2 style='margin:0 0 8px'>Internships — {_e(p['date'])}</h2>")
    links = []
    if p.get("sheet_url"):
        links.append(f"<a href='{_e(p['sheet_url'])}'>Tracker sheet</a>")
    if p.get("drive_folder_url"):
        links.append(f"<a href='{_e(p['drive_folder_url'])}'>Tonight's PDFs</a>")
    if p.get("desktop_folder"):
        links.append(f"PDFs: <code>{_e(p['desktop_folder'])}</code>")
    if links:
        out.append("<p>" + " · ".join(links) + "</p>")
    if p.get("notes"):
        out.append(f"<p style='color:#555'><i>{_e(p['notes'])}</i></p>")
    if picks:
        out.append("<table cellpadding='6' style='border-collapse:collapse;width:100%'>"
                   "<tr style='background:#f2f2f2;text-align:left'><th>Company</th><th>Role</th><th>ATS</th><th>Resume</th><th>Notes</th></tr>")
        out.extend(_pick_row(x) for x in picks)
        out.append("</table>")
    else:
        out.append("<p>No new postings cleared the filter tonight.</p>")
    if p.get("stopped_reason") == "quota":
        out.append("<p style='color:#b00'><b>Usage limit hit mid-run.</b> Remaining picks are link-only.</p>")
    if cuts:
        out.append("<h3 style='margin:18px 0 6px'>Close cuts</h3><p style='color:#555;margin:0 0 6px'>Tell Claude which kinds to include next time.</p><ul>")
        out.extend(f"<li><b>{_e(c.get('company'))}</b> — <a href='{_e(c.get('url'))}'>{_e(c.get('title'))}</a>: {_e(c.get('cut_reason'))}</li>" for c in cuts)
        out.append("</ul>")
    if hard:
        out.append("<h3 style='margin:18px 0 6px'>Dropped (citizenship / clearance)</h3><ul>")
        out.extend(f"<li>{_e(h.get('company'))} — <a href='{_e(h.get('url'))}'>{_e(h.get('title'))}</a> ({_e(h.get('reason'))})</li>" for h in hard)
        out.append("</ul>")
    out.append(f"<p style='color:#888;font-size:12px'>Job dirs: {_e(p.get('jobs_root', 'resume/jobs'))}/&lt;slug&gt;/ (report.md lists direct / reframed / inferred / stretch per bullet). Nothing has been submitted.</p>")
    out.append("</div>")
    return "\n".join(out)


def build_text(p: dict) -> str:
    lines = [f"Internships {p['date']}"]
    if p.get("sheet_url"):
        lines.append(f"Tracker: {p['sheet_url']}")
    if p.get("drive_folder_url"):
        lines.append(f"PDFs: {p['drive_folder_url']}")
    if p.get("desktop_folder"):
        lines.append(f"PDFs: {p['desktop_folder']}")
    lines.append("")
    for x in p.get("picks", []):
        score = f"{float(x['score']):.1f}" if x.get("score") is not None else "-"
        lines.append(f"- {x.get('company')} | {x.get('title')} | {', '.join(x.get('locations') or [])} | ATS {score}")
        lines.append(f"  apply: {x.get('url')}")
        if x.get("drive_url"):
            lines.append(f"  resume: {x['drive_url']}")
        if x.get("tailor_status") != "ok":
            lines.append(f"  resume failed: {x.get('tailor_error')}")
    if p.get("close_cuts"):
        lines.append("")
        lines.append("Close cuts:")
        lines.extend(f"- {c.get('company')} | {c.get('title')} | {c.get('url')} — {c.get('cut_reason')}" for c in p["close_cuts"])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    p = json.loads(Path(args.picks).read_text())
    from settings import settings
    p.setdefault("jobs_root", settings().get("jobs_root"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "email.subject").write_text(subject(p))
    (out / "email.html").write_text(build_html(p))
    (out / "email.txt").write_text(build_text(p))
    print(subject(p), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
