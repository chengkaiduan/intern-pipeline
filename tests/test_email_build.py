import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import email_build as eb  # noqa: E402

PICKS = {
    "date": "2026-09-23",
    "notes": "quiet night",
    "sheet_url": "https://docs.google.com/spreadsheets/d/abc",
    "drive_folder_url": "https://drive.google.com/drive/folders/xyz",
    "picks": [
        {"slug": "acme-swe-1", "company": "Acme", "title": "SWE Intern", "locations": ["SF"], "url": "https://acme/1",
         "score": 91.3, "required": "7/8", "grad": "May 2028", "gaps": ["Kubernetes"], "review_count": 3,
         "tailor_status": "ok", "jd_status": "ok", "pdf": "/x/Alex_Rivera_Acme_SWE_Intern.pdf",
         "drive_url": "https://drive.google.com/file/d/1/view", "rank_reason": "tier1, strong fit"},
        {"slug": "beta-pm-2", "company": "Beta", "title": "PM Intern", "locations": ["NYC"], "url": "https://beta/2",
         "score": None, "tailor_status": "failed", "tailor_error": "timeout", "jd_status": "failed", "pdf": None,
         "gaps": [], "rank_reason": "brand"},
    ],
    "close_cuts": [{"company": "Gamma", "title": "Data Intern", "url": "https://g/3", "cut_reason": "insurance back office"}],
    "dropped_hard": [{"company": "Delta", "title": "SWE", "url": "https://d/4", "reason": "citizenship/clearance"}],
}


def test_subject_counts_ready():
    assert eb.subject(PICKS) == "Internships 2026-09-23: 1 ready, 1 link-only"


def test_subject_nothing_new():
    assert eb.subject({"date": "2026-09-23", "picks": [], "close_cuts": []}) == "Internships 2026-09-23: nothing new"


def test_html_contains_everything():
    h = eb.build_html(PICKS)
    assert "https://acme/1" in h and "Acme" in h and "SWE Intern" in h
    assert "91.3" in h and "7/8" in h and "Kubernetes" in h and "3 flagged" in h
    assert "https://drive.google.com/file/d/1/view" in h and "Alex_Rivera_Acme_SWE_Intern.pdf" in h
    assert "Beta" in h and "resume failed" in h.lower() and "JD not fetched" in h
    assert "Gamma" in h and "insurance back office" in h
    assert "Delta" in h and "citizenship" in h
    assert PICKS["sheet_url"] in h and PICKS["drive_folder_url"] in h
    assert "quiet night" in h


def test_html_escapes():
    p = {**PICKS, "picks": [{**PICKS["picks"][0], "title": "SWE <Intern> & Co"}]}
    h = eb.build_html(p)
    assert "SWE &lt;Intern&gt; &amp; Co" in h and "<Intern>" not in h


def test_plain_text_has_links():
    t = eb.build_text(PICKS)
    assert "https://acme/1" in t and "Gamma" in t and PICKS["sheet_url"] in t
