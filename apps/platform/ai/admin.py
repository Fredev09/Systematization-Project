"""
admin.py — Django admin registration for AI models.
"""

from __future__ import annotations

from django.contrib import admin

from .models import AIAnalysisLog


@admin.register(AIAnalysisLog)
class AIAnalysisLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "provider",
        "model",
        "service",
        "document_type",
        "success",
        "cached",
        "total_tokens",
        "estimated_cost_usd",
        "confidence",
    )
    list_filter = (
        "provider",
        "service",
        "document_type",
        "success",
        "cached",
        "created_at",
    )
    search_fields = (
        "document_name",
        "error_message",
    )
    readonly_fields = (
        "created_at",
        "estimated_cost_usd",
    )
    date_hierarchy = "created_at"

    fieldsets = (
        ("Identificación", {
            "fields": ("provider", "model", "service", "document_type", "document_name"),
        }),
        ("Rendimiento", {
            "fields": (
                "processing_time_ms",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "estimated_cost_usd",
            ),
        }),
        ("Resultado", {
            "fields": ("success", "cached", "error_message", "confidence", "result_summary"),
        }),
    )
