#!/bin/zsh -l
# Nightly internship pipeline. usage: run.sh [--dry] [--max N] [--date YYYY-MM-DD]
#   --dry   scan + fetch + rank only; no tailoring, no sheet, no email, no state change
#
# Steps: scan → fetch JDs → rank → tailor loop → desktop folder → drive upload → sheet → email → mark seen.
# Fatal failures (scan / rank / email) POST to alert_webhook (if set). Per-job failures never abort the night.

set -u
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"
export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"   # append: keep the login shell's python3 first
export SSL_CERT_FILE="$(python3 -m certifi 2>/dev/null)"   # framework Python on macOS ships no CA bundle

DRY=0; MAX=""; DATE="$(date +%F)"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry) DRY=1 ;;
    --max) MAX="$2"; shift ;;
    --date) DATE="$2"; shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
  shift
done

RUN="state/$DATE"; mkdir -p "$RUN" state
LOG="$RUN/run.log"
START_TS=$(date +%s)
# macOS has no coreutils `timeout`; perl alarm does the same job.
with_timeout() { local secs="$1"; shift; perl -e 'alarm shift; exec @ARGV' "$secs" "$@"; }
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG" >&2; }
setting() { python3 -c "import sys; from settings import settings; print(settings(require_profile=False).get(sys.argv[1]) or '')" "$1"; }
alert() {
  local msg="$1"
  local url; url="$(setting alert_webhook_url)"
  [ -z "$url" ] && { log "alert (no webhook configured): $msg"; return 0; }
  local tokfile; tokfile="$(setting alert_webhook_token_file)"
  local auth=()
  [ -n "$tokfile" ] && [ -s "${tokfile/#\~/$HOME}" ] && auth=(-H "Authorization: Bearer $(cat "${tokfile/#\~/$HOME}")")
  curl -s -m 20 -X POST "$url" "${auth[@]}" -H "Content-Type: application/json" \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"message": sys.argv[1], "text": sys.argv[1]}))' "$msg")" >>"$LOG" 2>&1
  echo >>"$LOG"
}
fatal() { log "FATAL: $1"; alert "⚠️ intern-pipeline $DATE failed at $1. See $ROOT/$LOG"; exit 1; }

python3 -c "from settings import settings; settings()" || exit 2   # loud failure if profile.yaml is missing
echo "=== run $DATE start $(date) dry=$DRY max=${MAX:-cfg} ===" >>"$LOG"

# 1. scan
python3 scan.py --out "$RUN/candidates.json" >>"$LOG" 2>&1 || fatal "scan"
NCAND=$(python3 -c "import json;print(len(json.load(open('$RUN/candidates.json'))))")
log "scan: $NCAND candidates"

# 2. fetch JDs (never fatal; failures become link-only)
if [ "$NCAND" -gt 0 ]; then
  with_timeout 2400 python3 fetch_jd.py --candidates "$RUN/candidates.json" --jd-dir "$RUN/jd" >>"$LOG" 2>&1 || log "fetch_jd exited $? (continuing)"
fi

# 3. rank
RANK_ARGS=(--candidates "$RUN/candidates.json" --out "$RUN/picks.json" --date "$DATE")
[ -n "$MAX" ] && RANK_ARGS+=(--max "$MAX")
with_timeout 1200 python3 rank.py "${RANK_ARGS[@]}" >>"$LOG" 2>&1 || fatal "rank"
NPICK=$(python3 -c "import json;print(len(json.load(open('$RUN/picks.json'))['picks']))")
log "rank: $NPICK picks"

if [ "$DRY" -eq 1 ]; then
  python3 - "$RUN/picks.json" <<'EOF'
import json, sys
p = json.load(open(sys.argv[1]))
print("\nPICKS")
for x in p["picks"]:
    print(f"  {x['company']} | {x['title']} | {', '.join(x['locations'])} | jd={x.get('jd_status')} | {x.get('rank_reason','')}")
print("\nCLOSE CUTS")
for x in p["close_cuts"]:
    print(f"  {x['company']} | {x['title']} | {x.get('cut_reason','')}")
print("\nDROPPED HARD")
for x in p["dropped_hard"]:
    print(f"  {x['company']} | {x['title']} | {x['reason']}")
print("\nnotes:", p.get("notes"))
EOF
  log "dry run done"
  exit 0
fi

# 4. tailor loop (exit 4 = usage limit; continue with what finished)
if [ "$NPICK" -gt 0 ]; then
  TAILOR_ARGS=(--picks "$RUN/picks.json" --log-dir "$RUN")
  [ -n "$MAX" ] && TAILOR_ARGS+=(--limit "$MAX")
  python3 tailor.py "${TAILOR_ARGS[@]}" >>"$LOG" 2>&1
  TRC=$?
  if [ "$TRC" -eq 4 ]; then
    log "tailor: usage limit hit, continuing with partial results"
    alert "⚠️ intern-pipeline $DATE hit the usage limit mid-run; sending what finished."
  elif [ "$TRC" -ne 0 ]; then
    log "tailor exited $TRC (continuing)"
  fi
fi

# 5. desktop folder, drive upload, sheet (never fatal)
python3 collect_pdfs.py --picks "$RUN/picks.json" >>"$LOG" 2>&1 || log "collect_pdfs failed (continuing)"
python3 drive_upload.py --picks "$RUN/picks.json" >>"$LOG" 2>&1 || log "drive_upload failed (continuing)"
python3 sheet.py --picks "$RUN/picks.json" >>"$LOG" 2>&1 || log "sheet failed (continuing)"

# 6. email (built deterministically, sent by claude through the Gmail connector)
python3 email_build.py --picks "$RUN/picks.json" --out-dir "$RUN" >>"$LOG" 2>&1 || fatal "email_build"
EMAIL_TO="$(setting email_to)"
PROMPT=$(sed -e "s|{{EMAIL_TO}}|$EMAIL_TO|g" -e "s|{{RUN_DIR}}|$ROOT/$RUN|g" prompts/email_prompt.md)
send_email() {
  with_timeout 600 claude -p --dangerously-skip-permissions --output-format text "$PROMPT" < /dev/null > "$RUN/email.out" 2>>"$LOG"
  grep -q '^SENT' "$RUN/email.out"
}
if send_email || { log "email attempt 1 failed, retrying"; sleep 120; send_email; }; then
  log "email: $(grep '^SENT' "$RUN/email.out" | head -1)"
else
  cat "$RUN/email.out" >>"$LOG"
  log "email failed twice"
  alert "⚠️ intern-pipeline $DATE: digest email failed. Picks in $ROOT/$RUN/picks.json."
  exit 1
fi

# 7. mark everything considered tonight as seen; record success time for tomorrow's window
python3 - "$RUN/candidates.json" state/seen.json <<'EOF'
import json, sys
cands = json.load(open(sys.argv[1]))
try:
    seen = set(json.load(open(sys.argv[2])))
except FileNotFoundError:
    seen = set()
seen |= {c["id"] for c in cands}
json.dump(sorted(seen), open(sys.argv[2], "w"))
EOF
echo "$START_TS" > state/last_success.txt
log "done in $(( ($(date +%s) - START_TS) / 60 )) min"
exit 0
