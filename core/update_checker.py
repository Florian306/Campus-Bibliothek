"""GitHub Release & Auto-Updater Checker for Campus-Bibliothek.
Polls GitHub Releases API for Florian306/Campus-Bibliothek to detect new versions.
"""

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from core.error_handler import humanize_error

GITHUB_REPO = "Florian306/Campus-Bibliothek"
CURRENT_VERSION = "2.5.1"

FALLBACK_CHANGELOG: List[Dict[str, str]] = [
    {
        "version": "2.5.1",
        "date": "Aktuell",
        "title": "Intelligente Posteingangs-Erkennung & OCR-tolerante Metadaten",
        "notes": "• Smarter Dateinamen-Parser: Automatische Zerlegung von akademischen Dateinamen in Autor, Buchtitel, Auflage und Erscheinungsjahr\n• Tiefer Impressum-Scan: Erweitert die Titelei-Suche auf bis zu 16 Seiten zur zuverlässigen Erkennung von Springer-, Hanser- und DNB-Impressumsdaten\n• OCR-tolerante ISBN-Erkennung: Erkennt ISBNs auch bei Scans mit typischen Scan-Fehlern (z. B. 'O' statt '0') und fehlenden Bindestrichen\n• Multi-Stufen-Fallback: Nie wieder leere Autoren- oder Titelangaben im Posteingang",
    },
    {
        "version": "2.5.0",
        "date": "Aktuell",
        "title": "All-in-One Search Capsule, FTS Buch-Akkordeon & Live-Seitenvorschau",
        "notes": "• All-in-One Search Capsule: Integriertes Spotlight-Kapseldesign mit sanfter Glow-Border und interaktivem Live-Trefferzähler\n• Buch-Akkordeon für Volltext-Treffer: Ergebnisse werden übersichtlich nach Büchern gruppiert und lassen sich auf- und zuklappen\n• Live-Seitenvorschau (Split-View): Direkte hochauflösende Dokumentenvorschau im rechten Inspector ohne Reader-Öffnung\n• Floating Reader-HUD: Sanft ausblendende Seitenanzeige beim Scrollen im fortlaufenden Lesemodus",
    },
    {
        "version": "2.4.1",
        "date": "Aktuell",
        "title": "Sofortige Startup-Update-Erkennung & Persistenter Nav-Badge",
        "notes": "• Thread-sichere Startup-Erkennung: Neue Versionen werden sofort beim Start signalisiert – unabhängig davon, in welchem Tab sich der Benutzer befindet\n• Persistenter Nav-Badge: Das Leucht-Badge am Scan & Sync Button bleibt auch beim Tab-Wechsel dauerhaft erhalten\n• 1-Klick-Toast-Aktivierung: Der Floating Toast erscheint unmittelbar nach Boot und führt direkt zum Update-Dialog",
    },
    {
        "version": "2.4.0",
        "date": "Aktuell",
        "title": "Fix: Exakter Seiten-Erhalt beim Scrollmodus-Wechsel",
        "notes": "• Perfekter Scroll-Übergang: Behebt den QtPdf-Eigenheitseffekt beim Umschalten von Einzelseite auf fortlaufendes Scrollen, sodass der Reader nie mehr an den Buchanfang springt\n• Unmittelbare Ziel-Ausrichtung: Sofortige Scrollbar- und Navigator-Justierung auf die genaue Leseposition",
    },
    {
        "version": "2.3.9",
        "date": "Aktuell",
        "title": "Optimierte Volltext-Navigation & Seiten-Erhalt im PDF-Reader",
        "notes": "• Intelligenter Seiten-Erhalt: Beim Umschalten zwischen Einzelseite und fortlaufender Ansicht bleibt die aktuelle Leseseite exakt erhalten\n• Nahtloser Suchmodus-Wechsel: Umschalten von Volltext auf Titel wechselt sofort und zuverlässig zurück zur Regal-/Tabellenansicht\n• Premium Such-Snippets: Eleganter Glashighlight-Look für Trefferwörter ohne störende Farbblöcke",
    },
    {
        "version": "2.3.8",
        "date": "Aktuell",
        "title": "Ultra-flüssige Volltextsuche & ruckelfreie Hintergrund-Indizierung",
        "notes": "• Ruckelfreie Hintergrund-Indizierung: Worker auf niedrigste Betriebssystem-Priorität gedrosselt mit 50-Seiten-Batching und CPU-Yields\n• Butterweiches Tippen: 220ms Smart-Debouncing verhindert UI-Lags bei schneller Tastatureingabe\n• Edles Kachel-Design: Original-Buchcover, harmonische Typografie und sauber ausgerichtete Aktions-Buttons\n• Absturzsicheres Öffnen: Modalloser Reader-Start mit automatischer Pfad-Heilung und Direktsprung zur Fundstelle",
    },
    {
        "version": "2.3.7",
        "date": "02.11.2026",
        "title": "High-Performance Volltext-Suche (SQLite FTS5) & Direktsprung",
        "notes": "• Blitzschnelle Volltext-Suche: Durchsucht alle archivierten Buchseiten in unter 10ms mit BM25-Relevanzranking\n• 1-Klick-Umschaltung im Katalog: Nahtlos zwischen Titelsuche und Volltext-Inhaltssuche wechseln\n• Direktsprung & Snippets: Text-Auszüge mit Suchbegriff-Hervorhebung und 1-Klick-Öffnen direkt auf der Fundstellen-Seite\n• Inkrementeller Hintergrund-Index: Asynchrones Einlesen im Scan & Sync Center mit Live-Fortschrittsanzeige",
    },
    {
        "version": "2.3.6",
        "date": "02.11.2026",
        "title": "Menschliche KI-Sprachausgabe (Neural Voice) für JARVIS Briefings",
        "notes": "• Ultra-realistische Sprachausgabe: Natürliche, menschliche KI-Stimme (Microsoft Florian Neural Voice) mit deutscher Satzmelodie und Betonung\n• Zuverlässiger Offline-Fallback: Automatische Umschaltung auf lokale Windows-Stimmen bei fehlender Internetverbindung\n• Fehlerbehebung TTS: Beseitigt Parsing- und Variablenfehler in der PowerShell-Sprachsynthese",
    },
    {
        "version": "2.3.5",
        "date": "01.11.2026",
        "title": "Cyber-Obsidian Design-Perfektionierung für Statistik & Analyse",
        "notes": "• Design-Upgrade Cockpit: Dezente Icon-Badges mit sanftem Glow und harmonische Typografie auf allen 4 KPI-Karten\n• Bereinigte Fakultäts-Kacheln: Saubere Farb-Indikatoren ohne störende Klammern oder Textversatz\n• Neues Histogramm für Publikationsjahre: Gradient-Füllbalken mit abgerundeten Ecken und Ø-Jahrgangsanzeige\n• Vektor-Icons & Lesbarkeit: Gestochen scharfe Vektor-Icons in den Bibliotheks-Highlights & Rekorden",
    },
    {
        "version": "2.3.4",
        "date": "01.11.2026",
        "title": "Neuer Statistik & Analyse Tab, Instant-Update-Erkennung & Pre-Warming",
        "notes": "• Neuer Statistik & Analyse Tab: Interaktives Cyber-Obsidian Dashboard mit Bestands-KPIs, Fakultäten-Verteilung, Publikations-Histogramm und Bibliotheks-Rekorden\n• Sofortige Update-Erkennung: Schnelle Hintergrund-Prüfung direkt beim App-Start mit leuchtendem Nav-Badge und 1-Klick-Update-Toast\n• Zero-Hitch Pre-Warming: Kein Ruckeln mehr beim ersten Öffnen von Katalog und Posteingang dank asynchronem Hintergrund-Cachen\n• Optimierte SQLite-Indizes: Blitzschnelle Duplikat- und Metadatenprüfungen in der Datenbank",
    },
    {
        "version": "2.3.3",
        "date": "01.11.2026",
        "title": "Smarte Skript-Erkennung im Posteingang & Performance-Boost für das Bücherregal",
        "notes": "• Smarte Skript-Erkennung: Erkennt Studienbriefe, Kurseinheiten und Vorlesungsskripte schon beim Hinzufügen\n• 1-Klick-Pill-Schalter in der Inbox: Nahtloses Wechseln zwischen 'Fachbuch' und 'Studienbrief / Skript'\n• Sofortiges Bücherregal-Rendering: Kein zögerliches Nach-unten-Wegkleckern der Kacheln mehr\n• Korrigierte 'Zuletzt hinzugefügt'-Sortierung: Sortiert primär nach echtem Aufnahmezeitpunkt in die Bibliothek\n• Bereinigung: Veraltete Legacy-Dateien und ungenutzte Module vollständig entfernt",
    },
    {
        "version": "2.3.2",
        "date": "01.11.2026",
        "title": "Cyber-Obsidian Design-Upgrade & Perfektionierte Tabellen-Typografie",
        "notes": "• Optimierte Spalten-Breiten & Padding: Keine abgeschnittenen Kategorien mehr (z. B. Wirtschaftswissenschaften)\n• Perfekt ausgerichtete Dropdown-Pfeile & zentrierte Status-Badges\n• Pixel-genau zentrierte Checkboxen in Kopfzeile und Datenzeilen\n• Ruhiges, klares Tabellenbild ohne Textversatz",
    },
    {
        "version": "2.3.1",
        "date": "01.11.2026",
        "title": "Posteingang Stabilitäts-Fix & Duplikatschutz beim Hinzufügen",
        "notes": "• Behoben: NameError 'threading' in refresh_inbox_view gefixt – kein Absturz mehr beim Wechsel in den Posteingang\n• Intelligenter Duplikatschutz: Verhindert Mehrfachkopien gleicher Dateien im Posteingang\n• Ghost-Queue Bereinigung: Nicht mehr existierende Dateien werden automatisch aufgeräumt",
    },
    {
        "version": "2.3.0",
        "date": "01.11.2026",
        "title": "Herausgeber-Erkennung beim Zusammenführen & Perfektioniertes Tabellen-Layout",
        "notes": "• Intelligente Autoren- und Herausgebererkennung ((Hrsg.) / Editoren / DNB) beim Verschmelzen von Buchkapiteln\n• Exakte vertikale und horizontale Ausrichtung aller Spalten in der Posteingangs-Tabelle (Checkboxen, Status-Pills, Aktionen)\n• Dynamische Spaltenbreiten verhindern Textabschneidungen oder ungewollte Versätze",
    },
    {
        "version": "2.2.9",
        "date": "01.11.2026",
        "title": "TOC-Deep-Scan, Smarte Kapitelsortierung & Stabilitäts-Upgrade",
        "notes": "• Automatischer Deep-Scan des Inhaltsverzeichnisses (TOC) zur Bestimmung der perfekten Buch-Reihenfolge\n• Analyse gedruckter Buch-Seitenzahlen auf den ersten Seiten aller Kapitel als treffsichere Sortierbasis\n• Deckblatt, Frontmatter, Inhaltsverzeichnis, Vorwort und Hauptteile ordnen sich vollautomatisch akkurat an\n• Zuverlässiges Öffnen des PDF-Merge-Studios mit gezielt ausgewählten Inbox-Dateien\n• Robuste SQLite-Sperrbehandlung (Busy Timeout & Graceful Schema Init)",
    },
    {
        "version": "2.2.8",
        "date": "01.11.2026",
        "title": "TOC-Deep-Scan & Automatische Inhaltsverzeichnis-Sortierung",
        "notes": "• Automatischer Deep-Scan des Inhaltsverzeichnisses (TOC) zur Bestimmung der perfekten Buch-Reihenfolge\n• Analyse gedruckter Buch-Seitenzahlen auf den ersten Seiten aller Kapitel als treffsichere Sortierbasis\n• Deckblatt, Frontmatter, Inhaltsverzeichnis, Vorwort und Hauptteile ordnen sich vollautomatisch akkurat an",
    },
    {
        "version": "2.2.7",
        "date": "01.11.2026",
        "title": "Gezieltes Zusammenführen & Intelligente Buch-Kapitelsortierung",
        "notes": "• PDF-Merge-Studio lädt bei Auswahl präzise nur die angehakten Kapitel/Dateien aus dem Posteingang statt des gesamten Ordners\n• Smarte Frontmatter-Erkennung: Deckblatt/BEGINN, Inhalt/TOC und Vorwort sortieren sich automatisch an den Anfang vor Teil I..VI\n• Dynamische Button-Beschriftung im Posteingang passend zur Anzahl ausgewählter Kapitel",
    },
    {
        "version": "2.2.6",
        "date": "01.11.2026",
        "title": "Turbo-Katalog & Zero-Freeze Großbuch-Architektur",
        "notes": "• Sofortiges, ruckelfreies Umschalten in den Katalog ohne Layout-Zucken der Kacheln\n• Zuverlässiges Öffnen riesiger Fachbücher (> 1200 Seiten / fast 1 GB) im SinglePage-Modus ohne Einfrieren oder Absturz",
    },
    {
        "version": "2.1.5",
        "date": "31.10.2026",
        "title": "Verfeinerte Multi-Kategorien-Zuordnung & Interdisziplinäre Fächer",
        "notes": "• Vollständige Multi-Kategorie-Erkennung für interdisziplinäre Bücher (DNB-Katalog, OpenLibrary & Inhaltsverzeichnis-Heuristik)\n• Editierbare Mehrfach-Auswahl in der Posteingangs-Tabelle mit automatischer Primärfach-Gewichtung\n• Saubere Übernahme aller zugewiesenen Fachbereiche in den Bibliothekskatalog",
    },
    {
        "version": "2.1.4",
        "date": "31.10.2026",
        "title": "Posteingang KI-Analyse Patch",
        "notes": "• Behoben: NameError bei der Duplikatsprüfung im Hintergrund-Analyse-Thread des Posteingangs gefixt\n• Schnelle automatische Extraktion von Metadaten, Autoren und Kategorien für neue PDFs in der Warteschlange",
    },
    {
        "version": "2.1.3",
        "date": "30.10.2026",
        "title": "Click-To-Edit Eingabefelder im Posteingang & Ruhiger Mauszeiger",
        "notes": "• Neue ClickToEditLineEdit-Komponente für Autor und Titel: Kein Schreibcursor oder Aktivierung beim reinen Maus-Hover\n• Cursor wechselt erst bei explizitem Linksklick in den Schreibmodus\n• Automatisches Zurücksetzen in den gesicherten Ruhemodus bei Fokusverlust",
    },
    {
        "version": "2.1.2",
        "date": "30.10.2026",
        "title": "Präzisions-Texthighlight im PDF-Reader, Instant-Inbox & Greifbare Lernzeit",
        "notes": "• Perfekt linientreues Texthighlight im PDF-Reader mit dynamischer Wortabstandsbrücke für Blocksatz, Inhaltsverzeichnisse & Glossare\n• Sofortiges Öffnen des Posteingangs ohne Verzögerung (Hintergrund-Dateisystemabgleich)\n• Klick-Fokus für Autoren- & Titelzeilen in der Warteschlange (kein versehentlicher Schreibmodus bei Maus-Hover)\n• Greifbare Lernzeit-Telemetrie mit exakter Seitenzahl und realistischen Lesezielen (50 S./Tag)",
    },
    {
        "version": "2.1.1",
        "date": "30.10.2026",
        "title": "Vollwertige Fach-Websuche, Live-Suchvorschläge & Inbox Stabilität",
        "notes": "• Entfesselte Fach-Websuche ohne künstliche Ausschlussfilter; Presets steuern intelligentes Relevanz-Scoring\n• Live-Autocomplete & Suchvorschläge in Echtzeit direkt bei der Eingabe\n• Behoben: Klickbarkeit und Initialisierung der Posteingangs-Ansicht wiederhergestellt",
    },
    {
        "version": "2.1.0",
        "date": "30.10.2026",
        "title": "Quick-Look Staging Preview, Shift-Multi-Select & Live Feedback",
        "notes": "• Sofortige Buch- und Reader-Vorschau per Doppelklick / Cover-Klick direkt in der Warteschlange\n• Flüssige Mehrfachauswahl via Shift-Klick für schnelle Stapelverarbeitung\n• Native interaktive Checkboxen & Non-blocking Toast-Benachrichtigung beim Einsortieren",
    },
    {
        "version": "2.0.9",
        "date": "30.10.2026",
        "title": "Multi-Faktor Duplikaterkennung, SQLite-Persistenz & Warteschlangen-UI",
        "notes": "• Intelligente Duplikaterkennung nach ISBN, Autor, Titel und Datei (keine Falschmeldungen bei gleichen Titeln verschiedener Autoren)\n• Dauerhafte Speicherung des Duplikat-Status in SQLite\n• Direkte Inline-Titelbearbeitung, ISBN-Badges & verfeinertes Cyber-Obsidian-Design",
    },
    {
        "version": "2.0.8",
        "date": "30.10.2026",
        "title": "Akademische Lernzeit-Telemetrie & Layout-Feinschliff",
        "notes": "• Neue Live-Metrik: Echtzeit-Berechnung des Studien- und Lesevolumens (~2 Min/Seite) über alle Fachbereiche\n• Intelligente Null-Seiten-Korrektur bei importierten Dokumenten\n• Optimierte Dashboard-Synchronisation",
    },
    {
        "version": "2.0.7",
        "date": "30.10.2026",
        "title": "OCR Dot-Leader Bereinigung & Scan-Inhaltsverzeichnis Patch",
        "notes": "• Eliminierung von OCR-Punktreihen-Artefakten (z.B. Cambridge IELTS)\n• Exakte Trennung von Unit-Nummern und Seitenzahlen bei Buch-Scans",
    },
    {
        "version": "2.0.6",
        "date": "30.10.2026",
        "title": "Inno Setup BMP Fix & Cache-Bereinigung",
        "notes": "• Behebt 'Bitmap image is not valid' durch saubere 24-Bit BMP Konvertierung\n• Bereinigung von veralteten Logs und ungenutzten Systemdateien",
    },
    {
        "version": "2.0.5",
        "date": "30.10.2026",
        "title": "Generischer TOC-Extractor & Codebase-Entschlackung",
        "notes": "• Vollständige Entfernung hardcodierter Buch-Tabellen (-276 Zeilen)\n• 100% dynamische Erkennung via Projektions-Histogramm und OCR-Filter",
    },
    {
        "version": "2.0.0",
        "date": "29.10.2026",
        "title": "Turbo CI Build-Pipeline & Instant TOC & Mega-PDF Performance",
        "notes": "• Bis zu 70% schnellere GitHub Actions Builds durch Elimination von 2.700 ungenutzten QML-Dateien\n• Behebt TOC-Parser regex import für alle Scan- und OCR-Inhaltsverzeichnisse\n• Fast-Start für gigantische PDFs (800+ MB öffnen jetzt in Millisekunden)",
    },
    {
        "version": "1.9.9",
        "date": "29.10.2026",
        "title": "TOC Parser Hotfix & Stream-Start Optimierung",
        "notes": "• Re-Import für Inhaltsverzeichnis-Parser nachgerüstet\n• Sofortige Ladebereitschaft bei großen Dokumenten",
    },
    {
        "version": "1.9.8",
        "date": "29.10.2026",
        "title": "High-Speed TOC, Crash-Schutz & Hintergrund-Update-Polling",
        "notes": "• Crash-Schutz: Sicheres Schließen des Readers auch während des Ladevorgangs\n• Bis zu 250x schnelleres Öffnen von Büchern ohne digitales Inhaltsverzeichnis (0.05s)\n• Automatisches Update-Polling alle 30 Minuten mit Live-Benachrichtigungsbanner\n• 2-Stufen Release Pipeline für blitzschnelle Patch-Bereitstellung",
    },
    {
        "version": "1.9.7",
        "date": "29.10.2026",
        "title": "Universal-Inhaltsverzeichnis: OCR-Erkennung für Buch-Scans & Layout-Engine",
        "notes": "• Automatischer Tesseract-OCR Fallback für rein bildbasierte Buchscans\n• Filter für Dummy-/Dateinamen-Bookmarks (z. B. '148.jpg', '0.pdf')\n• Erweiterte Layout-Engine für O'Reilly-, Suhrkamp- & Back-Matter-Verzeichnisse",
    },
    {
        "version": "1.9.6",
        "date": "29.10.2026",
        "title": "Scan & Sync Command-Dashboard & Live-Update-Zentrale",
        "notes": "• 4 Live-System-Metriken (Bücher, Seiten, Notizen, Windows-Tresor)\n• Integriertes Release- & Update-Center mit direkter 1-Klick-Installation und Versionshistorie\n• Farbige Echtzeit-Statuskonsole mit Schnellfilter-Optionen",
    },
    {
        "version": "1.9.5",
        "date": "29.10.2026",
        "title": "Windows DPAPI Tresor-Verschlüsselung & Geheimnisschutz",
        "notes": "• Sensible Zugangsdaten (Gmail App-Passwort, Kalender-URL, Tokens) hardwaregebunden via Windows DPAPI verschlüsselt\n• Write-Only Maskierung im JARVIS-Setup schützt vor Auslesen & Screenshots",
    },
    {
        "version": "1.9.4",
        "date": "28.10.2026",
        "title": "Asynchroner PDF-Stream-Loader & Metadaten-Heilung",
        "notes": "• Nicht-blockierender PDF-Reader mit Abbruch-Button und 25-Hz Progress-Throttling\n• Automatische ISBN-, Jahres- und Auflagen-Erkennung für Posteingangs-Bücher",
    },
    {
        "version": "1.9.3",
        "date": "28.10.2026",
        "title": "Cyber-Obsidian PDF-Ladebildschirm & Quick-Select",
        "notes": "• Dunkler Ladebildschirm mit Fortschrittsbalken für große Cloud-PDFs\n• Flüssige Mehrfachauswahl im Katalog & breitere Band-Badges",
    },
]


def check_for_updates() -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """Checks if a newer release is available on GitHub.
    Returns: (update_available, latest_version, download_url, release_notes)
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Campus-Bibliothek-Updater",
        },
    )

    try:
        ssl_ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag_name = data.get("tag_name", "").lstrip("v").strip()
            if not tag_name:
                return False, None, None, None

            # Compare semantic versions
            if _is_version_greater(tag_name, CURRENT_VERSION):
                download_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")
                assets = data.get("assets", [])

                # 1. Bevorzuge schnelles Delta-Patch (<20 MB) statt vollständigem Installer (>300 MB)
                patch_url = None
                setup_url = None
                fallback_url = None

                for asset in assets:
                    name = asset.get("name", "").lower()
                    url_candidate = asset.get("browser_download_url")
                    if "patch" in name and name.endswith(".zip"):
                        patch_url = url_candidate
                    elif "setup" in name and name.endswith(".exe"):
                        setup_url = url_candidate
                    elif name.endswith(".exe") or name.endswith(".zip"):
                        fallback_url = url_candidate

                # Priorisiere Patch: lädt nur die geänderten Dateien (~18 MB) statt 330 MB
                download_url = patch_url or setup_url or fallback_url or download_url
                notes = data.get("body", "Keine Versionshinweise vorhanden.")
                return True, tag_name, download_url, notes
            return False, tag_name, None, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Repository or release not published yet
            return False, None, None, None
        friendly = humanize_error(e, "GitHub-Verbindung fehlgeschlagen")
        return False, None, None, friendly
    except Exception as e:
        friendly = humanize_error(e, "Update-Prüfung fehlgeschlagen")
        return False, None, None, friendly


def fetch_recent_releases(limit: int = 4) -> List[Dict[str, str]]:
    """Fetches recent GitHub releases for the What's New / Update feed, falling back to local changelog."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page={limit}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Campus-Bibliothek-Updater",
        },
    )
    try:
        ssl_ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=6, context=ssl_ctx) as resp:
            items = json.loads(resp.read().decode("utf-8"))
            if isinstance(items, list) and items:
                out: List[Dict[str, str]] = []
                seen_versions = set()
                for fb in FALLBACK_CHANGELOG:
                    top_tag = str(items[0].get("tag_name", "")).lstrip("v").strip()
                    if _is_version_greater(fb["version"], top_tag):
                        out.append(fb)
                        seen_versions.add(fb["version"])

                for rel in items[:limit]:
                    tag = str(rel.get("tag_name", "")).lstrip("v").strip()
                    if tag in seen_versions:
                        continue
                    seen_versions.add(tag)
                    name = str(rel.get("name") or f"Version {tag}").strip()
                    pub = str(rel.get("published_at") or "")[:10]
                    body = str(rel.get("body") or "").strip()
                    if not body:
                        body = "Stabilitäts- und Performance-Verbesserungen."
                    out.append({
                        "version": tag,
                        "date": pub or "Release",
                        "title": name,
                        "notes": body[:280] + ("..." if len(body) > 280 else ""),
                    })
                return out[:limit]
    except Exception:
        pass
    return FALLBACK_CHANGELOG[:limit]


def _is_version_greater(remote: str, current: str) -> bool:
    """Compares two semver version strings."""
    try:
        def parse_parts(v: str):
            return [int(x) for x in v.split(".") if x.isdigit()]
        r_parts = parse_parts(remote)
        c_parts = parse_parts(current)
        return r_parts > c_parts
    except Exception:
        return remote != current
