"""Author ownership checks shared by the widget and HTTP editing boundary.

A remembered guest email never grants editing rights to a comment. Each use
revalidates the exact purpose/Site-bound capability retained by the browser.
"""

from django.http import HttpRequest

from .models import Comment
from .security import verify_token
from .services import DomainError


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
