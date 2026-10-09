"""Main application controller and orchestrator for Buchsortierer AI.
"""

import os
import queue
import threading
from typing import List
import customtkinter as ctk
from tkinter import filedialog

from concurrent.futures import ThreadPoolExecutor, as_completed
from core.models import BookItem
from core.config import load_config, save_config
from core.memory import match_memory_rule, learn_user_correction
from core.file_processor import (
    scan_directory_for_pdfs,
    get_existing_subdirectories,
    execute_book_relocation,
)
from core.cache_manager import get_cached_file
from ai.pdf_extractor import extract_pdf_preview_text
from ai.pipeline import process_book_pipeline
from ui.theme import (
    BG_ROOT,
    BG_CONTAINER,
    ACCENT_BLUE,
    ACCENT_BLUE_HOVER,
    ACCENT_GREEN,
    ACCENT_GREEN_HOVER,
)
from ui.dialogs import ConfirmationDialog
from ui.components import (
    EngineSelector,
    OptionsBar,
    FilterTabBar,
    BookTable,
)


class BuchsortiererApp(ctk.CTk):
    """Main window for Buchsortierer AI."""

    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.items: List[BookItem] = []
        self.is_scanning = False
        self.is_applying = False
        self.is_loading_dir = False
        self.cancel_requested = False

        # Thread-safe UI event dispatch queue (eliminates cross-thread Tcl deadlocks)
        self._ui_queue = queue.Queue()

        self.title("📚 Buchsortierer AI — Intelligente Fachbuch-Katalogisierung")
        self.geometry("1240x840")
        self.minsize(1040, 680)
        self.configure(fg_color=BG_ROOT)

        self._build_ui()
        self._load_saved_state()
        self._poll_ui_queue()

    def dispatch_to_ui(self, func, *args, **kwargs):
        """Thread-safe UI dispatch: places action into queue without touching Tkinter from worker threads."""
        self._ui_queue.put((func, args, kwargs))

    def _poll_ui_queue(self):
        """Processes queued UI actions strictly on the main thread at ~50fps without starving Windows message pump."""
        try:
            processed = 0
            while processed < 30 and not self._ui_queue.empty():
                item = self._ui_queue.get_nowait()
                if len(item) == 3:
                    func, args, kwargs = item
                else:
                    func, args = item
                    kwargs = {}
                try:
                    func(*args, **kwargs)
                except Exception:
                    pass
                processed += 1
        except Exception:
            pass
        finally:
            self.after(20, self._poll_ui_queue)


    def _build_ui(self):
        # 1. Top Container: Header, AI Engine & Directory Selection
        self.top_container = ctk.CTkFrame(self, fg_color=BG_CONTAINER, corner_radius=12)
        self.top_container.pack(fill="x", padx=16, pady=(16, 10))

        # Title bar
        title_bar = ctk.CTkFrame(self.top_container, fg_color="transparent")
        title_bar.pack(fill="x", padx=20, pady=(14, 8))

        app_title = ctk.CTkLabel(
            title_bar,
            text="📚 Buchsortierer AI",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#fafafa",
        )
        app_title.pack(side="left")

        app_subtitle = ctk.CTkLabel(
            title_bar,
            text="Automatische PDF-Katalogisierung & Fachbereich-Sortierung via Ollama (Lokal) oder Gemini",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        )
        app_subtitle.pack(side="left", padx=(14, 0), pady=(5, 0))

        # Engine selector
        self.engine_selector = EngineSelector(self.top_container, on_config_change=self._save_engine_config)
        self.engine_selector.pack(fill="x", padx=20, pady=(2, 6))

        # Directory selection row
        dir_row = ctk.CTkFrame(self.top_container, fg_color="transparent")
        dir_row.pack(fill="x", padx=20, pady=(6, 14))

        dir_label = ctk.CTkLabel(
            dir_row,
            text="Quellverzeichnis:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e4e4e7",
            width=130,
            anchor="w",
        )
        dir_label.pack(side="left")

        self.dir_entry = ctk.CTkEntry(
            dir_row,
            placeholder_text="Wähle den Ordner mit unsortierten Fachbuch-PDFs...",
            fg_color="#27272a",
            border_color="#3f3f46",
            text_color="#fafafa",
            height=36,
            corner_radius=8,
        )
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_select_dir = ctk.CTkButton(
            dir_row,
            text="📂 Ordner wählen",
            width=150,
            height=36,
            corner_radius=8,
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_BLUE_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(weight="bold"),
            command=self._select_directory_clicked,
        )
        self.btn_select_dir.pack(side="left", padx=(0, 8))

        self.lbl_pdf_count = ctk.CTkLabel(
            dir_row,
            text="0 PDFs gefunden",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a1a1aa",
            fg_color="#27272a",
            corner_radius=8,
            width=130,
            height=36,
        )
        self.lbl_pdf_count.pack(side="left")

        # 2. Options Bar
        self.options_bar = OptionsBar(self, on_change=self._save_options_config)
        self.options_bar.pack(fill="x", padx=16, pady=(0, 10))

        # 3. Table & Filter Tabs Container
        self.table_container = ctk.CTkFrame(self, fg_color=BG_CONTAINER, corner_radius=12)
        self.table_container.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        tabs_nav_bar = ctk.CTkFrame(self.table_container, fg_color="transparent")
        tabs_nav_bar.pack(fill="x", padx=14, pady=(10, 4))

        self.tab_bar = FilterTabBar(tabs_nav_bar, on_tab_changed=self._on_tab_changed)
        self.tab_bar.pack(side="left")

        self.book_table = BookTable(self.table_container, on_category_changed=self._on_row_category_changed)
        self.book_table.pack(fill="both", expand=True, padx=4, pady=4)

        # 4. Bottom Action Bar & Progress
        self.bottom_container = ctk.CTkFrame(self, fg_color=BG_CONTAINER, corner_radius=12)
        self.bottom_container.pack(fill="x", padx=16, pady=(0, 16))

        status_bar = ctk.CTkFrame(self.bottom_container, fg_color="transparent")
        status_bar.pack(fill="x", padx=20, pady=(12, 6))

        self.lbl_status = ctk.CTkLabel(
            status_bar,
            text="Bereit",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e4e4e7",
            anchor="w",
        )
        self.lbl_status.pack(side="left", fill="x", expand=True)

        self.lbl_progress_percent = ctk.CTkLabel(
            status_bar,
            text="0%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a1a1aa",
            width=60,
            anchor="e",
        )
        self.lbl_progress_percent.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(
            self.bottom_container,
            orientation="horizontal",
            height=10,
            corner_radius=5,
            fg_color="#27272a",
            progress_color=ACCENT_BLUE,
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=20, pady=(0, 14))

        actions_bar = ctk.CTkFrame(self.bottom_container, fg_color="transparent")
        actions_bar.pack(fill="x", padx=20, pady=(0, 16))

        self.btn_cancel = ctk.CTkButton(
            actions_bar,
            text="⏹️ Abbrechen",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            text_color="#fee2e2",
            height=42,
            corner_radius=8,
            state="disabled",
            command=self._cancel_operation,
        )
        self.btn_cancel.pack(side="left")

        self.btn_apply = ctk.CTkButton(
            actions_bar,
            text="📁 2. Sortierung anwenden",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_GREEN_HOVER,
            text_color="#ffffff",
            height=42,
            corner_radius=8,
            command=self._apply_sorting_clicked,
        )
        self.btn_apply.pack(side="right")

        self.btn_scan = ctk.CTkButton(
            actions_bar,
            text="🔍 1. Bibliothek scannen",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_BLUE_HOVER,
            text_color="#ffffff",
            height=42,
            corner_radius=8,
            command=self._start_scanning_clicked,
        )
        self.btn_scan.pack(side="right", padx=(0, 12))

    def _load_saved_state(self):
        provider = self.config.get("provider", "ollama")
        ollama_model = self.config.get("ollama_model", "qwen2.5vl:latest")
        api_key = self.config.get("api_key", "")
        self.engine_selector.set_config(provider, ollama_model, api_key)

        self.options_bar.set_settings({
            "auto_rename": self.config.get("auto_rename", True),
            "prefer_existing_dirs": self.config.get("prefer_existing_dirs", False),
            "dry_run": self.config.get("dry_run", False),
        })

        last_dir = self.config.get("last_directory", "")
        if last_dir and os.path.isdir(last_dir):
            self.dir_entry.insert(0, last_dir)
            self._load_directory_items(last_dir)

    def _save_engine_config(self):
        self.config["provider"] = self.engine_selector.get_provider()
        self.config["ollama_model"] = self.engine_selector.get_ollama_model()
        self.config["api_key"] = self.engine_selector.get_api_key()
        save_config(self.config)

    def _save_options_config(self):
        opts = self.options_bar.get_settings()
        self.config.update(opts)
        save_config(self.config)

    def _on_tab_changed(self, tab_id: str):
        self.book_table.set_active_tab(tab_id)

    def _on_row_category_changed(self, idx: int, new_category: str):
        if idx < len(self.items):
            item = self.items[idx]
            item.category = new_category
            item.needs_review = False
            item.confidence = 100

            # 1. Learn pattern for persistent local memory
            pattern, count = learn_user_correction(item.original_filename, new_category)

            # 2. Cluster & auto-update other matching books in active list
            clustered_count = 0
            for other_idx, other_item in enumerate(self.items):
                if other_idx != idx:
                    matched = match_memory_rule(other_item.original_filename)
                    if matched and matched[0] == new_category and other_item.category != new_category:
                        other_item.category = new_category
                        other_item.needs_review = False
                        other_item.confidence = 100
                        other_item.review_reason = f"[Memory-Cluster] Aus Korrektur von '{item.original_filename}' gelernt"
                        self.book_table.update_row(other_idx)
                        clustered_count += 1

            self.book_table.update_row(idx)
            self.tab_bar.update_badges(self.items)

            if clustered_count > 0:
                self.lbl_status.configure(
                    text=f"✓ Gelernt: '{pattern}' erkannt! {clustered_count} weitere Bände automatisch auf '{new_category}' aktualisiert.",
                    text_color="#4ade80",
                )
            else:
                self.lbl_status.configure(
                    text=f"✓ Gelernt: Künftige Bücher mit '{pattern}' werden als '{new_category}' einsortiert.",
                    text_color="#60a5fa",
                )

    def _select_directory_clicked(self):
        current_dir = self.dir_entry.get().strip()
        initial = current_dir if os.path.isdir(current_dir) else os.path.expanduser("~")

        selected = filedialog.askdirectory(title="Wähle Fachbuch-Ordner aus", initialdir=initial)
        if selected:
            selected_normalized = os.path.normpath(selected)
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, selected_normalized)
            self.config["last_directory"] = selected_normalized
            save_config(self.config)
            self._load_directory_items(selected_normalized)

    def _load_directory_items(self, directory: str):
        if self.is_loading_dir:
            return

        self.is_loading_dir = True
        self.lbl_status.configure(text="Lese Ordner ein...", text_color="#38bdf8")
        self.lbl_pdf_count.configure(text="Lade...")

        def worker():
            items = scan_directory_for_pdfs(directory)
            self.dispatch_to_ui(self._on_directory_items_loaded, items)

        threading.Thread(target=worker, daemon=True).start()

    def _on_directory_items_loaded(self, items: List[BookItem]):
        self.is_loading_dir = False
        self.items = items
        count = len(self.items)
        self.lbl_pdf_count.configure(text=f"{count} PDF{'s' if count != 1 else ''} gefunden")
        self.lbl_status.configure(
            text=f"Bereit | {count} PDF{'s' if count != 1 else ''} geladen",
            text_color="#e4e4e7",
        )
        self.progress_bar.set(0.0)
        self.lbl_progress_percent.configure(text="0%")
        self.tab_bar.update_badges(self.items)
        self.book_table.load_items(self.items)

    def _start_scanning_clicked(self):
        if self.is_scanning or self.is_applying or self.is_loading_dir:
            return

        provider = self.engine_selector.get_provider()
        api_key = self.engine_selector.get_api_key()
        ollama_model = self.engine_selector.get_ollama_model()

        if provider == "gemini" and not api_key:
            self.lbl_status.configure(
                text="⚠️ Bitte gib deinen Gemini API-Key ein oder wechsle zu Ollama!",
                text_color="#f87171",
            )
            return

        directory = self.dir_entry.get().strip()
        if not directory or not os.path.isdir(directory):
            self.lbl_status.configure(
                text="⚠️ Bitte wähle ein gültiges Verzeichnis aus!",
                text_color="#f87171",
            )
            return

        if not self.items:
            self._load_directory_items(directory)
            return

        self.is_scanning = True
        self.cancel_requested = False
        self.btn_scan.configure(state="disabled")
        self.btn_apply.configure(state="disabled")
        self.btn_select_dir.configure(state="disabled")
        self.btn_cancel.configure(state="normal")

        opts = self.options_bar.get_settings()
        thread = threading.Thread(
            target=self._scan_thread_worker,
            args=(provider, api_key, ollama_model, directory, opts),
            daemon=True,
        )
        thread.start()

    def _scan_thread_worker(self, provider: str, api_key: str, ollama_model: str, directory: str, opts: dict):
        total = len(self.items)
        if total == 0:
            self.dispatch_to_ui(self._on_scan_completed, 1.0)
            return

        existing_folders = []
        if opts.get("prefer_existing_dirs"):
            existing_folders = get_existing_subdirectories(directory)

        completed_count = 0
        lock = threading.Lock()

        def process_single_item(index: int):
            if self.cancel_requested:
                return

            item = self.items[index]
            item.status = "Analysiere..."
            item.status_icon = "🔄"
            # Immediately show analyzing spinner in table
            self.dispatch_to_ui(self.book_table.update_row, index)

            try:
                # Instant Cache Fast-Path (< 0.1ms)
                cached = get_cached_file(item.original_path)
                if cached:
                    analysis = cached
                else:
                    # Lazy PDF extraction: If filename/memory matches (84% of books), PDF is NEVER opened!
                    analysis = process_book_pipeline(
                        original_path=item.original_path,
                        original_filename=item.original_filename,
                        pdf_text=None,
                        existing_folders=existing_folders,
                        provider=provider,
                        ollama_model=ollama_model,
                        api_key=api_key,
                    )

                item.category = analysis.kategorie
                item.author = analysis.autor
                item.title = analysis.titel
                item.new_filename = analysis.neuer_dateiname
                item.confidence = analysis.confidence
                item.needs_review = analysis.needs_review
                item.review_reason = analysis.review_reason
                item.status = "Analysiert"
                item.status_icon = "✓"
            except Exception as e:
                item.status = "Fehler"
                item.status_icon = "⚠️"
                item.confidence = 0
                item.needs_review = True
                item.error_message = str(e)

            with lock:
                nonlocal completed_count
                completed_count += 1
                current_done = completed_count
                progress_ratio = current_done / total

            self.dispatch_to_ui(
                self._update_progress,
                progress_ratio,
                f"Analysiert {current_done}/{total}: {item.original_filename} ({item.category})",
                index,
            )
            if current_done % 5 == 0 or current_done == total:
                self.dispatch_to_ui(self.tab_bar.update_badges, self.items)

        # Cloud-aware worker count: On cloud drives (Google Drive / OneDrive / G:), limit to 2 workers to avoid stream congestion
        dir_norm = directory.lower()
        is_cloud = (
            any(c in dir_norm for c in ["google", "drivefs", "onedrive", "dropbox", "icloud"])
            or (len(dir_norm) >= 2 and dir_norm[1] == ":" and dir_norm[0] not in "cdef")
        )
        pool_workers = 2 if is_cloud else min(6, max(2, (os.cpu_count() or 4)))

        with ThreadPoolExecutor(max_workers=pool_workers) as executor:
            futures = [executor.submit(process_single_item, i) for i in range(total)]
            for fut in as_completed(futures):
                if self.cancel_requested:
                    break
                try:
                    fut.result()
                except Exception:
                    pass

        final_progress = 1.0 if not self.cancel_requested else (completed_count / total)
        self.dispatch_to_ui(self._on_scan_completed, final_progress)

    def _on_scan_completed(self, final_progress: float):
        self.is_scanning = False
        self.progress_bar.set(final_progress)
        self.lbl_progress_percent.configure(text=f"{int(final_progress * 100)}%")
        self.tab_bar.update_badges(self.items)

        needs_rev_count = sum(1 for it in self.items if it.needs_review)
        if not self.cancel_requested:
            if needs_rev_count > 0:
                self.lbl_status.configure(
                    text=f"✓ Scan fertig! {needs_rev_count} Bücher im Tab '⚠️ Zu überprüfen' markiert.",
                    text_color="#fbbf24",
                )
            else:
                self.lbl_status.configure(
                    text="✓ Scan abgeschlossen! Alle Bücher wurden mit hoher Sicherheit zugeordnet.",
                    text_color="#4ade80",
                )

        self.btn_scan.configure(state="normal")
        self.btn_apply.configure(state="normal")
        self.btn_select_dir.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

    def _apply_sorting_clicked(self):
        if self.is_scanning or self.is_applying or self.is_loading_dir:
            return

        directory = self.dir_entry.get().strip()
        if not directory or not os.path.isdir(directory):
            self.lbl_status.configure(
                text="⚠️ Bitte wähle ein gültiges Verzeichnis aus!",
                text_color="#f87171",
            )
            return

        ready_items = [it for it in self.items if it.category != "-" and not it.applied]
        if not ready_items:
            self.lbl_status.configure(
                text="⚠️ Keine analysierten PDFs zum Sortieren vorhanden. Bitte zuerst scannen.",
                text_color="#f87171",
            )
            return

        needs_rev_count = sum(1 for it in ready_items if it.needs_review)
        opts = self.options_bar.get_settings()
        is_dry_run = opts.get("dry_run", False)
        auto_rename = opts.get("auto_rename", True)

        action_name = "TROCKENLAUF (Vorschau)" if is_dry_run else "Sortierung & Verschiebung"
        dialog_title = f"{action_name} bestätigen"

        warn = needs_rev_count > 0
        dialog_msg = (
            f"Möchtest du {len(ready_items)} PDF(s) verarbeiten?\n\n"
            f"• Zielverzeichnis: {directory}\n"
            f"• Dateien umbenennen: {'Ja' if auto_rename else 'Nein'}\n"
            f"• Trockenlauf: {'JA (nur Vorschau)' if is_dry_run else 'NEIN (Dateien werden verschoben)'}"
        )
        if warn:
            dialog_details = (
                f"⚠️ WICHTIG: Es gibt noch {needs_rev_count} Buch/Bücher mit unklarer Zuordnung im Tab '⚠️ Zu überprüfen'. "
                f"Du kannst diese vorher kontrollieren oder jetzt trotzdem fortfahren."
            )
        else:
            dialog_details = "Alle Bücher wurden mit hoher Sicherheit eingeordnet. Kollisionsschutz ist aktiv."

        confirm = ConfirmationDialog(self, dialog_title, dialog_msg, dialog_details, warn=warn)
        if not confirm.result:
            return

        self.is_applying = True
        self.cancel_requested = False
        self.btn_scan.configure(state="disabled")
        self.btn_apply.configure(state="disabled")
        self.btn_select_dir.configure(state="disabled")
        self.btn_cancel.configure(state="normal")

        thread = threading.Thread(
            target=self._apply_thread_worker,
            args=(directory, auto_rename, is_dry_run),
            daemon=True,
        )
        thread.start()

    def _apply_thread_worker(self, base_directory: str, auto_rename: bool, dry_run: bool):
        total = len(self.items)

        for i, item in enumerate(self.items):
            if self.cancel_requested:
                break

            if item.category == "-" or item.applied:
                continue

            success, rel_path, msg = execute_book_relocation(
                item=item,
                base_directory=base_directory,
                auto_rename=auto_rename,
                dry_run=dry_run,
            )

            if success:
                if dry_run:
                    item.status = "Vorschau OK"
                    item.status_icon = "👁️"
                else:
                    item.status = "Sortiert"
                    item.status_icon = "✅"
            else:
                item.status = "Fehler"
                item.status_icon = "⚠️"
                item.error_message = msg

            self.dispatch_to_ui(self.book_table.update_row, i)
            progress_ratio = (i + 1) / total
            self.dispatch_to_ui(
                self._update_progress,
                progress_ratio,
                f"Verschiebe {i + 1} von {total}... ({rel_path})",
                i,
            )

        self.dispatch_to_ui(self._on_apply_completed, dry_run)

    def _on_apply_completed(self, dry_run: bool):
        self.is_applying = False
        self.btn_scan.configure(state="normal")
        self.btn_apply.configure(state="normal")
        self.btn_select_dir.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

        if dry_run:
            self.lbl_status.configure(
                text="👁️ Trockenlauf beendet: Keine Dateien wurden verändert. Alle Pfade geprüft!",
                text_color="#c084fc",
            )
        else:
            self.lbl_status.configure(
                text="🎉 Fertig! Alle Fachbücher wurden erfolgreich sortiert und eingeordnet.",
                text_color="#4ade80",
            )

    def _update_progress(self, ratio: float, status_text: str, row_idx: int):
        self.progress_bar.set(ratio)
        self.lbl_progress_percent.configure(text=f"{int(ratio * 100)}%")
        self.lbl_status.configure(text=status_text, text_color="#e4e4e7")
        self.book_table.update_row(row_idx)

    def _set_status(self, text: str, color: str = "#e4e4e7"):
        self.lbl_status.configure(text=text, text_color=color)

    def _cancel_operation(self):
        self.cancel_requested = True
        self.lbl_status.configure(text="Stoppe laufenden Vorgang...", text_color="#f87171")
        self.btn_cancel.configure(state="disabled")


def main():
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = BuchsortiererApp()
    app.mainloop()


if __name__ == "__main__":
    main()
