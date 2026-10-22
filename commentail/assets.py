"""Content-versioned package resources shared by public tags and admin forms."""

from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
from typing import Literal

from django.templatetags.static import static

Asset = Literal["admin.css", "admin.js", "commentail.css", "commentail.js"]


@lru_cache(maxsize=4)
def asset_url(name: Asset) -> str:
    """Resolve a known package asset through host static storage with a content hash."""
    if name not in ("admin.css", "admin.js", "commentail.css", "commentail.js"):
        raise ValueError("Unknown Commentail asset")
    version = sha256(
        files("commentail").joinpath("static", "commentail", name).read_bytes()
    ).hexdigest()[:12]
    url = static("commentail/" + name)
    return url + ("&" if "?" in url else "?") + "v=" + version
