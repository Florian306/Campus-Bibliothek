"""Core SQLite database controller for the Virtual Campus Library (Data-Lake architecture).
Manages books, multi-category associations, tags, reading desk, book notes, and edition alerts.
Zero-touch on actual PDF files; full indexing and management in local SQLite.
"""

import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from core.config import get_app_dir, get_database_path

DB_PATH = get_database_path()

_local = threading.local()
_db_write_lock = threading.Lock()


def get_db_connection() -> sqlite3.Connection:
    """Thread-safe SQLite connection factory with high-performance WAL and memory caching."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64 MB SQLite RAM cache
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA mmap_size = 268435456;")  # 256 MB memory-mapped I/O
        conn.execute("PRAGMA foreign_keys = ON;")
        _local.conn = conn
    return _local.conn


def init_library_schema() -> None:
    """Creates the relational schema for the virtual library."""
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS books (
                id TEXT PRIMARY KEY,
                file_path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT 'Unbekannt',
                isbn TEXT,
                doi TEXT,
                edition INTEGER DEFAULT 1,
                edition_str TEXT,
                year INTEGER,
                page_count INTEGER DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                file_mtime REAL DEFAULT 0,
                confidence INTEGER DEFAULT 100,
                audit_trail TEXT,
                summary TEXT,
                date_added REAL NOT NULL,
                last_opened REAL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS book_categories (
                book_id TEXT NOT NULL,
                category TEXT NOT NULL,
                is_primary INTEGER DEFAULT 0,
                PRIMARY KEY (book_id, category),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS book_tags (
                book_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (book_id, tag),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS desk_items (
                book_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'Am Lesen',
                current_page INTEGER DEFAULT 0,
                total_pages INTEGER DEFAULT 0,
                progress_pct INTEGER DEFAULT 0,
                borrowed_at REAL NOT NULL,
                last_read_at REAL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS book_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                page_number INTEGER,
                note_text TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS edition_alerts (
                book_id TEXT PRIMARY KEY,
                current_edition INTEGER NOT NULL,
                latest_edition INTEGER NOT NULL,
                latest_year INTEGER,
                latest_isbn TEXT,
                latest_title TEXT,
                source TEXT,
                is_dismissed INTEGER DEFAULT 0,
                checked_at REAL NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS research_papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT,
                abstract TEXT,
                category TEXT DEFAULT '',
                year INTEGER,
                journal TEXT,
                doi TEXT,
                arxiv_id TEXT,
                pdf_url TEXT,
                local_path TEXT,
                is_downloaded INTEGER DEFAULT 0,
                citation_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_textbooks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT,
                description TEXT,
                category TEXT DEFAULT '',
                year INTEGER,
                publisher TEXT,
                isbn TEXT,
                doi TEXT,
                cover_url TEXT,
                preview_url TEXT,
                page_count INTEGER DEFAULT 0,
                citation_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'DNB',
                created_at REAL NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS institution_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                institution_name TEXT NOT NULL DEFAULT 'FernUniversität in Hagen',
                ezproxy_prefix TEXT NOT NULL DEFAULT 'https://login.ub-proxy.fernuni-hagen.de/login?url=',
                shibboleth_domain TEXT DEFAULT 'idp.fernuni-hagen.de',
                auto_proxy INTEGER DEFAULT 1
            );
            """
        )
        cursor.execute("INSERT OR IGNORE INTO institution_config (id, institution_name, ezproxy_prefix) VALUES (1, 'FernUniversität in Hagen', 'https://login.ub-proxy.fernuni-hagen.de/login?url=');")

        try:
            cursor.execute("ALTER TABLE books ADD COLUMN summary TEXT;")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE research_papers ADD COLUMN category TEXT DEFAULT '';")
        except Exception:
            pass

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS study_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER UNIQUE NOT NULL,
                target_date REAL,
                daily_pages_target INTEGER DEFAULT 15,
                mode TEXT DEFAULT 'deadline',
                active_days_mask TEXT DEFAULT '1,1,1,1,1,1,1',
                buffer_days INTEGER DEFAULT 3,
                is_active INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )

        try:
            cursor.execute("ALTER TABLE study_plans ADD COLUMN plan_json TEXT;")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE study_plans ADD COLUMN complexity_score REAL DEFAULT 2.5;")
        except Exception:
            pass

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reading_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                pages_read INTEGER DEFAULT 0,
                completed_target INTEGER DEFAULT 0,
                xp_earned INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS book_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                main_book_id INTEGER NOT NULL,
                workbook_id INTEGER NOT NULL,
                match_score REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                UNIQUE(main_book_id, workbook_id)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_title TEXT,
                mode TEXT,
                score_percent INTEGER,
                grade TEXT,
                details_json TEXT,
                created_at REAL NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_gamification (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_xp INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                last_active_date TEXT DEFAULT '',
                level INTEGER DEFAULT 1,
                title TEXT DEFAULT 'Ersti'
            );
            """
        )
        cursor.execute("INSERT OR IGNORE INTO user_gamification (id, total_xp, current_streak, last_active_date, level, title) VALUES (1, 0, 0, '', 1, 'Ersti');")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_author ON books(author);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_book_cats_cat ON book_categories(category);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_book_tags_tag ON book_tags(tag);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_book_notes_bid ON book_notes(book_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_desk_items_bid ON desk_items(book_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_year ON research_papers(year);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_cat ON research_papers(category);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_study_plans_bid ON study_plans(book_id);")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS book_covers (
                book_id TEXT PRIMARY KEY,
                cover_data BLOB NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                event_date TEXT NOT NULL,
                location TEXT DEFAULT '',
                category TEXT DEFAULT 'Uni',
                source TEXT DEFAULT 'local',
                created_at REAL NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS book_extracts (
                id TEXT PRIMARY KEY,
                parent_book_id TEXT NOT NULL,
                title TEXT NOT NULL,
                file_path TEXT NOT NULL,
                page_range TEXT,
                page_count INTEGER DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                on_desk INTEGER DEFAULT 0,
                notes TEXT,
                FOREIGN KEY (parent_book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extracts_parent ON book_extracts(parent_book_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extracts_desk ON book_extracts(on_desk);")

        conn.commit()
    finally:
        conn.close()


init_library_schema()


def save_book_cover_blob(book_id: str, cover_bytes: bytes) -> bool:
    """Stores binary cover image in database."""
    conn = get_db_connection()
    with _db_write_lock:
        try:
            conn.execute(
                """
                INSERT INTO book_covers (book_id, cover_data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    cover_data = excluded.cover_data,
                    updated_at = excluded.updated_at
                """,
                (book_id, sqlite3.Binary(cover_bytes), time.time()),
            )
            conn.commit()
            return True
        except Exception:
            return False


def get_book_cover_blob(book_id: str) -> Optional[bytes]:
    """Retrieves binary cover image from database."""
    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT cover_data FROM book_covers WHERE book_id = ?", (book_id,))
        row = cur.fetchone()
        if row and row["cover_data"]:
            return bytes(row["cover_data"])
        return None
    except Exception:
        return None


def delete_book_cover_blob(book_id: str) -> bool:
    """Deletes cached cover from database."""
    conn = get_db_connection()
    with _db_write_lock:
        try:
            conn.execute("DELETE FROM book_covers WHERE book_id = ?", (book_id,))
            conn.commit()
            return True
        except Exception:
            return False


def add_calendar_event(
    title: str,
    event_date: str,
    start_time: str,
    end_time: str = "",
    location: str = "",
    category: str = "Uni",
    source: str = "local"
) -> int:
    """Adds a calendar event to the database."""
    conn = get_db_connection()
    with _db_write_lock:
        cur = conn.execute(
            """
            INSERT INTO calendar_events (title, event_date, start_time, end_time, location, category, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, event_date, start_time, end_time, location, category, source, time.time())
        )
        conn.commit()
        return cur.lastrowid or 0


def get_calendar_events_for_date(date_str: str) -> List[Dict[str, Any]]:
    """Returns all events scheduled for a specific date (YYYY-MM-DD), ordered by start_time."""
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT * FROM calendar_events WHERE event_date = ? ORDER BY start_time ASC",
        (date_str,)
    )
    return [dict(r) for r in cur.fetchall()]


def get_upcoming_calendar_events(days: int = 7) -> List[Dict[str, Any]]:
    """Returns upcoming events starting from today for the given number of days."""
    import datetime
    today = datetime.date.today().isoformat()
    end_date = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT * FROM calendar_events WHERE event_date >= ? AND event_date <= ? ORDER BY event_date ASC, start_time ASC",
        (today, end_date)
    )
    return [dict(r) for r in cur.fetchall()]


def delete_calendar_event(event_id: int) -> bool:
    """Deletes a calendar event by ID."""
    conn = get_db_connection()
    with _db_write_lock:
        try:
            conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
            conn.commit()
            return True
        except Exception:
            return False


def clear_synced_calendar_events() -> None:
    """Removes previously synced iCal events before re-importing."""
    conn = get_db_connection()
    with _db_write_lock:
        try:
            conn.execute("DELETE FROM calendar_events WHERE source = 'ical'")
            conn.commit()
        except Exception:
            pass


def compute_file_id(file_path: str, size: int) -> str:
    """Generates a stable identifier based on path and file size."""
    import hashlib
    h = hashlib.sha256(f"{file_path}_{size}".encode("utf-8", errors="ignore")).hexdigest()
    return h[:16]


def upsert_book(
    file_path: str,
    filename: str,
    title: str,
    author: str,
    categories: List[str],
    isbn: Optional[str] = None,
    doi: Optional[str] = None,
    edition: int = 1,
    edition_str: Optional[str] = None,
    year: Optional[int] = None,
    page_count: int = 0,
    file_size: int = 0,
    file_mtime: float = 0.0,
    confidence: int = 100,
    audit_trail: str = "",
    tags: Optional[List[str]] = None,
) -> str:
    """Inserts or updates a book and its multi-category assignments in the library database."""
    book_id = compute_file_id(file_path, file_size)
    now = time.time()

    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO books (
                    id, file_path, filename, title, author, isbn, doi,
                    edition, edition_str, year, page_count, file_size, file_mtime,
                    confidence, audit_trail, date_added
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    filename = excluded.filename,
                    title = excluded.title,
                    author = excluded.author,
                    isbn = COALESCE(excluded.isbn, books.isbn),
                    doi = COALESCE(excluded.doi, books.doi),
                    edition = excluded.edition,
                    edition_str = excluded.edition_str,
                    year = COALESCE(excluded.year, books.year),
                    page_count = excluded.page_count,
                    file_size = excluded.file_size,
                    file_mtime = excluded.file_mtime,
                    confidence = excluded.confidence,
                    audit_trail = excluded.audit_trail;
                """,
                (
                    book_id, file_path, filename, title, author, isbn, doi,
                    edition, edition_str, year, page_count, file_size, file_mtime,
                    confidence, audit_trail, now
                ),
            )

            # Existing row keeps its original id (e.g. after file rename)
            row = conn.execute("SELECT id FROM books WHERE file_path = ?", (file_path,)).fetchone()
            if row:
                book_id = row["id"]

            # Update categories
            conn.execute("DELETE FROM book_categories WHERE book_id = ?", (book_id,))
            for idx, cat in enumerate(categories):
                if cat and cat.strip():
                    conn.execute(
                        "INSERT OR IGNORE INTO book_categories (book_id, category, is_primary) VALUES (?, ?, ?)",
                        (book_id, cat.strip(), 1 if idx == 0 else 0)
                    )

            # Update tags
            if tags:
                for tag in tags:
                    if tag and tag.strip():
                        conn.execute(
                            "INSERT OR IGNORE INTO book_tags (book_id, tag) VALUES (?, ?)",
                            (book_id, tag.strip())
                        )

    return book_id


def get_all_books(
    search_query: str = "",
    category_filter: str = "",
    tag_filter: str = "",
    sort_by: str = "title",
    ascending: bool = True
) -> List[Dict[str, Any]]:
    """Fetches books with category list, desk status, and edition alert flag."""
    conn = get_db_connection()
    sql = """
        SELECT 
            b.*,
            (SELECT GROUP_CONCAT(category, ' | ') FROM book_categories WHERE book_id = b.id) AS categories_str,
            (SELECT category FROM book_categories WHERE book_id = b.id AND is_primary = 1) AS primary_category,
            (SELECT GROUP_CONCAT(tag, ', ') FROM book_tags WHERE book_id = b.id) AS tags_str,
            (SELECT 1 FROM desk_items WHERE book_id = b.id) AS is_on_desk,
            (SELECT current_page FROM desk_items WHERE book_id = b.id) AS current_page,
            (SELECT progress_pct FROM desk_items WHERE book_id = b.id) AS reading_progress,
            (SELECT latest_edition FROM edition_alerts WHERE book_id = b.id AND is_dismissed = 0) AS new_edition_available,
            (SELECT COUNT(*) FROM book_extracts WHERE parent_book_id = b.id) AS extract_count
        FROM books b
        WHERE 1=1
    """
    params: List[Any] = []

    if search_query.strip():
        q = f"%{search_query.strip()}%"
        sql += " AND (b.title LIKE ? OR b.author LIKE ? OR b.filename LIKE ? OR b.isbn LIKE ?)"
        params.extend([q, q, q, q])

    if category_filter and category_filter != "Alle":
        sql += " AND EXISTS (SELECT 1 FROM book_categories bc WHERE bc.book_id = b.id AND bc.category = ?)"
        params.append(category_filter)

    if tag_filter and tag_filter != "Alle":
        sql += " AND EXISTS (SELECT 1 FROM book_tags bt WHERE bt.book_id = b.id AND bt.tag = ?)"
        params.append(tag_filter)

    order_col = "b.title"
    if sort_by == "author":
        order_col = "b.author"
    elif sort_by == "date_added":
        order_col = "b.date_added"
    elif sort_by == "year":
        order_col = "b.year"

    direction = "ASC" if ascending else "DESC"
    sql += f" ORDER BY {order_col} {direction};"

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()
    return [dict(r) for r in rows]


def get_book_by_id(book_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a single book by ID with all joined desk, category, and extract fields."""
    conn = get_db_connection()
    sql = """
        SELECT 
            b.*,
            (SELECT GROUP_CONCAT(category, ' | ') FROM book_categories WHERE book_id = b.id) AS categories_str,
            (SELECT category FROM book_categories WHERE book_id = b.id AND is_primary = 1) AS primary_category,
            (SELECT GROUP_CONCAT(tag, ', ') FROM book_tags WHERE book_id = b.id) AS tags_str,
            (SELECT 1 FROM desk_items WHERE book_id = b.id) AS is_on_desk,
            (SELECT current_page FROM desk_items WHERE book_id = b.id) AS current_page,
            (SELECT progress_pct FROM desk_items WHERE book_id = b.id) AS reading_progress,
            (SELECT latest_edition FROM edition_alerts WHERE book_id = b.id AND is_dismissed = 0) AS new_edition_available,
            (SELECT COUNT(*) FROM book_extracts WHERE parent_book_id = b.id) AS extract_count
        FROM books b
        WHERE b.id = ?;
    """
    row = conn.execute(sql, (str(book_id),)).fetchone()
    return dict(row) if row else None


def get_desk_books() -> List[Dict[str, Any]]:
    """Retrieves all books currently placed on the virtual desk."""
    conn = get_db_connection()
    sql = """
        SELECT 
            b.*,
            d.status,
            d.current_page,
            d.total_pages,
            d.progress_pct,
            d.progress_pct AS progress_percent,
            d.borrowed_at,
            d.last_read_at,
            (SELECT GROUP_CONCAT(category, ' | ') FROM book_categories WHERE book_id = b.id) AS categories_str,
            (SELECT COUNT(*) FROM book_notes WHERE book_id = b.id) AS notes_count
        FROM desk_items d
        JOIN books b ON b.id = d.book_id
        ORDER BY d.last_read_at DESC, d.borrowed_at DESC;
    """
    cursor = conn.execute(sql)
    return [dict(r) for r in cursor.fetchall()]


def toggle_desk_item(book_id: str, start_page: int = 1) -> bool:
    """Adds a book to the desk if absent (with optional start_page), or removes it if already present. Returns new on-desk status."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            cur = conn.execute("SELECT book_id FROM desk_items WHERE book_id = ?", (book_id,))
            exists = cur.fetchone() is not None
            if exists:
                conn.execute("DELETE FROM desk_items WHERE book_id = ?", (book_id,))
                return False
            else:
                cur_p = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
                tot = cur_p["page_count"] if cur_p else 0
                now = time.time()
                curr_p = max(1, int(start_page)) if start_page else 1
                pct = min(100, max(0, int((curr_p / tot) * 100))) if tot and tot > 0 else 0
                conn.execute(
                    """
                    INSERT INTO desk_items (book_id, status, current_page, total_pages, progress_pct, borrowed_at, last_read_at)
                    VALUES (?, 'Am Lesen', ?, ?, ?, ?, ?);
                    """,
                    (book_id, curr_p, tot, pct, now, now)
                )
                return True


def update_reading_progress(book_id: Any, current_page: int) -> None:
    """Updates reading progress page number and percentage."""
    bid = str(book_id)
    curr_p = max(1, int(current_page))
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            row = conn.execute(
                """
                SELECT d.total_pages, b.page_count 
                FROM desk_items d 
                JOIN books b ON b.id = d.book_id 
                WHERE d.book_id = ?;
                """,
                (bid,)
            ).fetchone()
            tot = 1
            if row:
                tot = row["total_pages"] if row["total_pages"] and row["total_pages"] > 0 else (row["page_count"] or 1)
            if tot <= 0:
                tot = 1
            pct = min(100, max(0, int((curr_p / tot) * 100)))
            status = "Abgeschlossen" if pct >= 100 else "Am Lesen"
            conn.execute(
                """
                UPDATE desk_items 
                SET current_page = ?, total_pages = ?, progress_pct = ?, status = ?, last_read_at = ?
                WHERE book_id = ?;
                """,
                (curr_p, tot, pct, status, time.time(), bid)
            )


def get_book_notes(book_id: str) -> List[Dict[str, Any]]:
    """Returns all notes for a specific book."""
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT * FROM book_notes WHERE book_id = ? ORDER BY page_number ASC, created_at DESC;",
        (book_id,)
    )
    return [dict(r) for r in cur.fetchall()]


def add_book_note(book_id: str, note_text: str, page_number: Optional[int] = None) -> int:
    """Creates a new note for a book."""
    now = time.time()
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO book_notes (book_id, page_number, note_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (book_id, page_number, note_text.strip(), now, now)
            )
            return cur.lastrowid


def delete_book_note(note_id: int) -> None:
    """Deletes a note."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM book_notes WHERE id = ?", (note_id,))


# -------------------------------------------------------------
# Book Extracts / Attached Chapters System
# -------------------------------------------------------------

def add_book_extract(
    parent_book_id: str,
    title: str,
    file_path: str,
    page_range: str = "",
    page_count: int = 0,
    file_size: int = 0,
    on_desk: bool = False,
    notes: str = ""
) -> str:
    """Attaches an extracted chapter/page excerpt to a parent book."""
    import uuid
    extract_id = f"ext_{uuid.uuid4().hex[:12]}"
    now = time.time()
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO book_extracts (
                    id, parent_book_id, title, file_path, page_range,
                    page_count, file_size, created_at, on_desk, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    extract_id,
                    str(parent_book_id),
                    title.strip() or "Kapitelauszug",
                    os.path.normpath(file_path),
                    page_range.strip(),
                    int(page_count),
                    int(file_size),
                    now,
                    1 if on_desk else 0,
                    notes.strip()
                )
            )
    return extract_id


def get_book_extracts(parent_book_id: str) -> List[Dict[str, Any]]:
    """Retrieves all attached chapters/extracts for a book."""
    conn = get_db_connection()
    cur = conn.execute(
        """
        SELECT * FROM book_extracts 
        WHERE parent_book_id = ? 
        ORDER BY created_at ASC;
        """,
        (str(parent_book_id),)
    )
    return [dict(r) for r in cur.fetchall()]


def delete_book_extract(extract_id: str, delete_file: bool = False) -> bool:
    """Deletes an attached extract record and optionally removes the PDF from disk."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            row = conn.execute("SELECT file_path FROM book_extracts WHERE id = ?", (str(extract_id),)).fetchone()
            if not row:
                return False
            fpath = row["file_path"]
            conn.execute("DELETE FROM book_extracts WHERE id = ?", (str(extract_id),))

    if delete_file and fpath and os.path.isfile(fpath):
        try:
            os.remove(fpath)
        except OSError:
            pass
    return True


def delete_all_book_extracts(parent_book_id: str, delete_folder: bool = True) -> int:
    """Deletes all attached extracts for a book, cleans up PDF files, and removes the chapter folder if empty/requested."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            rows = conn.execute("SELECT file_path FROM book_extracts WHERE parent_book_id = ?", (str(parent_book_id),)).fetchall()
            if not rows:
                return 0
            file_paths = [r["file_path"] for r in rows if r["file_path"]]
            conn.execute("DELETE FROM book_extracts WHERE parent_book_id = ?", (str(parent_book_id),))

    folders_to_clean = set()
    for fp in file_paths:
        if fp and os.path.isfile(fp):
            folders_to_clean.add(os.path.dirname(fp))
            try:
                os.remove(fp)
            except OSError:
                pass

    if delete_folder:
        import shutil
        for folder in folders_to_clean:
            if folder and os.path.isdir(folder):
                # Ensure we only remove chapter-specific folders like *_Kapitel
                folder_name = os.path.basename(folder)
                if folder_name.endswith("_Kapitel") or folder_name.lower() in ("kapitel", "extracts", "auszüge"):
                    try:
                        shutil.rmtree(folder, ignore_errors=True)
                    except OSError:
                        pass
                else:
                    # If it's a general folder, remove it only if it is completely empty
                    try:
                        os.rmdir(folder)
                    except OSError:
                        pass

    return len(file_paths)


def toggle_extract_desk(extract_id: str) -> bool:
    """Toggles on_desk status for an attached extract."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            cur = conn.execute("SELECT on_desk FROM book_extracts WHERE id = ?", (str(extract_id),))
            row = cur.fetchone()
            if not row:
                return False
            new_val = 0 if row["on_desk"] else 1
            conn.execute("UPDATE book_extracts SET on_desk = ? WHERE id = ?", (new_val, str(extract_id)))
            return bool(new_val)


def get_desk_extracts() -> List[Dict[str, Any]]:
    """Retrieves all extracted chapters placed on the virtual desk, joined with parent book info."""
    conn = get_db_connection()
    sql = """
        SELECT 
            e.*,
            b.title AS parent_title,
            b.author AS parent_author
        FROM book_extracts e
        JOIN books b ON b.id = e.parent_book_id
        WHERE e.on_desk = 1
        ORDER BY e.created_at DESC;
    """
    cur = conn.execute(sql)
    return [dict(r) for r in cur.fetchall()]


def get_category_counts() -> List[Tuple[str, int]]:
    """Returns sorted categories with active book counts."""
    conn = get_db_connection()
    cur = conn.execute(
        """
        SELECT bc.category, COUNT(DISTINCT bc.book_id) AS cnt
        FROM book_categories bc
        JOIN books b ON b.id = bc.book_id
        GROUP BY bc.category
        ORDER BY cnt DESC;
        """
    )
    return [(r["category"], r["cnt"]) for r in cur.fetchall()]


def get_edition_alerts() -> List[Dict[str, Any]]:
    """Retrieves all active edition alert recommendations."""
    conn = get_db_connection()
    sql = """
        SELECT 
            b.id AS book_id,
            b.title,
            b.author,
            b.file_path,
            ea.current_edition,
            ea.latest_edition,
            ea.latest_year,
            ea.latest_isbn,
            ea.latest_title,
            ea.source
        FROM edition_alerts ea
        JOIN books b ON b.id = ea.book_id
        WHERE ea.is_dismissed = 0
        ORDER BY ea.latest_edition - ea.current_edition DESC;
    """
    cur = conn.execute(sql)
    return [dict(r) for r in cur.fetchall()]


def save_edition_alert(
    book_id: str,
    current_edition: int,
    latest_edition: int,
    latest_year: Optional[int],
    latest_isbn: Optional[str],
    latest_title: Optional[str],
    source: str = "Deutsche Nationalbibliothek DNB"
) -> None:
    """Stores a newer edition discovery alert."""
    now = time.time()
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO edition_alerts (
                    book_id, current_edition, latest_edition, latest_year,
                    latest_isbn, latest_title, source, is_dismissed, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    latest_edition = excluded.latest_edition,
                    latest_year = excluded.latest_year,
                    latest_isbn = excluded.latest_isbn,
                    latest_title = excluded.latest_title,
                    source = excluded.source,
                    checked_at = excluded.checked_at;
                """,
                (book_id, current_edition, latest_edition, latest_year, latest_isbn, latest_title, source, now)
            )


def dismiss_edition_alert(book_id: str) -> None:
    """Dismisses an edition alert so it stops triggering warnings."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE edition_alerts SET is_dismissed = 1 WHERE book_id = ?", (book_id,))


def open_pdf_in_system_viewer(file_path: str) -> bool:
    """Launches the PDF file directly in Windows default PDF viewer without moving it."""
    if not os.path.exists(file_path):
        return False
    try:
        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE books SET last_opened = ? WHERE file_path = ?", (time.time(), file_path))
        os.startfile(os.path.normpath(file_path))
        return True
    except Exception:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", os.path.normpath(file_path)], shell=False)
            return True
        except Exception:
            return False


def open_pdf_in_edge(file_path: str, page: int = 1) -> bool:
    """Launches the PDF file directly in Microsoft Edge at a specific page number."""
    if not os.path.exists(file_path):
        return False
    try:
        conn = get_db_connection()
        with conn:
            conn.execute("UPDATE books SET last_opened = ? WHERE file_path = ?", (time.time(), file_path))
    except Exception:
        pass

    # Verify if file is indeed a valid PDF binary before invoking Edge PDF viewer
    try:
        with open(file_path, "rb") as f:
            header = f.read(512)
        if not (header.startswith(b"%PDF") or b"%PDF" in header):
            # Non-PDF payload (e.g. HTML landing page), open in default web browser / viewer
            return open_pdf_in_system_viewer(file_path)
    except Exception:
        pass

    target_page = max(1, int(page)) if page else 1
    abs_path = os.path.abspath(file_path)

    # 1. Primary: Direct launch via Edge executable with local file path
    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    edge_exe = None
    for cand in edge_candidates:
        if os.path.isfile(cand):
            edge_exe = cand
            break

    if edge_exe:
        # Prepare launch argument: file URI with #page=N if page > 1, else raw absolute path
        arg = abs_path
        if target_page > 1:
            try:
                import pathlib
                arg = pathlib.Path(abs_path).resolve().as_uri() + f"#page={target_page}"
            except Exception:
                arg = abs_path
        try:
            subprocess.Popen([edge_exe, arg])
            return True
        except Exception:
            pass

    # 2. Secondary: Fallback to Windows Shell open
    try:
        ret = subprocess.run(["cmd", "/c", "start", "", "msedge", abs_path], capture_output=True, text=True, check=False)
        if ret.returncode == 0:
            return True
    except Exception:
        pass

    try:
        os.startfile(abs_path)
        return True
    except Exception:
        return open_pdf_in_system_viewer(abs_path)


def open_pdf_at_page(file_path: str, page: int = 1) -> bool:
    """Launches the PDF directly at a specific page number in Microsoft Edge."""
    return open_pdf_in_edge(file_path, page)


def get_book_desk_page(book_id: str) -> Optional[int]:
    """Returns saved current_page from desk_items if the book is on the desk, else None."""
    conn = get_db_connection()
    row = conn.execute("SELECT current_page FROM desk_items WHERE book_id = ?", (book_id,)).fetchone()
    if row and row["current_page"] is not None:
        return row["current_page"]
    return None



def get_book_categories(book_id: str) -> List[Dict[str, Any]]:
    """Returns list of categories assigned to a book, sorted with primary first."""
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT category, is_primary FROM book_categories WHERE book_id = ? ORDER BY is_primary DESC, category ASC;",
        (book_id,)
    )
    return [dict(r) for r in cur.fetchall()]


def set_book_categories(book_id: str, categories: List[str], primary_category: Optional[str] = None) -> bool:
    """Assigns multiple categories to a book, designating the primary faculty."""
    cleaned = []
    for c in categories:
        c_str = (c or "").strip()
        if c_str and c_str not in cleaned:
            cleaned.append(c_str)
    if not cleaned:
        cleaned = ["Sonstiges"]

    prim = primary_category if (primary_category and primary_category in cleaned) else cleaned[0]

    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM book_categories WHERE book_id = ?", (book_id,))
            for cat in cleaned:
                conn.execute(
                    "INSERT OR IGNORE INTO book_categories (book_id, category, is_primary) VALUES (?, ?, ?)",
                    (book_id, cat, 1 if cat == prim else 0)
                )
            conn.execute(
                "UPDATE books SET audit_trail = ? WHERE id = ?",
                (f"[Kategorien] Zugewiesen: {', '.join(cleaned)} (Haupt: {prim})", book_id)
            )
    return True


def toggle_book_category(book_id: str, category: str) -> bool:
    """Adds or removes a category from a book. Preserves at least 1 category."""
    cat = category.strip()
    current = get_book_categories(book_id)
    cat_names = [c["category"] for c in current]
    primary_cat = next((c["category"] for c in current if c.get("is_primary")), None)

    if cat in cat_names:
        if len(cat_names) <= 1:
            return False  # Do not remove the last remaining category
        new_list = [c for c in cat_names if c != cat]
        new_prim = primary_cat if primary_cat != cat else new_list[0]
        return set_book_categories(book_id, new_list, new_prim)
    else:
        new_list = cat_names + [cat]
        return set_book_categories(book_id, new_list, primary_cat)


def set_primary_category(book_id: str, primary_category: str) -> bool:
    """Sets which assigned category is the primary faculty."""
    prim = primary_category.strip()
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO book_categories (book_id, category, is_primary) VALUES (?, ?, 0)",
                (book_id, prim)
            )
            conn.execute("UPDATE book_categories SET is_primary = 0 WHERE book_id = ?", (book_id,))
            conn.execute("UPDATE book_categories SET is_primary = 1 WHERE book_id = ? AND category = ?", (book_id, prim))
    return True


def update_book_category(book_id: str, new_category: str) -> bool:
    """Updates the primary category of a book and records the change."""
    return set_book_categories(book_id, [new_category], new_category)


def update_book_metadata(
    book_id: str,
    title: str,
    author: str,
    category: Optional[str] = None,
    categories: Optional[List[str]] = None,
    primary_category: Optional[str] = None
) -> bool:
    """Updates title, author and multi-category assignments of a book."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                "UPDATE books SET title = ?, author = ? WHERE id = ?",
                (title.strip(), author.strip(), book_id)
            )

    if categories is not None:
        set_book_categories(book_id, categories, primary_category)
    elif category:
        set_book_categories(book_id, [category], category)

    return True


def auto_reclassify_library() -> int:
    """Re-analyzes all indexed books with the improved classifier and corrects misclassifications."""
    from ai.classifier import classify_textbook
    from ai.sanity import perform_sanity_check

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id, b.title, b.filename, b.file_path, bc.category
        FROM books b
        JOIN book_categories bc ON b.id = bc.book_id
        WHERE bc.is_primary = 1
    """)
    rows = cur.fetchall()

    updated_count = 0
    for row in rows:
        b_id, title, fname, fpath, curr_cat = row
        det_cat, det_conf, det_expl = classify_textbook(f"{fname} {title}", "")

        if det_cat != "Sonstiges" and det_cat != curr_cat:
            if curr_cat == "Geschichte & Politik":
                genuine_history = any(w in f"{fname} {title}".lower() for w in [
                    "geschichte", "politik", "krieg", "reich", "weimar", "hitler", "nsdap",
                    "auschwitz", "holocaust", "mittelalter", "antike", "archäolog", "militär",
                    "bundesarchiv", "dejure", "verfolgung", "shoah", "quellenedition", "extremismus",
                    "islamismus", "burgen", "europäische union", "zeitgeschichte", "slawen", "polen",
                    "sowjetunion", "revolution", "bündnis"
                ])
                if not genuine_history and det_conf >= 70:
                    final_cat, conf, _, reason = perform_sanity_check(det_cat, fname, title, "", det_conf, det_expl)
                    if final_cat != curr_cat:
                        update_book_category(b_id, final_cat)
                        updated_count += 1
                        continue

            if det_conf >= 80:
                final_cat, conf, _, reason = perform_sanity_check(det_cat, fname, title, "", det_conf, det_expl)
                if final_cat != curr_cat:
                    update_book_category(b_id, final_cat)
                    updated_count += 1

    return updated_count


def cleanup_library_titles() -> int:
    """Cleans all book titles and authors across the library database:
    - Strips catalog foreign-title brackets "[Original] ; Translated"
    - Strips layout/InDesign file names (.indd) and extracts real titles from PDF front matter
    - Formats VEJ series books with proper series and volume headers
    - Extracts missing authors from clean filename patterns
    - Synchronizes changes to local SQLite cache
    """
    from ai.isbn_lookup import clean_catalog_title
    from ai.pipeline import clean_filename_to_title

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, filename, author, file_path FROM books")
    rows = cur.fetchall()

    updated = 0
    with _db_write_lock:
        with conn:
            for r in rows:
                b_id, title, fname, author, fpath = r
                new_title = (title or "").replace('\x00', '').strip()
                new_author = (author or "Unbekannt").replace('\x00', '').strip()
                clean_fname = (fname or "").replace('\x00', '').strip()

                # Clean author roles
                if new_author:
                    new_author = re.sub(
                        r'\[?\s*(?:Illustrator(?:in)?|Grafik(?:er)?|Redaktion|Red\.|Hrsg\.|Herausgeber|Fotograf(?:in)?|Bearb\.|Bearbeiter|Mitarb\.|Mitarbeiter)\s*\]?',
                        '', new_author, flags=re.IGNORECASE
                    )
                    new_author = new_author.replace('[', '').replace(']', '').strip()
                    if new_author.lower() in ('sjoerg', 'admin', 'user', 'author', 'scan', 'root', 'unknown', 'alin.cason', 'fk'):
                        new_author = "Unbekannt"

                # 1. Strip catalog [foreign] ; prefix
                if "[" in new_title and ";" in new_title:
                    new_title = clean_catalog_title(new_title)

                # 2. Strip [extra materials]
                new_title = re.sub(
                    r'\s*-\s*\[(?:extra materials|elektronische ressource|online-ausgabe|e-book|cd-rom|dvd|tag für tag[^\]]*)\]',
                    '', new_title, flags=re.IGNORECASE
                )
                new_title = re.sub(
                    r'\s*\[(?:extra materials|elektronische ressource|online-ausgabe|e-book|cd-rom|dvd|tag für tag[^\]]*)\]',
                    '', new_title, flags=re.IGNORECASE
                )

                # 3. Check if title is junk, boilerplate, or ISBN
                boilerplate_set = {
                    'copyright', 'author', 'this page intentionally left blank', 'table of contents',
                    'contents', 'preface', 'inhaltsverzeichnis', 'vorwort', 'impressum', 'cover',
                    'title', 'untitled', 'frontmatter', 'titelei', 'danksagung', 'acknowledgements'
                }
                low_t = new_title.lower()
                is_junk = (
                    not new_title
                    or len(new_title) < 3
                    or low_t in boilerplate_set
                    or any(low_t.startswith(b) for b in boilerplate_set)
                    or bool(re.search(r'\.(?:indd|indb|qxd|doc|docx|tex|rtf|pdf|pmd)$', new_title, re.IGNORECASE))
                    or bool(re.match(r'^(?:97[89]\d{10}|\d{9}[\dX]|\d{10,13})$', new_title))
                    or bool(re.match(r'^(?:\+?\d+_|pub_|cr_|mb_|book_)[0-9a-z_]+', new_title, re.IGNORECASE))
                    or any(j in low_t for j in ["titelei", "frontmatter", "cover", "impressum", "unbenannt", "untitled", "oceanofpdf.com"])
                )

                if is_junk:
                    vis_t, vis_a = None, None
                    if os.path.exists(fpath):
                        try:
                            import pymupdf
                            doc = pymupdf.open(fpath)
                            from ai.pdf_extractor import extract_visual_title_and_author
                            vis_t, vis_a = extract_visual_title_and_author(doc)
                            doc.close()
                        except Exception:
                            pass

                    vis_clean = vis_t.lower() if vis_t else ""
                    if vis_t and vis_clean not in boilerplate_set and not any(vis_clean.startswith(b) for b in boilerplate_set) and not bool(re.search(r'\.(?:indd|indb|qxd|pdf)$', vis_t, re.IGNORECASE)):
                        new_title = vis_t
                        if vis_a and new_author == "Unbekannt":
                            new_author = vis_a
                    else:
                        fa, ft = clean_filename_to_title(clean_fname)
                        new_title = ft
                        if fa != "Unbekannt" and new_author == "Unbekannt":
                            new_author = fa

                if new_title.lower().endswith('.pdf'):
                    new_title = new_title[:-4].strip()

                # 4. Fix specific known series / titles
                if '1_Joanne-K.-Rowling' in new_title or 'Harry-Potter-Book-1' in new_title or 'Harry-Potter' in clean_fname:
                    new_title = "Harry Potter and the Philosopher's Stone"
                    new_author = "J. K. Rowling"
                    # Update category to Sprach- & Literaturwissenschaft
                    conn.execute("DELETE FROM book_categories WHERE book_id = ?", (b_id,))
                    conn.execute("INSERT INTO book_categories (book_id, category) VALUES (?, ?)", (b_id, "Sprach- & Literaturwissenschaft"))
                elif 'English-for-Everyone' in clean_fname or 'English-for-Everyone' in new_title:
                    fa, ft = clean_filename_to_title(clean_fname)
                    new_title = ft
                    new_author = "DK Publishing"
                elif clean_fname in ('Physik 7_8.pdf', 'Physik 7-8.pdf', 'Physik 7 8.pdf') or new_title in ('Physik 7 8', 'Physik 7_8'):
                    new_title = "Physik 7./8. Schuljahr"
                elif 'kugler' in clean_fname.lower() or 'kugler' in new_title.lower():
                    new_title = "Der menschliche Körper - Anatomie, Physiologie, Pathologie"
                    new_author = "Peter Kugler"

                # 5. Fix VEJ series books
                vej_m = re.match(r'^Band\s+(\d+)\s+(?:(Polen|Sowjetunion|West-|Besetztes|Slowakei|Ungarn|Deutsches Reich).*)$', new_title, re.IGNORECASE)
                if vej_m:
                    b_num = vej_m.group(1)
                    sub = new_title[vej_m.start(2):].strip(" -_.:")
                    new_title = f"VEJ Band {b_num}: {sub}"
                    if new_author == "Unbekannt":
                        new_author = "Institut für Zeitgeschichte (Hg.)"

                # 6. Check if author is still Unbekannt and filename has author
                if new_author == "Unbekannt":
                    fa, ft = clean_filename_to_title(clean_fname)
                    if fa != "Unbekannt":
                        new_author = fa

                new_title = re.sub(r'\s+', ' ', new_title).strip()
                new_author = re.sub(r'\s+', ' ', new_author).strip()

                if new_title != title or new_author != author:
                    conn.execute(
                        "UPDATE books SET title = ?, author = ? WHERE id = ?",
                        (new_title, new_author, b_id)
                    )
                    updated += 1

    # Also sync updated titles to book_cache.db
    if updated > 0:
        try:
            from core.cache_manager import CACHE_DB_PATH
            import sqlite3
            c_conn = sqlite3.connect(CACHE_DB_PATH)
            with c_conn:
                for r in rows:
                    cur2 = conn.cursor()
                    cur2.execute("SELECT title, author, filename FROM books WHERE id = ?", (r[0],))
                    row2 = cur2.fetchone()
                    if row2:
                        c_conn.execute(
                            "UPDATE file_cache SET title = ?, author = ? WHERE new_filename = ? OR title = ?",
                            (row2[0], row2[1], row2[2], r[1])
                        )
            c_conn.close()
        except Exception:
            pass

    return updated


def backfill_library_isbns(max_workers: int = 5) -> int:
    """Scans existing PDF files in library without ISBN concurrently and extracts verified ISBNs."""
    import fitz
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ai.isbn_lookup import extract_isbns

    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, file_path, file_size FROM books WHERE file_path IS NOT NULL AND (isbn IS NULL OR isbn = '') ORDER BY file_size ASC;"
    ).fetchall()

    if not rows:
        return 0

    items = [(r["id"], r["file_path"], r["file_size"] or 0) for r in rows]

    def _worker(item):
        b_id, fpath, fsize = item
        if not fpath or not os.path.exists(fpath):
            return None
        # Skip oversized files on cloud storage during quick scan
        if fsize > 65 * 1024 * 1024:
            return None
        try:
            doc = fitz.open(fpath)
            text = ""
            for p in range(min(8, len(doc))):
                text += doc[p].get_text("text") + "\n"
            doc.close()
            isbns = extract_isbns(text)
            if isbns:
                return (isbns[0], b_id)
        except Exception:
            pass
        return None

    updated_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(_worker, it): it for it in items}
        batch = []
        for fut in as_completed(future_map):
            try:
                res = fut.result()
                if res:
                    batch.append(res)
                    if len(batch) >= 15:
                        with _db_write_lock:
                            with conn:
                                conn.executemany("UPDATE books SET isbn = ? WHERE id = ?", batch)
                        updated_count += len(batch)
                        batch.clear()
            except Exception:
                continue

        if batch:
            with _db_write_lock:
                with conn:
                    conn.executemany("UPDATE books SET isbn = ? WHERE id = ?", batch)
            updated_count += len(batch)

    return updated_count


def update_book_year(book_id: str, year: Optional[int]) -> bool:
    """Updates the publication year of a book in library.db."""
    try:
        with _db_write_lock:
            conn = get_db_connection()
            with conn:
                conn.execute("UPDATE books SET year = ? WHERE id = ?", (year, book_id))
        return True
    except Exception:
        return False


def update_book_summary(book_id: str, summary: str) -> bool:
    """Saves AI-generated abstract / summary for a book in library.db."""
    try:
        with _db_write_lock:
            conn = get_db_connection()
            with conn:
                conn.execute("UPDATE books SET summary = ? WHERE id = ?", (summary.strip(), book_id))
        return True
    except Exception:
        return False


def get_book_summary(book_id: str) -> Optional[str]:
    """Retrieves cached AI-generated summary for a book."""
    try:
        conn = get_db_connection()
        row = conn.execute("SELECT summary FROM books WHERE id = ?", (book_id,)).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def resolve_or_extract_book_year(book: Dict[str, Any]) -> Optional[int]:
    """Retrieves existing year or extracts it on-the-fly from the PDF file, persisting the result."""
    current_year = book.get("year")
    if current_year and isinstance(current_year, int) and current_year > 0:
        return current_year

    b_id = book.get("id")
    fpath = book.get("file_path")
    fname = book.get("filename") or ""

    if not fpath or not os.path.exists(fpath):
        return None

    try:
        import fitz
        from ai.pdf_extractor import extract_publication_year

        doc = fitz.open(fpath)
        snippet = ""
        for p in range(min(6, len(doc))):
            snippet += doc[p].get_text("text") + "\n"
        meta = doc.metadata or {}
        doc.close()

        extracted_year = extract_publication_year(snippet, meta, fname)
        if extracted_year and b_id:
            update_book_year(b_id, extracted_year)
            book["year"] = extracted_year
            return extracted_year
    except Exception:
        pass

    return None


def backfill_library_years(max_workers: int = 4) -> int:
    """Scans existing PDF files in library without year concurrently and extracts publication years."""
    import fitz
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ai.pdf_extractor import extract_publication_year

    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, file_path, filename, file_size FROM books WHERE file_path IS NOT NULL AND year IS NULL ORDER BY file_size ASC;"
    ).fetchall()

    if not rows:
        return 0

    items = [(r["id"], r["file_path"], r["filename"] or "", r["file_size"] or 0) for r in rows]

    def _worker(item):
        b_id, fpath, fname, fsize = item
        if not fpath or not os.path.exists(fpath):
            return None
        if fsize > 75 * 1024 * 1024:
            return None
        try:
            doc = fitz.open(fpath)
            text = ""
            for p in range(min(6, len(doc))):
                text += doc[p].get_text("text") + "\n"
            meta = doc.metadata or {}
            doc.close()
            y = extract_publication_year(text, meta, fname)
            if y:
                return (y, b_id)
        except Exception:
            pass
        return None

    updated_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(_worker, it): it for it in items}
        batch = []
        for fut in as_completed(future_map):
            try:
                res = fut.result()
                if res:
                    batch.append(res)
                    if len(batch) >= 15:
                        with _db_write_lock:
                            with conn:
                                conn.executemany("UPDATE books SET year = ? WHERE id = ?", batch)
                        updated_count += len(batch)
                        batch.clear()
            except Exception:
                continue

        if batch:
            with _db_write_lock:
                with conn:
                    conn.executemany("UPDATE books SET year = ? WHERE id = ?", batch)
            updated_count += len(batch)

    return updated_count


def optimize_library_catalog(
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[Any] = None,
) -> Dict[str, int]:
    """Performs a comprehensive, single-pass catalog optimization:
    1. Re-classifies ambiguous categories using smart academic scoring
    2. Cleans up InDesign/catalog junk titles & roles
    3. Concurrently resolves missing ISBNs and publication years from PDF imprint pages
    Supports non-blocking background progress callbacks and cancellation.
    """
    import fitz
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ai.isbn_lookup import extract_isbns
    from ai.pdf_extractor import extract_publication_year

    if progress_callback:
        progress_callback(0, 100, "Fachbereiche & Kategorien optimieren...")

    cat_count = auto_reclassify_library()

    if stop_event and stop_event.is_set():
        return {"categories": cat_count, "titles": 0, "isbns": 0, "years": 0}

    if progress_callback:
        progress_callback(10, 100, "Buchtitel & Autoren bereinigen...")

    title_count = cleanup_library_titles()

    if stop_event and stop_event.is_set():
        return {"categories": cat_count, "titles": title_count, "isbns": 0, "years": 0}

    # Combined single-pass for ISBN & Year
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, file_path, filename, file_size, isbn, year, title
        FROM books
        WHERE file_path IS NOT NULL AND (isbn IS NULL OR isbn = '' OR year IS NULL)
        ORDER BY file_size ASC;
        """
    ).fetchall()

    isbn_updated = 0
    year_updated = 0

    total_pending = len(rows)
    if total_pending == 0:
        if progress_callback:
            progress_callback(100, 100, "Katalog ist bereits vollständig!")
        return {"categories": cat_count, "titles": title_count, "isbns": 0, "years": 0}

    items = [
        (
            r["id"],
            r["file_path"],
            r["filename"] or "",
            r["file_size"] or 0,
            bool(not r["isbn"]),
            bool(r["year"] is None),
            r["title"] or r["filename"] or "Buch",
        )
        for r in rows
    ]

    # Cloud drives (Google Drive / OneDrive) safety: max 2-3 workers to prevent IO starvation
    max_workers = 3

    def _worker(item):
        if stop_event and stop_event.is_set():
            return None
        b_id, fpath, fname, fsize, need_isbn, need_year, b_title = item
        if not fpath or not os.path.exists(fpath):
            return None
        if fsize > 80 * 1024 * 1024:
            return None

        found_isbn = None
        found_year = None
        try:
            doc = fitz.open(fpath)
            snippet = ""
            for p in range(min(6, len(doc))):
                snippet += doc[p].get_text("text") + "\n"
            meta = doc.metadata or {}
            doc.close()

            if need_isbn:
                isbns = extract_isbns(snippet)
                if isbns:
                    found_isbn = isbns[0]

            if need_year:
                found_year = extract_publication_year(snippet, meta, fname)

        except Exception:
            pass

        return b_id, found_isbn, found_year, b_title

    done_count = 0
    isbn_batch = []
    year_batch = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(_worker, it): it for it in items}

        for fut in as_completed(future_map):
            if stop_event and stop_event.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break

            done_count += 1
            try:
                res = fut.result()
                if res:
                    b_id, f_isbn, f_year, b_title = res
                    if f_isbn:
                        isbn_batch.append((f_isbn, b_id))
                    if f_year:
                        year_batch.append((f_year, b_id))

                    if progress_callback:
                        pct = int(10 + (done_count / total_pending) * 90)
                        short_title = b_title if len(b_title) < 35 else b_title[:32] + "..."
                        progress_callback(pct, 100, f"Prüfe {done_count}/{total_pending}: {short_title}")

                    # Commit periodically
                    if len(isbn_batch) >= 10:
                        with _db_write_lock:
                            with conn:
                                conn.executemany("UPDATE books SET isbn = ? WHERE id = ?", isbn_batch)
                        isbn_updated += len(isbn_batch)
                        isbn_batch.clear()

                    if len(year_batch) >= 10:
                        with _db_write_lock:
                            with conn:
                                conn.executemany("UPDATE books SET year = ? WHERE id = ?", year_batch)
                        year_updated += len(year_batch)
                        year_batch.clear()

            except Exception:
                continue

        # Flush remaining
        if isbn_batch:
            with _db_write_lock:
                with conn:
                    conn.executemany("UPDATE books SET isbn = ? WHERE id = ?", isbn_batch)
            isbn_updated += len(isbn_batch)

        if year_batch:
            with _db_write_lock:
                with conn:
                    conn.executemany("UPDATE books SET year = ? WHERE id = ?", year_batch)
            year_updated += len(year_batch)

    if progress_callback:
        progress_callback(100, 100, "Optimierung abgeschlossen!")

    return {
        "categories": cat_count,
        "titles": title_count,
        "isbns": isbn_updated,
        "years": year_updated,
    }


# =========================================================================
# RESEARCH PAPER LAB & INSTITUTION SETTINGS (FERNUNI HAGEN ETC.)
# =========================================================================

def save_research_paper(paper: Dict[str, Any]) -> str:
    """Stores a scientific research paper in the local research archive."""
    import uuid
    pid = paper.get("id") or str(uuid.uuid4())
    now = time.time()
    category = (paper.get("category") or "").strip()
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_papers (
                    id, title, authors, abstract, category, year, journal, doi,
                    arxiv_id, pdf_url, local_path, is_downloaded, citation_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    pid,
                    paper.get("title", "Unbekanntes Paper").strip(),
                    paper.get("authors", "").strip(),
                    paper.get("abstract", "").strip(),
                    category,
                    paper.get("year"),
                    paper.get("journal", "").strip(),
                    paper.get("doi", "").strip(),
                    paper.get("arxiv_id", "").strip(),
                    paper.get("pdf_url", "").strip(),
                    paper.get("local_path", "").strip(),
                    1 if paper.get("local_path") else 0,
                    paper.get("citation_count", 0),
                    now
                )
            )
    return pid


def get_all_research_papers(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all saved scientific papers from the user's research archive, optionally filtered by category."""
    conn = get_db_connection()
    if category and category != "Alle":
        cur = conn.execute("SELECT * FROM research_papers WHERE category = ? ORDER BY created_at DESC;", (category,))
    else:
        cur = conn.execute("SELECT * FROM research_papers ORDER BY created_at DESC;")
    return [dict(r) for r in cur.fetchall()]


def get_paper_category_counts() -> List[Tuple[str, int]]:
    """Returns paper counts grouped by category."""
    conn = get_db_connection()
    cur = conn.execute("SELECT category, COUNT(*) FROM research_papers WHERE category != '' GROUP BY category ORDER BY COUNT(*) DESC;")
    return cur.fetchall()


def delete_research_paper(
    paper_id: str,
    local_path: Optional[str] = None,
    title: Optional[str] = None,
    doi: Optional[str] = None,
) -> bool:
    """Removes a paper from the research archive and safely removes the local file from disk."""
    target_file = local_path
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            # Match by id, doi, or exact title to guarantee removal
            cur = conn.execute(
                "SELECT id, local_path FROM research_papers WHERE id = ? OR (doi != '' AND doi = ?) OR (title != '' AND title = ?)",
                (paper_id or "", doi or "", title or "")
            )
            rows = cur.fetchall()
            found_ids = []
            for r in rows:
                found_ids.append(r["id"])
                if not target_file and r["local_path"]:
                    target_file = r["local_path"]

            for fid in found_ids:
                conn.execute("DELETE FROM research_papers WHERE id = ?", (fid,))

    # Robust local file deletion (with retry for OneDrive / Google Drive locks)
    if target_file and os.path.exists(target_file):
        def _robust_remove(path_to_delete: str):
            for _ in range(6):
                try:
                    if os.path.exists(path_to_delete):
                        os.chmod(path_to_delete, 0o777)
                        os.remove(path_to_delete)
                    break
                except Exception:
                    time.sleep(0.3)

        t = threading.Thread(target=_robust_remove, args=(target_file,), daemon=True)
        t.start()
        t.join(timeout=1.0)

    return True


def get_institution_settings() -> Dict[str, Any]:
    """Retrieves current university proxy configuration."""
    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM institution_config WHERE id = 1;")
    row = cur.fetchone()
    if row:
        return dict(row)
    return {
        "institution_name": "FernUniversität in Hagen",
        "ezproxy_prefix": "https://login.ub-proxy.fernuni-hagen.de/login?url=",
        "shibboleth_domain": "idp.fernuni-hagen.de",
        "auto_proxy": 1
    }


def update_institution_settings(institution_name: str, ezproxy_prefix: str, auto_proxy: bool = True) -> None:
    """Updates the university proxy configuration."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                UPDATE institution_config
                SET institution_name = ?, ezproxy_prefix = ?, auto_proxy = ?
                WHERE id = 1;
                """,
                (institution_name.strip(), ezproxy_prefix.strip(), 1 if auto_proxy else 0)
            )


def find_saved_research_paper(paper_id: Optional[str] = None, doi: Optional[str] = None, title: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Checks if a paper is already saved in the local archive by ID, DOI, or title."""
    conn = get_db_connection()
    if paper_id:
        cur = conn.execute("SELECT * FROM research_papers WHERE id = ? LIMIT 1;", (paper_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
    if doi:
        clean_doi = doi.replace("https://doi.org/", "").strip()
        cur = conn.execute("SELECT * FROM research_papers WHERE doi LIKE ? LIMIT 1;", (f"%{clean_doi}%",))
        row = cur.fetchone()
        if row:
            return dict(row)
    if title:
        cur = conn.execute("SELECT * FROM research_papers WHERE LOWER(title) = ? LIMIT 1;", (title.strip().lower(),))
        row = cur.fetchone()
        if row:
            return dict(row)
    return None


# =========================================================================
# SAVED TEXTBOOKS & ACADEMIC MONOGRAPHS (WUNSCHLISTE / VORMERKUNGEN)
# =========================================================================

def save_textbook(book: Dict[str, Any]) -> str:
    """Stores a curated textbook in the user's wishlist/saved textbooks catalogue."""
    import uuid
    bid = str(book.get("id") or uuid.uuid4())
    now = time.time()
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO saved_textbooks (
                    id, title, authors, description, category, year, publisher,
                    isbn, doi, cover_url, preview_url, page_count, citation_count, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    bid,
                    book.get("title", "Unbekanntes Fachbuch").strip(),
                    book.get("authors", "").strip(),
                    book.get("description", "").strip(),
                    (book.get("category") or "").strip(),
                    book.get("year"),
                    (book.get("publisher") or "").strip(),
                    (book.get("isbn") or "").strip(),
                    (book.get("doi") or "").strip(),
                    (book.get("cover_url") or "").strip(),
                    (book.get("preview_url") or "").strip(),
                    book.get("page_count", 0),
                    book.get("citation_count", 0),
                    book.get("source", "DNB / Google"),
                    now
                )
            )
    return bid


def get_all_saved_textbooks(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all saved textbooks/monographs, optionally filtered by academic faculty."""
    conn = get_db_connection()
    if category and category != "Alle":
        cur = conn.execute("SELECT * FROM saved_textbooks WHERE category = ? ORDER BY created_at DESC;", (category,))
    else:
        cur = conn.execute("SELECT * FROM saved_textbooks ORDER BY created_at DESC;")
    return [dict(r) for r in cur.fetchall()]


def delete_saved_textbook(book_id: str) -> bool:
    """Removes a textbook from the user's saved wishlist."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM saved_textbooks WHERE id = ?;", (book_id,))
    return True


def find_saved_textbook(book_id: Optional[str] = None, isbn: Optional[str] = None, title: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Checks if a textbook is already saved in the user's catalogue."""
    conn = get_db_connection()
    if book_id:
        cur = conn.execute("SELECT * FROM saved_textbooks WHERE id = ? LIMIT 1;", (book_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
    if isbn:
        clean_isbn = "".join(c for c in isbn if c.isdigit())
        if clean_isbn:
            cur = conn.execute("SELECT * FROM saved_textbooks WHERE replace(replace(isbn, '-', ''), ' ', '') LIKE ? LIMIT 1;", (f"%{clean_isbn}%",))
            row = cur.fetchone()
            if row:
                return dict(row)
    if title:
        cur = conn.execute("SELECT * FROM saved_textbooks WHERE LOWER(title) = ? LIMIT 1;", (title.strip().lower(),))
        row = cur.fetchone()
        if row:
            return dict(row)
    return None


# -------------------------------------------------------------
# Study Planner, Active Recall & Gamification Layer
# -------------------------------------------------------------

LEVEL_RANKS = [
    (1, 0, "Ersti"),
    (2, 250, "Tutor"),
    (3, 750, "Bachelor"),
    (4, 1500, "Master"),
    (5, 3000, "Doktorand"),
    (6, 6000, "Professor"),
    (7, 10000, "Bibliotheks-Titan"),
]


def get_study_plan(book_id: Any) -> Optional[Dict[str, Any]]:
    """Retrieves active study plan for a book if configured."""
    bid = str(book_id)
    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM study_plans WHERE book_id = ? AND is_active = 1 LIMIT 1;", (bid,))
    row = cur.fetchone()
    return dict(row) if row else None


def save_study_plan(
    book_id: Any,
    target_date: float,
    daily_pages: int = 15,
    mode: str = "deadline",
    active_days_mask: str = "1,1,1,1,1,1,1",
    buffer_days: int = 3,
) -> None:
    """Creates or updates a study plan for a book."""
    bid = str(book_id)
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO study_plans (book_id, target_date, daily_pages_target, mode, active_days_mask, buffer_days, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    target_date = excluded.target_date,
                    daily_pages_target = excluded.daily_pages_target,
                    mode = excluded.mode,
                    active_days_mask = excluded.active_days_mask,
                    buffer_days = excluded.buffer_days,
                    is_active = 1;
                """,
                (bid, target_date, daily_pages, mode, active_days_mask, buffer_days, time.time())
            )


def delete_study_plan(book_id: Any) -> None:
    """Removes or deactivates study plan for a book."""
    bid = str(book_id)
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM study_plans WHERE book_id = ?;", (bid,))


def save_habit_study_plan(book_id: Any, plan_data: Dict[str, Any]) -> None:
    """Saves structured habit study plan (including complexity and timeline) to SQLite."""
    import json
    bid = str(book_id)
    plan_json = json.dumps(plan_data, ensure_ascii=False)
    complexity = plan_data.get("complexity", {}).get("difficulty_score", 2.5) if isinstance(plan_data, dict) else 2.5
    daily_pages = plan_data.get("daily_pages", 15) if isinstance(plan_data, dict) else 15
    target_date = plan_data.get("target_date", 0.0) if isinstance(plan_data, dict) else 0.0
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO study_plans (book_id, target_date, daily_pages_target, mode, active_days_mask, buffer_days, is_active, created_at, plan_json, complexity_score)
                VALUES (?, ?, ?, 'habit', '1,1,1,1,1,1,1', 0, 1, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    target_date = excluded.target_date,
                    daily_pages_target = excluded.daily_pages_target,
                    mode = 'habit',
                    plan_json = excluded.plan_json,
                    complexity_score = excluded.complexity_score,
                    is_active = 1;
                """,
                (bid, target_date, daily_pages, time.time(), plan_json, complexity)
            )


def get_habit_study_plan(book_id: Any) -> Optional[Dict[str, Any]]:
    """Retrieves full structured habit study plan from SQLite."""
    import json
    bid = str(book_id)
    conn = get_db_connection()
    cur = conn.execute("SELECT plan_json, complexity_score FROM study_plans WHERE book_id = ? AND is_active = 1 LIMIT 1;", (bid,))
    row = cur.fetchone()
    if row and row["plan_json"]:
        try:
            data = json.loads(row["plan_json"])
            if isinstance(data, dict):
                data["complexity_score"] = row["complexity_score"]
                return data
        except Exception:
            pass
    return None


def calculate_study_plan_metrics(book_id: Any) -> Dict[str, Any]:
    """Calculates live adaptive daily target, remaining pages, days left, and current pace."""
    bid = str(book_id)
    conn = get_db_connection()
    plan_row = conn.execute("SELECT * FROM study_plans WHERE book_id = ? AND is_active = 1;", (bid,)).fetchone()
    book_row = conn.execute("SELECT * FROM books WHERE id = ?;", (bid,)).fetchone()
    desk_row = conn.execute("SELECT current_page FROM desk_items WHERE book_id = ?;", (bid,)).fetchone()

    if not plan_row or not book_row:
        return {"has_plan": False}

    plan = dict(plan_row)
    total_pages = book_row["page_count"] or 100
    curr_page = desk_row["current_page"] if desk_row else (book_row["current_page"] or 1)
    pages_left = max(0, total_pages - curr_page)

    now = time.time()
    today_str = time.strftime("%Y-%m-%d")

    # Read today
    today_log = conn.execute("SELECT pages_read, completed_target FROM reading_logs WHERE book_id = ? AND log_date = ?;", (bid, today_str)).fetchone()
    pages_today = today_log["pages_read"] if today_log else 0

    mode = plan.get("mode", "deadline")
    target_date = plan.get("target_date") or (now + 86400 * 30)
    seconds_left = max(0, target_date - now)
    days_left = max(1, int(seconds_left / 86400))

    buffer_days = plan.get("buffer_days", 3)
    effective_days = max(1, days_left - buffer_days)

    if mode == "deadline":
        daily_target = max(1, int((pages_left + pages_today + effective_days - 1) // effective_days))
    else:
        daily_target = plan.get("daily_pages_target") or 15

    progress_today_pct = min(100, int((pages_today / daily_target) * 100)) if daily_target > 0 else 100
    is_today_done = pages_today >= daily_target

    target_date_str = time.strftime("%d.%m.%Y", time.localtime(target_date))

    return {
        "has_plan": True,
        "mode": mode,
        "target_date_str": target_date_str,
        "days_left": days_left,
        "pages_left": pages_left,
        "daily_target": daily_target,
        "pages_today": pages_today,
        "progress_today_pct": progress_today_pct,
        "is_today_done": is_today_done,
        "curr_page": curr_page,
        "total_pages": total_pages,
    }


def log_daily_reading(book_id: Any, pages_delta: int) -> int:
    """Logs reading progress for today, updates streaks and awards XP."""
    if pages_delta <= 0:
        return 0

    bid = str(book_id)
    today_str = time.strftime("%Y-%m-%d")
    xp_to_award = pages_delta * 5  # 5 XP per page read

    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            cur = conn.execute("SELECT id, pages_read, completed_target FROM reading_logs WHERE book_id = ? AND log_date = ?;", (bid, today_str))
            row = cur.fetchone()
            if row:
                new_read = row["pages_read"] + pages_delta
                conn.execute("UPDATE reading_logs SET pages_read = ?, xp_earned = xp_earned + ? WHERE id = ?;", (new_read, xp_to_award, row["id"]))
            else:
                conn.execute(
                    "INSERT INTO reading_logs (book_id, log_date, pages_read, completed_target, xp_earned, created_at) VALUES (?, ?, ?, 0, ?, ?);",
                    (bid, today_str, pages_delta, xp_to_award, time.time())
                )

    # Award user XP and update streak
    add_user_xp(xp_to_award)
    return xp_to_award


def get_gamification_profile() -> Dict[str, Any]:
    """Returns current XP, rank, level, and streak for the user."""
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM user_gamification WHERE id = 1;").fetchone()
    if not row:
        return {"total_xp": 0, "current_streak": 0, "level": 1, "title": "Ersti"}
    d = dict(row)

    # Calculate next level info
    curr_lvl = d["level"]
    next_rank = next((r for r in LEVEL_RANKS if r[0] == curr_lvl + 1), None)
    curr_rank = next((r for r in LEVEL_RANKS if r[0] == curr_lvl), LEVEL_RANKS[0])

    if next_rank:
        xp_needed = next_rank[1] - curr_rank[1]
        xp_progress = max(0, d["total_xp"] - curr_rank[1])
        pct = min(100, int((xp_progress / xp_needed) * 100))
        d["next_title"] = next_rank[2]
        d["xp_for_next"] = next_rank[1]
        d["progress_pct"] = pct
    else:
        d["next_title"] = "Max Level"
        d["xp_for_next"] = d["total_xp"]
        d["progress_pct"] = 100

    return d


def add_user_xp(xp_amount: int) -> Dict[str, Any]:
    """Adds XP, updates streak if day changed, and levels up rank if threshold crossed."""
    today_str = time.strftime("%Y-%m-%d")
    yesterday_str = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))

    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            row = conn.execute("SELECT * FROM user_gamification WHERE id = 1;").fetchone()
            total_xp = (row["total_xp"] if row else 0) + max(0, xp_amount)
            streak = row["current_streak"] if row else 0
            last_date = row["last_active_date"] if row else ""

            if last_date == yesterday_str:
                streak += 1
                last_date = today_str
            elif last_date != today_str:
                streak = 1
                last_date = today_str

            # Calculate level
            lvl = 1
            title = "Ersti"
            for rank_lvl, req_xp, rank_title in LEVEL_RANKS:
                if total_xp >= req_xp:
                    lvl = rank_lvl
                    title = rank_title

            conn.execute(
                "UPDATE user_gamification SET total_xp = ?, current_streak = ?, last_active_date = ?, level = ?, title = ? WHERE id = 1;",
                (total_xp, streak, last_date, lvl, title)
            )

    return get_gamification_profile()


get_gamification_status = get_gamification_profile


def save_book_pair(main_book_id: Any, workbook_id: Any, match_score: float = 1.0) -> None:
    """Persists a textbook <-> workbook pairing."""
    mid = str(main_book_id)
    wid = str(workbook_id)
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO book_pairs (main_book_id, workbook_id, match_score, created_at) VALUES (?, ?, ?, ?);",
                (mid, wid, match_score, time.time())
            )


def get_book_pair(book_id: Any) -> Optional[Dict[str, Any]]:
    """Returns companion workbook or textbook for a book if linked."""
    bid = str(book_id)
    conn = get_db_connection()
    # Check if book_id is main
    cur = conn.execute(
        """
        SELECT b.*, bp.match_score, 'workbook' as pair_role
        FROM book_pairs bp
        JOIN books b ON b.id = bp.workbook_id
        WHERE bp.main_book_id = ?
        LIMIT 1;
        """,
        (bid,)
    )
    row = cur.fetchone()
    if row:
        return dict(row)

    # Check if book_id is workbook
    cur = conn.execute(
        """
        SELECT b.*, bp.match_score, 'main_book' as pair_role
        FROM book_pairs bp
        JOIN books b ON b.id = bp.main_book_id
        WHERE bp.workbook_id = ?
        LIMIT 1;
        """,
        (bid,)
    )
    row = cur.fetchone()
    return dict(row) if row else None


def save_quiz_result(book_id: Any, chapter_title: str, mode: str, score_percent: int, grade: str, details_json: str) -> None:
    """Stores quiz or exam simulator history."""
    bid = str(book_id)
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO quiz_history (book_id, chapter_title, mode, score_percent, grade, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (bid, chapter_title, mode, score_percent, grade, details_json, time.time())
            )


def get_quiz_history(limit: int = 150, mode_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves past exam and quiz records with book and paper titles."""
    conn = get_db_connection()
    query = """
        SELECT 
            qh.id,
            qh.book_id,
            qh.chapter_title,
            qh.mode,
            qh.score_percent,
            qh.grade,
            qh.details_json,
            qh.created_at,
            COALESCE(b.title, rp.title, 'Unbekanntes Werk') AS source_title,
            COALESCE(b.author, rp.authors, '') AS source_author,
            COALESCE(b.file_path, rp.local_path, '') AS source_path
        FROM quiz_history qh
        LEFT JOIN books b ON CAST(b.id AS TEXT) = CAST(qh.book_id AS TEXT)
        LEFT JOIN research_papers rp ON rp.id = CAST(qh.book_id AS TEXT)
    """
    params = []
    if mode_filter:
        query += " WHERE qh.mode = ?"
        params.append(mode_filter)

    query += " ORDER BY qh.created_at DESC LIMIT ?;"
    params.append(limit)

    cursor = conn.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_exam_statistics() -> Dict[str, Any]:
    """Calculates overall examination statistics (GPA, pass rate, count)."""
    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT 
            COUNT(*) as total_exams,
            AVG(score_percent) as avg_percent,
            SUM(CASE WHEN score_percent >= 50 THEN 1 ELSE 0 END) as passed_exams
        FROM quiz_history;
        """
    )
    row = cursor.fetchone()
    total = row["total_exams"] if row and row["total_exams"] else 0
    avg_pct = round(row["avg_percent"], 1) if row and row["avg_percent"] is not None else 0.0
    passed = row["passed_exams"] if row and row["passed_exams"] else 0
    pass_rate = round((passed / total) * 100, 1) if total > 0 else 0.0

    # Calculate German GPA from grade strings (e.g. '1.3', '2.0', '5.0')
    grade_rows = conn.execute("SELECT grade FROM quiz_history WHERE grade IS NOT NULL;").fetchall()
    numeric_grades = []
    for gr in grade_rows:
        g_text = gr["grade"] or ""
        # Match leading float like '1.3' or '2.0'
        m = re.search(r"(\d+[.,]\d+)", g_text)
        if m:
            val = float(m.group(1).replace(",", "."))
            if 1.0 <= val <= 5.0:
                numeric_grades.append(val)

    gpa = round(sum(numeric_grades) / len(numeric_grades), 2) if numeric_grades else 0.0

    return {
        "total_exams": total,
        "avg_percent": avg_pct,
        "passed_exams": passed,
        "pass_rate": pass_rate,
        "gpa": gpa,
    }


def delete_quiz_history_item(history_id: int) -> bool:
    """Removes a single quiz history entry."""
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            cur = conn.execute("DELETE FROM quiz_history WHERE id = ?;", (history_id,))
            return cur.rowcount > 0


def save_web_research_article(title: str, url: str, domain: str, snippet: str, summary: str = "") -> str:
    """Saves a web research article into the persistent research papers archive."""
    import hashlib
    article_id = f"web_{hashlib.md5(url.encode('utf-8')).hexdigest()[:12]}"
    now = time.time()
    with _db_write_lock:
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO research_papers (
                    id, title, authors, abstract, category, year, journal, doi, arxiv_id, pdf_url, local_path, is_downloaded, citation_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    abstract = excluded.abstract,
                    title = excluded.title;
                """,
                (
                    article_id,
                    title.strip(),
                    domain,
                    summary.strip() if summary else snippet.strip(),
                    "Web-Recherche",
                    int(time.strftime("%Y")),
                    domain,
                    "",
                    "",
                    url,
                    "",
                    0,
                    0,
                    now
                )
            )
    return article_id


def delete_book(book_id: str, delete_file: bool = False) -> Tuple[bool, Optional[str]]:
    """Deletes a book from the virtual catalog database and associated records.
    Optionally deletes the physical PDF file from the disk.
    Returns (success, error_message).
    """
    bid = str(book_id).strip()
    if not bid:
        return False, "Ungültige Buch-ID."

    conn = get_db_connection()
    file_path_to_delete: Optional[str] = None

    with _db_write_lock:
        try:
            with conn:
                row = conn.execute("SELECT file_path FROM books WHERE id = ?;", (bid,)).fetchone()
                if not row:
                    return False, "Buch wurde in der Datenbank nicht gefunden."
                file_path_to_delete = row["file_path"]

                # Explicit cleanup in related tables (in case foreign keys aren't active)
                conn.execute("DELETE FROM book_categories WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM book_tags WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM desk_items WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM book_notes WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM edition_alerts WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM study_plans WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM reading_logs WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM quiz_history WHERE book_id = ?;", (bid,))
                conn.execute("DELETE FROM book_pairs WHERE main_book_id = ? OR workbook_id = ?;", (bid, bid))
                conn.execute("DELETE FROM book_covers WHERE book_id = ?;", (bid,))

                # Delete main book record
                conn.execute("DELETE FROM books WHERE id = ?;", (bid,))

        except Exception as e:
            return False, f"Datenbankfehler beim Löschen: {e}"

    # Also clear in-memory cover cache
    try:
        from core.cover_manager import _MEMORY_CACHE
        _MEMORY_CACHE.pop(bid, None)
    except Exception:
        pass

    # Delete physical file if requested
    if delete_file and file_path_to_delete:
        try:
            if os.path.isfile(file_path_to_delete):
                os.remove(file_path_to_delete)
        except Exception as e:
            return True, f"Buch aus Katalog entfernt, aber Datei konnte nicht gelöscht werden: {e}"

    return True, None


def get_search_cache(cache_key: str, max_age_seconds: int = 86400) -> Optional[List[Dict[str, Any]]]:
    """Retrieves cached search results if not expired."""
    import json
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "SELECT results_json, created_at FROM search_cache WHERE cache_key = ?;",
            (cache_key,)
        )
        row = cur.fetchone()
        if not row:
            return None
        created_at = row["created_at"]
        if time.time() - created_at > max_age_seconds:
            return None
        return json.loads(row["results_json"])
    except Exception:
        return None


def set_search_cache(cache_key: str, results: List[Dict[str, Any]]) -> None:
    """Stores search results in SQLite cache."""
    import json
    conn = get_db_connection()
    with _db_write_lock:
        try:
            results_json = json.dumps(results, ensure_ascii=False)
            with conn:
                conn.execute(
                    """
                    INSERT INTO search_cache (cache_key, results_json, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        results_json = excluded.results_json,
                        created_at = excluded.created_at;
                    """,
                    (cache_key, results_json, time.time())
                )
        except Exception:
            pass

