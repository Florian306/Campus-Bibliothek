"""Quick-Look Dialog for PySide6.
Activated via Spacebar to view book cover, metadata, interactive TOC (Table of Contents), and AI summary/notes.
"""

import os
from typing import Any, Dict, List, Tuple
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap, QImage
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QWidget,
    QFrame,
    QApplication,
    QMessageBox,
    QCheckBox,
    QScrollArea,
)
import subprocess

from core.cover_manager import get_cached_cover, generate_fallback_cover
from core.library_db import (
    open_pdf_in_edge,
    toggle_desk_item,
    get_book_notes,
    update_reading_progress,
    delete_book,
    get_book_extracts,
    delete_book_extract,
    delete_all_book_extracts,
    toggle_extract_desk,
)
from core.config import load_config
from ai.pdf_extractor import extract_pdf_toc, _TOC_CACHE
from ui.qt.theme import NoFocusItemDelegate
from ui.qt.icons import create_vector_icon
from ui.qt.dialogs.pdf_reader_dialog import PdfReaderDialog


class TocLoaderThread(QThread):
    """Background worker to extract Table of Contents without blocking dialog render."""
    finished_toc = Signal(list)

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            items = extract_pdf_toc(self.file_path) if self.file_path and os.path.exists(self.file_path) else []
        except Exception:
            items = []
        self.finished_toc.emit(items)


class QuickLookDialog(QDialog):
    """Modern modal inspection window with interactive Table of Contents (TOC) and notes."""

    def __init__(self, book: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle(f"Quick-Look: {book.get('title', 'Buchdetails')}")
        self.resize(960, 640)
        self.setMinimumSize(920, 600)
        self.setStyleSheet("""
            QDialog {
                background-color: #161B22;
                border: 1px solid #30363D;
            }
        """)

        self._toc_thread = None
        self._cached_toc = None
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # Left Column: Large Cover & Actions
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        self.lbl_cover = QLabel()
        self.lbl_cover.setFixedSize(200, 280)
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setStyleSheet("""
            QLabel {
                background-color: #0D1117;
                border: 1px solid #30363D;
                border-radius: 6px;
            }
        """)
        self._load_cover()
        left_col.addWidget(self.lbl_cover)

        btn_open = QPushButton("  PDF öffnen")
        btn_open.setIcon(create_vector_icon("desk", "#FFFFFF", 16))
        btn_open.setObjectName("primaryButton")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(34)
        btn_open.clicked.connect(self._open_pdf)
        left_col.addWidget(btn_open)

        btn_desk = QPushButton("  Auf Schreibtisch")
        btn_desk.setIcon(create_vector_icon("library", "#C9D1D9", 16))
        btn_desk.setCursor(Qt.PointingHandCursor)
        btn_desk.setFixedHeight(34)
        btn_desk.clicked.connect(self._toggle_desk)
        left_col.addWidget(btn_desk)

        btn_extract = QPushButton("  ✂ Seiten extrahieren")
        btn_extract.setIcon(create_vector_icon("download", "#58A6FF", 15))
        btn_extract.setCursor(Qt.PointingHandCursor)
        btn_extract.setFixedHeight(34)
        btn_extract.setStyleSheet("""
            QPushButton {
                background-color: #162035;
                color: #58A6FF;
                border: 1px solid #283C64;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #1E2D4A;
                border-color: #58A6FF;
                color: #79C0FF;
            }
        """)
        btn_extract.clicked.connect(self._extract_pages)
        left_col.addWidget(btn_extract)

        btn_delete = QPushButton("  Aus Katalog entfernen")
        btn_delete.setIcon(create_vector_icon("trash", "#FF7B72", 15))
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.setFixedHeight(34)
        btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #211215;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #381920;
                border-color: #F85149;
                color: #FFA198;
            }
        """)
        btn_delete.clicked.connect(self._delete_book_prompt)
        left_col.addWidget(btn_delete)

        left_col.addStretch()
        main_layout.addLayout(left_col)

        # Right Column: Details, Metadata & Tabs
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        # Title & Author Header
        lbl_title = QLabel(self.book.get("title", "Ohne Titel"))
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC;")
        lbl_title.setWordWrap(True)
        right_col.addWidget(lbl_title)

        lbl_author = QLabel(f"von {self.book.get('author', 'Unbekannt')}")
        lbl_author.setFont(QFont("Segoe UI", 9))
        lbl_author.setStyleSheet("color: #8B949E;")
        right_col.addWidget(lbl_author)

        # Metadata Grid Frame
        meta_frame = QFrame()
        meta_frame.setStyleSheet("""
            QFrame {
                background-color: #0D1117;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 8px 12px;
            }
        """)
        meta_layout = QVBoxLayout(meta_frame)
        meta_layout.setSpacing(4)
        meta_layout.setContentsMargins(10, 8, 10, 8)

        cats = (self.book.get("categories_str") or "Sonstiges").replace("|", " • ")
        ed = f"{self.book.get('edition', 1)}. Auflage ({self.book.get('year') or 'N/A'})"
        pages = f"{self.book.get('page_count', 0)} Seiten"
        isbn = self.book.get("isbn") or "Keine ISBN"

        meta_layout.addWidget(QLabel(f"<span style='color:#8B949E;'>Fachbereiche:</span> <span style='color:#F0F6FC;'>{cats}</span>"))
        meta_layout.addWidget(QLabel(f"<span style='color:#8B949E;'>Ausgabe:</span> <span style='color:#F0F6FC;'>{ed} • {pages}</span>"))
        meta_layout.addWidget(QLabel(f"<span style='color:#8B949E;'>ISBN:</span> <span style='color:#F0F6FC;'>{isbn}</span>"))

        right_col.addWidget(meta_frame)

        # -------------------------------------------------------------
        # Tabs for Inhaltsverzeichnis (TOC) and Zusammenfassung & Notizen
        # -------------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #232F48;
                background-color: #0D111A;
                border-radius: 8px;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #121826;
                color: #8B949E;
                border: 1px solid #232F48;
                border-bottom: none;
                padding: 6px 14px;
                font-weight: 600;
                font-size: 11px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #0D111A;
                color: #58A6FF;
                border-color: #232F48;
                border-bottom: 2px solid #58A6FF;
            }
            QTabBar::tab:hover:!selected {
                background-color: #182236;
                color: #F0F6FC;
            }
            QScrollBar:vertical {
                border: none;
                background-color: #0D111A;
                width: 8px;
                margin: 0;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #232F48;
                min-height: 25px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #388BFD;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        # 1. Tab: Inhaltsverzeichnis (TOC)
        self.toc_tab = QWidget()
        self.toc_layout = QVBoxLayout(self.toc_tab)
        self.toc_layout.setContentsMargins(10, 10, 10, 10)
        self.toc_layout.setSpacing(8)

        # Initial loading placeholder for instant window opening
        self.lbl_toc_status = QLabel("⏳ Lese Inhaltsverzeichnis...")
        self.lbl_toc_status.setAlignment(Qt.AlignCenter)
        self.lbl_toc_status.setStyleSheet("color: #8B949E; padding: 40px; font-size: 12px;")
        self.toc_layout.addWidget(self.lbl_toc_status)
        self.tabs.addTab(self.toc_tab, create_vector_icon("notes", "#8B949E", 14), "Inhaltsverzeichnis")

        # Check in-memory TOC cache first for instant rendering
        fp = self.book.get("file_path", "")
        if fp and os.path.exists(fp):
            norm_fp = os.path.abspath(fp)
            if norm_fp in _TOC_CACHE:
                self._on_toc_loaded(_TOC_CACHE[norm_fp])
            else:
                self._toc_thread = TocLoaderThread(fp)
                self._toc_thread.finished_toc.connect(self._on_toc_loaded)
                self._toc_thread.start()
        else:
            self.lbl_toc_status.setText("Keine Datei verknüpft oder Datei existiert nicht mehr.")

        # 2. Tab: Extrahierte Kapitel & Anhänge (Parent-Child)
        self.extracts_tab = QWidget()
        self._build_extracts_tab()
        self.tabs.addTab(self.extracts_tab, create_vector_icon("download", "#58A6FF", 14), "Kapitel / Anhänge")

        # 3. Tab: Zusammenfassung & Notizen
        notes_tab = QWidget()
        notes_layout = QVBoxLayout(notes_tab)
        notes_layout.setContentsMargins(12, 12, 12, 12)
        notes_layout.setSpacing(8)

        summary_txt = self.book.get("summary") or ""
        bid = str(self.book.get("id", ""))
        book_notes = get_book_notes(bid) if bid else []

        content_parts = []
        if summary_txt:
            content_parts.append(f"Inhaltsangabe & Zusammenfassung:\n\n{summary_txt}")
        if book_notes:
            content_parts.append("\n\nEigene Notizen & Exzerpte:")
            for n in book_notes:
                p_info = f" (Seite {n['page_number']})" if n.get("page_number") else ""
                content_parts.append(f"• {n['note_text']}{p_info}")

        full_notes_text = "\n".join(content_parts) if content_parts else "Keine Inhaltsangabe oder Notizen für dieses Buch hinterlegt."

        txt_box = QPlainTextEdit()
        txt_box.setPlainText(full_notes_text)
        txt_box.setReadOnly(True)
        txt_box.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0D111A;
                color: #F0F6FC;
                border: none;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        notes_layout.addWidget(txt_box, stretch=1)
        self.tabs.addTab(notes_tab, create_vector_icon("book", "#A371F7", 14), "Zusammenfassung & Notizen")

        right_col.addWidget(self.tabs, stretch=1)

        # Close button
        btn_close = QPushButton("Schließen (Esc)")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        right_col.addWidget(btn_close, alignment=Qt.AlignRight)

        main_layout.addLayout(right_col, stretch=1)

    def _on_toc_loaded(self, toc_items: list) -> None:
        """Called when background TOC extraction finishes. Updates the tree smoothly."""
        self._cached_toc = toc_items
        if hasattr(self, "lbl_toc_status") and self.lbl_toc_status:
            self.lbl_toc_status.deleteLater()
            self.lbl_toc_status = None

        if toc_items:
            self.tree_toc = QTreeWidget()
            self.tree_toc.setItemDelegate(NoFocusItemDelegate(self.tree_toc))
            self.tree_toc.setHeaderLabels(["Kapitel / Abschnitt", "Seite"])
            self.tree_toc.header().setStretchLastSection(False)
            self.tree_toc.header().setSectionResizeMode(0, QHeaderView.Stretch)
            self.tree_toc.header().setSectionResizeMode(1, QHeaderView.Fixed)
            self.tree_toc.setColumnWidth(1, 75)
            self.tree_toc.setStyleSheet("""
                QTreeWidget {
                    background-color: #0D111A;
                    color: #F0F6FC;
                    border: none;
                    outline: none;
                }
                QTreeWidget::item {
                    padding: 5px 2px;
                    border-radius: 4px;
                }
                QTreeWidget::item:hover {
                    background-color: #16243E;
                }
                QTreeWidget::item:selected {
                    background-color: #1F365A;
                    color: #FFFFFF;
                }
                QHeaderView::section {
                    background-color: #121826;
                    color: #8B949E;
                    font-weight: 600;
                    font-size: 11px;
                    border: none;
                    border-bottom: 1px solid #232F48;
                    padding: 6px 8px;
                }
            """)

            stack = {}
            for item_data in toc_items:
                lvl = item_data[0]
                title = item_data[1]
                target_page = item_data[2]
                printed_page = item_data[3] if len(item_data) > 3 else target_page

                item = QTreeWidgetItem([title, f"S. {printed_page}"])
                item.setData(0, Qt.UserRole, target_page)
                item.setTextAlignment(1, Qt.AlignCenter)
                if lvl == 1 or (lvl - 1) not in stack:
                    self.tree_toc.addTopLevelItem(item)
                else:
                    stack[lvl - 1].addChild(item)
                stack[lvl] = item

            for i in range(self.tree_toc.topLevelItemCount()):
                self.tree_toc.topLevelItem(i).setExpanded(True)

            self.tree_toc.itemDoubleClicked.connect(self._on_toc_double_clicked)
            self.toc_layout.addWidget(self.tree_toc, stretch=1)

            # Footer hint + Quick Jump Button
            hint_row = QHBoxLayout()
            lbl_hint = QLabel("💡 Doppelklick auf ein Kapitel springt direkt zur Seite im PDF.")
            lbl_hint.setStyleSheet("color: #8B949E; font-size: 11px; border: none; background: transparent;")
            hint_row.addWidget(lbl_hint, stretch=1)

            btn_jump = QPushButton("Kapitel aufschlagen")
            btn_jump.setCursor(Qt.PointingHandCursor)
            btn_jump.setStyleSheet("""
                QPushButton {
                    background-color: #1F293D;
                    color: #58A6FF;
                    border: 1px solid #232F48;
                    border-radius: 5px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #263550;
                    border-color: #388BFD;
                }
            """)
            btn_jump.clicked.connect(self._jump_selected_chapter)
            hint_row.addWidget(btn_jump)
            self.toc_layout.addLayout(hint_row)

            self.tabs.setTabText(0, f"Inhaltsverzeichnis ({len(toc_items)})")
            self.tabs.setTabIcon(0, create_vector_icon("notes", "#58A6FF", 14))
        else:
            lbl_no_toc = QLabel("Für dieses Buch konnte weder ein digitales noch ein gedrucktes Inhaltsverzeichnis ermittelt werden.")
            lbl_no_toc.setAlignment(Qt.AlignCenter)
            lbl_no_toc.setStyleSheet("color: #8B949E; padding: 30px; font-size: 12px;")
            self.toc_layout.addWidget(lbl_no_toc)
            self.tabs.setTabText(0, "Inhaltsverzeichnis (0)")
            self.tabs.setTabIcon(0, create_vector_icon("notes", "#8B949E", 14))

    def _on_toc_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        page = item.data(0, Qt.UserRole)
        if page:
            p_int = max(1, int(page))
            path = self.book.get("file_path")
            bid = str(self.book.get("id", ""))
            if bid:
                update_reading_progress(bid, p_int)
            if path and os.path.exists(path):
                cfg = load_config()
                if cfg.get("use_internal_reader", True):
                    dlg = PdfReaderDialog(self.book, initial_page=p_int, toc_items=self._cached_toc, parent=self)
                    dlg.exec()
                else:
                    open_pdf_in_edge(path, page=p_int)
                    self.accept()

    def _jump_selected_chapter(self) -> None:
        if hasattr(self, "tree_toc"):
            item = self.tree_toc.currentItem()
            if item:
                self._on_toc_double_clicked(item, 0)

    def _load_cover(self) -> None:
        bid = str(self.book.get("id", ""))
        cached = get_cached_cover(bid)
        if not cached:
            cached = generate_fallback_cover(
                self.book.get("title", ""),
                self.book.get("author", ""),
                self.book.get("primary_category", "Sonstiges")
            )
        if cached:
            try:
                rgb_pil = cached.convert("RGB")
                w, h = rgb_pil.size
                qim = QImage(rgb_pil.tobytes(), w, h, w * 3, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(qim).scaled(200, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_cover.setPixmap(pixmap)
            except Exception:
                pass

    def _open_pdf(self) -> None:
        path = self.book.get("file_path")
        if path and os.path.exists(path):
            page = self.book.get("current_page", 1)
            cfg = load_config()
            if cfg.get("use_internal_reader", True):
                dlg = PdfReaderDialog(self.book, initial_page=page, toc_items=self._cached_toc, parent=self)
                dlg.exec()
            else:
                open_pdf_in_edge(path, page=page)

    def _toggle_desk(self) -> None:
        bid = str(self.book.get("id", ""))
        if bid:
            toggle_desk_item(bid)
            self.accept()

    def _delete_book_prompt(self) -> None:
        bid = str(self.book.get("id", ""))
        if not bid:
            return

        title = self.book.get("title", "Dieses Buch")
        file_path = self.book.get("file_path", "")

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Buch entfernen")
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setText(f"Möchtest du das Buch <b>{title}</b> wirklich aus dem Katalog entfernen?")
        msg_box.setInformativeText("Notizen, Lesefortschritt und Index-Daten werden gelöscht.")

        chk_delete_file = QCheckBox("Auch die PDF-Datei von der Festplatte löschen")
        chk_delete_file.setStyleSheet("color: #FF7B72; font-weight: bold; margin-top: 10px;")
        if not file_path or not os.path.isfile(file_path):
            chk_delete_file.setEnabled(False)
            chk_delete_file.setText("PDF-Datei existiert lokal nicht mehr")

        msg_box.setCheckBox(chk_delete_file)

        btn_cancel = msg_box.addButton("Abbrechen", QMessageBox.RejectRole)
        btn_del = msg_box.addButton("Aus Katalog entfernen", QMessageBox.AcceptRole)
        btn_del.setStyleSheet("background-color: #DA3633; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        msg_box.exec()

        if msg_box.clickedButton() == btn_del:
            delete_file_disk = chk_delete_file.isChecked()
            success, err = delete_book(bid, delete_file=delete_file_disk)
            if success:
                self.accept()
            else:
                QMessageBox.critical(self, "Fehler beim Löschen", err or "Unbekannter Fehler.")

    def _extract_pages(self) -> None:
        from ui.qt.dialogs.pdf_extract_dialog import PdfExtractDialog
        dlg = PdfExtractDialog(self.book, parent=self)
        if dlg.exec():
            self._refresh_extracts_list()

    def _build_extracts_tab(self) -> None:
        tab_layout = QVBoxLayout(self.extracts_tab)
        tab_layout.setContentsMargins(12, 12, 12, 12)
        tab_layout.setSpacing(10)

        # Header description + New Extraction Shortcut
        top_bar = QHBoxLayout()
        lbl_hint = QLabel("Auszüge & Kapitel als eigenständige PDFs für NotebookLM, KI-Tools oder separates Lernen.")
        lbl_hint.setFont(QFont("Segoe UI", 8))
        lbl_hint.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        lbl_hint.setWordWrap(True)
        top_bar.addWidget(lbl_hint, stretch=1)

        btn_open_all = QPushButton("  📂 In Explorer")
        btn_open_all.setToolTip("Öffnet den Speicherordner mit allen extrahierten Kapiteln")
        btn_open_all.setFont(QFont("Segoe UI", 8))
        btn_open_all.setCursor(Qt.PointingHandCursor)
        btn_open_all.setStyleSheet("""
            QPushButton {
                background-color: #162035;
                color: #C9D1D9;
                border: 1px solid #2B3D5E;
                border-radius: 5px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #1F2D48;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_open_all.clicked.connect(self._open_extracts_folder)
        top_bar.addWidget(btn_open_all)

        self.btn_delete_all_extracts = QPushButton("  Alle löschen")
        self.btn_delete_all_extracts.setIcon(create_vector_icon("trash", "#FF7B72", 12))
        self.btn_delete_all_extracts.setToolTip("Löscht alle an dieses Buch angehängten Kapitel und deren Ordner")
        self.btn_delete_all_extracts.setFont(QFont("Segoe UI", 8))
        self.btn_delete_all_extracts.setCursor(Qt.PointingHandCursor)
        self.btn_delete_all_extracts.setStyleSheet("""
            QPushButton {
                background-color: #211215;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 5px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #381920;
                border-color: #F85149;
                color: #FFA198;
            }
        """)
        self.btn_delete_all_extracts.clicked.connect(self._delete_all_extracts_prompt)
        top_bar.addWidget(self.btn_delete_all_extracts)

        btn_new_extract = QPushButton("  ✂ Extrahieren")
        btn_new_extract.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_new_extract.setCursor(Qt.PointingHandCursor)
        btn_new_extract.setStyleSheet("""
            QPushButton {
                background-color: #1F293D;
                color: #58A6FF;
                border: 1px solid #304163;
                border-radius: 5px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background-color: #263550;
                border-color: #58A6FF;
                color: #79C0FF;
            }
        """)
        btn_new_extract.clicked.connect(self._extract_pages)
        top_bar.addWidget(btn_new_extract)
        tab_layout.addLayout(top_bar)

        # Scrollable container for extract cards
        self.scroll_extracts = QScrollArea()
        self.scroll_extracts.setWidgetResizable(True)
        self.scroll_extracts.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_extracts.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
        """)

        self.extracts_container = QWidget()
        self.extracts_container.setStyleSheet("background-color: transparent; border: none;")
        self.extracts_layout = QVBoxLayout(self.extracts_container)
        self.extracts_layout.setContentsMargins(0, 0, 4, 0)
        self.extracts_layout.setSpacing(8)

        self.scroll_extracts.setWidget(self.extracts_container)
        tab_layout.addWidget(self.scroll_extracts, stretch=1)

        self._refresh_extracts_list()

    def _refresh_extracts_list(self) -> None:
        while self.extracts_layout.count() > 0:
            item = self.extracts_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        bid = str(self.book.get("id", ""))
        extracts = get_book_extracts(bid) if bid else []

        # Update tab title badge and action buttons
        tab_idx = self.tabs.indexOf(self.extracts_tab)
        if tab_idx != -1:
            self.tabs.setTabText(tab_idx, f"Kapitel / Anhänge ({len(extracts)})")

        if hasattr(self, "btn_delete_all_extracts") and self.btn_delete_all_extracts:
            self.btn_delete_all_extracts.setEnabled(bool(extracts))
            self.btn_delete_all_extracts.setVisible(bool(extracts))

        if not extracts:
            lbl_empty = QLabel("Noch keine Kapitel oder Auszüge an dieses Buch geheftet.\nKlicke oben auf '✂ Extrahieren'.")
            lbl_empty.setStyleSheet("color: #6E7681; font-style: italic; padding: 30px; border: none; background: transparent;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            self.extracts_layout.addWidget(lbl_empty)
            self.extracts_layout.addStretch()
            return

        for ext in extracts:
            card = self._create_extract_card(ext)
            self.extracts_layout.addWidget(card)

        self.extracts_layout.addStretch()

    def _create_extract_card(self, ext: Dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-left: 3px solid #58A6FF;
                border-radius: 6px;
            }
            QFrame:hover {
                background-color: #162035;
                border-color: #388BFD;
            }
        """)
        h_layout = QHBoxLayout(card)
        h_layout.setContentsMargins(12, 10, 12, 10)
        h_layout.setSpacing(12)

        # Title & Meta info
        info_col = QVBoxLayout()
        info_col.setSpacing(3)

        lbl_t = QLabel(ext.get("title", "Unbenannter Auszug"))
        lbl_t.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_t.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        lbl_t.setWordWrap(True)
        info_col.addWidget(lbl_t)

        p_range = ext.get("page_range") or "—"
        p_count = ext.get("page_count", 0)
        fsize_mb = (ext.get("file_size", 0) or 0) / (1024 * 1024)
        size_str = f"{fsize_mb:.1f} MB" if fsize_mb >= 0.1 else f"{ext.get('file_size', 0) // 1024} KB"

        meta_txt = f"Seiten: {p_range} ({p_count} S.) · Dateigröße: {size_str}"
        lbl_m = QLabel(meta_txt)
        lbl_m.setFont(QFont("Segoe UI", 8))
        lbl_m.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        lbl_m.setWordWrap(True)
        info_col.addWidget(lbl_m)

        h_layout.addLayout(info_col, stretch=1)

        # Action Buttons
        fpath = ext.get("file_path", "")
        ext_id = str(ext.get("id", ""))
        on_desk = bool(ext.get("on_desk", 0))

        # 1. Open PDF
        btn_open = QPushButton("Öffnen")
        btn_open.setIcon(create_vector_icon("desk", "#FFFFFF", 13))
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(28)
        btn_open.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 4px;
                padding: 0 8px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #388BFD;
            }
        """)
        btn_open.clicked.connect(lambda _, p=fpath, t=ext.get("title", "Auszug"): self._open_extract_pdf(p, t))
        h_layout.addWidget(btn_open)

        # 2. Explorer (For NotebookLM drag-and-drop)
        btn_exp = QPushButton("Datei")
        btn_exp.setIcon(create_vector_icon("library", "#C9D1D9", 13))
        btn_exp.setToolTip("Im Windows Explorer anzeigen (perfekt zum Hochladen in NotebookLM)")
        btn_exp.setCursor(Qt.PointingHandCursor)
        btn_exp.setFixedHeight(28)
        btn_exp.setStyleSheet("""
            QPushButton {
                background-color: #162035;
                color: #C9D1D9;
                border: 1px solid #2B3D5E;
                border-radius: 4px;
                padding: 0 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1F2D48;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_exp.clicked.connect(lambda _, p=fpath: subprocess.run(["explorer", "/select,", os.path.normpath(p)]) if p and os.path.exists(p) else None)
        h_layout.addWidget(btn_exp)

        # 3. Toggle Desk Button
        desk_text = "Schreibtisch"
        desk_color = "#388BFD" if on_desk else "#8B949E"
        btn_toggle_desk = QPushButton(desk_text)
        btn_toggle_desk.setIcon(create_vector_icon("library" if not on_desk else "desk", desk_color, 12))
        btn_toggle_desk.setCursor(Qt.PointingHandCursor)
        btn_toggle_desk.setFixedHeight(28)
        btn_toggle_desk.setStyleSheet(f"""
            QPushButton {{
                background-color: #161D2C;
                color: {desk_color};
                border: 1px solid #25334E;
                border-radius: 4px;
                padding: 0 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #1F293D;
                color: #58A6FF;
            }}
        """)
        btn_toggle_desk.clicked.connect(lambda _, eid=ext_id: self._on_toggle_extract_desk(eid))
        h_layout.addWidget(btn_toggle_desk)

        # 4. Delete Extract Button
        btn_del = QPushButton()
        btn_del.setIcon(create_vector_icon("trash", "#FF7B72", 13))
        btn_del.setToolTip("Kapitelverknüpfung löschen...")
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setFixedSize(28, 28)
        btn_del.setStyleSheet("""
            QPushButton {
                background-color: #211215;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #381920;
                border-color: #F85149;
            }
        """)
        btn_del.clicked.connect(lambda _, eid=ext_id, t=ext.get("title", ""), p=fpath: self._on_delete_extract(eid, t, p))
        h_layout.addWidget(btn_del)

        return card

    def _open_extract_pdf(self, file_path: str, title: str) -> None:
        if not file_path or not os.path.exists(file_path):
            return
        cfg = load_config()
        if cfg.get("use_internal_reader", True):
            ext_book = {
                "id": str(self.book.get("id", "")),
                "title": f"{self.book.get('title', '')} • {title}",
                "file_path": file_path,
            }
            dlg = PdfReaderDialog(ext_book, initial_page=1, parent=self)
            dlg.exec()
        else:
            open_pdf_in_edge(file_path)

    def _on_toggle_extract_desk(self, extract_id: str) -> None:
        toggle_extract_desk(extract_id)
        self._refresh_extracts_list()

    def _on_delete_extract(self, extract_id: str, title: str, file_path: str) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("Kapitel entfernen")
        msg.setIcon(QMessageBox.Question)
        msg.setText(f"Möchtest du das Kapitel <b>{title}</b> entfernen?")

        chk_del_disk = QCheckBox("Auch PDF-Datei von der Festplatte löschen")
        chk_del_disk.setStyleSheet("color: #FF7B72; font-weight: bold; margin-top: 10px;")
        if not file_path or not os.path.isfile(file_path):
            chk_del_disk.setEnabled(False)
            chk_del_disk.setText("Datei nicht mehr lokal vorhanden")
        msg.setCheckBox(chk_del_disk)

        btn_cancel = msg.addButton("Abbrechen", QMessageBox.RejectRole)
        btn_del = msg.addButton("Entfernen", QMessageBox.AcceptRole)
        btn_del.setStyleSheet("background-color: #DA3633; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        msg.exec()

        if msg.clickedButton() == btn_del:
            delete_file = chk_del_disk.isChecked()
            delete_book_extract(extract_id, delete_file=delete_file)
            self._refresh_extracts_list()

    def _delete_all_extracts_prompt(self) -> None:
        bid = str(self.book.get("id", ""))
        if not bid:
            return
        extracts = get_book_extracts(bid)
        if not extracts:
            return

        book_title = self.book.get("title", "diesem Buch")
        count = len(extracts)

        msg = QMessageBox(self)
        msg.setWindowTitle("Alle Kapitel entfernen")
        msg.setIcon(QMessageBox.Warning)
        msg.setText(f"Möchtest du wirklich alle <b>{count} angehängten Kapitel</b> von <i>{book_title}</i> entfernen?")
        msg.setInformativeText("Die Verknüpfungen in der Bibliothek werden vollständig gelöscht.")

        chk_del_folder = QCheckBox("Auch PDF-Dateien und den erstellten Kapitel-Ordner von der Festplatte löschen")
        chk_del_folder.setChecked(True)
        chk_del_folder.setStyleSheet("color: #FF7B72; font-weight: bold; margin-top: 10px;")
        msg.setCheckBox(chk_del_folder)

        btn_cancel = msg.addButton("Abbrechen", QMessageBox.RejectRole)
        btn_del_all = msg.addButton("Alle löschen", QMessageBox.AcceptRole)
        btn_del_all.setStyleSheet("background-color: #DA3633; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        msg.exec()

        if msg.clickedButton() == btn_del_all:
            delete_folder = chk_del_folder.isChecked()
            delete_all_book_extracts(bid, delete_folder=delete_folder)
            self._refresh_extracts_list()

    def _open_extracts_folder(self) -> None:
        """Opens the folder containing the extracts for easy drag-and-drop into NotebookLM."""
        bid = str(self.book.get("id", ""))
        extracts = get_book_extracts(bid) if bid else []
        folder = None
        for ext in extracts:
            fp = ext.get("file_path", "")
            if fp and os.path.exists(fp):
                folder = os.path.dirname(fp)
                break
        if not folder:
            from core.config import get_books_storage_dir
            raw_stem = os.path.splitext(os.path.basename(self.book.get("file_path", "")))[0]
            cand = os.path.join(get_books_storage_dir(), f"{raw_stem}_Kapitel")
            folder = cand if os.path.isdir(cand) else get_books_storage_dir()

        if folder and os.path.exists(folder):
            subprocess.run(["explorer", os.path.normpath(folder)])

    def closeEvent(self, event):
        if self._toc_thread and self._toc_thread.isRunning():
            self._toc_thread.quit()
        super().closeEvent(event)

    def reject(self):
        if self._toc_thread and self._toc_thread.isRunning():
            self._toc_thread.quit()
        super().reject()

