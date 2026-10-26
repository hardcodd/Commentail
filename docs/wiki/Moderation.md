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
From 1.4.0, enabled Reject rules refuse new guest text
before email confirmation, showing the configured reason and preserving the
draft. Other guest moderation decisions follow email confirmation. See
[rules and CSV](Rules-and-CSV.md) for reason priority and legacy CSV handling.
Changing policy leaves old queued
messages in their current state.

## Queue and decisions

Open **Comments** and search directly above the list. Expand **Filters** to
choose Site, status, date or Page; applied advanced filters open automatically
and their count remains visible when collapsed. **Reset filters** returns to the
default pending queue. Service links, including Site settings, email delivery
and permissions, are grouped under the cog **Management** button. The same menu
appears on every Commentail admin page, including settings, cards and confirmation
pages, with destinations limited by your permissions and a link to **Comments**.
Site and discussion settings are grouped into discussion, appearance and email
sections. The group-access editor separates the target group/Site, moderation
capabilities and management rights; checkbox labels sit beside their controls.
Filters are
grouped into Site/Page, status and date range sections. Floating menus close on
outside click or Escape; Escape and close buttons return focus to their trigger.
Opening and closing motion follows the reduced-motion preference. Counts
respect permitted Sites and active filters. Open a message to see its author,
state, text, action journal and any pending author revision.

Opening a comment carries the current search, Site, Page, status, date range and
list page into its card. **Back to results** returns to that selection, including
after a moderation decision, author revision decision, mail retry, or cancelling
or confirming text erasure. Successful single actions stay on the card. Direct
card links offer **All comments** and return to the default queue. Context travels
in links and forms, so tabs are independent and return navigation works without
JavaScript. If moderation empties the last list page, the existing pagination
returns to the nearest available page while preserving the filters.

The Page filter opens Wagtail's standard
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
the current page. The panel above the list shows **Selected: N** and offers
**Clear selection**. For a nonempty selection, expand **Action availability**
to see the required status and permissions of unavailable actions. The live count
and clear control require JavaScript. Without JavaScript, management links,
filters and action guidance stay visible; selecting rows and submitting actions
still works. The Page chooser keeps Wagtail's existing behavior.
The server rechecks the entire selection and rolls back all
changes if any row is no longer eligible or permitted. A batch accepts at most
100 identifiers. Successful actions preserve the list filters and pagination.

If a moderation action fails because statuses or permissions have changed, or a
comment is no longer available, Commentail shows **Action not completed** with
an explanation and **Back to results**. The link preserves search, filters and
pagination and reloads the current results; it never repeats the failed action.
No part of a failed bulk action is saved, including audit entries and queued
mail. Already-reviewed author revisions also offer recovery instead of another
decision. If all Commentail access has been revoked, the recovery link opens
the Wagtail dashboard. Recovery links work without JavaScript, and error pages
retain HTTP 400/403/404 statuses without revealing unavailable comments.

Single and bulk text erasure first open a confirmation page showing the number
of comments and an irreversible-erasure warning. Cancel leaves text and revisions
unchanged; bulk cancellation returns to the same list filters and page. Confirming
erases the selected comments' text and revisions, preserving replies. Confirmation
works without JavaScript, and execution rechecks current permissions and states.
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
