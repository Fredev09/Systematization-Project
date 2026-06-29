"""
form_similarity_finder.py — Finds similar forms before creating new ones.

Avoids duplicating forms by comparing proposed field sets against
existing forms. Uses column name overlap and type matching.

Reuses DynamicService to query existing forms and Campo model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.dynamic_forms.models import Campo, Formulario
from apps.platform.dynamic_forms.column_matching import normalizar_columna

logger = logging.getLogger(__name__)

# Min similarity ratio to consider a form as "similar"
# 0.6 = 60% field overlap is genuinely similar; lower values give false positives
MIN_SIMILARITY_THRESHOLD = 0.6


@dataclass
class SimilarForm:
    """A form found to be similar to the proposed one."""
    id: int
    nombre: str
    similitud: float  # 0.0 to 1.0
    campos_coincidentes: int = 0
    campos_nuevos: int = 0
    total_campos: int = 0
    campos_propuestos: list[str] = field(default_factory=list)


class FormSimilarityFinder:
    """
    Finds existing forms similar to a proposed field set.

    Pipeline:
      1. Normalize proposed field names
      2. Compare against all existing form field names
      3. Calculate overlap ratio
      4. Return ranked list of similar forms

    Usage:
        finder = FormSimilarityFinder()
        similar = finder.find_similar(["Nombre", "Precio", "Stock"])
        if similar:
            print(f"Found {similar[0].nombre} with {similar[0].similitud:.0%} similarity")
    """

    def find_similar(
        self,
        proposed_fields: list[dict[str, Any]],
        exclude_form_id: Optional[int] = None,
        threshold: float = MIN_SIMILARITY_THRESHOLD,
    ) -> list[SimilarForm]:
        """
        Find existing forms similar to the proposed field set.

        Args:
            proposed_fields: List of field dicts with at least 'name' key.
            exclude_form_id: Optional form ID to exclude from search.
            threshold: Minimum similarity ratio (0.0-1.0).

        Returns:
            List of SimilarForm sorted by similarity (highest first).
        """
        if not proposed_fields:
            return []

        # Normalize proposed field names
        proposed_names = self._normalize_names([f.get("name", "") for f in proposed_fields])
        proposed_set = set(proposed_names)

        if not proposed_set:
            return []

        results: list[SimilarForm] = []

        # Get all active forms (excluding the one being edited)
        forms = Formulario.objects.filter(activo=True)
        if exclude_form_id:
            forms = forms.exclude(id=exclude_form_id)

        for form in forms:
            # Get active fields for this form
            form_fields = form.campos.filter(activo=True).values_list("nombre", flat=True)
            form_names = self._normalize_names(list(form_fields))
            form_set = set(form_names)

            if not form_set:
                continue

            # Jaccard similarity: intersection / union
            intersection = proposed_set & form_set
            union = proposed_set | form_set

            similarity = len(intersection) / len(union) if union else 0.0

            if similarity >= threshold:
                results.append(SimilarForm(
                    id=form.id,
                    nombre=form.nombre,
                    similitud=round(similarity * 100, 1),
                    campos_coincidentes=len(intersection),
                    campos_nuevos=len(proposed_set - form_set),
                    total_campos=len(form_set),
                    campos_propuestos=list(proposed_set - form_set),
                ))

        # Sort by similarity (highest first)
        results.sort(key=lambda x: x.similitud, reverse=True)

        return results[:5]  # Max 5 results

    @staticmethod
    def _normalize_names(names: list[str]) -> list[str]:
        """Normalize field names using the same algorithm as column_matching."""
        normalized = []
        for name in names:
            if not name:
                continue
            n = normalizar_columna(name)
            normalized.append(n)
        return normalized
