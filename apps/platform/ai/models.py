"""
models.py — History model for AI analysis tracking.

Every AI analysis is logged here for audit, cost tracking, and debugging.
Independent of Dynamic Forms; reusable from any application.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class AIAnalysisLog(models.Model):
    """
    Audit log for every AI analysis performed.

    Tracks:
      - Provider and model used
      - Processing time and token usage
      - Estimated cost
      - Result and errors
      - Cache hit/miss

    This is the single source of truth for AI usage monitoring.
    """

    class Meta:
        verbose_name = "Registro de análisis AI"
        verbose_name_plural = "Registros de análisis AI"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "created_at"]),
            models.Index(fields=["document_type"]),
            models.Index(fields=["success"]),
        ]

    # ── Who / What ──
    provider = models.CharField(
        max_length=50,
        help_text="Provider slug (gemini, openrouter, deepseek, qwen)",
    )
    model = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Model name used",
    )
    service = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Service that triggered the analysis (e.g., field_detector)",
    )
    document_type = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Type of document analyzed (excel, pdf, image, text, invoice)",
    )
    document_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Original file name or identifier",
    )

    # ── Performance ──
    processing_time_ms = models.FloatField(
        default=0.0,
        help_text="Processing time in milliseconds",
    )
    prompt_tokens = models.IntegerField(
        default=0,
        help_text="Input tokens",
    )
    completion_tokens = models.IntegerField(
        default=0,
        help_text="Output tokens",
    )
    total_tokens = models.IntegerField(
        default=0,
        help_text="Total tokens consumed",
    )
    estimated_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0.0,
        help_text="Estimated cost in USD",
    )

    # ── Status ──
    success = models.BooleanField(
        default=True,
        help_text="Whether the analysis succeeded",
    )
    cached = models.BooleanField(
        default=False,
        help_text="Whether the result was served from cache",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error message if analysis failed",
    )
    confidence = models.FloatField(
        default=0.0,
        help_text="Overall confidence score (0.0 to 1.0)",
    )

    # ── Result (truncated) ──
    result_summary = models.TextField(
        blank=True,
        default="",
        help_text="Truncated summary of the analysis result (first 2000 chars)",
    )

    # ── Timestamps ──
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the analysis was performed",
    )

    def __str__(self) -> str:
        return (
            f"[{self.created_at:%Y-%m-%d %H:%M}] "
            f"{self.provider}/{self.model} | "
            f"{self.document_type}:{self.document_name} | "
            f"{'OK' if self.success else 'FAIL'}"
        )

    def save_estimated_cost(self) -> None:
        """
        Estimate cost based on provider pricing.
        This is a rough estimate and should be updated as pricing changes.

        Rates per 1K tokens (approximate):
          - Gemini 2.0 Flash: $0.00015 input / $0.00060 output
          - DeepSeek Chat:    $0.00027 input / $0.00110 output
          - GPT-4o Mini:      $0.00015 input / $0.00060 output
          - Qwen Plus:        $0.00080 input / $0.00200 output
        """
        rates = {
            "gemini":    (0.00015, 0.00060),
            "openrouter": (0.00015, 0.00060),  # conservative for GPT-4o-mini
            "deepseek":  (0.00027, 0.00110),
            "qwen":      (0.00080, 0.00200),
        }
        input_rate, output_rate = rates.get(self.provider, (0.0005, 0.0015))
        cost = (
            (self.prompt_tokens / 1000) * input_rate
            + (self.completion_tokens / 1000) * output_rate
        )
        self.estimated_cost_usd = round(cost, 6)

    @classmethod
    def log(
        cls,
        provider: str,
        model: str = "",
        service: str = "",
        document_type: str = "",
        document_name: str = "",
        processing_time_ms: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        success: bool = True,
        cached: bool = False,
        error_message: str = "",
        confidence: float = 0.0,
        result_summary: str = "",
    ) -> "AIAnalysisLog":
        """
        Create a new analysis log entry with automatic cost estimation.
        """
        entry = cls(
            provider=provider,
            model=model,
            service=service,
            document_type=document_type,
            document_name=document_name,
            processing_time_ms=processing_time_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            success=success,
            cached=cached,
            error_message=error_message[:2000],
            confidence=confidence,
            result_summary=result_summary[:2000],
        )
        entry.save_estimated_cost()
        entry.save(using="default")
        return entry

    @classmethod
    def get_stats(cls, days: int = 30) -> dict:
        """
        Get aggregate statistics for the last N days.
        """
        since = timezone.now() - timedelta(days=days)
        queryset = cls.objects.filter(created_at__gte=since)

        total = queryset.count()
        successful = queryset.filter(success=True).count()
        cached_count = queryset.filter(cached=True).count()

        token_data = queryset.aggregate(
            total_prompt=models.Sum("prompt_tokens"),
            total_completion=models.Sum("completion_tokens"),
            total_cost=models.Sum("estimated_cost_usd"),
        )

        return {
            "period_days": days,
            "total_calls": total,
            "successful": successful,
            "failed": total - successful,
            "cached": cached_count,
            "avg_time_ms": queryset.aggregate(
                avg=models.Avg("processing_time_ms")
            )["avg__processing_time_ms"] or 0.0,
            "total_prompt_tokens": token_data["total_prompt"] or 0,
            "total_completion_tokens": token_data["total_completion"] or 0,
            "estimated_cost_usd": float(token_data["total_cost"] or 0.0),
            "by_provider": dict(
                queryset.values_list("provider")
                .annotate(count=models.Count("id"))
            ),
        }


class Conversation(models.Model):
    """
    Persistent conversation thread for the AI chat assistant.

    Each conversation belongs to a single user and contains
    multiple messages. Supports archiving, pinning, and auto-summarization.
    """

    class Meta:
        verbose_name = "Conversacion"
        verbose_name_plural = "Conversaciones"
        ordering = ["-last_message_at", "-updated_at"]
        indexes = [
            models.Index(fields=["user", "-last_message_at"]),
            models.Index(fields=["user", "archived"]),
            models.Index(fields=["user", "pinned"]),
        ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Auto-generated or user-provided conversation title",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp of the last message",
    )
    archived = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)
    summary = models.TextField(
        blank=True, default="",
        help_text="Latest auto-generated summary of the conversation",
    )
    metadata_json = models.TextField(
        blank=True, default="{}",
        help_text="JSON metadata for extensibility",
    )
    message_count = models.IntegerField(default=0)

    def __str__(self) -> str:
        return self.title or f"Conversacion #{self.id}"


class ConversationMessage(models.Model):
    """
    Individual message within a conversation.

    Supports user, assistant, system, and tool roles with
    full metadata for source tracking and performance monitoring.
    """

    class Meta:
        verbose_name = "Mensaje de conversacion"
        verbose_name_plural = "Mensajes de conversacion"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["role"]),
        ]

    ROLES = [
        ("user", "Usuario"),
        ("assistant", "Asistente"),
        ("system", "Sistema"),
        ("tool", "Herramienta"),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(
        max_length=20,
        choices=ROLES,
        help_text="Quien envio el mensaje",
    )
    content = models.TextField(
        blank=True, default="",
        help_text="Contenido del mensaje",
    )

    # AI metadata (only for assistant/tool messages)
    intent = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Tipo de intent detectado",
    )
    provider = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Provider slug (gemini, deepseek, tool, data_agent)",
    )
    source = models.CharField(
        max_length=30, blank=True, default="",
        help_text="Source: ai, tool, data_agent, heuristic",
    )
    confidence = models.FloatField(default=0.0)
    execution_time = models.FloatField(
        default=0.0,
        help_text="Execution time in milliseconds",
    )
    token_count = models.IntegerField(default=0)

    # Tool metadata (only for tool messages)
    tool_name = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Nombre de la herramienta (solo role=tool)",
    )
    tool_success = models.BooleanField(default=True)
    tool_dry_run = models.BooleanField(default=False)
    tool_confirmation = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Cuando se envio el mensaje",
    )

    metadata_json = models.TextField(
        blank=True, default="{}",
        help_text="JSON metadata adicional",
    )

    def __str__(self) -> str:
        return f"[{self.created_at:%H:%M}] {self.role}: {self.content[:60]}"


class ConversationSummary(models.Model):
    """
    Auto-generated summary of a conversation at a point in time.

    New summaries are generated when a conversation exceeds
    the configurable message threshold (default: 30).
    """

    class Meta:
        verbose_name = "Resumen de conversacion"
        verbose_name_plural = "Resumenes de conversacion"
        ordering = ["-generated_at"]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="summaries",
    )
    summary = models.TextField(
        help_text="Resumen generado automaticamente",
    )
    message_count = models.IntegerField(
        default=0,
        help_text="Numero de mensajes al generar el resumen",
    )
    generated_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Cuando se genero el resumen",
    )
    metadata_json = models.TextField(
        blank=True, default="{}",
    )

    def __str__(self) -> str:
        return f"Resumen #{self.id} ({self.message_count} msg, {self.generated_at:%Y-%m-%d})"


class ConversationFeedback(models.Model):
    """
    User feedback on individual assistant messages.

    Each assistant response can receive optional thumbs-up or thumbs-down
    feedback with a reason. This drives SmartLearner improvements and
    dashboard analytics.
    """

    class Meta:
        verbose_name = "Retroalimentacion"
        verbose_name_plural = "Retroalimentaciones"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["message", "user"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["rating"]),
        ]

    REASONS = [
        ("", "Sin motivo"),
        ("incorrect", "Informacion incorrecta"),
        ("incomplete", "Respuesta incompleta"),
        ("slow", "Demasiado lento"),
        ("hallucination", "Alucinacion"),
        ("bad_format", "Formato incorrecto"),
        ("unhelpful", "No fue util"),
        ("other", "Otro"),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="feedbacks",
    )
    message = models.ForeignKey(
        ConversationMessage,
        on_delete=models.CASCADE,
        related_name="feedbacks",
        help_text="The assistant message being rated",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_feedbacks",
    )
    rating = models.SmallIntegerField(
        choices=[(1, "👍 Util"), (-1, "👎 No util")],
        help_text="+1 for thumbs up, -1 for thumbs down",
    )
    reason = models.CharField(
        max_length=50,
        blank=True,
        default="",
        choices=REASONS,
        help_text="Reason for negative feedback",
    )
    comment = models.TextField(
        blank=True,
        default="",
        help_text="Optional free-text comment",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When feedback was submitted",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last modification time",
    )

    def __str__(self) -> str:
        return (
            f"[{'👍' if self.rating > 0 else '👎'}] "
            f"Msg #{self.message_id} ({self.get_reason_display()})"
        )

    @classmethod
    def get_stats(cls, user=None, days: int = 30) -> dict:
        """
        Get aggregate feedback statistics.

        Args:
            user: Optional user filter.
            days: Lookback period in days.

        Returns:
            Dict with totals, score, breakdown, and per-provider stats.
        """
        from datetime import timedelta
        from django.db.models import Count, Avg, Q
        from django.utils import timezone

        since = timezone.now() - timedelta(days=days)
        qs = cls.objects.filter(created_at__gte=since)
        if user:
            qs = qs.filter(user=user)

        total = qs.count()
        thumbs_up = qs.filter(rating=1).count()
        thumbs_down = qs.filter(rating=-1).count()

        return {
            "period_days": days,
            "total": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "score": round((thumbs_up / total * 100) if total else 0.0, 1),
            "reason_breakdown": dict(
                qs.filter(rating=-1)
                .values_list("reason")
                .annotate(count=Count("id"))
            ),
            "by_provider": [
                {
                    "provider": item["message__provider"],
                    "avg_rating": round(float(item["avg_rating"] or 0.0), 2),
                    "count": item["count"],
                }
                for item in qs.values("message__provider")
                .annotate(
                    avg_rating=Avg("rating"),
                    count=Count("id"),
                )
                .filter(message__provider__gt="")
            ],
        }
