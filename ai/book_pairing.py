"""Intelligent Textbook and Workbook Companion Pairing Engine.
Detects exercise books, workbooks, exam prep materials, and links them with their companion textbooks.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from core.library_db import save_book_pair, get_book_pair

EXERCISE_KEYWORDS = [
    "arbeitsbuch",
    "übungsbuch",
    "aufgabensammlung",
    "prüfungstrainer",
    "klausurentraining",
    "fallrepetitorium",
    "lösungsbuch",
    "lösungsheft",
    "workbook",
    "exercise book",
    "exam prep",
    "aufgaben und lösungen",
    "aufgaben & übungen",
    "prüfungsfragen",
]


def is_exercise_book(title: str, author: str = "") -> Tuple[bool, str]:
    """Detects whether a book is an exercise book, workbook or task collection.
    Returns (is_exercise, label_reason).
    """
    clean_t = title.lower()

    for kw in EXERCISE_KEYWORDS:
        if kw in clean_t:
            # Capitalize nice badge label
            label = "Arbeitsbuch" if "arbeitsbuch" in kw else ("Übungsbuch" if "übungs" in kw else "Aufgabensammlung")
            return True, label

    return False, ""


def _extract_subject_or_key_terms(title: str) -> List[str]:
    """Extracts distinctive anchor words (e.g. 'tipler', 'physik', 'analysis') ignoring common filler words."""
    clean = re.sub(r'[\(\)\[\]\-_,.:;]', ' ', title.lower())
    stop_words = {
        "arbeitsbuch", "übungsbuch", "aufgabensammlung", "prüfungstrainer", "klausurentraining",
        "für", "mit", "und", "alle", "aufgaben", "fragen", "lösungen", "zur", "auflage", "band",
        "bd", "teil", "der", "die", "das", "ein", "eine", "eines", "des", "den", "dem", "lehrbuch",
        "buch", "studium", "oberstufe", "it", "unterricht", "vorbereitung", "nach", "von", "zu",
        "ausgabe", "studenten", "studierende", "lernfeld"
    }
    tokens = [w for w in clean.split() if len(w) >= 4 and w not in stop_words]
    return tokens


def find_matching_pair(target_book: Dict[str, Any], all_books: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Discovers companion textbook for a workbook, or companion workbook for a textbook."""
    target_id = target_book.get("id")
    target_title = target_book.get("title", "")
    target_author = target_book.get("author", "")
    target_is_wb, _ = is_exercise_book(target_title, target_author)

    target_tokens = set(_extract_subject_or_key_terms(target_title))
    if not target_tokens:
        return None

    target_author_clean = re.sub(r'[^\w\s]', '', target_author.lower()).strip()
    target_author_parts = [p for p in target_author_clean.split() if len(p) >= 3]

    best_match = None
    best_score = 0.0

    for candidate in all_books:
        cand_id = candidate.get("id")
        if cand_id == target_id:
            continue

        cand_title = candidate.get("title", "")
        cand_author = candidate.get("author", "")
        cand_is_wb, _ = is_exercise_book(cand_title, cand_author)

        # We look for opposite roles: textbook <-> workbook
        if target_is_wb == cand_is_wb:
            continue

        cand_tokens = set(_extract_subject_or_key_terms(cand_title))
        cand_author_clean = re.sub(r'[^\w\s]', '', cand_author.lower()).strip()

        score = 0.0

        # 1. Author matching (e.g. 'Tipler' in candidate author or title)
        for part in target_author_parts:
            if part in cand_author_clean or part in cand_title.lower():
                score += 3.0

        for part in cand_author_clean.split():
            if len(part) >= 3 and (part in target_title.lower() or part in target_author_clean):
                score += 3.0

        # 2. Key terms overlap (e.g. 'physik', 'tipler', 'mosca')
        overlap = target_tokens.intersection(cand_tokens)
        score += len(overlap) * 2.0

        # Also check if candidate title appears in target title or vice versa
        for tok in target_tokens:
            if tok in cand_title.lower():
                score += 1.5

        if score > best_score and score >= 4.0:
            best_score = score
            best_match = candidate

    if best_match:
        best_match["match_score"] = best_score
        return best_match

    return None


def auto_pair_library(all_books: List[Dict[str, Any]]) -> int:
    """Scans all books in library and establishes companion links between textbooks and workbooks."""
    paired_count = 0
    workbooks = [b for b in all_books if is_exercise_book(b.get("title", ""), b.get("author", ""))[0]]

    for wb in workbooks:
        wb_id = wb.get("id")
        existing = get_book_pair(wb_id)
        if existing:
            continue

        match = find_matching_pair(wb, all_books)
        if match:
            main_book_id = match.get("id")
            save_book_pair(main_book_id, wb_id, match.get("match_score", 1.0))
            paired_count += 1

    return paired_count
