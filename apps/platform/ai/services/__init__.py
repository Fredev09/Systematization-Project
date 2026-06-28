"""
services — AI-powered analysis services.

All services are provider-agnostic. They receive a BaseAIProvider
instance and use it without knowing which model/provider is behind it.

Available services:
  - PromptManager:      Loads and renders prompt templates from prompts/
  - DocumentAnalyzer:   Analyzes any document type (Excel, CSV, PDF, image, text)
  - FieldDetector:      Detects fields and types from structured/unstructured data
  - InvoiceAnalyzer:    Extracts invoice data from images, PDFs, or text
  - FormGenerator:      Generates complete form proposals from analysis
"""

from __future__ import annotations
