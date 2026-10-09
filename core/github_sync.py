"""GitHub Cloud Synchronization & Backup Service for Campus-Bibliothek.
Syncs library metadata, reading progress, and book notes to a private GitHub Gist.
Zero dependencies beyond Python standard library (urllib.request, json, gzip).
"""

import gzip
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.config import get_database_path, load_app_config, save_app_config

GIST_FILENAME = "campus_library_sync.json.gz"
GIST_DESCRIPTION = "Campus-Bibliothek • Encrypted & Compressed Private Cloud Backup"


class GitHubSyncService:
    """Manages cloud sync of library metadata, reading progress, and notes via GitHub Gist."""

    @staticmethod
    def test_token(token: str) -> Tuple[bool, str]:
        """Tests if the GitHub token is valid and has gist permission."""
        if not token or not token.strip():
            return False, "Token ist leer."
        url = "https://api.github.com/user"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token.strip()}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Campus-Bibliothek-App",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                login = data.get("login", "Unbekannt")
                return True, f"Erfolgreich verbunden als @{login}"
        except urllib.error.HTTPError as e:
            return False, f"GitHub Fehler {e.code}: Ungültiges Token oder keine Berechtigung."
        except Exception as e:
            return False, f"Netzwerkfehler: {str(e)}"

    @staticmethod
    def export_library_data() -> Dict[str, Any]:
        """Extracts portable library data (books metadata, notes, progress) from SQLite."""
        db_path = get_database_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Books metadata
        cur.execute("""
            SELECT id, file_path, filename, title, author, isbn, doi, edition, edition_str,
                   year, page_count, current_page, is_on_desk, desk_priority, desk_added_at,
                   publisher, series, volume, tags, added_at, last_opened_at, read_status
            FROM books
        """)
        books = [dict(r) for r in cur.fetchall()]

        # Book Notes
        notes = []
        try:
            cur.execute("""
                SELECT book_id, page_number, note_text, created_at, updated_at
                FROM book_notes
            """)
            notes = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

        # Book Categories
        categories = []
        try:
            cur.execute("""
                SELECT book_id, category, is_primary
                FROM book_categories
            """)
            categories = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

        conn.close()

        payload = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "total_books": len(books),
            "books": books,
            "notes": notes,
            "categories": categories,
        }
        return payload

    @staticmethod
    def push_to_gist() -> Tuple[bool, str]:
        """Pushes current library metadata snapshot to a private GitHub Gist."""
        cfg = load_app_config()
        token = cfg.github_token.strip()
        if not token:
            return False, "Kein GitHub-Token konfiguriert."

        data = GitHubSyncService.export_library_data()
        raw_json = json.dumps(data, ensure_ascii=False).encode("utf-8")
        compressed_hex = gzip.compress(raw_json).hex()

        gist_payload = {
            "description": GIST_DESCRIPTION,
            "public": False,
            "files": {
                GIST_FILENAME: {
                    "content": compressed_hex
                }
            }
        }

        gist_id = cfg.github_gist_id.strip()
        method = "PATCH" if gist_id else "POST"
        url = f"https://api.github.com/gists/{gist_id}" if gist_id else "https://api.github.com/gists"

        req = urllib.request.Request(
            url,
            data=json.dumps(gist_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Campus-Bibliothek-App",
                "Content-Type": "application/json",
            },
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                new_gist_id = res.get("id", "")
                if new_gist_id and new_gist_id != gist_id:
                    cfg.github_gist_id = new_gist_id
                    save_app_config(cfg)
                return True, f"Erfolgreich synchronisiert! {len(data['books'])} Bücher gesichert."
        except urllib.error.HTTPError as e:
            return False, f"GitHub Fehler {e.code}: {e.read().decode('utf-8', errors='ignore')[:100]}"
        except Exception as e:
            return False, f"Fehler bei Synchronisation: {str(e)}"

    @staticmethod
    def pull_from_gist() -> Tuple[bool, str]:
        """Fetches library metadata snapshot from private GitHub Gist and merges into SQLite."""
        cfg = load_app_config()
        token = cfg.github_token.strip()
        gist_id = cfg.github_gist_id.strip()
        if not token or not gist_id:
            return False, "GitHub-Token oder Gist-ID fehlt."

        url = f"https://api.github.com/gists/{gist_id}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Campus-Bibliothek-App",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                file_obj = res.get("files", {}).get(GIST_FILENAME)
                if not file_obj or not file_obj.get("content"):
                    return False, "Gist enthält keine gültige Campus-Bibliothek-Sicherung."
                compressed_hex = file_obj["content"]
                raw_bytes = bytes.fromhex(compressed_hex)
                decompressed = gzip.decompress(raw_bytes).decode("utf-8")
                payload = json.loads(decompressed)
        except Exception as e:
            return False, f"Download fehlgeschlagen: {str(e)}"

        # Restore / merge into SQLite
        return GitHubSyncService._restore_payload(payload)

    @staticmethod
    def _restore_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
        books = payload.get("books", [])
        notes = payload.get("notes", [])
        categories = payload.get("categories", [])
        db_path = get_database_path()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        try:
            cur.execute("BEGIN TRANSACTION;")

            # Merge books
            for b in books:
                bid = b.get("id")
                if not bid:
                    continue
                cur.execute("SELECT id, current_page FROM books WHERE id = ?", (bid,))
                existing = cur.fetchone()
                if existing:
                    # Update progress and desk state if remote is further
                    cur.execute("""
                        UPDATE books
                        SET current_page = MAX(COALESCE(current_page, 1), ?),
                            is_on_desk = COALESCE(?, is_on_desk),
                            tags = COALESCE(?, tags),
                            read_status = COALESCE(?, read_status)
                        WHERE id = ?
                    """, (b.get("current_page", 1), b.get("is_on_desk"), b.get("tags"), b.get("read_status"), bid))
                else:
                    # Insert missing book entry
                    cols = ["id", "file_path", "filename", "title", "author", "isbn", "doi", "edition", "year", "page_count", "current_page", "is_on_desk", "tags"]
                    vals = [b.get(c) for c in cols]
                    placeholders = ", ".join(["?"] * len(cols))
                    col_names = ", ".join(cols)
                    cur.execute(f"INSERT OR IGNORE INTO books ({col_names}) VALUES ({placeholders})", vals)

            # Merge notes
            for n in notes:
                cur.execute("""
                    INSERT OR IGNORE INTO book_notes (book_id, page_number, note_text, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (n.get("book_id"), n.get("page_number", 1), n.get("note_text", ""), n.get("created_at"), n.get("updated_at")))

            # Merge categories
            for c in categories:
                cur.execute("""
                    INSERT OR IGNORE INTO book_categories (book_id, category, is_primary)
                    VALUES (?, ?, ?)
                """, (c.get("book_id"), c.get("category"), c.get("is_primary", 0)))

            conn.commit()
            return True, f"Erfolgreich wiederhergestellt! {len(books)} Bücher synchronisiert."
        except Exception as e:
            conn.rollback()
            return False, f"Datenbank-Fehler beim Einspielen: {str(e)}"
        finally:
            conn.close()
