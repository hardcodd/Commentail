"""Current Site page-tree boundaries, including Wagtail's translated homepages."""

from django.conf import settings
from wagtail.models import Site


def site_page_paths(site: Site) -> tuple[str, ...]:
    """Return allowed tree prefixes without caching access across requests.

    Wagtail routes translated homepages as sibling trees of the configured root
    when content internationalization is enabled. Only that root's translation
    group belongs here; an arbitrary page translation grants no tree access.
    Callers still enforce live state and restrictions on the actual target.
    """
    root = site.root_page
    if not getattr(settings, "WAGTAIL_I18N_ENABLED", False):
        return (root.path,)

    return tuple(root.get_translations(inclusive=True).values_list("path", flat=True))
