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
    path("reports/", views.ai_reports, name="ai_reports"),
    path("settings/", views.ai_settings, name="ai_settings"),
]
