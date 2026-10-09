"""Academic Paper Discovery and Research Sentinel Service.
Searches global scientific literature via arXiv and Semantic Scholar APIs,
handles institutional access routing (FernUniversität in Hagen EZProxy),
and manages local PDF downloads for the dedicated Research Archive.
"""

import os
import re
import ssl
import json
import time
import urllib.parse
import urllib.request
import html
import concurrent.futures
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from core.config import get_app_dir, get_books_storage_dir
from ai.categories import STANDARD_CATEGORIES, COMPILED_FACULTY_KNOWLEDGE

_ssl_ctx = None
try:
    _ssl_ctx = ssl.create_default_context()
except Exception:
    _ssl_ctx = ssl._create_unverified_context()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CampusLibrary-ResearchSentinel/3.0"

FACULTY_SEARCH_TERMS: Dict[str, str] = {
    "Mathematik": "Algebra Topology Analysis Differential Equations Combinatorics Stochastik",
    "Physik & Astronomie": "Quantum Mechanics Astrophysics Thermodynamics Relativity Particle Physics",
    "Chemie": "Organic Chemistry Biochemistry Chemical Synthesis Catalysis Spectroscopy",
    "Biologie & Lebenswissenschaften": "Molecular Biology Genetics CRISPR Genomics Microbiology Neuroscience",
    "Geowissenschaften & Geologie": "Plate Tectonics Paleontology Climate Change Geology Mineralogy Geophysics",
    "Informatik & Programmierung": "Machine Learning Artificial Intelligence Algorithms Computer Systems Cybersecurity",
    "Medizin & Pharmazie": "Clinical Medicine Oncology Pharmacology Immunology Epidemiology Pathology",
    "Psychologie & Soziologie": "Cognitive Psychology Social Psychology Behavioral Neuroscience Personality Psychiatry",
    "Wirtschaftswissenschaften": "Macroeconomics Microeconomics Corporate Finance Behavioral Economics Econometrics",
    "Rechtswissenschaften & Jura": "Constitutional Law Criminal Jurisprudence Civil Law Commercial Law Legal Philosophy",
    "Ingenieurwissenschaften & Technik": "Mechanical Engineering Robotics Electrical Systems Materials Science Mechatronics",
    "Geschichte & Politik": "International Relations Contemporary History Political Theory World War Geopolitics",
    "Philosophie & Religion": "Epistemology Ethics Metaphysics Philosophy of Mind Political Philosophy Theology",
    "Pädagogik & Schule": "Educational Psychology Instructional Design Cognitive Load Didactics Learning Science",
    "Sprach- & Literaturwissenschaft": "Linguistics Computational Semantics Literary Theory Syntax Morphology Discourse",
    "Sonstiges": "Interdisciplinary Academic Research Methodology Innovation",
}


def infer_paper_category(title: str, abstract: str = "") -> str:
    """Classifies a research paper into one of the academic faculties based on title and abstract."""
    full_text = f"{title} {abstract}".lower()

    # Priority academic domain regex heuristics for immediate accurate faculty match
    if re.search(r'\b(neural network|deep learning|machine learning|maschinelles lernen|künstliche intelligenz|artificial intelligence|large language model|llm|transformer|algorithm|cybersecurity|software engineering|computer vision)\b', full_text):
        return "Informatik & Programmierung"
    if re.search(r'\b(licht|optik|dispergier|strahl|quanten|thermodynam|wellen|relativit|astronom|physik|particle|mechanics|gravitation)\b', full_text):
        return "Physik & Astronomie"
    if re.search(r'\b(medizin|patient|therap|klinik|hospital|infect|disease|covid|sars|pharma|biomed|drug|vaccin|cancer|tumor|surgery|treatment|syndrome|cardio|patholog|hypoxemia|lymphocytopenia)\b', full_text):
        return "Medizin & Pharmazie"
    if re.search(r'\b(bildung|erziehung|unterricht|schul|didaktik|p[aä]dagogik|lehrkraft|curriculum|klassenraum|pedagogy|education|schooling|instructional)\b', full_text) or re.search(r'\b(lernerfolg|lernprozess|multimediales lernen|lernumgebung)\b', full_text):
        return "Pädagogik & Schule"
    if re.search(r'\b(gesetz|urteil|rechtswissenschaft|verfassung|jurist|strafrecht|zivilrecht|urheberrecht|datenschutzrecht|legal theory|jurisprudence|constitutional law)\b', full_text):
        return "Rechtswissenschaften & Jura"
    if re.search(r'\b(wirtschaft|finanz|ökonom|macroeconomic|microeconomic|monetary policy|inflation|management|betriebswirtschaft|volkswirtschaft)\b', full_text):
        return "Wirtschaftswissenschaften"
    if re.search(r'\b(soziolog|gesellschaft|medienwirkung|kommunikation|psycholog|verhalten|kognition|sociology|cognition)\b', full_text):
        return "Psychologie & Soziologie"

    best_fac = "Interdisziplinär & Allgemein"
    best_score = 0

    for fac, data in COMPILED_FACULTY_KNOWLEDGE.items():
        score = 0
        # Anchors (higher weight)
        for _, pat in data.get("anchors", []):
            if pat.search(full_text):
                score += 3
        # Keywords
        for _, pat in data.get("keywords", []):
            if pat.search(full_text):
                score += 1

        if score > best_score:
            best_score = score
            best_fac = fac

    return best_fac if best_score > 0 else "Interdisziplinär & Allgemein"



def get_papers_dir(category: Optional[str] = None) -> str:
    """Ensures and returns the research papers storage directory located at the books storage root.
    Automatically creates the 'Papers' folder (and optional faculty subfolder) if it does not exist.
    """
    books_root = get_books_storage_dir()
    papers_base = os.path.join(books_root, "Papers")
    os.makedirs(papers_base, exist_ok=True)

    if category:
        clean_cat = re.sub(r'[\/\\:*?"<>|]', ' ', category).strip()
        cat_dir = os.path.join(papers_base, clean_cat)
        os.makedirs(cat_dir, exist_ok=True)
        return cat_dir

    return papers_base


_translation_cache: Dict[str, str] = {}


def translate_abstract_to_german(text: str) -> str:
    """Translates an academic English abstract into fluent, natural scientific German.
    Includes in-memory caching for instant tab switching.
    """
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) < 15:
        return cleaned

    # Return cached translation if available
    cache_key = cleaned[:100]
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    # Quick heuristic: if already German, return immediately
    german_indicators = {" der ", " die ", " das ", " und ", " ist ", " sind ", " werden ", " wurde ", " eine ", " eines "}
    lower_sample = f" {cleaned[:200].lower()} "
    if sum(1 for w in german_indicators if w in lower_sample) >= 3:
        _translation_cache[cache_key] = cleaned
        return cleaned

    try:
        # Split into manageable chunks if abstract is long
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=de&dt=t&q=" + urllib.parse.quote(cleaned[:2500])
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4.5, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        translated_parts = []
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
            for part in data[0]:
                if isinstance(part, list) and len(part) > 0 and part[0]:
                    translated_parts.append(str(part[0]))

        translated = "".join(translated_parts).strip()
        if translated:
            _translation_cache[cache_key] = translated
            return translated
    except Exception:
        pass

    return cleaned


def clean_abstract_text(abstract: str, title: str = "", year: Any = "") -> str:
    """Cleans and validates an abstract, replacing OCR garbage or math formula fragments with meaningful context."""
    if not abstract:
        return "Kein Fließtext-Abstract hinterlegt. Die Originalarbeit kann direkt in Microsoft Edge eingesehen werden."

    cleaned = abstract.strip()
    # Check if text is just math/OCR noise (e.g. "~+ 5 } ( 2 v + 7 ) '??+ ' * ' )")
    words = re.findall(r'[a-zA-ZäöüÄÖÜß]{2,}', cleaned)
    if len(words) < 5 or (len(words) / max(1, len(cleaned.split())) < 0.35):
        year_str = f" ({year})" if year else ""
        return (
            f"Für diese historische Publikation{year_str} liegt im digitalen Katalog kein Fließtext-Abstract vor. "
            f"Der vollständige Originaltext kann direkt über die Verlagsseite / DOI in Microsoft Edge geöffnet werden."
        )
    return cleaned


def search_openalex(query: str, max_results: int = 35) -> List[Dict[str, Any]]:
    """Queries OpenAlex Graph API across 250M+ global works spanning all 15 academic disciplines."""
    clean_q = re.sub(r'[^\w\s\-\.]', ' ', query).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    url = f"https://api.openalex.org/works?search={urllib.parse.quote(clean_q)}&per-page={max_results}&sort=relevance_score:desc"

    results = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"CampusLibrary-Sentinel/3.0 (mailto:scholar@campus-library.de)"})
        with urllib.request.urlopen(req, timeout=6.0, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        for item in data.get("results", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue

            year = item.get("publication_year") or time.localtime().tm_year

            # Authors
            authors = []
            for a in item.get("authorships", []):
                name = a.get("author", {}).get("display_name")
                if name:
                    authors.append(name)
            # Reconstruct abstract from inverted index
            abstract = ""
            inv = item.get("abstract_inverted_index")
            if inv:
                words = {}
                for word, pos_list in inv.items():
                    for pos in pos_list:
                        words[pos] = word
                abstract = " ".join(words[i] for i in sorted(words.keys()))
            abstract = clean_abstract_text(abstract, title=title, year=year)

            # Journal / Venue
            loc = item.get("primary_location") or {}
            source_obj = loc.get("source") or {}
            journal = source_obj.get("display_name") or "Akademische Publikation"

            if authors:
                authors_str = ", ".join(authors[:5])
            elif journal and "Akademische" not in journal:
                authors_str = f"{journal} (Hrsg.)"
            else:
                authors_str = "o.A. (Fachpublikation)"

            # Year & Citations
            year = item.get("publication_year") or time.localtime().tm_year
            citations = item.get("cited_by_count") or 0

            # Open Access & PDF (strict validation)
            oa_info = item.get("open_access") or {}
            is_oa = bool(oa_info.get("is_oa")) and (oa_info.get("oa_status") != "closed")
            pdf_url = ""
            if is_oa:
                best_loc = item.get("best_oa_location") or {}
                pdf_url = (best_loc.get("pdf_url") or "").strip()
                if not pdf_url:
                    for loc in item.get("locations", []):
                        if loc and loc.get("pdf_url") and loc.get("is_oa"):
                            pdf_url = loc["pdf_url"].strip()
                            break
                if not pdf_url:
                    pdf_url = (oa_info.get("oa_url") or "").strip()

            # DOI
            raw_doi = item.get("doi") or ""
            clean_doi = raw_doi.replace("https://doi.org/", "").strip()

            item_id = item.get("id", "").split("/")[-1] or f"oa_{abs(hash(title))}"

            results.append({
                "id": f"openalex_{item_id}",
                "title": title,
                "authors": authors_str,
                "abstract": abstract,
                "year": year,
                "journal": journal,
                "doi": clean_doi,
                "arxiv_id": "",
                "pdf_url": pdf_url,
                "citation_count": citations,
                "source": "OpenAlex Global Index",
                "is_open_access": is_oa,
            })
    except Exception:
        pass

    return results


def search_crossref(query: str, max_results: int = 12) -> List[Dict[str, Any]]:
    """Queries Crossref REST API for peer-reviewed journal articles, law publications, and books."""
    clean_q = re.sub(r'[^\w\s\-\.]', ' ', query).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    url = f"https://api.crossref.org/works?query={urllib.parse.quote(clean_q)}&rows={max_results}&sort=relevance"

    results = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"CampusLibrary-Sentinel/3.0 (mailto:scholar@campus-library.de)"})
        with urllib.request.urlopen(req, timeout=6.0, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        for item in data.get("message", {}).get("items", []):
            titles = item.get("title") or []
            title = titles[0].strip() if titles else ""
            if not title:
                continue

            authors = []
            for a in item.get("author", []):
                given = a.get("given", "")
                family = a.get("family", "")
                name = f"{given} {family}".strip()
                if name:
                    authors.append(name)
            # Year (Prioritize print publication, then online, issued, or created)
            pub = item.get("published-print") or item.get("published-online") or item.get("issued") or item.get("created") or {}
            parts = pub.get("date-parts", [[]])[0]
            year = parts[0] if (parts and isinstance(parts[0], int) and 1800 <= parts[0] <= 2030) else 2024

            # Venue
            containers = item.get("container-title") or []
            journal = containers[0] if containers else item.get("publisher", "Wissenschaftlicher Verlag")

            if authors:
                authors_str = ", ".join(authors[:5])
            elif journal:
                authors_str = f"{journal} (Hrsg.)"
            else:
                authors_str = "o.A. (Fachpublikation)"

            doi = item.get("DOI", "")
            citations = item.get("is-referenced-by-count", 0)

            # Strict Open Access License Verification (reject publisher paywall links)
            is_oa = False
            for lic in item.get("license", []):
                u = (lic.get("URL") or "").lower()
                if "creativecommons" in u or "open-access" in u:
                    is_oa = True
                    break

            links = item.get("link") or []
            pdf_url = ""
            if is_oa:
                for l in links:
                    if "pdf" in (l.get("content-type") or "").lower():
                        pdf_url = l.get("URL", "")
                        break

            abstract = (item.get("abstract") or "").replace("<jats:p>", "").replace("</jats:p>", "").strip()
            if not abstract:
                abstract = f"Wissenschaftlicher Fachbeitrag in {journal} ({year}). Abstract über Verlag oder Hochschul-Bibliothek abrufbar."

            results.append({
                "id": f"crossref_{re.sub(r'[^a-zA-Z0-9]', '_', doi)[:35]}",
                "title": title,
                "authors": authors_str,
                "abstract": abstract,
                "year": year,
                "journal": journal,
                "doi": doi,
                "arxiv_id": "",
                "pdf_url": pdf_url,
                "citation_count": citations,
                "source": "Crossref Peer-Review",
                "is_open_access": is_oa,
            })
    except Exception:
        pass

    return results


def search_arxiv(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Queries arXiv API for scientific preprints and full-text Open-Access PDFs."""
    clean_q = re.sub(r'[^\w\s\-\.]', ' ', query).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    url = f"https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(clean_q)}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"

    results = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=6.0, context=_ssl_ctx) as resp:
            content = resp.read()

        root = ET.fromstring(content)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", default="", namespaces=ns).strip()
            title = re.sub(r'\s+', ' ', title)
            if not title:
                continue

            summary = entry.findtext("atom:summary", default="", namespaces=ns).strip()
            summary = re.sub(r'\s+', ' ', summary)

            published = entry.findtext("atom:published", default="", namespaces=ns)
            year = None
            if published and len(published) >= 4:
                try:
                    year = int(published[:4])
                except ValueError:
                    pass

            authors = [a.findtext("atom:name", default="", namespaces=ns) for a in entry.findall("atom:author", ns)]
            authors_str = ", ".join(filter(None, authors))

            arxiv_id = entry.findtext("atom:id", default="", namespaces=ns).split("/abs/")[-1]
            doi = entry.findtext("arxiv:doi", default="", namespaces=ns)

            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href", pdf_url)

            results.append({
                "id": f"arxiv_{arxiv_id}",
                "title": title,
                "authors": authors_str or "Unbekannt",
                "abstract": summary,
                "year": year or time.localtime().tm_year,
                "journal": f"arXiv Preprint ({arxiv_id})",
                "doi": doi or "",
                "arxiv_id": arxiv_id,
                "pdf_url": pdf_url,
                "citation_count": 0,
                "source": "arXiv (Open Access)",
                "is_open_access": True,
            })
    except Exception:
        pass

    return results


def search_pedocs(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Queries peDOCS (DIPF | Leibniz-Institut für Bildungsforschung) for peer-reviewed German educational science and pedagogical research."""
    clean_q = re.sub(r'[^\w\s\-\.]', ' ', query).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    url = f"https://www.pedocs.de/lucene_ergebnis.php?suchwert1={urllib.parse.quote(clean_q)}&suchfeld1=o.freitext&bool1=and"
    headers = {"User-Agent": USER_AGENT}
    req = urllib.request.Request(url, headers=headers)

    results = []
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=_ssl_ctx) as resp:
            raw_html = resp.read().decode('utf-8', errors='ignore')

        pattern = re.compile(
            r'href=[\'"]([^\'\"]*frontdoor\.php\?source_opus=(\d+)[^\'\"]*)[\'"][^>]*>(.*?)</a>'
            r'.*?<strong class="[^"]*a5-book-list-item-autor[^"]*">(.*?)</strong>'
            r'(?:.*?href=[\'"]([^\'\"]*\.pdf)[\'"])?',
            re.DOTALL | re.IGNORECASE
        )

        for match in pattern.finditer(raw_html):
            if len(results) >= max_results:
                break
            _, opus_id, title_raw, author_raw, pdf_raw = match.groups()

            clean_title = html.unescape(re.sub(r'<[^>]+>', '', title_raw).strip())
            clean_author = html.unescape(re.sub(r'<[^>]+>', '', author_raw).strip())
            if not clean_title:
                continue

            pdf_url = ""
            if pdf_raw:
                pdf_url = pdf_raw.strip()
                if pdf_url.startswith("//"):
                    pdf_url = "https:" + pdf_url
                elif pdf_url.startswith("/"):
                    pdf_url = "https://www.pedocs.de" + pdf_url

            year_match = re.search(r'/volltexte/(\d{4})/', pdf_url) or re.search(r'\b(19\d\d|20\d\d)\b', clean_title)
            year = int(year_match.group(1)) if year_match else time.localtime().tm_year

            results.append({
                "id": f"pedocs_{opus_id}",
                "title": clean_title,
                "authors": clean_author or "peDOCS Bildungsforschung (DIPF)",
                "abstract": "Bildungswissenschaftliche Open-Access-Publikation aus dem Fachrepositorium peDOCS (DIPF | Leibniz-Institut für Bildungsforschung und Bildungsinformation). Volltext frei verfügbar.",
                "year": year,
                "journal": "peDOCS Bildungsforschung (DIPF)",
                "doi": f"10.25656/01:{opus_id}",
                "arxiv_id": "",
                "pdf_url": pdf_url,
                "citation_count": 0,
                "source": "peDOCS (DIPF)",
                "is_open_access": True,
                "category": "Pädagogik & Schule",
            })
    except Exception:
        pass

    return results


def search_eric(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Queries ERIC (Institute of Education Sciences - IES) for international educational and pedagogical science papers."""
    clean_q = re.sub(r'[^\w\s\-\.]', ' ', query).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    url = f"https://api.ies.ed.gov/eric/?search={urllib.parse.quote(clean_q)}&format=json&rows={max_results}"
    headers = {"User-Agent": USER_AGENT}
    req = urllib.request.Request(url, headers=headers)

    results = []
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))

        docs = data.get("response", {}).get("docs", [])
        for doc in docs:
            title = (doc.get("title") or "").strip()
            if not title:
                continue

            authors = doc.get("author") or []
            if isinstance(authors, list):
                authors_str = ", ".join(authors[:4])
            else:
                authors_str = str(authors)

            year_raw = doc.get("publicationdateyear")
            try:
                year = int(year_raw) if year_raw else time.localtime().tm_year
            except Exception:
                year = time.localtime().tm_year

            abstract = doc.get("description") or "Bildungswissenschaftliche Fachpublikation indexiert in ERIC (Institute of Education Sciences)."
            journal = doc.get("source") or "ERIC Education Database"
            eric_id = doc.get("id") or ""
            pdf_url = doc.get("pdfurl") or ""

            results.append({
                "id": f"eric_{eric_id}",
                "title": title,
                "authors": authors_str or "Education Researcher",
                "abstract": abstract,
                "year": year,
                "journal": journal,
                "doi": doc.get("iescitation") or "",
                "arxiv_id": "",
                "pdf_url": pdf_url,
                "citation_count": 0,
                "source": "ERIC (IES)",
                "is_open_access": bool(pdf_url),
                "category": "Pädagogik & Schule",
            })
    except Exception:
        pass

    return results


def search_semantic_scholar(query: str, max_results: int = 25) -> List[Dict[str, Any]]:
    """Queries Semantic Scholar Graph API (Allen Institute for AI) for peer-reviewed papers with verified Open Access PDFs."""
    clean_q = re.sub(r'[^\w\s\-\.]', ' ', query).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search?"
        f"query={urllib.parse.quote(clean_q)}&limit={max_results}&"
        f"fields=title,authors,year,abstract,citationCount,venue,externalIds,openAccessPdf"
    )
    headers = {"User-Agent": USER_AGENT}
    results = []
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5.5, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        for item in data.get("data", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue

            authors = [a.get("name") for a in item.get("authors", []) if a.get("name")]
            authors_str = ", ".join(authors[:5]) if authors else "Wissenschaftler / Forscher"

            ext_ids = item.get("externalIds") or {}
            doi = ext_ids.get("DOI") or ""
            arxiv_id = ext_ids.get("ArXiv") or ""

            oa_pdf = item.get("openAccessPdf") or {}
            pdf_url = oa_pdf.get("url") or ""

            year = item.get("year") or time.localtime().tm_year
            cites = item.get("citationCount") or 0
            journal = item.get("venue") or "Semantic Scholar Index"

            abstract = clean_abstract_text(item.get("abstract") or "", title=title, year=year)

            results.append({
                "id": f"s2_{item.get('paperId', '')[:16]}",
                "title": title,
                "authors": authors_str,
                "abstract": abstract,
                "year": year,
                "journal": journal,
                "doi": doi,
                "arxiv_id": arxiv_id,
                "pdf_url": pdf_url,
                "citation_count": cites,
                "source": "Semantic Scholar (AI)",
                "is_open_access": bool(pdf_url),
            })
    except Exception:
        pass

    return results


def search_europe_pmc(query: str, max_results: int = 25) -> List[Dict[str, Any]]:
    """Queries Europe PMC for global multidisciplinary science, open access repositories, and journals."""
    clean_q = re.sub(r'[^\w\s\-\.]', ' ', query).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    url = (
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
        f"query={urllib.parse.quote(clean_q)}&pageSize={max_results}&format=json&resultType=core"
    )
    headers = {"User-Agent": USER_AGENT}
    results = []
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5.5, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        items = data.get("resultList", {}).get("result", [])
        for item in items:
            title = (item.get("title") or "").strip().rstrip(".")
            if not title:
                continue

            authors_str = item.get("authorString") or "Forschungsteam"
            doi = item.get("doi") or ""
            cites = item.get("citedByCount") or 0
            journal = item.get("journalTitle") or "Europe PMC Open Access"
            try:
                year = int(item.get("pubYear") or time.localtime().tm_year)
            except Exception:
                year = time.localtime().tm_year

            abstract = clean_abstract_text(item.get("abstractText") or "", title=title, year=year)

            is_oa = item.get("isOpenAccess") == "Y"
            pmcid = item.get("pmcid") or ""
            pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render" if (is_oa and pmcid) else ""

            results.append({
                "id": f"epmc_{item.get('id', '')}",
                "title": title,
                "authors": authors_str,
                "abstract": abstract,
                "year": year,
                "journal": journal,
                "doi": doi,
                "arxiv_id": "",
                "pdf_url": pdf_url,
                "citation_count": cites,
                "source": "Europe PMC",
                "is_open_access": is_oa,
            })
    except Exception:
        pass

    return results


def search_all_papers(query: str, max_results: int = 500) -> List[Dict[str, Any]]:
    """Aggregates and deduplicates academic papers concurrently across 7 premier scientific indices
    with expanded depth: Semantic Scholar (AI), Europe PMC, OpenAlex Global, Crossref, arXiv, peDOCS, and ERIC.
    """
    raw_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
        f_s2 = executor.submit(search_semantic_scholar, query, max_results=60)
        f_oa = executor.submit(search_openalex, query, max_results=80)
        f_epmc = executor.submit(search_europe_pmc, query, max_results=60)
        f_crossref = executor.submit(search_crossref, query, max_results=50)
        f_arxiv = executor.submit(search_arxiv, query, max_results=50)
        f_pedocs = executor.submit(search_pedocs, query, max_results=30)
        f_eric = executor.submit(search_eric, query, max_results=30)

        futures = [f_s2, f_oa, f_epmc, f_crossref, f_arxiv, f_pedocs, f_eric]
        for f in concurrent.futures.as_completed(futures):
            try:
                res = f.result()
                if res:
                    raw_results.extend(res)
            except Exception:
                pass

    combined = []
    seen_titles = set()

    for p in raw_results:
        p["title"] = html.unescape(p.get("title", "")).strip()
        p["authors"] = html.unescape(p.get("authors", "")).strip()
        p["journal"] = html.unescape(p.get("journal", "")).strip()
        p["abstract"] = clean_abstract_text(html.unescape(p.get("abstract", "")).strip(), p["title"], p.get("year"))

        norm_t = re.sub(r'[^\w]', '', p["title"].lower())
        if norm_t and len(norm_t) > 5 and norm_t not in seen_titles:
            seen_titles.add(norm_t)
            if not p.get("category"):
                p["category"] = infer_paper_category(p.get("title", ""), p.get("abstract", ""))
            combined.append(p)

    return combined[:max_results]


def _solve_anubis_pow(challenge_data: Dict[str, Any]) -> Tuple[str, int]:
    """Solves Anubis Proof-of-Work challenge in Python in <5ms."""
    import hashlib
    rules = challenge_data.get("rules", {})
    chal = challenge_data.get("challenge", {})
    random_data = chal.get("randomData", "")
    difficulty = int(rules.get("difficulty", 2))

    p = difficulty // 2
    u = (difficulty % 2 != 0)
    nonce = 0

    while True:
        candidate = f"{random_data}{nonce}".encode("utf-8")
        h = hashlib.sha256(candidate).digest()
        match = True
        for b in h[:p]:
            if b != 0:
                match = False
                break
        if match and u and (h[p] >> 4) != 0:
            match = False

        if match:
            return h.hex(), nonce
        nonce += 1


def resolve_candidate_pdf_urls(paper: Dict[str, Any]) -> List[str]:
    """Exhaustively collects all possible Open Access PDF mirrors for a paper across global academic indexes."""
    candidates: List[str] = []
    seen = set()

    def _add(u: Optional[str]) -> None:
        if not u:
            return
        clean = u.strip()
        if clean and clean.startswith("http") and clean not in seen:
            seen.add(clean)
            candidates.append(clean)

    # 1. Primary registered PDF URL
    _add(paper.get("pdf_url"))

    # 2. arXiv preprints
    arxiv_id = (paper.get("arxiv_id") or "").strip()
    if arxiv_id:
        _add(f"https://arxiv.org/pdf/{arxiv_id}.pdf")
        _add(f"https://export.arxiv.org/pdf/{arxiv_id}.pdf")

    # 3. Multi-location resolution via DOI
    doi = (paper.get("doi") or "").strip()
    clean_doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").replace("doi.org/", "").strip()
    if clean_doi:
        # 3.1 Wiley Online Library direct endpoints
        if "10.1002/" in clean_doi or "10.1111/" in clean_doi or "10.3322/" in clean_doi or "wiley" in str(paper.get("source", "")).lower():
            _add(f"https://onlinelibrary.wiley.com/doi/pdfdirect/{clean_doi}")
            _add(f"https://onlinelibrary.wiley.com/doi/pdf/{clean_doi}")
            _add(f"https://acsjournals.onlinelibrary.wiley.com/doi/pdfdirect/{clean_doi}")

        # 3.2 OpenAlex API - query work record for all repository & publisher OA locations
        try:
            oa_url = f"https://api.openalex.org/works/https://doi.org/{clean_doi}"
            req = urllib.request.Request(oa_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=3.5, context=_ssl_ctx) as resp:
                oa_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                _add(oa_data.get("open_access", {}).get("oa_url"))
                for loc in oa_data.get("locations", []):
                    if loc:
                        _add(loc.get("pdf_url"))
                        _add(loc.get("landing_page_url"))
        except Exception:
            pass

        # 3.3 Unpaywall API - inspect all registered Open Access locations
        try:
            upw_url = f"https://api.unpaywall.org/v2/{clean_doi}?email=scholar@campus-library.de"
            req = urllib.request.Request(upw_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=3.5, context=_ssl_ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                best = data.get("best_oa_location") or {}
                _add(best.get("url_for_pdf"))
                _add(best.get("url"))
                for loc in data.get("oa_locations", []):
                    if loc:
                        _add(loc.get("url_for_pdf"))
                        _add(loc.get("url"))
                        _add(loc.get("url_for_landing_page"))
        except Exception:
            pass

        # 3.4 Europe PMC API lookup
        try:
            epmc_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:{clean_doi}&format=json"
            req = urllib.request.Request(epmc_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=3.5, context=_ssl_ctx) as resp:
                epmc_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for itm in epmc_data.get("resultList", {}).get("result", []):
                    pmcid = itm.get("pmcid")
                    if pmcid:
                        _add(f"https://europepmc.org/articles/{pmcid}?pdf=render")
        except Exception:
            pass

        # 3.5 Semantic Scholar Graph API
        try:
            s2_url = f"https://api.semanticscholar.org/graph/v1/paper/{clean_doi}?fields=openAccessPdf"
            req = urllib.request.Request(s2_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=3.5, context=_ssl_ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                oa_pdf = data.get("openAccessPdf") or {}
                _add(oa_pdf.get("url"))
        except Exception:
            pass

        # 3.6 Direct publisher Open Access patterns
        if "10.1371/" in clean_doi:  # PLOS One / PLOS Biology
            _add(f"https://journals.plos.org/plosone/article/file?id={clean_doi}&type=printable")
        elif "10.1186/" in clean_doi or "10.1007/" in clean_doi:  # Springer / BioMed Central
            _add(f"https://link.springer.com/content/pdf/{clean_doi}.pdf")
        elif "10.1038/" in clean_doi:  # Nature
            _add(f"https://www.nature.com/articles/{clean_doi}.pdf")
        elif "10.1080/" in clean_doi:  # Taylor & Francis
            _add(f"https://www.tandfonline.com/doi/pdf/{clean_doi}")
        elif "10.3390/" in clean_doi:  # MDPI
            _add(f"https://www.mdpi.com/article/{clean_doi}/pdf")
        elif "10.3389/" in clean_doi:  # Frontiers
            _add(f"https://www.frontiersin.org/articles/{clean_doi}/pdf")
        elif "10.1101/" in clean_doi:  # BioRxiv / MedRxiv
            _add(f"https://www.biorxiv.org/content/{clean_doi}.full.pdf")

    return candidates


def resolve_alternative_pdf_url(doi: str) -> Optional[str]:
    """Backward-compatible helper returning the top alternative candidate URL."""
    res = resolve_candidate_pdf_urls({"doi": doi})
    return res[0] if res else None


def download_paper_pdf(paper: Dict[str, Any], progress_cb=None) -> Optional[str]:
    """Downloads an Open Access PDF file into 'Papers/' storage.
    Includes multi-mirror resolution, Chrome-impersonating bypass, Anubis PoW solving, and HTML meta extraction.
    """
    cat = paper.get("category", "")
    target_dir = get_papers_dir(cat)

    # Format clean filename: [Autor] - [Titel].pdf
    author = (paper.get("authors") or "Unbekannt").split(",")[0].strip()
    title = (paper.get("title") or paper.get("id", "paper")).strip()
    clean_base = re.sub(r'[\/\\:*?"<>|]', ' ', f"{author} - {title}").strip()
    clean_base = re.sub(r'\s+', ' ', clean_base)[:120]
    out_path = os.path.join(target_dir, f"{clean_base}.pdf")

    urls_to_try = resolve_candidate_pdf_urls(paper)
    if not urls_to_try:
        return None

    # Browser headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    # Initialize curl_cffi session for Cloudflare / TLS bot bypass
    cffi_session = None
    try:
        from curl_cffi import requests as cffi_requests
        cffi_session = cffi_requests.Session(impersonate="chrome124")
    except Exception:
        pass

    import requests
    req_session = requests.Session()

    def _fetch_page(target_url: str) -> Optional[Tuple[int, bytes, str, str]]:
        # 1. Primary: curl_cffi browser impersonation
        if cffi_session:
            try:
                r_cffi = cffi_session.get(target_url, timeout=18, allow_redirects=True)
                return (r_cffi.status_code, r_cffi.content, r_cffi.headers.get("content-type", ""), str(r_cffi.url))
            except Exception:
                pass
        # 2. Secondary: requests session
        try:
            r_req = req_session.get(target_url, headers=headers, timeout=18, allow_redirects=True)
            return (r_req.status_code, r_req.content, r_req.headers.get("content-type", ""), str(r_req.url))
        except Exception:
            pass
        return None

    def _try_fetch(target_url: str) -> Optional[bytes]:
        res = _fetch_page(target_url)
        if not res:
            return None

        status_code, content, content_type, final_url = res
        if status_code != 200:
            return None

        # 1. Direct PDF payload
        if content.startswith(b"%PDF") or b"%PDF" in content[:1024]:
            return content

        html_text = content.decode("utf-8", errors="ignore")

        # 2. Anubis Bot-Protection Solver (used by German library/university repositories)
        if "anubis_challenge" in html_text:
            m_chal = re.search(r'<script id="anubis_challenge" type="application/json">\s*({[\s\S]*?})\s*</script>', html_text)
            m_pref = re.search(r'<script id="anubis_base_prefix" type="application/json">\s*"([^"]*)"\s*</script>', html_text)
            if m_chal:
                chal_data = json.loads(m_chal.group(1))
                base_pref = m_pref.group(1) if m_pref else ""
                chal_id = chal_data.get("challenge", {}).get("id", "")
                t0 = time.time()
                found_hash, nonce = _solve_anubis_pow(chal_data)
                solve_ms = int((time.time() - t0) * 1000)
                pass_url = urllib.parse.urljoin(final_url, f"{base_pref}/.within.website/x/cmd/anubis/api/pass-challenge")
                pass_res = req_session.get(pass_url, params={
                    "id": chal_id,
                    "response": found_hash,
                    "nonce": nonce,
                    "redir": final_url,
                    "elapsedTime": solve_ms + 150
                }, headers=headers, timeout=18, allow_redirects=True)
                if pass_res.content.startswith(b"%PDF") or b"%PDF" in pass_res.content[:1024]:
                    return pass_res.content

        # 3. Resolve PDF links from HTML meta tags or anchors
        m_meta = re.search(r'<meta\s+name=["\'](?:citation_pdf_url|eprints\.document_url)["\']\s+content=["\']([^"\']+)["\']', html_text, re.I)
        m_link = re.search(r'<link\s+rel=["\']alternate["\']\s+type=["\']application/pdf["\']\s+href=["\']([^"\']+)["\']', html_text, re.I)
        m_ojs = re.search(r'<a\s+[^>]*href=["\']([^"\']+/article/download/[^"\']+)["\']', html_text, re.I)
        m_bitstream = re.search(r'<a\s+[^>]*href=["\']([^"\']+(?:bitstream|\.pdf)[^"\']*)["\']', html_text, re.I)

        candidate_rel = None
        if m_meta:
            candidate_rel = m_meta.group(1).strip()
        elif m_link:
            candidate_rel = m_link.group(1).strip()
        elif m_ojs:
            candidate_rel = m_ojs.group(1).strip()
        elif m_bitstream:
            candidate_rel = m_bitstream.group(1).strip()

        if candidate_rel:
            sec_url = urllib.parse.urljoin(final_url, candidate_rel)
            sec_res = _fetch_page(sec_url)
            if sec_res and sec_res[0] == 200:
                sec_content = sec_res[1]
                if sec_content.startswith(b"%PDF") or b"%PDF" in sec_content[:1024]:
                    return sec_content

        return None

    for candidate_url in urls_to_try:
        content = _try_fetch(candidate_url)
        if content and len(content) > 1000 and (content.startswith(b"%PDF") or b"%PDF" in content[:1024]):
            with open(out_path, "wb") as f:
                f.write(content)
            return out_path

    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception:
            pass

    return None


def build_institution_url(paper: Dict[str, Any], ezproxy_prefix: str) -> str:
    """Constructs a university-licensed EZProxy login URL for paywalled academic papers."""
    doi = (paper.get("doi") or "").strip()
    if doi:
        clean_doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").replace("doi.org/", "").strip()
        target = f"https://doi.org/{clean_doi}"
    else:
        clean_t = urllib.parse.quote(paper.get("title", ""))
        target = f"https://scholar.google.com/scholar?q={clean_t}"

    if not ezproxy_prefix:
        return target

    return f"{ezproxy_prefix}{target}"


def generate_paper_bibtex(paper: Dict[str, Any]) -> str:
    """Generates standard BibTeX entry for LaTeX citations."""
    authors = paper.get("authors", "Anonymous")
    first_author = re.sub(r'[^a-zA-Z]', '', authors.split(",")[0].split()[-1] if authors.split() else "author")
    year = paper.get("year") or 2026
    cite_key = f"{first_author.lower()}{year}"

    lines = [
        f"@article{{{cite_key},",
        f"  title = {{{paper.get('title', '')}}},",
        f"  author = {{{authors}}},",
        f"  year = {{{year}}},",
    ]
    if paper.get("journal"):
        lines.append(f"  journal = {{{paper.get('journal')}}},")
    if paper.get("doi"):
        lines.append(f"  doi = {{{paper.get('doi')}}},")
    if paper.get("arxiv_id"):
        lines.append(f"  eprint = {{{paper.get('arxiv_id')}}},")
        lines.append("  archivePrefix = {arXiv},")
    lines.append("}")

    return "\n".join(lines)


def _extract_author_initials(first_names: str) -> str:
    """Extracts initials from first names, preserving hyphens for compound names (e.g. Hans-Peter -> H.-P.)."""
    if not first_names:
        return ""
    initial_parts = []
    for token in first_names.split():
        if "-" in token:
            sub = token.split("-")
            sub_inits = "-".join(f"{s[0].upper()}." for s in sub if s)
            initial_parts.append(sub_inits)
        elif token:
            clean = token.rstrip(".")
            initial_parts.append(f"{clean[0].upper()}.")
    return " ".join(initial_parts)


def parse_single_author(name: str) -> Tuple[str, str]:
    """Parses a single author name into (surname, initials). Handles prefixes, NLM format, and institutional authors."""
    name = name.strip().rstrip(".")
    if not name:
        return "", ""

    # Editor annotations or institutional authors remain as is
    if re.search(r'\((hrsg|ed|eds)\.?\)', name, re.I) or name.endswith(("(Hrsg.)", "(Ed.)", "(Eds.)")):
        return name, ""

    institutional_keywords = {"group", "team", "consortium", "organization", "organisation", "institute", "collaboration", "ai", "openai", "google", "meta"}
    if any(k in name.lower().split() for k in institutional_keywords) and len(name.split()) <= 4:
        return name, ""

    # Check if format is "Surname, Firstname"
    if "," in name:
        parts = [p.strip() for p in name.split(",") if p.strip()]
        surname = parts[0]
        first_names = " ".join(parts[1:]) if len(parts) > 1 else ""
        initials = _extract_author_initials(first_names)
        return surname, initials

    tokens = name.split()
    if len(tokens) == 1:
        return tokens[0], ""

    # Check for NLM / PubMed / Europe PMC format: "Surname Initial(s)" (e.g. "Shehadeh F", "Mylona EK")
    if len(tokens) >= 2 and re.match(r'^[A-Z]{1,3}$', tokens[-1]):
        surname = " ".join(tokens[:-1])
        initials_token = tokens[-1]
        formatted_inits = " ".join(f"{ch}." for ch in initials_token)
        return surname, formatted_inits

    # Handle European surname prefixes (von, van, de, der, den, du, la, le, zu)
    prefixes = {"von", "van", "de", "der", "den", "du", "la", "le", "zu", "zur"}
    split_idx = len(tokens) - 1
    for i in range(len(tokens) - 2, 0, -1):
        if tokens[i].lower() in prefixes:
            split_idx = i
        else:
            break

    first_names = " ".join(tokens[:split_idx])
    surname = " ".join(tokens[split_idx:])
    initials = _extract_author_initials(first_names)
    return surname, initials


def parse_authors_to_apa7(authors_input: Any) -> Tuple[str, str]:
    """Parses authors into (APA 7 reference list string, APA 7 in-text citation author string).
    Complies strictly with Scribbr APA 7:
    - 1 author: Surname, Initial.
    - 2 authors: Surname, Initial., & Surname, Initial.
    - Up to 20 authors: All authors listed with ', & ' before last author.
    - 21+ authors: First 19 authors, then '... ', then last author (no &).
    - In-Text: 1 author -> (Surname); 2 authors -> (Surname1 & Surname2); 3+ authors -> (Surname1 et al.)
    """
    raw_list: List[str] = []

    if isinstance(authors_input, list):
        for item in authors_input:
            if isinstance(item, str):
                if item.strip():
                    raw_list.append(item.strip())
            elif isinstance(item, dict):
                n = item.get("name") or item.get("display_name")
                if n:
                    raw_list.append(str(n).strip())
    elif isinstance(authors_input, str):
        clean = authors_input.strip()
        if not clean:
            return "Unbekannte Autorenschaft", "o. A."

        if " and " in clean:
            raw_list = [p.strip() for p in clean.split(" and ") if p.strip()]
        elif ";" in clean:
            raw_list = [p.strip() for p in clean.split(";") if p.strip()]
        else:
            comma_parts = [p.strip() for p in clean.split(",") if p.strip()]
            if len(comma_parts) > 1:
                # Disambiguate "Last, First, Last, First" vs "First Last, First Last"
                looks_like_pairs = True
                if len(comma_parts) % 2 == 0:
                    for i in range(0, len(comma_parts), 2):
                        words_s = comma_parts[i].split()
                        words_f = comma_parts[i+1].split()
                        if len(words_s) >= 2 and words_s[0].lower() not in {"von", "van", "de", "der", "du"}:
                            looks_like_pairs = False
                            break
                        if len(words_f) >= 3:
                            looks_like_pairs = False
                            break
                else:
                    looks_like_pairs = False

                if looks_like_pairs:
                    raw_list = [f"{comma_parts[i]}, {comma_parts[i+1]}" for i in range(0, len(comma_parts), 2)]
                else:
                    raw_list = comma_parts
            else:
                raw_list = [clean]

    formatted_authors = []
    surnames = []

    for author_str in raw_list:
        surname, initials = parse_single_author(author_str)
        if not surname:
            continue
        surnames.append(surname)
        if initials:
            formatted_authors.append(f"{surname}, {initials}")
        else:
            formatted_authors.append(surname)

    if not formatted_authors:
        return "Unbekannte Autorenschaft", "o. A."

    n_auth = len(formatted_authors)
    if n_auth == 1:
        ref_str = formatted_authors[0]
    elif n_auth == 2:
        ref_str = f"{formatted_authors[0]}, & {formatted_authors[1]}"
    elif n_auth <= 20:
        ref_str = ", ".join(formatted_authors[:-1]) + f", & {formatted_authors[-1]}"
    else:
        ref_str = ", ".join(formatted_authors[:19]) + f", ... {formatted_authors[-1]}"

    if n_auth == 1:
        intext_authors = surnames[0]
    elif n_auth == 2:
        intext_authors = f"{surnames[0]} & {surnames[1]}"
    else:
        intext_authors = f"{surnames[0]} et al."

    return ref_str, intext_authors


def clean_academic_journal_name(journal: str) -> str:
    """Cleans duplicated slash names or catalog artifacts from academic journal titles."""
    j = (journal or "").strip()
    if "/" in j:
        parts = [p.strip() for p in j.split("/") if p.strip()]
        if len(parts) >= 2 and parts[0].lower() == parts[1].lower():
            j = parts[0]
        elif len(parts) >= 2:
            j = parts[0]
    j = re.sub(r'[\.\,\;]+$', '', j).strip()
    return j


def generate_paper_apa7(paper: Dict[str, Any]) -> str:
    """Generates standard APA 7th Edition citation according to official Scribbr & APA Manual standards.
    Guidelines for Scientific Journals:
    1. Authors: 'Surname, Initials' (up to 20 authors fully listed with '&', 21+ with '...').
    2. Year: in parentheses '(Year).'
    3. Article Title: normal font, followed by period.
    4. Journal Name, Volume(Issue), Pages.
       - No space before opening parenthesis of issue.
       - Volume and Journal are emphasized; Pages separated with en-dash '–'.
       - If electronic article with article number: ', Artikel e12345.'
    5. DOI / URL:
       - Direct https://doi.org/... link without trailing dot.
       - No 'doi:' prefix, no 'Abgerufen von' prefix, no place of publication.
    """
    authors_input = paper.get("authors_list") or paper.get("authors")
    apa_authors, _ = parse_authors_to_apa7(authors_input)

    raw_year = str(paper.get("year") or "").strip()
    m_year = re.search(r'\b(19\d\d|20\d\d)\b', raw_year)
    year = m_year.group(1) if m_year else (raw_year if (raw_year and raw_year != "0") else "o. D.")

    title = (paper.get("title") or "Ohne Titel").strip()
    if title.endswith((".", "?", "!")):
        title_part = title
    else:
        title_part = f"{title}."

    journal = clean_academic_journal_name(paper.get("journal") or "")
    volume = str(paper.get("volume") or "").strip()
    issue = str(paper.get("issue") or "").strip()
    pages_raw = str(paper.get("pages") or "").strip().replace("-", "–")
    if "–" in pages_raw:
        sub_p = [s.strip() for s in pages_raw.split("–") if s.strip()]
        if len(sub_p) == 2 and sub_p[0] == sub_p[1]:
            pages_raw = sub_p[0]

    article_number = str(paper.get("article_number") or "").strip()

    # Detect article number if stored in pages
    if pages_raw and not article_number:
        if re.match(r'^[eE]\d+', pages_raw) or (pages_raw.isdigit() and len(pages_raw) >= 6):
            article_number = pages_raw
            pages_raw = ""

    journal_part = ""
    if journal:
        journal_part = journal
        vol_issue = ""
        if volume and issue:
            vol_issue = f"{volume}({issue})"
        elif volume:
            vol_issue = f"{volume}"
        elif issue:
            vol_issue = f"({issue})"

        if vol_issue:
            journal_part += f", {vol_issue}"

        if pages_raw:
            journal_part += f", {pages_raw}"
        elif article_number:
            journal_part += f", Artikel {article_number}"

        journal_part += "."

    doi = (paper.get("doi") or "").strip()
    arxiv_id = (paper.get("arxiv_id") or "").strip()
    url = (paper.get("pdf_url") or paper.get("url") or "").strip()

    doi_part = ""
    if doi:
        clean_doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").replace("doi.org/", "").strip()
        doi_part = f"https://doi.org/{clean_doi}"
    elif arxiv_id:
        clean_arxiv = arxiv_id.replace("arXiv:", "").strip()
        doi_part = f"https://arxiv.org/abs/{clean_arxiv}"
    elif url and ("http://" in url or "https://" in url):
        doi_part = url

    parts = [f"{apa_authors} ({year}).", title_part]
    if journal_part:
        parts.append(journal_part)
    if doi_part:
        parts.append(doi_part)

    return " ".join(parts).strip()


def generate_paper_apa7_intext(paper: Dict[str, Any]) -> str:
    """Generates standard APA 7th Edition in-text citation (Kurzverweis im Fließtext).
    Rule:
    - 1 author -> (Surname, Year)
    - 2 authors -> (Surname1 & Surname2, Year)
    - 3+ authors -> (Surname1 et al., Year) from the very first mention.
    """
    authors_input = paper.get("authors_list") or paper.get("authors")
    _, intext_authors = parse_authors_to_apa7(authors_input)
    raw_year = str(paper.get("year") or "").strip()
    m_year = re.search(r'\b(19\d\d|20\d\d)\b', raw_year)
    year = m_year.group(1) if m_year else (raw_year if (raw_year and raw_year != "0") else "o. D.")
    return f"({intext_authors}, {year})"


def find_similar_papers(paper: Dict[str, Any], limit: int = 15) -> List[Dict[str, Any]]:
    """Discovers semantically related papers and citation graph recommendations
    using Semantic Scholar Recommendations API with an intelligent academic query fallback.
    """
    results: List[Dict[str, Any]] = []
    doi = (paper.get("doi") or "").replace("https://doi.org/", "").strip()
    arxiv_id = (paper.get("arxiv_id") or "").strip()
    title = (paper.get("title") or "").strip()

    # Strategy 1: Semantic Scholar Recommendations Graph API
    target_id = None
    if doi:
        target_id = f"DOI:{doi}"
    elif arxiv_id:
        target_id = f"ARXIV:{arxiv_id}"
    elif paper.get("id", "").startswith("s2_"):
        target_id = paper.get("id").replace("s2_", "")

    if target_id:
        try:
            url = (
                f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{urllib.parse.quote(target_id)}?"
                f"limit={limit}&fields=title,authors,year,abstract,citationCount,venue,externalIds,openAccessPdf"
            )
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=5.0, context=_ssl_ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for item in data.get("recommendedPapers", []):
                    t = (item.get("title") or "").strip()
                    if not t or (title and t.lower() == title.lower()):
                        continue

                    authors = [a.get("name") for a in item.get("authors", []) if a.get("name")]
                    authors_str = ", ".join(authors[:5]) if authors else "Wissenschaftler / Forscher"

                    ext = item.get("externalIds") or {}
                    p_doi = ext.get("DOI") or ""
                    p_arxiv = ext.get("ArXiv") or ""
                    oa = item.get("openAccessPdf") or {}
                    pdf_url = oa.get("url") or ""
                    y = item.get("year") or ""
                    cites = item.get("citationCount") or 0
                    journal = item.get("venue") or "Forschungsnetzwerk-Empfehlung"
                    abstract = clean_abstract_text(item.get("abstract") or "", title=t, year=y)

                    results.append({
                        "id": f"rec_{item.get('paperId', '')[:16]}",
                        "title": t,
                        "authors": authors_str,
                        "abstract": abstract,
                        "year": y,
                        "journal": journal,
                        "doi": p_doi,
                        "arxiv_id": p_arxiv,
                        "pdf_url": pdf_url,
                        "citation_count": cites,
                        "source": "Zitations-Radar (AI)",
                        "is_open_access": bool(pdf_url),
                        "category": paper.get("category") or "",
                    })
        except Exception:
            pass

    # Strategy 2: High-relevance Keyword Fallback if API returned few or no results
    if len(results) < 4 and title:
        stopwords = {
            "eine", "einer", "einem", "eines", "über", "unter", "durch", "studie", "analyse",
            "untersuchung", "beitrag", "wirkung", "einfluss", "the", "and", "for", "with",
            "study", "analysis", "from", "into", "their", "this", "that", "approach"
        }
        words = [w for w in re.findall(r'[a-zA-ZäöüÄÖÜß]{4,}', title) if w.lower() not in stopwords]
        query_terms = " ".join(words[:4]) if words else title[:40]
        try:
            fallback_res = search_all_papers(query_terms, max_results=limit)
            for fb in fallback_res:
                if title and fb.get("title", "").strip().lower() == title.lower():
                    continue
                if not any(r.get("title", "").lower() == fb.get("title", "").lower() for r in results):
                    results.append(fb)
                if len(results) >= limit:
                    break
        except Exception:
            pass

    return results[:limit]
