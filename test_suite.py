"""Unit and component test suite for Buchsortierer AI.
"""

import os
import shutil
import tempfile
from pypdf import PdfWriter
from config_manager import load_config, save_config
from file_processor import (
    BookItem,
    scan_directory_for_pdfs,
    get_existing_subdirectories,
    resolve_collision_filename,
    execute_book_relocation,
)
from gemini_analyzer import (
    sanitize_filename,
    sanitize_folder_name,
    extract_pdf_preview_text,
)


def create_dummy_pdf(path: str, title: str, author: str, content: str):
    """Creates a basic PDF with text and metadata using pypdf."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    writer.add_metadata({
        "/Title": title,
        "/Author": author,
        "/Subject": "Wissenschaftliches Lehrbuch",
    })
    with open(path, "wb") as f:
        writer.write(f)


def run_tests():
    print("=== Starte Test Suite ===")

    # Test 1: Sanitization
    test_raw_filename = 'Helmut Plattner: Einführung in "Quantenmechanik" & Kernphysik?.pdf'
    clean_name = sanitize_filename(test_raw_filename)
    assert ":" not in clean_name and '"' not in clean_name and "?" not in clean_name
    assert clean_name.endswith(".pdf")
    print(f"[OK] Sanitize Filename: '{test_raw_filename}' -> '{clean_name}'")

    test_folder = 'Jura / Öffentliches Recht: Band 1'
    clean_folder = sanitize_folder_name(test_folder)
    assert "/" not in clean_folder and ":" not in clean_folder
    print(f"[OK] Sanitize Folder: '{test_folder}' -> '{clean_folder}'")

    # Test 2: Temporary Directory Operations
    temp_dir = tempfile.mkdtemp(prefix="buchsortierer_test_")
    try:
        # Create dummy subfolder to test directory detection
        mathe_dir = os.path.join(temp_dir, "Mathematik")
        os.makedirs(mathe_dir, exist_ok=True)
        subdirs = get_existing_subdirectories(temp_dir)
        assert "Mathematik" in subdirs
        print(f"[OK] Subdirectory Detection: {subdirs}")

        # Create dummy PDF files
        pdf1 = os.path.join(temp_dir, "analysis_1.pdf")
        pdf2 = os.path.join(temp_dir, "physik_grundlagen.pdf")
        create_dummy_pdf(pdf1, "Analysis I", "Otto Forster", "Analysis Vorlesungsskript")
        create_dummy_pdf(pdf2, "Physik Grundlagen", "Christian Gerthsen", "Experimentalphysik")

        items = scan_directory_for_pdfs(temp_dir)
        assert len(items) == 2
        print(f"[OK] PDF Scan: {len(items)} PDFs gefunden")

        # Test PDF text extraction / metadata fallback
        extracted = extract_pdf_preview_text(pdf1)
        assert "Analysis I" in extracted or "Otto Forster" in extracted or len(extracted) > 0
        print(f"[OK] PDF Text/Metadata Extraction erfolgreich: {extracted[:60]}...")

        # Test 3: Collision resolution
        collision_file = resolve_collision_filename(temp_dir, "analysis_1.pdf")
        assert collision_file == "analysis_1_1.pdf"
        print(f"[OK] Collision Resolution: analysis_1.pdf -> {collision_file}")

        # Test 4: Dry-Run Relocation
        item1 = items[0]
        item1.category = "Mathematik"
        item1.new_filename = "Otto Forster - Analysis 1.pdf"
        success, rel_path, msg = execute_book_relocation(
            item1, temp_dir, auto_rename=True, dry_run=True
        )
        assert success is True
        assert os.path.isfile(pdf1)  # File must still be at original location
        print(f"[OK] Dry Run Relocation: {msg}")

        # Test 5: Real Relocation
        success, rel_path, msg = execute_book_relocation(
            item1, temp_dir, auto_rename=True, dry_run=False
        )
        assert success is True
        assert not os.path.isfile(pdf1)  # Original moved
        expected_target = os.path.join(temp_dir, "Mathematik", "Otto Forster - Analysis 1.pdf")
        assert os.path.isfile(expected_target)
        print(f"[OK] Real Relocation: Erfolgreich verschoben nach '{expected_target}'")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("=== Alle Tests erfolgreich abgeschlossen! ===")


if __name__ == "__main__":
    run_tests()
