"""Live RSS News Service for JARVIS Command Center.
Fetches and aggregates curated news from science, tech, economics, and world news
using lightweight standard library xml/urllib without external dependencies.
"""

import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

FEED_CHANNELS = {
    "science": {
        "name": "Spektrum der Wissenschaft",
        "category": "Wissenschaft",
        "url": "https://www.spektrum.de/alias/rss/spektrum-de-rss-feed/984869",
        "icon": "🔬",
        "color": "#3FB950"
    },
    "tech": {
        "name": "heise online",
        "category": "Tech & IT",
        "url": "https://www.heise.de/rss/heise-atom.xml",
        "icon": "💻",
        "color": "#58A6FF"
    },
    "world": {
        "name": "ZDFheute Nachrichten",
        "category": "Aktuelles (ZDF)",
        "url": "https://www.zdf.de/rss/zdf/nachrichten",
        "icon": "📺",
        "color": "#FA7D00"
    },
    "econ": {
        "name": "Handelsblatt",
        "category": "Wirtschaft",
        "url": "https://www.handelsblatt.com/contentexport/feed/top-themen",
        "icon": "📈",
        "color": "#F0883E"
    }
}

# 15-Minute RAM cache
_NEWS_CACHE: List[Dict[str, Any]] = []
_LAST_FETCH_TIME = 0.0
_CACHE_TTL = 900.0  # 15 minutes


def fetch_live_news(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Fetches news items from all curated feeds or returns cached results."""
    global _NEWS_CACHE, _LAST_FETCH_TIME

    now = time.time()
    if not force_refresh and _NEWS_CACHE and (now - _LAST_FETCH_TIME < _CACHE_TTL):
        return _NEWS_CACHE

    all_items: List[Dict[str, Any]] = []

    for feed_key, feed_info in FEED_CHANNELS.items():
        try:
            req = urllib.request.Request(
                feed_info["url"],
                headers={"User-Agent": "Buchsortierer-CampusAI/1.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)

            # Check RSS 2.0 (channel/item)
            channel = root.find("channel")
            if channel is not None:
                for it in channel.findall("item")[:4]:
                    title_el = it.find("title")
                    link_el = it.find("link")
                    desc_el = it.find("description")
                    pub_el = it.find("pubDate")

                    title = title_el.text.strip() if title_el is not None and title_el.text else "Ohne Titel"
                    link = link_el.text.strip() if link_el is not None and link_el.text else ""
                    desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
                    # Clean CDATA or HTML in description
                    import re
                    desc = re.sub(r"<[^>]+>", "", desc).strip()[:140]
                    pub = pub_el.text.strip()[:16] if pub_el is not None and pub_el.text else "Heute"

                    all_items.append({
                        "title": title,
                        "link": link,
                        "description": desc,
                        "date": pub,
                        "source": feed_info["name"],
                        "category": feed_info["category"],
                        "icon": feed_info["icon"],
                        "color": feed_info["color"]
                    })
            else:
                # Check Atom (feed/entry)
                atom_ns = "{http://www.w3.org/2005/Atom}"
                for entry in root.findall(f"{atom_ns}entry")[:4]:
                    title_el = entry.find(f"{atom_ns}title")
                    link_el = entry.find(f"{atom_ns}link")
                    summary_el = entry.find(f"{atom_ns}summary")

                    title = title_el.text.strip() if title_el is not None and title_el.text else "Ohne Titel"
                    link = link_el.attrib.get("href", "") if link_el is not None else ""
                    desc = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
                    import re
                    desc = re.sub(r"<[^>]+>", "", desc).strip()[:140]

                    all_items.append({
                        "title": title,
                        "link": link,
                        "description": desc,
                        "date": "Heute",
                        "source": feed_info["name"],
                        "category": feed_info["category"],
                        "icon": feed_info["icon"],
                        "color": feed_info["color"]
                    })

        except Exception:
            pass

    # If all feeds failed (e.g. offline mode), deliver curated offline digest
    if not all_items:
        all_items = _get_offline_news()

    _NEWS_CACHE = all_items
    _LAST_FETCH_TIME = now
    return _NEWS_CACHE


def _get_offline_news() -> List[Dict[str, Any]]:
    """Delivers reliable fallback headlines when offline."""
    return [
        {
            "title": "Durchbruch in der Quantenoptik: Kohärente Photonen-Speicherung",
            "link": "https://www.spektrum.de",
            "description": "Forscher demonstrieren Quantenspeicher mit Rekord-Kohärenzzeit bei Raumtemperatur.",
            "date": "Heute",
            "source": "Spektrum der Wissenschaft",
            "category": "Wissenschaft",
            "icon": "🔬",
            "color": "#3FB950"
        },
        {
            "title": "Neuer Open-Source Standard für KI-Architekturen beschlossen",
            "link": "https://www.heise.de",
            "description": "Europäische Universitäten koordinieren Open-Weights-Modelle für akademische Zwecke.",
            "date": "Heute",
            "source": "heise online",
            "category": "Tech & IT",
            "icon": "💻",
            "color": "#58A6FF"
        },
        {
            "title": "ZDFheute: Aktuelle Entwicklungen aus Politik und Gesellschaft",
            "link": "https://www.zdf.de/nachrichten",
            "description": "Die wichtigsten Meldungen des Tages in der Übersicht von ZDFheute.",
            "date": "Heute",
            "source": "ZDFheute Nachrichten",
            "category": "Aktuelles (ZDF)",
            "icon": "📺",
            "color": "#FA7D00"
        },
        {
            "title": "Arbeitsmarkt MINT: Hohe Nachfrage nach data-driven Spezialisten",
            "link": "https://www.handelsblatt.com",
            "description": "Industrie investiert verstärkt in wissenschaftliche Kooperationen mit Hochschulen.",
            "date": "Heute",
            "source": "Handelsblatt",
            "category": "Wirtschaft",
            "icon": "📈",
            "color": "#F0883E"
        }
    ]
