"""Signed snapshot windows and host-relative widget reading navigation."""

from urllib.parse import urlsplit, urlunsplit

from django.core import signing
from django.http import HttpRequest, QueryDict
from django.utils import timezone

from .models import Discussion


def _window(
    request: HttpRequest, discussion: Discussion, key: str, thread: int = 0
) -> tuple[str, int]:
    """Use the first valid window bound to this discussion/thread, else start at 20."""
    for token in request.GET.getlist(key):
        try:
            payload = signing.loads(token, salt="commentail.window", max_age=86400)
            if (
                payload["discussion"] == discussion.pk
                and payload["thread"] == thread
                and type(payload["limit"]) is int
                and payload["limit"] > 0
            ):
                return payload["snapshot"], payload["limit"]
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            pass
    return timezone.now().isoformat(), 20


def _next(discussion: Discussion, snapshot: str, limit: int, thread: int = 0) -> str:
    """Sign the same publication snapshot with one additional batch of 20 rows."""
    return signing.dumps(
        {
            "discussion": discussion.pk,
            "thread": thread,
            "snapshot": snapshot,
            "limit": limit + 20,
        },
        salt="commentail.window",
        compress=True,
    )


def _url(request: HttpRequest, **values: object) -> str:
    """Merge reading controls into the host URL, retaining repeated query values.

    A None override removes a control; unrelated host parameters are preserved."""
    destination = urlsplit(request.META.get("COMMENTAIL_WIDGET_PATH", request.path))
    params = QueryDict(destination.query, mutable=True)
    for key in request.GET:
        params.setlist(key, request.GET.getlist(key))
    for key, value in values.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = str(value)
    return urlunsplit(
        (
            destination.scheme,
            destination.netloc,
            destination.path,
            params.urlencode(),
            "commentail",
        )
    )
