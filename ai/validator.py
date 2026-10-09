"""Filesystem sanitization, plausibility matrix, and integration with the academic classifier.
"""

import re
from typing import List, Optional, Tuple
from ai.classifier import classify_textbook, cross_validate_with_classifier


def sanitize_filename(filename: str) -> str:
    """Removes forbidden Windows characters, square brackets and trailing dots."""
    cleaned = filename.replace("[", "").replace("]", "")
    cleaned = re.sub(r'[\\/*?:"<>|]', "-", cleaned)
    cleaned = re.sub(r'[\r\n\t]+', " ", cleaned)
    cleaned = re.sub(r'\s+', " ", cleaned).strip()
    cleaned = cleaned.rstrip(". -")

    cleaned = re.sub(r'(\.pdf)+$', '', cleaned, flags=re.IGNORECASE)
    cleaned = f"{cleaned}.pdf"

    if cleaned.lower() == ".pdf" or len(cleaned) < 5:
        cleaned = "Unbenanntes_Fachbuch.pdf"
    return cleaned


def sanitize_folder_name(folder_name: str) -> str:
    """Cleans folder names of forbidden filesystem characters."""
    cleaned = folder_name.replace("[", "").replace("]", "")
    cleaned = re.sub(r'[\\/*?:"<>|]', "-", cleaned)
    cleaned = re.sub(r'[\r\n\t]+', " ", cleaned)
    cleaned = re.sub(r'\s+', " ", cleaned).strip()
    cleaned = cleaned.rstrip(". -")
    return cleaned or "Sonstiges"


def detect_heuristic_category(filename: str, text: str, existing_folders: Optional[List[str]] = None) -> Optional[str]:
    """Analyzes filename and text using the high-precision academic faculty engine."""
    best_faculty, conf, _ = classify_textbook(filename, text, existing_folders)
    return best_faculty if best_faculty != "Sonstiges" else None


def cross_validate_and_score(
    original_filename: str,
    pdf_text: str,
    raw_category: str,
    author: str,
    title: str,
    existing_folders: Optional[List[str]] = None,
) -> Tuple[str, int, bool, Optional[str]]:
    """Cross-validation plausibility matrix using the academic classifier."""
    return cross_validate_with_classifier(
        original_filename=original_filename,
        pdf_text=pdf_text,
        raw_category=raw_category,
        author=author,
        title=title,
        existing_folders=existing_folders,
    )
