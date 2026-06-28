"""Abstract base parser for all import formats."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParseResult:
    headers: list[str]
    rows: list[list[Any]]
    sheet_name: str = ''
    header_row: int = 0
    data_start_row: int = 1
    total_sheets: int = 1
    filename: str = ''
    errors: list[str] = field(default_factory=list)


class BaseParser(ABC):

    def __init__(self, filepath: str, filename: str = ''):
        self.filepath = filepath
        self.filename = filename or filepath.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]

    @abstractmethod
    def parse(self, sheet_name: str | None = None, header_row: int | None = None) -> ParseResult:
        ...

    @abstractmethod
    def detect_structure(self) -> dict:
        ...
