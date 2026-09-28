Use the `tailor-resume` skill for the job below. This is an unattended nightly run; nobody will
answer questions. Make every judgment call yourself and finish.

Job directory (already exists, JD already saved): `{{JOB_DIR}}/`
Resume tools (masterdoc.yaml, ats_scan.py, render.py): `{{RESUME_DIR}}/`
Company: {{COMPANY}}
Role: {{TITLE}}
Location: {{LOCATIONS}}
Posting URL: {{URL}}
{{JD_NOTE}}

Follow the skill's sequence with these overrides:

1. Step 1 (capture) is done. Do not re-fetch or rewrite `jd.txt`.
2. Use the loose writing policy exactly as the skill describes: strongest honest line the facts
   support, borrow the posting's vocabulary, label every bullet direct / reframed / inferred /
   stretch in `report.md`. The candidate prunes in the morning.
3. Skip step 10 (write-back) entirely. Do not modify `masterdoc.yaml`.
4. After the final render and scan, copy the PDF to
   `{{JOB_DIR}}/{{PDF_NAME}}` (keep `resume.pdf` too).
5. Two or three scoring passes at most. Stop when nothing honest is left to gain.
6. Finish by printing, as the very last line of your output, one JSON object on a single line:

{"score": <final ATS score number>, "required": "<matched>/<total required>", "preferred": "<matched>/<total preferred>", "grad": "<May 2028 or May 2029>", "gaps": ["<required keyword no fact supports>", ...], "review_count": <number of inferred+stretch bullets>, "pdf": "{{JOB_DIR}}/{{PDF_NAME}}"}

If the job turns out to be a bad fit or the JD is unusable, still produce the best honest
one-page resume you can and say so in `report.md`; never skip the PDF.
