# Optional: Google Sheet tracker

1. Create a Google Sheet (any name) in your own Drive. Copy its id from the URL
   (`/spreadsheets/d/<id>/edit`).
2. Have a Google Cloud project (free tier is fine) and `gcloud` logged in, then:
   ```bash
   ./setup/setup_google.sh <your-gcp-project-id>
   ```
   This enables the Sheets and Drive APIs, creates a service account, and saves its key to
   `secrets/sa.json` (gitignored). It prints the service-account email.
3. Share the sheet with that email as **Editor**.
4. Put the id in `profile.yaml` → `sheet_id`. The first run creates the `Jobs` and `Cuts` tabs,
   headers, and the Status dropdown.

Drive uploads of the PDFs are a separate, harder thing: service accounts have no storage quota
in My Drive, and Google blocks gcloud's default OAuth client for the Drive scope. You would need
your own OAuth Desktop client and `gcloud auth application-default login --client-id-file=...`.
The pipeline works fine without it; PDFs stay in `resume/jobs/` and the Desktop folder.
