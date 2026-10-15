from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.template import Context, NodeList, TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import get_template
from django.template.loader_tags import ExtendsNode, IncludeNode
from django.utils.module_loading import import_string
from wagtail.models import Page, Site

from .config import configuration_errors, technical_settings
from .templatetags.commentail_tags import CommentailNode


class DetectionError(ValueError):
    """The library cannot establish the effective template chain."""


def effective_settings(site: Site | None) -> dict[str, object]:
    if errors := configuration_errors():
        raise ImproperlyConfigured("; ".join(errors))
    if site:
        return dict(technical_settings(site))
    from django.conf import settings

    return dict(getattr(settings, "COMMENTAIL", {}).get("default", {}))


def has_comments(page: Page, request: HttpRequest) -> bool:
    """Inspect compiled nodes without rendering user templates or evaluating conditions.

    A configured resolver must enumerate unresolved dynamic dependencies. Template
    nodes are version-sensitive internals covered by integration tests.
    """
    config = effective_settings(Site.find_for_request(request))
    resolver_path = config.get("GET_COMMENT_TEMPLATES")
    resolver = import_string(str(resolver_path)) if resolver_path else None
    try:
        names = resolver(page, request) if resolver else [page.get_template(request)]
    except Exception as exc:
        # Do not expose handler exception payloads in editorial messages.
        raise DetectionError("Comment template handler failed") from exc
    if not isinstance(names, (list, tuple)) or not all(
        isinstance(n, str) for n in names
    ):
        raise DetectionError("GET_COMMENT_TEMPLATES must return template names")
    seen: set[str] = set()

    def load(name: str) -> bool:
        if name in seen:
            return False
        seen.add(name)
        compiled = get_template(name).template
        return scan(compiled.nodelist)

    def dependency(expression: object) -> bool:
        if getattr(expression, "is_var", True):
            if resolver:
                return False  # Resolver enumerates this dependency in names.
            raise DetectionError(
                "Dynamic template dependency requires GET_COMMENT_TEMPLATES"
            )
        value = expression.resolve(Context())
        candidates = [value] if isinstance(value, str) else list(value)
        for name in candidates:
            try:
                return load(name)
            except TemplateDoesNotExist:
                continue
        raise DetectionError("Included template not found")

    def scan(nodes: NodeList) -> bool:
        for node in nodes:
            if isinstance(node, CommentailNode):
                return True
            if isinstance(node, ExtendsNode) and dependency(node.parent_name):
                return True
            if isinstance(node, IncludeNode) and dependency(node.template):
                return True
            # Presence controls configuration, even in overridden blocks or
            # false conditions. Rendering is deliberately not simulated.
            for attr in getattr(node, "child_nodelists", ()):
                children = getattr(node, attr, None)
                if isinstance(children, NodeList) and scan(children):
                    return True
        return False

    try:
        return any(load(name) for name in names)
    except (TemplateDoesNotExist, TemplateSyntaxError) as exc:
        raise DetectionError(str(exc)) from exc
