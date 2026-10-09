"""Daily Web Impulse & Curated Discovery Engine for Academic Web Search.
Fetches high-value, diverse academic web articles, university lecture scripts,
authoritative definitions, political analyses, and economic deep-dives across all faculties:
- 📖 Fachlexika & Definitionen (Psychologie, Philosophie, Rechtsbegriffe, Soziologie)
- 🏛️ Politik & Zeitgeschehen (Bundeszentrale für politische Bildung / bpb, Völkerrecht, Demokratietheorie)
- 📈 Wirtschaft, Finanzen & VWL (Makroökonomie, Geldpolitik, Gabler Wirtschaftslexikon, Spieltheorie)
- 🎓 Hochschul-Skripte & Vorlesungen (RWTH, TUM, MIT, Uni Heidelberg, Stanford)
- 💻 Tech, KI & Future MINT (Quantum, Neural Networks, Python Internals, Systems Design)
- 🧬 Medizin, Neurowissenschaften & Naturwissenschaften (Spektrum, Max-Planck, Nature Reviews)

Includes:
- Persistent daily cache with 1-click '🎲 Neuer Impuls / Überrasch mich'
- 'Buch-Brücke': Cross-matching of the web article against the user's local PDF library.
"""

import os
import re
import json
import time
import random
import datetime
import urllib.request
import urllib.parse
import ssl
from typing import Any, Dict, List, Optional

from core.config import get_books_storage_dir
from core.library_db import get_all_books

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

USER_AGENT = "Buchsortierer/2.0 (Academic Library Discovery; Windows NT 10.0; Win64; x64)"

CURATED_DISCOVERY_POOL: List[Dict[str, Any]] = [
    # --- 1. RECHT, VERFASSUNG & DEMOKRATIE ---
    {
        "title": "Grundgesetz für die Bundesrepublik Deutschland",
        "url": "https://www.bpb.de/themen/politisches-system/deutsche-demokratie/39291/grundgesetz/",
        "domain": "bpb.de",
        "category": "⚖️ Verfassungsrecht & Staatstheorie",
        "badge": "🏛️ bpb Dossier",
        "badge_color": "#1F6FEB",
        "teaser": "Rechtssicherheit, Verhältnismäßigkeitsgrundsatz und Bindung aller staatlichen Gewalt an Gesetz und Recht (Art. 20 Abs. 3 GG) im institutionellen Gefüge.",
        "search_seed": "bpb Rechtsstaatsprinzip Grundgesetz Gewaltenteilung",
        "faculty": "Jura & Politik",
    },
    {
        "title": "Dossier Rechtsextremismus & Wehrhafte Demokratie",
        "url": "https://www.bpb.de/themen/rechtsextremismus/dossier-rechtsextremismus/",
        "domain": "bpb.de",
        "category": "🏛️ Politikwissenschaft & Soziologie",
        "badge": "🏛️ bpb Dossier",
        "badge_color": "#1F6FEB",
        "teaser": "Wissenschaftliche Analysen zu demokratiegefährdenden Tendenzen, Radikalisierungsmechanismen und Instrumenten der wehrhaften Demokratie.",
        "search_seed": "bpb Rechtsextremismus Wehrhafte Demokratie Verfassungsschutz",
        "faculty": "Politik & Gesellschaft",
    },
    {
        "title": "Charta der Vereinten Nationen & Völkerrecht",
        "url": "https://de.wikipedia.org/wiki/Charta_der_Vereinten_Nationen",
        "domain": "de.wikipedia.org",
        "category": "⚖️ Internationales Recht & Völkerrecht",
        "badge": "📖 Völkerrecht",
        "badge_color": "#1F6FEB",
        "teaser": "Das völkerrechtliche Fundament der Nachkriegsordnung: Allgemeines Gewaltverbot, kollektives Sicherheitssystem und Resolutionen des Sicherheitsrates.",
        "search_seed": "UN Charta Voelkerrecht Sicherheitsrat",
        "faculty": "Jura & Politik",
    },

    # --- 2. WIRTSCHAFT & FINANZEN (BUNDESBANK, DESTATIS, IFO) ---
    {
        "title": "Deutsche Bundesbank: Grundlagen der Geldpolitik im Eurosystem",
        "url": "https://www.bundesbank.de/de/aufgaben/geldpolitik",
        "domain": "bundesbank.de",
        "category": "📈 Volkswirtschaftslehre & Makroökonomie",
        "badge": "🏦 Bundesbank Lehre",
        "badge_color": "#238636",
        "teaser": "Zinspolitische Steuerungsmechanismen des Eurosystems, Mindestreserven, Offenmarktgeschäfte und Transmissionskanäle der Geldpolitik.",
        "search_seed": "Deutsche Bundesbank Geldpolitik Zinsen Eurosystem",
        "faculty": "Wirtschaftswissenschaften",
    },
    {
        "title": "Statistisches Bundesamt: Verbraucherpreisindex & Inflationsmessung",
        "url": "https://www.destatis.de/DE/Themen/Wirtschaft/Preise/Verbraucherpreisindex/_inhalt.html",
        "domain": "destatis.de",
        "category": "📈 Empirische Wirtschaftsforschung & Statistik",
        "badge": "📊 Destatis Fachportal",
        "badge_color": "#238636",
        "teaser": "Methodik des Warenkorbs, Laspeyres-Preisindex und Preisbereinigung als Fundament makroökonomischer Stabilitätsanalysen in Deutschland.",
        "search_seed": "Destatis Verbraucherpreisindex Inflation Warenkorb",
        "faculty": "Wirtschaftswissenschaften",
    },
    {
        "title": "Statistisches Bundesamt: Volkswirtschaftliche Gesamtrechnungen (BIP)",
        "url": "https://www.destatis.de/DE/Themen/Wirtschaft/Volkswirtschaftliche-Gesamtrechnungen-Inlandsprodukt/_inhalt.html",
        "domain": "destatis.de",
        "category": "📈 Makroökonomie & Gesamtrechnung",
        "badge": "📊 Destatis Fachportal",
        "badge_color": "#238636",
        "teaser": "Entstehungs-, Verwendungs- und Verteilungsrechnung des Bruttoinlandsprodukts: Empirische Erfassung des Wirtschafts- und Wohlstandswachstums.",
        "search_seed": "Destatis Bruttoinlandsprodukt VGR Entstehungsrechnung",
        "faculty": "Wirtschaftswissenschaften",
    },
    {
        "title": "WZB Wissenschaftszentrum Berlin: Gesellschaftlicher Wandel & Arbeitsmarkt",
        "url": "https://www.wzb.eu/de/forschung",
        "domain": "wzb.eu",
        "category": "🏛️ Soziologie & Sozialökonomie",
        "badge": "🔬 WZB Forschung",
        "badge_color": "#8E44AD",
        "teaser": "Spitzenforschung zu sozialer Ungleichheit, Bildungsrenditen und Transformationen der Arbeitswelt im europäischen Vergleich.",
        "search_seed": "WZB Sozialforschung Ungleichheit Arbeitsmarkt",
        "faculty": "Soziologie & Wirtschaft",
    },

    # --- 3. MATHEMATIK & INFORMATIK (HOCHSCHUL-LEHRBÜCHER) ---
    {
        "title": "Mathematik: Diskrete Mathematik",
        "url": "https://de.wikibooks.org/wiki/Mathematik:_Diskrete_Mathematik",
        "domain": "de.wikibooks.org",
        "category": "📐 Diskrete Mathematik & Informatik",
        "badge": "🎓 Hochschul-Lehrbuch",
        "badge_color": "#00549F",
        "teaser": "Aussagenlogik, Mengenlehre, Kombinatorik, Graphentheorie und algorithmische Komplexität als fundamentales Fundament der Informatik.",
        "search_seed": "Diskrete Mathematik Kombinatorik Graphen Logik",
        "faculty": "Mathematik & Informatik",
    },
    {
        "title": "Mathematik: Lineare Algebra",
        "url": "https://de.wikibooks.org/wiki/Mathematik:_Lineare_Algebra",
        "domain": "de.wikibooks.org",
        "category": "📐 Höhere Mathematik & Lineare Algebra",
        "badge": "🎓 Hochschul-Lehrbuch",
        "badge_color": "#00549F",
        "teaser": "Vektorräume, lineare Abbildungen, Matrizenkalkül, Eigenwertprobleme und Hauptachsentransformationen als Werkzeuge moderner Naturwissenschaften.",
        "search_seed": "Lineare Algebra Vektorraeume Matrizen Eigenwerte",
        "faculty": "Mathematik & Informatik",
    },
    {
        "title": "Künstliches neuronales Netz & Deep Learning",
        "url": "https://de.wikipedia.org/wiki/K%C3%BCnstliches_neuronales_Netz",
        "domain": "de.wikipedia.org",
        "category": "💻 Informatik & Deep Learning",
        "badge": "🤖 KI & Machine Learning",
        "badge_color": "#00549F",
        "teaser": "Mathematische Modellierung biologischer Neuronennetze: Perzeptrone, Backpropagation-Algorithmus, Loss-Funktionen und tiefe Architekturen.",
        "search_seed": "Kuenstliches neuronales Netz Backpropagation Deep Learning Machine Learning",
        "faculty": "Informatik",
    },

    # --- 4. NATURWISSENSCHAFTEN & PHYSIK ---
    {
        "title": "Einführung in die Theoretische Physik",
        "url": "https://de.wikibooks.org/wiki/Einf%C3%BChrung_in_die_Theoretische_Physik",
        "domain": "de.wikibooks.org",
        "category": "⚛️ Theoretische Physik & Mechanik",
        "badge": "🎓 Hochschul-Lehrbuch",
        "badge_color": "#00549F",
        "teaser": "Klassische Mechanik, Lagrange- und Hamilton-Formalismus, Variationsrechnung und Symmetrien für das universitäre Physikstudium.",
        "search_seed": "Theoretische Physik Mechanik Lagrange Hamilton",
        "faculty": "Physik",
    },
    {
        "title": "Dossier Klimawandel: Physikalische Grundlagen & Modelle",
        "url": "https://www.bpb.de/themen/umwelt/klimawandel/",
        "domain": "bpb.de",
        "category": "🌍 Geowissenschaften & Umweltforschung",
        "badge": "🏛️ bpb Dossier",
        "badge_color": "#006C66",
        "teaser": "Atmosphärenphysik, anthropogener Treibhauseffekt, Kippelemente im Erdsystem und sozioökonomische Transformationspfade.",
        "search_seed": "bpb Klimawandel Treibhauseffekt Klimamodelle Physik",
        "faculty": "Physik & Geowissenschaften",
    },
    {
        "title": "CRISPR/Cas-Methode & Genom-Editierung",
        "url": "https://de.wikipedia.org/wiki/CRISPR/Cas-Methode",
        "domain": "de.wikipedia.org",
        "category": "🧬 Molekularbiologie & Genetik",
        "badge": "🔬 Molekularbiologie",
        "badge_color": "#D35400",
        "teaser": "Präzises Genome Editing mittels RNA-geführter Nukleasen: Wie die molekulare Genschere funktioniert und biotechnologische Anwendungen eröffnet.",
        "search_seed": "CRISPR Cas9 Genetik Molekularbiologie Genom",
        "faculty": "Biologie & Medizin",
    },

    # --- 5. PSYCHOLOGIE & KOGNITIONSWISSENSCHAFT ---
    {
        "title": "Kognitive Dissonanz",
        "url": "https://de.wikipedia.org/wiki/Kognitive_Dissonanz",
        "domain": "de.wikipedia.org",
        "category": "🧠 Psychologie & Kognitionsforschung",
        "badge": "🔬 Sozialpsychologie",
        "badge_color": "#D35400",
        "teaser": "Leon Festingers Theorie des unangenehmen Gefühlszustands bei unvereinbaren Kognitionen und wie Menschen Rationalisierungen aufbauen.",
        "search_seed": "Kognitive Dissonanz Festinger Psychologie Kognition",
        "faculty": "Psychologie",
    },
    {
        "title": "Attributionstheorien & Kausale Urteilsbildung",
        "url": "https://de.wikipedia.org/wiki/Attributionstheorien",
        "domain": "de.wikipedia.org",
        "category": "🧠 Sozialpsychologie & Kognition",
        "badge": "🔬 Kognitionspsychologie",
        "badge_color": "#D35400",
        "teaser": "Wie Menschen Ursachen für beobachtetes Verhalten zuschreiben: Internale vs. externale Kausalattribution und der fundamentale Attributionsfehler.",
        "search_seed": "Attributionstheorien Heider Kelley Psychologie Kausalitaet",
        "faculty": "Psychologie",
    }
]


def _get_cache_file() -> str:
    base = get_books_storage_dir()
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "daily_web_impulse.json")


def _read_cache() -> Dict[str, Any]:
    f_path = _get_cache_file()
    if os.path.exists(f_path):
        try:
            with open(f_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _write_cache(data: Dict[str, Any]) -> None:
    f_path = _get_cache_file()
    try:
        with open(f_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_daily_web_impulse(force_refresh: bool = False, preset: str = "all") -> Dict[str, Any]:
    """Retrieves the curated Web Impulse for the day, or rolls a new one on demand.
    Matches the article with the user's local indexed library books.
    """
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    cache = _read_cache()

    cache_key = f"impulse_{preset}"
    cached_entry = cache.get(cache_key)

    selected_item = None
    if not force_refresh and cached_entry and cached_entry.get("date") == today_str:
        selected_item = cached_entry.get("item")

    if not selected_item:
        # Filter pool by preset if requested
        candidates = list(CURATED_DISCOVERY_POOL)
        if preset == "uni":
            candidates = [c for c in candidates if "🎓" in c.get("badge", "") or "uni" in c.get("domain", "") or "edu" in c.get("domain", "") or "mpg" in c.get("domain", "")]
        elif preset == "lexikon":
            candidates = [c for c in candidates if "📖" in c.get("badge", "") or "gabler" in c.get("domain", "") or "spektrum" in c.get("domain", "") or "bpb" in c.get("domain", "")]
        elif preset == "tech":
            candidates = [c for c in candidates if "💻" in c.get("badge", "") or "Informatik" in c.get("category", "") or "docs" in c.get("domain", "") or "ibm" in c.get("domain", "")]

        if not candidates:
            candidates = CURATED_DISCOVERY_POOL

        # Use date as deterministic daily seed unless force_refresh
        if force_refresh:
            selected_item = random.choice(candidates)
        else:
            daily_seed = int(today_str.replace("-", ""))
            selected_item = candidates[daily_seed % len(candidates)]

        cache[cache_key] = {
            "date": today_str,
            "timestamp": time.time(),
            "item": selected_item
        }
        _write_cache(cache)

    # Perform Buch-Brücke matching against local indexed library
    related_books = find_related_books_for_web_article(selected_item, max_results=3)
    
    result = dict(selected_item)
    result["related_books"] = related_books
    return result


def find_related_books_for_web_article(article: Dict[str, Any], max_results: int = 3) -> List[Dict[str, Any]]:
    """Buch-Brücke for Web Articles: Matches title, teaser, and keywords against local SQLite books."""
    try:
        books = get_all_books()
        if not books:
            return []

        title = article.get("title", "")
        teaser = article.get("teaser", "")
        faculty = article.get("faculty", "")

        raw_text = f"{title} {teaser} {faculty}".lower()
        tokens = re.findall(r'[a-zA-ZäöüÄÖÜß]{4,}', raw_text)

        stopwords = {
            "der", "die", "das", "und", "ist", "sind", "wird", "werden", "eine", "einer",
            "einem", "eines", "durch", "nach", "über", "unter", "zwischen", "wie", "auch",
            "kann", "können", "wenn", "damit", "sowie", "ihre", "ihrer", "ihrem", "ihren",
            "dieser", "diesem", "diesen", "dieses", "beim", "beide", "haben", "hatte", "wurde",
            "entstehung", "begriff", "bedeutung", "grundlagen", "prinzip", "theorie", "praxis"
        }

        keywords = [w for w in set(tokens) if w not in stopwords and len(w) >= 4]
        if not keywords:
            return []

        scored_books = []
        # Filter ancient books (e.g. from 1920s/30s/40s, Weimarer Republik, VEJ, war documents, etc.)
        historical_pattern = re.compile(
            r'\b(19[0-8][0-9]|18[0-9]{2}|vej|auschwitz|mauthausen|reichsrechnungshof|endlösung|hitler|nsdap|wehrmacht|konzentrationslager|ss-|weimarer\s+republik)\b',
            re.IGNORECASE
        )

        for b in books:
            pub_year = b.get("year")
            if pub_year is not None:
                try:
                    if int(pub_year) < 1990:
                        continue
                except (ValueError, TypeError):
                    pass

            b_raw_title = b.get("title") or ""
            b_desc = b.get("description") or ""
            b_full_meta = f"{b_raw_title} {b_desc}"
            if historical_pattern.search(b_full_meta):
                continue

            b_title = b_raw_title.lower()
            b_cats = (b.get("categories_str") or "").lower()
            b_author = (b.get("author") or "").lower()

            score = 0
            matched_terms = []

            for kw in keywords:
                pattern = rf"\b{re.escape(kw)}"
                if re.search(pattern, b_title):
                    score += 5
                    matched_terms.append(kw)
                elif re.search(pattern, b_cats):
                    score += 2
                    matched_terms.append(kw)
                elif len(kw) >= 5 and re.search(pattern, b_author):
                    score += 3
                    matched_terms.append(kw)

            # Faculty affinity bonus
            if "psychologie" in faculty.lower() and any(k in b_cats for k in ["psychologie", "kognition"]):
                score += 2
            elif "wirtschaft" in faculty.lower() and any(k in b_cats for k in ["wirtschaft", "bwl", "vwl"]):
                score += 2
            elif "politik" in faculty.lower() and any(k in b_cats for k in ["politik", "recht", "jura", "gesellschaft"]):
                score += 2
            elif "informatik" in faculty.lower() and any(k in b_cats for k in ["informatik", "programmierung", "python"]):
                score += 2
            elif "physik" in faculty.lower() and any(k in b_cats for k in ["physik", "quanten", "thermodynamik"]):
                score += 2

            if score > 0:
                scored_books.append((score, b, matched_terms))

        scored_books.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, book, matched in scored_books[:max_results]:
            b_copy = dict(book)
            b_copy["bridge_score"] = score
            b_copy["bridge_matches"] = matched[:3]
            results.append(b_copy)

        return results
    except Exception:
        return []
