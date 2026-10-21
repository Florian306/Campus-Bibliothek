"""High-precision academic dictionary and translation engine without AI.
Integrates Dict.cc vocabulary, English definitions (DictionaryAPI), DeepL Free API,
and MyMemory translation fallback with SQLite-based persistent caching.
"""

import html
import json
import os
import re
import sqlite3
import threading
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from core.config import get_user_data_dir, load_config

_DICT_CACHE_DB = os.path.join(get_user_data_dir(), "dictionary_cache.db")
_lock = threading.Lock()


def _get_cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DICT_CACHE_DB, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS translation_cache (
            source_text TEXT PRIMARY KEY,
            translated_text TEXT,
            engine TEXT,
            source_lang TEXT,
            target_lang TEXT,
            timestamp REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dictionary_cache (
            term TEXT PRIMARY KEY,
            data_json TEXT,
            timestamp REAL
        )
        """
    )
    conn.commit()
    return conn


def translate_text(
    text: str,
    source_lang: str = "EN",
    target_lang: str = "DE",
    deepl_key: Optional[str] = None
) -> Tuple[str, str]:
    """Translates text from English to German using DeepL (if key configured)
    or MyMemory as free, reliable fallback.
    Returns: (translated_text, engine_name)
    """
    clean_text = text.strip()
    if not clean_text:
        return "", ""

    # Check cache
    try:
        with _lock:
            conn = _get_cache_conn()
            row = conn.execute(
                "SELECT translated_text, engine FROM translation_cache WHERE source_text = ?",
                (clean_text,)
            ).fetchone()
            conn.close()
            if row:
                return row[0], f"{row[1]} (Cache)"
    except Exception:
        pass

    if not deepl_key:
        cfg = load_config()
        deepl_key = cfg.get("deepl_api_key", "").strip()

    # 1. DeepL Translation (if key configured and quota available)
    if deepl_key:
        try:
            host = "api-free.deepl.com" if deepl_key.endswith(":fx") else "api.deepl.com"
            url = f"https://{host}/v2/translate"
            data = urllib.parse.urlencode({
                "auth_key": deepl_key,
                "text": clean_text,
                "source_lang": source_lang.upper(),
                "target_lang": target_lang.upper()
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "Campus-Bibliothek/2.0"})
            with urllib.request.urlopen(req, timeout=7) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                trans_text = res_data["translations"][0]["text"].strip()
                _save_translation_cache(clean_text, trans_text, "DeepL", source_lang, target_lang)
                return trans_text, "DeepL"
        except Exception:
            pass

    # 2. Google Neural Machine Learning Engine (GTX - unlimited, high accuracy)
    try:
        url = (
            f"https://translate.googleapis.com/translate_a/single?client=gtx"
            f"&sl={source_lang.lower()}&tl={target_lang.lower()}&dt=t&q={urllib.parse.quote(clean_text)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and data and isinstance(data[0], list):
                translated_parts = [seg[0] for seg in data[0] if seg and seg[0]]
                if translated_parts:
                    trans_text = "".join(translated_parts).strip()
                    _save_translation_cache(clean_text, trans_text, "Google Neural MML", source_lang, target_lang)
                    return trans_text, "Google Neural MML"
    except Exception:
        pass

    # 3. Local Ollama Translation (if running locally)
    try:
        url_ol = "http://localhost:11434/api/generate"
        prompt_txt = (
            f"Translate the following scientific/academic text from English to German.\n"
            f"Preserve standard academic terminology. Do NOT add notes or conversational preamble. Return ONLY the translation:\n\n"
            f"{clean_text}"
        )
        payload = {
            "model": "qwen2.5vl:latest",
            "prompt": prompt_txt,
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 2048}
        }
        req_ol = urllib.request.Request(
            url_ol,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_ol, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ol_resp = data.get("response", "").strip()
            if ol_resp and len(ol_resp) > 3:
                _save_translation_cache(clean_text, ol_resp, "Local Ollama", source_lang, target_lang)
                return ol_resp, "Local Ollama"
    except Exception:
        pass

    # 4. MyMemory Translation Fallback (free translation memory)
    try:
        q_enc = urllib.parse.quote(clean_text[:500])
        pair = f"{source_lang.lower()}|{target_lang.lower()}"
        url = f"https://api.mymemory.translated.net/get?q={q_enc}&langpair={pair}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("responseStatus")
            trans_text = data.get("responseData", {}).get("translatedText", "")
            if trans_text and status in (200, "200"):
                trans_text = html.unescape(trans_text).strip()
                _save_translation_cache(clean_text, trans_text, "MyMemory", source_lang, target_lang)
                return trans_text, "MyMemory"
    except Exception as e:
        return f"Übersetzungsfehler: {e}", "Fehler"

    return clean_text, "Unverändert"


def _save_translation_cache(src: str, dst: str, engine: str, s_lang: str, t_lang: str) -> None:
    try:
        import time
        with _lock:
            conn = _get_cache_conn()
            conn.execute(
                "INSERT OR REPLACE INTO translation_cache VALUES (?, ?, ?, ?, ?, ?)",
                (src, dst, engine, s_lang, t_lang, time.time())
            )
            conn.commit()
            conn.close()
    except Exception:
        pass


def lookup_dictionary(term: str) -> Dict[str, any]:
    """Looks up single terms or idioms in Dict.cc and English DictionaryAPI.
    Returns structured results: {term, translations: [(en, de)], definitions: [(pos, def)]}
    """
    clean_term = term.strip(" ,.-;:_!?\"'()[]{}")
    if not clean_term:
        return {"term": "", "translations": [], "definitions": []}

    # Check cache
    try:
        with _lock:
            conn = _get_cache_conn()
            row = conn.execute(
                "SELECT data_json FROM dictionary_cache WHERE term = ?",
                (clean_term.lower(),)
            ).fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
    except Exception:
        pass

    results = {
        "term": clean_term,
        "translations": [],
        "definitions": []
    }

    # 1. Dict.cc Scraping (instant, specialized vocabulary & subject tags)
    try:
        url = f"https://www.dict.cc/?s={urllib.parse.quote(clean_term)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
        cells = re.findall(r'<td class=.td7nl.[^>]*>(.*?)</td>', content)
        for i in range(0, len(cells) - 1, 2):
            en_raw = re.sub(r'<[^>]+>', '', cells[i])
            de_raw = re.sub(r'<[^>]+>', '', cells[i + 1])
            en = re.sub(r'^\d+', '', en_raw).strip()
            de = re.sub(r'^\d+', '', de_raw).strip()
            if en and de:
                results["translations"].append((en, de))
            if len(results["translations"]) >= 8:
                break
    except Exception:
        pass

    # 2. English Monolingual Definitions (DictionaryAPI)
    try:
        url_d = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(clean_term)}"
        req_d = urllib.request.Request(url_d, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req_d, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                for m in data[0].get("meanings", [])[:3]:
                    pos = m.get("partOfSpeech", "")
                    for d in m.get("definitions", [])[:2]:
                        def_text = d.get("definition", "").strip()
                        example = d.get("example", "").strip()
                        if def_text:
                            results["definitions"].append((pos, def_text, example))
    except Exception:
        pass

    # Save cache
    try:
        import time
        with _lock:
            conn = _get_cache_conn()
            conn.execute(
                "INSERT OR REPLACE INTO dictionary_cache VALUES (?, ?, ?)",
                (clean_term.lower(), json.dumps(results), time.time())
            )
            conn.commit()
            conn.close()
    except Exception:
        pass

    return results
