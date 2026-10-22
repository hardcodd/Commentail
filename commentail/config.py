"""Technical settings inherit library defaults, default, then Site.hostname."""

import ipaddress
from typing import Literal, TypedDict

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from wagtail.models import Site

StructuredDataMode = Literal["both", "json_ld", "microdata", "off"]


class TechnicalSettings(TypedDict):
    """Validated technical configuration after library/project/Site inheritance."""

    STRUCTURED_DATA: StructuredDataMode
    OBJECT_ADAPTERS: dict[str, str]
    RULES_CSV_MAX_BYTES: int
    RULES_CSV_MAX_ROWS: int
    FORM_TICKET_SECONDS: int
    EDIT_WINDOW_SECONDS: int
    EMAIL_CONFIRM_SECONDS: int
    GUEST_GRANT_SECONDS: int
    CAPTCHA_SECONDS: int
    CAPTCHA_ATTEMPTS: int
    AUTHOR_MIN_INTERVAL: int
    AUTHOR_LIMIT_PER_HOUR: int
    IP_LIMIT_PER_HOUR: int
    RESEND_MIN_INTERVAL: int
    RESEND_LIMIT_PER_HOUR: int
    RESEND_IP_LIMIT_PER_HOUR: int
    CAPTCHA_IP_LIMIT_PER_MINUTE: int
    CAPTCHA_IP_LIMIT_PER_HOUR: int
    TRUSTED_PROXIES: list[str]
    GUEST_REQUEST_CHECKS: list[str]
    MAIL_RETENTION_SECONDS: int
    MAIL_LEASE_SECONDS: int
    MAIL_RETRY_SECONDS: list[int]
    ACTION_LINK_SECONDS: int
    CAPTCHA_BACKEND: str | None
    CAPTCHA_OPTIONS: dict[str, str | int]
    GUEST_CAPTCHA_MODE: str
    GUEST_FORM_MIN_SECONDS: int
    GUEST_ATTEMPTS_PER_MINUTE: int
    GUEST_IP_ATTEMPTS_PER_MINUTE: int
    GUEST_IP_ATTEMPTS_PER_HOUR: int
    GUEST_DUPLICATE_WINDOW_SECONDS: int
    GUEST_DUPLICATE_MIN_LENGTH: int
    GUEST_LINK_REVIEW_THRESHOLD: int
    GET_AVATAR: str | None
    GET_AUTHOR_NAME: str | None
    GET_COMMENT_TEMPLATES: str | None
    CAN_SEND_GUEST_EMAIL: str | None


DEFAULTS: TechnicalSettings = {
    "STRUCTURED_DATA": "both",
    "OBJECT_ADAPTERS": {},
    "RULES_CSV_MAX_BYTES": 5242880,
    "RULES_CSV_MAX_ROWS": 20000,
    "FORM_TICKET_SECONDS": 3600,
    "EDIT_WINDOW_SECONDS": 900,
    "EMAIL_CONFIRM_SECONDS": 86400,
    "GUEST_GRANT_SECONDS": 2592000,
    "CAPTCHA_SECONDS": 300,
    "CAPTCHA_ATTEMPTS": 5,
    "CAPTCHA_OPTIONS": {},
    "GUEST_CAPTCHA_MODE": "adaptive",
    "GUEST_FORM_MIN_SECONDS": 2,
    "GUEST_ATTEMPTS_PER_MINUTE": 10,
    "GUEST_IP_ATTEMPTS_PER_MINUTE": 30,
    "GUEST_IP_ATTEMPTS_PER_HOUR": 300,
    "GUEST_DUPLICATE_WINDOW_SECONDS": 3600,
    "GUEST_DUPLICATE_MIN_LENGTH": 80,
    "GUEST_LINK_REVIEW_THRESHOLD": 3,
    "AUTHOR_MIN_INTERVAL": 30,
    "AUTHOR_LIMIT_PER_HOUR": 20,
    "IP_LIMIT_PER_HOUR": 100,
    "RESEND_MIN_INTERVAL": 60,
    "RESEND_LIMIT_PER_HOUR": 5,
    "RESEND_IP_LIMIT_PER_HOUR": 20,
    "CAPTCHA_IP_LIMIT_PER_MINUTE": 10,
    "CAPTCHA_IP_LIMIT_PER_HOUR": 100,
    "TRUSTED_PROXIES": [],
    "GUEST_REQUEST_CHECKS": ["missing_user_agent", "cross_site"],
    "MAIL_RETENTION_SECONDS": 604800,
    "MAIL_LEASE_SECONDS": 300,
    "MAIL_RETRY_SECONDS": [60, 300, 900],
    "ACTION_LINK_SECONDS": 2592000,
    "CAN_SEND_GUEST_EMAIL": None,
    "GET_COMMENT_TEMPLATES": None,
    "GET_AVATAR": None,
    "CAPTCHA_BACKEND": None,
    "GET_AUTHOR_NAME": None,
}


def configuration_errors() -> list[str]:
    """Validate all configured sections without substituting defaults for errors.

    Check key scope, values and importable extension contracts. An empty list
    means the configuration is valid; Django system checks report these errors.
    """
    config = getattr(settings, "COMMENTAIL", {})
    if not isinstance(config, dict):
        return ["COMMENTAIL must be a dictionary"]
    errors: list[str] = []
    for hostname, values in config.items():
        if (
            not isinstance(hostname, str)
            or not hostname
            or not isinstance(values, dict)
        ):
            errors.append(
                "COMMENTAIL sections must have string names and dictionary values"
            )
            continue
        for key, value in values.items():
            if key not in DEFAULTS:
                errors.append(f"Unknown COMMENTAIL key: {key}")
            elif key == "STRUCTURED_DATA":
                if not isinstance(value, str) or value not in (
                    "both",
                    "json_ld",
                    "microdata",
                    "off",
                ):
                    errors.append(
                        "STRUCTURED_DATA must be both, json_ld, microdata or off"
                    )
            elif key == "OBJECT_ADAPTERS":
                from .objects import registry_errors

                if hostname != "default":
                    errors.append(
                        "OBJECT_ADAPTERS is project-wide; configure it in default"
                    )
                errors.extend(registry_errors(value))
            elif key.startswith("RULES_CSV_") and hostname != "default":
                errors.append(f"{key} is project-wide; configure it in default")
            elif key == "CAPTCHA_BACKEND":
                if value is not None:
                    from django.utils.module_loading import import_string

                    try:
                        backend = (
                            import_string(value) if isinstance(value, str) else None
                        )
                        if (
                            not isinstance(backend, type)
                            or len(value) > 255
                            or not all(
                                callable(getattr(backend, method, None))
                                for method in ("create", "verify")
                            )
                        ):
                            errors.append(
                                "CAPTCHA_BACKEND must be an import path to a class with create and verify methods"
                            )
                    except (ImportError, AttributeError):
                        errors.append("CAPTCHA_BACKEND cannot be imported")
            elif key == "GUEST_CAPTCHA_MODE":
                if value not in ("adaptive", "always"):
                    errors.append("GUEST_CAPTCHA_MODE must be adaptive or always")
            elif key in {
                "GUEST_FORM_MIN_SECONDS",
                "GUEST_DUPLICATE_WINDOW_SECONDS",
                "GUEST_LINK_REVIEW_THRESHOLD",
            }:
                if type(value) is not int or value < 0:
                    errors.append(f"{key} must be a nonnegative integer")
            elif key == "CAPTCHA_OPTIONS":
                valid = isinstance(value, dict)
                if valid:
                    for name, item in value.items():
                        if name == "timeout":
                            valid = type(item) is int and 1 <= item <= 10
                        else:
                            valid = (
                                name in {"site_key", "secret_key"}
                                and isinstance(item, str)
                                and bool(item.strip())
                            )
                        if not valid:
                            break
                if not valid:
                    errors.append(
                        "CAPTCHA_OPTIONS accepts nonempty site_key/secret_key strings and timeout from 1 to 10 seconds"
                    )
            elif key in {
                "CAN_SEND_GUEST_EMAIL",
                "GET_COMMENT_TEMPLATES",
                "GET_AVATAR",
                "GET_AUTHOR_NAME",
            }:
                if value is not None:
                    from django.utils.module_loading import import_string

                    try:
                        if not isinstance(value, str) or not callable(
                            import_string(value)
                        ):
                            errors.append(f"{key} must be an import path to a callable")
                    except (ImportError, AttributeError):
                        errors.append(f"{key} cannot be imported")
            elif key == "GUEST_REQUEST_CHECKS":
                if (
                    not isinstance(value, list)
                    or not all(
                        isinstance(item, str)
                        and item in {"missing_user_agent", "cross_site"}
                        for item in value
                    )
                    or len(value) != len(set(value))
                ):
                    errors.append(
                        "GUEST_REQUEST_CHECKS must contain unique known signal names: missing_user_agent, cross_site"
                    )
            elif key == "MAIL_RETRY_SECONDS":
                if not isinstance(value, list) or not all(
                    type(item) is int and item > 0 for item in value
                ):
                    errors.append(
                        "MAIL_RETRY_SECONDS must contain positive integer delays"
                    )
            elif key == "TRUSTED_PROXIES":
                if not isinstance(value, list) or not all(
                    isinstance(item, str) for item in value
                ):
                    errors.append("TRUSTED_PROXIES must be a list of network strings")
                else:
                    for item in value:
                        try:
                            ipaddress.ip_network(item)
                        except ValueError:
                            errors.append("Invalid TRUSTED_PROXIES network")
            elif type(value) is not int or value <= 0:
                errors.append(f"{key} must be a positive integer")
    if errors:
        return errors
    for hostname in {"default", *config}:
        section = {
            **DEFAULTS,
            **config.get("default", {}),
            **(config.get(hostname, {}) if hostname != "default" else {}),
        }
        if section.get("CAPTCHA_BACKEND") in {
            "commentail.captcha_providers.GoogleRecaptcha",
            "commentail.captcha_providers.YandexSmartCaptcha",
        }:
            options = section.get("CAPTCHA_OPTIONS")
            if not isinstance(options, dict) or not all(
                options.get(key) for key in ("site_key", "secret_key")
            ):
                errors.append(
                    "Built-in external CAPTCHA requires site_key and secret_key"
                )
    return errors


def technical_settings(site: Site | None) -> TechnicalSettings:
    """Merge library, project and hostname settings after validating every section.

    Without a Site, apply only library and project defaults. Raise
    ImproperlyConfigured on invalid configuration, including other hostnames.
    """
    errors = configuration_errors()
    if errors:
        raise ImproperlyConfigured("; ".join(errors))
    config = getattr(settings, "COMMENTAIL", {})
    return {
        **DEFAULTS,
        **config.get("default", {}),
        **(config.get(site.hostname, {}) if site else {}),
    }
