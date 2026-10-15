from importlib import import_module

from django.apps import AppConfig


class CommentailConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "commentail"

    def ready(self) -> None:
        import_module("commentail.checks")
        import_module("commentail.signals")
        import logging

        from .logging import CapabilityFilter

        logger = logging.getLogger("django.server")
        if not any(isinstance(item, CapabilityFilter) for item in logger.filters):
            logger.addFilter(CapabilityFilter())
