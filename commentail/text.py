"""Visible characters: Unicode graphemes, including composed emoji."""

import regex


def character_count(text: str) -> int:
    return sum(1 for _ in regex.finditer(r"\X", text, timeout=1))
