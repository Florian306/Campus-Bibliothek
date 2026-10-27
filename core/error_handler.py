"""Friendly error message translator and humanizer for network, database, and system errors.
Converts raw Python exceptions and technical HTTP codes into crystal-clear German explanations with actionable advice.
"""

import re
from typing import Any, Optional


def humanize_error(error: Any, context: str = "") -> str:
    """Translates raw exception messages or technical errors into user-friendly German."""
    if not error:
        return "Ein unerwarteter Fehler ist aufgetreten."

    err_str = str(error).strip()
    err_lower = err_str.lower()

    # 1. No Internet / DNS / Name resolution failure
    if any(k in err_lower for k in [
        "getaddrinfo failed",
        "name or service not known",
        "temporary failure in name resolution",
        "nodename nor servname provided",
        "dns_probe_finished_no_internet",
        "err_internet_disconnected",
        "err_name_not_resolved",
    ]):
        return (
            "Keine Internetverbindung verfügbar.\n"
            "Bitte prüfe deine Netzwerkverbindung oder WLAN-Verbindung und versuche es erneut."
        )

    # 2. Connection Refused / Connection Reset / Host Unreachable
    if any(k in err_lower for k in [
        "connection refused",
        "wsaeconnrefused",
        "winerror 10061",
        "connection reset",
        "wsaeconnreset",
        "winerror 10054",
        "network is unreachable",
        "wsaenetunreach",
        "winerror 10051",
        "host is down",
        "wsaehostunreach",
    ]):
        return (
            "Der Server ist momentan nicht erreichbar oder die Verbindung wurde unterbrochen.\n"
            "Bitte prüfe deine Internetverbindung oder versuche es in wenigen Minuten noch einmal."
        )

    # 3. Connection Timeout
    if any(k in err_lower for k in [
        "timed out",
        "timeout",
        "wsaetimedout",
        "winerror 10060",
        "operation timed out",
    ]):
        return (
            "Zeitüberschreitung bei der Verbindung (Timeout).\n"
            "Der Server antwortet zu langsam oder deine Internetverbindung ist ausgelastet."
        )

    # 4. SSL / Certificate / Handshake errors
    if any(k in err_lower for k in [
        "ssl",
        "certificate verify failed",
        "tlsv1",
        "handshake failure",
        "certificaterror",
    ]):
        return (
            "Sichere Verbindung fehlgeschlagen (SSL/Zertifikatsfehler).\n"
            "Möglicherweise blockiert eine Firewall, ein Proxy oder eine Antiviren-Software die sichere Verbindung."
        )

    # 5. HTTP Status Codes
    if "401" in err_lower or "unauthorized" in err_lower:
        return (
            "Authentifizierung fehlgeschlagen (Fehler 401).\n"
            "Bitte überprüfe dein GitHub-Token bzw. deine Anmeldedaten."
        )
    if "403" in err_lower or "forbidden" in err_lower:
        if "rate limit" in err_lower or "api rate limit exceeded" in err_lower:
            return (
                "Anfrage-Limit erreicht (API Rate Limit).\n"
                "Der Dienst erlaubt temporär keine weiteren Abfragen. Bitte warte einige Minuten."
            )
        return (
            "Zugriff verweigert (Fehler 403).\n"
            "Der Server oder Verlag erlaubt keinen direkten Zugriff auf dieses Dokument ohne Autorisierung."
        )
    if "404" in err_lower or "not found" in err_lower:
        return (
            "Dokument oder Seite nicht gefunden (Fehler 404).\n"
            "Die angeforderte Datei existiert auf dem Server nicht mehr oder der Link ist veraltet."
        )
    if "429" in err_lower or "too many requests" in err_lower:
        return (
            "Zu viele Anfragen in kurzer Zeit (Fehler 429).\n"
            "Bitte warte einen kurzen Moment und probiere es dann erneut."
        )
    if any(code in err_lower for code in ["500", "502", "503", "504", "internal server error", "bad gateway", "service unavailable", "gateway timeout"]):
        return (
            "Der externe Server hat technische Probleme (Server-Fehler 5xx).\n"
            "Der wissenschaftliche Dienst ist derzeit überlastet oder wird gewartet."
        )

    # 6. File not found / Permission / Lock errors
    if any(k in err_lower for k in ["filenotfounderror", "no such file or directory", "datei nicht gefunden"]):
        return (
            "Die Datei konnte auf der Festplatte nicht gefunden werden.\n"
            "Möglicherweise wurde sie verschoben oder gelöscht."
        )
    if any(k in err_lower for k in ["permissionerror", "access is denied", "zugriff verweigert"]):
        return (
            "Zugriff verweigert.\n"
            "Die Datei ist möglicherweise noch in einem anderen Programm (z. B. PDF-Reader) geöffnet oder es fehlen Schreibrechte."
        )
    if "database is locked" in err_lower:
        return (
            "Die Datenbank ist gerade durch einen anderen Vorgang belegt.\n"
            "Bitte warte einen Moment und versuche es erneut."
        )

    # Clean technical prefixes if unclassified
    clean = re.sub(r'^(exceptions?\.)?[A-Za-z0-9_]+Error:\s*', '', err_str)
    clean = re.sub(r'^<[^>]+>:\s*', '', clean)
    clean = clean.strip()
    if clean:
        if context:
            return f"{context}:\n{clean}"
        return clean

    return "Ein unerwarteter technischer Fehler ist aufgetreten."
