import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sheet  # noqa: E402

PICK = {
    "slug": "acme-swe-1a2b3c", "company": "Acme", "title": "SWE Intern", "locations": ["SF", "NYC"],
    "category": "Software", "url": "https://acme/jobs/1", "score": 91.34, "grad": "May 2028",
    "pdf": "/tmp/resume/jobs/acme-swe-1a2b3c/Alex_Rivera_Acme_SWE_Intern.pdf",
    "tailor_status": "ok", "gaps": ["Kubernetes", "Go"], "review_count": 3, "jd_status": "ok",
    "rank_reason": "tier1 fit",
}


def test_job_row_shape():
    r = sheet.job_row(PICK, "2026-09-23")
    assert len(r) == len(sheet.JOB_HEADERS) == 11
    assert r[0] == "2026-09-23" and r[1] == "Acme" and r[2] == "SWE Intern" and r[3] == "SF, NYC"
    assert r[4] == "Software" and r[5] == "https://acme/jobs/1"
    assert r[6] == "91.3" and r[7] == "May 2028"
    assert r[8] == "Alex_Rivera_Acme_SWE_Intern.pdf"
    assert r[9] == "New"
    assert "gaps: Kubernetes, Go" in r[10] and "review 3" in r[10]


def test_job_row_failed_tailor():
    p = {**PICK, "tailor_status": "failed", "pdf": None, "score": None, "grad": None, "gaps": [], "review_count": None,
         "tailor_error": "boom"}
    r = sheet.job_row(p, "2026-09-23")
    assert r[6] == "" and r[8] == "" and "resume failed" in r[10]


def test_job_row_jd_unavailable():
    p = {**PICK, "jd_status": "failed"}
    assert "JD not fetched" in sheet.job_row(p, "2026-09-23")[10]


def test_job_row_links_drive():
    p = {**PICK, "drive_url": "https://drive.google.com/file/d/1/view"}
    assert sheet.job_row(p, "2026-09-23")[8] == '=HYPERLINK("https://drive.google.com/file/d/1/view", "Alex_Rivera_Acme_SWE_Intern.pdf")'


def test_cut_row_shape():
    cut = {"company": "Eaton", "title": "Data Intern", "url": "https://e/1", "cut_reason": "insurance back office"}
    r = sheet.cut_row(cut, "2026-09-23")
    assert r == ["2026-09-23", "Eaton", "Data Intern", "https://e/1", "insurance back office", ""]
    assert len(r) == len(sheet.CUT_HEADERS)
