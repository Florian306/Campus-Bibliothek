"""Self-learning pattern memory and series clustering engine (rules_memory.json).
Caches user decisions, learns series templates, and provides instant zero-latency classification.
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple
from core.config import get_app_dir

MEMORY_FILE_PATH = os.path.join(get_app_dir(), "rules_memory.json")

# Built-in High-Confidence Academic Series
BUILTIN_SERIES_RULES: List[Dict[str, str]] = [
    {
        "series": "VEJ",
        "pattern": r"\b(vej|verfolgung und ermordung der europ[äa]ischen juden)\b",
        "category": "Geschichte & Politik",
        "reason": "[Reihe] VEJ (Institut für Zeitgeschichte)",
    },
    {
        "series": "Beck-Texte",
        "pattern": r"\b(beck-texte|nomosgesetze|sartorius|schönfelder)\b",
        "category": "Rechtswissenschaften & Jura",
        "reason": "[Reihe] C.H. Beck / Nomos Gesetzessammlung",
    },
    {
        "series": "Dubbel",
        "pattern": r"\bdubbel\b",
        "category": "Ingenieurwissenschaften & Technik",
        "reason": "[Standardwerk] Dubbel Maschinenbau",
    },
    {
        "series": "Wöhe",
        "pattern": r"\bwöhe\b.*(betriebswirtschaft|bwl)",
        "category": "Wirtschaftswissenschaften",
        "reason": "[Standardwerk] Wöhe Allgemeine BWL",
    },
]


def load_memory() -> Dict:
    """Loads learned rules from rules_memory.json or initializes defaults."""
    if os.path.isfile(MEMORY_FILE_PATH):
        try:
            with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    default_data = {
        "version": 2,
        "learned_patterns": [],
        "series_rules": BUILTIN_SERIES_RULES,
    }
    save_memory(default_data)
    return default_data


def save_memory(data: Dict):
    """Persists learned rules to rules_memory.json."""
    try:
        with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving rules_memory.json: {e}")


def match_memory_rule(filename: str, text: str = "") -> Optional[Tuple[str, str]]:
    """Checks filename and text against built-in series and learned user patterns.
    
    Returns:
        (category, reason_str) or None if no rule matches.
    """
    mem = load_memory()
    combined = f"{filename} {text[:400]}".lower()

    # 1. Check User-Learned Patterns first (Highest Priority)
    for rule in mem.get("learned_patterns", []):
        pattern = rule.get("pattern", "")
        regex_pat = rule.get("regex", "")
        cat = rule.get("category", "")
        if regex_pat:
            try:
                if re.search(regex_pat, combined, re.IGNORECASE):
                    rule["hit_count"] = rule.get("hit_count", 0) + 1
                    return cat, f"[Memory] Gelerntes Muster '{pattern}'"
            except Exception:
                continue

    # 2. Check Built-in Series Rules
    for series in mem.get("series_rules", []):
        pattern = series.get("pattern", "")
        cat = series.get("category", "")
        reason = series.get("reason", f"[Reihe] {series.get('series', 'Unbekannt')}")
        if pattern:
            try:
                if re.search(pattern, combined, re.IGNORECASE):
                    return cat, reason
            except Exception:
                continue

    return None


def learn_user_correction(filename: str, chosen_category: str) -> Tuple[str, int]:
    """Learns from a manual user category change and clusters multi-volume series.
    
    Returns:
        (learned_pattern_display, rule_id)
    """
    mem = load_memory()

    # Clean filename of extension
    stem = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE).strip()
    
    # Check if part of a multi-volume series like 'Band 3', 'Teil 2', 'Vol. 1'
    volume_pattern = r'\b(Band\s*\d+|Teil\s*\d+|Vol\.\s*\d+|Volume\s*\d+)\b'
    match_vol = re.search(volume_pattern, stem, re.IGNORECASE)

    if match_vol:
        # Extract the series prefix before the volume
        prefix = stem[:match_vol.start()].strip(" -_.:")
        suffix = stem[match_vol.end():].strip(" -_.:")
        if len(prefix) >= 3:
            pattern_display = f"{prefix} (Alle Bände)"
            regex_pat = r'\b' + re.escape(prefix) + r'\b'
        elif len(suffix) >= 3:
            pattern_display = f"*{suffix}*"
            regex_pat = re.escape(suffix)
        else:
            pattern_display = f"{stem}"
            regex_pat = r'\b' + re.escape(stem) + r'\b'
    else:
        # Single book or specific title
        # Strip numbers and noise
        cleaned_stem = re.sub(r'^[0-9_\-\.\s]+', '', stem).strip()
        pattern_display = cleaned_stem if len(cleaned_stem) >= 4 else stem
        regex_pat = r'\b' + re.escape(pattern_display) + r'\b'

    # Check if pattern already exists, if so update it
    existing = False
    for rule in mem.get("learned_patterns", []):
        if rule.get("pattern") == pattern_display or rule.get("regex") == regex_pat:
            rule["category"] = chosen_category
            rule["hit_count"] = rule.get("hit_count", 0) + 1
            existing = True
            break

    if not existing:
        new_rule = {
            "id": f"rule_{len(mem['learned_patterns']) + 1}",
            "pattern": pattern_display,
            "regex": regex_pat,
            "category": chosen_category,
            "hit_count": 1,
        }
        mem["learned_patterns"].insert(0, new_rule)

    save_memory(mem)
    return pattern_display, len(mem["learned_patterns"])
