"""
catalog_detector.py — Auto-detects catalog fields from data.

When a column has few repeated values (e.g., "Activo", "Pendiente", "Anulado"),
it suggests creating a List field with those values as options.

Heuristic-only (no AI call needed). Fast and deterministic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.document_intelligence.extractors.base import ExtractedDocument

logger = logging.getLogger(__name__)

# Max unique values for a column to be considered a catalog
MAX_CATALOG_UNIQUE_VALUES = 15
# Min unique values to avoid suggesting catalogs for single-value columns
MIN_CATALOG_UNIQUE_VALUES = 2
# Min ratio of repeated values (e.g., if 80% of values repeat, it's a catalog)
MIN_REPEAT_RATIO = 0.6
# Max length of each option value (avoid long text as catalog options)
MAX_OPTION_LENGTH = 50


@dataclass
class CatalogSuggestion:
    """A catalog suggestion for a detected column."""
    column_name: str = ""
    options: list[str] = field(default_factory=list)
    total_rows: int = 0
    unique_count: int = 0
    repeat_ratio: float = 0.0
    confidence: float = 0.0


class CatalogDetector:
    """
    Detects columns that should be List (catalog) fields.

    Heuristic: if a column has few (2-15) unique values and
    those values repeat across rows, it's a catalog.

    Usage:
        detector = CatalogDetector()
        suggestions = detector.detect(extracted_doc)
        for s in suggestions:
            print(f"{s.column_name} → {s.options}")
    """

    def detect(
        self,
        extracted_doc: ExtractedDocument,
        column_index: Optional[int] = None,
    ) -> list[CatalogSuggestion]:
        """
        Detect catalog columns in an extracted document.

        Args:
            extracted_doc: Extracted document with columns and rows.
            column_index: Optional specific column index to analyze.

        Returns:
            List of CatalogSuggestion for columns that look like catalogs.
        """
        if not extracted_doc.columns or not extracted_doc.rows:
            return []

        results: list[CatalogSuggestion] = []

        columns_to_check = (
            [column_index] if column_index is not None
            else range(len(extracted_doc.columns))
        )

        for idx in columns_to_check:
            if idx >= len(extracted_doc.columns):
                continue

            col_name = extracted_doc.columns[idx]

            # Extract all values for this column
            values = []
            for row in extracted_doc.rows:
                if idx < len(row):
                    val = row[idx].strip()
                    if val:
                        values.append(val)

            if len(values) < MIN_CATALOG_UNIQUE_VALUES:
                continue

            # Count unique values
            unique_values = list(dict.fromkeys(values))  # Preserve order
            unique_count = len(unique_values)

            # Skip if too many unique values
            if unique_count > MAX_CATALOG_UNIQUE_VALUES:
                continue

            # Calculate repeat ratio: 1 - (unique / total)
            repeat_ratio = 1 - (unique_count / len(values))

            # Must have at least MIN_REPEAT_RATIO repetition
            if repeat_ratio < MIN_REPEAT_RATIO:
                continue

            # Filter options (clean values, limit length)
            options = []
            for v in unique_values:
                cleaned = v.strip()
                if cleaned and len(cleaned) <= MAX_OPTION_LENGTH:
                    options.append(cleaned)

            if len(options) < MIN_CATALOG_UNIQUE_VALUES:
                continue

            # Confidence based on repeat ratio and uniqueness
            confidence = min(
                0.5 + (repeat_ratio * 0.3) + ((1 - unique_count / MAX_CATALOG_UNIQUE_VALUES) * 0.2),
                0.98,
            )

            results.append(CatalogSuggestion(
                column_name=col_name,
                options=options,
                total_rows=len(values),
                unique_count=unique_count,
                repeat_ratio=repeat_ratio,
                confidence=confidence,
            ))

        return results

    def suggest_renames(
        self,
        extracted_doc: ExtractedDocument,
        column_name: str,
    ) -> Optional[CatalogSuggestion]:
        """Convenience: get catalog suggestion for a single column."""
        if column_name not in extracted_doc.columns:
            return None
        idx = extracted_doc.columns.index(column_name)
        results = self.detect(extracted_doc, column_index=idx)
        return results[0] if results else None
