"""POST-only capability actions with normal CSRF and object-access checks."""

from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from wagtail.models import Site

from .admission import can_view
from .logging import redact
from .objects import discussion_url
from .security import (
    confirm_from_token,
    remember_guest,
    remembered_guest,
    unsubscribe,
    verify_token,
)
from .services import DomainError, edit_block_reason, revise


@require_http_methods(["GET", "POST"])
@csrf_protect
@sensitive_post_parameters("token")
@sensitive_variables("secret")
def action(request: HttpRequest, purpose: str) -> HttpResponse:
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
        return HttpResponse(_("Invalid or expired link"), status=404)
    try:
        token = verify_token(secret, purpose, site)
    except DomainError:
        return HttpResponse(_("Invalid or expired link"), status=404)
    comment = token.comment
    if purpose != "unsubscribe" and not can_view(request, comment.discussion):
        return HttpResponse(_("Page access is required"), status=403)
    if purpose == "view":
        from .policies import editorial_settings

        if editorial_settings(comment.discussion).mode == "hidden":
            return HttpResponse(status=403)
    if purpose == "view" and request.method != "GET":
        return HttpResponse(status=405)
    blocked = edit_block_reason(comment) if purpose == "edit" else ""
    message = ""
    error = _(blocked) if blocked else ""
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
            elif purpose == "edit":
                revise(
                    comment.pk,
                    request.POST.get("text", ""),
                    edit_token=secret,
                    site=site,
                )
                message = _("Revision submitted.")
            else:
                changed = unsubscribe(secret, site)
                message = (
                    _("Notifications disabled.")
                    if changed
                    else _("Notifications were already disabled.")
                )
        except DomainError as exc:
            error = str(exc)
    response = TemplateResponse(
        request,
        "commentail/action.html",
        {
            "language_code": translation.get_language(),
            "purpose": purpose,
            "token": secret,
            "message": message,
            "error": error,
            "text": request.POST.get("text", comment.text)
            if purpose == "edit"
            else comment.text
            if purpose == "view"
            else "",
            "can_edit": not blocked,
            "return_url": discussion_url(comment.discussion)
            + f"?target={comment.pk}#commentail-{comment.pk}",
            "status_label": comment.get_status_display(),
            "reason": comment.reason if purpose == "view" else "",
        },
        status=400 if request.method == "POST" and error else 200,
    )
    response["Referrer-Policy"] = "no-referrer"
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
