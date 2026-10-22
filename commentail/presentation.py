"""Escaped public cards built from already authorized comments."""

import re

from django.http import HttpRequest
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _

from .author_access import _edit_owner
from .avatars import author_name, avatar_url, default_avatar
from .models import Comment, Discussion
from .objects import ObjectAccessError, _comment_url, discussion_url, target_url
from .policies import EditorialSettings, editorial_settings
from .reading import _url
from .services import edit_block_reason
from .structured import comment_markup


def render_text(text: str, clickable: bool) -> SafeString:
    """Escape text, optionally linking HTTP(S) URLs without trailing punctuation."""
    if not clickable:
        return format_html("{}", text)
    parts: list[SafeString] = []
    start = 0
    for match in re.finditer(r"https?://[^\s<>]+", text, flags=re.IGNORECASE):
        url = match.group().rstrip(".,;:!?)]}")
        parts.append(format_html("{}", text[start : match.start()]))
        parts.append(
            format_html(
                '<a href="{}" target="_blank" rel="nofollow ugc noopener noreferrer">{}</a>',
                url,
                url,
            )
        )
        start = match.start() + len(url)
    parts.append(format_html("{}", text[start:]))
    return format_html_join("", "{}", ((part,) for part in parts))


def _present(
    comment: Comment,
    request: HttpRequest,
    clickable: bool,
    structured_target: str = "",
    *,
    destination: str | None = None,
    options: EditorialSettings | None = None,
) -> dict[str, object]:
    """Build public card fields with escaped text and independently checked editing.

    Reuse render-local settings/destination when supplied. Private email and
    internal models never enter the returned template data."""
    name = author_name(comment, request)
    initials, gradient = default_avatar(name)
    options = options if options is not None else editorial_settings(comment.discussion)
    user = comment.user
    staff = bool(
        options.highlight_staff
        and not comment.account_deleted
        and user
        and user.is_active
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )
    if comment.status == "deleted":
        label = _("Comment deleted")
    elif comment.status == "hidden":
        label = _("Comment hidden")
    else:
        label = comment.text
    editable = _edit_owner(request, comment) and not edit_block_reason(
        comment,
        options=options,
        pending_revision=getattr(comment, "pending_revision", None),
    )
    destination = (
        destination if destination is not None else _destination(comment.discussion)[0]
    )
    permalink = _comment_url(destination, comment.pk)
    return {
        "id": comment.pk,
        "display_name": name,
        "highlight_staff": staff,
        "show_crown": staff and bool(getattr(user, "is_superuser", False)),
        "initials": initials,
        "gradient": gradient,
        "avatar_url": avatar_url(comment, request, name),
        "body": render_text(
            label, clickable if comment.status == "published" else False
        ),
        "published_at": comment.published_at,
        "edited_at": comment.edited_at,
        "status": comment.status,
        "status_label": comment.get_status_display(),
        "reason": comment.reason if comment.status == "rejected" else "",
        "resend_url": "",
        "reply_to_id": comment.reply_to_id,
        "reply_to_name": author_name(comment.reply_to, request)
        if comment.reply_to_id
        else "",
        "permalink": permalink,
        "schema": comment_markup(
            comment,
            name,
            structured_target,
            request.build_absolute_uri(permalink),
        )
        if structured_target
        else None,
        "reply_url": _url(request, reply_to=comment.pk, target=comment.pk),
        "edit_url": _comment_url(
            destination,
            comment.pk,
            navigation={"edit_comment": str(comment.pk)},
        )
        if editable
        else "",
    }


def _destination(discussion: Discussion) -> tuple[str, bool]:
    """Resolve the host once per render; retain service recovery on URL failure."""
    try:
        return target_url(discussion), True
    except ObjectAccessError:
        return discussion_url(discussion), False
