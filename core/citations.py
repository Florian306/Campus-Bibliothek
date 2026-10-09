"""Academic citation and bibliography generator.
Supports BibTeX, APA 7th Edition, Harvard, and Markdown formats.
"""

import re
from typing import Any, Dict


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def generate_bibtex(b: Dict[str, Any]) -> str:
    """Generates standard BibTeX citation entry."""
    title = _clean_str(b.get("title") or "Ohne Titel")
    author = _clean_str(b.get("author") or "Unbekannt")
    year = _clean_str(b.get("year"))
    isbn = _clean_str(b.get("isbn"))
    edition = _clean_str(b.get("edition"))
    doi = _clean_str(b.get("doi"))

    # Generate citation key: e.g. "Mueller2021"
    first_author_token = re.sub(r"\W", "", author.split()[0]) if author else "Buch"
    year_token = year if year else "oD"
    cite_key = f"{first_author_token}{year_token}"

    lines = [f"@book{{{cite_key},"]
    lines.append(f"  title     = {{{title}}},")
    lines.append(f"  author    = {{{author}}},")
    if year:
        lines.append(f"  year      = {{{year}}},")
    if edition and edition != "1":
        lines.append(f"  edition   = {{{edition}}},")
    if isbn:
        lines.append(f"  isbn      = {{{isbn}}},")
    if doi:
        lines.append(f"  doi       = {{{doi}}},")
    
    # Remove trailing comma on last item
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def generate_apa(b: Dict[str, Any]) -> str:
    """Generates APA 7th Edition citation."""
    author = _clean_str(b.get("author") or "Unbekannt")
    year = _clean_str(b.get("year") or "o. D.")
    title = _clean_str(b.get("title") or "Ohne Titel")
    edition = _clean_str(b.get("edition"))
    doi = _clean_str(b.get("doi"))
    isbn = _clean_str(b.get("isbn"))

    ed_str = f" ({edition}. Aufl.)" if edition and edition != "1" else ""
    apa = f"{author} ({year}). {title}{ed_str}."
    if doi:
        apa += f" https://doi.org/{doi}"
    elif isbn:
        apa += f" ISBN: {isbn}"
    return apa


def generate_markdown_link(b: Dict[str, Any]) -> str:
    """Generates Markdown reference link."""
    title = _clean_str(b.get("title") or "Ohne Titel")
    author = _clean_str(b.get("author") or "Unbekannt")
    year = _clean_str(b.get("year"))
    file_path = _clean_str(b.get("file_path"))

    year_str = f" ({year})" if year else ""
    if file_path:
        # Standard file:/// URI
        norm_path = file_path.replace("\\", "/")
        return f"[{title}{year_str} - {author}](file:///{norm_path})"
    return f"**{title}**{year_str} von *{author}*"


def generate_ris(b: Dict[str, Any]) -> str:
    """Generates standard RIS (Research Information Systems) citation for Zotero/Citavi/Mendeley."""
    title = _clean_str(b.get("title") or "Ohne Titel")
    author = _clean_str(b.get("author") or "Unbekannt")
    year = _clean_str(b.get("year"))
    isbn = _clean_str(b.get("isbn"))
    edition = _clean_str(b.get("edition"))
    doi = _clean_str(b.get("doi"))

    lines = ["TY  - BOOK"]
    lines.append(f"TI  - {title}")
    lines.append(f"AU  - {author}")
    if year:
        lines.append(f"PY  - {year}")
    if edition and edition != "1":
        lines.append(f"ET  - {edition}. Auflage")
    if isbn:
        lines.append(f"SN  - {isbn}")
    if doi:
        lines.append(f"DO  - {doi}")
    lines.append("ER  - \n")
    return "\n".join(lines)


def export_library_to_file(books: list, export_format: str, target_path: str) -> int:
    """Exports list of books to the specified citation or spreadsheet format (.bib, .ris, .csv)."""
    import csv

    export_format = export_format.lower().strip(".")
    count = 0

    if export_format == "bib":
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("% Campus Library Export - BibTeX\n\n")
            for b in books:
                f.write(generate_bibtex(b) + "\n\n")
                count += 1

    elif export_format == "ris":
        with open(target_path, "w", encoding="utf-8") as f:
            for b in books:
                f.write(generate_ris(b) + "\n")
                count += 1

    elif export_format == "csv":
        with open(target_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Titel", "Autor", "Erscheinungsjahr", "Auflage", "ISBN", "Fachbereich(e)", "Seitenzahl", "Dateiname", "Pfad"])
            for b in books:
                writer.writerow([
                    b.get("title", ""),
                    b.get("author", ""),
                    b.get("year", ""),
                    b.get("edition", 1),
                    b.get("isbn", ""),
                    b.get("categories_str", ""),
                    b.get("page_count", 0),
                    b.get("filename", ""),
                    b.get("file_path", ""),
                ])
                count += 1

    return count

