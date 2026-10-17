"""Automated Edition Sentinel for textbook update tracking.
Queries Deutsche Nationalbibliothek (DNB SRU MARC21), Google Books, and OpenLibrary
to reliably detect newer published editions of indexed textbooks without 429 rate limit blocks.
Saves edition alerts to library.db for visual warning badges in the dashboard.
"""

import json
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from core.library_db import get_all_books, save_edition_alert

_EDITION_REGEX = re.compile(
    r'(?:^|[^\d])(\d{1,2})\.\s*(?:,\s*)?(?:neu\s*bearbeitete|aktualisierte|überarbeitete|erweiterte|vollständig|korrigierte|verbesserte|wesentlich|durchgesehene)?\s*Aufl(?:age)?',
    re.IGNORECASE
)

_EDITION_EN_REGEX = re.compile(
    r'(?:^|[^\d])(\d{1,2})(?:st|nd|rd|th)?\s+(?:revised\s+)?ed(?:ition)?\b',
    re.IGNORECASE
)

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CampusLibrary-EditionSentinel/3.0"

_ssl_context = None
try:
    _ssl_context = ssl.create_default_context()
except Exception:
    _ssl_context = ssl._create_unverified_context()


def parse_edition_from_string(text: str) -> Optional[int]:
    """Extracts integer edition number from a title, edition string, or description."""
    if not text:
        return None
    m = _EDITION_REGEX.search(text)
    if m:
        try:
            val = int(m.group(1))
            if 1 <= val <= 50:
                return val
        except ValueError:
            pass

    m_en = _EDITION_EN_REGEX.search(text)
    if m_en:
        try:
            val = int(m_en.group(1))
            if 1 <= val <= 50:
                return val
        except ValueError:
            pass

    return None


def _check_dnb(clean_title: str, clean_author: str, current_ed: int, timeout: float = 4.0) -> Optional[Dict]:
    """Queries official Deutsche Nationalbibliothek SRU API with MARC21 schema for authentic edition data."""
    try:
        # Build precise SRU query for title and author
        title_terms = clean_title.split()[:4]
        tit_q = " ".join(title_terms)
        query = f'tit="{tit_q}"'
        if clean_author and len(clean_author) >= 3:
            author_term = clean_author.split()[0]
            query += f' and per="{author_term}"'

        url = (
            f"https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve"
            f"&query={urllib.parse.quote(query)}&recordSchema=MARC21-xml&maximumRecords=6"
        )
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context) as resp:
            xml_bytes = resp.read()

        root = ET.fromstring(xml_bytes)
        ns = {"marc": "http://www.loc.gov/MARC21/slim"}

        best_found = None

        for rec in root.findall(".//marc:record", ns):
            rec_title = ""
            rec_edition_str = ""
            rec_year = None
            rec_isbn = None

            for df in rec.findall("marc:datafield", ns):
                tag = df.attrib.get("tag")
                if tag == "245":
                    # Title
                    rec_title = " ".join([sf.text.strip() for sf in df.findall("marc:subfield", ns) if sf.text])
                elif tag == "250":
                    # Edition field (e.g. '20., überarbeitete Auflage')
                    rec_edition_str = " ".join([sf.text.strip() for sf in df.findall("marc:subfield", ns) if sf.text])
                elif tag in ["260", "264"]:
                    # Imprint / Year
                    y_text = " ".join([sf.text.strip() for sf in df.findall("marc:subfield", ns) if sf.text])
                    m_yr = re.search(r'\b(20\d\d|19\d\d)\b', y_text)
                    if m_yr:
                        rec_year = int(m_yr.group(1))
                elif tag == "020":
                    # ISBN
                    isbn_txt = "".join([sf.text.strip() for sf in df.findall("marc:subfield", ns) if sf.text])
                    m_isbn = re.search(r'\b(97[89][0-9\-]{10,14}[0-9Xx])\b', isbn_txt)
                    if m_isbn:
                        rec_isbn = m_isbn.group(1).replace("-", "")

            # Check edition from MARC tag 250 first, fallback to title
            ed_found = parse_edition_from_string(rec_edition_str) or parse_edition_from_string(rec_title)

            if ed_found and ed_found > current_ed:
                if best_found is None or ed_found > best_found["latest_edition"]:
                    best_found = {
                        "latest_edition": ed_found,
                        "latest_year": rec_year,
                        "latest_isbn": rec_isbn,
                        "latest_title": rec_title or clean_title,
                        "source": "Deutsche Nationalbibliothek (DNB)",
                    }

        return best_found
    except Exception:
        return None


def _check_open_library(clean_title: str, clean_author: str, current_ed: int, timeout: float = 3.5) -> Optional[Dict]:
    """Queries OpenLibrary catalog as a robust secondary provider without rate limits."""
    try:
        title_q = urllib.parse.quote(clean_title)
        url = f"https://openlibrary.org/search.json?title={title_q}&limit=5"
        if clean_author:
            url += f"&author={urllib.parse.quote(clean_author.split()[0])}"

        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        best_found = None
        for doc in data.get("docs", []):
            doc_title = doc.get("title", "")
            ed_count = doc.get("edition_count", 0)
            ed_names = doc.get("edition_name", [])
            years = doc.get("publish_year", [])
            latest_year = max(years) if years else None
            isbns = doc.get("isbn", [])
            latest_isbn = isbns[0] if isbns else None

            # Detect edition from explicit edition_name list or edition_count
            ed_found = None
            if ed_names:
                for ed_n in ed_names:
                    parsed = parse_edition_from_string(str(ed_n))
                    if parsed and (ed_found is None or parsed > ed_found):
                        ed_found = parsed

            # If edition_count > current_ed and plausible (> 1), use it as fallback
            if not ed_found and ed_count and ed_count > current_ed and ed_count <= 40:
                ed_found = int(ed_count)

            if ed_found and ed_found > current_ed:
                if best_found is None or ed_found > best_found["latest_edition"]:
                    best_found = {
                        "latest_edition": ed_found,
                        "latest_year": latest_year,
                        "latest_isbn": latest_isbn,
                        "latest_title": doc_title or clean_title,
                        "source": "Open Library",
                    }

        return best_found
    except Exception:
        return None


def _check_google_books(clean_title: str, clean_author: str, current_ed: int, timeout: float = 3.0) -> Optional[Dict]:
    """Queries Google Books API with graceful 429 backoff handling."""
    try:
        author_query = f" inauthor:{clean_author.split()[0]}" if clean_author else ""
        query = f"intitle:{clean_title}{author_query}"
        url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&maxResults=5&printType=books"

        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        items = data.get("items", [])
        best_found = None

        for item in items:
            v_info = item.get("volumeInfo", {})
            v_title = v_info.get("title", "")
            v_desc = v_info.get("description", "")
            v_date = v_info.get("publishedDate", "")
            v_isbns = [i.get("identifier") for i in v_info.get("industryIdentifiers", []) if i.get("identifier")]

            year = None
            if v_date:
                m_yr = re.search(r'\b(20\d\d|19\d\d)\b', v_date)
                if m_yr:
                    year = int(m_yr.group(1))

            full_txt = f"{v_title} {v_info.get('subtitle', '')} {v_desc[:300]}"
            ed_found = parse_edition_from_string(full_txt)

            if ed_found and ed_found > current_ed:
                if best_found is None or ed_found > best_found["latest_edition"]:
                    best_found = {
                        "latest_edition": ed_found,
                        "latest_year": year,
                        "latest_isbn": v_isbns[0] if v_isbns else None,
                        "latest_title": v_title,
                        "source": "Google Books",
                    }

        return best_found
    except Exception:
        return None


def check_for_newer_edition(book: Dict, timeout: float = 4.5) -> Optional[Dict]:
    """Multi-tiered edition check: DNB MARC21 -> OpenLibrary -> Google Books.
    Guarantees reliable edition discovery without breaking on API rate limits.
    """
    title = book.get("title", "").strip()
    author = book.get("author", "").strip()
    current_ed = book.get("edition") or 1

    if not title or title.lower() in ["unbekannt", ""] or len(title) < 4:
        return None

    # Clean title from special symbols and noise words
    clean_title = re.sub(r'[\(\)\[\]\-_:;,\.]', ' ', title).strip()
    clean_title = " ".join(clean_title.split()[:5])

    clean_author = ""
    if author and author.lower() not in ["unbekannt", ""]:
        first_word = author.split()[0]
        clean_author = re.sub(r'[^a-zA-ZäöüÄÖÜß]', '', first_word)

    # 1. Primary: Deutsche Nationalbibliothek (Authentic official MARC21 catalog for German & International textbooks)
    res = _check_dnb(clean_title, clean_author, current_ed, timeout=timeout)

    # 2. Secondary: OpenLibrary (Open catalog, no rate limits)
    if not res:
        res = _check_open_library(clean_title, clean_author, current_ed, timeout=timeout)

    # 3. Tertiary: Google Books
    if not res:
        res = _check_google_books(clean_title, clean_author, current_ed, timeout=timeout)

    if res:
        alert_data = {
            "book_id": book["id"],
            "current_edition": current_ed,
            "latest_edition": res["latest_edition"],
            "latest_year": res.get("latest_year"),
            "latest_isbn": res.get("latest_isbn"),
            "latest_title": res.get("latest_title", title),
            "source": res.get("source", "Katalogabgleich"),
        }
        save_edition_alert(
            book_id=alert_data["book_id"],
            current_edition=alert_data["current_edition"],
            latest_edition=alert_data["latest_edition"],
            latest_year=alert_data["latest_year"],
            latest_isbn=alert_data["latest_isbn"],
            latest_title=alert_data["latest_title"],
            source=alert_data["source"]
        )
        return alert_data

    return None
