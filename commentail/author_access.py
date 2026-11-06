"""Author ownership checks shared by the widget and HTTP editing boundary.

A remembered guest email never grants editing rights to a comment. Each use
revalidates the exact purpose/Site-bound capability retained by the browser.
"""

from django.http import HttpRequest

from .models import Comment
from .security import remembered_guest, verify_token
from .services import DomainError, is_self_reply


def guest_edit_secret(request: HttpRequest, comment: Comment) -> str | None:
    """A remembered email is insufficient; revalidate this exact edit capability."""
    secret = request.session.get("commentail_edits", {}).get(str(comment.pk))
    if not secret or comment.user_id is not None or comment.account_deleted:
        return None
    try:
        token = verify_token(secret, "edit", comment.discussion.site)
    except DomainError:
        return None
    return secret if token.comment_id == comment.pk else None


def _edit_owner(request: HttpRequest, comment: Comment) -> bool:
    return bool(
        (
            request.user.is_authenticated
            and request.user.is_active
            and comment.user_id == request.user.pk
        )
        or guest_edit_secret(request, comment)
    )


def own_reply_target(request: HttpRequest, comment: Comment) -> bool:
    """Hide self-reply controls using account identity or existing guest proof.

    Cache guest proof per request/Site to avoid one lookup for every public card.
    Unknown guests are checked again against their submitted email by the service.
    This check deliberately does not confer editing authority.
    """
    if request.user.is_authenticated:
        return is_self_reply(comment, user=request.user)
    site = comment.discussion.site
    cache = getattr(request, "_commentail_reply_guests", None)
    if cache is None:
        cache = request._commentail_reply_guests = {}
    if site.pk not in cache:
        cache[site.pk] = remembered_guest(
            request.COOKIES.get(f"commentail_guest_{site.pk}", ""), site
        )
    grant = cache[site.pk]
    return bool(
        (grant and is_self_reply(comment, guest_email=grant.email))
        or guest_edit_secret(request, comment)
    )
