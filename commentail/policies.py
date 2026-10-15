"""Whole-word moderation matching; display text is never normalized."""

import re
from dataclasses import dataclass

from .models import (
    Discussion,
    ModerationRule,
    Policy,
    SiteCommentSettings,
)


@dataclass(frozen=True)
class EditorialSettings:
    mode: str
    moderation: str
    access: str
    max_length: int
    clickable_links: bool
    notify_publication: bool
    notify_rejection: bool


def editorial_settings(discussion: Discussion) -> EditorialSettings:
    site = SiteCommentSettings.objects.filter(site_id=discussion.site_id).first()
    defaults = site or SiteCommentSettings()
    return EditorialSettings(
        mode=discussion.mode or defaults.mode,
        moderation=discussion.moderation or defaults.moderation,
        access=discussion.access or defaults.access,
        max_length=defaults.max_length
        if discussion.max_length is None
        else discussion.max_length,
        clickable_links=defaults.clickable_links
        if discussion.clickable_links is None
        else discussion.clickable_links,
        notify_publication=defaults.notify_publication
        if discussion.notify_publication is None
        else discussion.notify_publication,
        notify_rejection=defaults.notify_rejection
        if discussion.notify_rejection is None
        else discussion.notify_rejection,
    )


def words(text: str) -> tuple[str, ...]:
    return tuple(
        re.findall(r"[^\W_]+", text.casefold().replace("ё", "е"), flags=re.UNICODE)
    )


def policy_result(text: str, policy: str, *, guest: bool, suspicious: bool) -> str:
    if policy not in Policy.values:
        raise ValueError("Unknown moderation policy")
    if policy == Policy.RULES:
        tokens = words(text)
        review = False
        for rule in ModerationRule.objects.filter(enabled=True):
            phrase = words(rule.phrase)
            if phrase and any(
                tokens[i : i + len(phrase)] == phrase
                for i in range(len(tokens) - len(phrase) + 1)
            ):
                if rule.action == ModerationRule.Action.REJECT:
                    return "rejected"
                review = True
        if review:
            return "pending"
    if suspicious or policy == Policy.ALL or (policy == Policy.GUESTS and guest):
        return "pending"
    return "published"
