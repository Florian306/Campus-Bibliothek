"""Smart bibliographic filename parser for academic textbooks and manuscripts.
Extracts author, title, edition, publication year, and volume from diverse filename patterns.
Handles formats like:
  - 'Stryer - Biochemie (8. Aufl.) 2017.pdf'
  - 'Kugler, Peter - Anatomie und Physiologie.pdf'
  - '9783642123456_Innere_Medizin_Gerd_Herold.pdf'
  - 'dokumen.pub_physiologie-des-menschen-mit-pathophysiologie-springer-lehrbuch-german-edition.pdf'
  - 'dokumen.pub_prometheus-kopf-hals-und-neuroanatomie-lernatlas-anatomie-5-berarbeitetenbsped-9783132420915.pdf'
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
    """Parses a filename to extract author, title, year, edition, and ISBN.
    Returns dict with keys: 'author', 'title', 'year', 'edition', 'isbn'.
    """
    base = os.path.splitext(os.path.basename(filename))[0]

    # 0. Strip web portal download prefixes (e.g. dokumen.pub_, vdoc.pub_, etc.)
    clean = re.sub(
        r'^(?:dokumen\.pub|vdoc\.pub|pdfcoffee\.com|kupdf\.net|z-lib\.is|1lib\.ch|annas-archive)[\._\-\s]*',
        '',
        base,
        flags=re.IGNORECASE
    )

    # 1. Extract and preserve any 10- or 13-digit ISBN embedded in filename
    isbn: Optional[str] = None
    isbn_match = re.search(r'\b(97[89]\d{10}|\d{10})\b', clean)
    if isbn_match:
        isbn = isbn_match.group(1)
        clean = re.sub(r'[\-_ ]*' + isbn + r'\b', '', clean)

    # 2. Extract publication year (e.g. (2018), [2021], or standalone 1970-2029)
    year: Optional[int] = None
    y_match = re.search(r'\b(19[5-9]\d|20[0-3]\d)\b', clean)
    if y_match:
        try:
            year = int(y_match.group(1))
        except ValueError:
            pass

    # 3. Extract edition (e.g. 5. Aufl., 3rd ed., 2. überarbeitete Auflage, 5-berarbeitetenbsped)
    edition: Optional[int] = None
    ed_match = re.search(r'\b(\d+)\s*\.?\s*(?:Aufl(?:age)?|ed(?:ition)?)\b', clean, re.IGNORECASE)
    if ed_match:
        try:
            edition = int(ed_match.group(1))
        except ValueError:
            pass
    else:
        # Check slug-style edition: e.g. -5-berarbeitetenbsped or -5-auflage
        slug_ed = re.search(r'[-_ ](\d+)[-_ ](?:berarbeitete|auflage|edition)', clean, re.IGNORECASE)
        if slug_ed:
            try:
                edition = int(slug_ed.group(1))
            except ValueError:
                pass

    # 4. Clean web slug artifacts and release tags
    clean = re.sub(r'[-_ ](?:german|english)[-_ ]edition\b', ' ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[-_ ](?:springer|pearson|hanser|vahlen|de[-_ ]gruyter)[-_ ]lehrbuch\b', ' ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[-_ ](?:springer|pearson|hanser|vahlen|de[-_ ]gruyter)\b', ' ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[-_ ]\d+[-_ ][a-z]*berarbeitetenbsped\b', ' ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[-_ ]\d+[-_ ]auflage\b', ' ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\[.*?\]', ' ', clean)

    if year:
        clean = re.sub(r'[\(\[]?\b' + str(year) + r'\b[\)\]]?', ' ', clean)
    if ed_match:
        clean = re.sub(r'\b\d+\s*\.?\s*(?:Aufl(?:age)?|ed(?:ition)?)\b', ' ', clean, flags=re.IGNORECASE)

    # 5. Check Author in parentheses: e.g. "Taschenlehrbuch Histologie (Lüllmann-Rauch, Asan)"
    paren_author = None
    paren_match = re.search(r'\(([^)]+)\)', clean)
    if paren_match:
        cand_p = paren_match.group(1).strip()
        if not re.search(r'\b(?:aufl|edition|vol|band|teil)\b', cand_p, re.I) and len(cand_p.split()) <= 4:
            paren_author = cand_p
            clean = clean[:paren_match.start()] + clean[paren_match.end():]

    clean = re.sub(r'[\(\)]', ' ', clean)

    # If the filename is kebab-cased or snake-cased throughout without explicit " - "
    if " - " not in clean:
        clean = clean.replace("_", " ").replace("-", " ")
    else:
        clean = clean.replace("_", " ")

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

    # Title Capitalization & Polish (e.g. if slug-derived lowercase "physiologie des menschen mit pathophysiologie")
    if title:
        title = re.sub(r'\s+', ' ', title).strip(" -_,;.()")
        # If all lowercase, title-case words with German grammar rules
        if title.islower():
            lower_words = {"des", "der", "die", "das", "und", "oder", "in", "im", "am", "an", "von", "vom", "zu", "zum", "zur", "mit", "für", "auf", "aus"}
            words = title.split()
            title = " ".join(
                w.capitalize() if i == 0 or w.lower() not in lower_words else w.lower()
                for i, w in enumerate(words)
            )

    if author:
        author = re.sub(r'\s+', ' ', author).strip(" -_,;.()")

    return {
        "author": author or None,
        "title": title or None,
        "year": year,
        "edition": edition,
        "isbn": isbn
    }
