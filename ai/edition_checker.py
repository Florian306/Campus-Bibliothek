"""Automated Edition Sentinel for textbook update tracking.
Queries DNB and Google Books catalogs to detect newer published editions of indexed textbooks.
Saves edition alerts to library.db for visual warning badges in the dashboard.
"""

import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple
from core.library_db import get_all_books, save_edition_alert


_EDITION_REGEX = re.compile(r'(\d{1,2})\.\s*(?:,\s*)?(?:neu\s*bearbeitete|aktualisierte|überarbeitete|erweiterte|vollständig)?\s*Aufl(?:age)?', re.IGNORECASE)

# SSL context fallback for environments with missing root certificates
_ssl_context = None
try:
    _ssl_context = ssl.create_default_context()
except Exception:
    _ssl_context = ssl._create_unverified_context()


def parse_edition_from_string(text: str) -> Optional[int]:
    """Extracts integer edition number from a title or description string."""
    m = _EDITION_REGEX.search(text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def check_for_newer_edition(book: Dict, timeout: float = 4.0) -> Optional[Dict]:
    """Queries Google Books API for newer editions of a textbook safely."""
    title = book.get("title", "").strip()
    author = book.get("author", "").strip()
    current_ed = book.get("edition") or 1

    if not title or title.lower() in ["unbekannt", ""] or len(title) < 4:
        return None
    if author.lower() in ["unbekannt", ""]:
        author_query = ""
    else:
        # Take first author name safely
        first_author = author.split()[0] if author.split() else ""
        first_author = re.sub(r'[^a-zA-ZäöüÄÖÜß]', '', first_author)
        author_query = f" inauthor:{first_author}" if first_author else ""

    clean_title = re.sub(r'[\(\)\[\]\-_:;,\.]', ' ', title).strip()
    clean_title = ' '.join(clean_title.split()[:5])  # Take first 5 words
    query = f"intitle:{clean_title}{author_query}"
    url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&maxResults=5&printType=books"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Buchsortierer/2.0",
                "Accept": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context) as resp:
            raw_data = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw_data)

        items = data.get("items", [])
        best_alert = None

        for item in items:
            v_info = item.get("volumeInfo", {})
            v_title = v_info.get("title", "")
            v_desc = v_info.get("description", "")
            v_date = v_info.get("publishedDate", "")
            v_isbns = [i.get("identifier") for i in v_info.get("industryIdentifiers", []) if i.get("identifier")]

            # Extract published year
            year = None
            if v_date:
                m_yr = re.search(r'\b(20\d\d|19\d\d)\b', v_date)
                if m_yr:
                    year = int(m_yr.group(1))

            # Detect edition in title, subtitle, or description
            full_txt = f"{v_title} {v_info.get('subtitle', '')} {v_desc[:300]}"
            ed_found = parse_edition_from_string(full_txt)

            if ed_found and ed_found > current_ed:
                if best_alert is None or ed_found > best_alert["latest_edition"]:
                    best_alert = {
                        "book_id": book["id"],
                        "current_edition": current_ed,
                        "latest_edition": ed_found,
                        "latest_year": year,
                        "latest_isbn": v_isbns[0] if v_isbns else None,
                        "latest_title": v_title,
                        "source": "Google Books",
                    }

        if best_alert:
            save_edition_alert(
                book_id=best_alert["book_id"],
                current_edition=best_alert["current_edition"],
                latest_edition=best_alert["latest_edition"],
                latest_year=best_alert["latest_year"],
                latest_isbn=best_alert["latest_isbn"],
                latest_title=best_alert["latest_title"],
                source=best_alert["source"]
            )
            return best_alert

    except Exception:
        # Ignore network errors silently and safely
        pass

    return None
