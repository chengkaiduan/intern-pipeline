import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scan  # noqa: E402

CFG = {
    "categories": ["Software", "AI/ML/Data", "Product"],
    "title_exclude_regex": r"\b(MS|M\.S\.|PhD|Ph\.D\.|MBA|Master'?s|Graduate)\b",
    "window_hours_max": 72,
}

NOW = 1_790_200_000


def row(**kw):
    base = {
        "id": "abcdef123456",
        "active": True,
        "category": "Software",
        "company_name": "Rivian",
        "title": "Software Engineer Intern - PDP",
        "locations": ["Palo Alto, CA"],
        "url": "https://x/y",
        "date_posted": NOW - 3600,
        "degrees": ["Bachelor's"],
        "terms": ["Summer 2027"],
        "sponsorship": "Other",
    }
    base.update(kw)
    return base


def test_us_in_person():
    assert scan.is_us_in_person(["Palo Alto, CA"])
    assert scan.is_us_in_person(["NYC"])
    assert scan.is_us_in_person(["SF"])
    assert scan.is_us_in_person(["United States"])
    assert scan.is_us_in_person(["SF", "Remote"])
    assert not scan.is_us_in_person(["Remote"])
    assert not scan.is_us_in_person(["Remote in USA"])
    assert not scan.is_us_in_person(["London, UK"])
    assert not scan.is_us_in_person(["Toronto, ON, Canada"])
    assert not scan.is_us_in_person(["Bangalore, India"])
    assert not scan.is_us_in_person([])


def test_title_excluded():
    pat = CFG["title_exclude_regex"]
    assert scan.title_excluded("Machine Learning Engineer Intern - MS/PhD", pat)
    assert scan.title_excluded("MBA Intern Co-op", pat)
    assert scan.title_excluded("Graduate Software Intern", pat)
    assert not scan.title_excluded("Software Engineer Intern", pat)
    assert not scan.title_excluded("Systems Intern", pat)  # 'ms' inside word


def test_degrees_ok():
    assert scan.degrees_ok([])
    assert scan.degrees_ok(["Bachelor's"])
    assert scan.degrees_ok(["Bachelor's", "Master's"])
    assert not scan.degrees_ok(["Master's"])
    assert not scan.degrees_ok(["PhD"])


def test_filter_listings_stages():
    rows = [
        row(id="keep00000001"),
        row(id="seen00000002"),
        row(id="old000000003", date_posted=NOW - 100 * 3600),
        row(id="hw0000000004", category="Hardware"),
        row(id="inactive0005", active=False),
        row(id="remote000006", locations=["Remote"]),
        row(id="phd000000007", title="Research Intern - PhD"),
        row(id="msonly000008", degrees=["Master's"]),
        row(id="uk0000000009", locations=["London, UK"]),
    ]
    cands, counts = scan.filter_listings(rows, CFG, seen={"seen00000002"}, since_ts=NOW - 24 * 3600, now_ts=NOW)
    assert [c["id"] for c in cands] == ["keep00000001"]
    assert counts["total"] == 9
    assert counts["kept"] == 1
    assert counts["dropped_seen"] == 1
    assert counts["dropped_window"] == 1
    assert counts["dropped_category"] == 1
    assert counts["dropped_inactive"] == 1
    assert counts["dropped_location"] == 2
    assert counts["dropped_title"] == 1
    assert counts["dropped_degrees"] == 1


def test_since_ts_clamped_to_window_max():
    # since_ts older than window_hours_max gets clamped
    rows = [row(id="a" * 12, date_posted=NOW - 80 * 3600)]
    cands, _ = scan.filter_listings(rows, CFG, seen=set(), since_ts=NOW - 200 * 3600, now_ts=NOW)
    assert cands == []


def test_slug_for():
    r = row(id="9f8e7d6c5b4a", company_name="Hudson River Trading", title="Software Engineer Intern (Summer 2027)")
    s = scan.slug_for(r)
    assert s.startswith("hudson-river-trading-software-engineer-intern")
    assert s.endswith("-6c5b4a")
    assert s == s.lower()
    assert "(" not in s and " " not in s


def test_candidate_shape():
    cands, _ = scan.filter_listings([row()], CFG, seen=set(), since_ts=NOW - 24 * 3600, now_ts=NOW)
    c = cands[0]
    assert c["slug"].endswith("-123456")
    for k in ("id", "company", "title", "locations", "category", "url", "date_posted", "degrees", "terms"):
        assert k in c


def test_load_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("max_jobs: 10\ncategories: [Software]\n")
    cfg = scan.load_config(p)
    assert cfg["max_jobs"] == 10
