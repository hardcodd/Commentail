"""Private, expiring form recovery across a browser POST/redirect/GET.

Content stays in the database. A URL contains only a ticket ID; recovery also
requires the secret in the browser session and its existing session binding.
The normal form-ticket cleanup command expires these records as well.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.http import HttpRequest, QueryDict
from django.utils import timezone

from .admission import issue_form, session_digest
from .models import Discussion, FormTicket
from .objects import ObjectAccessError, target_url
from .security import digest
from .validation import valid_identifier

SESSION_KEY = "commentail_drafts"
QUERY_KEY = "commentail_draft"


def is_document(request: HttpRequest) -> bool:
    """Fetch's default */* differs from a browser document navigation."""
    return (
        "text/html" in request.headers.get("Accept", "")
        or request.headers.get("Sec-Fetch-Dest") == "document"
    )


def save_draft(
    request: HttpRequest, discussion: Discussion, error: str = ""
) -> str | None:
    """Store bounded browser recovery state and return its host URL.

    Return None when the target URL is unavailable. The URL carries only an ID;
    recovery additionally requires the session-held ticket secret."""
    try:
        destination = target_url(discussion)
    except ObjectAccessError:
        return None
    secret = issue_form(request, discussion, previous_key=request.POST.get("key", ""))
    ticket = FormTicket.objects.get(digest=digest(secret))
    ticket.draft = {
        # PostgreSQL text/JSON cannot represent U+0000. Retain the remaining
        # invalid draft for review without persisting an unsupported character.
        "values": {
            key: request.POST.get(key, "").replace("\x00", "")
            for key in (
                "text",
                "name",
                "email",
                "reply_to",
                "subscribe",
                "edit_comment",
                "challenge",
            )
        },
        "error": error,
    }
    ticket.save(update_fields=["draft"])
    tickets = dict(request.session.get(SESSION_KEY, {}))
    tickets[str(ticket.pk)] = secret
    while len(tickets) > 5:
        expired_id = next(iter(tickets))
        expired_secret = tickets.pop(expired_id)
        FormTicket.objects.filter(pk=expired_id, digest=digest(expired_secret)).delete()
    request.session[SESSION_KEY] = tickets
    parts = urlsplit(destination)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[QUERY_KEY] = str(ticket.pk)
    fragment = "commentail"
    identifier = request.POST.get("edit_comment", "")
    if valid_identifier(identifier):
        query["edit_comment"] = identifier
        query["target"] = identifier
        fragment = f"commentail-{identifier}"
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), fragment)
    )


def load_draft(request: HttpRequest, discussion: Discussion) -> tuple[QueryDict, str]:
    """Recover values only for a live ticket bound to this browser and discussion."""
    values = QueryDict(mutable=True)
    identifier = request.GET.get(QUERY_KEY, "")
    secret = request.session.get(SESSION_KEY, {}).get(identifier)
    if request.method != "GET" or not secret or not valid_identifier(identifier):
        return values, ""
    ticket = FormTicket.objects.filter(
        pk=identifier,
        digest=digest(secret),
        discussion=discussion,
        session_digest=session_digest(request),
        expires_at__gt=timezone.now(),
    ).first()
    if ticket is None or not ticket.draft:
        return values, ""
    values.update(ticket.draft["values"])
    # This key is recovered from server-owned session state, never a URL.
    values["key"] = secret
    return values, ticket.draft["error"]


def clear_drafts(request: HttpRequest, discussion: Discussion) -> None:
    """Delete only this session's retained tickets for the accepted discussion."""
    tickets = dict(request.session.get(SESSION_KEY, {}))
    if not tickets:
        return
    owned = FormTicket.objects.filter(
        pk__in=tickets,
        discussion=discussion,
        session_digest=session_digest(request),
    )
    for identifier in owned.values_list("pk", flat=True):
        tickets.pop(str(identifier), None)
    owned.delete()
    request.session[SESSION_KEY] = tickets
