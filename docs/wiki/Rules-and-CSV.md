# Moderation rules and CSV import/export

Word/phrase rules are project-wide;
rejection takes precedence over review when several rules match. The rule list
supports phrase search, action/enabled filters and 25 records per page, retaining
filters across pages. Adding and editing use separate forms with an optional
rejection reason of up to 2000 characters; all rule endpoints
require the project-wide rules capability.

Import/export buttons support bulk rule management. Export downloads all rules
as UTF-8 CSV with a BOM, independent of active list filters. The columns are
`phrase`, `action` (`review` / `reject`), `enabled` (`1` / `0`; import also
accepts `true` / `false`) and `reason`. Import accepts legacy three-column files,
as well as comma or semicolon separators, and
preserves quoted Unicode phrases, commas and line breaks:

```csv
phrase,action,enabled,reason
spam,review,1,
unwanted phrase,reject,1,Please remove this phrase.
```

Import adds new phrases and updates action/enabled on exact phrase matches;
unmentioned rules remain unchanged. Reimporting the same file is idempotent.
The optional `reason` column updates the reason; an empty cell clears it.
Omitting the entire column preserves existing reasons and gives new rules an
empty reason. Reasons allow at most 2000 characters and no null bytes.
Invalid rows, duplicate phrases in the file or ambiguous existing matches abort
the entire import and show a row error. Spreadsheet-sensitive phrase/reason prefixes
are escaped with an apostrophe on export and restored on import; literal leading
apostrophes are doubled. Use the exported format when transferring such phrases.
Default limits are 5 MiB and 20,000 rules per import, overridable only in
`COMMENTAIL["default"]` as `RULES_CSV_MAX_BYTES` and `RULES_CSV_MAX_ROWS`.

## How text matches

Rules run only in **Apply rules** mode. Matching uses complete word-token sequences,
case-insensitively; punctuation is ignored, whitespace/line breaks are normalized,
and Russian ё equals е. A word does not match inside another word. Displayed text
is unchanged. Rejection wins over review when multiple rules match.

In the unpublished 1.4.0 candidate, new guest submissions matching an enabled
Reject rule are refused before a comment or confirmation/rejection mail is
created. The sender sees the reason of the matching Reject rule with the lowest
ID, or a localized default if that reason is blank. The reason is plain text,
not HTML; it appears only in the sender's form response/private draft. Drafts
remain editable with and without JavaScript. CAPTCHA and attempt limits remain
in force. Review rules and soft spam signals retain email confirmation and the
existing moderation flow; other policies do not apply phrase rules. Registered
submissions and author revisions retain their existing policy flow. Previously
accepted guest comments are still checked against current rules at confirmation.

## Bulk workflow

1. Export the existing list as a backup. Export includes all rules, regardless of filters.
2. Keep the column names and UTF-8 encoding when editing in a spreadsheet.
3. Import a small sample and inspect the result before a large batch.
4. Reimporting identical phrases updates without creating duplicates.

Import is an upsert, not a replacement/deletion tool. Literal phrase equality is the
CSV key; different phrases that normalize identically are not automatically merged.
A single invalid row aborts the entire import.

---

[← Moderation](Moderation.md) · [Documentation home](Home.md) · [Guest comments →](Guest-comments.md)
