"""Client for querying local Ollama instance with compact prompt, VRAM keep_alive, and validation.
"""

import json
import re
import threading
import urllib.request
from typing import List, Optional

_OLLAMA_LOCK = threading.Lock()
from core.models import BookAnalysis
from ai.categories import STANDARD_CATEGORIES
from ai.validator import (
    sanitize_filename,
    sanitize_folder_name,
    detect_heuristic_category,
    cross_validate_and_score,
)


import os
import shutil
import subprocess
import sys
import time

_OLLAMA_AVAILABLE: Optional[bool] = None
_OLLAMA_LAST_CHECK: float = 0.0


_OLLAMA_PROCESS: Optional[subprocess.Popen] = None


def start_ollama_service() -> bool:
    """Spawns Ollama background daemon silently without a console window."""
    global _OLLAMA_PROCESS
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        shutil.which("ollama"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ollama.Ollama.Portable_Microsoft.Winget.Source_8wekyb3d8bbwe\ollama.exe"),
        os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe"),
    ]
    ollama_bin = next((p for p in candidates if p and os.path.isfile(p)), None)
    if not ollama_bin:
        return False

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama app.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    try:
        bin_dir = os.path.dirname(ollama_bin)
        _OLLAMA_PROCESS = subprocess.Popen(
            [ollama_bin, "serve"],
            cwd=bin_dir if os.path.isdir(bin_dir) else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return True
    except Exception:
        return False


_STARTUP_LOCK = threading.Lock()


def ensure_ollama_running(timeout: float = 12.0) -> bool:
    """Ensures Ollama service is active. If offline, attempts silent autostart and polls until ready."""
    global _OLLAMA_AVAILABLE, _OLLAMA_LAST_CHECK
    _OLLAMA_AVAILABLE = None
    _OLLAMA_LAST_CHECK = 0.0
    if is_ollama_available():
        return True

    with _STARTUP_LOCK:
        _OLLAMA_AVAILABLE = None
        _OLLAMA_LAST_CHECK = 0.0
        if is_ollama_available():
            return True

        started = start_ollama_service()
        if not started:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            _OLLAMA_AVAILABLE = None
            _OLLAMA_LAST_CHECK = 0.0
            if is_ollama_available():
                return True

    return False


def is_ollama_available(host: str = "http://127.0.0.1:11434") -> bool:
    """Fast non-blocking health check for local Ollama service with 120-second TTL cache."""
    global _OLLAMA_AVAILABLE, _OLLAMA_LAST_CHECK
    now = time.time()
    if _OLLAMA_AVAILABLE is not None and (now - _OLLAMA_LAST_CHECK) < 120.0:
        return _OLLAMA_AVAILABLE

    try:
        # Standardize host to 127.0.0.1 to avoid Windows IPv6 resolution latency
        clean_host = host.replace("localhost", "127.0.0.1").rstrip("/")
        url = f"{clean_host}/api/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "BuchsortiererAI"})
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            _OLLAMA_AVAILABLE = (resp.status == 200)
    except Exception:
        _OLLAMA_AVAILABLE = False

    _OLLAMA_LAST_CHECK = now
    return _OLLAMA_AVAILABLE


def fetch_ollama_models(host: str = "http://localhost:11434") -> List[str]:
    """Fetches list of available local models from running Ollama service."""
    if not is_ollama_available(host):
        return []
    try:
        url = f"{host.rstrip('/')}/api/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "BuchsortiererAI"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            return models if models else ["qwen2.5vl:latest", "llama3.2:1b"]
    except Exception:
        return []


# Backward-compatibility aliases
check_ollama_status = is_ollama_available
list_ollama_models = fetch_ollama_models


def analyze_with_ollama(
    model_name: str,
    original_filename: str,
    pdf_text: str,
    existing_folders: Optional[List[str]] = None,
    host: str = "http://localhost:11434",
) -> BookAnalysis:
    """Queries local Ollama with compact prompt, hot VRAM caching, and cross-validation."""
    if not is_ollama_available(host):
        raise ConnectionError("Ollama Service ist nicht aktiv oder antwortet nicht.")

    available_cats = list(STANDARD_CATEGORIES)
    if existing_folders:
        for ef in existing_folders:
            clean_ef = ef.strip()
            if clean_ef and clean_ef not in available_cats:
                available_cats.insert(0, clean_ef)

    categories_list_str = ", ".join(available_cats)

    prompt = (
        "Du bist ein hochpräziser akademischer Bibliothekar und Fachbereichs-Analyst.\n"
        "AUFGABE: Bestimme die universitäre Fakultät (den primären Fachbereich), an der dieses Lehrbuch verwendet wird.\n"
        f"GÜLTIGE KATEGORIEN: {categories_list_str}\n\n"
        "STRIKTE REGELN:\n"
        "1. 'kategorie': Wähle exakt eine der oben genannten Kategorien. WICHTIG: Ignoriere populärwissenschaftliche Metaphern im Titel (z. B. 'für Höhlenmenschen', 'für Dummies', 'im Alltag', 'Abenteuer'). Entscheide rein nach dem wissenschaftlichen Inhalt!\n"
        "2. 'autor': Nachname oder Vorname Nachname des Hauptautors (oder 'Unbekannt').\n"
        "3. 'titel': Echter Buchtitel (NIEMALS 'Titelei', 'Cover', 'Frontmatter' oder 'Inhaltsverzeichnis').\n"
        "4. 'neuer_dateiname': Format 'Autor - Titel.pdf' ohne eckige Klammern.\n\n"
        f"Dateiname: {original_filename}\n"
        f"Text & Inhaltsverzeichnis:\n{pdf_text[:1800]}\n"
    )

    schema = BookAnalysis.model_json_schema()
    payload = {
        "model": model_name,
        "prompt": prompt,
        "format": schema,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": 0.0,
            "num_predict": 90,
            "num_thread": 4,
        },
    }

    url = f"{host.rstrip('/')}/api/generate"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with _OLLAMA_LOCK:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw_data = json.loads(resp.read().decode("utf-8"))
        content = raw_data.get("response", "{}")
        parsed = json.loads(content)

        raw_cat = str(parsed.get("kategorie", "")).strip()
        author = str(parsed.get("autor", "Unbekannt")).strip()
        title = str(parsed.get("titel", "Unbenannt")).strip()
        new_file = str(parsed.get("neuer_dateiname", "")).strip()

        author = author.replace("[", "").replace("]", "").strip()
        title = title.replace("[", "").replace("]", "").strip()
        new_file = new_file.replace("[", "").replace("]", "").strip()

        # Anti-Junk-Title Filter
        junk_title_words = [
            "titelei", "frontmatter", "vorspann", "cover",
            "inhaltsverzeichnis", "contents", "table of contents", "impressum"
        ]
        if any(jw in title.lower() for jw in junk_title_words) or len(title) < 4:
            clean_orig_stem = re.sub(r'\.pdf$', '', original_filename, flags=re.IGNORECASE)
            clean_orig_stem = re.sub(r'^[0-9_\-\.\s]+', '', clean_orig_stem)
            title = clean_orig_stem if clean_orig_stem else original_filename.replace(".pdf", "")

        # Cross-Validation & Confidence Engine
        cat, confidence, needs_rev, rev_reason = cross_validate_and_score(
            original_filename=original_filename,
            pdf_text=pdf_text,
            raw_category=raw_cat,
            author=author,
            title=title,
            existing_folders=existing_folders,
        )

        # Shorten authors list if multiple authors
        clean_author = author
        if "," in author or " und " in author or " and " in author:
            parts = [p.strip() for p in re.split(r',|\bund\b|\band\b', author) if p.strip()]
            if len(parts) > 2:
                clean_author = f"{parts[0]} et al."
            elif len(parts) == 2:
                clean_author = f"{parts[0]} & {parts[1]}"

        # Preserve Band / Volume numbers
        volume_match = re.search(r'\b(Band\s*\d+|Vol\.\s*\d+|Teil\s*\d+)\b', original_filename, re.IGNORECASE)
        vol_prefix = f" - {volume_match.group(1)}" if volume_match and volume_match.group(1).lower() not in title.lower() else ""

        # Deterministic, clean filename
        if clean_author and clean_author not in ["Unbekannt", "-"] and title and title not in ["Unbenannt", "-"]:
            final_name = f"{clean_author} - {title}{vol_prefix}.pdf"
        elif title and title not in ["Unbenannt", "-"]:
            final_name = f"{title}{vol_prefix}.pdf"
        elif new_file and not new_file.lower().startswith("autor -") and new_file.lower() != ".pdf":
            final_name = new_file
        else:
            final_name = original_filename

        return BookAnalysis(
            kategorie=sanitize_folder_name(cat),
            autor=clean_author or "Unbekannt",
            titel=title or "Unbenannt",
            neuer_dateiname=sanitize_filename(final_name),
            confidence=confidence,
            needs_review=needs_rev,
            review_reason=rev_reason,
        )
    except Exception as e:
        heuristic_cat = detect_heuristic_category(original_filename, pdf_text, existing_folders) or "Sonstiges"
        clean_orig = sanitize_filename(original_filename)
        return BookAnalysis(
            kategorie=sanitize_folder_name(heuristic_cat),
            autor="Unbekannt",
            titel=clean_orig.replace(".pdf", ""),
            neuer_dateiname=clean_orig,
            confidence=40,
            needs_review=True,
            review_reason=f"Analyse-Fehler: {str(e)}",
        )
