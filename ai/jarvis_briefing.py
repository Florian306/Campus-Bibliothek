"""JARVIS Briefing & Voice Synthesis Engine.
Synthesizes agenda, upcoming events, unread emails, and top news into a seamless daily executive summary.
Includes zero-dependency native Windows SpeechSynthesizer TTS audio playback.
"""

import os
import re
import datetime
import subprocess
import threading
from typing import Any, Dict, List, Optional

from core.calendar_service import get_today_events, get_next_upcoming_event
from core.library_db import get_desk_books, get_gamification_status
from core.mail_service import fetch_inbox_messages
from core.rss_news_service import fetch_live_news


_speech_process: Optional[subprocess.Popen] = None
_speech_lock = threading.Lock()


def get_greeting() -> str:
    """Returns time-appropriate friendly greeting."""
    hour = datetime.datetime.now().hour
    if 5 <= hour < 11:
        return "Guten Morgen, Florian! ☕ Hier ist dein persönliches Briefing für heute:"
    elif 11 <= hour < 14:
        return "Mahlzeit, Florian! ☀️ Hier ist dein aktueller Tagesüberblick:"
    elif 14 <= hour < 18:
        return "Guten Nachmittag, Florian! 📚 Hier ist der Status deiner Agenda:"
    else:
        return "Guten Abend, Florian! 🌙 Hier ist dein Tages-Rückblick und Ausblick:"


def generate_executive_briefing() -> str:
    """Creates a comprehensive AI executive briefing from agenda, mails, and news."""
    today_events = get_today_events()
    next_event_info = get_next_upcoming_event()
    desk_books = get_desk_books()
    gamification = get_gamification_status()
    mails = fetch_inbox_messages(limit=4)
    news = fetch_live_news()

    streak = gamification.get("current_streak", 0)
    level = gamification.get("level", 1)

    # Context compilation
    events_summary = []
    for ev in today_events[:3]:
        events_summary.append(f"{ev.get('start_time')}: {ev.get('title')} ({ev.get('location', 'Campus')})")
    events_text = ", ".join(events_summary) if events_summary else "Keine festen Termine für heute eingetragen."

    desk_summary = []
    for b in desk_books[:2]:
        desk_summary.append(f"{b.get('title')} ({b.get('reading_progress', 0)}%)")
    desk_text = ", ".join(desk_summary) if desk_summary else "Kein Buch auf dem Schreibtisch aktiv."

    high_urgency_mails = [m for m in mails if m.get("urgency") == "high"]
    mail_count = len(mails)

    news_top = [n.get("title") for n in news[:3]]
    news_text = " | ".join(news_top) if news_top else "Keine aktuellen Eilmeldungen."

    prompt = (
        f"Du bist JARVIS, ein hochintelligenter, freundlicher und motivierender KI-Assistent für Studierende. "
        f"Erstelle ein präzises, elegantes Morning Briefing (ca. 4-5 Sätze auf Deutsch). "
        f"Nutze diese Daten:\n"
        f"- Heutige Termine: {events_text}\n"
        f"- Bücher am Schreibtisch: {desk_text}\n"
        f"- Lernstreak: {streak} Tage, Level {level}\n"
        f"- E-Mails: {mail_count} neue Nachrichten ({len(high_urgency_mails)} mit hoher Priorität)\n"
        f"- Top Schlagzeilen: {news_text}\n\n"
        f"Formuliere es flüssig zum Vorlesen, direkt an Florian gerichtet. Beginne mit einer kurzen Begrüßung."
    )

    try:
        from ai.gemini_client import generate_response
        resp = generate_response(prompt)
        if resp and len(resp.strip()) > 50:
            return resp.strip()
    except Exception:
        pass

    try:
        from ai.ollama_client import generate_ollama_response
        resp = generate_ollama_response(prompt)
        if resp and len(resp.strip()) > 50:
            return resp.strip()
    except Exception:
        pass

    # Reliable template fallback
    next_ev_str = f" Dein nächster Termin ist {next_event_info[0].get('title')} um {next_event_info[0].get('start_time')} Uhr." if next_event_info else " Heute hast du freie Zeiteinteilung."
    mail_alert = f" Bitte beachte besonders die dringende E-Mail vom {high_urgency_mails[0].get('sender')}." if high_urgency_mails else ""
    desk_alert = f" Auf deinem Schreibtisch wartet «{desk_books[0].get('title')}»." if desk_books else ""

    return (
        f"{get_greeting()}\n\n"
        f"Du hast heute {len(today_events)} Termine im Kalender.{next_ev_str}{desk_alert}{mail_alert} "
        f"Dein Lern-Streak steht bei starken {streak} Tagen! "
        f"In den Schlagzeilen heute: {news[0].get('title') if news else 'Aktuelle MINT-Forschung'}."
    )


def speak_text(text: str, on_finished=None) -> None:
    """Speaks the text aloud using zero-dependency native Windows SpeechSynthesizer."""
    global _speech_process

    stop_speech()

    # Clean text of markdown, asterisks, emojis for smooth TTS pronunciation
    clean = re.sub(r"[\*#_`~]", "", text)
    clean = re.sub(r"[^\w\s\.,;:!\?\-\(\)\/äöüÄÖÜß]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()[:1000]

    if not clean:
        return

    def _worker():
        global _speech_process
        with _speech_lock:
            try:
                # PowerShell script for natural German speech output
                encoded_text = clean.replace("'", "''").replace('"', '`"')
                ps_script = (
                    f"$wshell = New-Object -ComObject WScript.Shell; "
                    f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$synth.Rate = 1; "
                    f"$synth.Speak('{encoded_text}');"
                )
                _speech_process = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )
            except Exception:
                _speech_process = None

        if _speech_process:
            _speech_process.wait()

        if on_finished:
            on_finished()

    threading.Thread(target=_worker, daemon=True).start()


def stop_speech() -> None:
    """Stops any currently playing text-to-speech audio."""
    global _speech_process
    with _speech_lock:
        if _speech_process is not None:
            try:
                _speech_process.terminate()
            except Exception:
                pass
            _speech_process = None
