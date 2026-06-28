"""Conflict detection for column mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConflictResult:
    has_conflicts: bool = False
    conflicts: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)


class ConflictDetector:
    """Detects column mapping conflicts and ambiguities."""

    def detect(
        self,
        headers: list[str],
        field_names: list[str],
        match_results: list[dict] | None = None,
    ) -> ConflictResult:
        result = ConflictResult()

        if not headers:
            return result

        header_lower = [h.strip().lower() for h in headers]
        field_lower = [f.strip().lower() for f in field_names]

        duplicates_in_excel: dict[str, list[int]] = {}
        for i, h in enumerate(header_lower):
            if h:
                duplicates_in_excel.setdefault(h, []).append(i)
        for h, indices in duplicates_in_excel.items():
            if len(indices) > 1:
                result.conflicts.append({
                    'type': 'duplicate_column',
                    'header': headers[indices[0]],
                    'columns': [i + 1 for i in indices],
                    'message': f'Columna duplicada: "{headers[indices[0]]}" aparece {len(indices)} veces',
                })
                result.warnings.append(f'Se ignorarán las columnas duplicadas de "{headers[indices[0]]}"')

        field_matches: dict[str, list[int]] = {}
        for i, h in enumerate(header_lower):
            if not h:
                continue
            if h in field_lower:
                fi = field_lower.index(h)
                field_matches.setdefault(field_names[fi], []).append(i)
        for field_name, cols in field_matches.items():
            if len(cols) > 1:
                result.conflicts.append({
                    'type': 'multiple_columns_to_field',
                    'field': field_name,
                    'columns': cols,
                    'message': f'Varias columnas del Excel apuntan al campo "{field_name}"',
                })

        if match_results:
            unmatched = [m for m in match_results if m.get('method') == 'none']
            if unmatched:
                col_names = [m.get('column') for m in unmatched[:5]]
                result.suggestions.append({
                    'type': 'unmatched_columns',
                    'columns': col_names,
                    'message': f'{len(unmatched)} columnas sin mapear: {", ".join(col_names[:5])}',
                })

        result.has_conflicts = bool(result.conflicts)
        return result
