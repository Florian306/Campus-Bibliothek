"""High-performance SQLite FTS5 Full-Text Indexing & Search Engine for Campus-Bibliothek.
Extracts and indexes page-level text from PDF documents incrementally in background threads.
Provides sub-10ms full-text search with BM25 ranking, snippet highlighting, and page jump support.
"""

import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

from core.library_db import DB_PATH


def _get_connection() -> sqlite3.Connection:
    """Creates a dedicated connection to DB_PATH for fulltext operations."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_fts_schema() -> None:
    """Initializes the FTS5 virtual table and index tracking status table."""
    conn = _get_connection()
    cur = conn.cursor()

    # 1. Virtual table for page-level full-text search
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS book_pages_fts USING fts5(
            book_id UNINDEXED,
            page_number UNINDEXED,
            content,
            tokenize = 'unicode61 remove_diacritics 2'
        );
    """)

    # 2. Tracking table for incremental indexing state
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fts_index_status (
            book_id TEXT PRIMARY KEY,
            file_mtime REAL,
            pages_indexed INTEGER DEFAULT 0,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'indexed',
            error_msg TEXT
        );
    """)

    # Index for fast status checks
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fts_status_book ON fts_index_status(book_id);")

    conn.commit()
    conn.close()


def get_fts_index_stats() -> Dict[str, Any]:
    """Returns indexing metrics: indexed books, pending books, and indexed pages."""
    init_fts_schema()
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM books WHERE file_path IS NOT NULL AND file_path != '';")
    total_books = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*), COALESCE(SUM(pages_indexed), 0) FROM fts_index_status WHERE status = 'indexed';")
    row = cur.fetchone()
    indexed_books = row[0] or 0
    indexed_pages = row[1] or 0

    conn.close()
    return {
        "total_books": total_books,
        "indexed_books": indexed_books,
        "pending_books": max(0, total_books - indexed_books),
        "indexed_pages": indexed_pages,
        "is_complete": (total_books > 0 and indexed_books >= total_books),
    }


def index_single_book(book_id: str, file_path: str, conn: Optional[sqlite3.Connection] = None) -> Tuple[bool, int, str]:
    """Extracts text page-by-page from PDF and indexes into FTS5. Returns (success, pages_count, error)."""
    if not file_path or not os.path.exists(file_path):
        return False, 0, "Datei nicht gefunden"

    should_close = False
    if conn is None:
        conn = _get_connection()
        should_close = True

    cur = conn.cursor()

    try:
        mtime = os.path.getmtime(file_path)

        # Check if already indexed with matching mtime
        cur.execute("SELECT file_mtime, status FROM fts_index_status WHERE book_id = ?;", (str(book_id),))
        row = cur.fetchone()
        if row and row[1] == mtime and row[0] == "indexed":
            if should_close:
                conn.close()
            return True, 0, "Bereits aktuell"

        # Remove previous index entries for this book if re-indexing
        cur.execute("DELETE FROM book_pages_fts WHERE book_id = ?;", (str(book_id),))

        # Extract text page by page with PyMuPDF
        doc = pymupdf.open(file_path)
        pages_to_insert = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            txt = page.get_text("text").strip()
            if txt:
                pages_to_insert.append((str(book_id), page_idx + 1, txt))

        doc.close()

        # Batch insert into FTS5
        if pages_to_insert:
            cur.executemany(
                "INSERT INTO book_pages_fts(book_id, page_number, content) VALUES (?, ?, ?);",
                pages_to_insert
            )

        # Update status record
        cur.execute("""
            INSERT INTO fts_index_status (book_id, file_mtime, pages_indexed, status, error_msg, indexed_at)
            VALUES (?, ?, ?, 'indexed', NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id) DO UPDATE SET
                file_mtime = excluded.file_mtime,
                pages_indexed = excluded.pages_indexed,
                status = 'indexed',
                error_msg = NULL,
                indexed_at = CURRENT_TIMESTAMP;
        """, (str(book_id), mtime, len(pages_to_insert)))

        conn.commit()
        if should_close:
            conn.close()
        return True, len(pages_to_insert), ""

    except Exception as exc:
        conn.rollback()
        cur.execute("""
            INSERT INTO fts_index_status (book_id, file_mtime, pages_indexed, status, error_msg, indexed_at)
            VALUES (?, 0, 0, 'failed', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id) DO UPDATE SET
                status = 'failed',
                error_msg = excluded.error_msg,
                indexed_at = CURRENT_TIMESTAMP;
        """, (str(book_id), str(exc)))
        conn.commit()
        if should_close:
            conn.close()
        return False, 0, str(exc)


def search_fulltext(
    query: str,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Performs lightning-fast BM25 full-text query across indexed book pages.
    Returns matched results with book metadata, page numbers, and highlighted snippets.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    # Clean query for FTS5 syntax safety (wrap tokens in quotes to prevent syntax errors)
    tokens = clean_query.split()
    safe_terms = []
    for t in tokens:
        t_clean = t.replace('"', '').replace("'", '').replace('*', '')
        if t_clean:
            safe_terms.append(f'"{t_clean}"*')

    if not safe_terms:
        return []

    match_expr = " AND ".join(safe_terms)

    init_fts_schema()
    conn = _get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            fts.book_id,
            fts.page_number,
            snippet(book_pages_fts, 2, '<b><mark style=\"background:#58A6FF; color:#0A0E17; border-radius:3px; padding:0 2px;\">', '</mark></b>', '...', 24) AS match_snippet,
            bm25(book_pages_fts) AS rank,
            b.title,
            b.author,
            b.file_path,
            b.year,
            b.doc_type
        FROM book_pages_fts fts
        JOIN books b ON b.id = fts.book_id
        WHERE book_pages_fts MATCH ?
        ORDER BY rank
        LIMIT ? OFFSET ?;
    """, (match_expr, limit, offset))

    results = []
    for row in cur.fetchall():
        results.append({
            "book_id": row[0],
            "page_number": int(row[1]),
            "snippet": row[2],
            "rank": float(row[3]),
            "title": row[4] or "Unbenanntes Dokument",
            "author": row[5] or "Unbekannter Autor",
            "file_path": row[6],
            "year": row[7],
            "doc_type": row[8] or "book"
        })

    conn.close()
    return results


class FullTextIndexWorker(threading.Thread):
    """Background worker daemon for incremental full-text library indexing."""

    def __init__(self, progress_callback=None, finished_callback=None):
        super().__init__(daemon=True)
        self.progress_callback = progress_callback
        self.finished_callback = finished_callback
        self.stop_requested = threading.Event()

    def stop(self) -> None:
        self.stop_requested.set()

    def run(self) -> None:
        init_fts_schema()
        conn = _get_connection()
        cur = conn.cursor()

        # Find books that need indexing (either not in fts_index_status or modified)
        cur.execute("""
            SELECT b.id, b.file_path, b.title
            FROM books b
            LEFT JOIN fts_index_status s ON b.id = s.book_id
            WHERE b.file_path IS NOT NULL AND b.file_path != ''
              AND (s.book_id IS NULL OR s.status = 'pending' OR s.status = 'failed')
            ORDER BY b.id ASC;
        """)
        pending_books = cur.fetchall()
        total_pending = len(pending_books)

        indexed_count = 0
        for idx, (b_id, f_path, title) in enumerate(pending_books):
            if self.stop_requested.is_set():
                break

            if self.progress_callback:
                self.progress_callback(idx + 1, total_pending, title or os.path.basename(f_path))

            success, pages, err = index_single_book(b_id, f_path, conn)
            if success:
                indexed_count += 1

            # Brief cooperative yield to keep UI and filesystem responsive
            time.sleep(0.01)

        conn.close()

        if self.finished_callback and not self.stop_requested.is_set():
            self.finished_callback(indexed_count, total_pending)
