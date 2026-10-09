"""Client for querying Google Gemini 2.5 Flash via official SDK with structured output and validation.
"""

from typing import List, Optional
from core.models import BookAnalysis
from ai.categories import STANDARD_CATEGORIES
from ai.validator import (
    sanitize_filename,
    sanitize_folder_name,
    cross_validate_and_score,
)


def analyze_with_gemini(
    api_key: str,
    original_filename: str,
    pdf_text: str,
    existing_folders: Optional[List[str]] = None,
) -> BookAnalysis:
    """Queries Gemini 2.5 Flash via official SDK with cross-validation."""
    if not api_key or not api_key.strip():
        raise ValueError("Kein Gemini API-Key angegeben.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key.strip())

    available_cats = list(STANDARD_CATEGORIES)
    if existing_folders:
        for ef in existing_folders:
            clean_ef = ef.strip()
            if clean_ef and clean_ef not in available_cats:
                available_cats.insert(0, clean_ef)

    categories_str = ", ".join(available_cats)

    system_instruction = (
        "Du bist ein hochpräziser akademischer Bibliothekar und Fachbereichs-Analyst.\n"
        "AUFGABE: Bestimme die universitäre Fakultät (den primären Fachbereich), an der dieses Lehrbuch verwendet wird.\n"
        f"GÜLTIGE KATEGORIEN: {categories_str}\n\n"
        "STRIKTE REGELN:\n"
        "1. 'kategorie': Wähle exakt eine der oben genannten Kategorien. WICHTIG: Ignoriere populärwissenschaftliche Metaphern im Titel (z. B. 'für Höhlenmenschen', 'für Dummies', 'im Alltag', 'Abenteuer'). Entscheide rein nach dem wissenschaftlichen Inhalt!\n"
        "2. 'autor': Nachname oder 'Vorname Nachname'. Bei vielen Autoren nutze 'Erstautor et al.'. Falls nicht ermittelbar, 'Unbekannt'.\n"
        "3. 'titel': Der Haupttitel des Werks ohne Untertitel-Überlänge (NIEMALS 'Titelei', 'Cover' oder 'Frontmatter'!).\n"
        "4. 'neuer_dateiname': Format 'Autor - Titel.pdf' ohne eckige Klammern!\n"
        "5. DATEISYSTEM-SCHUTZ: Ungültige Dateinamenzeichen (\\ / : * ? \" < > |) sowie eckige Klammern [ ] MÜSSEN durch Bindestriche oder Leerzeichen ersetzt werden!"
    )

    user_prompt = (
        f"Ursprünglicher Dateiname: {original_filename}\n\n"
        f"Auszug aus Titelblatt und Inhaltsverzeichnis:\n"
        f"'''\n{pdf_text}\n'''\n\n"
        "Bitte analysiere das Buch und gib das Ergebnis strukturiert im vorgegebenen JSON-Format zurück."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=BookAnalysis,
        temperature=0.1,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_prompt,
        config=config,
    )

    if hasattr(response, "parsed") and response.parsed is not None:
        analysis: BookAnalysis = response.parsed
    else:
        analysis = BookAnalysis.model_validate_json(response.text)

    # Cross-Validation & Confidence
    cat, confidence, needs_rev, rev_reason = cross_validate_and_score(
        original_filename=original_filename,
        pdf_text=pdf_text,
        raw_category=analysis.kategorie,
        author=analysis.autor,
        title=analysis.titel,
        existing_folders=existing_folders,
    )

    return BookAnalysis(
        kategorie=sanitize_folder_name(cat),
        autor=analysis.autor.replace("[", "").replace("]", "").strip() or "Unbekannt",
        titel=analysis.titel.replace("[", "").replace("]", "").strip() or "Unbenannt",
        neuer_dateiname=sanitize_filename(analysis.neuer_dateiname),
        confidence=confidence,
        needs_review=needs_rev,
        review_reason=rev_reason,
    )
