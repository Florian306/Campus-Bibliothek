"""Backward-compatible proxy for core.file_processor and core.models.
"""

from core.models import BookItem
from core.file_processor import (
    scan_directory_for_pdfs,
    get_existing_subdirectories,
    resolve_collision_filename,
    execute_book_relocation,
)

__all__ = [
    "BookItem",
    "scan_directory_for_pdfs",
    "get_existing_subdirectories",
    "resolve_collision_filename",
    "execute_book_relocation",
]
