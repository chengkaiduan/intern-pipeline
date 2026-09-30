# Optional: Instagram stories as a source

Some accounts (the default is `zero2sudo`) repost internship openings as stories. Stories need a
logged-in session, so the pipeline uses your own Instagram cookies.

1. In Chrome, logged in to instagram.com, open DevTools → Application → Cookies → `https://www.instagram.com`.
2. Copy `sessionid`, `csrftoken`, and `ds_user_id` into `secrets/instagram_cookies.json`:

   ```json
   {"sessionid": "...", "csrftoken": "...", "ds_user_id": "..."}
   ```

   (`sources/zero2sudo.py` also tries to decrypt Chrome's cookie jar itself via `browser_cookie3`;
   macOS will ask once for Keychain access to "Chrome Safe Storage".)
3. Set `instagram_source: zero2sudo` (or another username) in `profile.yaml`. Leave it empty to
   disable the source.

Each night the source pulls the account's live stories plus highlights from the last 48h, keeps
link-sticker URLs, and has the model read image-only stories to extract company, role, and any
visible URL. Results merge into the night's candidates before ranking, tagged `source: instagram:<user>`.
Sessions expire every few weeks; when the source logs "logged out", refresh the cookie file.
