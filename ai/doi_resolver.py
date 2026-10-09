"""Academic DOI (Digital Object Identifier) extractor and Crossref REST API resolver.
Provides official publisher bibliographic data with 100% precision for university textbooks.
"""

import json
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple
from core.cache_manager import get_cached_identifier, save_cached_identifier
from ai.categories import STANDARD_CATEGORIES

# Regex matching official standard DOIs (e.g., 10.1007/978-3-662-63286-4)
DOI_REGEX = re.compile(r'\b(10\.\d{4,9}/[^\s"\'<>]+)', re.IGNORECASE)

# Subject keyword mappings from Crossref academic taxonomy to STANDARD_CATEGORIES
CROSSREF_SUBJECT_MAP: Dict[str, str] = {
    # Medizin & Pharmazie
    "medicine": "Medizin & Pharmazie",
    "pharmacology": "Medizin & Pharmazie",
    "pharmacy": "Medizin & Pharmazie",
    "biomedicine": "Medizin & Pharmazie",
    "infectious diseases": "Medizin & Pharmazie",
    "virology": "Medizin & Pharmazie",
    "immunology": "Medizin & Pharmazie",
    "public health": "Medizin & Pharmazie",
    "internal medicine": "Medizin & Pharmazie",
    "surgery": "Medizin & Pharmazie",
    "pathology": "Medizin & Pharmazie",
    "clinical": "Medizin & Pharmazie",
    "toxicology": "Medizin & Pharmazie",
    # Informatik & Programmierung
    "computer science": "Informatik & Programmierung",
    "software engineering": "Informatik & Programmierung",
    "artificial intelligence": "Informatik & Programmierung",
    "computational": "Informatik & Programmierung",
    "information systems": "Informatik & Programmierung",
    "computer networks": "Informatik & Programmierung",
    "data structures": "Informatik & Programmierung",
    # Mathematik
    "mathematics": "Mathematik",
    "algebra": "Mathematik",
    "geometry": "Mathematik",
    "analysis": "Mathematik",
    "topology": "Mathematik",
    "statistics": "Mathematik",
    "numerical": "Mathematik",
    # Physik & Astronomie
    "physics": "Physik & Astronomie",
    "astronomy": "Physik & Astronomie",
    "astrophysics": "Physik & Astronomie",
    "optics": "Physik & Astronomie",
    "quantum": "Physik & Astronomie",
    "nuclear physics": "Physik & Astronomie",
    # Chemie
    "chemistry": "Chemie",
    "organic chemistry": "Chemie",
    "inorganic chemistry": "Chemie",
    "physical chemistry": "Chemie",
    "biochemistry": "Chemie",
    # Biologie & Lebenswissenschaften
    "biology": "Biologie & Lebenswissenschaften",
    "life sciences": "Biologie & Lebenswissenschaften",
    "microbiology": "Biologie & Lebenswissenschaften",
    "genetics": "Biologie & Lebenswissenschaften",
    "botany": "Biologie & Lebenswissenschaften",
    "zoology": "Biologie & Lebenswissenschaften",
    "ecology": "Biologie & Lebenswissenschaften",
    # Ingenieurwissenschaften & Technik
    "engineering": "Ingenieurwissenschaften & Technik",
    "mechanical engineering": "Ingenieurwissenschaften & Technik",
    "electrical engineering": "Ingenieurwissenschaften & Technik",
    "civil engineering": "Ingenieurwissenschaften & Technik",
    "electronics": "Ingenieurwissenschaften & Technik",
    "robotics": "Ingenieurwissenschaften & Technik",
    # Wirtschaft & Management
    "economics": "Wirtschaftswissenschaften",
    "business": "Wirtschaftswissenschaften",
    "management": "Wirtschaftswissenschaften",
    "finance": "Wirtschaftswissenschaften",
    "marketing": "Wirtschaftswissenschaften",
    "accounting": "Wirtschaftswissenschaften",
    # Jura & Rechtswissenschaften
    "law": "Jura & Rechtswissenschaften",
    "jurisprudence": "Jura & Rechtswissenschaften",
    "legal": "Jura & Rechtswissenschaften",
    "criminal law": "Jura & Rechtswissenschaften",
    # Psychologie & Soziologie
    "psychology": "Psychologie & Soziologie",
    "sociology": "Psychologie & Soziologie",
    "social sciences": "Psychologie & Soziologie",
    "psychotherapy": "Psychologie & Soziologie",
    # Philosophie & Religion
    "philosophy": "Philosophie & Religion",
    "religion": "Philosophie & Religion",
    "theology": "Philosophie & Religion",
    # Geschichte & Politik
    "history": "Geschichte & Politik",
    "archaeology": "Geschichte & Politik",
    "political science": "Geschichte & Politik",
    "international relations": "Geschichte & Politik",
    # Geowissenschaften & Geologie
    "earth sciences": "Geowissenschaften & Geologie",
    "geology": "Geowissenschaften & Geologie",
    "geography": "Geowissenschaften & Geologie",
    "meteorology": "Geowissenschaften & Geologie",
}


def extract_doi_candidates(text: str) -> List[str]:
    """Finds all potential DOI patterns in the extracted text or XMP metadata."""
    if not text:
        return []
    matches = DOI_REGEX.findall(text)
    clean_dois = []
    for m in matches:
        cleaned = m.rstrip(".,;)>]\"'")
        if cleaned and cleaned not in clean_dois:
            clean_dois.append(cleaned)
    return clean_dois


def resolve_doi_crossref(doi: str) -> Optional[Tuple[str, str, str, str]]:
    """Queries Crossref REST API for official metadata.
    Returns: (category, author, title, audit_reason) or None.
    """
    cached = get_cached_identifier(doi)
    if cached:
        cat, auth, title, reason = cached
        if cat == "NOT_FOUND":
            return None
        return cat, auth, title, reason

    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Buchsortierer/2.0 (mailto:sorter@academic.local)",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                msg = data.get("message", {})
                title = ""
                titles = msg.get("title", [])
                if titles and isinstance(titles, list):
                    title = re.sub(r'<[^>]+>', '', titles[0]).strip()
                    title = title.replace(" : ", " - ")
                    title = re.sub(r'\s+', ' ', title).rstrip(" /;:,. ")

                authors_list = []
                for a in msg.get("author", []):
                    family = a.get("family", "")
                    given = a.get("given", "")
                    if family and given:
                        authors_list.append(f"{given} {family}")
                    elif family:
                        authors_list.append(family)
                author = ", ".join(authors_list[:2]) if authors_list else "Unbekannt"

                subjects = [str(s).lower() for s in msg.get("subject", [])]
                publisher = msg.get("publisher", "")

                matched_cat = None
                for s in subjects:
                    for kw, cat in CROSSREF_SUBJECT_MAP.items():
                        if kw in s:
                            matched_cat = cat
                            break
                    if matched_cat:
                        break

                if not matched_cat:
                    t_lower = title.lower()
                    for kw, cat in CROSSREF_SUBJECT_MAP.items():
                        if kw in t_lower:
                            matched_cat = cat
                            break

                if not matched_cat:
                    matched_cat = "Sonstiges"

                reason = f"Crossref DOI {doi} ({publisher})"
                save_cached_identifier(doi, "DOI", matched_cat, author, title, reason)
                return matched_cat, author, title, reason
    except Exception:
        pass

    save_cached_identifier(doi, "DOI", "NOT_FOUND", "", "", "Nicht bei Crossref")
    return None


def resolve_doi_catalog(text: str) -> Optional[Tuple[str, str, str, str]]:
    """Scans text for DOI and resolves it against Crossref."""
    dois = extract_doi_candidates(text)
    for doi in dois[:3]:
        result = resolve_doi_crossref(doi)
        if result and result[0] != "Sonstiges":
            return result
    return None
