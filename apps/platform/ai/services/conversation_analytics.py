"""
conversation_analytics.py — Aggregated conversation metrics for learning & dashboard.

Tracks:
  - Repeated questions (same user, same conversation)
  - Conversation abandonment (no message in 7+ days)
  - Follow-up frequency (assistant msgs between user msgs)
  - Clarification requests (user questions referring to prior answers)
  - Average conversation length (messages per conversation)
  - Tool usage frequency (which tools used how often)
  - Provider effectiveness (per-intent success rates)

All metrics are aggregated from ConversationMessage and ConversationFeedback models.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from django.db.models import Avg, Count, Q
from django.utils import timezone

from apps.platform.ai.models import Conversation, ConversationFeedback, ConversationMessage

logger = logging.getLogger(__name__)


class ConversationAnalytics:
    """
    Aggregated conversation metrics for learning & dashboard.

    All methods are static. No state is maintained between calls.
    """

    # ── Repeated Questions ──

    @staticmethod
    def get_repeated_questions(
        user=None,
        days: int = 30,
        threshold: int = 2,
    ) -> list[dict[str, Any]]:
        """
        Find questions the user has asked repeatedly.

        Args:
            user: Optional user filter.
            days: Lookback period.
            threshold: Minimum repetitions to flag (default 2).

        Returns:
            List of {question, count, last_asked, conversation_ids}.
        """
        from django.utils import timezone
        since = timezone.now() - timedelta(days=days)
        qs = ConversationMessage.objects.filter(
            role="user", created_at__gte=since,
        )
        if user:
            qs = qs.filter(conversation__user=user)

        counter: dict[str, list[int]] = {}
        for msg in qs.values("content", "conversation_id", "created_at"):
            content = msg["content"].strip().lower()[:200]
            if not content:
                continue
            if content not in counter:
                counter[content] = []
            counter[content].append({
                "conversation_id": msg["conversation_id"],
                "asked_at": msg["created_at"].isoformat() if msg["created_at"] else "",
            })

        result = []
        for question, occurrences in counter.items():
            if len(occurrences) >= threshold:
                result.append({
                    "question": question[:200],
                    "count": len(occurrences),
                    "last_asked": occurrences[-1]["asked_at"],
                    "conversation_ids": list(set(
                        o["conversation_id"] for o in occurrences
                    )),
                })

        result.sort(key=lambda r: r["count"], reverse=True)
        return result[:50]

    # ── Conversation Abandonment ──

    @staticmethod
    def get_abandoned_conversations(
        user=None,
        days_no_reply: int = 7,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Find conversations where the user stopped replying.

        Args:
            user: Optional user filter.
            days_no_reply: Minimum days since last message to consider abandoned.
            limit: Max results.

        Returns:
            List of conversation summaries with abandonment details.
        """
        since = timezone.now() - timedelta(days=days_no_reply)
        qs = Conversation.objects.filter(last_message_at__lte=since)
        if user:
            qs = qs.filter(user=user)

        results = []
        for conv in qs.order_by("-last_message_at")[:limit]:
            last_user_msg = ConversationMessage.objects.filter(
                conversation=conv, role="user",
            ).order_by("-created_at").first()
            last_assistant_msg = ConversationMessage.objects.filter(
                conversation=conv, role="assistant",
            ).order_by("-created_at").first()

            results.append({
                "id": conv.id,
                "title": conv.title,
                "message_count": conv.message_count,
                "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else "",
                "days_abandoned": (timezone.now() - conv.last_message_at).days if conv.last_message_at else 0,
                "last_user_question": last_user_msg.content[:200] if last_user_msg else "",
                "got_response": last_assistant_msg is not None and (
                    last_assistant_msg.created_at > (last_user_msg.created_at if last_user_msg else timezone.min)
                ),
            })

        return results

    # ── Follow-up Frequency ──

    @staticmethod
    def get_follow_up_stats(
        user=None,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Analyze follow-up patterns in conversations.

        Returns:
            Dict with avg_follow_ups, distribution, clarification_rate.
        """
        since = timezone.now() - timedelta(days=days)
        conversations = Conversation.objects.filter(last_message_at__gte=since)
        if user:
            conversations = conversations.filter(user=user)

        follow_up_counts = []
        total_clarifications = 0
        total_exchanges = 0

        for conv in conversations:
            msgs = list(ConversationMessage.objects.filter(
                conversation=conv, role__in=("user", "assistant"),
            ).order_by("created_at").values_list("role", "content"))

            # Count user turns (each user message after an assistant message is a follow-up)
            user_turns = 0
            for i in range(1, len(msgs)):
                if msgs[i][0] == "user" and msgs[i - 1][0] == "assistant":
                    user_turns += 1
                    total_exchanges += 1
                    # Detect clarification: short follow-up or question about prior answer
                    prev_content = msgs[i - 1][1].lower()[:50]
                    curr_content = msgs[i][1].lower()[:100]
                    if any(word in curr_content for word in [
                        "explica", "por que", "como", "detalle", "mas", "otro",
                        "quiero saber", "puedes", "ejemplo", "clarifica",
                    ]):
                        total_clarifications += 1

            follow_up_counts.append(user_turns)

        if not follow_up_counts:
            return {"avg_follow_ups": 0.0, "clarification_rate": 0.0, "total_conversations": 0}

        return {
            "avg_follow_ups": round(sum(follow_up_counts) / len(follow_up_counts), 2),
            "max_follow_ups": max(follow_up_counts),
            "total_conversations": len(follow_up_counts),
            "clarification_rate": round(
                (total_clarifications / max(total_exchanges, 1)) * 100, 1
            ),
            "total_clarifications": total_clarifications,
        }

    # ── Average Conversation Length ──

    @staticmethod
    def get_conversation_length_stats(
        user=None,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Get statistics about conversation lengths.

        Returns:
            Dict with avg_length, median, max, distribution.
        """
        since = timezone.now() - timedelta(days=days)
        qs = Conversation.objects.filter(last_message_at__gte=since)
        if user:
            qs = qs.filter(user=user)

        lengths = list(qs.values_list("message_count", flat=True))
        if not lengths:
            return {"avg": 0, "median": 0, "max": 0, "total": 0}

        sorted_lengths = sorted(lengths)
        n = len(sorted_lengths)

        return {
            "avg": round(sum(lengths) / n, 1),
            "median": sorted_lengths[n // 2],
            "max": max(lengths),
            "total": n,
            "distribution": {
                "1-3": sum(1 for l in lengths if 1 <= l <= 3),
                "4-10": sum(1 for l in lengths if 4 <= l <= 10),
                "11-30": sum(1 for l in lengths if 11 <= l <= 30),
                "31+": sum(1 for l in lengths if l > 30),
            },
        }

    # ── Provider Effectiveness ──

    @staticmethod
    def get_provider_effectiveness(
        user=None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Get per-provider effectiveness stats based on feedback.

        Returns:
            List of {provider, total, thumbs_up, thumbs_down, score, avg_latency, intents}.
        """
        from django.db.models import Avg, Count, Q

        since = timezone.now() - timedelta(days=days)
        feedback_qs = ConversationFeedback.objects.filter(
            created_at__gte=since,
            message__provider__gt="",
        )
        if user:
            feedback_qs = feedback_qs.filter(user=user)

        stats = (
            feedback_qs
            .values("message__provider")
            .annotate(
                total=Count("id"),
                thumbs_up=Count("id", filter=Q(rating=1)),
                thumbs_down=Count("id", filter=Q(rating=-1)),
                avg_rating=Avg("rating"),
            )
            .order_by("-total")
        )

        return [
            {
                "provider": s["message__provider"],
                "total": s["total"],
                "thumbs_up": s["thumbs_up"],
                "thumbs_down": s["thumbs_down"],
                "score": round(
                    (s["thumbs_up"] / max(s["total"], 1)) * 100, 1
                ),
                "avg_rating": round(float(s["avg_rating"] or 0.0), 2),
            }
            for s in stats
        ]

    # ── Tool Usage Frequency ──

    @staticmethod
    def get_tool_usage_stats(
        user=None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Get tool usage frequency stats.

        Returns:
            List of {tool_name, count, success_rate, avg_execution_time, intents}.
        """
        since = timezone.now() - timedelta(days=days)
        qs = ConversationMessage.objects.filter(
            role="tool", created_at__gte=since,
        )
        if user:
            qs = qs.filter(conversation__user=user)

        stats = (
            qs.values("tool_name", "intent")
            .annotate(
                count=Count("id"),
                success_count=Count("id", filter=Q(tool_success=True)),
                avg_time=Avg("execution_time"),
            )
            .order_by("-count")
        )

        # Aggregate by tool
        tool_agg: dict[str, dict] = {}
        for s in stats:
            tool = s["tool_name"] or "unknown"
            if tool not in tool_agg:
                tool_agg[tool] = {
                    "tool_name": tool,
                    "count": 0,
                    "success_count": 0,
                    "total_time": 0.0,
                    "intents": set(),
                }
            tool_agg[tool]["count"] += s["count"]
            tool_agg[tool]["success_count"] += s["success_count"]
            tool_agg[tool]["total_time"] += (s["avg_time"] or 0.0) * s["count"]
            if s["intent"]:
                tool_agg[tool]["intents"].add(s["intent"])

        return [
            {
                "tool_name": v["tool_name"],
                "count": v["count"],
                "success_rate": round(
                    (v["success_count"] / max(v["count"], 1)) * 100, 1
                ),
                "avg_execution_time_ms": round(
                    v["total_time"] / max(v["count"], 1), 1
                ),
                "intents": sorted(v["intents"]),
            }
            for v in sorted(
                tool_agg.values(),
                key=lambda x: x["count"],
                reverse=True,
            )
        ]

    # ── Overall Dashboard Metrics ──

    @staticmethod
    def get_overall_metrics(
        user=None,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Get overall conversation and learning metrics.

        This is the main entry point for the dashboard API.
        """
        from apps.platform.ai.models import ConversationFeedback, ConversationMessage

        since = timezone.now() - timedelta(days=days)

        # Base message stats
        msg_qs = ConversationMessage.objects.filter(created_at__gte=since)
        if user:
            msg_qs = msg_qs.filter(conversation__user=user)

        total_messages = msg_qs.count()
        total_assistant = msg_qs.filter(role="assistant").count()
        total_user = msg_qs.filter(role="user").count()
        total_tool = msg_qs.filter(role="tool").count()
        total_conversations = Conversation.objects.filter(
            last_message_at__gte=since,
        ).count()

        # Average latencies
        latency_stats = msg_qs.filter(
            role="assistant", execution_time__gt=0,
        ).aggregate(
            avg_latency=Avg("execution_time"),
        )
        avg_latency = latency_stats.get("avg_latency") or 0.0

        # Heuristic hit rate
        heuristic_count = msg_qs.filter(source="heuristic").count()
        orm_count = msg_qs.filter(source="data_agent").count()
        ai_count = msg_qs.filter(source="ai").count()
        tool_msg_count = msg_qs.filter(source="tool").count()
        total_answered = heuristic_count + orm_count + ai_count + tool_msg_count or 1

        # Feedback summary
        feedback_qs = ConversationFeedback.objects.filter(created_at__gte=since)
        if user:
            feedback_qs = feedback_qs.filter(user=user)
        feedback_total = feedback_qs.count()
        feedback_up = feedback_qs.filter(rating=1).count()
        feedback_down = feedback_qs.filter(rating=-1).count()

        # Repeated questions
        repeated = ConversationAnalytics.get_repeated_questions(
            user=user, days=days,
        )

        # Abandoned
        abandoned = ConversationAnalytics.get_abandoned_conversations(
            user=user,
        )

        # Provider effectiveness
        provider_effectiveness = ConversationAnalytics.get_provider_effectiveness(
            user=user, days=days,
        )

        # Tool usage
        tool_usage = ConversationAnalytics.get_tool_usage_stats(
            user=user, days=days,
        )

        return {
            "period_days": days,
            "messages": {
                "total": total_messages,
                "user": total_user,
                "assistant": total_assistant,
                "tool": total_tool,
            },
            "conversations": {
                "total": total_conversations,
                "avg_length": round(total_messages / max(total_conversations, 1), 1),
            },
            "latency": {
                "avg_assistant_ms": round(float(avg_latency), 1),
            },
            "routing": {
                "heuristic_rate": round((heuristic_count / total_answered) * 100, 1),
                "data_agent_rate": round((orm_count / total_answered) * 100, 1),
                "ai_rate": round((ai_count / total_answered) * 100, 1),
                "tool_rate": round((tool_msg_count / total_answered) * 100, 1),
            },
            "feedback": {
                "total": feedback_total,
                "thumbs_up": feedback_up,
                "thumbs_down": feedback_down,
                "score": round((feedback_up / max(feedback_total, 1)) * 100, 1),
            },
            "repeated_questions": repeated[:10],
            "abandoned_conversations": len(abandoned),
            "provider_effectiveness": provider_effectiveness[:10],
            "tool_usage": tool_usage,
        }
