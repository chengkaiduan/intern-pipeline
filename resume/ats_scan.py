#!/usr/bin/env python3
"""Deterministic applicant-tracking-system simulator.

No model involved. Two modes:

    ats_scan.py --jd jd.txt                      what the scanner will look for
    ats_scan.py --jd jd.txt --resume resume.html how well a resume answers it

Prints JSON on stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# --------------------------------------------------------------------------- #
# Lexicon
# --------------------------------------------------------------------------- #

# Acronym <-> expansion. Matching either form credits both.
ACRONYMS = {
    "rag": "retrieval-augmented generation",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "cnn": "convolutional neural network",
    "llm": "large language model",
    "ts": "typescript",
    "js": "javascript",
    "k8s": "kubernetes",
    "ci/cd": "continuous integration",
    "gcp": "google cloud platform",
    "aws": "amazon web services",
    "api": "application programming interface",
    "sql": "structured query language",
    "ui": "user interface",
    "ux": "user experience",
    "kpi": "key performance indicator",
    "gtm": "go-to-market",
    "pm": "product management",
    "oop": "object-oriented programming",
    "rest": "restful",
    "ocr": "optical character recognition",
    "etl": "extract transform load",
    "rls": "row-level security",
    "a/b": "experimentation",
    "saas": "software as a service",
    "mvp": "minimum viable product",
    "aum": "assets under management",
    "esg": "environmental social governance",
}

# Words that mean the same thing to a human and different things to a matcher.
SYNONYM_SETS = [
    {"recommendation system", "recommender", "recsys", "ranking engine", "personalization"},
    {"backend", "back-end", "server-side"},
    {"frontend", "front-end", "client-side"},
    {"full stack", "fullstack", "full-stack"},
    {"distributed systems", "scalable systems", "high-scale"},
    {"data pipeline", "etl", "ingestion pipeline", "data engineering"},
    {"unit test", "automated test", "test coverage", "testing"},
    {"agile", "scrum", "sprint"},
    {"stakeholder", "cross-functional", "cross functional"},
    {"market research", "competitive analysis", "market analysis", "benchmarking"},
    {"financial modeling", "valuation", "equity research"},
    {"product roadmap", "roadmap", "prioritization"},
    {"experimentation", "a/b testing", "ab testing"},
    {"microservices", "service oriented", "distributed services"},
    {"real-time", "realtime", "low-latency"},
    {"mobile development", "ios", "android", "mobile app"},
    {"database", "postgres", "postgresql", "mysql", "rdbms"},
    {"cloud", "aws", "gcp", "azure"},
    {"version control", "git", "github"},
    {"customer segmentation", "user research", "persona"},
]

# Terms worth crediting when they appear. Multi-word entries are matched as phrases.
SKILL_LEXICON = {
    # languages / runtimes
    "python", "java", "javascript", "typescript", "swift", "kotlin", "c++", "c#", "go", "golang",
    "rust", "ruby", "php", "scala", "r", "matlab", "sql", "scheme", "objective-c", "dart",
    # frameworks
    "react", "next.js", "nextjs", "node", "node.js", "django", "flask", "fastapi", "spring",
    # "express" is deliberately spelled express.js — bare "Express" is American Express,
    # Federal Express, and half the payments industry.
    "rails", "angular", "vue", "svelte", "swiftui", "uikit", "flutter", "express.js", "deno",
    "tensorflow", "pytorch", "keras", "scikit-learn", "pandas", "numpy", "spark", "hadoop",
    # infra
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "postgres", "postgresql",
    "mysql", "mongodb", "redis", "kafka", "graphql", "rest", "grpc", "supabase", "firebase",
    "vercel", "git", "github", "gitlab", "jenkins", "ci/cd", "linux",
    # ml / data
    "machine learning", "deep learning", "neural network", "nlp", "computer vision",
    "recommendation system", "recommender", "ranking", "embeddings", "llm", "rag",
    "data pipeline", "etl", "data analysis", "statistics", "a/b testing", "experimentation",
    "feature engineering", "model training", "inference", "fine-tuning", "prompt engineering",
    # engineering practice
    "backend", "frontend", "full stack", "real-time", "concurrency", "latency",
    "api", "microservices", "distributed systems", "scalability", "performance", "testing",
    "unit test", "integration test", "code review", "debugging", "refactoring", "agile",
    "scrum", "system design", "architecture", "security", "authentication", "authorization",
    # product / business
    "product management", "product strategy", "product roadmap", "roadmap", "prioritization",
    "product backlog", "backlog", "business case", "customer needs", "customer experience",
    "customer feedback", "market trends", "competitive landscape", "digital products",
    "user research", "stakeholder", "cross-functional", "go-to-market", "gtm",
    "market research", "competitive analysis", "financial modeling", "financial analysis",
    "valuation", "forecasting", "kpi", "metrics", "segmentation", "pricing", "positioning",
    "business analysis", "consulting", "strategy", "due diligence", "project management",
    "payments", "commercial", "revenue growth", "revenue retention", "analytics",
    "excel", "powerpoint", "tableau", "looker", "sql analysis", "dashboards",
    # soft
    "communication", "leadership", "mentoring", "collaboration", "presentation",
    "problem solving", "ownership",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "to", "of", "in", "on", "at", "by",
    "from", "as", "is", "are", "be", "been", "being", "was", "were", "will", "would", "should",
    "could", "can", "may", "might", "must", "have", "has", "had", "do", "does", "did", "you",
    "your", "we", "our", "us", "they", "their", "it", "its", "this", "that", "these", "those",
    "who", "what", "when", "where", "how", "why", "all", "any", "each", "more", "most", "other",
    "some", "such", "no", "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "about", "into", "through", "during", "up", "out", "if", "then", "there", "here", "also",
    "work", "working", "team", "teams", "role", "job", "position", "company", "candidate",
    "candidates", "opportunity", "experience", "years", "year", "new", "help", "like", "well",
    "including", "etc", "ability", "strong", "excellent", "good", "great", "plus", "across",
}

PREFERRED_HEADER = re.compile(
    r"(nice[- ]to[- ]have|preferred|bonus|plus(?:es)?|desired|ideal(?:ly)?|"
    r"a plus|we'?d love|even better|not required)",
    re.I,
)
REQUIRED_HEADER = re.compile(
    r"(requirement|qualification|must[- ]have|minimum|basic qualification|what you'?ll need|"
    r"what we'?re looking for|you have|required)",
    re.I,
)
REQUIRED_MODAL = re.compile(r"\b(must|required|require|proficien|expert|strong)\b", re.I)
PREFERRED_MODAL = re.compile(r"\b(preferred|ideally|nice to have|bonus|familiar|exposure)\b", re.I)

YOE = re.compile(r"(\d+)\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)\b", re.I)

SOPHOMORE = re.compile(
    r"\b(sophomore|second[- ]year|2nd[- ]year|first[- ]or[- ]second[- ]year|"
    r"freshman|underclass)\w*\b",
    re.I,
)

SECTION_HEADERS = {
    "education", "experience", "work experience", "professional experience", "employment",
    "skills", "technical skills", "projects", "leadership", "awards", "certifications",
    "publications", "summary", "objective", "activities",
}


# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #

SUFFIXES = ("ization", "ations", "ation", "ements", "ement", "ingly",
            "ings", "ing", "edly", "ers", "er", "ied", "ed", "ly")


def _depluralize(w: str) -> str:
    """Plurals need their own rule: blind "es" stripping turns "pipelines" into
    "pipelin", which then never matches "pipeline"."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    # Only true sibilant plurals lose the whole "es". Blanket "ses" stripping turns
    # "cases" into "cas", which then never matches "case".
    if len(w) > 4 and w.endswith(("sses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def stem(word: str) -> str:
    """Cheap suffix stripper, applied to a fixed point.

    Iterating matters: "engineering" -> "engineer" -> "engine" has to land on the same
    stem as "engineer" -> "engine", or the two never match each other.
    """
    w = _depluralize(word.lower())
    for _ in range(3):
        for suffix in SUFFIXES:
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                w = _depluralize(w[: -len(suffix)])
                break
        else:
            break
    return w


def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9+#./'\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Keep interior punctuation (node.js, ci/cd, next.js) but drop the trailing kind that
    # sentence endings leave behind, or "docker." never matches "docker".
    return " ".join(tok.strip(".'-/") or tok for tok in text.split())


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t]


def ngrams(words: list[str], n: int) -> list[str]:
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


# Tags that end a line of text. Without these the whole document collapses onto one
# line and section-header detection (which anchors to line starts) can never fire.
BLOCK_TAGS = {"p", "div", "section", "article", "li", "ul", "ol", "br", "tr", "td", "th",
              "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "table", "hr"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        else:
            # Inline tags still separate words. Without this, two adjacent spans render as
            # "Product ManagerBerkeley" and neither word matches anything.
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.parts.append("\n" if tag in BLOCK_TAGS else " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        else:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        joined = "".join(self.parts)
        return re.sub(r"[ \t]*\n[ \t]*", "\n", joined)


def read_document(path: Path) -> str:
    """Text of an .html, .pdf, .txt, or .md file."""
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("pypdf required to scan a PDF: pip3 install pypdf")
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        parser = _TextExtractor()
        parser.feed(raw)
        return parser.text()
    return raw


# --------------------------------------------------------------------------- #
# Job description analysis
# --------------------------------------------------------------------------- #

@dataclass
class JobSpec:
    required: set[str] = field(default_factory=set)
    preferred: set[str] = field(default_factory=set)
    years_required: list[dict] = field(default_factory=list)
    targets_sophomores: bool = False
    raw_lines: int = 0

    def to_dict(self) -> dict:
        return {
            "required": sorted(self.required),
            "preferred": sorted(self.preferred),
            "years_required": self.years_required,
            "targets_sophomores": self.targets_sophomores,
        }


def _stem_phrase(phrase: str) -> str:
    return " ".join(stem(w) for w in phrase.split())


# "data pipelines" in a posting has to find "data pipeline" in the lexicon, so look the
# lexicon up by stem as well as literally. Canonical spelling is what gets reported.
STEMMED_LEXICON = {_stem_phrase(term): term for term in sorted(SKILL_LEXICON)}


def _phrases_in(line: str) -> set[str]:
    """Lexicon terms present in a line, longest match wins."""
    norm = normalize(line)
    words = norm.split()
    found: set[str] = set()
    for n in (3, 2, 1):
        for gram in ngrams(words, n):
            if gram in SKILL_LEXICON or gram in ACRONYMS:
                found.add(gram)
            elif n == 1:
                # Single words get depluralized, never fully stemmed. Stemming one word
                # collapses unrelated vocabulary: "looking" -> "look" would match the BI
                # tool Looker, and "recommendations" would match "recommender".
                singular = _depluralize(gram)
                if singular in SKILL_LEXICON:
                    found.add(singular)
            elif _stem_phrase(gram) in STEMMED_LEXICON:
                found.add(STEMMED_LEXICON[_stem_phrase(gram)])
    # Salvage capitalized proper nouns the lexicon has never heard of (product names,
    # in-house tools). Single tokens only, and only if they look like technology.
    for raw_word in re.findall(r"\b[A-Z][A-Za-z0-9+.#]{2,}\b", line):
        low = raw_word.lower()
        if low in STOPWORDS or low in found:
            continue
        if re.search(r"[0-9+.#]", raw_word) or raw_word.isupper():
            found.add(low)
    return found


def analyze_jd(text: str) -> JobSpec:
    spec = JobSpec()
    lines = [ln.strip() for ln in text.splitlines()]
    spec.raw_lines = len(lines)
    bucket = "required"  # postings that never say "preferred" are treated as all-required

    for line in lines:
        if not line:
            continue
        header_like = len(line) < 80 and not line.endswith(".")
        if header_like and PREFERRED_HEADER.search(line):
            bucket = "preferred"
        elif header_like and REQUIRED_HEADER.search(line):
            bucket = "required"

        line_bucket = bucket
        if PREFERRED_MODAL.search(line):
            line_bucket = "preferred"
        elif REQUIRED_MODAL.search(line):
            line_bucket = "required"

        found = _phrases_in(line)
        target = spec.required if line_bucket == "required" else spec.preferred
        target |= found

        for match in YOE.finditer(line):
            spec.years_required.append({
                "years": int(match.group(1)),
                "context": line[:120],
                "bucket": line_bucket,
            })

        if SOPHOMORE.search(line):
            spec.targets_sophomores = True

    spec.preferred -= spec.required
    return spec


# --------------------------------------------------------------------------- #
# Resume scoring
# --------------------------------------------------------------------------- #

MATCH_TIERS = {"exact": 1.0, "stem": 0.85, "synonym": 0.7, "acronym": 1.0}
WEIGHT_REQUIRED = 3.0
WEIGHT_PREFERRED = 1.0


def _synonyms_of(term: str) -> set[str]:
    out: set[str] = set()
    for group in SYNONYM_SETS:
        if term in group:
            out |= group - {term}
    return out


def _variants(term: str) -> set[str]:
    """Every surface form that should credit `term`."""
    out = {term}
    if term in ACRONYMS:
        out.add(ACRONYMS[term])
    for acronym, expansion in ACRONYMS.items():
        if term == expansion:
            out.add(acronym)
    return out


def match_term(term: str, haystack: str, haystack_stems: set[str]) -> tuple[bool, str]:
    """Does the resume credit `term`? Returns (matched, tier)."""
    for variant in _variants(term):
        if re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", haystack):
            return True, "exact" if variant == term else "acronym"

    term_stems = {stem(w) for w in term.split() if w not in STOPWORDS}
    if term_stems and term_stems <= haystack_stems:
        return True, "stem"

    for synonym in _synonyms_of(term):
        if re.search(rf"(?<![a-z0-9]){re.escape(synonym)}(?![a-z0-9])", haystack):
            return True, "synonym"

    return False, ""


HTML_FORMAT_CHECKS = [
    (re.compile(r"<table", re.I), "table element — many parsers flatten or drop table content"),
    (re.compile(r"<img", re.I), "image element — text inside images is invisible to the scanner"),
    (re.compile(r"column-count|columns\s*:", re.I), "multi-column CSS — parsers read across columns"),
    (re.compile(r"<header|<footer", re.I), "header/footer element — often stripped before parsing"),
    (re.compile(r"position\s*:\s*absolute", re.I), "absolutely positioned text — reading order unreliable"),
    (re.compile(r"font-size\s*:\s*(?:[0-9]|10)(?:\.\d+)?px", re.I), "text under ~10pt — hurts human readers"),
]


def check_format(path: Path, raw: str, text: str) -> list[str]:
    warnings: list[str] = []
    if path.suffix.lower() in (".html", ".htm"):
        for pattern, message in HTML_FORMAT_CHECKS:
            if pattern.search(raw):
                warnings.append(message)

    lower = text.lower()
    present = {h for h in SECTION_HEADERS if re.search(rf"(?m)^\W*{re.escape(h)}\b", lower)}
    if not present & {"experience", "work experience", "professional experience", "employment"}:
        warnings.append("no recognizable EXPERIENCE section header")
    if "education" not in present:
        warnings.append("no recognizable EDUCATION section header")
    if not present & {"skills", "technical skills"}:
        warnings.append("no recognizable SKILLS section header")

    date_styles = {
        "month_year": len(re.findall(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}", lower)),
        "numeric": len(re.findall(r"\b\d{1,2}/\d{4}\b", text)),
        "year_only": len(re.findall(r"(?<![/\w])\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}\b", text)),
    }
    if sum(1 for count in date_styles.values() if count) > 1:
        warnings.append(f"mixed date formats {date_styles} — normalize to one style")

    if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        warnings.append("no email address found in extracted text")

    return warnings


# Words that appear when an f-ligature fails to survive PDF text extraction — the bug that
# turns "workflows" into "workows". Matched whole-word: "flows" is a real word and must not fire.
LIGATURE_CASUALTIES = re.compile(
    r"(?<![a-z])(workow|workows|ow|ows|specication|specications|classication|bene t|"
    r"con guration|identi ed|signi cant|rst|nd|eld|elds)(?![a-z])"
)


def check_extraction(pdf_path: Path, credited: list[str]) -> dict:
    """Pull text back out of the rendered PDF and confirm credited keywords survived.

    A term credited on a synonym or stem tier has to be re-checked the same way — asking
    for its literal spelling in the PDF would flag every non-exact match as lost.
    """
    if not pdf_path.exists():
        return {"ran": False, "reason": f"{pdf_path} not found"}

    text = normalize(read_document(pdf_path))
    text_stems = {stem(w) for w in text.split()}

    lost = [term for term in credited if not match_term(term, text, text_stems)[0]]
    damage = LIGATURE_CASUALTIES.findall(text)

    return {
        "ran": True,
        "lost_in_extraction": lost,
        "ligature_damage": sorted(set(damage))[:10],
    }


def score(spec: JobSpec, path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace") if path.suffix.lower() != ".pdf" else ""
    text = read_document(path)
    haystack = normalize(text)
    haystack_stems = {stem(w) for w in haystack.split()}

    matched, missing_required, missing_preferred = [], [], []
    earned = possible = 0.0

    for term in sorted(spec.required):
        possible += WEIGHT_REQUIRED
        hit, tier = match_term(term, haystack, haystack_stems)
        if hit:
            earned += WEIGHT_REQUIRED * MATCH_TIERS[tier]
            matched.append({"term": term, "tier": tier, "bucket": "required"})
        else:
            missing_required.append(term)

    for term in sorted(spec.preferred):
        possible += WEIGHT_PREFERRED
        hit, tier = match_term(term, haystack, haystack_stems)
        if hit:
            earned += WEIGHT_PREFERRED * MATCH_TIERS[tier]
            matched.append({"term": term, "tier": tier, "bucket": "preferred"})
        else:
            missing_preferred.append(term)

    result = {
        "match_pct": round(100 * earned / possible, 1) if possible else 0.0,
        "required_hit": f"{len(spec.required) - len(missing_required)}/{len(spec.required)}",
        "preferred_hit": f"{len(spec.preferred) - len(missing_preferred)}/{len(spec.preferred)}",
        "matched": matched,
        "missing_required": missing_required,
        "missing_preferred": missing_preferred,
        "format_warnings": check_format(path, raw, text),
        "word_count": len(haystack.split()),
    }

    if spec.years_required:
        result["years_required"] = spec.years_required

    pdf_sibling = path.with_suffix(".pdf")
    if path.suffix.lower() != ".pdf":
        result["extraction_check"] = check_extraction(
            pdf_sibling, [m["term"] for m in matched]
        )

    return result


# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jd", required=True, type=Path, help="job description file")
    parser.add_argument("--resume", type=Path, help="resume to score (.html, .pdf, .txt)")
    args = parser.parse_args()

    if not args.jd.exists():
        sys.exit(f"job description not found: {args.jd}")

    spec = analyze_jd(read_document(args.jd))

    if args.resume is None:
        print(json.dumps(spec.to_dict(), indent=2))
        return

    if not args.resume.exists():
        sys.exit(f"resume not found: {args.resume}")

    output = {"jd": spec.to_dict(), "score": score(spec, args.resume)}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
