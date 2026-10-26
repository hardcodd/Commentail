"""Whole-word moderation matching; display text is never normalized."""

import re
from dataclasses import dataclass, field

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
    highlight_staff: bool = True


def editorial_settings(discussion: Discussion) -> EditorialSettings:
    """Resolve discussion overrides against Site defaults, retaining explicit False."""
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
        highlight_staff=defaults.highlight_staff,
    )


def email_enabled(site_id: int) -> bool:
    """Site-wide mail switch; pages cannot override it."""
    value = (
        SiteCommentSettings.objects.filter(site_id=site_id)
        .values_list("email_enabled", flat=True)
        .first()
    )
    return value is not False


def words(text: str) -> tuple[str, ...]:
    """Normalize only comparison tokens; never change stored or rendered text."""
    return tuple(
        re.findall(r"[^\W_]+", text.casefold().replace("ё", "е"), flags=re.UNICODE)
    )


@dataclass(slots=True)
class _RuleNode:
    children: dict[str, "_RuleNode"] = field(default_factory=dict)
    decision: "RuleDecision | None" = None


@dataclass(frozen=True, slots=True)
class RuleDecision:
    """Matched status and sender-facing reason, selected by stable rule ID."""

    status: str
    reason: str
    rule_id: int

    @property
    def priority(self) -> tuple[bool, int]:
        """Reject before review, then choose the oldest matching rule."""
        return self.status != "rejected", self.rule_id


def matching_rule(text: str) -> RuleDecision | None:
    """Match whole-word phrases without comparing every rule at every position.

    A call-local trie shares rule prefixes and avoids caching stale moderation
    decisions between submissions. Rejection wins over review, including duplicate
    phrases. Only phrases beginning with a word in this text need trie entries.
    """
    tokens = words(text)
    root = _RuleNode()
    initial_words = set(tokens)
    for identifier, phrase_text, action, reason in (
        ModerationRule.objects.filter(enabled=True)
        .values_list("pk", "phrase", "action", "reason")
        .iterator(chunk_size=1000)
    ):
        phrase = words(phrase_text)
        if not phrase or phrase[0] not in initial_words:
            continue
        node = root
        for word in phrase:
            if word not in node.children:
                node.children[word] = _RuleNode()
            node = node.children[word]
        decision = RuleDecision(
            "rejected" if action == ModerationRule.Action.REJECT else "pending",
            reason.strip(),
            identifier,
        )
        if node.decision is None or decision.priority < node.decision.priority:
            node.decision = decision
    matched: RuleDecision | None = None
    for start in range(len(tokens)):
        node = root
        for position in range(start, len(tokens)):
            node = node.children.get(tokens[position])
            if node is None:
                break
            candidate = node.decision
            if candidate is not None and (
                matched is None or candidate.priority < matched.priority
            ):
                matched = candidate
    return matched


def policy_result(text: str, policy: str, *, guest: bool, suspicious: bool) -> str:
    """Apply reject-before-review rules, then suspicious/guest moderation policy."""
    if policy not in Policy.values:
        raise ValueError("Unknown moderation policy")
    if policy == Policy.RULES and (result := matching_rule(text)):
        return result.status
    if suspicious or policy == Policy.ALL or (policy == Policy.GUESTS and guest):
        return "pending"
    return "published"
