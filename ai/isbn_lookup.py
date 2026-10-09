"""High-speed ISBN extraction with mathematical checksum validation and bibliographic catalog resolver.
Queries Google Books, Deutsche Nationalbibliothek (DNB), and OpenLibrary with persistent SQLite caching.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
from core.cache_manager import get_cached_identifier, save_cached_identifier
from ai.categories import STANDARD_CATEGORIES

_ISBN_EXPLICIT_RE = re.compile(r'(?:ISBN(?:-1[03])?[\s:]+)([0-9Xx\-\s]{10,20})', re.IGNORECASE)
_ISBN_STRICT13_RE = re.compile(r'\b(97[89][-\s]?[0-9]{1,5}[-\s]?[0-9]+[-\s]?[0-9]+[-\s]?[0-9])\b')
_CLEAN_RE = re.compile(r'[-\s]')

# Dewey Decimal Classification (DDC) & Subject Code Mapping to Academic Faculties
DDC_MAP: Dict[str, str] = {
    # 500 Naturwissenschaften & Mathematik
    "51": "Mathematik",
    "510": "Mathematik",
    "511": "Mathematik",
    "512": "Mathematik",
    "513": "Mathematik",
    "514": "Mathematik",
    "515": "Mathematik",
    "516": "Mathematik",
    "519": "Mathematik",
    "52": "Physik & Astronomie",
    "520": "Physik & Astronomie",
    "53": "Physik & Astronomie",
    "530": "Physik & Astronomie",
    "531": "Physik & Astronomie",
    "532": "Physik & Astronomie",
    "533": "Physik & Astronomie",
    "534": "Physik & Astronomie",
    "535": "Physik & Astronomie",
    "536": "Physik & Astronomie",
    "537": "Physik & Astronomie",
    "539": "Physik & Astronomie",
    "54": "Chemie",
    "540": "Chemie",
    "541": "Chemie",
    "542": "Chemie",
    "543": "Chemie",
    "546": "Chemie",
    "547": "Chemie",
    "55": "Geowissenschaften & Geologie",
    "550": "Geowissenschaften & Geologie",
    "551": "Geowissenschaften & Geologie",
    "552": "Geowissenschaften & Geologie",
    "56": "Geowissenschaften & Geologie",
    "57": "Biologie & Lebenswissenschaften",
    "570": "Biologie & Lebenswissenschaften",
    "571": "Biologie & Lebenswissenschaften",
    "572": "Biologie & Lebenswissenschaften",
    "576": "Biologie & Lebenswissenschaften",
    "577": "Biologie & Lebenswissenschaften",
    "58": "Biologie & Lebenswissenschaften",
    "580": "Biologie & Lebenswissenschaften",
    "59": "Biologie & Lebenswissenschaften",
    "590": "Biologie & Lebenswissenschaften",
    # 600 Technik, Medizin, Landwirtschaft & Tierkunde
    "63": "Biologie & Lebenswissenschaften",
    "630": "Biologie & Lebenswissenschaften",
    "636": "Biologie & Lebenswissenschaften",
    "61": "Medizin & Pharmazie",
    "610": "Medizin & Pharmazie",
    "611": "Medizin & Pharmazie",
    "612": "Medizin & Pharmazie",
    "615": "Medizin & Pharmazie",
    "616": "Medizin & Pharmazie",
    "617": "Medizin & Pharmazie",
    "618": "Medizin & Pharmazie",
    "62": "Ingenieurwissenschaften & Technik",
    "620": "Ingenieurwissenschaften & Technik",
    "621": "Ingenieurwissenschaften & Technik",
    "624": "Ingenieurwissenschaften & Technik",
    "629": "Ingenieurwissenschaften & Technik",
    # 000 Informatik
    "004": "Informatik & Programmierung",
    "005": "Informatik & Programmierung",
    "006": "Informatik & Programmierung",
    # 100 Philosophie & Psychologie
    "15": "Psychologie & Soziologie",
    "150": "Psychologie & Soziologie",
    "152": "Psychologie & Soziologie",
    "153": "Psychologie & Soziologie",
    "155": "Psychologie & Soziologie",
    "10": "Philosophie & Religion",
    "100": "Philosophie & Religion",
    "11": "Philosophie & Religion",
    "12": "Philosophie & Religion",
    "14": "Philosophie & Religion",
    "16": "Philosophie & Religion",
    "17": "Philosophie & Religion",
    "20": "Philosophie & Religion",
    "200": "Philosophie & Religion",
    "22": "Philosophie & Religion",
    "23": "Philosophie & Religion",
    # 300 Sozialwissenschaften, Wirtschaft, Recht
    "30": "Psychologie & Soziologie",
    "300": "Psychologie & Soziologie",
    "301": "Psychologie & Soziologie",
    "33": "Wirtschaftswissenschaften",
    "330": "Wirtschaftswissenschaften",
    "331": "Wirtschaftswissenschaften",
    "332": "Wirtschaftswissenschaften",
    "336": "Wirtschaftswissenschaften",
    "338": "Wirtschaftswissenschaften",
    "658": "Wirtschaftswissenschaften",
    "34": "Rechtswissenschaften & Jura",
    "340": "Rechtswissenschaften & Jura",
    "341": "Rechtswissenschaften & Jura",
    "342": "Rechtswissenschaften & Jura",
    "343": "Rechtswissenschaften & Jura",
    "344": "Rechtswissenschaften & Jura",
    "345": "Rechtswissenschaften & Jura",
    "346": "Rechtswissenschaften & Jura",
    "347": "Rechtswissenschaften & Jura",
    "37": "Pädagogik & Schule",
    "370": "Pädagogik & Schule",
    "371": "Pädagogik & Schule",
    "372": "Pädagogik & Schule",
    # 400 & 800 Sprache & Literatur
    "40": "Sprach- & Literaturwissenschaft",
    "400": "Sprach- & Literaturwissenschaft",
    "41": "Sprach- & Literaturwissenschaft",
    "43": "Sprach- & Literaturwissenschaft",
    "80": "Sprach- & Literaturwissenschaft",
    "800": "Sprach- & Literaturwissenschaft",
    "83": "Sprach- & Literaturwissenschaft",
    # 900 Geschichte & Politik
    "90": "Geschichte & Politik",
    "900": "Geschichte & Politik",
    "909": "Geschichte & Politik",
    "94": "Geschichte & Politik",
    "940": "Geschichte & Politik",
    "943": "Geschichte & Politik",
    "32": "Geschichte & Politik",
    "320": "Geschichte & Politik",
}


def _is_valid_isbn13(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if len(digits) != 13 or (digits[0] != 9 or digits[1] != 7 or digits[2] not in (8, 9)):
        return False
    check = (10 - sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12])) % 10) % 10
    return check == digits[12]


def _is_valid_isbn10(s: str) -> bool:
    clean = [c for c in s.upper() if c.isdigit() or c == "X"]
    if len(clean) != 10:
        return False
    try:
        total = sum(int(clean[i]) * (10 - i) for i in range(9))
        last = 10 if clean[9] == "X" else int(clean[9])
        return (total + last) % 11 == 0
    except ValueError:
        return False


def extract_isbns(text: str) -> List[str]:
    """Extracts only verified ISBNs passing official checksums.
    Prioritizes explicit 'ISBN' labels to completely avoid matching phone numbers or order IDs.
    """
    if not text:
        return []

    valid_isbns: List[str] = []

    # 1. High-confidence: Explicit ISBN keyword nearby
    explicit_matches = _ISBN_EXPLICIT_RE.findall(text)
    for m in explicit_matches:
        clean = _CLEAN_RE.sub('', m).upper()
        if _is_valid_isbn13(clean) or _is_valid_isbn10(clean):
            if clean not in valid_isbns:
                valid_isbns.append(clean)

    # 2. If nothing found, only scan for strict 978/979 ISBN-13 with valid checksum
    if not valid_isbns:
        matches = _ISBN_STRICT13_RE.findall(text)
        for m in matches:
            clean = _CLEAN_RE.sub('', m)
            if _is_valid_isbn13(clean) and clean not in valid_isbns:
                valid_isbns.append(clean)

    return valid_isbns


def clean_catalog_title(raw_title: str) -> str:
    """Cleans library catalog titles from DNB / Google Books / OpenLibrary.
    Removes bracketed original-language translations, responsibility statements, and noise.
    """
    if not raw_title:
        return ""
    # 1. DNB Statement of responsibility: "Title / by Author"
    title = raw_title.split(" / ")[0].strip()

    # 2. DNB bracketed original title/author prefix: "[Biochemistry] ; Stryer Biochemie" -> "Stryer Biochemie"
    title = re.sub(r'^\[.*?\]\s*;\s*', '', title).strip()

    # 3. Replace German catalog colon format " : " with " - "
    title = title.replace(" : ", " - ")

    # 4. Remove trailing media notes like " - [extra materials]"
    title = re.sub(r'\s*-\s*\[(?:extra materials|elektronische ressource|online-ausgabe|e-book|cd-rom|dvd|tag für tag[^\]]*)\]', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*\[(?:extra materials|elektronische ressource|online-ausgabe|e-book|cd-rom|dvd|tag für tag[^\]]*)\]', '', title, flags=re.IGNORECASE)

    # 5. Clean whitespace and trailing punctuation
    title = re.sub(r'\s+', ' ', title).strip()
    title = title.rstrip(" /;:,. ")
    return title


def query_google_books(isbn: str) -> Optional[dict]:
    """Queries Google Books public volume API with a strict 1.0s timeout."""
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
        req = urllib.request.Request(url, headers={"User-Agent": "BuchsortiererAI/2.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
            if items:
                v_info = items[0].get("volumeInfo", {})
                raw_t = v_info.get("title", "")
                sub_t = v_info.get("subtitle", "")
                clean_t = clean_catalog_title(raw_t)
                if sub_t and sub_t.lower() not in clean_t.lower():
                    clean_t = f"{clean_t} - {clean_catalog_title(sub_t)}"
                v_info["title"] = clean_t
                return v_info
    except Exception:
        return None


def query_dnb(isbn: str) -> Optional[dict]:
    """Queries Deutsche Nationalbibliothek (DNB) SRU catalog API with a strict 1.2s timeout."""
    try:
        url = f"https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve&query=isbn%3D{isbn}&recordSchema=oai_dc"
        req = urllib.request.Request(url, headers={"User-Agent": "Buchsortierer/2.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            ns = {
                "srw": "http://www.loc.gov/zing/srw/",
                "dc": "http://purl.org/dc/elements/1.1/",
            }
            records = root.findall(".//srw:recordData", ns)
            if not records:
                return None

            title_elem = records[0].find(".//dc:title", ns)
            raw_title = title_elem.text if title_elem is not None and title_elem.text else ""
            clean_title = clean_catalog_title(raw_title)

            creator_elem = records[0].find(".//dc:creator", ns)
            raw_creator = creator_elem.text if creator_elem is not None and creator_elem.text else "Unbekannt"
            clean_creator = re.sub(r'\[.*?\]', '', raw_creator).strip()
            clean_creator = re.sub(r'\s*\(.*?\)', '', clean_creator).strip()
            if ", " in clean_creator:
                parts = clean_creator.split(", ", 1)
                clean_creator = f"{parts[1]} {parts[0]}"

            subjects = []
            for s in records[0].findall(".//dc:subject", ns):
                if s.text:
                    subjects.append(s.text.strip())

            return {"title": clean_title, "creator": clean_creator, "subjects": subjects}
    except Exception:
        return None


def query_openlibrary(isbn: str) -> Optional[dict]:
    """Queries OpenLibrary public catalog API with a strict 1.0s timeout."""
    try:
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
        req = urllib.request.Request(url, headers={"User-Agent": "BuchsortiererAI/2.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            key = f"ISBN:{isbn}"
            return data.get(key)
    except Exception:
        return None


def map_ddc_to_faculty(ddc_codes: List[str]) -> Optional[str]:
    """Maps DDC decimal codes to our standard academic faculties."""
    for code in ddc_codes:
        clean_code = re.sub(r'[^0-9]', '', str(code))
        for prefix_len in [3, 2]:
            prefix = clean_code[:prefix_len]
            if prefix in DDC_MAP:
                return DDC_MAP[prefix]
    return None


def map_subjects_to_faculty(subjects: List[str], existing_folders: Optional[List[str]] = None) -> Optional[str]:
    """Maps BISAC / Library of Congress text categories to academic faculties."""
    joined = " ".join([s.lower() for s in subjects])

    # 1. Animal / Veterinary Disambiguation (Must be evaluated BEFORE human medicine)
    if any(k in joined for k in ["veterinär", "tiermedizin", "tierhaltung", "haustier", "hund", "katze", "kynologie", "zoolog"]):
        if existing_folders:
            for ef in existing_folders:
                if any(k in ef.lower() for k in ["tiermedizin", "tier", "hund"]):
                    return ef
        return "Biologie & Lebenswissenschaften"

    if any(k in joined for k in ["mathematic", "algebra", "calculus", "geometry", "stochast"]):
        return "Mathematik"
    if any(k in joined for k in ["physic", "quantum", "astronom", "thermodynamic", "mechanic"]):
        return "Physik & Astronomie"
    if any(k in joined for k in ["chemist", "organic", "inorganic", "biochem"]):
        return "Chemie"
    if any(k in joined for k in ["biolog", "genetics", "cellular", "botany", "microbiol"]):
        return "Biologie & Lebenswissenschaften"
    if any(k in joined for k in ["geolog", "earth", "oceanograph", "mineral", "geograph"]):
        return "Geowissenschaften & Geologie"
    if any(k in joined for k in ["computer", "program", "software", "algorithm", "network", "data"]):
        return "Informatik & Programmierung"
    if any(k in joined for k in ["medic", "pharmac", "patholog", "anatom", "surger", "clinic", "gesundheit", "humanmedizin"]) or (r"\bmedizin\b" in joined and "veterinär" not in joined):
        return "Medizin & Pharmazie"
    if any(k in joined for k in ["psycholog", "sociolog", "cognit", "behavior", "mental"]):
        return "Psychologie & Soziologie"
    if any(k in joined for k in ["econom", "business", "financ", "account", "manag", "market", "wirtschaft"]):
        return "Wirtschaftswissenschaften"
    if any(k in joined for k in ["law", "jurispruden", "legal", "recht", "strafrecht"]):
        return "Rechtswissenschaften & Jura"
    if any(k in joined for k in ["engineer", "mechanic", "electr", "civil engineer", "ingenieur"]):
        return "Ingenieurwissenschaften & Technik"
    if any(k in joined for k in ["histor", "polit", "world war", "archaeol", "geschichte"]):
        return "Geschichte & Politik"
    if any(k in joined for k in ["philosoph", "relig", "theolog"]):
        return "Philosophie & Religion"
    if any(k in joined for k in ["educat", "pedagog", "school", "teach", "pädagogik"]):
        return "Pädagogik & Schule"
    if any(k in joined for k in ["linguistic", "literat", "language", "grammar", "germanistik"]):
        return "Sprach- & Literaturwissenschaft"
    return None


def resolve_isbn_catalog(text_or_metadata: str, existing_folders: Optional[List[str]] = None) -> Optional[Tuple[str, str, str, str]]:
    """Tries to find verified ISBN and resolve official metadata via Google Books, DNB, or OpenLibrary.
    Cached locally in SQLite for instant 0ms retrieval and negative cache protection.
    """
    isbns = extract_isbns(text_or_metadata)
    if not isbns:
        return None

    # Title-only hit (catalog found book but no faculty mapping)
    partial: Optional[Tuple[str, str, str, str]] = None

    for isbn in isbns[:2]:
        cached = get_cached_identifier(isbn)
        if cached:
            cat, auth, title, reason = cached
            # Retry stale negative entries (may stem from former timeouts)
            if cat != "NOT_FOUND":
                return cat, auth, title, reason

        # 1. Google Books (fastest API response ~150ms, richest metadata)
        gb_info = query_google_books(isbn)
        if gb_info and gb_info.get("title") and not partial:
            _a = gb_info.get("authors", [])
            _auth = _a[0] if len(_a) == 1 else (f"{_a[0]} et al." if len(_a) > 1 else "Unbekannt")
            partial = ("", _auth, gb_info["title"], f"🏛️ ISBN {isbn} (Google Books, ohne Fachgebiet)")
        if gb_info:
            title = gb_info.get("title", "")
            authors = gb_info.get("authors", [])
            author_str = authors[0] if len(authors) == 1 else (f"{authors[0]} et al." if len(authors) > 1 else "Unbekannt")
            categories = gb_info.get("categories", [])
            cat = map_subjects_to_faculty(categories, existing_folders)
            if cat and title:
                reason = f"🏛️ ISBN {isbn} (Google Books Katalog)"
                save_cached_identifier(isbn, "ISBN", cat, author_str, title, reason)
                return cat, author_str, title, reason

        # 2 & 3: Run DNB and OpenLibrary concurrently if Google Books was inconclusive
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_dnb = executor.submit(query_dnb, isbn)
            fut_ol = executor.submit(query_openlibrary, isbn)
            dnb_info = fut_dnb.result()
            ol_info = fut_ol.result()

        # Check DNB first (gold standard for German bibliography)
        if dnb_info and dnb_info.get("title"):
            title = dnb_info["title"]
            author = dnb_info["creator"]
            if not partial:
                partial = ("", author, title, f"🏛️ ISBN {isbn} (DNB, ohne Fachgebiet)")
            subjects = dnb_info.get("subjects", [])
            cat = map_ddc_to_faculty(subjects) or map_subjects_to_faculty(subjects, existing_folders)
            if cat == "Biologie & Lebenswissenschaften" and existing_folders:
                for ef in existing_folders:
                    if any(k in ef.lower() for k in ["tiermedizin", "tier", "hund"]):
                        cat = ef
                        break

            if cat and title:
                reason = f"🏛️ ISBN {isbn} (Deutsche Nationalbibliothek DNB)"
                save_cached_identifier(isbn, "ISBN", cat, author, title, reason)
                return cat, author, title, reason

        # Check OpenLibrary DDC classifications
        if ol_info:
            title = clean_catalog_title(ol_info.get("title", ""))
            authors = [a.get("name", "") for a in ol_info.get("authors", [])]
            author_str = authors[0] if len(authors) == 1 else (f"{authors[0]} et al." if len(authors) > 1 else "Unbekannt")
            if title and not partial:
                partial = ("", author_str, title, f"🏛️ ISBN {isbn} (OpenLibrary, ohne Fachgebiet)")
            classifications = ol_info.get("classifications", {})
            ddc_list = classifications.get("dewey_decimal_class", [])
            cat = map_ddc_to_faculty(ddc_list)
            if not cat:
                subjects = [s.get("name", "") if isinstance(s, dict) else str(s) for s in ol_info.get("subjects", [])]
                cat = map_subjects_to_faculty(subjects, existing_folders)
            if cat and title:
                reason = f"🏛️ ISBN {isbn} (OpenLibrary DDC-Klassifikation)"
                save_cached_identifier(isbn, "ISBN", cat, author_str, title, reason)
                return cat, author_str, title, reason

        # Negative cache only if a catalog actually answered (no caching on timeouts/offline)
        if gb_info is not None or dnb_info is not None or ol_info is not None:
            if not partial:
                save_cached_identifier(isbn, "ISBN", "NOT_FOUND", "", "", "Nicht im Katalog")

    return partial
