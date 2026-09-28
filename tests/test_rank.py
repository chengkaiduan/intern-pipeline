import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rank  # noqa: E402

CANDS = [
    {"slug": "rivian-swe-intern-aaaaaa", "company": "Rivian", "title": "SWE Intern", "locations": ["Palo Alto, CA"],
     "category": "Software", "url": "https://r/1", "terms": ["Summer 2027"], "jd_status": "ok", "citizenship_only": False},
    {"slug": "ngc-swe-intern-bbbbbb", "company": "Northrop Grumman", "title": "SWE Intern", "locations": ["San Diego, CA"],
     "category": "Software", "url": "https://n/1", "terms": [], "jd_status": "ok", "citizenship_only": True},
    {"slug": "eaton-data-intern-cccccc", "company": "Eaton", "title": "Data Intern", "locations": ["Cleveland, OH"],
     "category": "AI/ML/Data", "url": "https://e/1", "terms": ["Summer 2027"], "jd_status": "failed", "citizenship_only": False},
]
CFG = {"tier1": ["Rivian"], "tier2": ["Eaton"], "max_jobs": 10, "close_cuts": 6}


def test_split_hard_drops():
    keep, dropped = rank.split_hard_drops(CANDS)
    assert [c["slug"] for c in keep] == ["rivian-swe-intern-aaaaaa", "eaton-data-intern-cccccc"]
    assert dropped[0]["slug"] == "ngc-swe-intern-bbbbbb" and dropped[0]["reason"] == "citizenship/clearance"


def test_build_rank_input(tmp_path):
    jd = tmp_path / "rivian-swe-intern-aaaaaa.txt"
    jd.write_text("Rivian SWE Intern. " + "Build vehicle software. " * 200)
    cands = [{**CANDS[0], "jd_path": str(jd)}, CANDS[2]]
    text = rank.build_rank_input(cands, CFG)
    assert "rivian-swe-intern-aaaaaa" in text and "[tier1]" in text
    assert "eaton-data-intern-cccccc" in text and "[tier2]" in text and "JD: unavailable" in text
    # excerpt capped
    assert len(text) < 2500


def test_render_prompt():
    p = rank.render_prompt("Target {{MAX_JOBS}} picks {{MIN_PICKS}}-{{MAX_PICKS}} {{CLOSE_CUTS}} cuts\n{{CANDIDATES}}", "LIST", CFG)
    assert p == "Target 10 picks 6-14 6 cuts\nLIST"
    p2 = rank.render_prompt("{{NAME}}|{{PROFILE_SUMMARY}}|{{RANKING_RULES}}", "", {**CFG, "name": "Alex", "summary": " sum \n", "ranking_rules": "- r"})
    assert p2 == "Alex|sum|- r"
    assert rank.pick_band(2) == (1, 3) and rank.pick_band(10) == (6, 14) and rank.pick_band(1) == (1, 1)


def test_parse_rank_output_clean():
    out = '{"picks":[{"slug":"rivian-swe-intern-aaaaaa","reason":"tier1"}],"close_cuts":[{"slug":"eaton-data-intern-cccccc","reason":"meh"}],"notes":"x"}'
    r = rank.parse_rank_output(out, {c["slug"] for c in CANDS})
    assert r["picks"][0]["slug"] == "rivian-swe-intern-aaaaaa"
    assert r["close_cuts"][0]["reason"] == "meh"


def test_parse_rank_output_with_prose_and_fence():
    out = 'Here you go:\n```json\n{"picks":[{"slug":"rivian-swe-intern-aaaaaa","reason":"a"}],"close_cuts":[]}\n```\nthanks'
    r = rank.parse_rank_output(out, {c["slug"] for c in CANDS})
    assert len(r["picks"]) == 1


def test_parse_rank_output_unknown_slug():
    out = '{"picks":[{"slug":"nope","reason":"a"}],"close_cuts":[]}'
    with pytest.raises(rank.RankParseError):
        rank.parse_rank_output(out, {c["slug"] for c in CANDS})


def test_parse_rank_output_missing_key():
    with pytest.raises(rank.RankParseError):
        rank.parse_rank_output('{"picks":[]}', set())
    with pytest.raises(rank.RankParseError):
        rank.parse_rank_output('no json here', set())


def test_parse_rank_output_dedupes_and_drops_pick_from_cuts():
    out = '{"picks":[{"slug":"rivian-swe-intern-aaaaaa","reason":"a"},{"slug":"rivian-swe-intern-aaaaaa","reason":"b"}],' \
          '"close_cuts":[{"slug":"rivian-swe-intern-aaaaaa","reason":"c"},{"slug":"eaton-data-intern-cccccc","reason":"d"}]}'
    r = rank.parse_rank_output(out, {c["slug"] for c in CANDS})
    assert [p["slug"] for p in r["picks"]] == ["rivian-swe-intern-aaaaaa"]
    assert [p["slug"] for p in r["close_cuts"]] == ["eaton-data-intern-cccccc"]


def test_assemble_picks_enriches():
    parsed = {"picks": [{"slug": "rivian-swe-intern-aaaaaa", "reason": "a"}],
              "close_cuts": [{"slug": "eaton-data-intern-cccccc", "reason": "d"}], "notes": "n"}
    _, dropped = rank.split_hard_drops(CANDS)
    out = rank.assemble_picks(parsed, CANDS, dropped, "2026-09-23")
    assert out["date"] == "2026-09-23"
    assert out["picks"][0]["company"] == "Rivian" and out["picks"][0]["rank_reason"] == "a"
    assert out["close_cuts"][0]["company"] == "Eaton"
    assert out["dropped_hard"][0]["company"] == "Northrop Grumman"
