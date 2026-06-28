from __future__ import annotations

from django.apps import AppConfig


class DocumentIntelligenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.document_intelligence"
    label = "document_intelligence"
    verbose_name = "Document Intelligence Platform"
