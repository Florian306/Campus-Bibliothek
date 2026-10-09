"""High-performance calendar and schedule service.
Supports local scheduling and remote iCal/WebCal (.ics) synchronization
compatible with Google Calendar, Outlook/Office 365, Apple Calendar, and university timetables.
"""

import re
import time
import threading
import urllib.request
import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.config import load_config, save_config
from core.library_db import (
    _db_write_lock,
    get_db_connection,
    add_calendar_event,
    get_calendar_events_for_date,
    get_upcoming_calendar_events,
    delete_calendar_event,
    clear_synced_calendar_events,
)

_SYNC_WINDOW_PAST_DAYS = 1
_SYNC_WINDOW_FUTURE_DAYS = 365
_AUTO_SYNC_MAX_AGE_S = 600
_DISPLAY_LIMIT = 8
_last_sync_ts: float = 0.0
_sync_lock = threading.Lock()

_WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def get_cal_url() -> str:
    """Returns saved iCal/WebCal calendar URL from config."""
    cfg = load_config()
    return str(cfg.get("cal_url", ""))


def save_cal_url(url: str) -> bool:
    """Saves calendar URL to application config."""
    cfg = load_config()
    if cfg.get("cal_url") == url.strip():
        return True
    cfg["cal_url"] = url.strip()
    return save_config(cfg)


# ---------------------------------------------------------------- ICS parsing

def _unfold_ics(content: str) -> List[str]:
    return re.sub(r"\r?\n[ \t]", "", content).splitlines()


def _unescape_ics(val: str) -> str:
    return (val.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\").strip())


def _split_prop(line: str) -> Tuple[str, Dict[str, str], str]:
    head, _, value = line.partition(":")
    parts = head.split(";")
    params: Dict[str, str] = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v
    return parts[0].upper(), params, value.strip()


def _ics_to_local(value: str, params: Dict[str, str]) -> Tuple[datetime.datetime, bool]:
    """Returns (naive local datetime, is_all_day)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return datetime.datetime.strptime(value[:8], "%Y%m%d"), True
    dt = datetime.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        # UTC -> system local time
        dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    return dt, False


def _normalize_rrule_until(rrule: str) -> str:
    # dateutil rejects UTC UNTIL with naive DTSTART -> convert to local naive
    def _fix(m: "re.Match[str]") -> str:
        try:
            loc, _ = _ics_to_local(m.group(1), {})
            return "UNTIL=" + loc.strftime("%Y%m%dT%H%M%S")
        except Exception:
            return m.group(0)
    return re.sub(r"UNTIL=(\d{8}T\d{6}Z)", _fix, rrule)


def parse_ics_datetime(dt_str: str) -> Tuple[str, str]:
    """Extracts date (YYYY-MM-DD) and local time (HH:MM) from an iCal date string."""
    try:
        dt, all_day = _ics_to_local(re.sub(r"[^0-9TZ]", "", dt_str), {})
        return dt.date().isoformat(), ("Ganztägig" if all_day else dt.strftime("%H:%M"))
    except Exception:
        return datetime.date.today().isoformat(), "09:00"


def _detect_category(title: str) -> str:
    low_t = title.lower()
    if any(k in low_t for k in ["klausur", "prüfung", "exam", "test", "abgabe", "deadline"]):
        return "Prüfung"
    if any(k in low_t for k in ["vorlesung", "lecture", "übung", "tutorium", "seminar", "einführung", "modul", "kurs", "wissenschaft", "didaktik", "theorie", "schreibe", "schreiben", "bachelor", "master"]):
        return "Uni"
    if any(k in low_t for k in ["praktikum", "praxis", "arbeit", "job", "meeting", "projekt"]):
        return "Praxis"
    if any(k in low_t for k in ["lernen", "recherche", "bibliothek", "study", "hausarbeit", "skript"]):
        return "Lernen"
    if any(k in low_t for k in ["lampe", "aufladen", "akku", "wartung", "routine", "haushalt", "erinnerung", "to-do", "todo"]):
        return "Aufgabe"
    if any(k in low_t for k in ["geburtstag", "urlaub", "essen", "hund", "pause", "todestag", "party", "arzt", "sport"]):
        return "Privat"
    return "Termin"


def _parse_vevents(content: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for line in _unfold_ics(content):
        if line == "BEGIN:VEVENT":
            cur = {"exdates": []}
            continue
        if line == "END:VEVENT":
            if cur is not None and "start" in cur:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        name, params, value = _split_prop(line)
        try:
            if name == "SUMMARY":
                cur["title"] = _unescape_ics(value)
            elif name == "LOCATION":
                cur["location"] = _unescape_ics(value)
            elif name == "UID":
                cur["uid"] = value
            elif name == "STATUS":
                cur["status"] = value.upper()
            elif name == "RRULE":
                cur["rrule"] = value
            elif name == "DTSTART":
                cur["start"], cur["all_day"] = _ics_to_local(value, params)
            elif name == "DTEND":
                cur["end"], _ = _ics_to_local(value, params)
            elif name == "RECURRENCE-ID":
                cur["recurrence_id"], _ = _ics_to_local(value, params)
            elif name == "EXDATE":
                for v in value.split(","):
                    cur["exdates"].append(_ics_to_local(v, params)[0])
        except Exception:
            continue
    return events


def _expand_events(raw: List[Dict[str, Any]]) -> List[Tuple[str, str, str, str, str, str]]:
    """Expands recurring events into concrete rows within the sync window."""
    today = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
    win_start = today - datetime.timedelta(days=_SYNC_WINDOW_PAST_DAYS)
    win_end = today + datetime.timedelta(days=_SYNC_WINDOW_FUTURE_DAYS)

    overrides = {(e.get("uid"), e["recurrence_id"]) for e in raw if e.get("recurrence_id")}
    rows: List[Tuple[str, str, str, str, str, str]] = []

    for ev in raw:
        if ev.get("status") == "CANCELLED":
            continue
        start: datetime.datetime = ev["start"]
        all_day = ev.get("all_day", False)
        duration = (ev.get("end") or start) - start
        title = (ev.get("title") or "Termin")[:80]

        occurrences: List[datetime.datetime] = []
        if ev.get("rrule") and not ev.get("recurrence_id"):
            try:
                from dateutil.rrule import rrulestr
                rule = rrulestr(_normalize_rrule_until(ev["rrule"]), dtstart=start)
                exdates = set(ev["exdates"])
                for occ in rule.between(win_start, win_end, inc=True):
                    if occ in exdates or (ev.get("uid"), occ) in overrides:
                        continue
                    occurrences.append(occ)
            except Exception:
                occurrences = [start] if win_start <= start <= win_end else []
        elif win_start <= start <= win_end:
            occurrences = [start]

        for occ in occurrences:
            end = occ + duration
            rows.append((
                title,
                occ.date().isoformat(),
                "Ganztägig" if all_day else occ.strftime("%H:%M"),
                "Ganztägig" if all_day else end.strftime("%H:%M"),
                (ev.get("location") or "")[:60],
                _detect_category(title),
            ))
    return rows


# ---------------------------------------------------------------- Sync

def sync_webcal_feed(ics_url: str) -> Tuple[int, str]:
    """Downloads and parses an iCal/WebCal URL, atomically replacing synced events."""
    global _last_sync_ts
    url = ics_url.strip()
    if not url:
        return 0, "Keine URL angegeben."

    save_cal_url(url)

    if url.startswith("webcal://"):
        url = "https://" + url[9:]
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Buchsortierer-CampusAI/1.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return 0, f"Netzwerkfehler beim Abrufen des Kalenders: {e}"

    if "BEGIN:VEVENT" not in content:
        return 0, "Keine Termine (VEVENT) im iCal-Feed gefunden."

    rows = _expand_events(_parse_vevents(content))

    # Single transaction -> UI never sees a half-empty calendar
    conn = get_db_connection()
    now_ts = time.time()
    with _db_write_lock:
        try:
            conn.execute("DELETE FROM calendar_events WHERE source IN ('ical', 'local')")
            conn.executemany(
                "INSERT INTO calendar_events (title, event_date, start_time, end_time, location, category, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'ical', ?)",
                [r + (now_ts,) for r in rows],
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            return 0, f"Datenbankfehler beim Speichern der Termine: {e}"

    _last_sync_ts = now_ts
    return len(rows), f"{len(rows)} Termine erfolgreich synchronisiert."


def ensure_calendar_synced(force: bool = False) -> None:
    """Re-syncs the saved calendar feed if the last sync is older than _AUTO_SYNC_MAX_AGE_S."""
    url = get_cal_url()
    if not url:
        return
    if not force and time.time() - _last_sync_ts < _AUTO_SYNC_MAX_AGE_S:
        return
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        sync_webcal_feed(url)
    finally:
        _sync_lock.release()


def clear_all_demo_events() -> None:
    """Removes all initial mock demo events from database."""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM calendar_events WHERE source = 'local'")
        conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------- Queries

def is_event_passed(ev: Dict[str, Any]) -> bool:
    """Checks whether a calendar event has already ended (is in the past)."""
    try:
        now = datetime.datetime.now()
        today_str = now.date().isoformat()
        ev_date = ev.get("event_date", "")
        if not ev_date:
            return False
        if ev_date < today_str:
            return True
        if ev_date > today_str:
            return False

        start_t = str(ev.get("start_time", "")).strip()
        end_t = str(ev.get("end_time", "")).strip()
        now_t = now.strftime("%H:%M")

        if start_t.lower() in ["ganztägig", "all-day", "ganztags"]:
            return False

        if end_t and ":" in end_t:
            # End before start -> event runs past midnight
            if start_t and ":" in start_t and end_t < start_t:
                return False
            return end_t <= now_t
        elif start_t and ":" in start_t:
            return start_t <= now_t

        return False
    except Exception:
        return False


def format_event_day(event_date: str) -> str:
    """Returns 'Heute', 'Morgen' or e.g. 'Di 06.10.'."""
    try:
        d = datetime.date.fromisoformat(event_date)
    except Exception:
        return event_date
    delta = (d - datetime.date.today()).days
    if delta == 0:
        return "Heute"
    if delta == 1:
        return "Morgen"
    return f"{_WEEKDAYS_DE[d.weekday()]} {d.strftime('%d.%m.')}"


def format_event_relative(event_date: str) -> str:
    """Returns human-readable countdown string like 'Heute', 'Morgen', 'In 6 Tagen', 'In 2 Wochen'."""
    try:
        d = datetime.date.fromisoformat(event_date)
    except Exception:
        return ""
    delta = (d - datetime.date.today()).days
    if delta < 0:
        return "Vergangen"
    if delta == 0:
        return "Heute"
    if delta == 1:
        return "Morgen"
    if delta < 7:
        return f"In {delta} Tagen"
    if delta < 14:
        return f"In 1 Woche ({delta} T.)"
    weeks = delta // 7
    return f"In {weeks} Wochen"


def calculate_event_duration(start_time: str, end_time: str) -> str:
    """Calculates duration between two HH:MM strings and returns e.g. '1 Std.', '1.5 Std.', '45 Min.'."""
    if not start_time or not end_time or ":" not in start_time or ":" not in end_time:
        return ""
    try:
        sh, sm = map(int, start_time.split(":")[:2])
        eh, em = map(int, end_time.split(":")[:2])
        start_mins = sh * 60 + sm
        end_mins = eh * 60 + em
        diff = end_mins - start_mins
        if diff <= 0:
            return ""
        if diff < 60:
            return f"{diff} Min."
        if diff % 60 == 0:
            hrs = diff // 60
            return f"{hrs} Std." if hrs == 1 else f"{hrs} Std."
        hrs_float = diff / 60.0
        return f"{hrs_float:.1f} Std.".replace(".0", "")
    except Exception:
        return ""


def get_display_events() -> Tuple[List[Dict[str, Any]], bool]:
    """Returns the next upcoming, not yet finished events (today first).
    Returns (events, has_today_events).
    """
    today_str = datetime.date.today().isoformat()
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT * FROM calendar_events WHERE event_date >= ? ORDER BY event_date ASC, "
        "CASE WHEN start_time LIKE '%:%' THEN start_time ELSE '00:00' END ASC LIMIT 60",
        (today_str,),
    )
    active = [dict(r) for r in cur.fetchall() if not is_event_passed(dict(r))][:_DISPLAY_LIMIT]

    if not active and not get_cal_url():
        seed_default_schedule_if_empty()
        active = [e for e in get_calendar_events_for_date(today_str) if not is_event_passed(e)]

    has_today = any(e.get("event_date") == today_str for e in active)
    return active, has_today


def get_today_events(include_passed: bool = False) -> List[Dict[str, Any]]:
    """Retrieves calendar events for today, omitting passed events by default."""
    today_str = datetime.date.today().isoformat()
    events = get_calendar_events_for_date(today_str)
    if not include_passed:
        return [e for e in events if not is_event_passed(e)]
    return events


def get_next_upcoming_event() -> Optional[Tuple[Dict[str, Any], int]]:
    """Finds the next event today that has not started yet and returns (event, minutes_until)."""
    today_events = get_today_events()
    now = datetime.datetime.now()
    current_minutes = now.hour * 60 + now.minute

    for ev in today_events:
        time_str = ev.get("start_time", "")
        if ":" in time_str:
            try:
                h, m = map(int, time_str.split(":")[:2])
                diff = h * 60 + m - current_minutes
                if diff >= 0:
                    return ev, diff
            except Exception:
                continue
    return None


def seed_default_schedule_if_empty() -> None:
    """Populates initial mock demo schedule only if table is completely empty."""
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
    if count > 0:
        return

    today_str = datetime.date.today().isoformat()

    add_calendar_event(
        title="Vorlesung: Höhere Mathematik II",
        event_date=today_str,
        start_time="10:15",
        end_time="11:45",
        location="Hörsaal 3 (Campus Mitte)",
        category="Uni",
        source="local"
    )
    add_calendar_event(
        title="Übungsgruppe & Aufgabenbesprechung",
        event_date=today_str,
        start_time="14:00",
        end_time="15:30",
        location="Seminarraum B-12",
        category="Lernen",
        source="local"
    )
    add_calendar_event(
        title="Fokus-Lernfenster: Maslow & Psychologie",
        event_date=today_str,
        start_time="16:30",
        end_time="18:00",
        location="Universitätsbibliothek (Lesesaal)",
        category="Lernen",
        source="local"
    )
