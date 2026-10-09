"""Mail & Inbox Service for JARVIS Command Center.
Provides secure IMAP SSL/TLS connectivity for university/private mailboxes,
filtering exclusively for unread messages (UNSEEN), plus connection diagnostics.
"""

import email
import email.utils
import imaplib
from email.header import decode_header
from typing import Any, Dict, List, Optional, Tuple

from core.config import load_config, save_config


def get_mail_settings() -> Dict[str, Any]:
    """Loads email configuration from application config."""
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("mail_enabled", False)),
        "host": str(cfg.get("mail_host", "")),
        "port": int(cfg.get("mail_port", 993)),
        "user": str(cfg.get("mail_user", "")),
        "password": str(cfg.get("mail_password", "")),
        "folder": str(cfg.get("mail_folder", "INBOX")),
        "only_unseen": bool(cfg.get("mail_only_unseen", True)),
    }


def save_mail_settings(host: str, user: str, password: str, port: int = 993, enabled: bool = True, only_unseen: bool = True) -> bool:
    """Saves email connection parameters to local configuration."""
    cfg = load_config()
    cfg["mail_enabled"] = enabled
    cfg["mail_host"] = host.strip()
    cfg["mail_port"] = port
    cfg["mail_user"] = user.strip()
    cfg["mail_password"] = password.strip().replace(" ", "")
    cfg["mail_only_unseen"] = only_unseen
    _drop_connection()
    return save_config(cfg)


import socket
import threading

_CONN_LOCK = threading.RLock()
_CONN: Optional[imaplib.IMAP4_SSL] = None
_CONN_KEY: Optional[Tuple[str, int, str, str]] = None


def _drop_connection() -> None:
    """Closes the cached connection silently."""
    global _CONN, _CONN_KEY
    conn, _CONN, _CONN_KEY = _CONN, None, None
    if conn is not None:
        try:
            conn.logout()
        except Exception:
            pass


def _get_connection(settings: Dict[str, Any], readonly: bool = True) -> imaplib.IMAP4_SSL:
    """Returns a live IMAP connection (reused, NOOP-checked, reconnects on failure) with folder selected."""
    global _CONN, _CONN_KEY
    user = settings["user"].strip()
    pwd = settings["password"].strip().replace(" ", "")
    key = (settings["host"], int(settings["port"]), user, pwd)

    if _CONN is not None and _CONN_KEY == key:
        try:
            _CONN.noop()
        except Exception:
            _drop_connection()
    elif _CONN is not None:
        _drop_connection()

    if _CONN is None:
        conn = imaplib.IMAP4_SSL(settings["host"], settings["port"], timeout=15.0)
        conn.login(user, pwd)
        _CONN, _CONN_KEY = conn, key

    _CONN.select(settings["folder"], readonly=readonly)
    return _CONN


def test_mail_connection(host: str, port: int, user: str, password: str) -> Tuple[bool, str, int]:
    """Tests IMAP connection and returns (success, message, unread_count)."""
    if not host or not user or not password:
        return False, "Bitte Server, E-Mail-Adresse und Passwort ausfüllen.", 0

    clean_pwd = password.strip().replace(" ", "")
    clean_user = user.strip()

    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=6.0)
        mail.login(clean_user, clean_pwd)
        mail.select("INBOX", readonly=True)

        status, messages = mail.search(None, "UNSEEN")
        unread_count = 0
        if status == "OK" and messages[0]:
            unread_count = len(messages[0].split())

        mail.logout()
        return True, f"Verbindung erfolgreich! {unread_count} ungelesene E-Mails im Posteingang.", unread_count
    except imaplib.IMAP4.error as e:
        err_msg = str(e)
        if "AUTHENTICATIONFAILED" in err_msg.upper() or "LOGIN" in err_msg.upper():
            return False, "Authentifizierung fehlgeschlagen: Bitte das 16-stellige App-Passwort aus Google verwenden (nicht das normale Passwort)!", 0
        return False, f"IMAP-Fehler: {err_msg}", 0
    except (socket.timeout, TimeoutError):
        return False, "Zeitüberschreitung: Server antwortet nicht (Timeout nach 6s). Bitte Internetverbindung prüfen.", 0
    except Exception as e:
        return False, f"Netzwerk-/Serverfehler: {e}", 0


def _decode_header_str(val: Any) -> str:
    """Decodes MIME encoded email header subjects or senders."""
    if not val:
        return ""
    try:
        decoded_list = decode_header(val)
        result = []
        for text, encoding in decoded_list:
            if isinstance(text, bytes):
                result.append(text.decode(encoding or "utf-8", errors="ignore"))
            else:
                result.append(str(text))
        return " ".join(result)
    except Exception:
        return str(val)


def _extract_body_and_html_from_message(msg: email.message.Message) -> Tuple[str, str]:
    """Extracts readable body text and raw HTML from an email message."""
    text_content = []
    html_content = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in cd:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/plain":
                text_content.append(decoded)
            elif ct == "text/html":
                html_content.append(decoded)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_content.append(decoded)
            else:
                text_content.append(decoded)

    raw_text = "\n".join(text_content).strip()
    raw_html = "\n".join(html_content).strip()

    if not raw_text and raw_html:
        import re
        clean = re.sub(r"<style.*?</style>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"<script.*?</script>", "", clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"<br\s*/?>", "\n", clean, flags=re.IGNORECASE)
        clean = re.sub(r"</p>", "\n\n", clean, flags=re.IGNORECASE)
        clean = re.sub(r"<[^>]+>", " ", clean)
        lines = [l.strip() for l in clean.splitlines() if l.strip()]
        raw_text = "\n".join(lines).strip()

    return raw_text or "(Diese Nachricht enthält keinen reinen Textinhalt oder besteht nur aus Anhängen.)", raw_html


_EMAIL_CONTENT_CACHE: Dict[str, Dict[str, Any]] = {}


def fetch_single_email_content(msg_id: str) -> Dict[str, Any]:
    """Fetches full text and HTML content of an email by IMAP message ID."""
    global _EMAIL_CONTENT_CACHE
    if msg_id in _EMAIL_CONTENT_CACHE:
        return _EMAIL_CONTENT_CACHE[msg_id]

    if not msg_id or msg_id.startswith("demo_"):
        for m in _get_demo_inbox():
            if m.get("id") == msg_id:
                return {
                    "text": m.get("body", ""),
                    "html": m.get("html", ""),
                    "subject": m.get("subject", ""),
                    "sender": m.get("sender", ""),
                    "sender_email": m.get("sender_email", ""),
                    "date": m.get("date", ""),
                }
        return {"text": "(Keine E-Mail-Daten gefunden)", "html": ""}

    settings = get_mail_settings()
    if not (settings["enabled"] and settings["host"] and settings["user"] and settings["password"]):
        return {"text": "E-Mail-Server ist nicht eingerichtet.", "html": ""}

    try:
        with _CONN_LOCK:
            try:
                mail = _get_connection(settings, readonly=True)
                res, data = mail.fetch(msg_id, "(RFC822)")
            except (imaplib.IMAP4.abort, OSError):
                _drop_connection()
                mail = _get_connection(settings, readonly=True)
                res, data = mail.fetch(msg_id, "(RFC822)")

        if res == "OK" and data and isinstance(data[0], tuple):
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            text, html = _extract_body_and_html_from_message(msg)
            raw_from = _decode_header_str(msg.get("From", ""))
            p_name, p_addr = email.utils.parseaddr(raw_from)
            sender_display = p_name or p_addr.split("@")[0] or raw_from
            sender_email = p_addr or raw_from

            data_res = {
                "text": text,
                "html": html,
                "subject": _decode_header_str(msg.get("Subject", "")),
                "sender": sender_display,
                "sender_email": sender_email,
                "date": str(msg.get("Date", ""))[:25],
            }
            _EMAIL_CONTENT_CACHE[msg_id] = data_res
            return data_res
        return {"text": "E-Mail-Inhalt konnte vom Server nicht gelesen werden.", "html": ""}
    except Exception as e:
        return {"text": f"Fehler beim Abrufen der E-Mail: {e}", "html": ""}


def fetch_single_email_body(msg_id: str) -> str:
    """Fetches full body of an email by IMAP message ID."""
    return fetch_single_email_content(msg_id).get("text", "")


def delete_email_by_id(msg_id: str) -> Tuple[bool, str]:
    """Moves an email to Trash / deletes it by message ID."""
    global _ACTIVE_DEMO_MAILS, _EMAIL_CONTENT_CACHE
    if not msg_id:
        return False, "Keine E-Mail-ID angegeben."

    _EMAIL_CONTENT_CACHE.pop(msg_id, None)

    if msg_id.startswith("demo_"):
        curr = _get_demo_inbox()
        _ACTIVE_DEMO_MAILS = [m for m in curr if m.get("id") != msg_id]
        return True, "E-Mail in den Papierkorb verschoben."

    settings = get_mail_settings()
    if not (settings["enabled"] and settings["host"] and settings["user"] and settings["password"]):
        return False, "E-Mail-Server ist nicht eingerichtet."

    try:
      with _CONN_LOCK:
        mail = _get_connection(settings, readonly=False)

        # In Gmail: try copying to [Gmail]/Trash or [Gmail]/Papierkorb
        try:
            status, folders = mail.list()
            if status == "OK":
                for f in folders:
                    f_name = f.decode("utf-8", errors="ignore")
                    if any(w in f_name for w in ["\\Trash", "Papierkorb", "Trash", "Bin"]):
                        parts = f_name.split(' "/" ')
                        if len(parts) >= 2:
                            trash_target = parts[-1].strip().strip('"')
                            mail.copy(msg_id, f'"{trash_target}"')
                            break
        except Exception:
            pass

        # Flag \Deleted and expunge from current folder
        mail.store(msg_id, "+FLAGS", "\\Deleted")
        mail.expunge()
        return True, "E-Mail erfolgreich in den Papierkorb verschoben."
    except Exception as e:
        return False, f"Fehler beim Löschen der E-Mail: {e}"


def fetch_inbox_messages(limit: int = 6) -> List[Dict[str, Any]]:
    """Fetches unread emails via IMAP with instant pre-caching for 0ms opening performance."""
    global _EMAIL_CONTENT_CACHE
    settings = get_mail_settings()

    if settings["enabled"] and settings["host"] and settings["user"] and settings["password"]:
        try:
          with _CONN_LOCK:
            mail = _get_connection(settings, readonly=True)

            search_filter = "UNSEEN" if settings.get("only_unseen", True) else "ALL"
            status, messages = mail.search(None, search_filter)

            fetched_mails: List[Dict[str, Any]] = []
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                recent_ids = msg_ids[-limit:][::-1]  # Most recent first

                for mid in recent_ids:
                    mid_str = mid.decode("utf-8", errors="ignore") if isinstance(mid, bytes) else str(mid)
                    res, data = mail.fetch(mid, "(RFC822)")
                    if res == "OK" and data and isinstance(data[0], tuple):
                        raw_email = data[0][1]
                        msg = email.message_from_bytes(raw_email)

                        subject = _decode_header_str(msg.get("Subject", "Kein Betreff"))
                        raw_from = _decode_header_str(msg.get("From", "Unbekannt"))
                        p_name, p_addr = email.utils.parseaddr(raw_from)
                        sender_display = p_name or p_addr.split("@")[0] or raw_from
                        sender_email = p_addr or raw_from
                        date_str = str(msg.get("Date", "Heute"))[:16]

                        text_body, html_body = _extract_body_and_html_from_message(msg)
                        clean_snip = " ".join(text_body.split())
                        snippet = clean_snip[:110] if clean_snip else f"Nachricht von {sender_display}"

                        # Urgency categorization
                        low_subj = subject.lower()
                        urgency = "normal"
                        if any(w in low_subj for w in ["frist", "wichtig", "klausur", "anmeldung", "dringend", "urgent", "deadline", "sicherheitswarnung", "warnung"]):
                            urgency = "high"
                        elif any(w in low_subj for w in ["skript", "material", "vorlesung", "termin", "aufgabe", "übung"]):
                            urgency = "medium"

                        mail_item = {
                            "id": mid_str,
                            "sender": sender_display,
                            "sender_email": sender_email,
                            "subject": subject,
                            "date": date_str,
                            "snippet": snippet,
                            "urgency": urgency,
                            "is_unread": True,
                            "is_demo": False,
                            "body": text_body,
                            "html": html_body,
                        }
                        _EMAIL_CONTENT_CACHE[mid_str] = mail_item
                        fetched_mails.append(mail_item)

            # Successfully connected to real account: return actual mails (even if empty!)
            return fetched_mails

        except Exception as e:
            _drop_connection()
            return [{
                "id": "err",
                "sender": "Verbindungsfehler",
                "sender_email": "system@error",
                "subject": f"Konnte Postfach nicht abrufen: {e}",
                "date": "Jetzt",
                "snippet": "Überprüfe Host, Passwort oder App-Passwort im Setup.",
                "urgency": "high",
                "is_unread": True,
                "is_demo": False,
                "is_error": True,
                "body": f"Verbindungsfehler aufgetreten:\n{e}\n\nBitte prüfe die Serverdaten und das App-Passwort.",
            }]

    # Only show demo inbox if no email account was configured
    return _get_demo_inbox()


_ACTIVE_DEMO_MAILS: Optional[List[Dict[str, Any]]] = None

def _get_demo_inbox() -> List[Dict[str, Any]]:
    """Returns realistic university mailbox demo when no account is configured."""
    global _ACTIVE_DEMO_MAILS
    if _ACTIVE_DEMO_MAILS is not None:
        return _ACTIVE_DEMO_MAILS

    _ACTIVE_DEMO_MAILS = [
        {
            "id": "demo_1",
            "sender": "Prüfungsamt MINT",
            "sender_email": "pruefungsamt-mint@campus-uni.de",
            "subject": "⚠️ Wichtig: Verlängerung der Rückmeldefrist & Klausuranmeldung",
            "date": "Heute, 08:30",
            "snippet": "Die Frist für die verbindliche Prüfungsanmeldung für das Wintersemester wurde um 48h bis Freitag verlängert.",
            "urgency": "high",
            "is_unread": True,
            "is_demo": True,
            "body": "Sehr geehrte Studierende,\n\naufgrund von planmäßigen Wartungsarbeiten an der IT-Infrastruktur am vergangenen Wochenende wurde die Frist zur verbindlichen Prüfungsanmeldung für sämtliche Pflicht- und Wahlpflichtmodule um 48 Stunden bis Freitag, 23:59 Uhr verlängert.\n\nBitte beachten Sie:\n• Nach Ablauf dieser Frist sind keine Nachmeldungen mehr möglich.\n• Kontrollieren Sie in Ihrem Campus-Portal unter «Meine Prüfungen», ob alle gewünschten Module als angemeldet gelistet sind.\n• Krankmeldungen am Klausurtag müssen innerhalb von 3 Werktagen im Original beim Prüfungsamt eingereicht werden.\n\nBei Rückfragen steht Ihnen die Sprechstunde am Donnerstag von 10:00 bis 12:00 Uhr zur Verfügung.\n\nMit freundlichen Grüßen,\nIhr Prüfungsamt MINT",
        },
        {
            "id": "demo_2",
            "sender": "Prof. Dr. M. Weber (Lehrstuhl)",
            "sender_email": "m.weber@maschinenbau-uni.de",
            "subject": "Vorlesungsmaterialien Kapitel 5 & Probeklausur hochgeladen",
            "date": "Gestern, 18:45",
            "snippet": "Sehr geehrte Studierende, die Foliensätze zu den thermischen Kreisprozessen stehen im Lernraum bereit.",
            "urgency": "medium",
            "is_unread": True,
            "is_demo": True,
            "body": "Liebe Studierende,\n\ndie Unterlagen zur heutigen Vorlesung (Kapitel 5: «Thermodynamische Kreisprozesse, Carnot-Wirkungsgrad und Exergie») sowie die Musterlösung zu Übungsblatt 4 sind ab sofort im digitalen Lernraum freigeschaltet.\n\nZudem habe ich eine Probeklausur aus dem letzten Semester samt ausführlichem Erwartungshorizont hochgeladen. Ich empfehle Ihnen dringend, diese unter Realbedingungen (90 Minuten Bearbeitungszeit ohne Hilfsmittel außer Formelsammlung) durchzurechnen.\n\nIn der kommenden Übung werden wir gezielt Ihre Fragen dazu besprechen.\n\nBeste Grüße,\nProf. Dr. M. Weber",
        },
        {
            "id": "demo_3",
            "sender": "Universitätsbibliothek",
            "sender_email": "service@ub-campus.de",
            "subject": "Erinnerung: Leihfrist-Ende für 2 Vormerkungen in 3 Tagen",
            "date": "Gestern, 11:20",
            "snippet": "Ihre entliehenen Lehrbücher können online um weitere 14 Tage verlängert werden.",
            "urgency": "normal",
            "is_unread": True,
            "is_demo": True,
            "body": "Sehr geehrte Bibliotheksbenutzerin, sehr geehrter Benutzer,\n\nwir möchten Sie daran erinnern, dass die Leihfrist für folgende entliehene Medien in 3 Tagen abläuft:\n\n1. Dubbel – Taschenbuch für den Maschinenbau (Signatur: MB-2024-88)\n2. Bronstein – Taschenbuch der Mathematik (Signatur: MA-101)\n\nVerlängerungsmöglichkeiten:\nSofern keine Vormerkung durch andere Leser vorliegt, können Sie die Leihfrist über Ihr Benutzerkonto im Bibliothekskatalog bequem um weitere 14 Tage verlängern.\n\nBitte vermeiden Sie Mahngebühren durch rechtzeitige Rückgabe oder Verlängerung.\n\nIhr Bibliotheksteam",
        },
        {
            "id": "demo_4",
            "sender": "Fachschaftsrat",
            "sender_email": "kontakt@fachschaft-mint.de",
            "subject": "Einladung: Digitaler Campus-Hackathon & Lerngruppen-Börse",
            "date": "Vor 2 Tagen",
            "snippet": "Finde deinen Lernpartner für die anstehenden Modulprüfungen – Anmeldung ab sofort möglich.",
            "urgency": "normal",
            "is_unread": True,
            "is_demo": True,
            "body": "Hallo zusammen!\n\ndie Prüfungsphase rückt näher und gemeinsam lernt es sich bekanntlich leichter! Deshalb veranstalten wir nächsten Donnerstag ab 17:00 Uhr die diesjährige Lerngruppen-Börse mit anschließendem Mini-Hackathon im Foyer des Informatik-Gebäudes.\n\nWas euch erwartet:\n• Matchmaking nach Modulen (Mathe II, Technische Mechanik, Programmieren)\n• Kostenlose Snacks, Mate und Pizza\n• Mentoren aus höheren Semestern für knifflige Fragen\n\nKommt einfach vorbei oder meldet euer Team vorab online an: https://fachschaft-mint.de/events\n\nWir freuen uns auf euch!\nEuer Fachschaftsrat",
        }
    ]
