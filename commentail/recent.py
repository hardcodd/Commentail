"""Read-only recent-comment selection with the visitor's target permissions."""

from collections import deque
from datetime import datetime
from typing import TypedDict

from django.db.models import Q, prefetch_related_objects
from django.http import HttpRequest
from django.utils import timezone
from wagtail.models import Page, PageViewRestriction, Site

from .models import Comment, Discussion, Mode, SiteCommentSettings


class RecentComment(TypedDict):
    """Plain presentation data; no private fields or model instances."""

    id: int
    author_name: str
    text: str
    published_at: datetime
    target_title: str
    url: str


def _plain_text(value: str) -> str:
    # Drop SafeString markers supplied by host hooks: these fields are plain text.
    return str.__str__(value)


def _page_access(request: HttpRequest, pages: dict[int, Page]) -> dict[int, bool]:
    """Batch ordinary inherited restrictions; aliases use Wagtail's own resolver.

    Alias ancestry can point outside the Site tree. Retaining the native check
    for those pages avoids assuming that a restriction follows the alias path.
    Decisions and model instances never outlive this selector call.
    """
    paths = {
        page.path[:length]
        for page in pages.values()
        for length in range(Page.steplen, len(page.path) + 1, Page.steplen)
    }
    if not paths:
        return {}
    aliases = list(Page.objects.filter(
        path__in=paths, alias_of__isnull=False,
    ).values_list("path", flat=True))
    rules = list(PageViewRestriction.objects.filter(
        page__path__in=paths,
    ).select_related("page").prefetch_related("groups"))
    native_pages = {
        identifier for identifier, page in pages.items()
        if getattr(type(page), "get_view_restrictions", None) is not Page.get_view_restrictions
        or any(page.path.startswith(path) for path in aliases)
    }
    user = request.user
    original_cache = getattr(user, "_prefetched_objects_cache", None)
    prefetch_groups = user.is_authenticated and not user.is_superuser and (
        native_pages or any(rule.restriction_type == rule.GROUPS for rule in rules)
    )
    if prefetch_groups:
        # Native accept_request must retain host overrides. Its groups.all()
        # can share a prefetch, but that cache must not survive this selection.
        user._prefetched_objects_cache = dict(original_cache or {})
        prefetch_related_objects([user], "groups")
    try:
        accepted = {rule.pk: rule.accept_request(request) for rule in rules}
        result = {}
        for identifier, page in pages.items():
            if identifier in native_pages:
                result[identifier] = all(
                    rule.accept_request(request) for rule in page.get_view_restrictions()
                )
            else:
                result[identifier] = all(
                    accepted[rule.pk] for rule in rules
                    if page.path.startswith(rule.page.path)
                )
        return result
    finally:
        if prefetch_groups:
            if original_cache is None:
                del user._prefetched_objects_cache
            else:
                user._prefetched_objects_cache = original_cache


def _target_data(
    request: HttpRequest, discussion: Discussion, page_allowed: bool = True,
) -> tuple[str, str] | None:
    """Check a target and resolve its title and URL once, including widget removal."""
    from .detection import DetectionError, has_comments
    from .objects import (
        ObjectAccessError,
        _target_url,
        checked_site,
        discussion_url,
        target_for,
    )

    if discussion.page_id:
        obj = discussion.page
        try:
            if (
                not obj.live or not obj.path.startswith(discussion.site.root_page.path)
                or not page_allowed or not has_comments(obj, request)
            ):
                return None
        except DetectionError:
            return None
        title = _plain_text(obj.title)
    else:
        try:
            obj = target_for(discussion)
            if checked_site(obj, request).pk != discussion.site_id:
                return None
            title = _plain_text(str(obj))
        except ObjectAccessError:
            return None
    try:
        destination = _target_url(discussion, obj)
    except ObjectAccessError:
        destination = discussion_url(discussion)
    return title, destination


def recent_comments(
    request: HttpRequest, *, limit: int, page: Page | None, include_replies: bool
) -> list[RecentComment]:
    """Return up to limit accessible published comments, newest publication first.

    Inspect targets before counting rows toward the limit. Access decisions are
    reused only within this call; never cache them across requests or visitors.
    The request marker lets CapabilityHeadersMiddleware protect personalized HTML.
    """
    from .avatars import author_name
    from .objects import _comment_url

    request.META["COMMENTAIL_PRIVATE"] = True
    if limit == 0:
        return []
    site = Site.find_for_request(request)
    if site is None:
        return []
    discussions = Discussion.objects.filter(site=site).filter(
        Q(page__isnull=True)
        | Q(page__live=True, page__path__startswith=site.root_page.path)
    ).exclude(mode=Mode.HIDDEN)
    if page is not None:
        discussions = discussions.filter(page=page)
    default_mode = SiteCommentSettings.objects.filter(site=site).values_list(
        "mode", flat=True,
    ).first() or Mode.OPEN
    if default_mode == Mode.HIDDEN:
        discussions = discussions.exclude(mode="")
    # Keep Site/Page eligibility in a subquery. Joining it into the ordered read
    # can make the planner sort a whole discussion before applying a small LIMIT.
    comments = Comment.objects.filter(
        discussion_id__in=discussions.values("pk"),
        status=Comment.Status.PUBLISHED,
        published_at__lte=timezone.now(),
    ).select_related("user", "discussion__content_type").order_by("-published_at", "-pk")
    if not include_replies:
        comments = comments.filter(root__isnull=True)

    targets: dict[int, tuple[str, str] | None] = {}
    resolved: dict[int, Discussion] = {}
    rows: list[RecentComment] = []
    batch_size = min(100, max(20, limit))
    cursor = None
    # A bounded exclusion window skips dense denied discussions without building
    # an arbitrarily large SQL parameter list on sites with many private targets.
    denied: deque[int] = deque(maxlen=100)
    while True:
        candidates = comments.exclude(discussion_id__in=denied)
        if cursor is not None:
            timestamp, identifier = cursor
            candidates = candidates.filter(
                Q(published_at__lt=timestamp) | Q(published_at=timestamp, pk__lt=identifier)
            )
        batch = list(candidates[:batch_size])
        if not batch:
            break
        new_discussions = {
            item.discussion_id: item.discussion for item in batch
            if item.discussion_id not in targets
        }
        resolved.update(new_discussions)
        pages = {
            item.pk: item for item in Page.objects.filter(
                pk__in=[d.page_id for d in new_discussions.values() if d.page_id]
            ).specific()
        }
        allowed = _page_access(request, pages)
        for discussion in new_discussions.values():
            discussion.site = site
            if discussion.page_id:
                if discussion.page_id not in pages:
                    targets[discussion.pk] = None
                    denied.append(discussion.pk)
                    continue
                discussion.page = pages[discussion.page_id]
            data = _target_data(request, discussion, allowed.get(discussion.page_id, True))
            targets[discussion.pk] = data
            if data is None:
                denied.append(discussion.pk)
        for comment in batch:
            comment.discussion = resolved[comment.discussion_id]
            data = targets[comment.discussion_id]
            if data is None:
                continue
            title, destination = data
            rows.append({
                "id": comment.pk,
                "author_name": _plain_text(author_name(comment, request)),
                "text": _plain_text(comment.text),
                "published_at": comment.published_at,
                "target_title": title,
                "url": _comment_url(destination, comment.pk),
            })
            if len(rows) == limit:
                return rows
        cursor = batch[-1].published_at, batch[-1].pk
        if len(batch) < batch_size:
            break
    return rows
