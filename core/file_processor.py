"""File processor module for scanning directories, collision-safe renaming and moving of PDFs.
"""

import os
import shutil
from typing import List, Tuple
from core.models import BookItem


def scan_directory_for_pdfs(directory: str) -> List[BookItem]:
    """Finds all PDF files directly located in the chosen directory (shallow scan)."""
    items: List[BookItem] = []
    if not os.path.isdir(directory):
        return items

    try:
        with os.scandir(directory) as scanner:
            for entry in scanner:
                if entry.name.lower().endswith(".pdf") and entry.is_file(follow_symlinks=False):
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        size = 0
                    items.append(
                        BookItem(
                            original_path=entry.path,
                            original_filename=entry.name,
                            file_size=size,
                        )
                    )
    except Exception as e:
        print(f"Error scanning directory {directory}: {e}")

    items.sort(key=lambda x: x.original_filename.lower())
    return items


def get_existing_subdirectories(directory: str) -> List[str]:
    """Retrieves list of existing subfolder names to assist category matching."""
    subdirs: List[str] = []
    if not os.path.isdir(directory):
        return subdirs

    try:
        with os.scandir(directory) as scanner:
            for entry in scanner:
                if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    subdirs.append(entry.name)
    except Exception:
        pass

    return subdirs


def resolve_collision_filename(target_directory: str, filename: str) -> str:
    """Appends an incremental counter (e.g. filename_1.pdf) if target file already exists."""
    full_target = os.path.join(target_directory, filename)
    if not os.path.exists(full_target):
        return filename

    base_name, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = f"{base_name}_{counter}{ext}"
        if not os.path.exists(os.path.join(target_directory, candidate)):
            return candidate
        counter += 1


def execute_book_relocation(
    item: BookItem,
    base_directory: str,
    auto_rename: bool = True,
    dry_run: bool = False,
) -> Tuple[bool, str, str]:
    """Moves and renames a PDF file safely into its categorized folder."""
    if not os.path.isfile(item.original_path):
        return False, "", f"Datei nicht mehr vorhanden: {item.original_filename}"

    category_folder = item.category.strip() if item.category and item.category != "-" else "Sonstiges"
    dest_dir = os.path.join(base_directory, category_folder)

    if auto_rename and item.new_filename and item.new_filename != "-":
        desired_filename = item.new_filename
    else:
        desired_filename = item.original_filename

    final_filename = resolve_collision_filename(dest_dir, desired_filename)
    final_dest_path = os.path.join(dest_dir, final_filename)
    relative_target = os.path.join(category_folder, final_filename)

    if dry_run:
        return True, relative_target, f"[Trockenlauf] Würde nach '{relative_target}' verschoben."

    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(item.original_path, final_dest_path)
        item.original_path = final_dest_path
        item.original_filename = final_filename
        item.applied = True
        return True, relative_target, f"Erfolgreich nach '{relative_target}' verschoben."
    except Exception as e:
        return False, "", f"Fehler beim Verschieben: {str(e)}"
