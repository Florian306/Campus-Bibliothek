"""Unified Multi-Tier Pipeline Controller with Early-Exit Cascade and Persistent Cache.
Executes: 
Stufe -1: Local SQLite Hash Cache (0ms)
Stufe 0: DOI (Crossref) & ISBN (DNB / Google Books / OpenLibrary) (~100ms)
Stufe 1: Local Memory & Book Series Patterns (<1ms)
Stufe 2: TOC & Deterministic Faculty Heuristics (~5ms)
Stufe 3: Local LLM (Ollama) / Cloud VLM (Gemini) (ambiguous edge cases)
Stufe 4: Sanity-Guard & Faculty Conflict Veto
"""

import re
from typing import List, Optional, Tuple
from core.models import BookAnalysis
from core.cache_manager import get_cached_file, save_cached_file
from core.memory import match_memory_rule
from ai.doi_resolver import resolve_doi_catalog
from ai.isbn_lookup import resolve_isbn_catalog
from ai.classifier import classify_textbook
from ai.sanity import perform_sanity_check
from ai.validator import sanitize_filename, sanitize_folder_name
from ai.ollama_client import analyze_with_ollama
from ai.gemini_client import analyze_with_gemini


def clean_filename_to_title(clean_stem: str) -> Tuple[str, str]:
    """Decomposes a filename stem into clean (author, title) by stripping
    scanner artifacts, publisher suffixes, expanding abbreviations, and parsing series.
    """
    author = "Unbekannt"
    title = clean_stem.replace('\x00', '').strip()

    # High-value textbook & series overrides
    if 'kugler' in title.lower() or 'menschliche k' in title.lower() or 'menschliche-krper' in title.lower():
        if '2' in title:
            return "Peter Kugler", "Der menschliche Körper - Anatomie, Physiologie, Pathologie (Band 2)"
        elif '3' in title:
            return "Peter Kugler", "Der menschliche Körper - Anatomie, Physiologie, Pathologie (Band 3)"
        return "Peter Kugler", "Der menschliche Körper - Anatomie, Physiologie, Pathologie"

    if 'oceanofpdf' in title.lower() and 'mensch' in title.lower():
        return "Renate Huch", "Mensch Körper Krankheit"

    # Remove site watermarks & leading scanner / archive IDs
    title = re.sub(r'^(?:oceanofpdf\.com[-_]|pub_\d+_|\d+_\d+[-_]|\d+[-_\s]+)', '', title, flags=re.IGNORECASE).strip()

    # Detect VEJ series: "Band X ..." -> "VEJ Band X: ..."
    vej_match = re.match(r'^Band\s+(\d+)\s+(?:(Polen|Sowjetunion|West-|Besetztes|Slowakei|Ungarn|Deutsches Reich).*)$', title, re.IGNORECASE)
    if vej_match or "vej" in title.lower():
        b_num = vej_match.group(1) if vej_match else ""
        sub = title[vej_match.start(2):].strip(" -_.:") if vej_match and vej_match.group(2) else title
        title = f"VEJ Band {b_num}: {sub}" if b_num else f"VEJ: {title}"
        author = "Institut für Zeitgeschichte (Hg.)"
        return author, title

    # Harry Potter series
    hp_match = re.match(r'^(?:1_)?(?:Joanne[-.\s]+K\.[-.\s]+Rowling|J\.[-.\s]+K\.[-.\s]+Rowling)[-_\s]+(.+)$', title, re.IGNORECASE)
    if hp_match:
        author = "J. K. Rowling"
        title = hp_match.group(1)
    hp_sub = re.search(r'Harry[-_ ]+Potter.*?(Philosopher.*|Chamber.*|Prisoner.*|Goblet.*|Order.*|Half[- ]Blood.*|Deathly.*)', title, re.IGNORECASE)
    if hp_sub:
        sub = hp_sub.group(1).replace('-', ' ').replace('_', ' ').strip(" ._")
        return "J. K. Rowling", f"Harry Potter and the {sub}"

    # English for Everyone series
    if 'english-for-everyone' in title.lower() or 'english for everyone' in title.lower():
        t_clean = re.sub(r'[-_.]+', ' ', title)
        m_efe = re.search(r'Level\s*(\d+)\s*(Beginner|Intermediate|Advanced)\s*(Course|Practice)\s*Book', t_clean, re.IGNORECASE)
        if m_efe:
            return "DK Publishing", f"English for Everyone: Level {m_efe.group(1)} {m_efe.group(2).capitalize()} - {m_efe.group(3).capitalize()} Book"
        elif 'Business' in t_clean:
            m_biz = re.search(r'Business\s*English\s*(?:Course\s*Book\s*Level\s*(\d+)|Level\s*(\d+)\s*Course\s*Book|(\d+)\s*Course\s*Book)', t_clean, re.IGNORECASE)
            lvl = m_biz.group(1) or m_biz.group(2) or m_biz.group(3) if m_biz else "1"
            return "DK Publishing", f"English for Everyone: Business English Level {lvl} - Course Book"
        return "DK Publishing", title.replace('_', ' ').replace('-', ' ').strip()

    # School physics / chemistry textbooks
    if 'schuljahr' in title.lower() or 'schlerbuch' in title.lower():
        t = title.replace('-', ' ').replace('schlerbuch', 'Schülerbuch').replace('baden wrttemberg', 'Baden-Württemberg').replace('naturphnomene', 'Naturphänomene')
        t = re.sub(r'\bphysik\b', 'Physik', t, flags=re.IGNORECASE)
        t = re.sub(r'\b(\d+)\s+(\d+)\s+schuljahr\b', r'\1./\2. Schuljahr', t, flags=re.IGNORECASE)
        t = re.sub(r'\b(\d+)\s+schuljahr\b', r'\1. Schuljahr', t, flags=re.IGNORECASE)
        words = [w.capitalize() if w.lower() not in ('und', 'in', 'von', 'der', 'die', 'das', 'für') else w.lower() for w in t.split()]
        return "Unbekannt", ' '.join(words)

    if title.strip() in ('Physik 7 8', 'Physik 7_8', 'Physik 7-8'):
        return "Unbekannt", 'Physik 7./8. Schuljahr'
    if title.strip() in ('Physik 9 10', 'Physik 9_10', 'Physik 9-10'):
        return "Unbekannt", 'Physik 9./10. Schuljahr'
    if title.strip() in ('Chemie 11 12', 'Chemie 11_12', 'Chemie 11-12'):
        return "Unbekannt", 'Chemie 11./12. Schuljahr'

    # Remove trailing metadata tags (e.g. "-2016-184p", "_2_Aufl.indd")
    title = re.sub(r'[-_.](?:19\d\d|20\d\d)[-_.]\d+p?$', '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r'[-_.]\d+p$', '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r'\.(?:indd|indb|qxd|doc|docx|pdf)$', '', title, flags=re.IGNORECASE).strip()

    # Remove trailing publisher signatures from filenames
    title = re.sub(r'(?:\s+[-_]\s*|\s+)(?:hanser|springer(\s+spektrum)?|de gruyter|c\.h\.beck|pearson|wiley|utb|oldenbourg)$', '', title, flags=re.IGNORECASE).strip()

    # Expand common abbreviations
    title = re.sub(r'\bdt\.\b', 'Deutsche', title)
    title = re.sub(r'\bBnd\s*(\d+)', r'Band \1', title, flags=re.IGNORECASE)
    title = re.sub(r'\bBd\.\s*(\d+)', r'Band \1', title, flags=re.IGNORECASE)

    # Check "Author - Title" pattern
    if " - " in title:
        parts = title.split(" - ", 1)
        left = parts[0].strip()
        right = parts[1].strip()
        non_authors = ["band", "teil", "kapitel", "lehrbuch", "einführung", "grundlagen", "basiswissen", "vorkurs", "statistik", "mathe", "arbeitsbuch", "wbg", "thieme"]
        words = left.split()
        if 1 <= len(words) <= 4 and not any(w.lower() in non_authors for w in words) and not re.search(r'\d', left):
            author = left
            title = right
    elif "_" in title:
        title = re.sub(r'_+(\d+)_+', r' - Teil \1: ', title)
        title = re.sub(r'_+(Band\s*\d+)', r', \1', title, flags=re.IGNORECASE)
        title = title.replace("_", " ").strip()

    title = re.sub(r'\s+', ' ', title).strip()
    return author, title


def extract_fallback_author_title(clean_stem: str, pdf_text: str = "") -> Tuple[str, str]:
    """Extracts author and title cleanly from metadata text or filename pattern."""
    fn_author, fn_title = clean_filename_to_title(clean_stem)
    author = fn_author
    title = fn_title

    # 1. Try metadata from PDF header
    if pdf_text and "--- METADATEN ---" in pdf_text:
        m_auth = re.search(r'^Autor:\s*(.+)$', pdf_text, re.MULTILINE)
        if m_auth:
            raw_auth = m_auth.group(1).replace('\x00', '').strip()
            raw_auth = re.sub(r'\[?\s*(?:Illustrator(?:in)?|Grafik(?:er)?|Redaktion|Red\.|Hrsg\.|Herausgeber|Fotograf(?:in)?|Bearb\.|Bearbeiter|Mitarb\.|Mitarbeiter)\s*\]?', '', raw_auth, flags=re.IGNORECASE)
            raw_auth = raw_auth.replace('[', '').replace(']', '').strip()
            junk_users = ["alin.cason", "fk", "admin", "administrator", "user", "root", "unbekannt", "indesign", "sjoerg"]
            if raw_auth.lower() not in junk_users and len(raw_auth) >= 3 and not raw_auth.isdigit():
                if "," in raw_auth and len(raw_auth.split(",")) == 2:
                    parts = [p.strip() for p in raw_auth.split(",")]
                    author = f"{parts[1]} {parts[0]}"
                else:
                    author = raw_auth

        m_tit = re.search(r'^Titel:\s*(.+)$', pdf_text, re.MULTILINE)
        if m_tit:
            raw_tit = m_tit.group(1).replace('\x00', '').strip()
            is_bad_tit = (
                len(raw_tit) < 3
                or bool(re.search(r'\.(?:indd|indb|qxd|doc|docx|pdf)$', raw_tit, re.IGNORECASE))
                or bool(re.match(r'^(?:97[89]\d{10}|\d{9}[\dX]|\d{10,13})$', raw_tit))
                or bool(re.match(r'^(?:\+?\d+_|pub_|cr_|mb_|book_)[0-9a-z_]+', raw_tit, re.IGNORECASE))
                or any(j in raw_tit.lower() for j in ["titelei", "cover", "frontmatter", "unbenannt", "untitled", "microsoft word"])
            )
            if not is_bad_tit:
                clean_t = re.sub(r'^\[.*?\]\s*;\s*', '', raw_tit).strip()
                if len(clean_t) >= 4:
                    title = clean_t

    return author, title


def process_book_pipeline(
    original_path: str,
    original_filename: str,
    pdf_text: Optional[str] = None,
    existing_folders: Optional[List[str]] = None,
    provider: str = "ollama",
    ollama_model: str = "qwen2.5vl:latest",
    api_key: str = "",
    host: str = "http://localhost:11434",
) -> BookAnalysis:
    """Orchestrates the multi-tier classification pipeline with lazy PDF extraction and cloud-stream protection.
    
    Zero-Download Guarantee:
    Reads only metadata and the first few pages (<50KB) via PyMuPDF.
    Resolves official DNB/Google Books catalog metadata (ISBN/DOI) for 100% confidence.
    """
    raw_stem = re.sub(r'\.pdf$', '', original_filename, flags=re.IGNORECASE).strip()
    clean_stem = re.sub(r'^[0-9_\-\.\s]+', '', raw_stem) or raw_stem

    # -------------------------------------------------------------
    # STUFE -1: Lokaler SQLite Hash-Cache (0.0001s Latenz, 0 Downloads)
    # -------------------------------------------------------------
    cached = get_cached_file(original_path)
    if cached and cached.confidence > 65 and cached.kategorie != "Sonstiges":
        return cached

    # -------------------------------------------------------------
    # STUFE 0: Gelerntes Gedächtnis (rules_memory.json)
    # -------------------------------------------------------------
    memory_match = match_memory_rule(original_filename, "")
    if memory_match:
        mem_cat, mem_reason = memory_match
        fb_author, fb_title = extract_fallback_author_title(clean_stem, "")
        final_cat, conf, needs_rev, final_reason = perform_sanity_check(
            category=mem_cat,
            original_filename=original_filename,
            title=fb_title,
            pdf_text="",
            confidence=98,
            audit_trail=f"[Stufe 0 - Memory] {mem_reason}",
            existing_folders=existing_folders,
        )
        new_name = f"{fb_author} - {fb_title}.pdf" if fb_author and fb_author != "Unbekannt" else f"{fb_title}.pdf"
        result = BookAnalysis(
            kategorie=sanitize_folder_name(final_cat),
            autor=fb_author,
            titel=fb_title,
            neuer_dateiname=sanitize_filename(new_name),
            confidence=conf,
            needs_review=needs_rev,
            review_reason=final_reason,
        )
        save_cached_file(original_path, result)
        return result

    # -------------------------------------------------------------
    # STUFE 1: Smarte Cloud-sichere PDF-Voransicht (PyMuPDF max 5 Seiten)
    # -------------------------------------------------------------
    if pdf_text is None:
        from ai.pdf_extractor import extract_pdf_preview_text
        pdf_text = extract_pdf_preview_text(original_path) or ""

    # Filename may carry the ISBN (e.g. "9783662...pdf")
    fname_isbn_hint = f"ISBN {re.sub(r'[_]+', ' ', raw_stem)}"

    # -------------------------------------------------------------
    # STUFE 2: Offizielle Verlags-Identifikatoren (DOI & ISBN)
    # -------------------------------------------------------------
    # 2a: DOI via Crossref API (Springer, Wiley, Elsevier etc.)
    if pdf_text:
        doi_result = resolve_doi_catalog(pdf_text)
        if doi_result:
            cat, author, title, reason = doi_result
            final_cat, conf, needs_rev, final_reason = perform_sanity_check(
                category=cat,
                original_filename=original_filename,
                title=title,
                pdf_text=pdf_text,
                confidence=100,
                audit_trail=f"[Stufe 2 - DOI] {reason}",
                existing_folders=existing_folders,
            )
            new_name = f"{author} - {title}.pdf" if author and author != "Unbekannt" else f"{title}.pdf"
            result = BookAnalysis(
                kategorie=sanitize_folder_name(final_cat),
                autor=author,
                titel=title,
                neuer_dateiname=sanitize_filename(new_name),
                confidence=conf,
                needs_review=needs_rev,
                review_reason=final_reason,
            )
            save_cached_file(original_path, result)
            return result

    # 2b: ISBN via DNB & Google Books (filename first, then PDF text)
    isbn_result = resolve_isbn_catalog(f"{fname_isbn_hint}\n{pdf_text or ''}", existing_folders=existing_folders)
    if isbn_result:
        cat, author, title, reason = isbn_result
        if not cat:
            # Catalog title known, faculty unknown -> classify via title
            cat, _c, _e = classify_textbook(
                filename=f"{title}.pdf",
                text=f"{title}\n{pdf_text or ''}",
                existing_folders=existing_folders,
            )
            reason = f"{reason} | Heuristik: {_e}"
        final_cat, conf, needs_rev, final_reason = perform_sanity_check(
            category=cat,
            original_filename=original_filename,
            title=title,
            pdf_text=pdf_text,
            confidence=100 if isbn_result[0] else 85,
            audit_trail=f"[Stufe 2 - ISBN] {reason}",
            existing_folders=existing_folders,
        )
        new_name = f"{author} - {title}.pdf" if author and author != "Unbekannt" else f"{title}.pdf"
        result = BookAnalysis(
            kategorie=sanitize_folder_name(final_cat),
            autor=author,
            titel=title,
            neuer_dateiname=sanitize_filename(new_name),
            confidence=conf,
            needs_review=needs_rev,
            review_reason=final_reason,
        )
        save_cached_file(original_path, result)
        return result

    # -------------------------------------------------------------
    # STUFE 3: Volltext-, Metadaten- & Fakultäts-Klassifikator
    # -------------------------------------------------------------
    fb_author, fb_title = extract_fallback_author_title(clean_stem, pdf_text)
    det_cat, det_conf, det_expl = classify_textbook(
        filename=original_filename,
        text=pdf_text or "",
        existing_folders=existing_folders,
    )
    if det_conf >= 70 and det_cat != "Sonstiges":
        final_cat, conf, needs_rev, final_reason = perform_sanity_check(
            category=det_cat,
            original_filename=original_filename,
            title=fb_title,
            pdf_text=pdf_text or "",
            confidence=det_conf,
            audit_trail=f"[Stufe 3 - Heuristik] {det_expl}",
            existing_folders=existing_folders,
        )
        new_name = f"{fb_author} - {fb_title}.pdf" if fb_author and fb_author != "Unbekannt" else f"{fb_title}.pdf"
        result = BookAnalysis(
            kategorie=sanitize_folder_name(final_cat),
            autor=fb_author,
            titel=fb_title,
            neuer_dateiname=sanitize_filename(new_name),
            confidence=conf,
            needs_review=conf < 85,
            review_reason=final_reason,
        )
        save_cached_file(original_path, result)
        return result

    # -------------------------------------------------------------
    # STUFE 3: LLM / VLM (Ollama Qwen-VL oder Gemini Flash)
    # -------------------------------------------------------------
    # Only triggered for genuinely ambiguous books
    try:
        if provider == "gemini" and api_key:
            analysis = analyze_with_gemini(
                api_key=api_key,
                original_filename=original_filename,
                pdf_text=pdf_text,
                existing_folders=existing_folders,
            )
            audit_prefix = "[Stufe 3] Gemini 2.5 Flash KI"
        else:
            analysis = analyze_with_ollama(
                model_name=ollama_model,
                original_filename=original_filename,
                pdf_text=pdf_text,
                existing_folders=existing_folders,
                host=host,
            )
            audit_prefix = f"[Stufe 3] Ollama ({ollama_model})"

        # -------------------------------------------------------------
        # STUFE 4: Sanity-Check & Plausibilitäts-Matrix
        # -------------------------------------------------------------
        final_cat, conf, needs_rev, final_reason = perform_sanity_check(
            category=analysis.kategorie,
            original_filename=original_filename,
            title=analysis.titel,
            pdf_text=pdf_text,
            confidence=analysis.confidence,
            audit_trail=f"{audit_prefix} | {analysis.review_reason or 'Plausibel'}",
            existing_folders=existing_folders,
        )

        analysis.kategorie = sanitize_folder_name(final_cat)
        analysis.confidence = conf
        analysis.needs_review = needs_rev
        analysis.review_reason = final_reason
        save_cached_file(original_path, analysis)
        return analysis

    except Exception as e:
        final_cat, conf, needs_rev, final_reason = perform_sanity_check(
            category=det_cat,
            original_filename=original_filename,
            title=clean_stem,
            pdf_text=pdf_text,
            confidence=min(det_conf, 70),
            audit_trail=f"[Fallback] KI nicht erreichbar ({str(e)}), Heuristik angewendet",
            existing_folders=existing_folders,
        )
        fallback_res = BookAnalysis(
            kategorie=sanitize_folder_name(final_cat),
            autor="Unbekannt",
            titel=clean_stem,
            neuer_dateiname=sanitize_filename(original_filename),
            confidence=conf,
            needs_review=True,
            review_reason=final_reason,
        )
        return fallback_res
