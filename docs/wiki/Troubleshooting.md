# Troubleshooting and frequently asked questions

| Symptom | Check |
| --- | --- |
| Widget missing | Actual template needs the widget tag; inspect target access and hidden mode. Resource tags alone do not enable comments. |
| Editor tab missing | Check template inheritance/includes; supply GET_COMMENT_TEMPLATES for dynamic dependencies. |
| Message not public | Review all is default; guests confirm first. Inspect private status, queue, request signals and rules. |
| Guests unavailable | Site mail, configured email backend, author policy, mode, target permission and quotas. SMTP requires an explicit host; other backends use their own settings. |
| Mail stuck | Command or host task schedule and environment/database must match the site; inspect next attempt/status, broker/task failures and batch capacity. |
| Background task rejects a transaction | Call `process_pending()` outside `atomic()` with autocommit enabled; do not wrap the batch in a transaction. |
| Sent but absent in inbox | Sent means backend acceptance; inspect spam/provider logs and sender authorization. |
| Duplicate mail | An uncertain backend outcome may be retried. Exactly-once delivery is not promised. |
| Resend disabled | Check original expiry, active worker claim, disabled mail and resend quotas. Deadline never extends. |
| Edit missing | Check age, accepted reply, pending revision, ownership, target access and open mode. Guests use the publication email link. |
| Old text after edit | Revision may be pending or rejected; inspect moderation. |
| Shared IP quota | Verify real immediate proxy networks; never trust arbitrary forwarded headers. |
| CSRF after login | Login rotates the token; reload. Check cookies/origin/scheme/middleware. Optional failure view recovers a draft without accepting the POST. |
| Local projects interfere | Cookies span ports; use different session and CSRF cookie names. |
| Missing CSS/JS | Check collectstatic, resource tags, CSP, paths and override order. Avoid loading JS twice. |
| Expired action link | Original deadline/access still applies. Do not bypass it in a custom view. |
| Object widget missing | Verify registration, saved PK, adapter Site matches current Site and can_view returns bool. |
| CSV rejected | Check exact headers/actions/enabled values, reported row, duplicates and limits. Import is atomic. |
| commentail.E001 | Use documented keys, positive integer limits and importable callback paths. |
| Separate mail configuration rejected | Check the `COMMENTAIL_EMAIL` keys `BACKEND`, `OPTIONS`, `FROM_EMAIL`. Nonempty options require an explicit backend; use its constructor argument names and do not set `fail_silently`. See [the reference](Email-configuration.md). |
| Commentail uses the wrong sender or backend | Restart web and worker processes with the same settings/environment. Queued jobs use the active configuration when processed; ordinary Django mail still uses `EMAIL_BACKEND`. |

## Can comments work without mail or JavaScript?

Registered users can post without configured email delivery but receive no mail;
guests need delivery for proof. Non-SMTP backends are supported; console,
file, in-memory and dummy backends do not deliver to an inbox. See
[backend configuration](Email-and-worker.md).
Without JS, normal links/forms work; reply selection uses the top form.
There is no standalone discussion/edit document; service reads return to the article.
Confirmation/unsubscribe remain intentional customizable action screens.

## Does disabling comments erase messages?

No. Read only permits reading; Hidden suppresses display. Both block posting and
editing. Erasing text is a separate irreversible moderation action.

## Why confirm again?

Browser proof is separate per Site/email and lasts 30 days from confirmation.
It does not slide with visits or comments. Clearing storage/changing browser ends
that browser's proof.

## Reporting a bug

Include package/Python/Django/Wagtail versions, database, browser, expected/actual
behavior and reproduction steps. Redact passwords, tokens, session IDs, emails
and private text. Use [GitHub Issues](https://github.com/hardcodd/Commentail/issues).

---

[← Deployment](Deployment.md) · [Documentation home](Home.md) · [Example and testing →](Example-and-testing.md)
