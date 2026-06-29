from __future__ import annotations

import json
import logging
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.platform.ai.models import Conversation, ConversationMessage, ConversationSummary

logger = logging.getLogger(__name__)

# Configurable threshold for auto-summarization
SUMMARY_THRESHOLD = 30
RECENT_MESSAGES_FOR_CONTEXT = 10


class ConversationManager:
    """
    Manages persistent conversation threads.

    Handles CRUD, message persistence, context building, search,
    auto-summarization, and metadata collection for SmartLearner integration.
    """

    # ──────────────────────────────────────────────
    # Conversation CRUD
    # ──────────────────────────────────────────────

    @staticmethod
    def create_conversation(
        user: Any,
        title: str = "",
    ) -> Conversation:
        """
        Create a new conversation for the given user.
        """
        conv = Conversation.objects.create(
            user=user,
            title=title or f"Conversacion {timezone.now():%Y-%m-%d %H:%M}",
            last_message_at=timezone.now(),
        )
        logger.debug("Created conversation %d for user %s", conv.id, user)
        return conv

    @staticmethod
    def get_conversation(
        conversation_id: int,
        user: Any,
    ) -> Optional[Conversation]:
        """
        Get a conversation by ID, scoped to the given user.
        """
        try:
            return Conversation.objects.get(id=conversation_id, user=user)
        except Conversation.DoesNotExist:
            return None

    @staticmethod
    def list_conversations(
        user: Any,
        include_archived: bool = False,
        limit: int = 50,
    ) -> QuerySet[Conversation]:
        """
        List conversations for a user, newest first.

        Args:
            user: User to list conversations for.
            include_archived: If True, include archived conversations.
            limit: Max number of conversations to return.

        Returns:
            QuerySet of Conversation objects.
        """
        qs = Conversation.objects.filter(user=user)
        if not include_archived:
            qs = qs.filter(archived=False)
        return qs.order_by("-pinned", "-last_message_at")[:limit]

    @staticmethod
    def rename_conversation(
        conversation_id: int,
        user: Any,
        title: str,
    ) -> Optional[Conversation]:
        """
        Rename a conversation.
        """
        conv = ConversationManager.get_conversation(conversation_id, user)
        if conv is None:
            return None
        conv.title = title.strip() or conv.title
        conv.save(update_fields=["title", "updated_at"])
        return conv

    @staticmethod
    def archive_conversation(
        conversation_id: int,
        user: Any,
        archived: bool = True,
    ) -> Optional[Conversation]:
        """
        Archive or unarchive a conversation.
        """
        conv = ConversationManager.get_conversation(conversation_id, user)
        if conv is None:
            return None
        conv.archived = archived
        conv.save(update_fields=["archived", "updated_at"])
        return conv

    @staticmethod
    def pin_conversation(
        conversation_id: int,
        user: Any,
        pinned: bool = True,
    ) -> Optional[Conversation]:
        """
        Pin or unpin a conversation.
        """
        conv = ConversationManager.get_conversation(conversation_id, user)
        if conv is None:
            return None
        conv.pinned = pinned
        conv.save(update_fields=["pinned", "updated_at"])
        return conv

    @staticmethod
    def delete_conversation(
        conversation_id: int,
        user: Any,
    ) -> bool:
        """
        Delete a conversation and all its messages.
        """
        conv = ConversationManager.get_conversation(conversation_id, user)
        if conv is None:
            return False
        conv.delete()
        return True

    # ──────────────────────────────────────────────
    # Message CRUD
    # ──────────────────────────────────────────────

    @staticmethod
    def add_message(
        conversation: Conversation,
        role: str,
        content: str,
        *,
        intent: str = "",
        provider: str = "",
        source: str = "",
        confidence: float = 0.0,
        execution_time: float = 0.0,
        token_count: int = 0,
        tool_name: str = "",
        tool_success: bool = True,
        tool_dry_run: bool = False,
        tool_confirmation: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        """
        Add a message to a conversation and update conversation metadata.

        Args:
            conversation: Conversation to add the message to.
            role: 'user', 'assistant', 'system', or 'tool'.
            content: Message text content.
            intent: Detected intent (for assistant/tool messages).
            provider: Provider slug (gemini, deepseek, tool, data_agent).
            source: Source type (ai, tool, data_agent, heuristic).
            confidence: Confidence score (0.0 to 1.0).
            execution_time: Execution time in milliseconds.
            token_count: Token count (for assistant messages).
            tool_name: Tool name (only for role='tool').
            tool_success: Whether the tool execution succeeded.
            tool_dry_run: Whether this was a dry run.
            tool_confirmation: Whether confirmation was required.
            metadata: Additional JSON metadata.

        Returns:
            The created ConversationMessage.
        """
        msg = ConversationMessage.objects.create(
            conversation=conversation,
            role=role,
            content=content,
            intent=intent,
            provider=provider,
            source=source,
            confidence=confidence,
            execution_time=execution_time,
            token_count=token_count,
            tool_name=tool_name,
            tool_success=tool_success,
            tool_dry_run=tool_dry_run,
            tool_confirmation=tool_confirmation,
            metadata_json=json.dumps(metadata or {}),
        )

        # Update conversation metadata
        conversation.last_message_at = timezone.now()
        conversation.message_count = ConversationMessage.objects.filter(
            conversation=conversation
        ).count()
        # Auto-generate title from first user message
        if conversation.message_count == 1 and role == "user":
            conversation.title = content[:80]
        conversation.save(update_fields=["last_message_at", "message_count", "title", "updated_at"])

        # Auto-summarize if threshold exceeded
        if conversation.message_count >= SUMMARY_THRESHOLD and (
            conversation.message_count % SUMMARY_THRESHOLD == 0
        ):
            ConversationManager._try_generate_summary(conversation)

        return msg

    @staticmethod
    def get_messages(
        conversation: Conversation,
        limit: int | None = None,
    ) -> list[ConversationMessage]:
        """
        Get messages for a conversation, oldest first.
        """
        qs = ConversationMessage.objects.filter(
            conversation=conversation
        ).order_by("created_at")
        if limit:
            qs = qs[:limit]
        return list(qs)

    @staticmethod
    def get_recent_messages(
        conversation: Conversation,
        count: int = RECENT_MESSAGES_FOR_CONTEXT,
    ) -> list[ConversationMessage]:
        """
        Get the most recent N messages (for context building).
        """
        return list(
            ConversationMessage.objects.filter(
                conversation=conversation
            ).order_by("-created_at")[:count]
        )

    # ──────────────────────────────────────────────
    # Context Building (replaces session history)
    # ──────────────────────────────────────────────

    @staticmethod
    def build_context(
        conversation: Conversation,
        system_context: str = "",
        max_recent: int = RECENT_MESSAGES_FOR_CONTEXT,
    ) -> str:
        """
        Build a prompt context string from a conversation.

        Structure:
          System Context (if provided)
          Conversation Summary (if exists)
          Recent Messages (last N)
          Current User Question

        Args:
            conversation: Conversation to build context from.
            system_context: System-level context string.
            max_recent: Max number of recent messages to include.

        Returns:
            Formatted context string.
        """
        parts = []

        # System context
        if system_context:
            parts.append(f"[CONTEXTO DEL SISTEMA]\n{system_context}")

        # Conversation summary
        latest_summary = ConversationSummary.objects.filter(
            conversation=conversation
        ).order_by("-generated_at").first()
        if latest_summary:
            parts.append(
                f"[RESUMEN DE LA CONVERSACION]\n{latest_summary.summary}\n"
                f"(Basado en los primeros {latest_summary.message_count} mensajes)"
            )

        # Recent messages
        recent = ConversationManager.get_recent_messages(conversation, max_recent)
        if recent:
            msg_lines = []
            for msg in recent:
                role_label = {
                    "user": "Usuario",
                    "assistant": "Asistente",
                    "tool": "Herramienta",
                    "system": "Sistema",
                }.get(msg.role, msg.role)
                msg_lines.append(f"{role_label}: {msg.content[:500]}")
            parts.append(
                f"[MENSAJES RECIENTES ({len(recent)} ultimos)]\n" + "\n".join(reversed(msg_lines))
            )

        return "\n\n---\n\n".join(parts)

    # ──────────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────────

    @staticmethod
    def search_conversations(
        user: Any,
        query: str = "",
        *,
        date_from: str = "",
        date_to: str = "",
        intent: str = "",
        limit: int = 20,
    ) -> QuerySet[Conversation]:
        """
        Search conversations by title, message content, date, or intent.

        Args:
            user: User to search conversations for.
            query: Free-text search in title and message content.
            date_from: Filter conversations from this date (YYYY-MM-DD).
            date_to: Filter conversations until this date (YYYY-MM-DD).
            intent: Filter by message intent type.
            limit: Max results.

        Returns:
            QuerySet of matching conversations.
        """
        qs = Conversation.objects.filter(user=user)

        # Full-text search in title
        if query:
            qs = qs.filter(
                Q(title__icontains=query)
                | Q(messages__content__icontains=query)
            ).distinct()

        # Date range
        if date_from:
            qs = qs.filter(last_message_at__gte=date_from)
        if date_to:
            qs = qs.filter(last_message_at__lte=date_to)

        # Intent filter
        if intent:
            qs = qs.filter(messages__intent=intent).distinct()

        return qs.order_by("-last_message_at")[:limit]

    # ──────────────────────────────────────────────
    # Summarization
    # ──────────────────────────────────────────────

    @staticmethod
    def should_summarize(conversation: Conversation) -> bool:
        """
        Check if a conversation needs summarization.

        Returns True if the conversation has more than SUMMARY_THRESHOLD messages
        and has not been summarized for the current threshold.
        """
        return (
            conversation.message_count >= SUMMARY_THRESHOLD
            and conversation.message_count % SUMMARY_THRESHOLD == 0
        )

    @staticmethod
    def _try_generate_summary(conversation: Conversation) -> None:
        """
        Generate a summary for a conversation.

        This is a heuristic summary builder that concatenates key messages.
        In future phases, this could use an AI provider for better summaries.
        """
        try:
            # Get first N messages (before the most recent threshold)
            all_msgs = ConversationManager.get_messages(conversation)
            summary_msgs = all_msgs[:conversation.message_count - RECENT_MESSAGES_FOR_CONTEXT]

            if not summary_msgs:
                return

            # Build a simple heuristic summary
            user_msgs = [m for m in summary_msgs if m.role == "user"]
            tool_msgs = [m for m in summary_msgs if m.role == "tool"]
            assistant_msgs = [m for m in summary_msgs if m.role == "assistant"]

            lines = [
                f"La conversacion cubrio {len(user_msgs)} interacciones del usuario.",
                f"El asistente respondio {len(assistant_msgs)} veces.",
            ]
            if tool_msgs:
                tools_used = set(m.tool_name for m in tool_msgs if m.tool_name)
                if tools_used:
                    lines.append(f"Herramientas utilizadas: {', '.join(sorted(tools_used))}.")

            # Include user topics
            topics = set()
            for m in user_msgs[:5]:
                content = m.content[:100].strip()
                if content:
                    topics.add(content[:60])
            if topics:
                lines.append("Temas principales:")
                for t in list(topics)[:3]:
                    lines.append(f"  - {t}...")

            summary_text = "\n".join(lines)

            ConversationSummary.objects.create(
                conversation=conversation,
                summary=summary_text,
                message_count=conversation.message_count,
            )
            conversation.summary = summary_text
            conversation.save(update_fields=["summary"])

            logger.debug(
                "Generated summary for conversation %d (%d messages)",
                conversation.id, conversation.message_count,
            )
        except Exception as e:
            logger.warning("Failed to generate summary: %s", e)

    # ──────────────────────────────────────────────
    # SmartLearner metadata collection
    # ──────────────────────────────────────────────

    @staticmethod
    def collect_metadata(
        conversation: Conversation,
    ) -> dict[str, Any]:
        """
        Collect conversation metadata for SmartLearner integration.

        Returns a dict with:
          - message_count, user_message_count, assistant_message_count
          - tool_message_count, top_provider, top_source
          - average_confidence, average_execution_time
          - unique_intents, unique_tools
          - has_summary, conversation_age_hours
          - repeated_questions, abandoned (no user msg in 7+ days)
        """
        msgs = ConversationManager.get_messages(conversation)
        if not msgs:
            return {}

        user_msgs = [m for m in msgs if m.role == "user"]
        assistant_msgs = [m for m in msgs if m.role == "assistant"]
        tool_msgs = [m for m in msgs if m.role == "tool"]

        # Average metrics
        confidences = [m.confidence for m in assistant_msgs if m.confidence > 0]
        times = [m.execution_time for m in assistant_msgs if m.execution_time > 0]

        # Intents and tools
        intents = set(m.intent for m in msgs if m.intent)
        tools = set(m.tool_name for m in tool_msgs if m.tool_name)

        # Provider stats
        providers = {}
        for m in assistant_msgs:
            if m.provider:
                providers[m.provider] = providers.get(m.provider, 0) + 1
        top_provider = max(providers, key=providers.get) if providers else ""

        # Sources
        sources = {}
        for m in msgs:
            if m.source:
                sources[m.source] = sources.get(m.source, 0) + 1
        top_source = max(sources, key=sources.get) if sources else ""

        # Repeated questions
        user_contents = [m.content.lower().strip() for m in user_msgs]
        repeated = len(user_contents) - len(set(user_contents))

        # Abandoned
        now = timezone.now()
        days_since_last = (now - conversation.last_message_at).days if conversation.last_message_at else 0

        return {
            "message_count": len(msgs),
            "user_message_count": len(user_msgs),
            "assistant_message_count": len(assistant_msgs),
            "tool_message_count": len(tool_msgs),
            "top_provider": top_provider,
            "top_source": top_source,
            "average_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
            "average_execution_time_ms": round(sum(times) / len(times), 1) if times else 0.0,
            "unique_intents": sorted(intents),
            "unique_tools": sorted(tools),
            "has_summary": conversation.summary != "",
            "conversation_age_hours": round((now - conversation.created_at).total_seconds() / 3600, 1),
            "repeated_questions": repeated,
            "abandoned": days_since_last > 7,
        }
