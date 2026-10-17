"""Schema.org metadata for the public rows rendered in the current widget.

No queries or author callbacks run here. The caller supplies the same resolved
name used by the visible HTML; private cards never enter this representation.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from django.utils.html import json_script
from django.utils.safestring import SafeString, mark_safe

from .models import Comment

# Functional syntax preserves JSON-LD keywords without untyped dictionary values.
Reference = TypedDict("Reference", {"@id": str})
Person = TypedDict("Person", {"@type": str, "name": str})
CommentEntity = TypedDict(
    "CommentEntity",
    {
        "@type": str,
        "@id": str,
        "url": str,
        "text": str,
        "author": Person,
        "datePublished": str,
        "about": Reference,
        "dateModified": NotRequired[str],
        "parentItem": NotRequired[Reference],
    },
)


@dataclass(frozen=True)
class CommentMarkup:
    identifier: str
    url: str
    target: str
    author: str
    text: str
    published: str
    modified: str | None
    parent: str | None

    def as_json_ld(self) -> CommentEntity:
        entity: CommentEntity = {
            "@type": "Comment",
            "@id": self.identifier,
            "url": self.url,
            "text": self.text,
            "author": {"@type": "Person", "name": self.author},
            "datePublished": self.published,
            "about": {"@id": self.target},
        }
        if self.modified:
            entity["dateModified"] = self.modified
        if self.parent:
            entity["parentItem"] = {"@id": self.parent}
        return entity


def comment_markup(
    comment: Comment,
    name: str,
    target: str,
    permalink: str,
) -> CommentMarkup | None:
    """Return metadata only for a published row with a resolved host URL."""
    if not target or comment.status != "published" or comment.published_at is None:
        return None
    return CommentMarkup(
        identifier=f"{target}#commentail-{comment.pk}",
        url=permalink,
        target=target,
        author=name,
        text=comment.text,
        published=comment.published_at.isoformat(),
        modified=comment.edited_at.isoformat() if comment.edited_at else None,
        parent=f"{target}#commentail-{comment.reply_to_id}"
        if comment.reply_to_id
        else None,
    )


def render_json_ld(comments: Iterable[CommentMarkup]) -> SafeString | str:
    """Serialize passive linked data using Django's script-safe escaping."""
    graph = [comment.as_json_ld() for comment in comments]
    if not graph:
        return ""
    script = json_script({"@context": "https://schema.org", "@graph": graph})
    # Only the constant MIME wrapper changes; Django still escapes all data.
    return mark_safe(
        script.replace('type="application/json"', 'type="application/ld+json"', 1)
    )
