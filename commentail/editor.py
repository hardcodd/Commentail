"""Server admission policy and safe presentation for comment text formats."""

from django.utils.safestring import SafeString, mark_safe

from .markdown import FEATURES, MarkdownError, parse, render, render_plain, walk
from .policies import EditorialSettings

_FEATURE = {
    "strong": "bold",
    "emphasis": "italic",
    "strike": "strike",
    "link": "link",
    "quote": "quote",
    "code": "inlineCode",
    "codeBlock": "codeBlock",
}


def settings_for(
    options: EditorialSettings, *, guest: bool, text_format: str | None = None
) -> dict:
    """Resolve current Site policy, preserving legacy plain-text editing.

    Existing Markdown keeps its format after a mode change. When Markdown is
    disabled, its source stays editable but new formatting cannot be submitted.
    Rendering existing content is deliberately independent from admission policy.
    """
    mode = options.guest_editor if guest else options.registered_editor
    if mode not in ("plain", "markdown", "visual"):
        raise MarkdownError("Invalid editor mode")
    features = list(options.editor_features)
    if len(features) != len(set(features)) or any(
        name not in FEATURES for name in features
    ):
        raise MarkdownError("Invalid editor capabilities")
    if text_format == "plain":
        mode = "plain"
    elif text_format == "markdown" and mode == "plain":
        mode, features = "markdown", []
    return {"guest": mode, "registered": mode, "features": features}


def validate_text(
    text: str,
    options: EditorialSettings,
    *,
    guest: bool,
    text_format: str | None = None,
) -> str:
    """Infer format from trusted settings and reject forbidden nested constructs."""
    policy = settings_for(options, guest=guest, text_format=text_format)
    if policy["guest"] == "plain":
        return "plain"
    document = parse(text)
    if not any(
        node.type in ("text", "code", "codeBlock") and node.value.strip()
        for node in walk(document.children)
    ):
        raise MarkdownError("Comment is empty")
    for node in walk(document.children):
        feature = (
            ("orderedList" if node.ordered else "unorderedList")
            if node.type == "list"
            else _FEATURE.get(node.type)
        )
        if feature and feature not in policy["features"]:
            raise MarkdownError("This formatting is disabled for this site.")
        if node.type == "link" and len(node.href) > 2048:
            raise MarkdownError("Link address is too long.")
    return "markdown"


def render_markdown(text: str) -> SafeString:
    """Only the bounded parser can produce trusted HTML; never mark source safe."""
    return mark_safe(render(text))


def visible_text(text: str, text_format: str) -> str:
    """Plain presentation for metadata; old plain text remains literal."""
    return render_plain(text) if text_format == "markdown" else text
