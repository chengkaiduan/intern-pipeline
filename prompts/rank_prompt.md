You are ranking internship postings for {{NAME}}. Pick the ones most worth applying to
tonight, name the close cuts, and answer ONLY with the JSON object described at the end.

## Candidate profile

{{PROFILE_SUMMARY}}

## What "valuable" means

1. Fit: he can honestly clear the required qualifications with the background above.
   Roles asking for graduate students, 3+ years of experience, or a specific stack he has never
   touched (embedded C, Verilog, mainframe COBOL) are cuts.
2. Payoff: name-brand or high-signal companies first (tiers are tagged below), then well-funded
   startups with real engineering, then everyone else. Government contractors, insurance back
   offices and staffing agencies rank low unless the role itself is strong.
3. Term: Summer 2027 (or unspecified). Spring/Fall-only co-ops are cuts unless the company is tier 1.
4. Location: in-person US. Bay Area is a plus, not a requirement.
5. Hard drop: US-citizenship-only or clearance-required postings. They are listed under
   `dropped_hard` already; do not re-add them.
6. Diversity: avoid five near-identical postings from one company; take the best one or two.

{{RANKING_RULES}}

Target {{MAX_JOBS}} picks. Return between {{MIN_PICKS}} and {{MAX_PICKS}} depending on quality:
never pad with weak roles to hit the number, never leave a strong role out to stay under it. Then list
{{CLOSE_CUTS}} close cuts: roles that nearly made it, with a one-line reason each, so the candidate can
tell us whether to include that kind next time.

Postings whose JD could not be fetched are marked `JD: unavailable`. Judge them from the title,
company and location; they can still be picks (the candidate will read the posting).

## Candidates

{{CANDIDATES}}

## Output

Answer with exactly one JSON object and nothing else, no prose, no code fence:

{"picks": [{"slug": "<slug>", "reason": "<one line>"}],
 "close_cuts": [{"slug": "<slug>", "reason": "<one line why it was cut>"}],
 "notes": "<one optional line about tonight's batch>"}

Every slug must be copied exactly from the candidate list.
