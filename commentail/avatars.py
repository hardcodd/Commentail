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
    words = name.strip().split()
    initials = (
        (words[0][:2] if len(words) == 1 else words[0][0] + words[-1][0]).upper()
        if words
        else ""
    )
    if not initials:
        return "?", "linear-gradient(135deg, hsl(220 85% 56%), hsl(265 85% 60%))"
    hashed = 2166136261
    for letter in initials:
        hashed = ((hashed ^ ord(letter)) * 16777619) & 0xFFFFFFFF
    hue = hashed % 360
    second = (hue + 45 + ((hashed >> 8) % 90)) % 360
    gradient = f"linear-gradient(135deg, hsl({hue} {78 + hashed % 12}% {48 + ((hashed >> 12) % 8)}%), hsl({second} {80 + ((hashed >> 4) % 12)}% {50 + ((hashed >> 20) % 8)}%))"
    return initials, gradient


def author_name(comment: Comment, request: HttpRequest) -> str:
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
