"""Backward-compatible proxy for ai package and core.models.
"""

from core.models import BookAnalysis
from ai.categories import STANDARD_CATEGORIES, KEYWORD_MAP
from ai.validator import (
    sanitize_filename,
    sanitize_folder_name,
    detect_heuristic_category,
    cross_validate_and_score,
)
from ai.pdf_extractor import extract_pdf_preview_text
from ai.ollama_client import fetch_ollama_models, analyze_with_ollama
from ai.gemini_client import analyze_with_gemini

__all__ = [
    "BookAnalysis",
    "STANDARD_CATEGORIES",
    "KEYWORD_MAP",
    "sanitize_filename",
    "sanitize_folder_name",
    "detect_heuristic_category",
    "cross_validate_and_score",
    "extract_pdf_preview_text",
    "fetch_ollama_models",
    "analyze_with_ollama",
    "analyze_with_gemini",
]
