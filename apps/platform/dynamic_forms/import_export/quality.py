"""Quality analyzer — assesses file quality and assigns star rating."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QualityReport:
    stars: int
    score: float
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'stars': self.stars,
            'score': round(self.score, 1),
            'issues': len(self.issues),
            'warnings': len(self.warnings),
            'issues_list': self.issues[:10],
            'warnings_list': self.warnings[:10],
        }


class QualityAnalyzer:
    """Evaluates import file quality and assigns 1-5 star rating."""

    PENALTIES: dict[str, float] = {
        'empty_rows': 0.15,
        'duplicate_rows': 0.20,
        'all_empty': 1.0,
        'single_row': 0.10,
        'no_headers': 0.30,
        'header_as_data': 0.15,
        'many_empty_cols': 0.25,
        'type_mismatch': 0.15,
        'encoding_issues': 0.20,
        'excessive_cols': 0.10,
    }

    BONUSES: dict[str, float] = {
        'has_synonyms': 0.05,
        'high_confidence': 0.10,
        'has_structure': 0.05,
        'clean_types': 0.10,
    }

    def analyze(
        self,
        headers: list[str],
        rows: list[list[Any]],
        match_results: list[dict] | None = None,
    ) -> QualityReport:
        score = 1.0
        issues: list[str] = []
        warnings: list[str] = []
        details: dict[str, Any] = {}

        n_rows = len(rows)
        n_cols = len(headers) if headers else 0

        details['rows'] = n_rows
        details['cols'] = n_cols

        if n_rows == 0:
            issues.append('El archivo no contiene filas de datos')
            score -= self.PENALTIES['all_empty']
        elif n_rows == 1:
            warnings.append('El archivo contiene solo 1 fila de datos')
            score -= self.PENALTIES['single_row']

        empty_cols = sum(1 for h in headers if not h.strip()) if headers else 0
        if empty_cols > n_cols * 0.3:
            warnings.append(f'{empty_cols} columnas sin encabezado')
            score -= self.PENALTIES['many_empty_cols']

        if not headers or all(not h.strip() for h in headers):
            issues.append('No se detectaron encabezados')
            score -= self.PENALTIES['no_headers']

        if n_rows > 1 and headers:
            first_data_row = [str(r[0]).strip().lower() if r and len(r) > 0 else '' for r in rows[:3]]
            header_names = [h.strip().lower() for h in headers if h.strip()]
            if first_data_row and header_names and first_data_row[0] == header_names[0].lower():
                warnings.append('La primera fila de datos parece un encabezado repetido')
                score -= self.PENALTIES['header_as_data']

        empty_rows_count = sum(1 for r in rows if all(not str(c).strip() for c in r))
        if empty_rows_count > 0:
            warnings.append(f'{empty_rows_count} filas vacías')
            score -= self.PENALTIES['empty_rows'] * min(empty_rows_count / max(n_rows, 1), 1.0)

        if match_results:
            auto_matches = sum(1 for m in match_results if m.get('method') in ('exact', 'normalized', 'synonym'))
            auto_pct = auto_matches / max(len(match_results), 1)
            details['auto_match_pct'] = round(auto_pct * 100, 1)
            if auto_pct >= 0.8:
                score += self.BONUSES['high_confidence']
            elif auto_pct < 0.3:
                issues.append(f'Solo {auto_pct:.0%} de columnas mapeadas automáticamente')

        stars = max(1, min(5, round(score * 5)))
        details['raw_score'] = round(score, 2)

        return QualityReport(
            stars=stars,
            score=score,
            issues=issues,
            warnings=warnings,
            details=details,
        )
