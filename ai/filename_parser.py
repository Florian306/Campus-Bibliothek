"""Smart bibliographic filename parser for academic textbooks and manuscripts.
Extracts author, title, edition, publication year, and volume from diverse filename patterns.
Handles formats like:
  - 'Stryer - Biochemie (8. Aufl.) 2017.pdf'
  - 'Kugler, Peter - Anatomie und Physiologie.pdf'
  - '9783642123456_Innere_Medizin_Gerd_Herold.pdf'
  - 'Einfuehrung_in_die_Wirtschaftsinformatik_-_Hansen_Neumann.pdf'
"""

import os
import re
from typing import Dict, Any, Optional

SUBJECT_TERMS = {
    "makroökonomik", "mikroökonomik", "wirtschaftsinformatik", "betriebswirtschaftslehre",
    "volkswirtschaftslehre", "biochemie", "anatomie", "physiologie", "pathologie",
    "organische chemie", "anorganische chemie", "physik", "mathematik", "informatik",
    "neurobiologie", "histologie", "zellbiologie", "psychologie", "soziologie",
    "pädagogik", "didaktik", "rechtswissenschaft", "staatsrecht", "bgb", "strafrecht",
    "innere medizin", "chirurgie", "neurologie", "pharmakologie", "toxikologie"
}


def parse_filename_metadata(filename: str) -> Dict[str, Any]:
    """Parses a filename to extract author, title, year, and edition dictionary.
    Returns dict with keys: 'author', 'title', 'year', 'edition'.
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    clean = base.replace("_", " ").strip()

    # 1. Extract publication year (e.g. (2018), [2021], or standalone 1970-2029)
    year: Optional[int] = None
    y_match = re.search(r'\b(19[5-9]\d|20[0-3]\d)\b', clean)
    if y_match:
        try:
            year = int(y_match.group(1))
        except ValueError:
            pass

    # 2. Extract edition (e.g. 5. Aufl., 3rd ed., 2. überarbeitete Auflage)
    edition: Optional[int] = None
    ed_match = re.search(r'\b(\d+)\s*\.?\s*(?:Aufl(?:age)?|ed(?:ition)?)\b', clean, re.IGNORECASE)
    if ed_match:
        try:
            edition = int(ed_match.group(1))
        except ValueError:
            pass

    # 3. Strip release tags and bracketed metadata before stripping standalone year
    clean = re.sub(r'\[.*?\]', ' ', clean)
    if year:
        clean = re.sub(r'[\(\[]?\b' + str(year) + r'\b[\)\]]?', ' ', clean)
    if ed_match:
        clean = re.sub(r'\b\d+\s*\.?\s*(?:Aufl(?:age)?|ed(?:ition)?)\b', ' ', clean, flags=re.IGNORECASE)

    # 4. Strip leading ISBN if present (e.g. '9783642123456 ...')
    clean = re.sub(r'^(?:97[89]\d{10}|\d{10})\s*[-_ ]\s*', '', clean)

    # 5. Check Author in parentheses: e.g. "Taschenlehrbuch Histologie (Lüllmann-Rauch, Asan)"
    paren_author = None
    paren_match = re.search(r'\(([^)]+)\)', clean)
    if paren_match:
        cand_p = paren_match.group(1).strip()
        # If looks like author names (e.g. "Lüllmann-Rauch, Asan" or "Müller")
        if not re.search(r'\b(?:aufl|edition|vol|band|teil)\b', cand_p, re.I) and len(cand_p.split()) <= 4:
            paren_author = cand_p
            clean = clean[:paren_match.start()] + clean[paren_match.end():]

    clean = re.sub(r'[\(\)]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip(" -_,;.")

    # 6. Check Author - Title separator patterns
    author: Optional[str] = None
    title: Optional[str] = None

    if " - " in clean:
        parts = clean.split(" - ", 1)
        left = parts[0].strip()
        right = parts[1].strip()

        left_low = left.lower().replace("ue", "ü").replace("oe", "ö").replace("ae", "ä")
        right_low = right.lower().replace("ue", "ü").replace("oe", "ö").replace("ae", "ä")

        if any(term in left_low for term in SUBJECT_TERMS) or any(k in left_low for k in ["einführung", "lehrbuch", "grundlagen", "handbuch"]):
            title = left
            author = right
        elif any(term in right_low for term in SUBJECT_TERMS):
            title = right
            author = left
        elif len(left.split()) <= 2:
            if "," in left:
                sub = [s.strip() for s in left.split(",", 1)]
                author = f"{sub[1]} {sub[0]}".strip()
            else:
                author = left
            title = right
        else:
            title = left
            author = right

    # Pattern B: "Title by Author" or "Title von Author"
    elif re.search(r'\s+(?:by|von)\s+', clean, re.IGNORECASE):
        parts = re.split(r'\s+(?:by|von)\s+', clean, maxsplit=1, flags=re.IGNORECASE)
        title = parts[0].strip()
        author = parts[1].strip()

    else:
        title = clean
        if paren_author:
            author = paren_author

    # Final cleanup of title & author
    if title:
        title = re.sub(r'\s+', ' ', title).strip(" -_,;.()")
    if author:
        author = re.sub(r'\s+', ' ', author).strip(" -_,;.()")

    return {
        "author": author or None,
        "title": title or None,
        "year": year,
        "edition": edition
    }
