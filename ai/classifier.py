"""High-precision hybrid academic classifier with weighted semantic scoring,
metaphor filtering, Table of Contents prioritization, and cross-validation.
"""

import re
from typing import Dict, List, Optional, Tuple
from ai.categories import (
    STANDARD_CATEGORIES,
    METAPHOR_STOPWORDS,
    FACULTY_KNOWLEDGE,
    COMPILED_FACULTY_KNOWLEDGE,
    COMPILED_FACULTY_UNION,
)


def clean_text_for_scoring(text: str) -> str:
    """Removes non-alphanumeric noise, formats whitespace, strips file extension and brackets."""
    clean = re.sub(r'\.pdf$', '', text, flags=re.IGNORECASE)
    clean = re.sub(r'[()\[\]{}]+', ' ', clean)
    clean = re.sub(r'[\-_.]+', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip().lower()


def classify_textbook(
    filename: str,
    text: str,
    existing_folders: Optional[List[str]] = None
) -> Tuple[str, int, str]:
    """Scores academic faculties using weighted anchors, keyword patterns, and TOC signals.
    
    Returns:
        (best_faculty, confidence_percent, explanation)
    """
    clean_fn = clean_text_for_scoring(filename)
    clean_text = text.lower() if text else ""

    # 1. Existing user folder matching (exact or high-similarity match)
    if existing_folders:
        for ef in existing_folders:
            ef_clean = ef.strip().lower()
            if len(ef_clean) > 3:
                pattern = r'\b' + re.escape(ef_clean) + r'\b'
                if re.search(pattern, clean_fn):
                    return ef.strip(), 98, f"Direkte Übereinstimmung mit Ordner '{ef}'"

    # 2. Extract Table of Contents / chapter chunk if present
    toc_chunk = ""
    if "--- inhaltsverzeichnis" in clean_text or "--- inhalt" in clean_text:
        match = re.search(r'---\s*inhalt[^\n]*---\n(.*?)(?:---|\Z)', clean_text, re.DOTALL)
        if match:
            toc_chunk = match.group(1)

    scores: Dict[str, float] = {cat: 0.0 for cat in STANDARD_CATEGORIES if cat != "Sonstiges"}
    matched_anchors: Dict[str, List[str]] = {cat: [] for cat in scores}

    # 3. Score each academic faculty with fast-reject optimization
    for faculty, c_data in COMPILED_FACULTY_KNOWLEDGE.items():
        union_regex = COMPILED_FACULTY_UNION.get(faculty)
        if union_regex and not (
            union_regex.search(clean_fn)
            or (toc_chunk and union_regex.search(toc_chunk))
            or (clean_text and union_regex.search(clean_text))
        ):
            continue

        # Anchors: Filename x12, TOC x8, Body x2.5
        for pat_str, regex in c_data.get("anchors", []):
            pat_clean = pat_str.replace(r"\b", "")
            if regex.search(clean_fn):
                scores[faculty] += 12.0
                matched_anchors[faculty].append(f"Titel: {pat_clean}")
            elif toc_chunk and regex.search(toc_chunk):
                scores[faculty] += 8.0
                matched_anchors[faculty].append(f"Inhalt: {pat_clean}")
            elif clean_text and regex.search(clean_text):
                scores[faculty] += 2.5
                matched_anchors[faculty].append(f"Text: {pat_clean}")

        # Secondary Keywords: Filename x4, TOC x2, Body x0.5
        for _, regex in c_data.get("keywords", []):
            if regex.search(clean_fn):
                scores[faculty] += 4.0
            elif toc_chunk and regex.search(toc_chunk):
                scores[faculty] += 2.0
            elif clean_text and regex.search(clean_text):
                scores[faculty] += 0.5

    # 4. Disambiguation Rules for Classic Academic Overlaps
    # Rule A: Metaphor in title ("Höhlenmenschen", "Dummies", "Kinder") -> Never history/pedagogy
    if any(m in clean_fn for m in ["höhlenmenschen", "steinzeit"]):
        if scores["Mathematik"] >= 10.0 and scores["Geschichte & Politik"] < 20.0:
            scores["Geschichte & Politik"] = 0.0

    # Rule B: Biochemistry: If plant/animal/genetics -> Biology; if synthesis/reaction -> Chemistry
    if scores["Biologie & Lebenswissenschaften"] > 0 and scores["Chemie"] > 0:
        if any(w in clean_fn or w in clean_text for w in ["pflanze", "tier", "zelle", "genom", "organismus", "evolution"]):
            scores["Biologie & Lebenswissenschaften"] += 5.0
        elif any(w in clean_fn or w in clean_text for w in ["synthese", "reaktionsmechanismus", "katalysator"]):
            scores["Chemie"] += 5.0

    # Rule C: Polar / Climate Research -> Geowissenschaften & Geologie
    if any(w in clean_fn or w in clean_text for w in ["polarforschung", "meereis", "arktis", "antarktis", "ozeanographie", "gletscher"]):
        scores["Geowissenschaften & Geologie"] += 10.0

    # Rule D: Applied Ethics / Bioethics / Infection Protection
    if any(w in clean_fn or w in clean_text for w in ["ethik", "risikoethik", "bioethik", "entscheidungstheorie", "normativ"]):
        if any(w in clean_fn or w in clean_text for w in ["infektion", "medizin", "patient", "pandemie", "impf", "klinik", "seuche", "virologie", "ebola", "covid"]):
            scores["Medizin & Pharmazie"] += 20.0
            scores["Philosophie & Religion"] = 0.0
        elif any(w in clean_fn or w in clean_text for w in ["wirtschaft", "unternehmen", "management", "corporate", "finanz"]):
            scores["Wirtschaftswissenschaften"] += 15.0
            scores["Philosophie & Religion"] = 0.0
        elif any(w in clean_fn or w in clean_text for w in ["künstliche intelligenz", "ki", "algorithmen", "roboter", "computer"]):
            scores["Informatik & Programmierung"] += 15.0
            scores["Philosophie & Religion"] = 0.0

    # Rule E: English & Foreign Language Learning Materials
    if any(w in clean_fn for w in ["business english", "english for everyone", "cambridge english", "oxford english", "sprachkurs", "practice book level"]):
        scores["Sprach- & Literaturwissenschaft"] += 20.0

    # Rule F: Web Development / HTML Semantics
    if any(w in clean_fn for w in ["html", "css", "webdesign", "responsive layout", "javascript"]):
        scores["Informatik & Programmierung"] += 25.0
        scores["Sprach- & Literaturwissenschaft"] = 0.0

    # Rule G: Pedagogical Diagnostics / Psychology
    if "pädagog" in clean_fn and "diagnostik" in clean_fn:
        scores["Pädagogik & Schule"] += 20.0
        scores["Medizin & Pharmazie"] = 0.0

    # Rule H: Distinct STEM & Medicine Title Overrides
    if any(w in clean_fn for w in ["chemistry", "chemical", "principles and reactions"]):
        scores["Chemie"] += 20.0
    if any(w in clean_fn for w in ["körper des menschen", "taschenatlas anatomie", "humanmedizin", "klinische anatomie"]):
        scores["Medizin & Pharmazie"] += 20.0

    # 5. Determine Winner (Must reach at least 6.0 points to prevent stray body false positives)
    best_faculty = "Sonstiges"
    best_score = 0.0
    sorted_faculties = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    if sorted_faculties and sorted_faculties[0][1] >= 6.0:
        best_faculty = sorted_faculties[0][0]
        best_score = sorted_faculties[0][1]

    # 6. Calibrate Confidence
    confidence = 50
    explanation = "Allgemeine Zuordnung"
    if best_score >= 6.0:
        runner_up = sorted_faculties[1][0] if len(sorted_faculties) > 1 else ""
        runner_score = sorted_faculties[1][1] if len(sorted_faculties) > 1 else 0.0
        lead = best_score - runner_score

        if best_score >= 18.0 or (lead >= 8.0 and best_score >= 12.0):
            confidence = 98
            anchors_str = ", ".join(matched_anchors[best_faculty][:2])
            explanation = f"Eindeutiger Fachbereich ({anchors_str})" if anchors_str else f"Eindeutig {best_faculty}"
        elif lead >= 6.0 or best_score >= 12.0:
            confidence = 90
            explanation = f"Hohe Übereinstimmung mit {best_faculty}"
        elif lead >= 3.0 or best_score >= 8.0:
            confidence = 78
            explanation = f"Leichte Tendenz zu {best_faculty} vor {runner_up}"
        else:
            confidence = 65
            explanation = f"Gleichstand/Uneindeutig zwischen {best_faculty} und {runner_up}"

    return best_faculty, confidence, explanation


def cross_validate_with_classifier(
    original_filename: str,
    pdf_text: str,
    raw_category: str,
    author: str,
    title: str,
    existing_folders: Optional[List[str]] = None,
) -> Tuple[str, int, bool, Optional[str]]:
    """Cross-validates an LLM-predicted category against the deterministic AcademicClassifier.
    
    Returns:
        (validated_category, confidence_percent, needs_review, review_reason)
    """
    category = raw_category
    confidence = 95
    needs_review = False
    review_reason = None

    # Run deterministic classification
    det_category, det_conf, det_expl = classify_textbook(
        filename=f"{original_filename} {title}",
        text=pdf_text,
        existing_folders=existing_folders
    )

    # 1. Scanned / Missing text penalty
    is_scanned = len(pdf_text.strip()) < 30 or "kein lesbarer text" in pdf_text.lower()
    if is_scanned:
        confidence = min(det_conf, 75)
        needs_review = (confidence < 80)
        review_reason = "Wenig/kein Text im PDF (Zuordnung anhand des Dateinamens)."
        return det_category if det_category != "Sonstiges" else category, confidence, needs_review, review_reason

    # 2. Model returned generic/empty category
    if category in ["Sonstiges", "Wissenschaftliche Fachbücher", "Fachbuch", "Unbekannt", ""] or category not in STANDARD_CATEGORIES:
        if det_category != "Sonstiges":
            category = det_category
            confidence = det_conf
            needs_review = (det_conf < 80)
            review_reason = f"Präzisiert zu '{category}' ({det_expl})"
        else:
            category = "Sonstiges"
            confidence = 45
            needs_review = True
            review_reason = "Fachbereich unklar (manuelle Prüfung erforderlich)"
        return category, confidence, needs_review, review_reason

    # 3. Agreement: Model and Deterministic Classifier agree
    if category == det_category:
        confidence = max(95, det_conf)
        return category, confidence, False, None

    # 4. Conflict: Model differs from Deterministic Classifier
    # Special Protection: Never let secondary ethical terms override an applied science model prediction to Philosophy!
    if det_category == "Philosophie & Religion" and category in ["Medizin & Pharmazie", "Informatik & Programmierung", "Wirtschaftswissenschaften", "Biologie & Lebenswissenschaften"]:
        return category, 92, False, None

    # If Deterministic Classifier has very high confidence (>= 92%), override model!
    if det_conf >= 92 and det_category != "Sonstiges":
        review_reason = f"Widerspruch behoben: Thema '{title}' ist {det_category} (Modell schätzte {category})."
        category = det_category
        confidence = 88
        needs_review = True
    elif det_conf >= 75:
        # Mild conflict, keep model but flag for quick user review
        confidence = 72
        needs_review = True
        review_reason = f"Zu überprüfen: Modell schlägt '{category}' vor, Text deutet auf '{det_category}' hin."
    else:
        # Low deterministic confidence, trust model
        confidence = 85
        needs_review = False

    return category, confidence, needs_review, review_reason
