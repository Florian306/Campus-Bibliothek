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


def extract_visual_title_and_author(doc) -> Tuple[Optional[str], Optional[str]]:
    """Inspects front-matter text blocks and bookmarks to extract genuine book title and author."""
    total_pages = len(doc)
    found_title = None
    found_author = None

    # 1. Front-matter prominent blocks (Page 0 and 1)
    for p_no in range(min(2, total_pages)):
        try:
            blocks = doc[p_no].get_text("blocks")
            for b in blocks:
                text = b[4].strip()
                if not text or len(text) < 3 or len(text) > 120:
                    continue
                if any(k in text.lower() for k in [
                    "http", "doi:", "isbn", "copyright", "©", "urheberrecht",
                    "alle rechte", "gespeichert", "ip ", "download", "druck:",
                    "satz:", "verlag", "bibliografische", "open-access", "for personal use"
                ]):
                    continue
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                cand = " ".join(lines)
                cand = re.sub(r'\s+', ' ', cand).strip()
                if not (3 <= len(cand) <= 95):
                    continue
                if re.match(r'^\d+$', cand) or re.search(r'\.(?:indd|indb|qxd|doc|docx|pdf)$', cand, re.I):
                    continue
                if any(j in cand.lower() for j in [
                    "titelei", "vorsatz", "inhaltsverzeichnis", "inhalt", "impressum", "cover",
                    "copyright", "author", "this page intentionally left blank", "table of contents",
                    "preface", "vorwort", "danksagung", "acknowledgements", "all rights reserved"
                ]):
                    continue

                words = cand.split()
                is_person = (
                    2 <= len(words) <= 4
                    and all(w[0].isupper() for w in words if w.isalpha())
                    and not any(k in cand.lower() for k in ["band", "auflage", "lehrbuch", "einführung", "grundkurs", "handbuch", "buch", "reihe", "edition", "mitteilung"])
                )

                if is_person and not found_author and not found_title:
                    found_author = cand
                elif not found_title:
                    # Clean out bullet points like '●'
                    cand = cand.replace("●", "-").replace("  ", " ")
                    found_title = cand
                elif not found_author and is_person:
                    found_author = cand
        except Exception:
            pass
        if found_title:
            break

    # 2. Bookmarks / TOC Fallback if front page was completely empty
    if not found_title:
        try:
            toc = doc.get_toc()
            if toc:
                for lvl, t, p in toc[:5]:
                    clean_t = t.strip('\x00 \t\r\n')
                    if clean_t and not any(j in clean_t.lower() for j in [
                        "cover", "titelei", "vorsatz", "inhaltsverzeichnis", "inhalt",
                        "vorwort", "impressum", "gehe zu", "seite", "kapitel", "chapter",
                        "einleitung", "einführung", "abkürzungen", "literatur"
                    ]):
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
                raw_author = re.sub(r'\[?\s*(?:Illustrator(?:in)?|Grafik(?:er)?|Redaktion|Red\.|Hrsg\.|Herausgeber|Fotograf(?:in)?|Bearb\.|Bearbeiter|Mitarb\.|Mitarbeiter)\s*\]?', '', raw_author, flags=re.IGNORECASE)
                raw_author = raw_author.replace('[', '').replace(']', '').strip()
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


def extract_pdf_toc(file_path: str) -> List[Tuple[int, str, int]]:
    """Extracts chapter titles, nesting levels, and destination page numbers from PDF.
    1. First attempts reading electronic bookmarks (doc.get_toc()).
    2. If no electronic bookmarks exist, automatically parses the printed Table of Contents.
    Returns list of (level, chapter_title, page_number_1_indexed).
    """
    if not os.path.exists(file_path):
        return []

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

    return results


