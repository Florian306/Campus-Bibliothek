"""AI-Powered Tutor & Exam Generation Engine.
Extracts chapter text from PDFs and synthesizes Active Recall Quizzes, Timed Exam Simulations,
Socratic Oral Exam dialogues, and 1-Page Cheat Sheets using Ollama or Gemini.
"""

import json
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from core.config import load_config
from ai.pdf_extractor import extract_pdf_toc

FRONT_MATTER_REGEX = re.compile(
    r'(?i)^(?:vorwort|geleitwort|inhalt|inhaltsverzeichnis|contents|table of contents|'
    r'danksagung|hinweise|cover|titel|titelei|impressum|index|sachregister|'
    r'literatur|literaturverzeichnis|abbildungsverzeichnis|tabellenverzeichnis|'
    r'glossar|anhang|abkrzungsverzeichnis|abkrzungen)'
)


def get_book_substantive_chapters(file_path: str) -> List[Dict[str, Any]]:
    """Extracts actual instructional subject-matter chapters from the PDF TOC, skipping front/back matter.
    Returns list of dicts: {'title': str, 'start_page': int, 'end_page': int, 'level': int, 'display': str}
    """
    raw_toc = extract_pdf_toc(file_path)
    if not raw_toc:
        return []

    valid_chapters = []
    for lvl, title, page in raw_toc:
        clean_title = title.strip()
        # Filter out front-matter and back-matter
        if FRONT_MATTER_REGEX.search(clean_title):
            continue
        # Also filter out generic roman-only parts if followed by chapters
        valid_chapters.append({
            "title": clean_title,
            "start_page": page,
            "level": lvl,
        })

    # Calculate end_page for each chapter
    for i in range(len(valid_chapters)):
        sp = valid_chapters[i]["start_page"]
        if i + 1 < len(valid_chapters):
            next_sp = valid_chapters[i + 1]["start_page"]
            ep = max(sp, next_sp - 1) if next_sp > sp else (sp + 15)
        else:
            ep = sp + 20
        valid_chapters[i]["end_page"] = ep
        valid_chapters[i]["display"] = f"{valid_chapters[i]['title']} (S. {sp}-{ep})"

    return valid_chapters


def normalize_german_pdf_text(text: str) -> str:
    """Restores German umlauts, ligatures, and hyphens from TeX and PDF extractions."""
    if not text:
        return ""
    import unicodedata
    # 1. Ligatures and standard composition
    text = unicodedata.normalize('NFKC', text)
    # 2. TeX diaeresis U+00A8 and U+0308
    umlaut_map = {
        r'a\s*[\u00A8\u0308]|[\u00A8\u0308]\s*a': 'ä',
        r'o\s*[\u00A8\u0308]|[\u00A8\u0308]\s*o': 'ö',
        r'u\s*[\u00A8\u0308]|[\u00A8\u0308]\s*u': 'ü',
        r'A\s*[\u00A8\u0308]|[\u00A8\u0308]\s*A': 'Ä',
        r'O\s*[\u00A8\u0308]|[\u00A8\u0308]\s*O': 'Ö',
        r'U\s*[\u00A8\u0308]|[\u00A8\u0308]\s*U': 'Ü',
    }
    for pat, rep in umlaut_map.items():
        text = re.sub(pat, rep, text)
    # 3. Fix broken inter-letter spaces before umlauts common in TeX PDFs: e.g. "h ätte" -> "hätte", "f ür" -> "für"
    text = re.sub(r'([a-zA-Z])\s+([äöüÄÖÜ])', r'\1\2', text)
    # 4. Clean quotes
    text = text.replace('\u201d', '"').replace('\u201c', '"').replace('\u201e', '"').replace('\u2019', "'")
    # 5. Rejoin hyphenated words across linebreaks
    text = re.sub(r'(\b[a-zA-ZäöüÄÖÜß]+)-\s*\n\s*([a-zA-ZäöüÄÖÜß]+\b)', r'\1\2', text)
    return text


def extract_chapter_text(file_path: str, start_page: int, end_page: int, max_chars: int = 14000) -> str:
    """Extracts text from the specified page range using PyMuPDF, intelligently skipping title sheets and front-matter."""
    if not os.path.exists(file_path):
        return ""

    extracted_parts = []
    try:
        import fitz
        doc = fitz.open(file_path)
        total_p = doc.page_count
        sp = max(1, min(start_page, total_p))
        ep = max(sp, min(end_page, total_p))

        total_chars = 0
        for pno in range(sp - 1, ep):
            page = doc.load_page(pno)
            p_text = page.get_text("text")
            if not p_text:
                continue

            clean = re.sub(r'[\t ]+', ' ', p_text).strip()
            # If start_page is in first 10 pages, skip pure front-matter pages (impressum, TOC, Vorwort)
            if pno < 10 and (len(clean) < 140 or FRONT_MATTER_REGEX.search(clean[:80])):
                continue

            # Skip single-line splash/divider pages
            if len(clean) < 80 and ("kapitel" in clean.lower() or "teil" in clean.lower()):
                continue

            extracted_parts.append(f"--- [Seite {pno + 1}] ---\n{clean}")
            total_chars += len(clean)
            if total_chars >= max_chars:
                break

        doc.close()
    except Exception:
        pass

    raw_joined = "\n\n".join(extracted_parts)
    return normalize_german_pdf_text(raw_joined)


def ensure_ollama_running() -> bool:
    """Verifies if Ollama is listening on localhost:11434; if not, attempts to spawn 'ollama serve' in background."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    # Attempt to start ollama serve
    try:
        import subprocess
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        subprocess.Popen(["ollama", "serve"], creationflags=creationflags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time
        for _ in range(6):
            time.sleep(0.5)
            try:
                req = urllib.request.Request("http://localhost:11434/api/tags")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                continue
    except Exception:
        pass

    return False


def get_available_ai_models() -> List[Dict[str, str]]:
    """Returns available local Ollama models and cloud providers."""
    models = []
    cfg = load_config()
    api_key = cfg.get("api_key", "").strip()
    if api_key:
        models.append({"id": "gemini:gemini-2.5-flash", "name": "Google Gemini 2.5 Flash (Cloud)", "provider": "gemini"})

    # Query Ollama
    if ensure_ollama_running():
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("models", []):
                    m_name = m.get("name", "")
                    details = m.get("details", {})
                    p_size = details.get("parameter_size", "")
                    label = f"Ollama: {m_name}"
                    if p_size:
                        label += f" ({p_size})"
                    models.append({"id": f"ollama:{m_name}", "name": label, "provider": "ollama", "model": m_name})
        except Exception:
            pass

    return models


def _resolve_model(requested_model: Optional[str] = None) -> Tuple[str, str]:
    """Resolves provider and model name based on requested, config, or installed models."""
    cfg = load_config()
    provider = cfg.get("provider", "ollama")
    api_key = cfg.get("api_key", "")

    if requested_model:
        if requested_model.startswith("gemini:"):
            return "gemini", requested_model.split(":", 1)[1]
        elif requested_model.startswith("ollama:"):
            return "ollama", requested_model.split(":", 1)[1]

    if provider == "gemini" and api_key.strip():
        return "gemini", "gemini-2.5-flash"

    # Default to Ollama
    ensure_ollama_running()
    installed = []
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            installed = [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        pass

    cfg_model = cfg.get("ollama_model", "")
    if cfg_model and cfg_model in installed:
        return "ollama", cfg_model

    # Pick best available installed model
    for pref in ["mathstral:latest", "qwen2.5vl:latest", "qwen2.5:latest", "llama3.2:1b"]:
        if pref in installed:
            return "ollama", pref

    if installed:
        return "ollama", installed[0]

    return "ollama", cfg_model or "qwen2.5vl:latest"


def _clean_and_parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """5-stage cascade JSON extractor – handles fences, trailing text, and partial responses."""
    if not raw:
        return None
    raw = raw.strip()

    # Stage 1: direct parse
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # Stage 2: strip markdown fences  ```json ... ```
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if md_match:
        try:
            result = json.loads(md_match.group(1).strip())
            if isinstance(result, dict):
                return result
        except Exception:
            pass

    # Stage 3: raw_decode from first '{' – handles trailing prose after valid JSON
    first_brace = raw.find("{")
    if first_brace != -1:
        decoder = json.JSONDecoder()
        try:
            result, _ = decoder.raw_decode(raw, first_brace)
            if isinstance(result, dict):
                return result
        except Exception:
            pass

    # Stage 4: scan for largest balanced {…} block
    best: Optional[Dict] = None
    for m in re.finditer(r"\{", raw):
        start = m.start()
        depth = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and len(parsed) > (len(best) if best else 0):
                            best = parsed
                    except Exception:
                        pass
                    break
    if best:
        return best

    # Stage 5: aggressive key-value rescue via regex (last resort)
    rescued: Dict[str, Any] = {}
    for kv in re.finditer(r'"(\w+)"\s*:\s*("[^"]*"|\[.*?\]|\d+(?:\.\d+)?|true|false|null)', raw, re.DOTALL):
        key, val = kv.group(1), kv.group(2)
        try:
            rescued[key] = json.loads(val)
        except Exception:
            rescued[key] = val
    if "questions" in rescued or "professor_message" in rescued:
        return rescued

    return None


_LLM_JSON_RETRIES = 3
_LLM_BACKOFF_BASE = 1.5  # seconds


def _call_llm_json(system_prompt: str, user_prompt: str, model_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Dispatches to Gemini or Ollama with retry/backoff and multi-stage JSON extraction."""
    import time

    provider, model_name = _resolve_model(model_id)
    cfg = load_config()
    api_key = cfg.get("api_key", "")

    # Force JSON hint appended once to system_prompt
    json_hint = "\n\nCRITICAL: Your ENTIRE response MUST be valid JSON only. No prose, no markdown fences."
    augmented_system = system_prompt + json_hint

    # -- Gemini path --
    if provider == "gemini" and api_key.strip():
        for attempt in range(_LLM_JSON_RETRIES):
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=api_key.strip())
                resp = client.models.generate_content(
                    model=model_name or "gemini-2.5-flash",
                    contents=f"{augmented_system}\n\n{user_prompt}",
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=max(0.0, 0.2 - attempt * 0.05),  # cool down on retry
                    )
                )
                parsed = _clean_and_parse_json(resp.text)
                if parsed:
                    return parsed
            except Exception:
                pass
            if attempt < _LLM_JSON_RETRIES - 1:
                time.sleep(_LLM_BACKOFF_BASE ** attempt)

    # -- Ollama path --
    ensure_ollama_running()
    url = "http://localhost:11434/api/generate"
    combined_prompt = (
        f"<|im_start|>system\n{augmented_system}<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    for attempt in range(_LLM_JSON_RETRIES):
        try:
            payload = {
                "model": model_name,
                "prompt": combined_prompt,
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": max(0.0, 0.2 - attempt * 0.05),
                    "num_ctx": 8192,
                    "num_predict": 2048,
                    "repeat_penalty": 1.1,
                    "top_p": 0.9,
                }
            }
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                raw = body.get("response", "").strip()
                parsed = _clean_and_parse_json(raw)
                if parsed:
                    return parsed
        except Exception:
            pass
        if attempt < _LLM_JSON_RETRIES - 1:
            time.sleep(_LLM_BACKOFF_BASE ** attempt)

    return None


def generate_active_recall_quiz(
    book_title: str,
    chapter_title: str,
    text: str,
    num_questions: int = 5,
    model_id: Optional[str] = None
) -> Dict[str, Any]:
    """Synthesizes high-yield multiple-choice questions from the real book chapter text."""
    clean_text = text[:12000]
    if len(clean_text) < 150:
        return _generate_fallback_quiz(book_title, chapter_title, text=clean_text)

    system_prompt = (
        "Du bist ein renommierter Universitätsprofessor und anspruchsvoller Klausur-Prüfer an einer deutschen Hochschule.\n"
        f"AUFGABE: Erstelle eine fachlich anspruchsvolle, wissenschaftlich fundierte Multiple-Choice-Prüfung zum Thema '{chapter_title}'.\n\n"
        "DIDAKTISCHE STUFEN DER ANFORDERUNGSBEREICHE (AFB I bis AFB III):\n"
        f"Erstelle exakt {num_questions} Fragen, die didaktisch in den drei universitären Anforderungsbereichen gestaffelt sind:\n"
        "- AFB I (Reproduktion & Fachwissen): Exakte Abfrage grundlegender Definitionen, Sätze, mathematischer Axiome oder formaler Begriffe. (difficulty: 'AFB I')\n"
        "- AFB II (Reorganisation & Transfer): Rechnerische oder logische Anwendung auf nichttriviale Fälle, Umformungen, Verknüpfungen von Sätzen. (difficulty: 'AFB II')\n"
        "- AFB III (Reflexion & Problemlösung): Höchster Schwierigkeitsgrad! Erkennen von mathematischen Fallstricken, Scheinschlüssen, Finden von Gegenbeispielen oder Analyse von Gültigkeitsgrenzen. (difficulty: 'AFB III')\n\n"
        "STRIKTE QUALITÄTSVORGABEN:\n"
        "1. KEINE TRIVIALEN FRAGEN: Vermeide oberflächliche Fragen. Die 3 falschen Optionen (Distraktoren) müssen typische studentische Denk- oder Vorzeichenfehler repräsentieren.\n"
        "2. MATHEMATIK & FORMELN (LATEX): Nutze für JEDE Formel, Gleichung, Aussageform, Variable oder mathematischen Term zwingend sauberes LaTeX mit genau einem Dollarzeichen ($...$), z.B. $A(x): x + 5 = 8$, $x^2 \\geq 0$, $\\forall x \\in \\mathbb{R}$, $\\frac{a}{b}$. Formeln NIEMALS in Anführungszeichen setzen.\n"
        "3. DEUTSCHE RECHTSCHREIBUNG: Schreibe echte deutsche Umlaute (ä, ö, ü, Ä, Ö, Ü, ß). Verwende NIEMALS TeX-Ersatz wie \\\"a, \\\"o, \\\"u.\n"
        "4. Genau 1 Option muss absolut korrekt sein (correct_index: 0, 1, 2 oder 3).\n"
        "5. MUSTERLÖSUNG (explanation): Begründe mathematisch präzise und herleitend, warum die Lösung zutrifft und woran die Distraktoren scheitern.\n"
        "6. Antworte AUSSCHLIESSLICH im vorgegebenen JSON-Format:\n"
        "{\n"
        '  "title": "Klausur: ' + chapter_title + '",\n'
        '  "questions": [\n'
        '    {\n'
        '      "question": "Präzise fachliche Frage mit sauberem $LaTeX$...",\n'
        '      "options": ["Option A", "Option B", "Option C", "Option D"],\n'
        '      "correct_index": 0,\n'
        '      "explanation": "Fundierte mathematische Herleitung...",\n'
        '      "difficulty": "AFB I"\n'
        '    }\n'
        '  ]\n'
        "}"
    )

    user_prompt = (
        f"Fachbuch: {book_title}\n"
        f"Thema / Kapitel: {chapter_title}\n\n"
        f"Auszug aus den Buchseiten:\n'''\n{clean_text}\n'''"
    )

    result = _call_llm_json(system_prompt, user_prompt, model_id=model_id)
    if result and "questions" in result and len(result["questions"]) > 0:
        return result

    return _generate_fallback_quiz(book_title, chapter_title, text=clean_text)


def generate_exam_simulation(
    book_title: str,
    chapter_title: str,
    text: str,
    duration_minutes: int = 25,
    model_id: Optional[str] = None
) -> Dict[str, Any]:
    """Generates a timed, scored examination simulation with AFB I-III weighted points and pass mark."""
    quiz_data = generate_active_recall_quiz(book_title, chapter_title, text, num_questions=6, model_id=model_id)
    questions = quiz_data.get("questions", [])

    total_points = 0
    for i, q in enumerate(questions):
        diff = q.get("difficulty", "")
        if "AFB III" in diff or i >= 4:
            pts = 8
            q["difficulty"] = "AFB III"
        elif "AFB II" in diff or i >= 2:
            pts = 6
            q["difficulty"] = "AFB II"
        else:
            pts = 4
            q["difficulty"] = "AFB I"

        q["points"] = pts
        q["id"] = i + 1
        total_points += pts

    return {
        "title": f"Klausur-Simulation: {chapter_title}",
        "book_title": book_title,
        "duration_seconds": duration_minutes * 60,
        "total_points": total_points,
        "pass_points": int(total_points * 0.5),
        "questions": questions,
    }


def generate_socratic_turn(
    book_title: str,
    chapter_title: str,
    text: str,
    history: List[Dict[str, str]],
    model_id: Optional[str] = None
) -> Dict[str, Any]:
    """Executes one turn of a Socratic Oral Exam where the AI plays the university professor."""
    clean_text = text[:10000]

    system_prompt = (
        "Du bist ein anspruchsvoller, aber wohlwollender Universitätsprofessor in einer mündlichen Prüfung.\n"
        f"Gegenstand der Prüfung ist das Fachbuch '{book_title}' (Kapitel: '{chapter_title}').\n"
        "REGELN FÜR DEN PRÜFER:\n"
        "1. Wenn der Student antwortet, beurteile seine Aussage präzise (Lob für Gutes, sachliche Korrektur bei Lücken).\n"
        "2. Hake sokratisch nach oder stelle eine vertiefende Transferfrage zum Buchinhalt.\n"
        "3. Wenn das Gespräch 3-4 Runden erreicht hat, beende die Prüfung mit einer Gesamtnote (1.0 bis 5.0) und Feedback.\n"
        "Antworte AUSSCHLIESSLICH als JSON:\n"
        "{\n"
        '  "professor_message": "Deine Antwort oder nächste Frage an den Studenten",\n'
        '  "is_exam_finished": false,\n'
        '  "final_grade": null,\n'
        '  "feedback_summary": ""\n'
        "}"
    )

    conv_text = ""
    for msg in history:
        role = "Professor" if msg.get("role") == "assistant" else "Student"
        conv_text += f"{role}: {msg.get('content', '')}\n"

    user_prompt = (
        f"Buchinhalt:\n'''\n{clean_text}\n'''\n\n"
        f"Bisheriger Prüfungsverlauf:\n{conv_text}\n\n"
        "Bitte reagiere als Professor auf die letzte Aussage des Studenten."
    )

    result = _call_llm_json(system_prompt, user_prompt, model_id=model_id)
    if result and "professor_message" in result:
        return result

    # Fallback initial prompt
    return {
        "professor_message": f"Guten Tag! Lassen Sie uns über '{chapter_title}' sprechen. Erläutern Sie mir bitte zu Beginn die zentrale Grundidee oder Fragestellung dieses Abschnitts in eigenen Worten.",
        "is_exam_finished": False,
        "final_grade": None,
        "feedback_summary": ""
    }


def generate_cheat_sheet(
    book_title: str,
    chapter_title: str,
    text: str,
    model_id: Optional[str] = None
) -> str:
    """Creates a high-density 1-page markdown summary with formulas, definitions, and laws."""
    clean_text = text[:12000]
    if len(clean_text) < 150:
        return f"# Spickzettel: {chapter_title}\n\n*Kein ausreichender Buchtext zur Extraktion verfügbar.*"

    system_prompt = (
        "Du bist ein wissenschaftlicher Tutor. Erstelle ein kompaktes, hochgradig komprimiertes 'One-Pager Cheat Sheet' "
        "(Spickzettel / Formelsammlung / Merkhilfe) im Markdown-Format.\n"
        "GLIEDERUNG:\n"
        "1. 📌 Kernaussage in 2 Sätzen\n"
        "2. 🔑 Wichtigste Definitionen & Fachbegriffe\n"
        "3. 📐 Gesetze, Paragrafen oder Kernformeln\n"
        "4. ⚠️ Häufige Klausur-Fallen & Merksätze\n"
        "Formatiere übersichtlich mit Bullet Points, Fettdruck und Code-Blöcken. Gib NUR das Markdown zurück."
    )

    user_prompt = f"Buch: {book_title}\nKapitel: {chapter_title}\n\nTextauszug:\n'''\n{clean_text}\n'''"

    provider, model_name = _resolve_model(model_id)
    cfg = load_config()
    api_key = cfg.get("api_key", "")

    if provider == "gemini" and api_key.strip():
        try:
            from google import genai
            client = genai.Client(api_key=api_key.strip())
            resp = client.models.generate_content(
                model=model_name or "gemini-2.5-flash",
                contents=f"{system_prompt}\n\n{user_prompt}"
            )
            return resp.text.strip()
        except Exception:
            pass

    try:
        ensure_ollama_running()
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": model_name,
            "prompt": f"<system>\n{system_prompt}\n</system>\n\n<user>\n{user_prompt}\n</user>",
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 4096}
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "").strip()
    except Exception:
        pass

    return f"# 📄 Spickzettel: {chapter_title}\n\n### Kernaspekte\n• Siehe Lehrbuchauszug: {book_title}\n• Wichtige Passagen und Definitionen im Kapitel markiert."


def _generate_fallback_quiz(book_title: str, chapter_title: str, text: str = "") -> Dict[str, Any]:
    """High-quality heuristic fallback quiz when LLM daemon is offline, tailored to topic."""
    # Find potential key terms from chapter title and text
    terms = [w.strip(".,;:()") for w in chapter_title.split() if len(w) > 3 and not w.isdigit()]
    main_term = " ".join(terms) if terms else chapter_title

    q1 = {
        "question": f"Welche zentrale Fragestellung bzw. Definition behandelt der Abschnitt '{chapter_title}'?",
        "options": [
            f"Die formalen Axiome, Gesetzmäßigkeiten und Definitionen zu {main_term}",
            "Ausschließlich die historische Druckgeschichte ohne fachlichen Gehalt",
            "Eine bloße Aufzählung von Randnotizen ohne theoretische Systematik",
            "Die Kritik an alternativen didaktischen Strömungen"
        ],
        "correct_index": 0,
        "explanation": f"In '{chapter_title}' werden die theoretischen Grundpfeiler und Prinzipien von {main_term} systematisch eingeführt.",
        "difficulty": "Grundlagen"
    }

    q2 = {
        "question": f"Welche Voraussetzung ist für das korrekte Anwenden der Regeln in '{chapter_title}' zwingend zu prüfen?",
        "options": [
            f"Dass alle definierten Randbedingungen und Grundannahmen von {main_term} erfüllt sind",
            "Dass die Seitenzahl des Kapitels eine Primzahl ist",
            "Dass die Aufgabe ohne mathematisch-logischen Beweis gelöst wird",
            "Dass ausschließlich Faustformeln ohne theoretisches Fundament verwendet werden"
        ],
        "correct_index": 0,
        "explanation": "Wissenschaftliche Aussagen und Sätze gelten stets nur unter Einhaltung ihrer expliziten Voraussetzungen und Gültigkeitsbereiche.",
        "difficulty": "Verständnis"
    }

    q3 = {
        "question": f"Wie wird in einer Klausur vorgegangen, wenn eine Aufgabenstellung zu '{main_term}' vorliegt?",
        "options": [
            "Zunächst die gegebenen Größen/Prämissen formal notieren, den passenden Satz identifizieren und schrittweise ableiten",
            "Direkt ein intuitives Endergebnis ohne Nachvollziehbarkeit des Rechenwegs aufschreiben",
            "Die Aufgabe überspringen, da Theoriekapitel nie prüfungsrelevant sind",
            "Die Lösung anhand des Deckblatts des Lehrbuchs raten"
        ],
        "correct_index": 0,
        "explanation": "Klausuren verlangen eine saubere mathematisch-logische Struktur: Prämissen, Satzidentifikation, deduktive Herleitung.",
        "difficulty": "Klausurniveau"
    }

    q4 = {
        "question": f"Welcher typische Denkfehler tritt bei Studierenden im Themenfeld '{main_term}' besonders häufig auf?",
        "options": [
            "Die Verwechslung von notwendiger und hinreichender Bedingung (bzw. Implikation und Äquivalenz)",
            "Das zu genaue Lesen der Aufgabenstellung",
            "Das Überprüfen des Ergebnisses auf Plausibilität",
            "Das Verwenden anerkannter Fachtermini"
        ],
        "correct_index": 0,
        "explanation": "Häufigster Klausurfehler in Grundlagenfächern ist das unzulässige Schließen der Umkehrung (Rückrichtung) einer Implikation.",
        "difficulty": "Fallstrick"
    }

    q5 = {
        "question": f"Welche Methode garantiert die höchste Retention für die Konzepte aus '{chapter_title}'?",
        "options": [
            "Active Recall: Das eigenständige Lösen von Transferaufgaben und Rekapitulieren ohne Buch",
            "Passives Wiederholen durch mehrfaches farbiges Markieren desselben Textes",
            "Reines Auswendiglernen von Formelzeichen ohne geometrisch-logische Anschauung",
            "Das Verschieben der Klausurvorbereitung auf den Vorabend der Prüfung"
        ],
        "correct_index": 0,
        "explanation": "Kognitive Studien belegen: Nur aktives Abrufen (Active Recall) und Transfertraining bauen neuronale Abrufstrukturen für die Klausur auf.",
        "difficulty": "Didaktik"
    }

    return {
        "title": f"Klausur-Vorbereitung: {chapter_title}",
        "questions": [q1, q2, q3, q4, q5]
    }
