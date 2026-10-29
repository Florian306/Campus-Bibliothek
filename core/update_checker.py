"""GitHub Release & Auto-Updater Checker for Campus-Bibliothek.
Polls GitHub Releases API for Florian306/Campus-Bibliothek to detect new versions.
"""

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from core.error_handler import humanize_error

GITHUB_REPO = "Florian306/Campus-Bibliothek"
CURRENT_VERSION = "1.9.6"

FALLBACK_CHANGELOG: List[Dict[str, str]] = [
    {
        "version": "1.9.6",
        "date": "Aktuell",
        "title": "Scan & Sync Command-Dashboard & Live-Update-Zentrale",
        "notes": "• 4 Live-System-Metriken (Bücher, Seiten, Notizen, Windows-Tresor)\n• Integriertes Release- & Update-Center mit direkter 1-Klick-Installation und Versionshistorie\n• Farbige Echtzeit-Statuskonsole mit Schnellfilter-Optionen",
    },
    {
        "version": "1.9.5",
        "date": "29.10.2026",
        "title": "Windows DPAPI Tresor-Verschlüsselung & Geheimnisschutz",
        "notes": "• Sensible Zugangsdaten (Gmail App-Passwort, Kalender-URL, Tokens) hardwaregebunden via Windows DPAPI verschlüsselt\n• Write-Only Maskierung im JARVIS-Setup schützt vor Auslesen & Screenshots",
    },
    {
        "version": "1.9.4",
        "date": "28.10.2026",
        "title": "Asynchroner PDF-Stream-Loader & Metadaten-Heilung",
        "notes": "• Nicht-blockierender PDF-Reader mit Abbruch-Button und 25-Hz Progress-Throttling\n• Automatische ISBN-, Jahres- und Auflagen-Erkennung für Posteingangs-Bücher",
    },
    {
        "version": "1.9.3",
        "date": "28.10.2026",
        "title": "Cyber-Obsidian PDF-Ladebildschirm & Quick-Select",
        "notes": "• Dunkler Ladebildschirm mit Fortschrittsbalken für große Cloud-PDFs\n• Flüssige Mehrfachauswahl im Katalog & breitere Band-Badges",
    },
]


def check_for_updates() -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """Checks if a newer release is available on GitHub.
    Returns: (update_available, latest_version, download_url, release_notes)
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Campus-Bibliothek-Updater",
        },
    )

    try:
        ssl_ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag_name = data.get("tag_name", "").lstrip("v").strip()
            if not tag_name:
                return False, None, None, None

            # Compare semantic versions
            if _is_version_greater(tag_name, CURRENT_VERSION):
                download_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")
                assets = data.get("assets", [])

                # 1. Bevorzuge schnelles Delta-Patch (<20 MB) statt vollständigem Installer (>300 MB)
                patch_url = None
                setup_url = None
                fallback_url = None

                for asset in assets:
                    name = asset.get("name", "").lower()
                    url_candidate = asset.get("browser_download_url")
                    if "patch" in name and name.endswith(".zip"):
                        patch_url = url_candidate
                    elif "setup" in name and name.endswith(".exe"):
                        setup_url = url_candidate
                    elif name.endswith(".exe") or name.endswith(".zip"):
                        fallback_url = url_candidate

                # Priorisiere Patch: lädt nur die geänderten Dateien (~18 MB) statt 330 MB
                download_url = patch_url or setup_url or fallback_url or download_url
                notes = data.get("body", "Keine Versionshinweise vorhanden.")
                return True, tag_name, download_url, notes
            return False, tag_name, None, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Repository or release not published yet
            return False, None, None, None
        friendly = humanize_error(e, "GitHub-Verbindung fehlgeschlagen")
        return False, None, None, friendly
    except Exception as e:
        friendly = humanize_error(e, "Update-Prüfung fehlgeschlagen")
        return False, None, None, friendly


def fetch_recent_releases(limit: int = 4) -> List[Dict[str, str]]:
    """Fetches recent GitHub releases for the What's New / Update feed, falling back to local changelog."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page={limit}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Campus-Bibliothek-Updater",
        },
    )
    try:
        ssl_ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=6, context=ssl_ctx) as resp:
            items = json.loads(resp.read().decode("utf-8"))
            if isinstance(items, list) and items:
                out: List[Dict[str, str]] = []
                seen_versions = set()
                for fb in FALLBACK_CHANGELOG:
                    top_tag = str(items[0].get("tag_name", "")).lstrip("v").strip()
                    if _is_version_greater(fb["version"], top_tag):
                        out.append(fb)
                        seen_versions.add(fb["version"])

                for rel in items[:limit]:
                    tag = str(rel.get("tag_name", "")).lstrip("v").strip()
                    if tag in seen_versions:
                        continue
                    seen_versions.add(tag)
                    name = str(rel.get("name") or f"Version {tag}").strip()
                    pub = str(rel.get("published_at") or "")[:10]
                    body = str(rel.get("body") or "").strip()
                    if not body:
                        body = "Stabilitäts- und Performance-Verbesserungen."
                    out.append({
                        "version": tag,
                        "date": pub or "Release",
                        "title": name,
                        "notes": body[:280] + ("..." if len(body) > 280 else ""),
                    })
                return out[:limit]
    except Exception:
        pass
    return FALLBACK_CHANGELOG[:limit]


def _is_version_greater(remote: str, current: str) -> bool:
    """Compares two semver version strings."""
    try:
        def parse_parts(v: str):
            return [int(x) for x in v.split(".") if x.isdigit()]
        r_parts = parse_parts(remote)
        c_parts = parse_parts(current)
        return r_parts > c_parts
    except Exception:
        return remote != current
