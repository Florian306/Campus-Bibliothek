"""Incremental Delta-Scanner for the Virtual Campus Library.
Scans source directory in milliseconds by skipping already indexed and unchanged PDFs.
Parses page count, multi-categories, edition, and metadata seamlessly into library.db.
"""

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple
import fitz

from core.library_db import get_db_connection, upsert_book
from ai.pipeline import process_book_pipeline
from ai.isbn_lookup import extract_isbns
from ai.pdf_extractor import extract_publication_year



_EDITION_RE = re.compile(
    r'(?:^|[^\d])(\d{1,2})\.\s*(?:,\s*)?(?:neu\s*bearbeitete|aktualisierte|überarbeitete|erweiterte|vollständig|korrigierte|verbesserte|wesentlich|durchgesehene)?\s*Aufl(?:age)?',
    re.IGNORECASE
)

_ISBN_TITLE_RE = re.compile(r'^[\dXx\-\s_]{10,17}(?:\.pdf)?$')

RENAME_MIN_CONFIDENCE = 80
_rename_lock = threading.Lock()


def _rename_book_file(full_path: str, new_filename: str) -> Tuple[str, str]:
    """Renames PDF on disk (collision-safe) and moves the DB row to the new path.
    Returns (path, filename) actually in use.
    """
    folder, old_name = os.path.split(full_path)
    new_filename = (new_filename or "").strip()
    if not new_filename or new_filename.lower() == old_name.lower():
        return full_path, old_name
    if not new_filename.lower().endswith(".pdf"):
        new_filename += ".pdf"

    with _rename_lock:
        stem = new_filename[:-4]
        target = os.path.join(folder, new_filename)
        n = 2
        while os.path.exists(target):
            target = os.path.join(folder, f"{stem} ({n}).pdf")
            n += 1
        try:
            os.rename(full_path, target)
        except OSError:
            return full_path, old_name

        # Keep book id / notes / desk entries attached
        try:
            conn = get_db_connection()
            with conn:
                conn.execute(
                    "UPDATE books SET file_path = ?, filename = ? WHERE file_path = ?;",
                    (target, os.path.basename(target), full_path),
                )
        except Exception:
            pass

    return target, os.path.basename(target)


def extract_edition_number(text: str) -> Tuple[int, str]:
    """Detects book edition number (e.g. '4. Auflage' -> 4)."""
    m = _EDITION_RE.search(text)
    if m:
        try:
            ed_num = int(m.group(1))
            if 1 <= ed_num <= 40:
                return ed_num, m.group(0).strip()
        except ValueError:
            pass
    return 1, "1. Auflage"


def run_delta_scan(
    source_dir: str,
    progress_callback: Optional[Callable] = None,
    stop_event: Optional[Any] = None,
    provider: str = "ollama",
    ollama_model: str = "qwen2.5vl:latest",
    max_workers: Optional[int] = None,
) -> Dict[str, int]:
    """Performs a modern concurrent incremental scan with multi-threaded worker pool.
    Returns stats: {'total': N, 'new_or_updated': N, 'unchanged': N}
    """
    if not os.path.exists(source_dir):
        return {"total": 0, "new_or_updated": 0, "unchanged": 0}

    # 1. Fetch existing indexed files and registered extracts from library.db in a single fast read
    conn = get_db_connection()
    cur = conn.execute("SELECT file_path, file_size, file_mtime FROM books;")
    indexed_map = {row["file_path"]: (row["file_size"], row["file_mtime"]) for row in cur.fetchall()}

    # Registered chapter extracts are child documents and must NEVER be scanned into the main books table
    extract_paths = set()
    try:
        cur_e = conn.execute("SELECT file_path FROM book_extracts WHERE file_path IS NOT NULL;")
        extract_paths = {os.path.normcase(os.path.abspath(row["file_path"])) for row in cur_e.fetchall()}
    except Exception:
        pass

    # Unresolved entries (Sonstiges / ISBN-only title) are re-analyzed on every scan
    unresolved_paths = set()
    try:
        cur = conn.execute(
            """
            SELECT b.file_path, b.title, b.filename, c.category FROM books b
            LEFT JOIN book_categories c ON c.book_id = b.id AND c.is_primary = 1
            WHERE c.category IS NULL OR c.category = 'Sonstiges'
               OR b.title = b.filename OR b.title GLOB '[0-9]*';
            """
        )
        for row in cur.fetchall():
            if (
                row["category"] in (None, "Sonstiges")
                or row["title"] == row["filename"]
                or _ISBN_TITLE_RE.match(row["title"] or "")
            ):
                unresolved_paths.add(row["file_path"])
    except Exception:
        pass

    # 2. Gather candidate PDF files in source directory (skip extract subfolders)
    pdf_files: List[Tuple[str, str, int, float]] = []
    for root, dirs, files in os.walk(source_dir):
        # Prune extract / chapter subfolders so they are not scanned as standalone books
        dirs[:] = [
            d for d in dirs
            if not (d.endswith("_Kapitel") or d.lower() in ("kapitel", "extracts", "auszüge", "auszuege"))
        ]

        if stop_event and stop_event.is_set():
            return {"total": 0, "new_or_updated": 0, "unchanged": 0}
        for f in files:
            if f.lower().endswith(".pdf"):
                full_p = os.path.join(root, f)
                # Ignore files that are registered chapter extracts
                if extract_paths and os.path.normcase(os.path.abspath(full_p)) in extract_paths:
                    continue
                try:
                    stat = os.stat(full_p)
                    pdf_files.append((full_p, f, stat.st_size, stat.st_mtime))
                except Exception:
                    pass

    total_files = len(pdf_files)
    if total_files == 0:
        return {"total": 0, "new_or_updated": 0, "unchanged": 0}

    # 3. Categorize into unchanged vs pending in memory (< 1ms)
    unchanged_files: List[Tuple[str, str, int, float]] = []
    pending_files: List[Tuple[str, str, int, float]] = []

    for item in pdf_files:
        full_path, fname, fsize, fmtime = item
        if full_path in indexed_map and full_path not in unresolved_paths:
            known_size, known_mtime = indexed_map[full_path]
            if known_size == fsize and abs(known_mtime - fmtime) < 1.5:
                unchanged_files.append(item)
                continue
        pending_files.append(item)

    unchanged_count = len(unchanged_files)
    new_count = 0
    processed_count = unchanged_count
    count_lock = threading.Lock()

    # Inform UI immediately about already known files without flooding
    if unchanged_count > 0 and progress_callback:
        try:
            progress_callback(processed_count, total_files, f"{unchanged_count} bekannte PDFs übersprungen", False, None)
        except TypeError:
            progress_callback(processed_count, total_files, f"{unchanged_count} bekannte PDFs übersprungen", False)

    # If all files are up to date, we are finished instantly
    if not pending_files:
        return {"total": total_files, "new_or_updated": 0, "unchanged": unchanged_count}

    # 4. Multi-threaded processing pool
    dir_norm = source_dir.lower()
    is_cloud = (
        any(c in dir_norm for c in ["google", "drivefs", "onedrive", "dropbox", "icloud"])
        or (len(dir_norm) >= 2 and dir_norm[1] == ":" and dir_norm[0] not in "cdef")
    )
    if max_workers is None:
        max_workers = 3 if is_cloud else min(6, max(2, (os.cpu_count() or 4)))

    def process_single_pdf(item: Tuple[str, str, int, float]) -> Optional[Dict[str, Any]]:
        if stop_event and stop_event.is_set():
            return None

        full_path, fname, fsize, fmtime = item
        try:
            analysis = process_book_pipeline(
                original_path=full_path,
                original_filename=fname,
                provider=provider,
                ollama_model=ollama_model,
            )

            page_count = 0
            ed_num = 1
            ed_str = "1. Auflage"
            isbn_str: Optional[str] = None
            pub_year: Optional[int] = None
            try:
                doc = fitz.open(full_path)
                page_count = len(doc)
                snippet = ""
                for p_idx in range(min(8, page_count)):
                    snippet += doc[p_idx].get_text("text") + "\n"
                ed_num, ed_str = extract_edition_number(f"{fname}\n{snippet}")
                found_isbns = extract_isbns(f"ISBN {fname.replace('_', ' ')}\n{snippet}")
                if found_isbns:
                    isbn_str = found_isbns[0]
                pub_year = extract_publication_year(snippet, doc.metadata, fname)
                doc.close()
            except Exception:
                pass

            categories = [analysis.kategorie] if analysis.kategorie else ["Sonstiges"]

            if (
                analysis.neuer_dateiname
                and analysis.titel
                and analysis.confidence >= RENAME_MIN_CONFIDENCE
                and "Sonstiges" not in categories
            ):
                full_path, fname = _rename_book_file(full_path, analysis.neuer_dateiname)

            book_id = upsert_book(
                file_path=full_path,
                filename=fname,
                title=analysis.titel or fname,
                author=analysis.autor or "Unbekannt",
                categories=categories,
                isbn=isbn_str,
                edition=ed_num,
                edition_str=ed_str,
                year=pub_year,
                page_count=page_count,
                file_size=fsize,
                file_mtime=fmtime,
                confidence=analysis.confidence,
                audit_trail=analysis.review_reason or "",
            )

            return {
                "id": book_id,
                "title": analysis.titel or fname,
                "author": analysis.autor or "Unbekannt",
                "isbn": isbn_str,
                "categories_str": " | ".join(categories),
                "edition": ed_num,
                "year": pub_year,
                "page_count": page_count,
                "is_on_desk": 0,
            }

        except Exception as e:
            book_id = upsert_book(
                file_path=full_path,
                filename=fname,
                title=fname,
                author="Unbekannt",
                categories=["Sonstiges"],
                file_size=fsize,
                file_mtime=fmtime,
                confidence=50,
                audit_trail=f"Fehler: {str(e)}",
            )
            return {
                "id": book_id,
                "title": fname,
                "author": "Unbekannt",
                "categories_str": "Sonstiges",
                "edition": 1,
                "page_count": 0,
                "is_on_desk": 0,
            }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(process_single_pdf, it): it for it in pending_files}

        for future in as_completed(future_to_item):
            if stop_event and stop_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                break

            item = future_to_item[future]
            fname = item[1]
            try:
                book_data = future.result()
            except Exception:
                book_data = None

            with count_lock:
                new_count += 1
                processed_count += 1
                curr_done = processed_count

            if progress_callback:
                try:
                    progress_callback(curr_done, total_files, fname, True, book_data)
                except TypeError:
                    progress_callback(curr_done, total_files, fname, True)

    return {"total": total_files, "new_or_updated": new_count, "unchanged": unchanged_count}


def index_single_book_file(full_path: str) -> Optional[Dict[str, Any]]:
    """Analyzes and indexes a single PDF file immediately into the library database."""
    if not os.path.isfile(full_path) or not full_path.lower().endswith(".pdf"):
        return None

    fname = os.path.basename(full_path)
    try:
        stat = os.stat(full_path)
        fsize = stat.st_size
        fmtime = stat.st_mtime
    except Exception:
        fsize = 0
        fmtime = time.time()

    try:
        analysis = process_book_pipeline(
            original_path=full_path,
            original_filename=fname,
        )

        page_count = 0
        ed_num = 1
        ed_str = "1. Auflage"
        isbn_str: Optional[str] = None
        pub_year: Optional[int] = None
        try:
            doc = fitz.open(full_path)
            page_count = len(doc)
            snippet = ""
            for p_idx in range(min(8, page_count)):
                snippet += doc[p_idx].get_text("text") + "\n"
            ed_num, ed_str = extract_edition_number(f"{fname}\n{snippet}")
            found_isbns = extract_isbns(f"ISBN {fname.replace('_', ' ')}\n{snippet}")
            if found_isbns:
                isbn_str = found_isbns[0]
            pub_year = extract_publication_year(snippet, doc.metadata, fname)
            doc.close()
        except Exception:
            pass

        categories = [analysis.kategorie] if analysis.kategorie else ["Sonstiges"]

        if (
            analysis.neuer_dateiname
            and analysis.titel
            and analysis.confidence >= RENAME_MIN_CONFIDENCE
            and "Sonstiges" not in categories
        ):
            full_path, fname = _rename_book_file(full_path, analysis.neuer_dateiname)

        book_id = upsert_book(
            file_path=full_path,
            filename=fname,
            title=analysis.titel or fname,
            author=analysis.autor or "Unbekannt",
            categories=categories,
            isbn=isbn_str,
            edition=ed_num,
            edition_str=ed_str,
            year=pub_year,
            page_count=page_count,
            file_size=fsize,
            file_mtime=fmtime,
            confidence=analysis.confidence,
            audit_trail=analysis.review_reason or "",
        )

        return {
            "id": book_id,
            "title": analysis.titel or fname,
            "author": analysis.autor or "Unbekannt",
            "categories_str": " | ".join(categories),
            "file_path": full_path,
        }
    except Exception:
        return None
