"""Public tags render server HTML; resources are explicitly placed by the host."""

from collections.abc import Iterable

from django import template
from django.db.models import Model
from django.http import HttpRequest
from django.template import Context, Node, TemplateSyntaxError
from django.template.base import FilterExpression, Parser, Token
from django.template.loader import render_to_string
from django.utils.html import format_html
from wagtail.models import Page

from commentail.assets import Asset, asset_url
from commentail.recent import RecentComment
from commentail.structured import CommentMarkup, render_json_ld

register = template.Library()


@register.simple_tag(takes_context=True)
def commentail_recent(
    context: Context,
    limit: int = 5,
    *,
    page: Page | None = None,
    include_replies: bool = True,
) -> list[RecentComment]:
    """Select recent accessible comments for host markup using `as variable`."""
    from commentail.recent import recent_comments

    if type(limit) is not int or limit < 0:
        raise TemplateSyntaxError(
            "commentail_recent limit must be a nonnegative integer"
        )
    if type(include_replies) is not bool:
        raise TemplateSyntaxError("commentail_recent include_replies must be a boolean")
    request = context.get("request")
    if not isinstance(request, HttpRequest):
        return []
    if page is not None and (
        not isinstance(page, Page) or page.pk is None or page._state.adding
    ):
        return []
    return recent_comments(
        request, limit=limit, page=page, include_replies=include_replies
    )


class CommentailNode(Node):
    def __init__(self, expression: FilterExpression) -> None:
        self.expression = expression

    def render(self, context: Context) -> str:
        from commentail.public import block_context, get_discussion

        target = self.expression.resolve(context)
        request = context.get("request")
        if not isinstance(target, Model) or request is None or target.pk is None:
            return ""
        from django.http import Http404
        from django.utils.translation import gettext as _

        from commentail.objects import ObjectAccessError, get_object_discussion

        try:
            discussion = (
                get_discussion(request, target.pk)
                if isinstance(target, Page)
                else get_object_discussion(request, target)
            )
            return render_to_string(
                "commentail/block.html",
                block_context(request, discussion),
                request=request,
            )
        except ObjectAccessError:
            return format_html(
                '<p class="commentail-muted">{}</p>', _("Comments are unavailable.")
            )
        except Http404:
            return ""


@register.tag("commentail")
def commentail(parser: Parser, token: Token) -> CommentailNode:
    bits = token.split_contents()
    if len(bits) != 2:
        raise TemplateSyntaxError("commentail requires one target")
    return CommentailNode(parser.compile_filter(bits[1]))


@register.simple_tag
def commentail_css() -> str:
    return format_html('<link rel="stylesheet" href="{}">', asset_url("commentail.css"))


@register.simple_tag
def commentail_js() -> str:
    return format_html('<script defer src="{}"></script>', asset_url("commentail.js"))


@register.simple_tag
def commentail_asset(name: Asset) -> str:
    return asset_url(name)


@register.simple_tag
def commentail_json_ld(comments: Iterable[CommentMarkup]) -> str:
    """Render the widget's eligible public comment entities as passive JSON-LD."""
    return render_json_ld(comments)
