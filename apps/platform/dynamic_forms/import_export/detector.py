"""Data detector — identifies patterns in imported data."""

from __future__ import annotations

import re
from typing import Any


class DataDetector:
    """Detects data patterns, types, and anomalies in imported rows."""

    PATTERN_TYPES: dict[str, re.Pattern] = {
        'email': re.compile(r'^[\w.+-]+@[\w-]+\.[\w.]+$'),
        'telefono': re.compile(r'^[\d\s\-\+\(\)]{7,20}$'),
        'url': re.compile(r'^https?://'),
        'entero': re.compile(r'^-?\d+$'),
        'decimal': re.compile(r'^-?\d+\.\d+$'),
        'moneda': re.compile(r'^\$?\s*-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?$'),
        'fecha_iso': re.compile(r'^\d{4}-\d{2}-\d{2}$'),
        'fecha_slash': re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4}$'),
        'fecha_dmy': re.compile(r'^\d{1,2}-\d{1,2}-\d{4}$'),
        'booleano': re.compile(r'^(sí|si|no|true|false|1|0|yes|on|off)$', re.I),
    }

    def infer_type(self, value: str) -> str:
        if not value or not value.strip():
            return 'vacio'
        v = value.strip()
        for type_name, pattern in self.PATTERN_TYPES.items():
            if pattern.match(v):
                return type_name
        return 'texto'

    def detect_duplicates(self, rows: list[list[Any]], key_col: int = 0) -> list[dict]:
        seen: dict[str, list[int]] = {}
        duplicates: list[dict] = []
        for i, row in enumerate(rows):
            if key_col < len(row):
                val = str(row[key_col]).strip().lower()
                if val in seen:
                    duplicates.append({
                        'fila': i + 1,
                        'valor': row[key_col],
                        'primera_aparicion': seen[val][0] + 1,
                    })
                else:
                    seen[val] = [i]
        return duplicates

    def detect_empty_rows(self, rows: list[list[Any]], min_filled: int = 1) -> list[int]:
        empty: list[int] = []
        for i, row in enumerate(rows):
            filled = sum(1 for c in row if c and str(c).strip())
            if filled < min_filled:
                empty.append(i + 1)
        return empty

    def detect_outliers(self, values: list[str], threshold: float = 3.0) -> list[dict]:
        nums = []
        for v in values:
            try:
                nums.append(float(v.replace('$', '').replace(',', '').strip()))
            except (ValueError, AttributeError):
                continue
        if len(nums) < 3:
            return []
        mean = sum(nums) / len(nums)
        variance = sum((x - mean) ** 2 for x in nums) / len(nums)
        std = variance ** 0.5
        if std == 0:
            return []
        outliers = []
        for i, v in enumerate(values):
            try:
                n = float(v.replace('$', '').replace(',', '').strip())
                if abs(n - mean) > threshold * std:
                    outliers.append({'fila': i + 1, 'valor': v, 'zscore': round(abs(n - mean) / std, 2)})
            except (ValueError, AttributeError):
                pass
        return outliers

    def summary(self, rows: list[list[Any]]) -> dict:
        total = len(rows)
        empty = self.detect_empty_rows(rows)
        info = {
            'total_filas': total,
            'filas_vacias': len(empty),
            'indices_vacias': empty[:20],
            'columnas': {},
        }
        if not rows:
            return info
        for col_idx in range(len(rows[0])):
            col_vals = [str(r[col_idx]) if col_idx < len(r) else '' for r in rows]
            non_empty = [v for v in col_vals if v.strip()]
            types = [self.infer_type(v) for v in non_empty]
            type_counts: dict[str, int] = {}
            for t in types:
                type_counts[t] = type_counts.get(t, 0) + 1
            info['columnas'][col_idx] = {
                'no_vacios': len(non_empty),
                'tipos': type_counts,
                'tipo_predominante': max(type_counts, key=type_counts.get) if type_counts else 'vacio',
            }
        return info
