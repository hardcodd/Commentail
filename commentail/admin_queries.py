"""Read-only moderation queries; Site visibility is applied before filters."""

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.http import HttpRequest
from django.utils.dateparse import parse_date

from .models import Comment, CommentRevision
from .permissions import sites_for
from .validation import valid_identifier


def _comments(request: HttpRequest) -> QuerySet[Comment]:
    """Restrict every moderation read to Sites the actor may view."""
    return Comment.objects.filter(
        discussion__site__in=sites_for(request.user, "view")
    ).select_related(
        "discussion__site", "discussion__page", "discussion__content_type", "user"
    )


def filtered_comments(request: HttpRequest) -> QuerySet[Comment]:
    """Apply author/text, target and date filters before status tab aggregation.

    Invalid identifiers/dates return no rows rather than ignoring a filter.
    Account name fields are discovered from the host's configured user model.
    """
    query = _comments(request).annotate(
        pending_revision=Exists(
            CommentRevision.objects.filter(comment_id=OuterRef("pk"), status="pending")
        )
    )
    if value := request.GET.get("site"):
        query = (
            query.filter(discussion__site_id=value)
            if valid_identifier(value)
            else query.none()
        )
    if value := request.GET.get("page"):
        query = (
            query.filter(discussion__page_id=value)
            if valid_identifier(value)
            else query.none()
        )
    if value := request.GET.get("q"):
        names = Q()
        for field in (get_user_model().USERNAME_FIELD, "first_name", "last_name"):
            if field in {item.name for item in get_user_model()._meta.fields}:
                names |= Q(**{f"user__{field}__icontains": value})
        query = query.filter(
            names
            | Q(text__icontains=value)
            | Q(guest_name__icontains=value)
            | Q(email__icontains=value)
            | Q(user__email__icontains=value)
        )
    for key, lookup in [
        ("from", "created_at__date__gte"),
        ("to", "created_at__date__lte"),
    ]:
        if value := request.GET.get(key):
            try:
                day = parse_date(value)
            except ValueError:
                day = None
            query = query.filter(**{lookup: day}) if day else query.none()
    return query
