"""
urls.py — Document Intelligence Platform routes.
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "document_intelligence"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.document_upload, name="document_upload"),
    path("create-from-file/", views.create_from_file, name="create_from_file"),
    path("scan-invoice/", views.scan_invoice, name="scan_invoice"),
    path("history/", views.history, name="history"),
    path("chat/", views.ai_chat, name="ai_chat"),
    path("chat/ask/", views.ai_chat_ask, name="ai_chat_ask"),
    path("chat/stream/", views.ai_chat_stream, name="ai_chat_stream"),
    path("chat/conversations/", views.conversation_list, name="conversation_list"),
    path("chat/conversations/create/", views.conversation_create, name="conversation_create"),
    path("chat/conversations/search/", views.conversation_search, name="conversation_search"),
    path("chat/conversations/<int:conversation_id>/", views.conversation_detail, name="conversation_detail"),
    path("chat/conversations/<int:conversation_id>/rename/", views.conversation_rename, name="conversation_rename"),
    path("chat/conversations/<int:conversation_id>/archive/", views.conversation_archive, name="conversation_archive"),
    path("chat/conversations/<int:conversation_id>/delete/", views.conversation_delete, name="conversation_delete"),
    # Feedback API
    path("chat/feedback/", views.feedback_create, name="feedback_create"),
    path("chat/feedback/<int:feedback_id>/", views.feedback_update, name="feedback_update"),
    path("chat/feedback/<int:feedback_id>/delete/", views.feedback_delete, name="feedback_delete"),
    path("chat/feedback/stats/", views.feedback_stats, name="feedback_stats"),
    # Dashboard API (JSON only)
    path("dashboard/metrics/", views.dashboard_metrics, name="dashboard_metrics"),
    path("dashboard/providers/", views.dashboard_providers, name="dashboard_providers"),
    path("dashboard/tools/", views.dashboard_tools, name="dashboard_tools"),
    path("dashboard/feedback/", views.dashboard_feedback, name="dashboard_feedback"),
    # Plan API
    path("plan/<str:plan_id>/", views.plan_detail, name="plan_detail"),
    path("plan/<str:plan_id>/confirm/", views.plan_confirm_step, name="plan_confirm_step"),
    path("plan/<str:plan_id>/resume/", views.plan_resume, name="plan_resume"),
    path("plan/<str:plan_id>/cancel/", views.plan_cancel, name="plan_cancel"),
    path("plan/<str:plan_id>/retry/", views.plan_retry, name="plan_retry"),
    path("plan/<str:plan_id>/stream/", views.plan_stream, name="plan_stream"),
    path("reports/", views.ai_reports, name="ai_reports"),
    path("settings/", views.ai_settings, name="ai_settings"),
]
