"""High-performance PDF manipulation service powered by PyMuPDF (fitz).
Provides lossless, instantaneous page extraction, page range parsing, and PDF slicing.
"""

import os
import re
from typing import List, Optional, Tuple, Dict, Any

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None


def parse_page_ranges(range_str: str, max_pages: int) -> List[int]:
    """Parses human-friendly page strings (e.g. '1-5, 8, 12-14') into sorted, unique 0-indexed page numbers.
    Validates against the document's total page count.
    """
    if not range_str or not range_str.strip():
        return []

    # Safe fallback if page count could not be retrieved
    limit = max_pages if max_pages > 0 else 999999

    clean = range_str.replace(";", ",").strip()
    tokens = [t.strip() for t in clean.split(",") if t.strip()]
    selected_pages = set()

    for token in tokens:
        # Check for range: e.g. "5-12"
        m_range = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', token)
        if m_range:
            start_p = int(m_range.group(1))
            end_p = int(m_range.group(2))
            if start_p > end_p:
                start_p, end_p = end_p, start_p
            for p in range(start_p, end_p + 1):
                if 1 <= p <= limit:
                    selected_pages.add(p - 1)
            continue

        # Single page: e.g. "8"
        if token.isdigit():
            p = int(token)
            if 1 <= p <= limit:
                selected_pages.add(p - 1)

    return sorted(list(selected_pages))


def extract_pdf_pages(
    source_pdf_path: str,
    page_indices: List[int],
    target_pdf_path: str
) -> Tuple[bool, str]:
    """Extracts specified 0-indexed pages from source_pdf_path into target_pdf_path.
    Uses PyMuPDF for lightning-fast (<50ms), lossless extraction with stream deflation.
    """
    if fitz is None:
        return False, "PyMuPDF (fitz) ist auf dem System nicht verfügbar."

    if not os.path.isfile(source_pdf_path):
        return False, f"Quelldatei nicht gefunden: {source_pdf_path}"

    if not page_indices:
        return False, "Keine gültigen Seiten zur Extraktion ausgewählt."

    try:
        src_doc = fitz.open(source_pdf_path)
        total_src = len(src_doc)
        valid_indices = [p for p in page_indices if 0 <= p < total_src]

        if not valid_indices:
            src_doc.close()
            return False, "Die ausgewählten Seitenzahlen liegen außerhalb des Dokuments."

        out_doc = fitz.open()

        # Insert selected pages in requested order
        for p in valid_indices:
            out_doc.insert_pdf(src_doc, from_page=p, to_page=p)

        os.makedirs(os.path.dirname(os.path.abspath(target_pdf_path)), exist_ok=True)
        out_doc.save(target_pdf_path, deflate=True, garbage=3)
        out_doc.close()
        src_doc.close()

        return True, f"{len(valid_indices)} Seiten erfolgreich nach '{os.path.basename(target_pdf_path)}' extrahiert."
    except Exception as e:
        return False, f"Fehler bei der PDF-Extraktion: {str(e)}"


def get_pdf_page_count(pdf_path: str) -> int:
    """Returns total number of pages in a PDF file."""
    if not os.path.isfile(pdf_path) or fitz is None:
        return 0
    try:
        doc = fitz.open(pdf_path)
        c = len(doc)
        doc.close()
        return c
    except Exception:
        return 0


def compute_chapter_spans(
    toc_entries: List[Tuple[int, str, int]],
    total_pages: int,
    max_level: int = 1
) -> List[Dict[str, Any]]:
    """Calculates non-overlapping page boundaries for chapters up to max_level.
    Returns list of dicts with: index, level, title, start_page, end_page, page_count.
    """
    if not toc_entries or total_pages <= 0:
        return []

    # Filter by hierarchy level
    filtered = [(lvl, t, p) for (lvl, t, p) in toc_entries if lvl <= max_level and p > 0]
    if not filtered:
        # Fallback to level 1 or min level available
        min_lvl = min(lvl for (lvl, _, _) in toc_entries)
        filtered = [(lvl, t, p) for (lvl, t, p) in toc_entries if lvl == min_lvl and p > 0]

    spans: List[Dict[str, Any]] = []
    num_items = len(filtered)

    for i, (lvl, title, start_p) in enumerate(filtered):
        # Clean title
        clean_title = re.sub(r'[\r\n\t]+', ' ', title).strip()
        clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_title)[:80].strip() or f"Kapitel {i + 1}"

        # Boundary end page is page before next sibling/higher item, or total_pages for the last item
        if i + 1 < num_items:
            next_start = filtered[i + 1][2]
            end_p = next_start - 1 if next_start > start_p else start_p
        else:
            end_p = total_pages

        start_p = max(1, min(start_p, total_pages))
        end_p = max(start_p, min(end_p, total_pages))
        count = end_p - start_p + 1

        spans.append({
            "index": i + 1,
            "level": lvl,
            "title": clean_title,
            "start_page": start_p,
            "end_page": end_p,
            "page_count": count
        })

    return spans


def batch_extract_all_chapters(
    source_pdf_path: str,
    output_dir: str,
    base_prefix: str,
    spans: List[Dict[str, Any]],
    progress_callback=None
) -> List[Dict[str, Any]]:
    """Extracts all chapters from spans into output_dir.
    Returns list of successful extract dicts with: title, file_path, page_range, page_count, file_size.
    """
    if fitz is None or not os.path.isfile(source_pdf_path):
        return []

    os.makedirs(output_dir, exist_ok=True)
    created: List[Dict[str, Any]] = []

    try:
        src_doc = fitz.open(source_pdf_path)
        total_src = len(src_doc)
        total_spans = len(spans)

        for i, item in enumerate(spans):
            sp = item["start_page"]
            ep = item["end_page"]
            title = item["title"]

            # Format filename: e.g. "01 - Grundlagen (S. 1-25).pdf"
            fn = f"{item['index']:02d} - {title} (S. {sp}-{ep}).pdf"
            target_path = os.path.join(output_dir, fn)

            out_doc = fitz.open()
            from_idx = max(0, sp - 1)
            to_idx = min(total_src - 1, ep - 1)

            out_doc.insert_pdf(src_doc, from_page=from_idx, to_page=to_idx)
            out_doc.save(target_path, deflate=True, garbage=3)
            out_doc.close()

            f_size = os.path.getsize(target_path) if os.path.isfile(target_path) else 0
            p_range = f"{sp}-{ep}" if sp != ep else str(sp)

            created.append({
                "title": f"{item['index']:02d} - {title}",
                "file_path": target_path,
                "page_range": p_range,
                "page_count": item["page_count"],
                "file_size": f_size
            })

            if progress_callback:
                progress_callback(i + 1, total_spans, title)

        src_doc.close()
    except Exception:
        pass

    return created


def compute_chunk_spans(total_pages: int, chunk_size: int = 30) -> List[Dict[str, Any]]:
    """Generates equal-sized chapter/chunk spans (e.g. 30 pages each).
    Useful for NotebookLM or LLM context splitting when no TOC exists.
    """
    if total_pages <= 0:
        return []
    
    chunk_size = max(5, int(chunk_size))
    spans: List[Dict[str, Any]] = []
    
    start_p = 1
    idx = 1
    while start_p <= total_pages:
        end_p = min(start_p + chunk_size - 1, total_pages)
        count = end_p - start_p + 1
        spans.append({
            "index": idx,
            "level": 1,
            "title": f"Teil {idx:02d} (S. {start_p}–{end_p})",
            "start_page": start_p,
            "end_page": end_p,
            "page_count": count
        })
        start_p = end_p + 1
        idx += 1
        
    return spans


def detect_printed_toc(source_pdf_path: str, max_scan_pages: int = 30) -> List[Tuple[int, str, int]]:
    """Intelligent multi-strategy algorithm for detecting Table of Contents in PDFs without bookmarks.
    
    Architecture:
    1. Pass 1: Identify strictly valid TOC pages (find header & stop when TOC patterns cease).
    2. Pass 2: Layout block analysis with multi-line title fusion and dot-leader resolution.
    3. Pass 3: Filtering & noise removal (drop page footer artifacts, TOC titles).
    4. Pass 4: Page offset calibration (verifies where chapter headings physically begin in the PDF).
    """
    if fitz is None or not os.path.isfile(source_pdf_path):
        return []

    try:
        doc = fitz.open(source_pdf_path)
        total_p = len(doc)
        scan_limit = min(total_p, max_scan_pages)

        # High-accuracy regex matching: "1.2 Einführung ....... 15", "Chapter 3: Foundations ___ 42", "Introduction 5"
        inline_pattern = re.compile(
            r'^(?:(?:Kapitel|Chapter|Abschnitt|Teil|Part|Lernfeld)\s+)?([0-9]+(?:\.[0-9]+)*\.?|[A-Z]\.)\s*([A-Za-zÄÖÜäöüß][\w\s,.:\-–—\(\)\/\'\"\?\!«»\<\>&]+?)(?:[\.\-–—_]{2,}|\s{2,}|\s+)\s*([0-9]{1,4})\s*$'
        )
        trailing_num_pattern = re.compile(
            r'^([A-Za-zÄÖÜäöüß][\w\s,.:\-–—\(\)\/\'\"\?\!«»\<\>&]+?)(?:[\.\-–—_]{2,}|\s{2,}|\s+)\s*([0-9]{1,4})\s*$'
        )

        toc_pages: List[int] = []

        # Pass 1: Discover TOC pages with strict boundaries
        for p_idx in range(scan_limit):
            page = doc[p_idx]
            txt = page.get_text("text").strip()
            if not txt:
                continue

            lines = [l.strip() for l in txt.split("\n") if l.strip()]
            has_header = any(
                re.search(r'\b(inhaltsverzeichnis|inhaltsübersicht|table of contents|contents|inhalt|sommaire)\b', l, re.IGNORECASE)
                for l in lines[:6]
            )

            # Count TOC-like lines on this page
            num_toc_lines = 0
            for l in lines:
                if re.search(r'(?:[\.\-–—_]{2,}|\t+)\s*[0-9]{1,4}\s*$', l) or re.match(r'^[0-9]+(?:\.[0-9]+)*\s+[A-Za-zÄÖÜäöüß].+[0-9]+$', l):
                    num_toc_lines += 1

            if has_header or num_toc_lines >= 4:
                toc_pages.append(p_idx)
            elif toc_pages and p_idx == toc_pages[-1] + 1 and (num_toc_lines >= 2 or len(lines) <= 25):
                # Continuation page immediately following TOC page
                toc_pages.append(p_idx)
            elif toc_pages and p_idx > toc_pages[-1]:
                # We have left the TOC section
                break

        scan_candidates = toc_pages if toc_pages else list(range(min(scan_limit, 12)))
        raw_candidates: List[Dict[str, Any]] = []

        # Pass 2: Extract structured chapter candidates
        for p_idx in scan_candidates:
            page = doc[p_idx]
            blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)

            for b_idx, b in enumerate(blocks):
                if b[6] != 0:  # text blocks only
                    continue
                b_text = b[4].strip().replace("\r", "")
                b_flat = " ".join([l.strip() for l in b_text.split("\n") if l.strip()])

                # Check if block is a lone page number following a title block
                if b_flat.isdigit() and 1 <= int(b_flat) <= total_p and b_idx > 0:
                    prev_b = blocks[b_idx - 1]
                    prev_flat = " ".join([l.strip() for l in prev_b[4].strip().split("\n") if l.strip()])
                    clean_prev = re.sub(r'[\.\-–—_]+$', '', prev_flat).strip()
                    if len(clean_prev) >= 4 and not re.match(r'^(seite|page|inhaltsverzeichnis|inhalt)\b', clean_prev.lower()):
                        raw_candidates.append({
                            "title": clean_prev,
                            "printed_page": int(b_flat),
                            "toc_page_idx": p_idx,
                            "level": 1
                        })
                        continue

                m_inline = inline_pattern.match(b_flat)
                if m_inline:
                    num_pfx = (m_inline.group(1) or "").strip()
                    c_title = m_inline.group(2).strip()
                    p_num = int(m_inline.group(3))
                    clean_t = re.sub(r'[\.\-–—_]+$', '', c_title).strip()
                    if clean_t and not re.match(r'^(inhaltsverzeichnis|inhalt|table of contents)\b', clean_t.lower()):
                        title = f"{num_pfx} {clean_t}".strip() if num_pfx else clean_t
                        lvl = min(3, num_pfx.count(".") + 1) if ("." in num_pfx and any(c.isdigit() for c in num_pfx)) else 1
                        raw_candidates.append({
                            "title": title,
                            "printed_page": p_num,
                            "toc_page_idx": p_idx,
                            "level": lvl
                        })
                    continue

                m_trail = trailing_num_pattern.match(b_flat)
                if m_trail:
                    c_title = m_trail.group(1).strip()
                    p_num = int(m_trail.group(2))
                    clean_t = re.sub(r'[\.\-–—_]+$', '', c_title).strip()
                    if len(clean_t) >= 4 and not re.match(r'^(seite|page|kapitel|vol|band|inhaltsverzeichnis|inhalt)\b', clean_t.lower()):
                        raw_candidates.append({
                            "title": clean_t,
                            "printed_page": p_num,
                            "toc_page_idx": p_idx,
                            "level": 1
                        })

        if not raw_candidates:
            doc.close()
            return []

        # Pass 3: Filtering & Deduplication
        unique_list: List[Dict[str, Any]] = []
        seen = set()
        for c in raw_candidates:
            clean_name = c["title"].strip()
            # Ignore self-references, header keywords or current page numbers
            if re.match(r'^(inhaltsverzeichnis|inhalt|table of contents|contents)\b', clean_name.lower()):
                continue
            if clean_name.lower().endswith("inhaltsverzeichnis"):
                continue
            key = (c["printed_page"], clean_name.lower())
            if key not in seen:
                seen.add(key)
                c["title"] = clean_name
                unique_list.append(c)

        if not unique_list:
            doc.close()
            return []

        # Pass 4: Page Offset Calibration
        # Verifies where the chapter heading physically begins in the document
        offset = 0
        tested_offsets = []
        for cand in unique_list[:4]:
            words = [w for w in re.findall(r'[A-Za-zÄÖÜäöüß]{4,}', cand["title"]) if w.lower() not in {"kapitel", "teil", "buch", "einführung", "grundlagen"}]
            if not words:
                continue
            search_query = words[0]
            printed_p = cand["printed_page"]
            toc_p = cand["toc_page_idx"]

            start_search = max(toc_p + 1, printed_p - 5)
            end_search = min(total_p, printed_p + 35)

            for check_idx in range(start_search, end_search):
                p_text = doc[check_idx].get_text("text")
                if search_query.lower() in p_text.lower():
                    actual_pdf_page = check_idx + 1
                    diff = actual_pdf_page - printed_p
                    if 0 <= diff <= 40:
                        tested_offsets.append(diff)
                    break

        if tested_offsets:
            from collections import Counter
            offset = Counter(tested_offsets).most_common(1)[0][0]

        doc.close()

        final_toc: List[Tuple[int, str, int]] = []
        for item in unique_list:
            final_p = min(total_p, max(1, item["printed_page"] + offset))
            final_toc.append((item["level"], item["title"], final_p))

        final_toc.sort(key=lambda x: x[2])
        return final_toc

    except Exception:
        return []



