"""Explicit non-Page target registration; generic IDs never authorize access.

Adapters are stateless classes constructed without arguments. Every request
re-resolves the target and validates Site and view permission. Handler failures
fail closed; no exception text or target content is logged or returned.
"""

import logging
from typing import Protocol, cast
from urllib.parse import urlsplit

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils.module_loading import import_string
from wagtail.models import Page, Site

from .models import Discussion

logger = logging.getLogger("commentail.objects")


class ObjectAccessError(Exception):
    """Target is unavailable, unregistered or denied; never a permission grant."""


class ObjectAdapterError(ObjectAccessError):
    """A project handler failed, rather than returning a normal access denial."""


class ObjectAdapter(Protocol):
    def get_site(self, obj: models.Model, request: HttpRequest) -> Site: ...
    def can_view(self, obj: models.Model, request: HttpRequest) -> bool: ...
    def get_url(self, obj: models.Model, site: Site) -> str: ...


def registry_errors(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["OBJECT_ADAPTERS must be a model-label to adapter-class dictionary"]
    errors: list[str] = []
    seen: set[str] = set()
    for label, path in value.items():
        try:
            if not isinstance(label, str) or not isinstance(path, str):
                raise TypeError
            model = apps.get_model(label)
            if (
                model is None
                or issubclass(model, Page)
                or model._meta.abstract
                or model._meta.proxy
                or model._meta.app_label in {"commentail", "contenttypes"}
            ):
                raise ValueError
            if not isinstance(
                model._meta.pk,
                (
                    models.IntegerField,
                    models.UUIDField,
                    models.CharField,
                    models.TextField,
                ),
            ):
                raise TypeError
            if model._meta.label_lower in seen:
                raise ValueError
            seen.add(model._meta.label_lower)
            adapter = import_string(path)
            if not isinstance(adapter, type) or not all(
                callable(getattr(adapter, method, None))
                for method in ("get_site", "can_view", "get_url")
            ):
                raise ValueError
        except (ValueError, TypeError, LookupError, ImportError, AttributeError):
            errors.append(f"Invalid OBJECT_ADAPTERS entry: {label}")
    return errors


def _adapter(model: type[models.Model]) -> ObjectAdapter:
    config = getattr(settings, "COMMENTAIL", {})
    registry = config.get("default", {}).get("OBJECT_ADAPTERS", {})
    for label, path in registry.items():
        if label.lower() == model._meta.label_lower:
            return cast(ObjectAdapter, import_string(path)())
    raise ObjectAccessError


def object_key(obj: models.Model) -> str:
    """Canonical PK storage for integer, UUID and exact, case-sensitive strings."""
    if obj.pk is None or obj._state.adding:
        raise ObjectAccessError
    key = str(obj._meta.pk.to_python(obj.pk))
    if not key or len(key) > 255:
        raise ObjectAccessError
    return key


def target_for(discussion: Discussion) -> models.Model:
    if discussion.page_id:
        return discussion.page.specific
    try:
        model = discussion.content_type.model_class()
        if model is None:
            raise ObjectAccessError
        _adapter(model)
        try:
            return model._default_manager.get(pk=discussion.object_id)
        except model.DoesNotExist:
            raise ObjectAccessError from None
    except ObjectAccessError:
        raise
    except Exception as exc:  # noqa: BLE001 - project model/adapter boundary
        logger.error("Target resolution failed (%s)", type(exc).__name__)
        raise ObjectAdapterError from None


def checked_site(
    obj: models.Model,
    request: HttpRequest,
    *,
    view: bool = True,
    expected_site: Site | None = None,
) -> Site:
    try:
        if isinstance(obj, Page):
            raise ObjectAccessError
        adapter = _adapter(type(obj))
        site = adapter.get_site(obj, request)
        current = expected_site or Site.find_for_request(request)
        if not isinstance(site, Site) or not site.pk or site._state.adding:
            raise TypeError("Adapter must return a saved Site")
        if current is None or site.pk != current.pk:
            raise ObjectAccessError
        if view:
            allowed = adapter.can_view(obj, request)
            if type(allowed) is not bool:
                raise TypeError("Adapter must return a bool")
            if not allowed:
                raise ObjectAccessError
        return current
    except ObjectAccessError:
        raise
    except Exception as exc:  # noqa: BLE001 - project model/adapter boundary
        logger.error("Object access handler failed (%s)", type(exc).__name__)
        raise ObjectAdapterError from None


@transaction.atomic
def get_object_discussion(request: HttpRequest, obj: models.Model) -> Discussion:
    key = object_key(obj)
    # Resolve the stored object, never accept stale caller visibility/site fields.
    try:
        _adapter(type(obj))
        obj = type(obj)._default_manager.select_for_update().get(pk=obj.pk)
    except Exception as exc:  # noqa: BLE001 - project model/adapter boundary
        if not isinstance(exc, ObjectAccessError):
            logger.error("Object lookup failed (%s)", type(exc).__name__)
        raise ObjectAdapterError from None
    site = checked_site(obj, request)
    content_type = ContentType.objects.get_for_model(obj)
    discussion, _ = Discussion.objects.get_or_create(
        site=site, content_type=content_type, object_id=key
    )
    return discussion


def target_url(discussion: Discussion) -> str:
    """Host target URL for mail; reject executable and network-relative URLs."""
    try:
        obj = target_for(discussion)
        url = (
            (obj.get_url(current_site=discussion.site) or "/")
            if isinstance(obj, Page)
            else _adapter(type(obj)).get_url(obj, discussion.site)
        )
        if (
            not isinstance(url, str)
            or not url
            or any(ord(c) < 32 for c in url)
            or "\\" in url
        ):
            raise ObjectAccessError
        parts = urlsplit(url)
        if not (url.startswith("/") and not url.startswith("//")) and not (
            parts.scheme in {"http", "https"} and parts.netloc
        ):
            raise ObjectAccessError
        return url
    except ObjectAccessError:
        raise
    except Exception as exc:  # noqa: BLE001 - project model/adapter boundary
        logger.error("Object URL handler failed (%s)", type(exc).__name__)
        raise ObjectAdapterError from None


def discussion_url(discussion: Discussion, *, submit: bool = False) -> str:
    if discussion.page_id:
        return reverse(
            "commentail:submit" if submit else "commentail:discussion",
            args=[discussion.page_id],
        )
    return reverse(
        "commentail:object_submit" if submit else "commentail:object_discussion",
        args=[discussion.pk],
    )


def clear_object_discussions(
    sender: type[models.Model], instance: models.Model, using: str, **kwargs: object
) -> None:
    """ORM deletion cascades stored targets even after adapter deregistration."""
    if sender._meta.apps is not apps:
        return  # Historical migration models can precede the discussion table.
    if sender._meta.app_label in {"commentail", "contenttypes"} or issubclass(
        sender, Page
    ):
        return
    # Serialize cleanup with discussion creation on databases with row locks.
    sender._base_manager.using(using).select_for_update().filter(pk=instance.pk).first()
    Discussion.objects.using(using).filter(
        content_type__app_label=sender._meta.app_label,
        content_type__model=sender._meta.model_name,
        object_id=str(instance.pk),
    ).delete()
