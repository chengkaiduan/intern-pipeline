#!/bin/zsh
# One-time: enable Sheets/Drive APIs in your GCP project, create a service account, save its key.
# usage: ./setup_google.sh <gcp-project-id>
set -euo pipefail
PROJECT="${1:?usage: setup_google.sh <gcp-project-id>}"
SA=intern-pipeline
EMAIL="$SA@$PROJECT.iam.gserviceaccount.com"
KEY="$(dirname "$0")/secrets/sa.json"
gcloud services enable sheets.googleapis.com drive.googleapis.com --project="$PROJECT"
if ! gcloud iam service-accounts describe "$EMAIL" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA" --display-name="Intern pipeline sheet writer" --project="$PROJECT"
fi
mkdir -p "$(dirname "$KEY")"
if [ ! -s "$KEY" ]; then
  gcloud iam service-accounts keys create "$KEY" --iam-account="$EMAIL" --project="$PROJECT"
  chmod 600 "$KEY"
fi
echo "service account: $EMAIL"
echo "share your tracker Google Sheet with that address as Editor, then put its id in profile.yaml sheet_id"
