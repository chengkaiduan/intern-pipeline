#!/usr/bin/env python3
"""Append tonight's picks and close cuts to the 'Internship Pipeline' Google Sheet.

Deterministic, no model. Auth = service account key (secrets/sa.json); the sheet is owned by
you and shared with the service account as Editor. Optional: skipped when sheet_id is empty.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from settings import settings

JOB_HEADERS = ["Date", "Company", "Role", "Location", "Category", "Apply link", "ATS score", "Grad date",
               "Resume file", "Status", "Notes"]
CUT_HEADERS = ["Date", "Company", "Role", "Link", "Why cut", "Want?"]
STATUS_VALUES = ["New", "Applied", "Skip"]


def job_row(p: dict, run_date: str) -> list[str]:
    notes = []
    if p.get("tailor_status") != "ok":
        notes.append("resume failed: " + str(p.get("tailor_error") or "")[:80])
    if p.get("jd_status") != "ok":
        notes.append("JD not fetched")
    if p.get("gaps"):
        notes.append("gaps: " + ", ".join(p["gaps"][:6]))
    if p.get("review_count") is not None:
        notes.append(f"review {p['review_count']} flagged bullets")
    if p.get("rank_reason"):
        notes.append(p["rank_reason"])
    score = p.get("score")
    return [
        run_date,
        p.get("company", ""),
        p.get("title", ""),
        ", ".join(p.get("locations") or []),
        p.get("category", ""),
        p.get("url", ""),
        f"{float(score):.1f}" if score is not None else "",
        p.get("grad") or "",
        resume_cell(p),
        "New",
        " | ".join(notes),
    ]


def resume_cell(p: dict) -> str:
    if not p.get("pdf"):
        return ""
    name = Path(p["pdf"]).name
    if p.get("drive_url"):
        url = p["drive_url"].replace('"', "")
        return f'=HYPERLINK("{url}", "{name}")'
    return name


def cut_row(c: dict, run_date: str) -> list[str]:
    return [run_date, c.get("company", ""), c.get("title", ""), c.get("url", ""), c.get("cut_reason", ""), ""]


# ---------------------------------------------------------------- live sheet

def open_client(sa_key: str):
    import gspread
    return gspread.service_account(filename=str(Path(sa_key).expanduser()))


def ensure_tabs(sh):
    """Create Jobs/Cuts tabs with headers and the Status dropdown if they do not exist yet."""
    import gspread
    titles = {ws.title for ws in sh.worksheets()}
    if "Jobs" not in titles:
        ws = sh.add_worksheet("Jobs", rows=1000, cols=len(JOB_HEADERS))
        ws.append_row(JOB_HEADERS)
        ws.format("A1:K1", {"textFormat": {"bold": True}})
        ws.freeze(rows=1)
        # Status dropdown on column J
        sh.batch_update({"requests": [{"setDataValidation": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 9, "endColumnIndex": 10},
            "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in STATUS_VALUES]},
                     "showCustomUi": True, "strict": False}}}]})
    if "Cuts" not in titles:
        ws = sh.add_worksheet("Cuts", rows=1000, cols=len(CUT_HEADERS))
        ws.append_row(CUT_HEADERS)
        ws.format("A1:F1", {"textFormat": {"bold": True}})
        ws.freeze(rows=1)
    # drop the default empty "Sheet1" if it is still there and unused
    for ws in sh.worksheets():
        if ws.title == "Sheet1" and len(sh.worksheets()) > 1 and not ws.get_all_values():
            try:
                sh.del_worksheet(ws)
            except gspread.exceptions.APIError:
                pass


def append(sh, picks: dict) -> tuple[int, int]:
    date = picks["date"]
    jobs = [job_row(p, date) for p in picks.get("picks", [])]
    cuts = [cut_row(c, date) for c in picks.get("close_cuts", [])]
    if jobs:
        sh.worksheet("Jobs").append_rows(jobs, value_input_option="USER_ENTERED")
    if cuts:
        sh.worksheet("Cuts").append_rows(cuts, value_input_option="USER_ENTERED")
    return len(jobs), len(cuts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", required=True)
    ap.add_argument("--init-only", action="store_true", help="just make sure tabs exist")
    args = ap.parse_args(argv)
    cfg = settings()
    if not cfg.get("sheet_id"):
        print("sheet: disabled (profile.yaml sheet_id empty)", file=sys.stderr)
        return 0
    sh = open_client(cfg.get("sa_key", "secrets/sa.json")).open_by_key(cfg["sheet_id"])
    ensure_tabs(sh)
    if args.init_only:
        print(sh.url)
        return 0
    picks = json.loads(Path(args.picks).read_text())
    nj, nc = append(sh, picks)
    picks["sheet_url"] = sh.url
    Path(args.picks).write_text(json.dumps(picks, indent=1))
    print(json.dumps({"sheet_jobs": nj, "sheet_cuts": nc, "url": sh.url}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"sheet.py FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
