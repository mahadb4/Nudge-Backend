from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Installed only so it can host management commands (the migrate guard). It has no models."""

    name = "common"
    label = "common"
