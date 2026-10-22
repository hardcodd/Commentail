"""POST-only capability actions with normal CSRF and object-access checks."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from wagtail.models import Site

from .admission import can_view
from .logging import redact
from .objects import comment_url
from .security import (
    confirm_from_token,
    remember_guest,
    remembered_guest,
    unsubscribe,
    verify_token,
)
from .services import DomainError


def _action_error(request: HttpRequest, message: str, status: int) -> HttpResponse:
    """Render a capability failure without resolving or disclosing its target."""
    response = TemplateResponse(
        request,
        "commentail/action.html",
        {
            "language_code": translation.get_language(),
            "page_title": _("Comment action"),
            "error": message,
            "unavailable": True,
            "return_url": "/",
        },
        status=status,
    )
    response["Referrer-Policy"] = "strict-origin"
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET", "POST"])
@csrf_protect
@sensitive_post_parameters("token")
@sensitive_variables("secret")
def action(request: HttpRequest, purpose: str) -> HttpResponse:
    """Verify a purpose/Site-bound link before rendering or processing its action.

    GET verifies access without confirming email or changing subscriptions.
    Editing retains the capability in the session and delegates author writes
    to the normal edit boundary. Invalid links reveal no target data.
    """
    secret = (
        request.POST.get("token", "")
        if request.method == "POST"
        else request.GET.get("token", "")
    )
    # Keep framework exception reports from including the capability query.
    query = request.GET.copy()
    if "token" in query:
        query["token"] = "[redacted]"
    request.GET = query
    for field in ["QUERY_STRING", "RAW_URI", "REQUEST_URI"]:
        if field in request.META:
            request.META[field] = redact(str(request.META[field]))

    site = Site.find_for_request(request)
    if site is None or purpose not in {"confirm", "edit", "unsubscribe", "view"}:
        return _action_error(request, _("Invalid or expired link"), 404)
    try:
        token = verify_token(secret, purpose, site)
    except DomainError:
        return _action_error(request, _("Invalid or expired link"), 404)

    comment = token.comment
    if purpose != "unsubscribe" and not can_view(request, comment.discussion):
        return _action_error(request, _("Page access is required"), 403)
    if purpose == "view":
        from .policies import editorial_settings

        if editorial_settings(comment.discussion).mode == "hidden":
            return _action_error(request, _("Page access is required"), 403)
    if purpose == "view" and request.method != "GET":
        return HttpResponse(status=405)

    if purpose == "edit":
        from .public import edit_view

        proofs = dict(request.session.get("commentail_edits", {}))
        proofs[str(comment.pk)] = secret
        while len(proofs) > 10:
            proofs.pop(next(iter(proofs)))
        request.session["commentail_edits"] = proofs
        owned = request.session.get("commentail_own", [])
        if comment.pk not in owned:
            request.session["commentail_own"] = [*owned[-99:], comment.pk]
        response = edit_view(request, comment.pk)
        response["Referrer-Policy"] = "strict-origin"
        return response

    message = ""
    error = ""
    grant_secret = None
    if request.method == "POST":
        try:
            if purpose == "confirm":
                comment = confirm_from_token(secret, site)
                message = _(
                    "Email confirmed. Your comment follows the site's moderation policy."
                )
                if comment.email_confirmed_at and comment.email:
                    existing = remembered_guest(
                        request.COOKIES.get(f"commentail_guest_{site.pk}", ""), site
                    )
                    if existing is None or existing.email != comment.email:
                        grant_secret = remember_guest(
                            site, comment.email, confirmed_at=comment.email_confirmed_at
                        )
            else:
                changed = unsubscribe(secret, site)
                message = (
                    _("Notifications disabled.")
                    if changed
                    else _("Notifications were already disabled.")
                )
        except DomainError as exc:
            error = str(exc)

    response: HttpResponse
    if message and purpose == "confirm":
        response = redirect(comment_url(comment.discussion, comment.pk))
        response.status_code = 303
    else:
        response = TemplateResponse(
            request,
            "commentail/action.html",
            {
                "language_code": translation.get_language(),
                "purpose": purpose,
                "page_title": {
                    "confirm": _("Confirm email"),
                    "unsubscribe": _("Reply notifications"),
                    "view": _("Comment status"),
                }[purpose],
                "token": secret,
                "message": message,
                "error": error,
                "text": comment.text if purpose == "view" else "",
                "return_url": comment_url(comment.discussion, comment.pk),
                "status_label": comment.get_status_display(),
                "reason": comment.reason if purpose == "view" else "",
            },
            status=400 if request.method == "POST" and error else 200,
        )
    response["Referrer-Policy"] = "strict-origin"
    response["Cache-Control"] = "private, no-store"
    if grant_secret:
        grant = remembered_guest(grant_secret, site)
        response.set_cookie(
            f"commentail_guest_{site.pk}",
            grant_secret,
            max_age=max(1, int((grant.expires_at - timezone.now()).total_seconds())),
            secure=request.is_secure(),
            httponly=True,
            samesite="Lax",
        )
    return response
