"""
apps.py — Django AppConfig for apps.platform.ai.
"""

from __future__ import annotations

from django.apps import AppConfig


class AIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.ai"
    label = "ai"
    verbose_name = "AI Infrastructure"

    def ready(self) -> None:
        """App startup hook. Import signals here if needed."""
        pass
