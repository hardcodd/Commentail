"""Validate rule files before merging; CSV interchange never deletes rules."""

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from .models import ModerationRule

LEGACY_HEADERS = ("phrase", "action", "enabled")
HEADERS = (*LEGACY_HEADERS, "reason")
SPREADSHEET_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "'")


@dataclass(frozen=True)
class RuleRow:
    """Validated input; an absent reason preserves existing values on import."""

    phrase: str
    action: str
    enabled: bool
    line: int
    reason: str | None = None


@dataclass(frozen=True)
class ImportResult:
    added: int
    updated: int
    unchanged: int


def _needs_escape(value: str) -> bool:
    return value.lstrip(" ").startswith(SPREADSHEET_PREFIXES)


def spreadsheet_text(value: str) -> str:
    """Prefix formula-like text and literal apostrophes for reversible export."""
    return "'" + value if _needs_escape(value) else value


def parse_rules(data: bytes, max_rows: int) -> list[RuleRow]:
    """Accept UTF-8 comma/semicolon files; raise a localized first-row error."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValidationError(_("The CSV file must use UTF-8 encoding.")) from error
    if not text:
        raise ValidationError(_("The CSV file is empty."))
    try:
        delimiter = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;").delimiter
        reader = csv.reader(
            io.StringIO(text, newline=""), delimiter=delimiter, strict=True
        )
        headers = next(reader)
        if tuple(sorted(headers)) not in (
            tuple(sorted(LEGACY_HEADERS)),
            tuple(sorted(HEADERS)),
        ):
            raise ValidationError(
                _("CSV headers must be phrase, action, enabled, with optional reason.")
            )
        rows: list[RuleRow] = []
        phrases: set[str] = set()
        for values in reader:
            if not values:
                continue
            line = reader.line_num
            if len(rows) >= max_rows:
                raise ValidationError(
                    _("The CSV file exceeds the limit of %(limit)s rules."),
                    params={"limit": max_rows},
                )
            if len(values) != len(headers):
                raise ValidationError(
                    _("Row %(line)s: expected %(columns)s columns."),
                    params={"line": line, "columns": len(headers)},
                )
            cells = dict(zip(headers, values, strict=True))
            phrase = cells["phrase"]
            if phrase.startswith("'") and _needs_escape(phrase[1:]):
                phrase = phrase[1:]
            reason = cells.get("reason")
            if reason is not None:
                if reason.startswith("'") and _needs_escape(reason[1:]):
                    reason = reason[1:]
                if len(reason) > 2000 or "\x00" in reason:
                    raise ValidationError(
                        _(
                            "Row %(line)s: reason must contain at most 2000 characters without null bytes."
                        ),
                        params={"line": line},
                    )
            if not phrase.strip() or len(phrase) > 255 or "\x00" in phrase:
                raise ValidationError(
                    _(
                        "Row %(line)s: phrase must contain 1–255 characters without null bytes."
                    ),
                    params={"line": line},
                )
            if phrase in phrases:
                raise ValidationError(
                    _("Row %(line)s: duplicate phrase in the file."),
                    params={"line": line},
                )
            action = cells["action"].strip().lower()
            enabled = cells["enabled"].strip().lower()
            if action not in ModerationRule.Action.values:
                raise ValidationError(
                    _("Row %(line)s: action must be review or reject."),
                    params={"line": line},
                )
            if enabled not in ("1", "0", "true", "false"):
                raise ValidationError(
                    _("Row %(line)s: enabled must be 1, 0, true or false."),
                    params={"line": line},
                )
            phrases.add(phrase)
            rows.append(RuleRow(phrase, action, enabled in ("1", "true"), line, reason))
    except (csv.Error, StopIteration) as error:
        raise ValidationError(
            _("Invalid CSV structure: check the delimiter and quoting.")
        ) from error
    if not rows:
        raise ValidationError(_("The CSV file contains no rules."))
    return rows


@transaction.atomic
def import_rules(rows: list[RuleRow]) -> ImportResult:
    """Merge exact phrases atomically; ambiguity aborts the whole import."""
    existing: dict[str, ModerationRule] = {}
    duplicates: set[str] = set()
    for rule in ModerationRule.objects.select_for_update().filter(
        phrase__in=[row.phrase for row in rows]
    ):
        if rule.phrase in existing:
            duplicates.add(rule.phrase)
        existing[rule.phrase] = rule
    additions: list[ModerationRule] = []
    updates: list[ModerationRule] = []
    unchanged = 0
    for row in rows:
        if row.phrase in duplicates:
            raise ValidationError(
                _(
                    "Row %(line)s: multiple existing rules have this phrase; resolve them before importing."
                ),
                params={"line": row.line},
            )
        rule = existing.get(row.phrase)
        if rule is None:
            additions.append(
                ModerationRule(
                    phrase=row.phrase,
                    action=row.action,
                    enabled=row.enabled,
                    reason=row.reason or "",
                )
            )
        elif (rule.action, rule.enabled, rule.reason) == (
            row.action,
            row.enabled,
            rule.reason if row.reason is None else row.reason,
        ):
            unchanged += 1
        else:
            rule.action, rule.enabled = row.action, row.enabled
            if row.reason is not None:
                rule.reason = row.reason
            updates.append(rule)
    ModerationRule.objects.bulk_create(additions)
    ModerationRule.objects.bulk_update(updates, ("action", "enabled", "reason"))
    return ImportResult(len(additions), len(updates), unchanged)


def export_rules() -> Iterator[str]:
    """Stream all rules with bounded buffering and stable machine values."""
    yield "\ufeff"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    writer.writerow(HEADERS)
    yield buffer.getvalue()
    for rule in ModerationRule.objects.order_by("phrase", "pk").iterator():
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow(
            (
                spreadsheet_text(rule.phrase),
                rule.action,
                "1" if rule.enabled else "0",
                spreadsheet_text(rule.reason),
            )
        )
        yield buffer.getvalue()
