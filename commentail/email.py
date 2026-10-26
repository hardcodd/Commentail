"""Project-wide mail transport configuration, independent of Django's default.

Validation and guest-form availability never instantiate a backend. Constructor
options belong to the selected backend; only SMTP's known options are checked
here. Credentials and backend exception text must not appear in diagnostics.
"""

import math
from typing import TypedDict

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend
from django.utils.module_loading import import_string


class EmailSettings(TypedDict):
    """Resolved transport, constructor options and sender for this process."""

    BACKEND: str
    OPTIONS: dict[str, object]
    FROM_EMAIL: str


def configuration_errors() -> list[str]:
    """Return redacted configuration errors without constructing a transport."""
    config = getattr(settings, "COMMENTAIL_EMAIL", {})
    if not isinstance(config, dict):
        return ["COMMENTAIL_EMAIL must be a dictionary"]

    errors: list[str] = []
    if config.keys() - {"BACKEND", "OPTIONS", "FROM_EMAIL"}:
        errors.append("COMMENTAIL_EMAIL accepts only BACKEND, OPTIONS and FROM_EMAIL")

    backend_path = config.get("BACKEND")
    backend = None
    if backend_path is not None and (
        not isinstance(backend_path, str) or not backend_path.strip()
    ):
        errors.append("COMMENTAIL_EMAIL BACKEND must be a class import path or None")
    else:
        try:
            backend = import_string(backend_path or settings.EMAIL_BACKEND)
            if not isinstance(backend, type) or not issubclass(
                backend, BaseEmailBackend
            ):
                errors.append("COMMENTAIL_EMAIL backend must extend BaseEmailBackend")
                backend = None
        except (ImportError, AttributeError, ValueError):
            errors.append("COMMENTAIL_EMAIL backend cannot be imported")

    options = config.get("OPTIONS", {})
    if not isinstance(options, dict) or not all(
        isinstance(key, str) for key in options
    ):
        errors.append("COMMENTAIL_EMAIL OPTIONS must be a dictionary with string keys")
    else:
        if {"backend", "fail_silently"} & options.keys():
            errors.append(
                "COMMENTAIL_EMAIL OPTIONS cannot set backend or fail_silently"
            )
        if options and not backend_path:
            errors.append("COMMENTAIL_EMAIL OPTIONS requires an explicit BACKEND")
        if backend is not None and issubclass(backend, EmailBackend):
            errors.extend(_smtp_errors(options))

    sender = config.get("FROM_EMAIL")
    if sender is not None and (
        not isinstance(sender, str)
        or not sender.strip()
        or any(character in sender for character in ("\r", "\n", "\x00"))
    ):
        errors.append(
            "COMMENTAIL_EMAIL FROM_EMAIL must be a nonempty single-line string or None"
        )
    return errors


def _smtp_errors(options: dict[str, object]) -> list[str]:
    """Check standard SMTP options while allowing subclass-specific keywords."""
    errors: list[str] = []
    for key in ("host", "username", "password", "ssl_keyfile", "ssl_certfile"):
        value = options.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"COMMENTAIL_EMAIL SMTP {key} must be a string or None")
    port = options.get("port")
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        errors.append("COMMENTAIL_EMAIL SMTP port must be an integer from 1 to 65535")
    for key in ("use_tls", "use_ssl"):
        if options.get(key) is not None and type(options[key]) is not bool:
            errors.append(f"COMMENTAIL_EMAIL SMTP {key} must be a boolean or None")
    tls = options.get("use_tls")
    ssl = options.get("use_ssl")
    if (settings.EMAIL_USE_TLS if tls is None else tls) and (
        settings.EMAIL_USE_SSL if ssl is None else ssl
    ):
        errors.append(
            "COMMENTAIL_EMAIL SMTP use_tls and use_ssl cannot both be enabled"
        )
    timeout = options.get("timeout")
    if timeout is not None and (
        type(timeout) not in (int, float)
        or (type(timeout) is float and not math.isfinite(timeout))
        or timeout <= 0
    ):
        errors.append(
            "COMMENTAIL_EMAIL SMTP timeout must be finite and positive or None"
        )
    return errors


def email_settings() -> EmailSettings:
    """Resolve current settings; invalid independent configuration never falls back."""
    errors = configuration_errors()
    if errors:
        raise ImproperlyConfigured("; ".join(errors))
    config = getattr(settings, "COMMENTAIL_EMAIL", {})
    return {
        "BACKEND": config.get("BACKEND") or settings.EMAIL_BACKEND,
        "OPTIONS": dict(config.get("OPTIONS", {})),
        "FROM_EMAIL": config.get("FROM_EMAIL") or settings.DEFAULT_FROM_EMAIL,
    }


def email_configured() -> bool:
    """Check form availability without I/O; SMTP requires an explicit host."""
    config = email_settings()
    backend = import_string(config["BACKEND"])
    if issubclass(backend, EmailBackend):
        host = config["OPTIONS"].get("host")
        if isinstance(host, str):
            return bool(host.strip())
        return settings.is_overridden("EMAIL_HOST") and bool(settings.EMAIL_HOST)
    return True


def connection() -> BaseEmailBackend:
    """Construct the current backend with failures enabled for queue retry handling."""
    config = email_settings()
    backend = import_string(config["BACKEND"])
    host = config["OPTIONS"].get("host")
    if issubclass(backend, EmailBackend) and isinstance(host, str) and not host.strip():
        # Django treats an empty host kwarg as inheritance. Here it explicitly
        # disables SMTP, including existing jobs, rather than rerouting mail.
        raise ImproperlyConfigured("COMMENTAIL_EMAIL SMTP host is empty")
    return get_connection(config["BACKEND"], fail_silently=False, **config["OPTIONS"])
