"""Protect capability responses, including rejection by host CSRF middleware."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class CapabilityHeadersMiddleware:
    """Place before CsrfViewMiddleware so denied action links also get headers."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.META.get("COMMENTAIL_PRIVATE"):
            response["Cache-Control"] = "private, no-store"
        match = request.resolver_match
        if match is not None:
            from .views import action

            if match.func is action:
                # Keep capability paths/secrets out of Referer without suppressing
                # the origin required by native forms and HTTPS CSRF checks.
                response["Referrer-Policy"] = "strict-origin"
                response["Cache-Control"] = "private, no-store"
        return response
