"""Academic Textbook Discovery & Monograph Search Service.
Queries Deutsche Nationalbibliothek (DNB), Google Books Volumes API, Crossref Books,
and OpenLibrary with parallel query execution, metadata normalization, and BibTeX/APA citation generation.
"""

import re
import ssl
import json
import time
import urllib.parse
import urllib.request
import concurrent.futures
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from ai.isbn_lookup import clean_catalog_title, DDC_MAP
from ai.categories import STANDARD_CATEGORIES, COMPILED_FACULTY_KNOWLEDGE
from core.library_db import get_institution_settings

_ssl_ctx = None
try:
    _ssl_ctx = ssl.create_default_context()
except Exception:
    _ssl_ctx = ssl._create_unverified_context()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CampusLibrary-TextbookHub/3.0"

BOOK_FACULTY_KEYWORDS: Dict[str, str] = {
    "Mathematik": "Mathematik Analysis Lineare Algebra Stochastik Differentialgleichungen",
    "Physik & Astronomie": "Experimentalphysik Theoretische Physik Quantenmechanik Astrophysik",
    "Chemie": "Organische Chemie Anorganische Chemie Biochemie Physikalische Chemie",
    "Biologie & Lebenswissenschaften": "Biologie Genetik Mikrobiologie Zellbiologie Ökologie",
    "Geowissenschaften & Geologie": "Geologie Geomorphologie Klimatologie Kartographie Mineralogie",
    "Informatik & Programmierung": "Informatik Algorithmen Softwaretechnik Datenstrukturen Rechnernetze",
    "Medizin & Pharmazie": "Anatomie Physiologie Innere Medizin Pharmakologie Neurologie",
    "Psychologie & Soziologie": "Allgemeine Psychologie Sozialpsychologie Klinische Psychologie Soziologie",
    "Wirtschaftswissenschaften": "Betriebswirtschaftslehre Volkswirtschaftslehre Rechnungswesen Mikroökonomie",
    "Rechtswissenschaften & Jura": "Bürgerliches Recht Strafrecht Öffentliches Recht Zivilrecht Europarecht",
    "Ingenieurwissenschaften & Technik": "Maschinenbau Elektrotechnik Technische Mechanik Werkstoffkunde",
    "Geschichte & Politik": "Deutsche Geschichte Neuere Geschichte Politikwissenschaft Internationale Beziehungen",
    "Philosophie & Religion": "Philosophie Ethik Erkenntnistheorie Logik Religionswissenschaft",
    "Pädagogik & Schule": "Schulpädagogik Allgemeine Didaktik Erziehungswissenschaft Förderpädagogik",
    "Sprach- & Literaturwissenschaft": "Germanistik Anglistik Linguistik Literaturgeschichte Sprachwissenschaft",
}


def infer_textbook_category(title: str, description: str = "", ddc: str = "") -> str:
    """Classifies a textbook into one of the 15 standard academic faculties."""
    if ddc:
        for prefix, cat in DDC_MAP.items():
            if ddc.startswith(prefix):
                return cat

    full_text = f"{title} {description}".lower()

    # Domain specific regex
    if re.search(r'\b(mathematik|algebra|analysis|stochastik|geometrie|differential|wahrscheinlichkeits)\b', full_text):
        return "Mathematik"
    if re.search(r'\b(physik|quanten|mechanik|thermodynam|astronomie|optik|relativit)\b', full_text):
        return "Physik & Astronomie"
    if re.search(r'\b(chemie|biochemie|molekül|anorganisch|organisch|katalyse)\b', full_text):
        return "Chemie"
    if re.search(r'\b(informatik|algorithmen|programmieren|python|java|rechnerarchitektur|software|datenbank|machine learning|ki|künstliche intelligenz)\b', full_text):
        return "Informatik & Programmierung"
    if re.search(r'\b(strafrecht|zivilrecht|bgb|jura|rechtswissenschaft|staatsrecht|verwaltungsrecht|europarecht|jurist)\b', full_text):
        return "Rechtswissenschaften & Jura"
    if re.search(r'\b(bwl|vwl|betriebswirtschaft|volkswirtschaft|management|marketing|controlling|bilanz|finanz)\b', full_text):
        return "Wirtschaftswissenschaften"
    if re.search(r'\b(medizin|anatomie|klinik|pharma|chirurgie|patholog|physiologie|neurologie|ärztlich)\b', full_text):
        return "Medizin & Pharmazie"
    if re.search(r'\b(psychologie|soziologie|kognitiv|verhalten|psychoanalyse|gesellschaft)\b', full_text):
        return "Psychologie & Soziologie"
    if re.search(r'\b(pädagogik|didaktik|erziehung|unterricht|schulbuch|lehrbuch|lehramt)\b', full_text):
        return "Pädagogik & Schule"
    if re.search(r'\b(geographie|geologie|erdkunde|klima|bodenkunde|kartographie)\b', full_text):
        return "Geowissenschaften & Geologie"
    if re.search(r'\b(geschichte|historisch|mittelalter|antike|politik|krieg|demokratie)\b', full_text):
        return "Geschichte & Politik"
    if re.search(r'\b(philosophie|ethik|metaphysik|kant|platon|aristoteles|theologie)\b', full_text):
        return "Philosophie & Religion"
    if re.search(r'\b(linguistik|germanistik|literatur|grammatik|semantik|romanistik|anglistik)\b', full_text):
        return "Sprach- & Literaturwissenschaft"
    if re.search(r'\b(ingenieur|maschinenbau|elektrotechnik|statik|werkstoff|mechatronik)\b', full_text):
        return "Ingenieurwissenschaften & Technik"
    if re.search(r'\b(biologie|botanik|zoologie|ökologie|mikrobiologie|zellbiologie)\b', full_text):
        return "Biologie & Lebenswissenschaften"

    return "Interdisziplinär & Lehrbuch"


def query_dnb_books(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Searches Deutsche Nationalbibliothek (DNB) SRU catalog for published textbooks."""
    results = []
    clean_q = re.sub(r'[\/\\:;,\(\)\[\]]', ' ', query).strip()
    if not clean_q:
        return []

    # Check if query is an ISBN
    isbn_clean = "".join(c for c in clean_q if c.isdigit())
    if len(isbn_clean) in (10, 13):
        sru_query = f"isbn={isbn_clean}"
    else:
        words = clean_q.split()[:4]
        safe_term = " and ".join(f'tit="{w}"' for w in words)
        sru_query = f"{safe_term} and mat=books"

    try:
        url = (
            f"https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve"
            f"&query={urllib.parse.quote(sru_query)}&recordSchema=oai_dc&maximumRecords={limit}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4.5, context=_ssl_ctx) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        ns = {"srw": "http://www.loc.gov/zing/srw/", "dc": "http://purl.org/dc/elements/1.1/"}
        records = root.findall(".//srw:recordData", ns)

        for rec in records:
            raw_t = rec.findtext(".//dc:title", default="", namespaces=ns)
            title = clean_catalog_title(raw_t)
            if not title or len(title) < 3:
                continue

            authors_list = [e.text.strip() for e in rec.findall(".//dc:creator", ns) if e.text]
            # Clean author bracket notations like "[Verfasser]"
            clean_authors = []
            for a in authors_list:
                a_clean = re.sub(r'\[.*?\]', '', a).strip()
                if "," in a_clean:
                    parts = a_clean.split(",", 1)
                    a_clean = f"{parts[1].strip()} {parts[0].strip()}"
                clean_authors.append(a_clean)
            authors_str = ", ".join(clean_authors[:3]) if clean_authors else "Unbekannt"

            publisher_text = rec.findtext(".//dc:publisher", default="", namespaces=ns)
            pub_clean = publisher_text.split(":")[-1].strip() if ":" in publisher_text else publisher_text

            date_text = rec.findtext(".//dc:date", default="", namespaces=ns)
            year = None
            if date_text:
                m_yr = re.search(r'\b(20\d\d|19\d\d)\b', date_text)
                if m_yr:
                    year = int(m_yr.group(1))

            identifiers = [e.text.strip() for e in rec.findall(".//dc:identifier", ns) if e.text]
            isbn = None
            doi = None
            for ident in identifiers:
                if "10." in ident and "doi.org" in ident:
                    doi = ident.split("doi.org/")[-1].strip()
                elif "10." in ident and not doi:
                    m_doi = re.search(r'\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b', ident)
                    if m_doi:
                        doi = m_doi.group(1)
                m_isbn = re.search(r'\b(97[89][-\s]?[0-9]{1,5}[-\s]?[0-9]+[-\s]?[0-9]+[-\s]?[0-9])\b', ident)
                if m_isbn and not isbn:
                    isbn = "".join(c for c in m_isbn.group(1) if c.isdigit())

            desc = rec.findtext(".//dc:description", default="", namespaces=ns)
            cat = infer_textbook_category(title, desc)

            cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg" if isbn else ""

            book_id = f"dnb_{isbn}" if isbn else f"dnb_{abs(hash(title))}"
            results.append({
                "id": book_id,
                "title": title,
                "authors": authors_str,
                "publisher": pub_clean or "Akademischer Verlag",
                "year": year or 2023,
                "isbn": isbn or "",
                "doi": doi or "",
                "description": desc or f"Akademisches Fachbuch verzeichnet im Katalog der Deutschen Nationalbibliothek ({pub_clean or 'DNB'}).",
                "category": cat,
                "cover_url": cover_url,
                "preview_url": f"https://d-nb.info/{isbn}" if isbn else f"https://portal.dnb.de/opac.htm?query={urllib.parse.quote(title)}",
                "source": "Deutsche Nationalbibliothek (DNB)",
                "citation_count": 0,
            })
    except Exception:
        pass

    return results


def query_google_books_textbooks(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Queries Google Books for academic textbooks."""
    results = []
    clean_q = re.sub(r'[\/\\:;,\(\)\[\]]', ' ', query).strip()
    if not clean_q:
        return []

    # Check for ISBN
    isbn_clean = "".join(c for c in clean_q if c.isdigit())
    if len(isbn_clean) in (10, 13):
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn_clean}&maxResults={limit}"
    else:
        words = clean_q.split()[:5]
        q_term = " ".join(words)
        url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(q_term)}&printType=books&maxResults={limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4.5, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        items = data.get("items", [])
        for item in items:
            v = item.get("volumeInfo", {})
            raw_t = v.get("title", "")
            if not raw_t:
                continue
            sub_t = v.get("subtitle", "")
            clean_t = clean_catalog_title(raw_t)
            if sub_t and sub_t.lower() not in clean_t.lower():
                clean_t = f"{clean_t} - {clean_catalog_title(sub_t)}"

            authors = ", ".join(v.get("authors", [])) if v.get("authors") else "Unbekannt"
            publisher = v.get("publisher", "Springer / Wiley / De Gruyter")
            desc = v.get("description", "")

            date_str = v.get("publishedDate", "")
            year = None
            if date_str:
                m_yr = re.search(r'\b(20\d\d|19\d\d)\b', date_str)
                if m_yr:
                    year = int(m_yr.group(1))

            isbn = ""
            for ident in v.get("industryIdentifiers", []):
                t_val = ident.get("type", "")
                i_val = ident.get("identifier", "")
                if "13" in t_val:
                    isbn = i_val
                    break
                elif "10" in t_val and not isbn:
                    isbn = i_val

            cover_img = v.get("imageLinks", {}).get("thumbnail") or v.get("imageLinks", {}).get("smallThumbnail") or ""
            if cover_img and cover_img.startswith("http://"):
                cover_img = "https://" + cover_img[7:]

            cat = infer_textbook_category(clean_t, desc)
            bid = item.get("id") or f"gb_{isbn}" if isbn else f"gb_{abs(hash(clean_t))}"

            results.append({
                "id": bid,
                "title": clean_t,
                "authors": authors,
                "publisher": publisher,
                "year": year or 2022,
                "isbn": isbn,
                "doi": "",
                "description": desc or f"Standard-Fachbuch für Hochschulen und Universitäten ({publisher}).",
                "category": cat,
                "cover_url": cover_img,
                "preview_url": v.get("previewLink") or v.get("infoLink") or f"https://books.google.de/books?id={bid}",
                "page_count": v.get("pageCount", 0),
                "source": "Google Books",
                "citation_count": 0,
            })
    except Exception:
        pass

    return results


def query_crossref_books(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Queries Crossref Works API specifically filtered for scholarly monographs & books (type:book)."""
    results = []
    clean_q = re.sub(r'[\/\\:;,\(\)\[\]]', ' ', query).strip()
    if not clean_q:
        return []

    words = clean_q.split()[:5]
    q_str = " ".join(words)
    url = f"https://api.crossref.org/works?query.bibliographic={urllib.parse.quote(q_str)}&filter=type:book&rows={limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CampusLibrary/2.0 (mailto:info@campus-library.de)"})
        with urllib.request.urlopen(req, timeout=4.5, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        items = data.get("message", {}).get("items", [])
        for item in items:
            titles = item.get("title", [])
            if not titles:
                continue
            raw_t = titles[0]
            clean_t = clean_catalog_title(raw_t)

            authors_list = []
            for a in item.get("author", []):
                given = a.get("given", "").strip()
                family = a.get("family", "").strip()
                if given and family:
                    authors_list.append(f"{given} {family}")
                elif family:
                    authors_list.append(family)
            authors_str = ", ".join(authors_list[:3]) if authors_list else "Unbekannt"

            publisher = item.get("publisher", "Springer Nature / Elsevier / Wiley")
            doi = item.get("DOI", "")

            isbns = item.get("ISBN", [])
            isbn = isbns[0] if isbns else ""

            # Publication year
            year = None
            date_parts = item.get("published-print", {}).get("date-parts") or item.get("created", {}).get("date-parts")
            if date_parts and date_parts[0]:
                year = date_parts[0][0]

            cat = infer_textbook_category(clean_t, "")
            cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg" if isbn else ""

            results.append({
                "id": f"cr_{doi}" if doi else f"cr_{abs(hash(clean_t))}",
                "title": clean_t,
                "authors": authors_str,
                "publisher": publisher,
                "year": year or 2023,
                "isbn": isbn,
                "doi": doi,
                "description": f"Begutachtetes wissenschaftliches Fachbuch & Monographie ({publisher}). DOI: {doi}",
                "category": cat,
                "cover_url": cover_url,
                "preview_url": f"https://doi.org/{doi}" if doi else "",
                "source": "Crossref Scholarly Books",
                "citation_count": item.get("is-referenced-by-count", 0),
            })
    except Exception:
        pass

    return results


def query_openlibrary_books(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Queries OpenLibrary Search API for academic monographs and textbooks with fields filtering."""
    results = []
    clean_q = re.sub(r'[\/\\:;,\(\)\[\]]', ' ', query).strip()
    if not clean_q:
        return []

    words = clean_q.split()[:5]
    q_str = " ".join(words)
    url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(q_str)}&fields=title,subtitle,author_name,first_publish_year,isbn,publisher,cover_i,key,number_of_pages_median&limit={limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5.0, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        docs = data.get("docs", [])
        for doc in docs:
            raw_t = doc.get("title", "")
            if not raw_t:
                continue
            sub_t = doc.get("subtitle", "")
            clean_t = clean_catalog_title(raw_t)
            if sub_t and sub_t.lower() not in clean_t.lower():
                clean_t = f"{clean_t} - {clean_catalog_title(sub_t)}"

            authors_list = doc.get("author_name", [])
            authors_str = ", ".join(authors_list[:3]) if authors_list else "Unbekannt"

            pub_list = doc.get("publisher", [])
            publisher = pub_list[0] if pub_list else "Akademischer Verlag"

            year = doc.get("first_publish_year")

            isbn_list = doc.get("isbn", [])
            isbn = ""
            if isbn_list:
                # Prefer 13-digit ISBN
                for isb in isbn_list:
                    if len(isb) == 13:
                        isbn = isb
                        break
                if not isbn and isbn_list:
                    isbn = isbn_list[0]

            cover_i = doc.get("cover_i")
            cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else (f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg" if isbn else "")
            pages = doc.get("number_of_pages_median", 0)
            work_key = doc.get("key", "")

            cat = infer_textbook_category(clean_t, "")
            bid = f"ol_{isbn}" if isbn else f"ol_{abs(hash(clean_t))}"

            results.append({
                "id": bid,
                "title": clean_t,
                "authors": authors_str,
                "publisher": publisher,
                "year": year or 2022,
                "isbn": isbn,
                "doi": "",
                "description": f"Akademisches Fachbuch im Verzeichnis der Open Library ({publisher}).",
                "category": cat,
                "cover_url": cover_url,
                "preview_url": f"https://openlibrary.org{work_key}" if work_key else f"https://openlibrary.org/search?q={urllib.parse.quote(clean_t)}",
                "page_count": pages,
                "source": "Open Library",
                "citation_count": 0,
            })
    except Exception:
        pass

    return results


def search_all_textbooks(
    query: str,
    faculty_filter: Optional[str] = None,
    limit_per_source: int = 35,
    max_results: Optional[int] = 80,
) -> List[Dict[str, Any]]:
    """Runs high-performance parallel federated queries against DNB, Crossref, OpenLibrary, and Google Books."""
    if not query or not query.strip():
        return []

    per_source = max(25, (max_results or 80) // 2)

    combined_results: List[Dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f_dnb = executor.submit(query_dnb_books, query, per_source)
        f_cr = executor.submit(query_crossref_books, query, per_source)
        f_ol = executor.submit(query_openlibrary_books, query, per_source)
        f_gb = executor.submit(query_google_books_textbooks, query, per_source)

        for fut in (f_dnb, f_cr, f_ol, f_gb):
            try:
                res = fut.result(timeout=6.5)
                if res:
                    combined_results.extend(res)
            except Exception:
                pass

    # Deduplicate by normalized title
    seen_titles = set()
    unique_books: List[Dict[str, Any]] = []

    for b in combined_results:
        norm_t = re.sub(r'[^a-zA-Z0-9äöüÄÖÜß]', '', b.get("title", "").lower())
        if not norm_t or len(norm_t) < 4:
            continue
        if norm_t in seen_titles:
            continue
        seen_titles.add(norm_t)

        # Apply faculty filter if specified
        if faculty_filter and faculty_filter != "Alle":
            if b.get("category") != faculty_filter:
                continue

        unique_books.append(b)

    # Sort prioritized: books with ISBN, DOI and citations first
    unique_books.sort(key=lambda x: (
        1 if x.get("isbn") else 0,
        1 if x.get("doi") else 0,
        x.get("citation_count", 0),
        x.get("year", 0)
    ), reverse=True)

    if max_results and max_results > 0:
        return unique_books[:max_results]
    return unique_books


def build_textbook_institution_url(book: Dict[str, Any]) -> str:
    """Constructs the EZProxy university link for accessing the textbook through the institution license."""
    cfg = get_institution_settings()
    prefix = cfg.get("ezproxy_prefix", "https://login.ub-proxy.fernuni-hagen.de/login?url=")
    doi = book.get("doi")
    isbn = book.get("isbn")

    if doi:
        clean_doi = doi.replace("https://doi.org/", "").strip()
        target = f"https://doi.org/{clean_doi}"
    elif isbn:
        clean_isbn = "".join(c for c in isbn if c.isdigit())
        target = f"https://search.ebscohost.com/login.aspx?direct=true&bquery=IS+{clean_isbn}"
    else:
        target = book.get("preview_url") or f"https://scholar.google.de/scholar?q={urllib.parse.quote(book.get('title', ''))}"

    return f"{prefix}{urllib.parse.quote(target)}"


def generate_textbook_apa7(book: Dict[str, Any]) -> str:
    """Generates standard APA 7th edition reference citation for the textbook."""
    authors = book.get("authors") or "Autor unbekannt"
    year = book.get("year") or "o. D."
    title = book.get("title", "")
    publisher = book.get("publisher") or "Verlag"
    doi = book.get("doi")
    isbn = book.get("isbn")

    doi_part = f" https://doi.org/{doi}" if doi else ""
    return f"{authors} ({year}). {title}. {publisher}.{doi_part}"


def generate_textbook_bibtex(book: Dict[str, Any]) -> str:
    """Generates standard BibTeX citation entry (@book)."""
    authors = book.get("authors") or "Anonymous"
    title = book.get("title") or "Untitled Book"
    year = book.get("year") or 2023
    publisher = book.get("publisher") or "Academic Publisher"
    doi = book.get("doi") or ""
    isbn = book.get("isbn") or ""

    # Citekey: FirstAuthorYear
    first_author_clean = re.sub(r'[^a-zA-Z]', '', authors.split(",")[0].split()[-1] if authors else "Book")
    cite_key = f"{first_author_clean.lower()}{year}"

    bib = f"""@book{{{cite_key},
  author    = {{{authors}}},
  title     = {{{title}}},
  publisher = {{{publisher}}},
  year      = {{{year}}}"""

    if isbn:
        bib += f",\n  isbn      = {{{isbn}}}"
    if doi:
        bib += f",\n  doi       = {{{doi}}}"

    bib += "\n}"
    return bib
