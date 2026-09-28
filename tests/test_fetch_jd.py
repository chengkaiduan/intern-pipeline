import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_jd as fj  # noqa: E402

FX = Path(__file__).parent / "fixtures"


def test_detect_greenhouse_board_url():
    kind, info = fj.detect("https://job-boards.greenhouse.io/klaviyocampus/jobs/8002711003")
    assert kind == "greenhouse" and info == {"board": "klaviyocampus", "id": "8002711003"}
    kind, info = fj.detect("https://boards.greenhouse.io/stripe/jobs/123?t=abc")
    assert kind == "greenhouse" and info == {"board": "stripe", "id": "123"}


def test_detect_greenhouse_custom_domain():
    kind, info = fj.detect("https://www.hudsonrivertrading.com/careers/job/?gh_jid=8222414")
    assert kind == "greenhouse"
    assert info["id"] == "8222414"
    assert info["board"] is None
    assert info["domain_guess"] == "hudsonrivertrading"


def test_detect_lever_ashby_workday_generic():
    assert fj.detect("https://jobs.lever.co/plaid/1a2b3c4d-1111-2222-3333-444455556666/apply") == (
        "lever", {"co": "plaid", "id": "1a2b3c4d-1111-2222-3333-444455556666"})
    assert fj.detect("https://jobs.ashbyhq.com/grow-therapy/92bfe88a-4c23-48c8-8f7b-4959ab6cd8d8/application?embed=true") == (
        "ashby", {"co": "grow-therapy", "id": "92bfe88a-4c23-48c8-8f7b-4959ab6cd8d8"})
    kind, info = fj.detect(
        "https://ngc.wd1.myworkdayjobs.com/Northrop_Grumman_External_Site/job/United-States-California-San-Diego/XMLNAME-2027-Software-Engineer-Intern---San-Diego-CA_R10252150")
    assert kind == "workday"
    assert info["api"] == (
        "https://ngc.wd1.myworkdayjobs.com/wday/cxs/ngc/Northrop_Grumman_External_Site/job/"
        "United-States-California-San-Diego/XMLNAME-2027-Software-Engineer-Intern---San-Diego-CA_R10252150")
    kind, info = fj.detect("https://usaa.wd1.myworkdayjobs.com/en-US/USAAJOBSWD/job/San-Antonio/Intern_R0100")
    assert kind == "workday"
    assert info["api"] == "https://usaa.wd1.myworkdayjobs.com/wday/cxs/usaa/USAAJOBSWD/job/San-Antonio/Intern_R0100"
    assert fj.detect("https://eaton.eightfold.ai/careers/job/687239256112")[0] == "generic"


def test_parse_greenhouse_fixture():
    text = fj.parse_greenhouse(json.loads((FX / "greenhouse.json").read_text()))
    assert "People Analytics Co-op" in text
    assert "Klaviyo" in text
    assert "<" not in text and "&lt;" not in text
    assert len(text) > 2000


def test_parse_ashby_fixture():
    text = fj.parse_ashby(json.loads((FX / "ashby.json").read_text()), "92bfe88a-4c23-48c8-8f7b-4959ab6cd8d8")
    assert text.startswith("Software Engineering Intern")
    assert "Grow" in text and len(text) > 1000


def test_parse_ashby_missing_id():
    import pytest
    with pytest.raises(fj.FetchError):
        fj.parse_ashby(json.loads((FX / "ashby.json").read_text()), "nope")


def test_parse_workday_fixture():
    text = fj.parse_workday(json.loads((FX / "workday.json").read_text()))
    assert "2027 Software Engineer Intern" in text
    assert "<p" not in text
    assert "CLEARANCE" in text


def test_parse_lever_shape():
    j = {"text": "SWE Intern", "descriptionPlain": "About us. Build things.",
         "lists": [{"text": "Requirements", "content": "<li>Python</li><li>Go</li>"}],
         "additionalPlain": "Pay: lots"}
    text = fj.parse_lever(j)
    assert text.startswith("SWE Intern")
    assert "Requirements" in text and "Python" in text and "Go" in text and "Pay: lots" in text
    assert "<li>" not in text


def test_extract_generic_html():
    html = "<html><head><title>x</title><style>.a{}</style><script>var a=1;</script></head><body>" \
           "<nav><a>Home</a><a>Jobs</a></nav><main><h1>Software Engineer Intern</h1><p>" + \
           ("We are looking for an intern. Responsibilities include building. Qualifications: CS student. " * 12) + \
           "</p></main><footer>© Co</footer></body></html>"
    text = fj.extract_generic(html)
    assert "Software Engineer Intern" in text
    assert "var a=1" not in text and ".a{}" not in text
    assert fj.looks_like_jd(text)


def test_looks_like_jd_rejects_json_blob():
    blob = '{"a": {"b": "intern responsibilities"}, ' * 60 + "}"
    assert not fj.looks_like_jd(blob)
    assert not fj.looks_like_jd("intern responsibilities qualifications " * 3000)  # absurdly long


def test_looks_like_jd_rejects_nav_page():
    assert not fj.looks_like_jd("Home Jobs About Contact Login " * 40)
    assert not fj.looks_like_jd("intern responsibilities")  # too short


def test_citizenship_only():
    assert fj.citizenship_only("Applicants must be a U.S. citizen due to contract requirements.")
    assert fj.citizenship_only("Active Secret security clearance required")
    assert fj.citizenship_only("US citizenship is required for this role")
    assert not fj.citizenship_only("We sponsor visas. Authorized to work in the US.")
    assert not fj.citizenship_only("CLEARANCE REQUIRED FOR START: No")


def test_html_to_text_lists_and_entities():
    t = fj.html_to_text("<p>Hi&nbsp;there &amp; you</p><ul><li>One</li><li>Two</li></ul>")
    assert "Hi there & you" in t
    assert "- One" in t and "- Two" in t
