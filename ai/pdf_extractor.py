"""Smart ultra-fast PDF text, TOC, and metadata extraction.
Uses PyMuPDF (fitz) for C-accelerated instant parsing (<5ms) with graceful fallback to pypdf.
Extracts bookmarks, embedded XMP metadata, DOI, ISBN, and chapter titles.
"""

import os
import re
from typing import List, Optional, Tuple

# Attempt to load C-accelerated PyMuPDF engine
_HAS_FITZ = False
try:
    import pymupdf as fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    try:
        import fitz
        _HAS_FITZ = True
    except ImportError:
        _HAS_FITZ = False

from pypdf import PdfReader


import threading

# Semaphore to strictly serialize PDF file reads and prevent choking cloud streaming providers (Google Drive / OneDrive)
_PDF_IO_SEMAPHORE = threading.Semaphore(1)


SERIES_OR_GENRE_KEYWORDS = {
    "kompakt", "vorkurs", "masterclass", "springer-lehrbuch", "springer", "spektrum",
    "lehrbuch", "studienbuch", "studium", "basiswissen", "prüfungswissen", "prüfungs-repetitorium",
    "repetitorium", "leitfaden", "skript", "vorlesung", "kurs", "grundkurs", "aufbaukurs",
    "handbuch", "taschenbuch", "lehr- und übungsbuch", "übungsbuch",
    "arbeitsbuch", "fallstudien", "edition", "mitteilung", "reihe", "band", "teil",
    "gesamtausgabe", "de gruyter", "pearson", "wiley", "oldenbourg", "vieweg", "hanser", "utb"
}

GENERIC_SECTION_TITLES = {
    "cover", "titelseite", "titelei", "vorsatz", "inhaltsverzeichnis", "inhalt", "contents",
    "table of contents", "vorwort", "preface", "foreword", "geleitwort", "geleitwort des herausgebers",
    "impressum", "gehe zu", "seite", "kapitel", "chapter", "abkürzungen", "abkürzungsverzeichnis",
    "siglen", "siglenverzeichnis", "editorische hinweise", "anmerkungen", "danksagung",
    "acknowledgments", "literatur", "literaturverzeichnis", "bibliografie", "register",
    "sachregister", "personenregister", "namenregister", "index", "glossar"
}


def sanitize_author_string(author: str) -> str:
    """Strips roles, brackets, and decorative symbols/emojis from author names."""
    if not author:
        return ""
    # Strip roles
    cleaned = re.sub(
        r'\[?\s*(?:Illustrator(?:in)?|Grafik(?:er)?|Redaktion|Red\.|Hrsg\.|Herausgeber|Fotograf(?:in)?|Bearb\.|Bearbeiter|Mitarb\.|Mitarbeiter)\s*\]?',
        '', author, flags=re.IGNORECASE
    )
    # Strip emojis and decorative symbols (hearts, stars, dingbats)
    cleaned = re.sub(r'[\u2600-\u27bf\U0001f300-\U0001f9ff♥★✦◆■▲●]+', '', cleaned)
    # Clean brackets and whitespace
    cleaned = re.sub(r'[{}\[\]\(\)]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(" ,.-_/;:")
    return cleaned


def extract_visual_title_and_author(doc) -> Tuple[Optional[str], Optional[str]]:
    """Inspects front-matter text spans and blocks with typographic font-size weighting
    to reliably separate book series/courses, actual titles, and genuine author names.
    """
    total_pages = len(doc)
    found_title = None
    found_author = None

    # Step 1: Check embedded metadata first if available
    try:
        meta = doc.metadata or {}
        raw_meta_author = str(meta.get("author") or "").replace('\x00', '').strip()
        raw_meta_title = str(meta.get("title") or "").replace('\x00', '').strip()

        # Sanitize metadata author
        if raw_meta_author:
            clean_m_auth = sanitize_author_string(raw_meta_author)
            if clean_m_auth.lower() not in ('sjoerg', 'admin', 'user', 'author', 'scan', 'root', 'unknown', 'alin.cason', 'fk') and len(clean_m_auth) >= 3:
                # Discard if it looks like software, filename or series
                if not re.search(r'\.(?:indd|indb|qxd|doc|docx|pdf)$', clean_m_auth, re.I) and not any(kw in clean_m_auth.lower() for kw in SERIES_OR_GENRE_KEYWORDS):
                    found_author = clean_m_auth

        # Sanitize metadata title
        if raw_meta_title and len(raw_meta_title) >= 4:
            is_bad_m_title = (
                bool(re.search(r'\.(?:indd|indb|qxd|qxp|doc|docx|tex|rtf|pdf|pmd)$', raw_meta_title, re.I))
                or bool(re.match(r'^(?:97[89]\d{10}|\d{9}[\dX]|\d{10,13})$', raw_meta_title))
                or any(j in raw_meta_title.lower() for j in ["titelei", "frontmatter", "cover", "impressum", "unbenannt", "untitled", "microsoft word"])
            )
            if not is_bad_m_title:
                found_title = raw_meta_title
    except Exception:
        pass

    # Helper to check if a string is purely a generic section header
    def is_generic_section(text_val: str) -> bool:
        norm = re.sub(r'[^a-z0-9äöüß ]+', ' ', text_val.lower()).strip()
        if norm in GENERIC_SECTION_TITLES:
            return True
        for sec in GENERIC_SECTION_TITLES:
            if norm == sec or norm.startswith(sec + " ") or norm.endswith(" " + sec):
                return True
        return False

    # Helper to check if a string is a series/course name rather than a person
    def is_series_or_course(text_val: str) -> bool:
        low = text_val.lower()
        return any(kw in low for kw in SERIES_OR_GENRE_KEYWORDS)

    # Helper to check if a string looks like a person's name
    def is_person_name(text_val: str) -> bool:
        if is_series_or_course(text_val) or is_generic_section(text_val):
            return False
        words = text_val.split()
        if not (2 <= len(words) <= 5):
            return False
        # Every word must consist purely of alphabetic characters (including German umlauts)
        for w in words:
            if not re.match(r'^[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?$', w):
                return False
        return True

    # Step 2: Front-matter visual inspection (Check up to first 6 pages for title page)
    candidate_titles_by_size = []
    candidate_authors = []

    for p_no in range(min(6, total_pages)):
        try:
            page = doc[p_no]
            page_dict = page.get_text("dict")
            text_lines = []

            for b in page_dict.get("blocks", []):
                if b.get("type") != 0:  # text block only
                    continue
                for l in b.get("lines", []):
                    line_spans = l.get("spans", [])
                    if not line_spans:
                        continue
                    line_text = "".join(s.get("text", "") for s in line_spans).strip()
                    if not line_text:
                        continue
                    max_size = max(s.get("size", 10.0) for s in line_spans)
                    text_lines.append((line_text, max_size, b.get("bbox", (0, 0, 0, 0))))

            if not text_lines:
                continue

            # Filter junk lines
            valid_lines = []
            for lt, sz, bbox in text_lines:
                cand = re.sub(r'\s+', ' ', lt).strip()
                if not (3 <= len(cand) <= 120):
                    continue
                if any(k in cand.lower() for k in [
                    "http", "doi:", "isbn", "copyright", "©", "urheberrecht",
                    "alle rechte", "gespeichert", "ip ", "download", "druck:",
                    "satz:", "verlag", "bibliografische", "open-access", "for personal use",
                    "all rights reserved", "gesamtausgabe"
                ]):
                    continue
                if is_generic_section(cand):
                    continue
                if re.match(r'^\d+$', cand) or re.search(r'\.(?:indd|indb|qxd|doc|docx|pdf)$', cand, re.I):
                    continue
                valid_lines.append((cand, sz, bbox))

            if not valid_lines:
                continue

            # Group adjacent lines with similar font sizes
            grouped_candidates = []
            curr_text = valid_lines[0][0]
            curr_size = valid_lines[0][1]

            for next_txt, next_sz, _ in valid_lines[1:]:
                if abs(curr_size - next_sz) <= max(curr_size, next_sz) * 0.15 and len(curr_text) + len(next_txt) < 110:
                    curr_text += " " + next_txt
                else:
                    grouped_candidates.append((curr_text.strip(), curr_size))
                    curr_text = next_txt
                    curr_size = next_sz
            if curr_text:
                grouped_candidates.append((curr_text.strip(), curr_size))

            # Find title candidates on this page
            page_title_cands = []
            for c in grouped_candidates:
                cand_text = c[0]
                if is_series_or_course(cand_text) or is_generic_section(cand_text):
                    continue
                if any(cand_text.lower().startswith(x) for x in ["prof.", "dr.", "von "]):
                    continue
                # Reject candidate if it contains edition/editor indicators (e.g. "Hrsg.", "3. Auflage")
                if re.search(r'\b(?:hrsg\.?|herausgeber|auflage|edition|bearb\.?|mitarb\.?)\b', cand_text, re.I):
                    continue
                # Reject if candidate is just person names (e.g. "Rolf Arnold Antonius Lipsmeier Matthias Rohs")
                if is_person_name(cand_text):
                    continue
                words = cand_text.split()
                if 2 <= len(words) <= 6 and all(is_person_name(w) or re.match(r'^[A-ZÄÖÜ][a-zäöüß]+$', w) for w in words):
                    # Likely a list of full author names without commas
                    if len(words) >= 4 and len(words) % 2 == 0:
                        continue
                if len(cand_text) >= 4:
                    page_title_cands.append(c)

            for cand_txt, sz in page_title_cands:
                clean_cand = cand_txt.replace("●", "-").strip()
                candidate_titles_by_size.append((clean_cand, sz, p_no))

            # Find author candidates on this page
            for cand_text, cand_sz in grouped_candidates:
                if is_series_or_course(cand_text) or is_generic_section(cand_text):
                    continue
                cleaned_author_cand = re.sub(r'^(?:von|by|autor(?:en)?|author(?:s)?)\s*:\s*', '', cand_text, flags=re.I).strip()
                cleaned_author_cand = sanitize_author_string(cleaned_author_cand)
                if is_person_name(cleaned_author_cand):
                    candidate_authors.append((cleaned_author_cand, cand_sz, p_no))

        except Exception:
            pass

    # Select best title from visual scan if not found via metadata
    best_title_page = -1
    if not found_title and candidate_titles_by_size:
        # Prioritize largest font size, tie-breaker: earlier page
        candidate_titles_by_size.sort(key=lambda x: (x[1], -x[2]), reverse=True)
        found_title = candidate_titles_by_size[0][0]
        best_title_page = candidate_titles_by_size[0][2]

    # Select author from visual scan if not found via metadata
    if not found_author and candidate_authors:
        # Filter candidate authors that match title
        valid_authors = [
            a for a in candidate_authors
            if not found_title or a[0].lower() not in found_title.lower()
        ]
        if valid_authors:
            # Prefer author appearing on the same page as the detected title
            same_page_authors = [a for a in valid_authors if a[2] == best_title_page]
            if same_page_authors:
                same_page_authors.sort(key=lambda x: x[1], reverse=True)
                found_author = same_page_authors[0][0]
            else:
                valid_authors.sort(key=lambda x: x[1], reverse=True)
                found_author = valid_authors[0][0]

    # Step 3: Bookmarks / TOC Fallback if title still not found
    if not found_title:
        try:
            toc = doc.get_toc()
            if toc:
                for lvl, t, p in toc[:8]:
                    clean_t = t.strip('\x00 \t\r\n')
                    if clean_t and not is_generic_section(clean_t):
                        # Reject plain standalone chapter headings or page markers
                        if 4 <= len(clean_t) <= 85 and not re.search(r'^\d+\.?\s*$', clean_t):
                            clean_t = re.sub(r'^\[.*?\]\s*;\s*', '', clean_t).strip()
                            found_title = clean_t
                            break
        except Exception:
            pass

    return found_title, found_author


def _extract_with_fitz(file_path: str) -> Optional[str]:
    """C-accelerated PDF parser using PyMuPDF (fitz).
    Optimized for cloud-streamed drives (Google Drive / OneDrive):
    Reads only metadata and page 0, early-exiting immediately to prevent downloading the full book.
    """
    with _PDF_IO_SEMAPHORE:
        doc = None
        try:
            doc = fitz.open(file_path)
            extracted_chunks: List[str] = []
            total_pages = len(doc)
            if total_pages == 0:
                return None

            # 1. Embedded PDF Metadata (with strict junk filter & visual fallback)
            meta_items = []
            meta = doc.metadata or {}
            raw_title = str(meta.get("title") or "").replace('\x00', '').strip()
            raw_author = str(meta.get("author") or "").replace('\x00', '').strip()
            if raw_author:
                raw_author = sanitize_author_string(raw_author)
                if raw_author.lower() in ('sjoerg', 'admin', 'user', 'author', 'scan', 'root', 'unknown', 'alin.cason', 'fk'):
                    raw_author = ""

            is_junk_title = (
                not raw_title
                or len(raw_title) < 4
                or bool(re.search(r'\.(?:indd|indb|qxd|qxp|doc|docx|tex|rtf|pdf|pmd)$', raw_title, re.IGNORECASE))
                or bool(re.match(r'^(?:97[89]\d{10}|\d{9}[\dX]|\d{10,13})$', raw_title))
                or any(j in raw_title.lower() for j in [
                    "titelei", "frontmatter", "cover", "impressum", "unbenannt", "untitled",
                    "microsoft word", "adobe indesign", "quarkxpress", "satz", "druck", "layout"
                ])
                or bool(re.match(r'^[A-Z0-9_\-]{6,20}$', raw_title))
                or bool(re.match(r'^(?:\+?\d+_|pub_|cr_|mb_|book_)[0-9a-z_]+', raw_title, re.IGNORECASE))
            )

            vis_title, vis_author = None, None
            if is_junk_title or not raw_author:
                vis_title, vis_author = extract_visual_title_and_author(doc)

            final_title = raw_title if not is_junk_title else (vis_title or "")
            final_author = raw_author or vis_author or ""

            if final_title:
                meta_items.append(f"Titel: {final_title}")
            if final_author:
                meta_items.append(f"Autor: {final_author}")
            if meta.get("subject"):
                meta_items.append(f"Subject: {meta['subject']}")
            if meta.get("keywords"):
                meta_items.append(f"Keywords: {meta['keywords']}")

            if meta_items:
                extracted_chunks.append("--- METADATEN ---\n" + "\n".join(meta_items))

            # 2. Fast scan of up to 5 pages for title, author, and ISBN/DOI
            max_pages = min(5, total_pages)
            for page_idx in range(max_pages):
                try:
                    p_text = doc[page_idx].get_text("text").replace('\x00', '').strip()
                    if p_text:
                        extracted_chunks.append(f"[Seite {page_idx + 1}]\n{p_text[:1200]}")
                        # Early-exit immediately if ISBN or DOI is found
                        has_isbn = bool(re.search(r'(?:ISBN(?:-1[03])?:?\s*)(97[89][-\s0-9]{10,20}|[0-9X-]{10,17})', p_text, re.IGNORECASE))
                        has_doi = bool(re.search(r'10\.\d{4,9}/', p_text))
                        if has_isbn or has_doi:
                            break
                except Exception:
                    pass

            combined = "\n\n".join(extracted_chunks)
            return combined[:4000] if combined else None
        except Exception:
            return None
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass



def _extract_with_pypdf(file_path: str) -> str:
    """Pure-Python fallback parser using pypdf."""
    extracted_chunks: List[str] = []
    try:
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        has_bookmarks = False

        # Bookmarks
        try:
            outline = reader.outline
            if outline:
                toc_titles = []
                junk = ["titelei", "frontmatter", "vorspann", "cover", "impressum", "inhaltsverzeichnis"]

                def parse_outline(items, depth=0):
                    if depth > 2 or len(toc_titles) >= 20:
                        return
                    for item in items:
                        if len(toc_titles) >= 20:
                            break
                        if isinstance(item, list):
                            parse_outline(item, depth + 1)
                        elif hasattr(item, "title") and item.title:
                            t = str(item.title).strip()
                            if t and len(t) > 2 and not any(j in t.lower() for j in junk):
                                toc_titles.append(f"- {t}")

                parse_outline(outline)
                if toc_titles:
                    has_bookmarks = True
                    extracted_chunks.append("--- INHALTSVERZEICHNIS (Kapitel) ---\n" + "\n".join(toc_titles[:15]))
        except Exception:
            pass

        # Page 1
        if total_pages > 0:
            try:
                p1_text = reader.pages[0].extract_text()
                if p1_text and p1_text.strip():
                    extracted_chunks.append(f"--- Seite 1 ---\n{p1_text.strip()[:800]}")
            except Exception:
                pass

        # TOC Scan
        if not has_bookmarks and total_pages > 1:
            toc_keywords = ["inhaltsverzeichnis", "inhalt", "contents", "table of contents"]
            pages_to_check = min(6, total_pages)
            for page_idx in range(1, pages_to_check):
                try:
                    p_text = reader.pages[page_idx].extract_text()
                    if p_text:
                        p_lower = p_text[:200].lower()
                        if any(kw in p_lower for kw in toc_keywords):
                            extracted_chunks.append(f"--- INHALT (Seite {page_idx + 1}) ---\n{p_text.strip()[:1000]}")
                            break
                        elif page_idx == 1:
                            extracted_chunks.append(f"--- Seite 2 ---\n{p_text.strip()[:600]}")
                except Exception:
                    continue

        if reader.metadata:
            meta = []
            if reader.metadata.title:
                meta.append(f"Titel: {reader.metadata.title}")
            if reader.metadata.author:
                meta.append(f"Autor: {reader.metadata.author}")
            if meta:
                extracted_chunks.insert(0, "--- METADATEN ---\n" + "\n".join(meta))

    except Exception as e:
        return f"Metadaten-Fallback ({str(e)})"

    combined = "\n\n".join(extracted_chunks)
    return combined[:3000] if combined else "Kein lesbarer Text."


def extract_pdf_preview_text(file_path: str) -> str:
    """High-speed PDF text and TOC extractor.
    Uses PyMuPDF (fitz) if installed for ultra-fast C execution (~3ms),
    falling back seamlessly to pypdf.
    """
    if _HAS_FITZ:
        res = _extract_with_fitz(file_path)
        if res:
            return res

    return _extract_with_pypdf(file_path)


def extract_publication_year(
    text: str = "",
    metadata: Optional[dict] = None,
    filename: str = "",
) -> Optional[int]:
    """Extracts the genuine publication/copyright year of a book.
    Prioritizes copyright notices, imprint edition lines, metadata timestamps, and filename cues.
    """
    import datetime
    current_year = datetime.date.today().year + 1

    # 1. Direct copyright notice (e.g. © 2021, Copyright 2018, (c) 2015, or "© Springer-Verlag ... 2014, 2026")
    if text:
        cp_years = []
        for m in re.finditer(r'(?:©|copyright|\(c\))[^\n\r]{0,160}', text, re.I):
            for ym in re.finditer(r'\b([12]\d{3})\b', m.group(0)):
                try:
                    y = int(ym.group(1))
                    if 1900 <= y <= current_year:
                        cp_years.append(y)
                except (ValueError, TypeError):
                    continue
        if cp_years:
            return max(cp_years)

        # 2. Edition notice with year (e.g. '4. Auflage 2020', '2., vollständig überarbeitete Auflage 2023')
        ed_years = []
        for m in re.finditer(
            r'(?:\b\d{1,2}\.?\s*(?:,\s*)?(?:[\wäöüß\-\.]+\s+){0,4}Aufl(?:age)?|\b\d{1,2}(?:st|nd|rd|th)\s+Edition|\bEdition)\s*[,.:;\-\s]*([12]\d{3})\b',
            text,
            re.I,
        ):
            try:
                y = int(m.group(1))
                if 1900 <= y <= current_year:
                    ed_years.append(y)
            except (ValueError, TypeError):
                continue
        if ed_years:
            return max(ed_years)

        # 3. Imprint keywords / Publishing houses (up to 110 chars after publisher name)
        pub_years = []
        for m in re.finditer(
            r'(?:erscheinungsjahr|veröffentlicht|gedruckt|printed|published|springer(?:\s+nature|\s+spektrum|\s+gabler|\s+vieweg|\s+fachmedien)?|hanser|pearson|wiley|thieme|de gruyter|c\.?\s*h\.?\s*beck|hogrefe|kohlhammer|nomos|utb|vahlen|vieweg|rowohlt|suhrkamp|campus|schubert|cornelsen|klett|westermann|oldenbourg|metzler|transcript|reclam|dtv|cambridge|oxford|routledge|elsevier|macmillan|münchen|berlin|heidelberg|wiesbaden|stuttgart|leipzig|frankfurt|köln|göttingen|weinheim|darmstadt|bonn)[^\n\r]{0,110}?\b([12]\d{3})\b',
            text,
            re.I,
        ):
            try:
                y = int(m.group(1))
                if 1950 <= y <= current_year:
                    pub_years.append(y)
            except (ValueError, TypeError):
                continue
        if pub_years:
            return max(pub_years)

        # 4. Preface / Imprint Date Line (e.g. "Aachen, im März 2016", "Dezember 2021")
        date_years = []
        for m in re.finditer(
            r'\b(?:Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|January|February|March|May|June|July|October|December|Frühjahr|Herbst|Sommer|Winter)\s+([12]\d{3})\b',
            text,
            re.I,
        ):
            try:
                y = int(m.group(1))
                if 1960 <= y <= current_year:
                    date_years.append(y)
            except (ValueError, TypeError):
                continue
        if date_years:
            return max(date_years)

    # 4. Embedded PDF Metadata (CreationDate / ModDate)
    if metadata:
        for k in ("creationDate", "modDate", "CreationDate", "ModDate"):
            raw_val = str(metadata.get(k) or "")
            if raw_val:
                ym = re.search(r'(?:19[7-9]\d|20[0-2]\d)', raw_val)
                if ym:
                    try:
                        y = int(ym.group(0))
                        if 1970 <= y <= current_year:
                            return y
                    except (ValueError, TypeError):
                        pass

    # 5. Filename cue (e.g. "Buch_Titel (2019).pdf" or "Autor - Titel - 2021.pdf")
    if filename:
        fn_matches = re.findall(r'[\(\[\s_-](19\d{2}|20\d{2})[\)\]\s_.-]', filename)
        if fn_matches:
            try:
                y = int(fn_matches[-1])
                if 1950 <= y <= current_year:
                    return y
            except (ValueError, TypeError):
                pass

    return None


def _extract_printed_toc(doc) -> List[Tuple[int, str, int, int]]:
    """Heuristic fallback parser: Extracts chapters and page numbers directly from printed
    Table of Contents (Inhaltsverzeichnis) pages when no digital PDF bookmarks exist.
    Returns: list of (level, chapter_title, target_pdf_page_1_indexed, printed_page_number)
    """
    total_len = len(doc)
    if total_len == 0:
        return []

    # 1. Locate start of printed table of contents:
    # Scan front-matter (first 40 pages) and back-matter (last 16 pages)
    # Check both line headers and block texts for standard and non-standard layouts
    toc_pages = []
    max_scan_front = min(40, total_len)
    for p_no in range(max_scan_front):
        try:
            matched = False
            # Check line starts
            txt = doc[p_no].get_text("text")
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            for l in lines[:10]:
                low = l.lower()
                if any(k in low for k in ["inhaltsverzeichnis", "inhaltsübersicht", "table of contents"]) and len(l) <= 45:
                    toc_pages.append(p_no)
                    matched = True
                    break
                if low in ["inhalt", "contents"]:
                    toc_pages.append(p_no)
                    matched = True
                    break

            # If not matched by first 10 lines, inspect blocks (e.g. Head-First / O'Reilly layout)
            if not matched:
                for b in doc[p_no].get_text("blocks"):
                    b_txt = b[4].strip()
                    low_b = b_txt.lower()
                    if any(k in low_b for k in ["inhaltsverzeichnis", "inhaltsübersicht", "table of contents"]) and len(b_txt) <= 60:
                        toc_pages.append(p_no)
                        matched = True
                        break
                    if low_b in ["inhalt", "contents"]:
                        toc_pages.append(p_no)
                        matched = True
                        break

            if matched:
                break
        except Exception:
            pass

    # If not found in front-matter, check back-matter (e.g. Suhrkamp, French/Italian literature layout)
    if not toc_pages and total_len > 15:
        for p_no in range(total_len - 1, max(total_len - 16, 0), -1):
            try:
                matched = False
                for b in doc[p_no].get_text("blocks"):
                    b_txt = b[4].strip()
                    low_b = b_txt.lower()
                    if any(k in low_b for k in ["inhaltsverzeichnis", "inhaltsübersicht", "table of contents"]) and len(b_txt) <= 60:
                        toc_pages.append(p_no)
                        matched = True
                        break
                    if low_b in ["inhalt", "contents"]:
                        toc_pages.append(p_no)
                        matched = True
                        break
                if matched:
                    break
            except Exception:
                pass

    if not toc_pages:
        return []

    # 2. Gather contiguous TOC pages
    first_p = toc_pages[0]
    scan_range = [first_p]
    for p in range(first_p + 1, min(first_p + 20, total_len)):
        try:
            text = doc[p].get_text("text")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            header_lines = " ".join(lines[:4]).lower()
            is_toc_heading = any(k in header_lines for k in ["inhaltsverzeichnis", "inhaltsübersicht", "inhalt", "contents"])
            has_leaders = (
                len(re.findall(r'(?:\.{2,}|\. \. \.|\t+)\s*\d+\s*$', text, re.MULTILINE)) >= 3
                or "...." in text
                or ". . ." in text
            )
            if is_toc_heading or has_leaders:
                scan_range.append(p)
            else:
                break
        except Exception:
            break

    # 3. Parse entries from all gathered TOC pages
    raw_entries = []
    for p_no in scan_range:
        try:
            raw_text = doc[p_no].get_text("text")
            norm_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw_text)
            norm_text = re.sub(r'[\u2000-\u200f\u2028-\u202f\xa0]', ' ', norm_text)
            raw_lines = [l.strip() for l in norm_text.splitlines() if l.strip()]

            # Determine where the TOC heading actually occurs on this page
            start_idx = 0
            for idx, l in enumerate(raw_lines):
                low_l = l.lower()
                if any(k in low_l for k in ["inhaltsverzeichnis", "inhaltsübersicht", "table of contents"]) and len(l) <= 45:
                    start_idx = idx + 1
                    break
                if low_l in ["inhalt", "contents"]:
                    start_idx = idx + 1
                    break

            cleaned_lines = []
            for raw in raw_lines[start_idx:]:
                s = raw.strip()
                if not s or re.match(r'^[\.\s·]+$', s):
                    continue
                if any(k in s.lower() for k in ["©", "copyright", "urheberrecht", "bereitgestellt", "powered by", "inhaltsverzeichnis", "inhaltsübersicht", "inhalt"]):
                    continue
                s_clean = re.sub(r'[\.\s·]{2,}\.?$', '', s).strip()
                if s_clean:
                    cleaned_lines.append(s_clean)

            i = 0
            while i < len(cleaned_lines):
                line = cleaned_lines[i]

                # Pattern A: Section prefix line (e.g. 'I.', 'II.', 'Kapitel 1', or single/double digit '1', '2', '18')
                # followed by title line followed by digit page
                if (
                    i + 2 < len(cleaned_lines)
                    and (
                        re.match(r'^(?:[IVXLCDM]+\.?|Teil\s+[IVXLCDM\d]+|Kapitel\s+\d+\.?|[A-Z]\b)$', line, re.I)
                        or re.match(r'^\d{1,2}$', line)
                    )
                    and cleaned_lines[i + 2].isdigit()
                    and not cleaned_lines[i + 1].isdigit()
                ):
                    prefix = f"{line}. " if line.isdigit() else f"{line} "
                    title = f"{prefix}{cleaned_lines[i + 1]}".strip()
                    p = int(cleaned_lines[i + 2])
                    raw_entries.append((1, title, p))
                    i += 3
                    continue

                # Pattern B1: Line 1 + Line 2 (multiline title) followed by standalone digit
                if (
                    i + 2 < len(cleaned_lines)
                    and cleaned_lines[i + 2].isdigit()
                    and not cleaned_lines[i + 1].isdigit()
                    and not re.match(r'^(?:[IVXLCDM]+\.?|\d+\.)', cleaned_lines[i + 1])
                ):
                    combined = f"{line} {cleaned_lines[i + 1]}".strip()
                    p = int(cleaned_lines[i + 2])
                    lvl = 2 if re.match(r'^\d+\.', combined) else 1
                    raw_entries.append((lvl, combined, p))
                    i += 3
                    continue

                # Pattern B2: Title line followed immediately by standalone digit (Arabic or Roman numeral)
                if i + 1 < len(cleaned_lines) and (cleaned_lines[i + 1].isdigit() or re.match(r'^[ivxlcdm]+$', cleaned_lines[i + 1], re.I)):
                    title = line
                    raw_p = cleaned_lines[i + 1]
                    p = int(raw_p) if raw_p.isdigit() else 1
                    lvl = 2 if re.match(r'^\d+\.', title) else 1
                    raw_entries.append((lvl, title, p))
                    i += 2
                    continue

                # Pattern C: In-line page number (e.g. 'Personenregister ... 165' or 'Title    165')
                m = re.search(r'^(.*?)(?:\s*[\.\s·]{2,}\.?|\s{2,}|\t+)(\d{1,4}|[ivxlcdm]+)$', line, re.I)
                if m:
                    title = m.group(1).strip()
                    raw_p = m.group(2)
                    p = int(raw_p) if raw_p.isdigit() else 1
                    lvl = 2 if re.match(r'^\d+\.', title) else 1
                    raw_entries.append((lvl, title, p))
                    i += 1
                    continue

                # Pattern D: Wrapped multi-line title where next line has rest of title + page
                if i + 1 < len(cleaned_lines):
                    next_l = cleaned_lines[i + 1]
                    m2 = re.search(r'^(.*?)(?:\s*[\.\s·]{2,}\.?|\s{2,}|\t+)(\d{1,4})$', next_l)
                    if m2 and not re.match(r'^(?:[IVXLCDM]+\.?|\d+\.)', next_l):
                        combined_title = f"{line} {m2.group(1).strip()}".strip()
                        p = int(m2.group(2))
                        lvl = 2 if re.match(r'^\d+\.', combined_title) else 1
                        raw_entries.append((lvl, combined_title, p))
                        i += 2
                        continue

                i += 1
        except Exception:
            pass

    if not raw_entries:
        return []

    # 4. Intelligently detect page offset between printed page numbers and PDF physical page index
    # We inspect headers/footers in the first 35 pages of the document where page 1 or 2 appears
    detected_offsets = []
    for pdf_idx in range(min(35, total_len)):
        try:
            page_obj = doc[pdf_idx]
            page_h = page_obj.rect.height
            page_dict = page_obj.get_text("dict")
            for b in page_dict.get("blocks", []):
                if b.get("type") != 0:
                    continue
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        txt = s.get("text", "").strip()
                        if txt.isdigit():
                            p_val = int(txt)
                            y_pos = s.get("bbox", (0, 0, 0, 0))[1]
                            # Check if the number is in header (< 15% height) or footer (> 85% height)
                            if y_pos < page_h * 0.15 or y_pos > page_h * 0.85:
                                if 1 <= p_val <= total_len:
                                    offset_candidate = (pdf_idx + 1) - p_val
                                    if 0 <= offset_candidate <= 35:
                                        detected_offsets.append(offset_candidate)
        except Exception:
            pass

    offset = 0
    if detected_offsets:
        offset = max(set(detected_offsets), key=detected_offsets.count)

    adjusted_entries = []
    for lvl, title, printed_p in raw_entries:
        target_pdf_page = min(total_len, max(1, printed_p + offset))
        adjusted_entries.append((lvl, title, target_pdf_page, printed_p))

    return adjusted_entries


_TOC_CACHE: dict = {}


def extract_pdf_toc(file_path: str) -> List[Tuple]:
    """Extracts chapter titles, nesting levels, and destination page numbers from PDF.
    1. First attempts reading electronic bookmarks (doc.get_toc()).
    2. If no electronic bookmarks exist, automatically parses the printed Table of Contents.
    Results are cached in memory for zero-lag subsequent lookups.
    Returns list of (level, chapter_title, target_page_1_indexed, printed_page_number_optional).
    """
    if not os.path.exists(file_path):
        return []

    norm_path = os.path.abspath(file_path)
    if norm_path in _TOC_CACHE:
        return _TOC_CACHE[norm_path]

    results: List[Tuple] = []
    try:
        if _HAS_FITZ:
            import fitz
            doc = fitz.open(file_path)
            toc = doc.get_toc()
            if toc:
                for item in toc:
                    try:
                        lvl = int(item[0])
                        t = str(item[1]).strip()
                        p = int(item[2])
                        if t and p > 0:
                            t = re.sub(r'[\r\n\t]+', ' ', t).strip()
                            results.append((lvl, t, p, p))
                    except Exception:
                        continue
            else:
                # Fallback to intelligent printed TOC text parsing
                results = _extract_printed_toc(doc)

            doc.close()
    except Exception:
        pass

    _TOC_CACHE[norm_path] = results
    return results


