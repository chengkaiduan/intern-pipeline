import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sources"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import zero2sudo as z  # noqa: E402


def test_unwrap_link():
    u = "https://l.instagram.com/?u=https%3A%2F%2Fjobs.lever.co%2Facme%2F123%3Flever-source%3DIG&e=AT0x"
    assert z.unwrap_link(u) == "https://jobs.lever.co/acme/123?lever-source=IG"
    assert z.unwrap_link("https://x.com/a") == "https://x.com/a"


def test_to_candidates_link_and_model():
    stories = [
        {"pk": "111", "taken_at": 1, "links": ["https://jobs.lever.co/acme/1"], "image": None, "_file": "111.jpg"},
        {"pk": "222", "taken_at": 2, "links": [], "image": "x", "_file": "222.jpg"},
        {"pk": "333", "taken_at": 3, "links": ["https://linktr.ee/zero2sudo"], "image": None},
    ]
    extracted = [{"file": "222.jpg", "company": "Beta", "title": "SWE Intern", "location": "NYC", "term": "Summer 2027", "url": ""}]
    c = z.to_candidates(stories, extracted, "zero2sudo")
    assert [x["id"] for x in c] == ["ig-111-0", "ig-222-0"]
    assert c[0]["url"] == "https://jobs.lever.co/acme/1" and c[0]["company"] == "Jobs"
    assert c[1]["url"] == "https://www.instagram.com/stories/zero2sudo/222/" and c[1]["title"] == "SWE Intern"
    assert c[1]["locations"] == ["NYC"] and c[1]["source"] == "instagram:zero2sudo"
