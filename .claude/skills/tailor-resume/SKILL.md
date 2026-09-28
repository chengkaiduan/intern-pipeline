---
name: tailor-resume
description: Use when the user wants a resume aimed at a specific job — pasting a job description, saying "tailor my resume", "apply to X", "resume for this posting", or /tailor-resume. Builds a one-page PDF from resume/masterdoc.yaml, scores it with a deterministic ATS simulator, and reports what to review.
---

# Tailor Resume

Turn a job description into a one-page resume, scored the way a keyword-matching applicant
tracking system scores it.

Everything lives in `resume/` at the repo root (paths below are relative to it):

| File | Role |
|---|---|
| `masterdoc.yaml` | Every experience the candidate has. Facts and approved phrasings. Source of truth. |
| `ats_scan.py` | Deterministic scorer. No model. |
| `render.py` | resume.json → HTML → one-page PDF → plain text. |
| `jobs/<slug>/` | One directory per application. |

Use the strongest model available. Reasoning quality is the whole product here.

## Sequence

### 1. Capture the posting

Make `resume/jobs/<company>-<role>/` (kebab-case slug) and save the description
verbatim to `jd.txt`. Never paraphrase it — the scorer reads it literally.

### 2. Measure the target

```bash
cd resume && python3 ats_scan.py --jd jobs/<slug>/jd.txt
```

Read the output. That keyword set is the target — not your impression of the posting.
Note `targets_sophomores`.

### 3. Read the masterdoc

Read `masterdoc.yaml` in full. You are selecting from facts, not recalling from memory.

### 4. Select

Rank experiences by overlap with the required keyword set, then preferred. Budget to one page:
roughly 4-5 entries with 2-3 bullets each, plus education and skills.

Guidance, not law:

- **Recent and relevant beats impressive and stale.** College-era work is the core. Entries tagged
  `hs` (high school) only appear when a posting rewards them — investing club for a finance role,
  robotics for hardware — or when the college material genuinely cannot fill a page.
- **Names are exact.** Follow any `resume_name`, `never_write`, or `org_note` in the masterdoc.
  Those are decisions the candidate already made; do not re-open them.
- **Section order follows the job.** Engineering posting: Education, Experience, Projects, Skills.
  Consulting or PM posting: Education, Experience, Leadership, Skills — projects compressed.
- **Skills line front-loads whatever the posting named.** Same skills, reordered.

### 5. Pick the graduation date

Use `education.graduation.default` from the masterdoc. Use `education.graduation.sophomore_framing`
only when the posting explicitly asks for sophomores, second-years, or first/second-year students —
that is what `targets_sophomores` in the scan reports.

Say in the report which one you used and why.

### 6. Write

Reuse any bullet with `approved: true` verbatim. It is settled; do not re-litigate it.

Write new bullets only where a gap exists. Policy is deliberately loose — the candidate would rather
delete an overreach than guess at the optimal line:

- Write the strongest line the underlying facts can support.
- Borrow the posting's exact vocabulary wherever a fact backs it. If the posting says
  "distributed systems" and the fact is an atomic Postgres pairing function under concurrent load,
  use their words.
- Lead with the verb, land on a number where one exists.
- Do not soften yourself preemptively. Flagging is the safety mechanism, not self-censorship.

Then label every bullet you wrote:

| Label | Meaning |
|---|---|
| `direct` | Restates a masterdoc fact. Nothing added. |
| `reframed` | Same fact, the posting's vocabulary. |
| `inferred` | Implied by the facts but never explicitly recorded. The candidate should confirm. |
| `stretch` | Reaches past what the masterdoc supports. Delete unless it happens to be true. |

Any experience with entries in `detail_gaps` is under-documented: bullets that go beyond its
recorded facts are `inferred` by default.

### 7. Render

Write `jobs/<slug>/resume.json` (shape documented at the top of `render.py`), then:

```bash
cd resume && python3 render.py jobs/<slug>
```

It fails loudly if the PDF is not exactly one page. Cut a bullet, do not shrink the type.

### 8. Score the output

```bash
cd resume && python3 ats_scan.py --jd jobs/<slug>/jd.txt --resume jobs/<slug>/resume.html
```

Check three things:

1. `missing_required` — for each, ask whether a masterdoc fact could honestly cover it. If yes,
   revise and re-render. If no, it goes in the report as an honest gap.
2. `format_warnings` — should be empty. Anything here is a bug in the resume, not a style note.
3. `extraction_check.lost_in_extraction` — must be empty. A keyword credited in the HTML but
   missing from the PDF text layer is invisible to the real scanner.

Iterate until nothing honest is left to gain. Two or three passes, not twenty.

### 9. Report

Write `jobs/<slug>/report.md`:

```markdown
# <Company> — <Role>

Score: <before> → <after>   Required <n/n>   Preferred <n/n>
Graduation date used: May 2028 (reason)

## Review queue
Everything below is `inferred` or `stretch`. Delete or correct.
- [bullet id] "text" — why it is flagged

## Honest gaps
Required keywords no fact supports: ...

## All bullets
| id | label | text |
```

### 10. Write back

When the candidate approves the resume or specific bullets:

- Add the approved bullet to the right experience in `masterdoc.yaml` with `approved: true`,
  its `tags`, and `source_facts`.
- Any bullet they reject gets `rejected: true` plus the reason, so it is never regenerated.
- Any new fact they mention while reviewing gets appended to that experience's `facts`, and the
  matching entry in `detail_gaps` gets removed once filled.
- Then run the validator, every time:

  ```bash
  cd resume && python3 validate_masterdoc.py
  ```

  It catches duplicate YAML keys, which are the dangerous failure — a second `bullets:` block
  under one experience deletes every bullet in the first, silently, with no parse error. It also
  catches `source_facts` pointing at facts that do not exist and reused bullet ids.
- Commit `masterdoc.yaml` locally if you keep it in a private repo. It is gitignored here.

The point of this step: the same edit is never requested twice. If the write-back is skipped,
the next run asks the candidate to fix something they already fixed.

## Rules

- The score is computed by `ats_scan.py`. Never estimate a match percentage yourself.
- Never invent an employer, a title, a date, or a number. Rephrasing is open; fabricating a fact
  is not, and that is what the labels exist to surface.
- One page. Always.
