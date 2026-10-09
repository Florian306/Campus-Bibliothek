"""Plausibility matrix and sanity-check validator.
Guards against LLM hallucinations, metaphor traps, and chronological/disciplinary contradictions.
"""

import re
from typing import Optional, Tuple
from ai.categories import STANDARD_CATEGORIES


def perform_sanity_check(
    category: str,
    original_filename: str,
    title: str,
    pdf_text: str,
    confidence: int,
    audit_trail: str,
    existing_folders: Optional[list] = None,
) -> Tuple[str, int, bool, str]:
    """Applies strict sanity checks to detect and correct contradictions.
    
    Returns:
        (sanitized_category, adjusted_confidence, needs_review, final_audit_trail)
    """
    clean_context = f"{original_filename} {title} {pdf_text[:1200]}".lower()
    needs_review = (confidence < 80)
    final_category = category
    final_conf = confidence
    final_reason = audit_trail

    # Rule 1: History / Holocaust / NS Epoch Hard Veto against generic or ambiguous categories
    # Strict rule: NEVER override STEM sciences or linguistics based purely on casual imprint/preface mentions!
    stem_and_languages = {
        "Mathematik", "Physik & Astronomie", "Chemie", "Biologie & Lebenswissenschaften",
        "Informatik & Programmierung", "Medizin & Pharmazie", "Ingenieurwissenschaften & Technik",
        "Sprach- & Literaturwissenschaft"
    }

    title_context = f"{original_filename} {title}".lower()
    history_hard_triggers = [
        "auschwitz", "konzentrationslager", "holocaust", "judenverfolgung",
        "endlösung", "gestapo", "nsdap", "drittes reich", "nationalsozialis",
        "weimarer republik", "1939-1945", "1933-1945", "1941-1945", "1941–1945",
        "wehrmacht", "vernichtungslager", "generalgouvernement",
        "verfolgung und ermordung der europäischen juden", "shoah"
    ]
    has_history_in_title = any(ht in title_context for ht in history_hard_triggers)
    if has_history_in_title or (
        final_category not in stem_and_languages
        and any(ht in clean_context for ht in history_hard_triggers)
    ):
        if final_category not in stem_and_languages and final_category != "Geschichte & Politik":
            final_reason = f"[Sanity-Check] Historische Epoche/Quelle korrigiert auf Geschichte & Politik (vorher: {final_category})."
            final_category = "Geschichte & Politik"
            final_conf = 95
            needs_review = False

    # Rule 2: Mathematics Metaphors ("Höhlenmenschen", "Dummies", "Cartoons")
    math_hard_triggers = ["algebra", "analysis", "differentialrechnung", "integralrechnung", "vektorraum", "stochastik", "hochschulmathematik"]
    if any(mt in clean_context for mt in math_hard_triggers):
        if final_category in ["Geschichte & Politik", "Pädagogik & Schule", "Philosophie & Religion"]:
            final_reason = f"[Sanity-Check] Metapher im Titel erkannt, zugeordnet nach Inhalt: Mathematik (nicht {final_category})."
            final_category = "Mathematik"
            final_conf = 85
            needs_review = True

    # Rule 3: Zero-Text / Scanned PDF Penalty
    # Only applies if PDF page extraction was actually performed and produced unreadable content
    if pdf_text and len(pdf_text.strip()) > 0:
        is_scanned = "kein lesbarer text" in pdf_text.lower() or (
            "[seite" in pdf_text.lower() and len(pdf_text.strip()) < 25
        )
        if is_scanned:
            final_conf = min(final_conf, 65)
            needs_review = True
            final_reason = f"{final_reason} | Gescanntes PDF ohne lesbaren Text"

    # Rule 4: Philosophy & Religion vs. Infection / Medical Science Veto
    medical_veto_words = ["infektion", "virologie", "impfstoff", "pandemie", "ebola", "covid", "pathologie", "anatomie"]
    if any(w in clean_context for w in medical_veto_words):
        if final_category == "Philosophie & Religion":
            final_reason = f"[Sanity-Check] Thema Infektionen/Medizin widerspricht Kategorie 'Philosophie & Religion'."
            final_category = "Medizin & Pharmazie"
            final_conf = 95
            needs_review = False

    # Rule 5: Veterinary / Animal & Dog Training vs. Human Medicine Veto
    animal_veto_triggers = [
        "hund", "hunde", "welpe", "welpen", "katze", "katzen", "haustier", "haustiere",
        "tiertraining", "hundetraining", "clicker", "kynologie", "tiererziehung",
        "veterinär", "tiermedizin", "pferd", "reiten", "tierarzt", "tierärztin"
    ]
    if any(at in clean_context for at in animal_veto_triggers):
        if final_category in ["Medizin & Pharmazie", "Sonstiges"]:
            # Route to matching user folder (e.g. Tiermedizinischer Fachangestellter) or Biologie
            chosen_cat = "Biologie & Lebenswissenschaften"
            if existing_folders:
                for ef in existing_folders:
                    if any(k in ef.lower() for k in ["tiermedizin", "tier", "hund"]):
                        chosen_cat = ef
                        break
            final_reason = f"[Sanity-Check] Tierkunde/Veterinärbereich korrigiert auf '{chosen_cat}' (vorher: {final_category})."
            final_category = chosen_cat
            final_conf = 98
            needs_review = False

    # Rule 6: Sonstiges / Unknown Penalty (must ALWAYS require manual review)
    if final_category in ["Sonstiges", "Unbekannt", ""] or final_category not in STANDARD_CATEGORIES:
        # Check if it matches an existing user directory
        if existing_folders and final_category in existing_folders:
            pass
        else:
            final_category = "Sonstiges"
            final_conf = min(final_conf, 45)
            needs_review = True
            final_reason = f"{final_reason} | Unklarer Fachbereich (Prüfung erforderlich)"

    return final_category, final_conf, needs_review, final_reason
