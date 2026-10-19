# Moderate comments in Wagtail

## Choose a policy

| Policy | Behavior after guest email proof |
| --- | --- |
| Review all | Queue every new message |
| Review guests | Queue guests; normally publish registered authors |
| Publish immediately | Publish eligible submissions without routine review |
| Apply rules | Review/reject matches; normally publish unmatched text |

Suspicious guest signals can still require review. Rule rejection wins when
**Apply rules** is active. Phrase rules are not applied by the other policies.
Guest confirmation always precedes moderation. Changing policy leaves old queued
messages in their current state.

## Queue and decisions

Open **Comments**, choose Site/status and filter by search, date or Page. Counts
respect permitted Sites and active filters. Open a message to see its author,
state, text, action journal and any pending author revision.

Since 0.2.0, the Page filter opens Wagtail's standard
searchable chooser instead of loading every discussion Page into the list.
Choosing a Page does not grant permission to its comments; Site grants still
bound the resulting queue.

| Action | Effect |
| --- | --- |
| Approve | Publish a pending comment or approve its author revision |
| Reject | Keep content private; optional reason is author-only |
| Hide | Reversibly hide published content |
| Restore | Restore hidden content |
| Erase text | Permanently remove text, retaining replies and a deleted placeholder |

Moderators cannot change another author's text or propose replacement text.
The list, including **All statuses**, supports bulk approve/reject for pending
comments, hide for published comments, restore for hidden comments, and permanent
text erasure for any non-deleted comment. Checkboxes and buttons respect each
comment's status and your Site permissions. A button is enabled only when every
selected comment supports that action; **Select all** selects eligible rows on
the current page. The server rechecks the entire selection and rolls back all
changes if any row is no longer eligible or permitted. A batch accepts at most
100 identifiers. Successful actions preserve the list filters and pagination.
Author revisions are decided individually.
Pending revisions keep the old published text visible. Closing a discussion does
not remove its moderation queue. Logs record actions without copies of comment text.

## Group permissions by Site

The standard Wagtail group create/edit form includes **Comment permissions by site**.
Users also need Wagtail admin access. Capabilities are View, Moderate, Hide/restore,
Delete text, Settings and Rules. Moderate permits retrying eligible failed mail.
Normal Page-edit rights are additionally required to configure a Page.

Rules are shared project-wide: granting Rules through a Site row permits management
of the common list affecting every Site using Apply rules. Grant it deliberately.
There are no per-Page moderator grants. The separate group-access editor inside
Comments is superuser-only; ordinary group forms use Wagtail's group permissions.
Direct action URLs enforce the same boundaries as the visible buttons.

---

[← Configuration](Configuration.md) · [Documentation home](Home.md) · [Rules and CSV →](Rules-and-CSV.md)
