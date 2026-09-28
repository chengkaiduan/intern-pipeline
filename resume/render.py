#!/usr/bin/env python3
"""Render a job's resume.json into resume.html, resume.pdf, and resume.txt.

    render.py jobs/acme-swe-intern

The PDF is produced by headless Chrome, which gives a clean text layer — the thing the
scanner actually reads. Page count is asserted, not hoped for.

resume.json shape:

{
  "name": "Alex Rivera",
  "contact": ["City, ST", "you@example.edu", "(555) 555-5555", "linkedin.com/in/you"],
  "sections": [
    {"title": "Education", "entries": [
        {"org": "State University", "when": "Aug 2025 - May 2028",
         "role": "B.S. Computer Science", "where": "City, ST",
         "lines": ["Relevant Coursework: ..."]}
    ]},
    {"title": "Experience", "entries": [
        {"org": "Acme", "when": "Jun 2026 - Aug 2026", "role": "Software Engineer Intern",
         "where": "City, ST", "bullets": ["..."]}
    ]},
    {"title": "Skills", "lines": [
        {"label": "Languages", "text": "Python, Java, TypeScript"}
    ]}
  ]
}
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    sys.exit("no Chrome/Chromium/Edge found — needed to render the PDF")


# --------------------------------------------------------------------------- #
# HTML assembly
# --------------------------------------------------------------------------- #

def render_entry(entry: dict) -> str:
    parts = ['<div class="entry">']

    org, when = entry.get("org"), entry.get("when")
    if org or when:
        parts.append(
            f'<div class="entry-head"><span class="org">{esc(org or "")}</span>'
            f'<span class="when">{esc(when or "")}</span></div>'
        )

    role, where = entry.get("role"), entry.get("where")
    if role or where:
        parts.append(
            f'<div class="entry-sub"><span class="role">{esc(role or "")}</span>'
            f'<span class="where">{esc(where or "")}</span></div>'
        )

    for line in entry.get("lines", []):
        parts.append(f'<div class="line">{esc(line)}</div>')

    bullets = entry.get("bullets", [])
    if bullets:
        parts.append("<ul>")
        parts.extend(f"<li>{esc(b)}</li>" for b in bullets)
        parts.append("</ul>")

    parts.append("</div>")
    return "\n".join(parts)


def render_section(section: dict) -> str:
    parts = [f'<h2>{esc(section["title"])}</h2>']

    for line in section.get("lines", []):
        if isinstance(line, dict):
            label = f'<span class="label">{esc(line["label"])}:</span> ' if line.get("label") else ""
            parts.append(f'<div class="line">{label}{esc(line["text"])}</div>')
        else:
            parts.append(f'<div class="line">{esc(line)}</div>')

    for entry in section.get("entries", []):
        parts.append(render_entry(entry))

    return "\n".join(parts)


def build_html(data: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    sections = "\n".join(render_section(s) for s in data["sections"])
    contact = " &nbsp;•&nbsp; ".join(esc(c) for c in data.get("contact", []))
    font_pt = data.get("fontPt", 10)
    return (template
            .replace("__FONTPT__", str(font_pt))
            .replace("__NAME__", esc(data["name"]))
            .replace("__CONTACT__", contact)
            .replace("__SECTIONS__", sections))


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def to_pdf(html_path: Path, pdf_path: Path) -> None:
    chrome = find_chrome()
    result = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--virtual-time-budget=3000",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if not pdf_path.exists():
        sys.exit(f"Chrome produced no PDF.\nstdout: {result.stdout}\nstderr: {result.stderr}")


def page_count(pdf_path: Path) -> int:
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("pypdf required for the page-count assertion: pip3 install pypdf")
    return len(PdfReader(str(pdf_path)).pages)


def to_text(html_path: Path) -> str:
    sys.path.insert(0, str(HERE))
    import ats_scan
    return "\n".join(
        line.strip() for line in ats_scan.read_document(html_path).splitlines() if line.strip()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_dir", type=Path, help="directory holding resume.json")
    parser.add_argument("--allow-overflow", action="store_true",
                        help="report page overflow instead of failing")
    args = parser.parse_args()

    job_dir = args.job_dir.resolve()  # Chrome needs an absolute file:// URI
    data_path = job_dir / "resume.json"
    if not data_path.exists():
        sys.exit(f"missing {data_path}")

    data = json.loads(data_path.read_text(encoding="utf-8"))
    html_path = job_dir / "resume.html"
    pdf_path = job_dir / "resume.pdf"
    txt_path = job_dir / "resume.txt"

    html_path.write_text(build_html(data), encoding="utf-8")
    to_pdf(html_path, pdf_path)
    txt_path.write_text(to_text(html_path), encoding="utf-8")

    pages = page_count(pdf_path)
    print(json.dumps({
        "html": str(html_path),
        "pdf": str(pdf_path),
        "txt": str(txt_path),
        "pages": pages,
        "words": len(txt_path.read_text(encoding="utf-8").split()),
    }, indent=2))

    if pages != 1:
        message = f"resume is {pages} pages — cut content or tighten spacing"
        if args.allow_overflow:
            print(f"WARNING: {message}", file=sys.stderr)
        else:
            sys.exit(f"ERROR: {message}")


if __name__ == "__main__":
    main()
