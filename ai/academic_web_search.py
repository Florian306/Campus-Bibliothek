import base64
import concurrent.futures
import hashlib
import html
import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False
    import urllib.request

from core.library_db import get_search_cache, set_search_cache

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

PRESET_FILTERS = {
    "all": {
        "label": "🌐 Bereinigtes Web",
        "description": "Hochwertige Fachrechereche im offenen Web ohne Werbung oder Clickbait-Spam.",
        "query_suffix": "",
    },
    "uni": {
        "label": "🎓 Uni-Skripte & Vorlesungen",
        "description": "Vorlesungsskripte, Foliensätze und Lehrmaterialien von Hochschulen und Universitäten.",
        "query_suffix": "Skript OR Vorlesung OR lecture OR filetype:pdf",
    },
    "lexikon": {
        "label": "📖 Fachlexika & Definitionen",
        "description": "Definitionen und fundierte Fachartikel aus wissenschaftlichen Enzyklopädien und Lexika.",
        "query_suffix": "Lexikon OR Definition OR Enzyklopädie",
    },
    "tech": {
        "label": "💻 Tech- & MINT-Dokus",
        "description": "Offizielle Dokumentationen, RFCs und technische Entwicklerreferenzen.",
        "query_suffix": "documentation OR tutorial OR reference OR docs",
    },
}

# Domain classifiers
TRUSTED_UNI_TLDS = (".edu", ".ac.uk", ".ac.at", ".ac.jp", ".edu.au", ".edu.cn")
TRUSTED_UNI_DOMAINS = (
    "uni-", "tu-", "hs-", "kit.edu", "tum.de", "rwth-aachen.de", "fu-berlin.de",
    "hu-berlin.de", "lmu.de", "mpg.de", "fraunhofer.de", "helmholtz.de", "leibniz-gemeinschaft.de",
    "ethz.ch", "unibas.ch", "ox.ac.uk", "cam.ac.uk", "mit.edu", "stanford.edu", "harvard.edu",
    "fernuni-hagen.de", "uibk.ac.at", "univie.ac.at", "unizh.ch", "uni.lu"
)
TRUSTED_LEXIKA_DOMAINS = (
    "spektrum.de", "chemie.de", "plato.stanford.edu", "iep.utm.edu", "wolfram.com",
    "wikipedia.org", "wikibooks.org", "britannica.com", "bpb.de", "wirtschaftslexikon.gabler.de",
    "duden.de", "dwds.de", "bibelwissenschaft.de", "zeno.org", "textlog.de"
)
TRUSTED_TECH_DOMAINS = (
    "python.org", "mozilla.org", "w3.org", "kernel.org", "geeksforgeeks.org",
    "devdocs.io", "github.com", "stackoverflow.com", "gnu.org", "apache.org",
    "rust-lang.org", "golang.org", "qt.io", "microsoft.com/learn", "digitalocean.com/community"
)
TRUSTED_SCIENCE_DOMAINS = (
    "springer.com", "sciencedirect.com", "nature.com", "wiley.com", "nih.gov",
    "frontiersin.org", "plos.org", "mdpi.com", "cell.com", "bmj.com", "thelancet.com",
    "arxiv.org", "researchgate.net", "semanticscholar.org", "openalex.org", "doi.org"
)

# Unwanted clickbait, social networks, and affiliate portals
BLOCKED_DOMAINS = (
    "bing.com/aclick", "googleadservices.com", "doubleclick.net",
    "pinterest.", "instagram.com", "tiktok.com", "facebook.com", "twitter.com", "x.com",
    "gala.de", "bunte.de", "brigitte.de", "instyle.de", "freundin.de", "bild.de",
    "promiflash.de", "chip.de/downloads"
)


def decode_bing_url(bing_url: str) -> str:
    """Decodes actual target URL from Bing redirect tracking links (base64 in 'u=' param)."""
    clean_url = html.unescape(bing_url)
    if "u=" not in clean_url:
        return clean_url
    m = re.search(r'[?&]u=([a-zA-Z0-9_-]+)', clean_url)
    if not m:
        return clean_url
    raw = m.group(1)
    if raw.startswith("a1"):
        raw = raw[2:]
    rem = len(raw) % 4
    if rem > 0:
        raw += "=" * (4 - rem)
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8", "ignore")
        if decoded.startswith("http://") or decoded.startswith("https://"):
            return decoded
    except Exception:
        pass
    return clean_url


def decode_ddg_url(ddg_url: str) -> str:
    """Decodes DuckDuckGo redirect link."""
    clean_url = html.unescape(ddg_url)
    if "uddg=" in clean_url:
        m = re.search(r'uddg=([^&]+)', clean_url)
        if m:
            try:
                return urllib.parse.unquote(m.group(1))
            except Exception:
                pass
    if clean_url.startswith("//"):
        return "https:" + clean_url
    return clean_url


def classify_url(url: str) -> Tuple[str, str, str, bool, bool]:
    """Classifies a URL into a source category badge, badge color, domain name, verified trust status, and PDF flag.
    Returns: (badge_text, badge_color, domain_name, is_verified, is_pdf)
    """
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        path = parsed.path.lower()
        is_pdf = path.endswith(".pdf") or "pdf" in parsed.query.lower()
    except Exception:
        return "🌐 Web-Quelle", "#8B949E", "web", False, False

    # 1. Uni / Academic Institute
    if any(domain.endswith(tld) for tld in TRUSTED_UNI_TLDS) or any(u in domain for u in TRUSTED_UNI_DOMAINS):
        return "🎓 Hochschule & Forschung", "#238636", domain, True, is_pdf

    # 2. Fachlexika & Enzyklopädie
    if any(d in domain for d in TRUSTED_LEXIKA_DOMAINS):
        return "📖 Fachlexikon & Definition", "#3FB950", domain, True, is_pdf

    # 3. Tech Doku
    if any(d in domain for d in TRUSTED_TECH_DOMAINS):
        return "💻 Tech-Dokumentation", "#A371F7", domain, True, is_pdf

    # 4. Peer-Reviewed / Science Publisher
    if any(d in domain for d in TRUSTED_SCIENCE_DOMAINS):
        return "🔬 Wissenschaftsportal", "#F0883E", domain, True, is_pdf

    # 5. General verified education/govt
    if domain.endswith(".org") or domain.endswith(".gov"):
        return "🏛️ Offizielle Institution", "#79C0FF", domain, True, is_pdf

    if is_pdf:
        return "📄 Fachdokument (PDF)", "#58A6FF", domain, False, True

    return "🌐 Seriöser Fachbeitrag", "#8B949E", domain, False, False


def _search_wikipedia_api(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Fetches high-quality definitions and encyclopedia articles directly from Wikipedia API."""
    try:
        url = f"https://de.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json&srlimit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Buchsortierer/2.0 (Academic Library Assistant)"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
            results = []
            for item in data.get("query", {}).get("search", []):
                t = item.get("title", "")
                if not t:
                    continue
                snip = html.unescape(re.sub(r'<[^>]+>', '', item.get("snippet", ""))).strip()
                page_url = f"https://de.wikipedia.org/wiki/{urllib.parse.quote(t.replace(' ', '_'))}"
                results.append({
                    "title": f"{t} – Wikipedia",
                    "url": page_url,
                    "domain": "de.wikipedia.org",
                    "snippet": snip,
                    "badge_text": "📖 Fachlexikon & Definition",
                    "badge_color": "#3FB950",
                    "is_verified": True,
                    "is_pdf": False,
                    "preset": "lexikon"
                })
            return results
    except Exception:
        return []


def _search_crossref_api(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Fetches verified peer-reviewed publications and books from CrossRef DOI registry."""
    try:
        url = f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={limit}"
        resp_text = ""
        if _HAS_CURL_CFFI:
            r = cffi_requests.get(url, headers={"User-Agent": "Buchsortierer/2.0 (mailto:florian@campus.edu)"}, timeout=5)
            if r.status_code == 200:
                resp_text = r.text
        if not resp_text:
            req = urllib.request.Request(url, headers={"User-Agent": "Buchsortierer/2.0 (mailto:florian@campus.edu)"})
            with urllib.request.urlopen(req, timeout=5) as r:
                resp_text = r.read().decode("utf-8", "ignore")

        data = json.loads(resp_text)
        items = []
        for w in data.get("message", {}).get("items", []):
            titles = w.get("title", [])
            if not titles or not titles[0]:
                continue
            title = titles[0].strip()
            link = w.get("URL") or f"https://doi.org/{w.get('DOI', '')}"
            pub = w.get("publisher", "Fachverlag")
            container = w.get("container-title", [""])[0] if w.get("container-title") else ""
            year = ""
            if "published" in w and "date-parts" in w["published"]:
                dp = w["published"]["date-parts"]
                if dp and dp[0]:
                    year = str(dp[0][0])
            authors = []
            for a in w.get("author", [])[:2]:
                family = a.get("family", "")
                if family:
                    authors.append(family)
            auth_str = ", ".join(authors) if authors else "Wissenschaftliche Publikation"
            parts = [auth_str]
            if year:
                parts.append(f"({year})")
            if container:
                parts.append(f"in: {container}")
            if pub:
                parts.append(f"[{pub}]")
            snip = " · ".join(parts)

            items.append({
                "title": title,
                "url": link,
                "domain": "doi.org",
                "snippet": snip,
                "badge_text": "🔬 Wissenschaftsportal",
                "badge_color": "#F0883E",
                "is_verified": True,
                "is_pdf": False,
                "year": int(year) if year.isdigit() else None,
                "preset": "all"
            })
        return items
    except Exception:
        return []


def _search_openalex_api(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Queries OpenAlex Open Science Index for open-access research papers and monographs."""
    try:
        url = f"https://api.openalex.org/works?search={urllib.parse.quote(query)}&per-page={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Buchsortierer/2.0 (Campus Library AI)"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))

        items = []
        for w in data.get("results", []):
            title = w.get("title")
            if not title:
                continue
            doi = w.get("doi")
            landing_url = doi or w.get("id") or ""
            oa_url = w.get("open_access", {}).get("oa_url")
            effective_url = oa_url if oa_url else landing_url
            if not effective_url:
                continue

            year = w.get("publication_year")
            authorships = w.get("authorships", [])
            author_names = []
            for a in authorships[:2]:
                name = a.get("author", {}).get("display_name")
                if name:
                    author_names.append(name)
            auth_str = ", ".join(author_names) if author_names else "OpenAlex Scholar"
            venue = w.get("primary_location", {}).get("source", {}).get("display_name", "")

            parts = [auth_str]
            if year:
                parts.append(f"({year})")
            if venue:
                parts.append(f"in: {venue}")
            snip = " · ".join(parts)

            is_pdf = effective_url.lower().endswith(".pdf") or (oa_url and oa_url.lower().endswith(".pdf"))
            badge_text = "🎓 Open-Access Paper" if is_pdf else "🔬 OpenAlex Publikation"

            items.append({
                "title": title.strip(),
                "url": effective_url,
                "domain": "openalex.org",
                "snippet": snip,
                "badge_text": badge_text,
                "badge_color": "#238636" if is_pdf else "#F0883E",
                "is_verified": True,
                "is_pdf": is_pdf,
                "year": year,
                "preset": "all"
            })
        return items
    except Exception:
        return []


def _search_bing(effective_query: str) -> List[Dict[str, Any]]:
    """Crawls Bing Search results."""
    search_url = (
        f"https://www.bing.com/search?q={urllib.parse.quote(effective_query)}"
        f"&setlang=de-de&setmkt=de-de"
    )
    html_content = ""

    if _HAS_CURL_CFFI:
        try:
            resp = cffi_requests.get(
                search_url,
                headers={"Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"},
                impersonate="chrome120",
                timeout=7
            )
            if resp.status_code == 200:
                html_content = resp.text
        except Exception:
            pass

    if not html_content:
        try:
            req = urllib.request.Request(
                search_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            )
            with urllib.request.urlopen(req, timeout=7) as resp:
                html_content = resp.read().decode("utf-8", "ignore")
        except Exception:
            html_content = ""

    blocks = re.findall(r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>', html_content, re.DOTALL) if html_content else []
    results: List[Dict[str, Any]] = []

    for b in blocks:
        if "b_ad" in b or "b_ans" in b:
            continue

        h2 = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2>', b, re.DOTALL)
        if not h2:
            continue

        raw_href = h2.group(1)
        real_url = decode_bing_url(raw_href)

        if not real_url or any(bad in real_url.lower() for bad in BLOCKED_DOMAINS):
            continue

        raw_title = re.sub(r'<[^>]+>', '', h2.group(2)).strip()
        clean_title = html.unescape(raw_title)

        snip_m = re.search(r'<p[^>]*class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', b, re.DOTALL)
        if not snip_m:
            snip_m = re.search(r'<p[^>]*>(.*?)</p>', b, re.DOTALL)
        raw_snippet = ""
        if snip_m:
            raw_snippet = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip()
        clean_snippet = html.unescape(raw_snippet)

        badge_text, badge_color, domain, is_verified, is_pdf = classify_url(real_url)

        year_val: Optional[int] = None
        ym = re.search(r'\b(20[0-2][0-9]|19[89][0-9])\b', f"{clean_title} {clean_snippet} {real_url}")
        if ym:
            try:
                year_val = int(ym.group(1))
            except Exception:
                pass

        results.append({
            "title": clean_title,
            "url": real_url,
            "domain": domain,
            "snippet": clean_snippet,
            "badge_text": badge_text,
            "badge_color": badge_color,
            "is_verified": is_verified,
            "is_pdf": is_pdf,
            "year": year_val,
        })
    return results


def _search_duckduckgo(effective_query: str) -> List[Dict[str, Any]]:
    """Fallback search using DuckDuckGo HTML endpoint."""
    ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(effective_query)}"
    html_content = ""

    if _HAS_CURL_CFFI:
        try:
            resp = cffi_requests.get(
                ddg_url,
                headers={"User-Agent": USER_AGENT},
                impersonate="chrome120",
                timeout=7
            )
            if resp.status_code == 200:
                html_content = resp.text
        except Exception:
            pass

    if not html_content:
        try:
            req = urllib.request.Request(ddg_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=7) as resp:
                html_content = resp.read().decode("utf-8", "ignore")
        except Exception:
            return []

    results: List[Dict[str, Any]] = []
    blocks = re.findall(r'<div class="result[^>]*>(.*?)</div>\s*</div>', html_content, re.DOTALL)
    for b in blocks:
        link_m = re.search(r'<a class="result__url"[^>]*href="([^"]+)"', b)
        title_m = re.search(r'<a class="result__snippet[^>]*href="[^"]*"[^>]*>(.*?)</a>', b) or re.search(r'<h2 class="result__title">.*?<a[^>]*>(.*?)</a>', b, re.DOTALL)
        snip_m = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', b, re.DOTALL)

        if not link_m:
            continue

        raw_url = decode_ddg_url(link_m.group(1).strip())
        if not raw_url.startswith("http") or any(bad in raw_url.lower() for bad in BLOCKED_DOMAINS):
            continue

        title_raw = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
        snip_raw = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip() if snip_m else ""

        title = html.unescape(title_raw)
        snippet = html.unescape(snip_raw)

        badge_text, badge_color, domain, is_verified, is_pdf = classify_url(raw_url)

        results.append({
            "title": title or domain,
            "url": raw_url,
            "domain": domain,
            "snippet": snippet,
            "badge_text": badge_text,
            "badge_color": badge_color,
            "is_verified": is_verified,
            "is_pdf": is_pdf,
            "year": None,
        })
    return results


def search_academic_web(
    query: str,
    preset: str = "all",
    pdf_only: bool = False,
    min_year: Optional[int] = None,
    max_results: int = 999,
    use_cache: bool = True
) -> List[Dict[str, Any]]:
    """Executes resilient multi-source academic web search.
    Features:
    - High-performance SQLite search cache (instant response on repeated queries).
    - Multi-Source crawler: Bing + DuckDuckGo fallback + OpenAlex API + CrossRef + Wikipedia.
    - Automatic URL deduplication, ranking and PDF detection.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    # Check cache
    cache_key = f"web_{hashlib.md5(f'{clean_query}_{preset}_{pdf_only}_{min_year}'.encode('utf-8')).hexdigest()}"
    if use_cache:
        cached = get_search_cache(cache_key, max_age_seconds=86400)
        if cached:
            return cached[:max_results]

    preset_config = PRESET_FILTERS.get(preset, PRESET_FILTERS["all"])
    suffix = preset_config.get("query_suffix", "").strip()

    if pdf_only:
        suffix = f"{suffix} filetype:pdf".strip()

    effective_query = f"{clean_query} {suffix}".strip() if suffix else clean_query

    results: List[Dict[str, Any]] = []
    seen_urls = set()

    # Parallel query execution for lightning-fast multi-source response
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_bing = executor.submit(_search_bing, effective_query)
        future_ddg = executor.submit(_search_duckduckgo, effective_query)
        future_wiki = executor.submit(_search_wikipedia_api, clean_query, 4 if preset in ("all", "lexikon") else 0)
        future_crossref = executor.submit(_search_crossref_api, clean_query, 4 if preset in ("all", "uni") else 0)
        future_openalex = executor.submit(_search_openalex_api, clean_query, 5 if preset in ("all", "uni") else 0)

        # 1. Harvest Bing
        try:
            for item in future_bing.result(timeout=8):
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    item["preset"] = preset
                    results.append(item)
        except Exception:
            pass

        # 2. Harvest DuckDuckGo if Bing had few results
        if len(results) < 8:
            try:
                for item in future_ddg.result(timeout=8):
                    if item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        item["preset"] = preset
                        results.append(item)
            except Exception:
                pass

        # 3. Harvest Wikipedia (capped to max 2 items to prevent Wikipedia dominance)
        if not pdf_only and preset in ("all", "lexikon"):
            try:
                wiki_count = 0
                for item in future_wiki.result(timeout=6):
                    if item["url"] not in seen_urls and wiki_count < 2:
                        seen_urls.add(item["url"])
                        results.append(item)
                        wiki_count += 1
            except Exception:
                pass

        # 4. Harvest CrossRef
        if not pdf_only and preset in ("all", "uni"):
            try:
                for item in future_crossref.result(timeout=6):
                    if item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        results.append(item)
            except Exception:
                pass

        # 5. Harvest OpenAlex Open Science Index
        try:
            for item in future_openalex.result(timeout=6):
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    results.append(item)
        except Exception:
            pass

    # Post-filtering (PDF-only & min_year)
    filtered: List[Dict[str, Any]] = []
    wiki_seen = 0
    for r in results:
        if pdf_only and not r.get("is_pdf"):
            continue
        y = r.get("year")
        if min_year and y and y < min_year:
            continue
        # Hard cap on Wikipedia in final results: max 2
        if "wikipedia.org" in (r.get("domain") or "").lower():
            if wiki_seen >= 2:
                continue
            wiki_seen += 1
        filtered.append(r)

    # Smart priority ranking
    def _rank_score(r: Dict[str, Any]) -> int:
        score = 0
        p = r.get("preset", "all")
        badge = r.get("badge_text", "")
        dom = (r.get("domain") or "").lower()

        if p == "uni":
            if "Uni" in badge or "Hochschule" in badge or "Paper" in badge:
                score += 15
            if r.get("is_pdf"):
                score += 10
        elif p == "lexikon":
            if "Lexikon" in badge or "Definition" in badge:
                score += 15
        elif p == "tech":
            if "Tech" in badge:
                score += 15

        # Reward verified institutional portals (bpb, bundesbank, destatis, universities, science papers)
        if any(pri in dom for pri in ["bpb.de", "bundesbank.de", "destatis.de", "wzb.eu", "diw.de", "ifo.de", "mpg.de", "fraunhofer.de", "uni-", "tum.de", "rwth-"]):
            score += 18

        if r.get("is_verified"):
            score += 10
        if r.get("is_pdf"):
            score += 8
        if r.get("year") and r["year"] >= 2020:
            score += 2

        # Demote Wikipedia slightly to give variety & priority to primary sources
        if "wikipedia.org" in dom:
            score -= 5

        return score

    filtered.sort(key=_rank_score, reverse=True)
    final_results = filtered[:max_results]

    # Save to SQLite cache
    if final_results and use_cache:
        set_search_cache(cache_key, final_results)

    return final_results
