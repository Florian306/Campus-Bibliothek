"""Core data models for Buchsortierer AI.
"""

from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, Field


@dataclass
class BookItem:
    """Represents a PDF book to be processed in the application."""
    original_path: str
    original_filename: str
    file_size: int
    status: str = "Wartend"
    status_icon: str = "⏳"
    category: str = "-"
    author: str = "-"
    title: str = "-"
    new_filename: str = "-"
    confidence: int = 100
    needs_review: bool = False
    review_reason: Optional[str] = None
    error_message: Optional[str] = None
    applied: bool = False


class BookAnalysis(BaseModel):
    """Structured response schema for book categorization with confidence."""
    kategorie: str = Field(description="Genau eine passende Fachkategorie aus der Liste der Standard-Fachgebiete")
    autor: str = Field(description="Autor(en) des Fachbuchs")
    titel: str = Field(description="Prägnanter Buchtitel")
    neuer_dateiname: str = Field(description="Dateiname im Format: Autor - Titel.pdf")
    confidence: int = Field(default=95, description="Sicherheitswert von 0 bis 100")
    needs_review: bool = Field(default=False, description="Markierung ob manuelle Überprüfung empfohlen ist")
    review_reason: Optional[str] = Field(default=None, description="Begründung für die Überprüfung")
