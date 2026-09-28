#!/usr/bin/env python3
"""Tests for the ATS simulator. Run: python3 -m unittest -v test_ats_scan"""

import json
import tempfile
import unittest
from pathlib import Path

import ats_scan as ats

SAMPLE_JD = """\
Software Engineer Intern, Summer 2027

About the role
You'll build backend services that power our recommendation system.

Minimum qualifications
- Currently pursuing a BS in Computer Science or related field
- Proficiency in Python or Java
- Experience with SQL and relational databases
- Must have 2+ years of programming experience

Preferred qualifications
- Familiarity with Kubernetes and Docker
- Exposure to machine learning or RAG pipelines
- Nice to have: React experience
"""


def write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(body, encoding="utf-8")
    return path


class TestJDAnalysis(unittest.TestCase):
    def setUp(self):
        self.spec = ats.analyze_jd(SAMPLE_JD)

    def test_required_terms_land_in_required(self):
        for term in ("python", "java", "sql"):
            self.assertIn(term, self.spec.required, f"{term} should be required")

    def test_preferred_terms_land_in_preferred(self):
        for term in ("kubernetes", "docker", "react"):
            self.assertIn(term, self.spec.preferred, f"{term} should be preferred")
            self.assertNotIn(term, self.spec.required)

    def test_buckets_are_disjoint(self):
        self.assertEqual(self.spec.required & self.spec.preferred, set())

    def test_years_of_experience_extracted(self):
        self.assertTrue(any(entry["years"] == 2 for entry in self.spec.years_required))

    def test_sophomore_targeting_detected(self):
        self.assertFalse(self.spec.targets_sophomores)
        soph = ats.analyze_jd("Open to sophomores and second-year students.")
        self.assertTrue(soph.targets_sophomores)

    def test_postings_without_a_preferred_section_are_all_required(self):
        spec = ats.analyze_jd("We need Python and Docker.")
        self.assertIn("python", spec.required)
        self.assertIn("docker", spec.required)
        self.assertEqual(spec.preferred, set())


class TestFalsePositives(unittest.TestCase):
    """Words that look like skills but aren't, drawn from real postings."""

    def test_looking_is_not_the_bi_tool_looker(self):
        self.assertNotIn("looker", ats.analyze_jd("We are looking for interns.").required)

    def test_recommendations_is_not_a_recommender_system(self):
        spec = ats.analyze_jd("Synthesize insights to develop recommendations.")
        self.assertNotIn("recommender", spec.required | spec.preferred)

    def test_company_name_express_is_not_the_framework(self):
        spec = ats.analyze_jd("American Express serves millions of business customers.")
        self.assertNotIn("express", spec.required | spec.preferred)
        self.assertNotIn("express.js", spec.required | spec.preferred)

    def test_business_vocabulary_is_still_captured(self):
        spec = ats.analyze_jd(
            "Develop business cases for new products. Analyze market trends and the "
            "competitive landscape to inform product strategy. Maintain product backlogs."
        )
        for term in ("business case", "market trends", "competitive landscape",
                     "product strategy", "product backlog"):
            self.assertIn(term, spec.required, f"{term} should be captured")


class TestMatching(unittest.TestCase):
    def match(self, term, resume_text):
        hay = ats.normalize(resume_text)
        stems = {ats.stem(w) for w in hay.split()}
        return ats.match_term(term, hay, stems)

    def test_exact(self):
        self.assertEqual(self.match("python", "Built tools in Python."), (True, "exact"))

    def test_acronym_expands(self):
        hit, tier = self.match("rag", "retrieval-augmented generation pipeline")
        self.assertTrue(hit)
        self.assertEqual(tier, "acronym")

    def test_expansion_credits_acronym(self):
        hit, tier = self.match("machine learning", "ML-powered ranking")
        self.assertTrue(hit)
        self.assertEqual(tier, "acronym")

    def test_stem_match(self):
        hit, tier = self.match("testing", "Wrote 186 tests against Postgres.")
        self.assertTrue(hit)
        self.assertEqual(tier, "stem")

    def test_synonym_match(self):
        hit, tier = self.match("recommendation system", "built a ranking engine")
        self.assertTrue(hit)
        self.assertEqual(tier, "synonym")

    def test_no_false_positive_on_substring(self):
        hit, _ = self.match("java", "I write JavaScript all day.")
        self.assertFalse(hit, "java must not match inside javascript")

    def test_missing_term_is_missing(self):
        hit, _ = self.match("kubernetes", "Deployed on Vercel.")
        self.assertFalse(hit)


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_required_outweighs_preferred(self):
        spec = ats.analyze_jd(SAMPLE_JD)
        hits_required = write(self.tmp, "req.txt",
                              "EDUCATION\nEXPERIENCE\nSKILLS\nme@x.edu\nPython Java SQL databases")
        hits_preferred = write(self.tmp, "pref.txt",
                               "EDUCATION\nEXPERIENCE\nSKILLS\nme@x.edu\nKubernetes Docker React")
        req_score = ats.score(spec, hits_required)["match_pct"]
        pref_score = ats.score(spec, hits_preferred)["match_pct"]
        self.assertGreater(req_score, pref_score)

    def test_perfect_resume_scores_high(self):
        spec = ats.analyze_jd(SAMPLE_JD)
        body = ("EDUCATION\nEXPERIENCE\nSKILLS\nme@x.edu\n"
                + " ".join(sorted(spec.required | spec.preferred)))
        result = ats.score(spec, write(self.tmp, "all.txt", body))
        self.assertGreaterEqual(result["match_pct"], 95.0)
        self.assertEqual(result["missing_required"], [])

    def test_empty_resume_scores_zero(self):
        spec = ats.analyze_jd(SAMPLE_JD)
        result = ats.score(spec, write(self.tmp, "empty.txt", "nothing relevant here"))
        self.assertEqual(result["match_pct"], 0.0)
        self.assertTrue(result["missing_required"])


class TestFormatChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def html(self, body: str) -> Path:
        return write(self.tmp, "r.html", f"<html><body>{body}</body></html>")

    def test_table_flagged(self):
        path = self.html("<table><tr><td>Experience</td></tr></table>")
        warnings = ats.check_format(path, path.read_text(), ats.read_document(path))
        self.assertTrue(any("table" in w for w in warnings))

    def test_missing_sections_flagged(self):
        path = self.html("<p>Just some prose.</p>")
        warnings = ats.check_format(path, path.read_text(), ats.read_document(path))
        self.assertTrue(any("EXPERIENCE" in w for w in warnings))
        self.assertTrue(any("EDUCATION" in w for w in warnings))
        self.assertTrue(any("SKILLS" in w for w in warnings))

    def test_clean_resume_has_no_section_warnings(self):
        path = self.html(
            "<h2>EDUCATION</h2><p>Berkeley</p>"
            "<h2>EXPERIENCE</h2><p>Aug 2025 - May 2026 Google</p>"
            "<h2>SKILLS</h2><p>Python</p><p>me@berkeley.edu</p>"
        )
        warnings = ats.check_format(path, path.read_text(), ats.read_document(path))
        self.assertEqual([w for w in warnings if "section header" in w], [])

    def test_missing_email_flagged(self):
        path = self.html("<h2>EDUCATION</h2><h2>EXPERIENCE</h2><h2>SKILLS</h2>")
        warnings = ats.check_format(path, path.read_text(), ats.read_document(path))
        self.assertTrue(any("email" in w for w in warnings))

    def test_mixed_date_formats_flagged(self):
        path = self.html(
            "<h2>EDUCATION</h2><h2>EXPERIENCE</h2><h2>SKILLS</h2>"
            "<p>me@x.edu Aug 2025 - Dec 2025 and 06/2025 and 2021 - 2023</p>"
        )
        warnings = ats.check_format(path, path.read_text(), ats.read_document(path))
        self.assertTrue(any("date format" in w for w in warnings))


class TestLigatureDetector(unittest.TestCase):
    def test_real_words_do_not_fire(self):
        for word in ("flows", "workflows", "follows", "windows", "shadows"):
            self.assertEqual(ats.LIGATURE_CASUALTIES.findall(word), [], f"{word} is a real word")

    def test_damaged_words_fire(self):
        for word in ("workows", "specication", "classication"):
            self.assertTrue(ats.LIGATURE_CASUALTIES.findall(word), f"{word} is ligature damage")


class TestTextUtilities(unittest.TestCase):
    def test_html_text_extraction_drops_markup(self):
        tmp = Path(tempfile.mkdtemp())
        path = write(tmp, "x.html", "<p>Python</p><style>p{color:red}</style><script>1</script>")
        text = ats.read_document(path)
        self.assertIn("Python", text)
        self.assertNotIn("color", text)
        self.assertNotIn("script", text.lower())

    def test_adjacent_inline_tags_do_not_glue_words(self):
        tmp = Path(tempfile.mkdtemp())
        path = write(tmp, "y.html",
                     "<div><span>Product Manager</span><span>Berkeley, CA</span></div>")
        text = ats.read_document(path)
        self.assertIn("Manager", text)
        self.assertNotIn("ManagerBerkeley", text)

    def test_stem_is_stable(self):
        self.assertEqual(ats.stem("testing"), ats.stem("tests"))
        self.assertEqual(ats.stem("engineering"), ats.stem("engineer"))

    def test_plurals_reach_singular_lexicon_entries(self):
        self.assertEqual(ats.stem("pipelines"), ats.stem("pipeline"))
        spec = ats.analyze_jd("Build and maintain data pipelines for our systems.")
        self.assertIn("data pipeline", spec.required)


if __name__ == "__main__":
    unittest.main()
