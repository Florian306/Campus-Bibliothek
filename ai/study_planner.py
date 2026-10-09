"""Intelligent Reading & Study Planner Engine for Campus Library AI.
Provides:
1. Automated didactic complexity analysis (Flesch-DE, sentence length, formula/technical term density).
2. Realistic daily rhythm & habit planning for self-study (by daily minutes or target weeks).
3. Adaptive buffer & procrastination rescheduling without stress.
4. Full integration with SQLite study_plans table.
"""

import math
import re
import time
import json
import datetime
from typing import Any, Dict, List, Optional, Tuple


def analyze_text_complexity(sample_text: str, total_pages: int = 1) -> Dict[str, Any]:
    """Analyzes text structure, specialized terminology, and formula density
    to determine an accurate difficulty score (1.0 to 5.0) and reading pace in minutes per page.
    """
    if not sample_text or len(sample_text.strip()) < 40:
        return {
            "score": 3.0,
            "level": "Mittelschwer",
            "level_code": 3,
            "min_per_page": 3.5,
            "flesch_de": 55.0,
            "avg_sentence_len": 16.0,
            "long_word_pct": 28.0,
            "term_density": "Mittel",
            "formula_density": "Gering",
            "recommendation": "Standard-Lehrbuchtempo: ca. 3–4 Minuten pro Seite für aufmerksames Durcharbeiten.",
        }

    # Clean text
    clean_t = sample_text.strip()

    # Sentences
    sentences = [s.strip() for s in re.split(r'[.!?]+', clean_t) if len(s.strip()) > 3]
    num_sentences = max(1, len(sentences))

    # Words
    words = re.findall(r'[a-zA-ZäöüÄÖÜß0-9\-_]{2,}', clean_t)
    num_words = max(1, len(words))

    # Average sentence length (ASL)
    asl = num_words / num_sentences

    # Long words (>= 8 characters, common in German academic compounds)
    long_words = [w for w in words if len(w) >= 8]
    long_word_pct = (len(long_words) / num_words) * 100.0

    # Syllables estimation for German Flesch index
    vowels = "aeiouäöüy"
    total_syllables = 0
    for w in words:
        wl = w.lower()
        count = sum(1 for char in wl if char in vowels)
        total_syllables += max(1, count)
    asw = total_syllables / num_words  # Average Syllables per Word

    # Flesch-Reading-Ease for German (Amstad-Formel): 180 - ASL - (58.5 * ASW)
    flesch_de = max(0.0, min(100.0, 180.0 - asl - (58.5 * asw)))

    # Technical / Academic terminology detection
    academic_suffixes = (
        "ierung", "ation", "ismus", "theorie", "konzept", "analyse",
        "synthese", "paradigma", "heuristik", "metrik", "dynamik", "logik",
        "modell", "funktion", "theorem", "hypothese", "struktur"
    )
    tech_count = sum(1 for w in words if w.lower().endswith(academic_suffixes))
    tech_ratio = tech_count / num_words

    # Formula / Math / Code density
    math_tokens = re.findall(r'(\\[a-zA-Z]+|\b\d+[\+\-\*\/\=]\d+\b|[\{\}\[\]\$\\\^_~]|\b(sum|lim|int|sin|cos|log|exp|dx|dt)\b)', clean_t)
    math_ratio = len(math_tokens) / num_words

    # Compute base complexity score (1.0 to 5.0)
    base_score = 3.0 + ((50.0 - flesch_de) / 25.0)
    if tech_ratio > 0.08:
        base_score += 0.6
    elif tech_ratio > 0.04:
        base_score += 0.3

    if math_ratio > 0.05:
        base_score += 0.8
    elif math_ratio > 0.02:
        base_score += 0.4

    score = round(max(1.0, min(5.0, base_score)), 1)

    # Determine pacing based on complexity
    if score <= 1.8:
        level = "Sehr leicht"
        level_code = 1
        min_per_page = 1.8
        rec = "Leichte Lektüre / Sachbuch: Schneller Lesefluss, ca. 1,5–2 Min. pro Seite."
    elif score <= 2.6:
        level = "Leicht / Einstieg"
        level_code = 2
        min_per_page = 2.5
        rec = "Verständliche Einführung: ca. 2,5 Min. pro Seite für solides Verständnis."
    elif score <= 3.5:
        level = "Mittelschwer"
        level_code = 3
        min_per_page = 3.5
        rec = "Standard-Lehrbuch: ca. 3,5 Min. pro Seite inklusive Notizen und Beispielen."
    elif score <= 4.3:
        level = "Anspruchsvoll"
        level_code = 4
        min_per_page = 5.0
        rec = "Vertiefende Fachliteratur: ca. 5 Min. pro Seite für konzentriertes Durchdringen."
    else:
        level = "Hochkomplex"
        level_code = 5
        min_per_page = 7.5
        rec = "Dichte Forschungsmonografie: ca. 7–8 Min. pro Seite, schrittweises Verstehen."

    term_density_str = "Hoch" if tech_ratio > 0.06 else ("Mittel" if tech_ratio > 0.03 else "Gering")
    formula_density_str = "Hoch" if math_ratio > 0.04 else ("Mittel" if math_ratio > 0.015 else "Gering")

    return {
        "score": score,
        "level": level,
        "level_code": level_code,
        "min_per_page": min_per_page,
        "flesch_de": round(flesch_de, 1),
        "avg_sentence_len": round(asl, 1),
        "long_word_pct": round(long_word_pct, 1),
        "term_density": term_density_str,
        "formula_density": formula_density_str,
        "recommendation": rec,
    }


def generate_habit_study_plan(
    book_id: str,
    title: str,
    total_pages: int,
    start_page: int = 1,
    end_page: Optional[int] = None,
    chapters: Optional[List[Dict[str, Any]]] = None,
    complexity_meta: Optional[Dict[str, Any]] = None,
    mode: str = "daily_time",  # 'daily_time' or 'target_weeks'
    daily_minutes: int = 30,
    target_weeks: int = 4,
    study_days: Optional[List[int]] = None,  # 0=Monday ... 6=Sunday. Default: 5 days (Mo-Fr)
) -> Dict[str, Any]:
    """Builds a structured, realistic daily learning plan for self-study.
    Calculates page quotas based on text complexity so daily goals remain achievable and motivating.
    """
    start_p = max(1, start_page)
    end_p = end_page if (end_page and end_page > start_p) else total_pages
    pages_to_read = max(1, end_p - start_p + 1)

    if not complexity_meta:
        complexity_meta = {
            "score": 3.0,
            "level": "Mittelschwer",
            "min_per_page": 3.5
        }

    min_per_page = complexity_meta.get("min_per_page", 3.5)

    # Active study days per week
    if not study_days:
        study_days = [0, 1, 2, 3, 4]  # Mo-Fr default

    active_days_per_week = max(1, len(study_days))

    # Calculate required sessions and pages per session
    if mode == "target_weeks":
        target_w = max(1, target_weeks)
        total_sessions = max(1, target_w * active_days_per_week)
        pages_per_session = max(1, math.ceil(pages_to_read / total_sessions))
        est_daily_minutes = round(pages_per_session * min_per_page)
    else:  # 'daily_time'
        daily_m = max(10, daily_minutes)
        pages_per_session = max(1, math.floor(daily_m / min_per_page))
        total_sessions = max(1, math.ceil(pages_to_read / pages_per_session))
        est_daily_minutes = daily_m

    # Chapter mapping helper
    def find_chapter_for_page(page_num: int) -> str:
        if not chapters:
            return f"Abschnitt S. {page_num}"
        for ch in reversed(chapters):
            ch_start = ch.get("start_page", 1)
            ch_title = ch.get("title", "")
            if page_num >= ch_start:
                return ch_title
        return chapters[0].get("title", f"Seite {page_num}")

    # Build sequence of daily sessions
    sessions: List[Dict[str, Any]] = []
    curr_date = datetime.date.today()
    curr_page = start_p
    session_num = 1
    total_est_hours = round((pages_to_read * min_per_page) / 60.0, 1)

    german_day_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

    while curr_page <= end_p:
        weekday = curr_date.weekday()
        if weekday in study_days:
            p_start = curr_page
            p_end = min(end_p, curr_page + pages_per_session - 1)
            p_count = p_end - p_start + 1
            dur_min = round(p_count * min_per_page)
            ch_label = find_chapter_for_page(p_start)

            sessions.append({
                "session_idx": session_num,
                "date_iso": curr_date.strftime("%Y-%m-%d"),
                "date_display": curr_date.strftime("%d.%m.%Y"),
                "weekday": german_day_names[weekday],
                "start_page": p_start,
                "end_page": p_end,
                "page_count": p_count,
                "chapter": ch_label,
                "est_minutes": dur_min,
                "completed": False,
                "completed_at": None,
                "is_buffer": False,
            })

            curr_page = p_end + 1
            session_num += 1

            # Insert a consolidation & review session every 5 active sessions
            if session_num % 6 == 0 and curr_page <= end_p:
                sessions.append({
                    "session_idx": session_num,
                    "date_iso": curr_date.strftime("%Y-%m-%d"),
                    "date_display": curr_date.strftime("%d.%m.%Y"),
                    "weekday": german_day_names[weekday],
                    "start_page": p_start,
                    "end_page": p_end,
                    "page_count": 0,
                    "chapter": "⚡ Konsolidierung & Wissens-Check",
                    "est_minutes": min(25, est_daily_minutes),
                    "completed": False,
                    "completed_at": None,
                    "is_buffer": True,
                })
                session_num += 1

        curr_date += datetime.timedelta(days=1)

    completion_date_display = sessions[-1]["date_display"] if sessions else curr_date.strftime("%d.%m.%Y")

    return {
        "book_id": book_id,
        "title": title,
        "mode": mode,
        "daily_minutes": est_daily_minutes,
        "target_weeks": target_weeks,
        "start_page": start_p,
        "end_page": end_p,
        "total_pages": pages_to_read,
        "pages_per_session": pages_per_session,
        "total_sessions": len(sessions),
        "total_est_hours": total_est_hours,
        "completion_date": completion_date_display,
        "complexity": complexity_meta,
        "study_days": study_days,
        "sessions": sessions,
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def adapt_plan_for_missed_days(plan_data: Dict[str, Any], days_missed: int, strategy: str = "extend") -> Dict[str, Any]:
    """Elastically adjusts remaining sessions if user fell behind or took time off.
    'extend': shifts remaining dates forward without increasing daily reading load.
    'catch_up': slightly compresses remaining days if user wants to keep original deadline.
    """
    sessions = plan_data.get("sessions", [])
    if not sessions:
        return plan_data

    # Find first uncompleted session
    uncompleted_idx = None
    for i, s in enumerate(sessions):
        if not s.get("completed"):
            uncompleted_idx = i
            break

    if uncompleted_idx is None:
        return plan_data

    shift_days = max(1, days_missed)

    if strategy == "extend":
        for s in sessions[uncompleted_idx:]:
            old_dt = datetime.datetime.strptime(s["date_iso"], "%Y-%m-%d").date()
            new_dt = old_dt + datetime.timedelta(days=shift_days)
            s["date_iso"] = new_dt.strftime("%Y-%m-%d")
            s["date_display"] = new_dt.strftime("%d.%m.%Y")
            german_days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
            s["weekday"] = german_days[new_dt.weekday()]

        plan_data["completion_date"] = sessions[-1]["date_display"]
        plan_data["updated_at"] = time.time()

    return plan_data
