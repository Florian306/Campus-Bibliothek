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
            page_title_cands = [
                c for c in grouped_candidates
                if not is_series_or_course(c[0])
                and not is_generic_section(c[0])
                and not any(c[0].lower().startswith(x) for x in ["prof.", "dr.", "von "])
                and len(c[0]) >= 4
            ]
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

    # 1. Direct copyright notice (e.g. © 2021, Copyright 2018, (c) 2015)
    if text:
        cp_years = []
        for m in re.finditer(r'(?:©|copyright|\(c\))\s*(?:by\s+)?([12]\d{3})', text, re.I):
            try:
                y = int(m.group(1))
                if 1900 <= y <= current_year:
                    cp_years.append(y)
            except (ValueError, TypeError):
                continue
        if cp_years:
            return max(cp_years)

        # 2. Edition notice with year (e.g. '4. Auflage 2020', '3. überarb. Auflage 2018')
        ed_years = []
        for m in re.finditer(r'(?:\b\d+\.?\s*(?:überarb\.|aktualis\.|erw\.|vollst\.)?\s*Auflage|\bEdition)\s*[,.:-]?\s*([12]\d{3})\b', text, re.I):
            try:
                y = int(m.group(1))
                if 1900 <= y <= current_year:
                    ed_years.append(y)
            except (ValueError, TypeError):
                continue
        if ed_years:
            return max(ed_years)

        # 3. Imprint keywords / Publishing houses
        pub_years = []
        for m in re.finditer(
            r'(?:erscheinungsjahr|veröffentlicht|gedruckt|printed|published|springer|hanser|pearson|wiley|thieme|de gruyter|c\.?\s*h\.?\s*beck|hogrefe|kohlhammer|nomos|utb|vahlen|vieweg|rowohlt|suhrkamp|campus)[^\n\r]{0,45}\b([12]\d{3})\b',
            text,
            re.I
        ):
            try:
                y = int(m.group(1))
                if 1950 <= y <= current_year:
                    pub_years.append(y)
            except (ValueError, TypeError):
                continue
        if pub_years:
            return max(pub_years)

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


def _extract_printed_toc(doc) -> List[Tuple[int, str, int]]:
    """Heuristic fallback parser: Extracts chapters and page numbers directly from printed
    Table of Contents (Inhaltsverzeichnis) pages when no digital PDF bookmarks exist.
    """
    total_len = len(doc)
    if total_len == 0:
        return []

    # 1. Locate start of printed table of contents within the first 35 pages
    toc_pages = []
    max_scan = min(35, total_len)
    for p_no in range(max_scan):
        try:
            txt = doc[p_no].get_text("text")
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            for l in lines[:6]:
                low = l.lower()
                if any(k in low for k in ["inhaltsverzeichnis", "inhaltsübersicht", "inhalt", "contents", "table of contents"]):
                    if len(l) <= 45 and not re.search(r'\d{3,}', l):
                        toc_pages.append(p_no)
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

    # 3. Parse entries (handling multi-line blocks with trailing page numbers and line patterns)
    raw_entries = []
    for p_no in scan_range:
        page_entries = []

        # 3a. Block-based parsing (preserves multi-line chapter descriptions)
        try:
            blocks = doc[p_no].get_text("blocks")
            for b_idx, b in enumerate(blocks):
                txt = b[4].strip()
                norm = re.sub(r'[\t\u2000-\u200f\u2028-\u202f]+', ' ', txt)
                norm = re.sub(r' +', ' ', norm)
                m = re.search(r'^(.*?)(?:\s*\.{2,}|\s{2,}|\n\s*|\s+)(\d{1,4})\s*$', norm, re.DOTALL)
                if m:
                    raw_t = re.sub(r'\s+', ' ', m.group(1)).strip()
                    p_num = int(m.group(2))
                    if b_idx > 0:
                        prev_txt = blocks[b_idx - 1][4].strip()
                        if prev_txt.isdigit() and len(prev_txt) <= 3 and not re.match(r'^(?:Lernfeld|\d+)', raw_t):
                            raw_t = f"{prev_txt}. {raw_t}"
                    clean_t = raw_t.lstrip('.-· ')
                    if (
                        clean_t
                        and len(clean_t) >= 2
                        and not any(j in clean_t.lower() for j in ["inhaltsverzeichnis", "inhaltsübersicht", "inhalt"])
                    ):
                        lvl = 1
                        if re.match(r'^\d+\.\d+\.\d+', clean_t):
                            lvl = 3
                        elif re.match(r'^\d+\.\d+', clean_t):
                            lvl = 2
                        page_entries.append((lvl, clean_t, p_num))
        except Exception:
            pass

        # 3b. Line-based parsing fallback if block extraction yielded few results
        if len(page_entries) < 2:
            line_entries = []
            try:
                txt = doc[p_no].get_text("text")
                norm_txt = re.sub(r'(?:[\.\s·]{2,}\.|\.{2,})', ' ... ', txt)
                norm_txt = re.sub(r'\.\.\.\s*\n\s*(\d{1,4})\b', r'... \1', norm_txt)
                lines = [l.strip() for l in norm_txt.splitlines() if l.strip()]
                i = 0
                while i < len(lines):
                    line = lines[i]
                    m = re.search(r'^(.*?)\s*\.{2,}\s*(\d{1,4})\s*$', line)
                    if not m:
                        m = re.search(r'^(.*?)(?:\t+|\s{3,})(\d{1,4})\s*$', line)
                    if m:
                        raw_title = m.group(1).strip()
                        page_num = int(m.group(2))
                        if (
                            i > 0
                            and len(lines[i - 1]) < 30
                            and re.match(r'^(?:Teil\s+[IVXLCDM\d]+|Kapitel\s+\d+|\d+(?:\.\d+)*\.?)$', lines[i - 1], re.IGNORECASE)
                        ):
                            raw_title = f"{lines[i - 1]} {raw_title}"

                        clean_title = re.sub(r'[\r\n\t]+', ' ', raw_title).strip().lstrip('.-· ')
                        if (
                            clean_title
                            and len(clean_title) >= 2
                            and not any(j in clean_title.lower() for j in ["inhaltsverzeichnis", "inhaltsübersicht", "inhalt"])
                        ):
                            lvl = 1
                            if re.match(r'^\d+\.\d+\.\d+', clean_title):
                                lvl = 3
                            elif re.match(r'^\d+\.\d+', clean_title):
                                lvl = 2
                            line_entries.append((lvl, clean_title, page_num))
                    i += 1
            except Exception:
                pass
            if len(line_entries) > len(page_entries):
                page_entries = line_entries

        raw_entries.extend(page_entries)

    if not raw_entries:
        return []

    # 4. Detect offset between printed book page numbers and physical PDF page indices
    detected_offsets = []
    for p_idx in range(min(scan_range), min(scan_range[-1] + 25, total_len)):
        try:
            txt = doc[p_idx].get_text("text")
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            if not lines:
                continue
            for cand in [lines[0], lines[-1]]:
                if cand.isdigit():
                    val = int(cand)
                    if 1 <= val <= total_len:
                        detected_offsets.append((p_idx + 1) - val)
        except Exception:
            pass

    offset = 0
    if detected_offsets:
        valid_offsets = [o for o in detected_offsets if 0 <= o <= 40]
        if valid_offsets:
            offset = max(set(valid_offsets), key=valid_offsets.count)

    adjusted_entries = []
    for lvl, t, p in raw_entries:
        # Use the exact page number printed directly in the document
        page_in_doc = min(total_len, max(1, p))
        adjusted_entries.append((lvl, t, page_in_doc))

    return adjusted_entries


_TOC_CACHE: dict = {}


def extract_pdf_toc(file_path: str) -> List[Tuple[int, str, int]]:
    """Extracts chapter titles, nesting levels, and destination page numbers from PDF.
    1. First attempts reading electronic bookmarks (doc.get_toc()).
    2. If no electronic bookmarks exist, automatically parses the printed Table of Contents.
    Results are cached in memory for zero-lag subsequent lookups.
    Returns list of (level, chapter_title, page_number_1_indexed).
    """
    if not os.path.exists(file_path):
        return []

    norm_path = os.path.abspath(file_path)
    if norm_path in _TOC_CACHE:
        return _TOC_CACHE[norm_path]

    results: List[Tuple[int, str, int]] = []
    try:
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
                        results.append((lvl, t, p))
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


