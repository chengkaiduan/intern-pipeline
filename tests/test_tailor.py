import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tailor  # noqa: E402


def test_pdf_name_sanitizes():
    assert tailor.pdf_name("Alex_Rivera", "Hudson River Trading", "Software Engineer Intern (Summer 2027)") == \
        "Alex_Rivera_Hudson_River_Trading_Software_Engineer_Intern_Summer_2027.pdf"
    assert tailor.pdf_name("Alex Rivera", "ByteDance", "Product Management Project Intern - Global Payment") == \
        "Alex_Rivera_ByteDance_Product_Management_Project_Intern_Global_Payment.pdf"


def test_pdf_name_caps_length():
    n = tailor.pdf_name("Alex_Rivera", "A" * 60, "B" * 60)
    assert n.endswith(".pdf") and len(n) <= 80


def test_extract_result_line():
    out = "Doing stuff...\nScore: 91\n" \
          '{"score": 91.2, "required": "7/8", "preferred": "3/5", "grad": "May 2028", "gaps": ["Kubernetes"], "review_count": 3, "pdf": "jobs/x/y.pdf"}\n'
    r = tailor.extract_result_line(out)
    assert r["score"] == 91.2 and r["gaps"] == ["Kubernetes"] and r["review_count"] == 3


def test_extract_result_line_ignores_non_result_json():
    out = '{"foo": 1}\nsome text\n{"score": 80, "required": "1/2"}\n{"bar": 2}\n'
    assert tailor.extract_result_line(out)["score"] == 80


def test_extract_result_line_missing():
    assert tailor.extract_result_line("no json at all") is None


CFG = {"pdf_prefix": "Alex_Rivera", "resume_dir": str(tailor.ROOT / "resume"), "jobs_root": str(tailor.ROOT / "resume" / "jobs")}


def test_render_prompt_fills_placeholders():
    pick = {"slug": "acme-swe-1a2b3c", "company": "Acme", "title": "SWE Intern", "locations": ["SF"], "url": "https://a",
            "jd_status": "ok"}
    p = tailor.render_prompt("{{SLUG}}|{{COMPANY}}|{{TITLE}}|{{LOCATIONS}}|{{URL}}|{{PDF_NAME}}|{{JOB_DIR}}|{{RESUME_DIR}}|{{JD_NOTE}}", pick, CFG)
    assert p.startswith("acme-swe-1a2b3c|Acme|SWE Intern|SF|https://a|Alex_Rivera_Acme_SWE_Intern.pdf|resume/jobs/acme-swe-1a2b3c|resume|")
    assert p.endswith("|")  # empty JD note when JD ok
    pick["jd_status"] = "failed"
    assert "could not be fetched" in tailor.render_prompt("{{JD_NOTE}}", pick, CFG)


def test_is_quota_error():
    assert tailor.is_quota_error("Error: You've hit your usage limit. Resets at 5pm")
    assert tailor.is_quota_error("rate limit exceeded")
    assert tailor.is_quota_error("out of extra usage")
    assert not tailor.is_quota_error("rendered resume.pdf, score 92")


def test_classify_run():
    ok = tailor.classify_run(returncode=0, stdout='{"score": 90, "required": "1/1"}', pdf_exists=True)
    assert ok["tailor_status"] == "ok" and ok["score"] == 90
    no_pdf = tailor.classify_run(returncode=0, stdout='{"score": 90}', pdf_exists=False)
    assert no_pdf["tailor_status"] == "failed" and "pdf" in no_pdf["tailor_error"]
    no_json = tailor.classify_run(returncode=0, stdout="hello", pdf_exists=True)
    assert no_json["tailor_status"] == "ok" and no_json["score"] is None  # PDF is what matters
    with pytest.raises(tailor.QuotaError):
        tailor.classify_run(returncode=1, stdout="You've hit your usage limit", pdf_exists=False)


def test_stage_job_dir_copies_jd(tmp_path):
    jd = tmp_path / "x.txt"
    jd.write_text("the jd")
    d = tailor.stage_job_dir({"slug": "acme-1", "jd_status": "ok", "jd_path": str(jd)}, tmp_path / "jobs")
    assert d == tmp_path / "jobs" / "acme-1" and (d / "jd.txt").read_text() == "the jd"
    d2 = tailor.stage_job_dir({"slug": "beta-2", "jd_status": "failed", "jd_path": None}, tmp_path / "jobs")
    assert d2.exists() and not (d2 / "jd.txt").exists()


def test_run_with_deadline_kills_on_timeout():
    import time
    t0 = time.time()
    rc, out, err = tailor.run_with_deadline(["sh", "-c", "sleep 30; echo late"], "", 1)
    assert rc == 124 and "late" not in out and time.time() - t0 < 10


def test_run_with_deadline_passes_stdin_and_output():
    rc, out, err = tailor.run_with_deadline(["cat"], "hello", 5)
    assert rc == 0 and out == "hello"

