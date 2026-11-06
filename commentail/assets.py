"""Content-versioned package resources shared by public tags and admin forms."""

from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
from typing import Literal

from django.templatetags.static import static

Asset = Literal[
    "admin.css",
    "admin.js",
    "commentail.css",
    "commentail.js",
    "editor.js",
    "editor.css",
    "editor-ru.js",
    "editor-de.js",
    "editor-fr.js",
    "editor-es.js",
    "editor-pt-br.js",
]


@lru_cache(maxsize=11)
def asset_url(name: Asset) -> str:
    """Resolve a known package asset through host static storage with a content hash."""
    if name not in (
        "admin.css",
        "admin.js",
        "commentail.css",
        "commentail.js",
        "editor.js",
        "editor.css",
        "editor-ru.js",
        "editor-de.js",
        "editor-fr.js",
        "editor-es.js",
        "editor-pt-br.js",
    ):
        raise ValueError("Unknown Commentail asset")
    version = sha256(
        files("commentail").joinpath("static", "commentail", name).read_bytes()
    ).hexdigest()[:12]
    url = static("commentail/" + name)
    return url + ("&" if "?" in url else "?") + "v=" + version


def editor_locale_url(language: str | None) -> str:
    """Load one supported locale; English and unknown languages need no payload."""
    primary = (language or "").lower().replace("_", "-").split("-")[0]
    if primary == "pt":
        return asset_url("editor-pt-br.js")
    names: dict[str, Asset] = {
        "ru": "editor-ru.js",
        "de": "editor-de.js",
        "fr": "editor-fr.js",
        "es": "editor-es.js",
    }
    return asset_url(names[primary]) if primary in names else ""
