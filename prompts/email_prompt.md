Send one email using the Gmail connector tool `send_message`. This is an unattended run; do not
ask questions, do not edit the content, do not add commentary.

- to: ["{{EMAIL_TO}}"]
- subject: exactly the contents of `{{RUN_DIR}}/email.subject`
- htmlBody: exactly the contents of `{{RUN_DIR}}/email.html`
- body: exactly the contents of `{{RUN_DIR}}/email.txt`

Read the three files with `cat` first, then call `send_message` once with those values. Pass no
attachments. If the send call returns an error, retry once. Finish by printing one line:
`SENT <message id>` on success, or `SEND_FAILED <reason>` if both attempts failed.
