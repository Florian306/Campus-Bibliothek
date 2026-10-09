"""AI Abstract & Audience analyzer for academic textbooks.
Generates structured summaries via Ollama or Google Gemini with persistent caching in library.db.
"""

import json
import os
import re
import urllib.request
from typing import Optional

from core.config import load_config
from core.library_db import get_book_summary, update_book_summary


def generate_book_summary(
    book_id: str,
    title: str,
    author: str,
    file_path: str,
    force_refresh: bool = False,
) -> str:
    """Returns cached summary or queries AI (Ollama/Gemini) to generate structured abstract."""
    if not force_refresh:
        cached = get_book_summary(book_id)
        if cached:
            return cached

    # 1. Extract sample text from front-matter and TOC
    sample_text = ""
    if os.path.exists(file_path):
        try:
            import fitz
            doc = fitz.open(file_path)
            for p in range(min(5, len(doc))):
                sample_text += doc[p].get_text("text") + "\n"
            doc.close()
        except Exception:
            pass

    clean_sample = re.sub(r'[\r\n\t]+', ' ', sample_text)[:2000].strip()

    cfg = load_config()
    provider = cfg.get("provider", "ollama")
    api_key = cfg.get("api_key", "").strip()
    ollama_model = cfg.get("ollama_model", "qwen2.5vl:latest")

    summary_result: Optional[str] = None

    # Prompt
    prompt = (
        f"Du bist ein wissenschaftlicher Bibliothekar. Erstelle eine prägnante Zusammenfassung für das Fachbuch:\n"
        f"Titel: {title}\n"
        f"Autor: {author}\n"
        f"Textauszug: {clean_sample}\n\n"
        "Antworte auf Deutsch mit genau diesem kompakten Format:\n"
        "📌 Kerninhalt: (2 prägnante Sätze zum wissenschaftlichen Thema)\n"
        "🎯 Zielgruppe: (z. B. Studierende der Physik ab 2. Semester, Praktiker)\n"
        "🔑 Schwerpunkte: (3-4 wichtige Themen durch Komma getrennt)"
    )

    # 2. Try Gemini if configured
    if provider == "gemini" and api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            if resp and resp.text:
                summary_result = resp.text.strip()
        except Exception:
            pass

    # 3. Try Ollama
    if not summary_result:
        try:
            payload = {
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 180},
            }
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data.get("response", "").strip()
                if text:
                    summary_result = text
        except Exception:
            pass

    # 4. Fallback if AI offline
    if not summary_result:
        summary_result = (
            f"📌 Kerninhalt: Standardwerk zu '{title}' von {author}.\n"
            f"🎯 Zielgruppe: Akademische Fachleser und Studierende.\n"
            f"🔑 Schwerpunkte: Fachspezifische Grundlagen, Methoden und Anwendungsbeispiele."
        )

    # Cache in DB
    if book_id and summary_result:
        update_book_summary(book_id, summary_result)

    return summary_result
