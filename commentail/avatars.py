"""Deterministic initials/gradient and a safe read-only avatar callback."""

import logging
from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Model
from django.http import HttpRequest
from django.utils.module_loading import import_string
from wagtail.models import Site

from .config import technical_settings
from .models import Comment
from .objects import target_for

logger = logging.getLogger("commentail")


@dataclass(frozen=True)
class CommentContext:
    id: int
    display_name: str
    user: AbstractBaseUser | None
    site: Site
    target: Model


def default_avatar(name: str) -> tuple[str, str]:
    """Return uppercase initials and their deterministic CSS gradient.

    Use two characters for one word, or the first and last word's initials.
    Empty names share a neutral fallback; no external avatar service is used.
    """
    words = name.strip().split()
    if not words:
        return "?", "linear-gradient(135deg, hsl(220 85% 56%), hsl(265 85% 60%))"
    if len(words) == 1:
        initials = words[0][:2].upper()
    else:
        initials = (words[0][0] + words[-1][0]).upper()
    hashed = 2166136261
    for letter in initials:
        hashed = ((hashed ^ ord(letter)) * 16777619) & 0xFFFFFFFF
    hue = hashed % 360
    second = (hue + 45 + ((hashed >> 8) % 90)) % 360
    gradient = (
        f"linear-gradient(135deg, "
        f"hsl({hue} {78 + hashed % 12}% {48 + ((hashed >> 12) % 8)}%), "
        f"hsl({second} {80 + ((hashed >> 4) % 12)}% {50 + ((hashed >> 20) % 8)}%))"
    )
    return initials, gradient


def author_name(comment: Comment, request: HttpRequest) -> str:
    """Resolve an account's name hook, falling back on empty/invalid output or error.

    Guests retain their stored name. Hook failures log only the exception type.
    The result is plain text; the rendering boundary must escape it.
    """
    path = technical_settings(comment.discussion.site)["GET_AUTHOR_NAME"]
    if path and comment.user_id:
        try:
            value = import_string(path)(comment.user, request)
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception as exc:
            logger.exception(
                "Author name handler failed (%s)", type(exc).__name__, exc_info=False
            )
    return comment.display_name


def avatar_url(comment: Comment, request: HttpRequest, name: str) -> str | None:
    """Call the avatar hook with a restricted context, or return None for fallback.

    The hook receives no guest email or comment text. Empty/invalid output and
    hook failures select the default avatar; errors log only their type.
    """
    path = technical_settings(comment.discussion.site)["GET_AVATAR"]
    if not path:
        return None
    try:
        value = import_string(path)(
            CommentContext(
                comment.pk,
                name,
                comment.user,
                comment.discussion.site,
                target_for(comment.discussion),
            ),
            request,
        )
        return value if isinstance(value, str) and value else None
    except Exception as exc:
        logger.exception(
            "Avatar handler failed (%s)", type(exc).__name__, exc_info=False
        )
        return None
