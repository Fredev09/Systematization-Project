"""
text_extractor.py — Plain text, JSON, and XML document extractor.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from apps.platform.document_intelligence.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractedTable,
)

logger = logging.getLogger(__name__)

MAX_TEXT_SIZE = 10 * 1024 * 1024  # 10 MB


class TextExtractor(DocumentExtractor):
    """Extracts content from text files (txt, json, xml, md)."""

    def extract(self, file_path: str | Path) -> ExtractedDocument:
        path = Path(file_path)
        ext = path.suffix.lower()

        try:
            raw = path.read_bytes()
            # Try UTF-8 first, fall back to latin-1
            try:
                text = raw.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
                encoding = "latin-1"
        except Exception as e:
            raise ValueError(f"Cannot read file: {e}")

        doc = ExtractedDocument(
            document_type=ext.lstrip(".") if ext else "text",
            title=path.name,
            raw_text=text,
            confidence=1.0,
        )
        doc.metadata["encoding"] = encoding
        doc.metadata["char_count"] = len(text)
        doc.metadata["line_count"] = text.count("\n") + 1

        # JSON: parse and extract tables
        if ext == ".json":
            try:
                data = json.loads(text)
                if isinstance(data, list) and data:
                    # List of objects → table
                    headers = list(data[0].keys()) if isinstance(data[0], dict) else []
                    rows = [
                        [str(item.get(h, "")) for h in headers]
                        if isinstance(item, dict) else [str(item)]
                        for item in data
                    ]
                    table = ExtractedTable(
                        name="JSON Data",
                        headers=headers,
                        rows=rows,
                        row_count=len(rows),
                    )
                    doc.tables = [table]
                    doc.columns = headers
                    doc.rows = rows
            except json.JSONDecodeError:
                pass

        # XML: simple text extraction
        elif ext in (".xml", ".html", ".htm"):
            # Strip tags for clean text
            clean = re.sub(r"<[^>]+>", " ", text)
            clean = re.sub(r"\s+", " ", clean).strip()
            doc.raw_text = clean[:50000]

        # Text/MD: look for pipe tables
        else:
            lines = text.split("\n")
            pipe_tables = []
            for i, line in enumerate(lines):
                if "|" in line and i + 2 < len(lines):
                    if "---" in lines[i + 1]:
                        # Found a markdown table
                        headers = [h.strip() for h in line.split("|") if h.strip()]
                        table_lines = []
                        for j in range(i + 2, min(i + 200, len(lines))):
                            if "|" not in lines[j]:
                                break
                            parts = [p.strip() for p in lines[j].split("|") if p.strip()]
                            if parts:
                                table_lines.append(parts)
                        if table_lines:
                            pipe_tables.append(ExtractedTable(
                                name="Detected Table",
                                headers=headers,
                                rows=table_lines,
                                row_count=len(table_lines),
                                confidence=0.8,
                            ))
                        break

            if pipe_tables:
                doc.tables = pipe_tables
                doc.columns = pipe_tables[0].headers
                doc.rows = pipe_tables[0].rows

        return doc

    def validate(self, file_path: str | Path) -> None:
        super().validate(file_path)
        size = Path(file_path).stat().st_size
        if size > MAX_TEXT_SIZE:
            raise ValueError(
                f"File too large: {size / 1024 / 1024:.1f} MB "
                f"(max {MAX_TEXT_SIZE / 1024 / 1024:.0f} MB)"
            )

    @classmethod
    def supported_extensions(cls) -> list[str]:
        return [".txt", ".md", ".json", ".xml", ".html", ".htm"]
