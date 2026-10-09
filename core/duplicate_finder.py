"""Smart duplicate book and multiple edition analyzer.
Finds redundant PDF copies, duplicate ISBNs, multi-volume works, and book chapters.
Distinguishes real identical duplicates from multi-volume editions (Bände) and chapter-split books.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from core.library_db import get_all_books


def _extract_volume_info(text: str) -> Optional[str]:
    """Detects volume markings like Band 1, Bd. 2, Vol. 3, Teil 1, or trailing volume numbers."""
    if not text:
        return None

    # 1. Explicit volume markers: Band 1, Bd. 2, Vol. 3, Teil 1, Part 2
    m = re.search(r'\b(?:band|vol(?:ume)?|teil|part|bd\.?)\s*(\d+|[ivxlcdm]+)\b', text, re.IGNORECASE)
    if m:
        return f"Band {m.group(1).upper()}"

    # 2. Filename style suffixes like "Name 1.pdf", "Buch_2.pdf", "Title - Band 3.pdf"
    base_name = os.path.splitext(os.path.basename(text))[0]
    m2 = re.search(r'(?:[_\-\s]|^)(\d+)\s*$', base_name)
    if m2:
        num = int(m2.group(1))
        # Valid volumes 1 to 50
        if 1 <= num <= 50:
            return f"Band {num}"
    return None


def _is_chapter_or_partial_file(book: Dict[str, Any]) -> Tuple[bool, str]:
    """Detects whether a file represents a chapter, section, or cover/index split rather than a full book."""
    file_path = book.get("file_path") or ""
    file_name = os.path.basename(file_path).lower()

    chapter_keywords = [
        "kapitel", "chapter", "inhaltsverzeichnis", "literaturverzeichnis",
        "literatur", "register", "cover", "front_cover", "back_cover",
        "titel", "impressum", "glossar", "anhang", "appendix", "vorwort", "preface"
    ]

    for kw in chapter_keywords:
        if kw in file_name:
            return True, f"Kapitel/Teil ({os.path.splitext(os.path.basename(file_path))[0]})"

    # Pattern like "1_Geomorphologie.pdf", "2_Klimageographie.pdf", "Ch01", "Chapter 2"
    # Note: explicitly avoid matching things like COVID-19 by ensuring underscore or chapter prefix
    if re.search(r'(?:^|[_\-\s])(?:ch(?:apter)?\s*\d+|\d{1,2}_[a-z])', file_name):
        return True, f"Einzelkapitel ({os.path.splitext(os.path.basename(file_path))[0]})"

    return False, ""


def find_library_duplicates(filter_mode: str = "all") -> List[Dict[str, Any]]:
    """Identifies duplicate candidates and categorizes them intelligently.
    
    Categories:
    - 'identical_duplicate': Genuine identical duplicate files (same content/file/hash or identical book)
    - 'multi_volume': Different volumes of the same work (e.g. Band 1, Band 2)
    - 'book_chapters': Individual chapters or sections of a single split book
    
    Args:
        filter_mode: 'all', 'duplicates_only', 'multi_volume', 'chapters'
    """
    books = get_all_books()
    groups: List[Dict[str, Any]] = []

    # 1. Group by ISBN (only valid 10/13 digits)
    isbn_groups: Dict[str, List[Dict[str, Any]]] = {}
    for b in books:
        raw_isbn = b.get("isbn")
        if raw_isbn:
            clean = "".join(c for c in str(raw_isbn) if c.isdigit())
            if len(clean) in (10, 13):
                isbn_groups.setdefault(clean, []).append(b)

    handled_ids = set()

    for isbn, blist in isbn_groups.items():
        if len(blist) > 1:
            # Check volumes from title and filepath
            vol_map = {}
            for b in blist:
                vol = _extract_volume_info(b.get("title", "")) or _extract_volume_info(b.get("file_path", ""))
                vol_map[b["id"]] = vol

            unique_vols = set(v for v in vol_map.values() if v)
            
            # Check chapter flags
            chapter_flags = [_is_chapter_or_partial_file(b) for b in blist]
            ch_true_count = sum(1 for is_ch, _ in chapter_flags if is_ch)
            dirs = set(os.path.dirname(b.get("file_path", "")) for b in blist if b.get("file_path"))
            
            if len(unique_vols) > 1:
                category = "multi_volume"
                vol_names = ", ".join(sorted(unique_vols))
                first_title = blist[0].get("title", "")
                reason = f"Mehrbändiges Werk ({vol_names}): '{first_title}'"
            elif ch_true_count >= 2 or (len(dirs) == 1 and ch_true_count >= 1):
                category = "book_chapters"
                reason = f"Einzelkapitel eines Buches (Gemeinsame ISBN {isbn})"
            else:
                # Same ISBN, no distinct volume numbers, not chapters -> actual identical duplicate
                category = "identical_duplicate"
                reason = f"Identische ISBN ({isbn})"

            groups.append({
                "reason": reason,
                "type": "isbn_group",
                "category": category,
                "count": len(blist),
                "books": blist,
            })
            for b in blist:
                handled_ids.add(b["id"])

    # 2. Group by normalized title & author
    title_author_groups: Dict[str, List[Dict[str, Any]]] = {}
    for b in books:
        t = (b.get("title") or "").strip().lower()
        a = (b.get("author") or "").strip().lower()
        if len(t) >= 4 and a and a != "unbekannt":
            key = f"{t}___{a}"
            title_author_groups.setdefault(key, []).append(b)

    for key, blist in title_author_groups.items():
        if len(blist) > 1:
            # Filter out books already grouped
            unhandled = [b for b in blist if b["id"] not in handled_ids]
            if len(unhandled) <= 1 and len(blist) == len(handled_ids.intersection(set(b["id"] for b in blist))):
                continue

            target_list = blist

            # Check volumes from title and filepath
            vol_map = {}
            for b in target_list:
                vol = _extract_volume_info(b.get("title", "")) or _extract_volume_info(b.get("file_path", ""))
                vol_map[b["id"]] = vol

            unique_vols = set(v for v in vol_map.values() if v)

            # Check chapter flags
            chapter_flags = [_is_chapter_or_partial_file(b) for b in target_list]
            ch_true_count = sum(1 for is_ch, _ in chapter_flags if is_ch)
            dirs = set(os.path.dirname(b.get("file_path", "")) for b in target_list if b.get("file_path"))

            if len(unique_vols) > 1:
                category = "multi_volume"
                vol_names = ", ".join(sorted(unique_vols))
                reason = f"Mehrbändiges Werk ({vol_names}): '{target_list[0].get('title', '')}'"
            elif ch_true_count >= 2 or (len(dirs) == 1 and ch_true_count >= 1):
                category = "book_chapters"
                reason = f"Einzelkapitel eines Buches: '{target_list[0].get('title', '')}'"
            else:
                # Are page counts vastly different while one is a chapter/leaflet?
                page_counts = [b.get("page_count") or 0 for b in target_list]
                if min(page_counts) < 15 and max(page_counts) > 100:
                    category = "book_chapters"
                    reason = f"Buch & Begleitdokumente/Kapitel: '{target_list[0].get('title', '')}'"
                else:
                    category = "identical_duplicate"
                    reason = f"Gleicher Titel & Autor: '{target_list[0].get('title', '')}'"

            groups.append({
                "reason": reason,
                "type": "title_author_group",
                "category": category,
                "count": len(target_list),
                "books": target_list,
            })
            for b in target_list:
                handled_ids.add(b["id"])

    # Filter based on requested filter_mode
    if filter_mode == "duplicates_only":
        return [g for g in groups if g["category"] == "identical_duplicate"]
    elif filter_mode == "multi_volume":
        return [g for g in groups if g["category"] == "multi_volume"]
    elif filter_mode == "chapters":
        return [g for g in groups if g["category"] == "book_chapters"]

    return groups
