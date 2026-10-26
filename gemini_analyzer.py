"""PDF text extractor and Gemini 2.5 Flash analyzer for textbook categorization.
"""

import os
import re
from typing import List, Optional
from pydantic import BaseModel, Field
from pypdf import PdfReader
from google import genai
from google.genai import types


class BookAnalysis(BaseModel):
    """Structured response schema for Gemini book analysis."""
    kategorie: str = Field(
        description="Thematische Fachkategorie (z. B. Mathematik, Physik, Biologie, Chemie, Jura, Geschichte, Informatik, etc.)"
    )
    autor: str = Field(
        description="Autor(en) des Fachbuchs oder 'Unbekannt'"
    )
    titel: str = Field(
        description="Prägnanter Buchtitel"
    )
    neuer_dateiname: str = Field(
        description="Bereinigter Dateiname im Format: '[Autor] - [Titel].pdf' ohne ungültige Zeichen"
    )


def sanitize_filename(filename: str) -> str:
    """Removes or replaces characters forbidden on Windows/NTFS file systems."""
    # Replace forbidden chars: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/*?:"<>|]', "-", filename)
    # Remove control chars and excessive whitespace
    cleaned = re.sub(r'[\r\n\t]+', " ", cleaned)
    cleaned = re.sub(r'\s+', " ", cleaned).strip()
    # Remove trailing dots or spaces which are invalid in Windows
    cleaned = cleaned.rstrip(". ")
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    if cleaned == ".pdf" or len(cleaned) < 5:
        cleaned = "Unbenanntes_Fachbuch.pdf"
    return cleaned


def sanitize_folder_name(folder_name: str) -> str:
    """Cleans folder names of forbidden filesystem characters."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "-", folder_name)
    cleaned = re.sub(r'[\r\n\t]+', " ", cleaned)
    cleaned = re.sub(r'\s+', " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Sonstiges"


def extract_pdf_preview_text(file_path: str, max_pages: int = 3) -> str:
    """Extracts text from the first few pages (title, imprint, table of contents) of a PDF."""
    extracted_text_chunks: List[str] = []
    try:
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        pages_to_read = min(max_pages, total_pages)

        for page_idx in range(pages_to_read):
            try:
                page = reader.pages[page_idx]
                page_text = page.extract_text()
                if page_text:
                    extracted_text_chunks.append(f"--- Seite {page_idx + 1} ---\n{page_text.strip()}")
            except Exception:
                continue

        # Also attempt to grab metadata if text extraction was sparse
        if not extracted_text_chunks or len(" ".join(extracted_text_chunks)) < 150:
            if reader.metadata:
                meta_info = []
                if reader.metadata.title:
                    meta_info.append(f"PDF Meta-Titel: {reader.metadata.title}")
                if reader.metadata.author:
                    meta_info.append(f"PDF Meta-Autor: {reader.metadata.author}")
                if reader.metadata.subject:
                    meta_info.append(f"PDF Meta-Thema: {reader.metadata.subject}")
                if meta_info:
                    extracted_text_chunks.insert(0, "\n".join(meta_info))

    except Exception as e:
        return f"Fehler beim Lesen der PDF-Seiten: {str(e)}"

    combined_text = "\n\n".join(extracted_text_chunks)
    # Truncate text to avoid token limits on extremely dense OCR outputs (first ~12000 chars are more than sufficient)
    return combined_text[:12000] if combined_text else "Kein lesbarer Text auf den ersten Seiten gefunden."


def analyze_book_with_gemini(
    api_key: str,
    original_filename: str,
    pdf_text: str,
    existing_folders: Optional[List[str]] = None,
) -> BookAnalysis:
    """Sends extracted PDF text to Gemini 2.5 Flash and returns structured BookAnalysis."""
    if not api_key or not api_key.strip():
        raise ValueError("Kein Gemini API-Key angegeben.")

    client = genai.Client(api_key=api_key.strip())

    existing_folders_str = ""
    if existing_folders and len(existing_folders) > 0:
        cleaned_folders = [f.strip() for f in existing_folders if f.strip()]
        if cleaned_folders:
            existing_folders_str = (
                f"\nBEVORZUGTE KATEGORIEN / BEREITS EXISTIERENDE ORDNER IM ZIELVERZEICHNIS:\n"
                f"{', '.join(cleaned_folders)}\n"
                f"WICHTIG: Wenn das Buch thematisch zu einem dieser vorhandenen Ordner passt, "
                f"ordne es bitte bevorzugt genau diesem Ordner zu!\n"
            )

    system_instruction = (
        "Du bist ein intelligenter Bibliothekar und Dateiorganisator für wissenschaftliche Fachbücher.\n"
        "Deine Aufgabe ist es, anhand des Auszugs der ersten Seiten (Titelblatt, Impressum, Inhaltsverzeichnis) "
        "und des ursprünglichen Dateinamens das Buch präzise zu kategorisieren, Autor und Titel zu ermitteln "
        "und einen standardisierten, sauberen Dateinamen zu generieren.\n\n"
        "STRIKTE REGELN:\n"
        "1. 'kategorie': Ein prägnantes, aussagekräftiges Hauptfachgebiet auf Deutsch (z. B. Mathematik, Physik, "
        "Informatik, Medizin, Jura, Wirtschaftswissenschaften, Psychologie, Maschinenbau, Chemie, Philosophie, etc.).\n"
        "2. 'autor': Nachname oder 'Vorname Nachname' des Autors. Bei mehreren Autoren z. B. 'Müller et al.' oder 'Müller & Schmidt'. "
        "Falls nicht ermittelbar, trage 'Unbekannt' ein.\n"
        "3. 'titel': Der Haupttitel des Werks ohne Untertitel-Überlänge.\n"
        "4. 'neuer_dateiname': Format '[Autor] - [Titel].pdf'.\n"
        "5. DATEISYSTEM-SCHUTZ: Ungültige Dateinamenzeichen (\\ / : * ? \" < > |) MÜSSEN zwingend durch Bindestriche oder Leerzeichen "
        "ersetzt werden. Der Dateiname darf keine Windows-verbotenen Sonderzeichen enthalten!"
        f"{existing_folders_str}"
    )

    user_prompt = (
        f"Ursprünglicher Dateiname: {original_filename}\n\n"
        f"Auszug aus den ersten Seiten des PDFs:\n"
        f"'''\n{pdf_text}\n'''\n\n"
        "Bitte analysiere das Buch und gib das Ergebnis strukturiert im vorgegebenen JSON-Format zurück."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=BookAnalysis,
        temperature=0.2,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_prompt,
        config=config,
    )

    # In google-genai SDK with response_schema, response.parsed contains the Pydantic instance directly
    if hasattr(response, "parsed") and response.parsed is not None:
        analysis: BookAnalysis = response.parsed
    else:
        # Fallback parsing
        analysis = BookAnalysis.model_validate_json(response.text)

    # Post-process sanitation in Python to guarantee 100% OS safety
    cleaned_name = sanitize_filename(analysis.neuer_dateiname)
    cleaned_kat = sanitize_folder_name(analysis.kategorie)

    return BookAnalysis(
        kategorie=cleaned_kat,
        autor=analysis.autor.strip() or "Unbekannt",
        titel=analysis.titel.strip() or "Unbenannt",
        neuer_dateiname=cleaned_name,
    )
