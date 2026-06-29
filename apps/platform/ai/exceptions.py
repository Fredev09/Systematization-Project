"""
exceptions.py — AI module custom exceptions.

Clean Architecture: all provider errors are wrapped into these
before propagating to services or views.
"""

from __future__ import annotations


class AIError(Exception):
    """Base exception for all AI module errors."""
    def __init__(self, message: str, original: Exception | None = None):
        self.original = original
        super().__init__(message)


class ProviderNotAvailable(AIError):
    """The configured provider is not available (no API key, network error)."""
    def __init__(self, provider: str, reason: str = ""):
        msg = f"Provider '{provider}' is not available"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.provider = provider


class ProviderRateLimit(AIError):
    """Rate limit exceeded for the provider."""
    def __init__(self, provider: str, retry_after: int = 0, detail: str = ""):
        msg = f"Rate limit exceeded for '{provider}'."
        if detail:
            msg += f" {detail}"
        if retry_after:
            msg += f" Retry after {retry_after}s."
        super().__init__(msg)
        self.provider = provider
        self.retry_after = retry_after


class ProviderAuthError(AIError):
    """Authentication failed for the provider."""
    def __init__(self, provider: str, detail: str = ""):
        msg = f"Authentication failed for provider '{provider}'."
        if detail:
            msg += f" {detail}"
        else:
            msg += " Check your API key."
        super().__init__(msg)
        self.provider = provider


class InvalidPromptError(AIError):
    """The prompt file or template is invalid or missing."""
    def __init__(self, prompt_name: str, detail: str = ""):
        msg = f"Invalid prompt '{prompt_name}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.prompt_name = prompt_name


class InvalidSchemaError(AIError):
    """The schema file is invalid or missing."""
    def __init__(self, schema_name: str, detail: str = ""):
        msg = f"Invalid schema '{schema_name}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.schema_name = schema_name


class AnalysisError(AIError):
    """The analysis of a document failed."""
    def __init__(self, document: str, reason: str = ""):
        msg = f"Analysis failed for '{document}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.document = document


class UnsupportedDocumentType(AIError):
    """The document type is not supported by the analyzer."""
    def __init__(self, doc_type: str):
        super().__init__(f"Unsupported document type: '{doc_type}'")
        self.doc_type = doc_type


class JSONParseError(AIError):
    """Failed to parse JSON from the AI response."""
    def __init__(self, raw_text: str, detail: str = ""):
        msg = f"Failed to parse JSON from AI response"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.raw_text = raw_text[:500]
