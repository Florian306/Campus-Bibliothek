"""Persistent, thread-safe SQLite cache for instant (0ms) book classification and catalog lookups.
Caches ISBN, DOI, and file-fingerprints (size + head-hash).
"""

import hashlib
import os
import sqlite3
import time
from typing import Optional, Tuple
from core.models import BookAnalysis
from core.config import get_app_dir

CACHE_DB_PATH = os.path.join(get_app_dir(), "book_cache.db")


import threading

_local = threading.local()


def _init_db_schema(conn: sqlite3.Connection) -> None:
    # Init WAL mode and tables once
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_cache (
            file_hash TEXT PRIMARY KEY,
            file_size INTEGER,
            category TEXT,
            title TEXT,
            author TEXT,
            new_filename TEXT,
            confidence INTEGER,
            needs_review INTEGER,
            review_reason TEXT,
            timestamp REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS identifier_cache (
            identifier TEXT PRIMARY KEY,
            id_type TEXT,
            category TEXT,
            title TEXT,
            author TEXT,
            reason TEXT,
            timestamp REAL
        )
        """
    )
    conn.commit()


# Run once at module load
_init_conn = sqlite3.connect(CACHE_DB_PATH, timeout=10.0)
try:
    _init_db_schema(_init_conn)
finally:
    _init_conn.close()


def _get_connection() -> sqlite3.Connection:
    conn = getattr(_local, "connection", None)
    if conn is None:
        conn = sqlite3.connect(CACHE_DB_PATH, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        _local.connection = conn
    return conn


def compute_file_fingerprint(file_path: str) -> Optional[Tuple[str, int]]:
    """Generates a lightning-fast fingerprint from file path, size, and mtime (takes 0.0001s).
    Crucial for cloud-streamed drives (Google Drive / OneDrive) as it NEVER triggers cloud file downloads!
    """
    try:
        stat = os.stat(file_path)
        size = stat.st_size
        mtime = int(stat.st_mtime)
        norm_path = os.path.normpath(file_path).lower()
        key_str = f"{norm_path}:{size}:{mtime}"
        file_hash = hashlib.sha256(key_str.encode("utf-8")).hexdigest()
        return file_hash, size
    except Exception:
        return None


def get_cached_file(file_path: str) -> Optional[BookAnalysis]:
    """Retrieves full classification result from local cache if file is unchanged."""
    fp = compute_file_fingerprint(file_path)
    if not fp:
        return None
    file_hash, file_size = fp

    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT category, title, author, new_filename, confidence, needs_review, review_reason
                FROM file_cache WHERE file_hash = ? AND file_size = ?
                """,
                (file_hash, file_size),
            )
            row = cursor.fetchone()
            if row:
                return BookAnalysis(
                    kategorie=row[0],
                    titel=row[1],
                    autor=row[2],
                    neuer_dateiname=row[3],
                    confidence=row[4],
                    needs_review=bool(row[5]),
                    review_reason=f"[Cache] {row[6]}",
                )
    except Exception:
        pass
    return None


def save_cached_file(file_path: str, result: BookAnalysis) -> None:
    """Stores full classification result in local cache."""
    fp = compute_file_fingerprint(file_path)
    if not fp:
        return
    file_hash, file_size = fp

    try:
        with _get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO file_cache 
                (file_hash, file_size, category, title, author, new_filename, confidence, needs_review, review_reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_hash,
                    file_size,
                    result.kategorie,
                    result.titel,
                    result.autor,
                    result.neuer_dateiname,
                    result.confidence,
                    1 if result.needs_review else 0,
                    result.review_reason,
                    time.time(),
                ),
            )
    except Exception:
        pass


def get_cached_identifier(identifier: str) -> Optional[Tuple[str, str, str, str]]:
    """Retrieves cached (category, author, title, reason) for an ISBN or DOI.
    If previously marked as NOT_FOUND, returns ('NOT_FOUND', '', '', '') to prevent repeated network queries.
    """
    clean_id = identifier.strip().upper()
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT category, author, title, reason FROM identifier_cache WHERE identifier = ?",
                (clean_id,),
            )
            row = cursor.fetchone()
            if row:
                cat, auth, title, reason = row
                if cat == "NOT_FOUND":
                    return "NOT_FOUND", "", "", "[Negative Cache] Nicht im Katalog gefunden"
                return cat, auth, title, f"[Cache] {reason}"
    except Exception:
        pass
    return None


def save_cached_identifier(
    identifier: str, id_type: str, category: str, author: str, title: str, reason: str
) -> None:
    """Stores verified catalog metadata for an ISBN or DOI."""
    clean_id = identifier.strip().upper()
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO identifier_cache
                (identifier, id_type, category, author, title, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_id, id_type, category, author, title, reason, time.time()),
            )
    except Exception:
        pass
