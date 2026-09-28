# intern-pipeline

Every night at 4am, this scans new internship postings, picks the ~10 most worth your time,
writes a tailored one-page resume PDF for each one from a fact sheet of your own experiences,
scores each resume the way a keyword-matching applicant tracking system would, logs everything
to a Google Sheet you can tick off, and emails you a digest with apply links. In the morning you
open the email, read the flagged bullets, and apply. It never submits anything for you.

It runs on a Mac with [Claude Code](https://claude.com/claude-code) as the model harness. The
deterministic parts (scanning, fetching job descriptions, scoring, rendering, the sheet) are plain
Python. The judgment parts (ranking, writing the resume, sending the email) are `claude -p` calls.

## How it works

```
SimplifyJobs feed ──▶ scan.py ──▶ fetch_jd.py ──▶ rank.py ──▶ tailor.py ×N ──▶ sheet.py ──▶ email
   (~125/day)        filters     ATS APIs +      one model    one model call        Google     Gmail
                     to ~30-100  Playwright      call: picks  per pick, runs the    Sheet      connector
                                                + close cuts  tailor-resume skill
```

- **scan.py** pulls the [SimplifyJobs Summer2027 listings](https://github.com/SimplifyJobs/Summer2027-Internships)
  feed and filters by category, US in-person location, bachelor's eligibility, and what it has seen before.
- **fetch_jd.py** gets the job description text: Greenhouse / Lever / Ashby / Workday JSON APIs, then plain
  HTML, then Playwright (bundled Chromium, then your installed Chrome for bot-walled sites).
- **rank.py** sends titles, companies, and JD excerpts plus your `profile.yaml` summary to the model and
  gets back picks and "close cuts" with one-line reasons, so you can tune the rules over time.
- **tailor.py** runs the `tailor-resume` skill (in `.claude/skills/`) once per pick in a fresh session.
  The skill reads `resume/masterdoc.yaml`, writes `resume.json`, renders a one-page PDF with headless
  Chrome, scores it with `resume/ats_scan.py`, iterates two or three times, and writes `report.md`
  labelling every bullet `direct` / `reframed` / `inferred` / `stretch` so you know what to prune.
- **sheet.py** appends rows to a Google Sheet (Status dropdown: New / Applied / Skip). Optional.
- **collect_pdfs.py** copies the night's PDFs to `~/Desktop/Internship Resumes/<date>/`.
- **email_build.py** renders the digest deterministically; a short `claude -p` call sends it through
  the claude.ai Gmail connector from your own account.

### The resume part on its own

`resume/` is usable without the nightly pipeline. Put a job description in `resume/jobs/<slug>/jd.txt`
and tell Claude Code "tailor my resume for jobs/<slug>". The skill does the rest. The interesting
bits are:

- **masterdoc.yaml**: your experiences as atomic *facts* plus *bullets* that cite them. Approved bullets
  are reused verbatim; rejected ones are never regenerated. See `resume/masterdoc.example.yaml`.
- **ats_scan.py**: a deterministic keyword scorer, no model. It extracts required/preferred terms from
  the posting, scores the rendered PDF's *text layer* (what a real scanner reads), and fails loudly on
  ligature damage or keywords lost in extraction. 27 unit tests.
- **render.py**: `resume.json` → HTML → PDF via headless Chrome, asserting exactly one page.

## Setup

Requirements: macOS, Python 3.11+, Google Chrome, [Claude Code](https://claude.com/claude-code)
signed in, and the claude.ai **Gmail connector** enabled in Claude Code (`claude mcp list` should
show it connected). Expect roughly one model session per resume, so ~10 sessions a night.

```bash
git clone https://github.com/chengkaiduan/intern-pipeline && cd intern-pipeline
pip install -r requirements.txt && python3 -m playwright install chromium
cp profile.example.yaml profile.yaml            # who you are; the ranker reads `summary`
cp resume/masterdoc.example.yaml resume/masterdoc.yaml   # your experiences, as facts + bullets
python3 -m pytest tests resume -q               # everything green before you trust it
./run.sh --dry                                  # scan + fetch + rank, prints picks, changes nothing
./run.sh --max 2                                # real run with 2 resumes; check the email and PDFs
./setup/install_launchd.sh 4 0                  # schedule daily at 04:00
```

Filling in `masterdoc.yaml` well is the whole game. Facts first, one per line, with numbers.
Let the skill write bullets, then approve or reject them in the file; that is how it learns
your voice without ever inventing a job.

### Optional pieces

- **Google Sheet tracker**: see `setup/google.md`. Needs a GCP project and a service account.
- **Alerts on failure**: set `alert_webhook_url` in `profile.yaml` (Poke, Slack incoming webhook, ntfy).
- **Lid closed overnight**: `sudo pmset -c sleep 0 disablesleep 1 && sudo pmset repeat wakeorpoweron MTWRFSU 03:55:00`.
  The Mac must be on power. Undo with `sudo pmset -c sleep 1 disablesleep 0; sudo pmset repeat cancel`.
- **Drive links in the email**: off by default. Service accounts cannot upload to My Drive, and Google
  blocks gcloud's default OAuth client for the Drive scope, so it needs your own OAuth client.

## Tuning

- `config.yaml`: categories, `max_jobs`, lookback window, tier-1 / tier-2 company lists.
- `profile.yaml` → `summary` and `ranking_rules`: what the ranker knows about you and what to skip.
- `prompts/rank_prompt.md`: the definition of "valuable". Read the close cuts in a few digests, then edit.

## Failure behaviour

| Failure | Behaviour |
|---|---|
| listings feed broken | abort, alert |
| zero new postings | "nothing new" email |
| JD fetch fails | pick stays link-only, resume still attempted from title |
| rank JSON invalid twice | abort, alert |
| resume fails twice | pick listed link-only |
| usage limit mid-run | stop loop, email partial, alert |
| sheet fails | logged, email still goes |
| email fails twice | alert with picks.json path |

`state/seen.json` and `state/last_success.txt` update only after a successful email, so a failed night
is retried in full the next night (lookback capped at 72h).

## Notes from running it

- Framework Python on macOS ships no CA bundle; everything uses `certifi`.
- macOS has no `timeout`; `run.sh` uses a perl `alarm`. `subprocess.run(timeout=)` never fires on
  `claude -p` because its MCP child processes hold the pipes open; `tailor.run_with_deadline` kills the
  whole process group instead.
- A third of listing URLs are Workday. Its undocumented JSON endpoint is
  `https://<tenant>.wdN.myworkdayjobs.com/wday/cxs/<tenant>/<site>/job/<path>`.
- Career sites behind bot walls (Citadel, Eightfold) need the installed Chrome with automation flags off.

## License

MIT.
