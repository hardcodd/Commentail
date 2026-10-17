# Replies, inline editing and pagination

## Conversations

The UI displays one reply level, but any published visible message can be an
addressee. Its @name link leads to that exact message. Replies to pending, hidden
or deleted messages are unavailable.

With JS, Reply opens one composer below the selected comment. The main form keeps
its independent draft. Switching addressees retains the reply draft. Cancel removes
the reply form and returns focus. Submission reveals the accepted message while
retaining expanded threads and reading position; pending messages are author-only.
Without JS, reply selection uses the form at the discussion's top. All navigation
stays in the host article. Inline editing also works without JS.

## Edit eligibility

Every save rechecks ownership, target access, author policy, open mode and:

- Fewer than 15 minutes since publication, configurable in Python.
- No direct reply has ever been accepted for the comment.
- No previous author revision is still pending.

A reply locks editing immediately, even before moderation. Removing/rejecting
that reply never restores the right. An already-submitted revision can still be
decided after a reply; new revisions are blocked.

Edits pass the same current filters. Pending/rejected edits leave the old published
text visible. Approval replaces it and displays an Edited timestamp. Account authors
open Edit from the ellipsis menu; guests use the protected publication email link.
Cancel removes the editor and restores focus. Moderators do not edit author text.

## Large discussions

Roots and replies load in batches of 20 using signed snapshot windows. New messages
appear after refresh. Loading more preserves drafts and avoids duplicates. A direct
permalink expands its thread and loads the exact reply beyond the first batch.
Counters include published visible comments and replies only. No live polling,
likes, attachments or report button is included in 0.1.0.

---

[← Guest comments](Guest-comments.md) · [Documentation home](Home.md) · [Email and worker →](Email-and-worker.md)
