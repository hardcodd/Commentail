from django.core.checks import Error, register

from .config import configuration_errors


@register()
def check_settings(app_configs: object, **kwargs: object) -> list[Error]:
    return [Error(message, id="commentail.E001") for message in configuration_errors()]
