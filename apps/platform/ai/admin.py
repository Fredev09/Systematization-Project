"""
admin.py — Django admin registration for AI models.
"""

from __future__ import annotations

from django.contrib import admin

from .models import AIAnalysisLog, Conversation, ConversationMessage, ConversationSummary, ConversationFeedback


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


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "message_count", "pinned", "archived", "last_message_at")
    list_filter = ("pinned", "archived", "created_at")
    search_fields = ("title", "user__username")
    readonly_fields = ("created_at", "updated_at", "last_message_at")
    date_hierarchy = "last_message_at"


@admin.register(ConversationMessage)
class ConversationMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation_id", "role", "created_at", "source", "provider", "content_preview")
    list_filter = ("role", "source", "provider", "created_at")
    search_fields = ("content",)
    readonly_fields = ("created_at",)

    @admin.display(description="Contenido")
    def content_preview(self, obj):
        return obj.content[:80]


@admin.register(ConversationSummary)
class ConversationSummaryAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "message_count", "generated_at")
    readonly_fields = ("generated_at",)


@admin.register(ConversationFeedback)
class ConversationFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "rating_icon", "conversation_id", "user", "reason", "created_at")
    list_filter = ("rating", "reason", "created_at")
    search_fields = ("message__content", "comment")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Valoracion")
    def rating_icon(self, obj):
        return "👍" if obj.rating > 0 else "👎"
