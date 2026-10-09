"""AI package for book categorization, PDF text extraction, and model integration.
"""

from ai.categories import STANDARD_CATEGORIES, KEYWORD_MAP
from ai.pdf_extractor import extract_pdf_preview_text
from ai.validator import (
    sanitize_filename,
    sanitize_folder_name,
    detect_heuristic_category,
    cross_validate_and_score,
)
from ai.classifier import classify_textbook, cross_validate_with_classifier
from ai.ollama_client import fetch_ollama_models, analyze_with_ollama
from ai.gemini_client import analyze_with_gemini

__all__ = [
    "STANDARD_CATEGORIES",
    "KEYWORD_MAP",
    "extract_pdf_preview_text",
    "sanitize_filename",
    "sanitize_folder_name",
    "detect_heuristic_category",
    "cross_validate_and_score",
    "classify_textbook",
    "cross_validate_with_classifier",
    "fetch_ollama_models",
    "analyze_with_ollama",
    "analyze_with_gemini",
]
