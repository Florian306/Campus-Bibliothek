"""Dialog for extracting pages/chapters from a PDF (PDF24 style).
Allows human-readable page ranges, 1-click Table of Contents (TOC) chapter selection,
automatic chapter-aware filename generation, and post-extraction launch options.
"""

import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QFrame,
    QFileDialog,
    QMessageBox,
    QCheckBox,
    QSplitter,
    QWidget,
    QProgressBar,
    QProgressDialog,
    QApplication,
    QInputDialog,
)

from core.pdf_tools import (
    parse_page_ranges,
    extract_pdf_pages,
    get_pdf_page_count,
    compute_chapter_spans,
    compute_chunk_spans,
    detect_printed_toc,
    batch_extract_all_chapters,
)
from core.config import get_books_storage_dir
from core.delta_scanner import index_single_book_file
from core.library_db import open_pdf_in_edge, add_book_extract
from ai.pdf_extractor import extract_pdf_toc
from ui.qt.icons import create_vector_icon
from ui.qt.theme import NoFocusItemDelegate


class PdfExtractDialog(QDialog):
    """Modern modal dialog for selective PDF page/chapter extraction with rich UX."""

    def __init__(self, book: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.book = book
        self.source_path = book.get("file_path", "")
        try:
            self.total_pages = int(book.get("page_count") or 0)
        except (ValueError, TypeError):
            self.total_pages = 0
        if self.total_pages <= 0:
            self.total_pages = get_pdf_page_count(self.source_path)

        self.setWindowTitle(f"Seiten extrahieren – {book.get('title', 'Dokument')}")
        self.resize(840, 580)
        self.setMinimumSize(720, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #121722;
                border: 1px solid #283750;
            }
        """)

        self._build_ui()
        self._load_toc()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 18, 20, 18)
        root_layout.setSpacing(14)

        # 1. Header Card
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #162035, stop:1 #111827);
                border: 1px solid #233454;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(10, 6, 10, 6)
        h_layout.setSpacing(12)

        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_icon("book", "#58A6FF", 22).pixmap(22, 22))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        h_layout.addWidget(lbl_icon)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        lbl_title = QLabel(self.book.get("title", "Dokument"))
        lbl_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        title_layout.addWidget(lbl_title)

        author_str = self.book.get("author", "Unbekannt")
        lbl_sub = QLabel(f"Autor: {author_str} · Gesamtdokument: {self.total_pages} Seiten")
        lbl_sub.setFont(QFont("Segoe UI", 8))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        title_layout.addWidget(lbl_sub)
        h_layout.addLayout(title_layout, stretch=1)

        root_layout.addWidget(header_card)

        # 2. Main Content Splitter
        splitter = QSplitter(Qt.Horizontal)

        # Left: TOC Chapter Quick-Selector
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(6)

        toc_header_row = QHBoxLayout()
        self.lbl_toc = QLabel("📑 KAPITEL-SCHNELLAUSWAHL (TOC):")
        self.lbl_toc.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_toc.setStyleSheet("color: #58A6FF; letter-spacing: 0.5px;")
        toc_header_row.addWidget(self.lbl_toc, stretch=1)

        self.btn_scan_toc = QPushButton("🔍 Seiten nach Inhaltsverzeichnis scannen")
        self.btn_scan_toc.setFont(QFont("Segoe UI", 8))
        self.btn_scan_toc.setCursor(Qt.PointingHandCursor)
        self.btn_scan_toc.setStyleSheet("""
            QPushButton {
                background-color: #162035;
                color: #79C0FF;
                border: 1px solid #283C64;
                border-radius: 4px;
                padding: 3px 8px;
            }
            QPushButton:hover {
                background-color: #1F2D48;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        self.btn_scan_toc.setToolTip("Durchsucht die ersten 25 Seiten nach gedruckten Inhaltsverzeichnissen & Überschriften")
        self.btn_scan_toc.clicked.connect(self._on_scan_printed_toc_clicked)
        self.btn_scan_toc.setVisible(False)
        toc_header_row.addWidget(self.btn_scan_toc)

        left_layout.addLayout(toc_header_row)

        self.tree_toc = QTreeWidget()
        self.tree_toc.setHeaderLabels(["Kapitel", "Seitenbereich", "Umfang"])
        self.tree_toc.setItemDelegate(NoFocusItemDelegate())
        self.tree_toc.setStyleSheet("""
            QTreeWidget {
                background-color: #0B0F19;
                border: 1px solid #1E2B45;
                border-radius: 6px;
                color: #C9D1D9;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 11px;
            }
            QTreeWidget::item {
                padding: 5px 6px;
            }
            QTreeWidget::item:hover {
                background-color: #162238;
                color: #58A6FF;
            }
            QTreeWidget::item:selected {
                background-color: #1F6FEB;
                color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #131A29;
                color: #8B949E;
                padding: 4px 6px;
                border: none;
                border-bottom: 1px solid #1E2B45;
                font-size: 10px;
                font-weight: bold;
            }
        """)
        self.tree_toc.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree_toc.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree_toc.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        
        # Connect both single-click and double-click / selection changed for maximum ease of use
        self.tree_toc.itemClicked.connect(self._on_toc_item_selected)
        self.tree_toc.currentItemChanged.connect(lambda cur, prev: self._on_toc_item_selected(cur) if cur else None)
        left_layout.addWidget(self.tree_toc)

        lbl_hint = QLabel("💡 1 Klick auf ein Kapitel wählt den gesamten Bereich & benennt die Datei automatisch.")
        lbl_hint.setFont(QFont("Segoe UI", 8))
        lbl_hint.setStyleSheet("color: #6E7681;")
        lbl_hint.setWordWrap(True)
        left_layout.addWidget(lbl_hint)

        # Batch Operations Row (Split by TOC or Split by Pages)
        batch_btns_layout = QVBoxLayout()
        batch_btns_layout.setSpacing(6)

        # Batch Chapter Split Button
        self.btn_batch_split = QPushButton("  ⚡ Alle Kapitel einzeln extrahieren & anheften")
        self.btn_batch_split.setIcon(create_vector_icon("download", "#FFFFFF", 14))
        self.btn_batch_split.setIconSize(QSize(14, 14))
        self.btn_batch_split.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_batch_split.setFixedHeight(34)
        self.btn_batch_split.setCursor(Qt.PointingHandCursor)
        self.btn_batch_split.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #8957E5);
                color: #FFFFFF;
                border: 1px solid #8957E5;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388BFD, stop:1 #A371F7);
                border-color: #A371F7;
            }
            QPushButton:disabled {
                background: #161D2C;
                color: #6E7681;
                border-color: #232F48;
            }
        """)
        self.btn_batch_split.setToolTip("Zerlegt das Buch vollautomatisch anhand des Inhaltsverzeichnisses in einzelne PDF-Kapiteldateien und heftet alle an dieses Buch an.")
        self.btn_batch_split.clicked.connect(self._on_batch_split_clicked)
        batch_btns_layout.addWidget(self.btn_batch_split)

        # Chunk Split Button for documents without TOC or for NotebookLM
        self.btn_chunk_split = QPushButton("  📦 In gleichmäßige Abschnitte zerlegen (z. B. 30 S. für KI)")
        self.btn_chunk_split.setIcon(create_vector_icon("library", "#C9D1D9", 13))
        self.btn_chunk_split.setIconSize(QSize(14, 14))
        self.btn_chunk_split.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_chunk_split.setFixedHeight(28)
        self.btn_chunk_split.setCursor(Qt.PointingHandCursor)
        self.btn_chunk_split.setStyleSheet("""
            QPushButton {
                background-color: #162035;
                color: #C9D1D9;
                border: 1px solid #2B3D5E;
                border-radius: 6px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #1F2D48;
                border-color: #58A6FF;
                color: #58A6FF;
            }
        """)
        self.btn_chunk_split.setToolTip("Teilt das Dokument in gleich große Häppchen (z. B. 20, 30 oder 50 Seiten) – perfekt für NotebookLM, ChatGPT oder Skripte ohne TOC.")
        self.btn_chunk_split.clicked.connect(self._on_chunk_split_clicked)
        batch_btns_layout.addWidget(self.btn_chunk_split)

        left_layout.addLayout(batch_btns_layout)

        splitter.addWidget(left_widget)

        # Right: Page Range Input & Configuration
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        lbl_range_title = QLabel("✂ SEITENBEREICH EINGEBEN:")
        lbl_range_title.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_range_title.setStyleSheet("color: #58A6FF; letter-spacing: 0.5px;")
        right_layout.addWidget(lbl_range_title)

        self.input_pages = QLineEdit()
        self.input_pages.setPlaceholderText("z. B. 1-15, 24, 30-45")
        self.input_pages.setFont(QFont("Segoe UI", 12))
        self.input_pages.setFixedHeight(40)
        self.input_pages.setStyleSheet("""
            QLineEdit {
                background-color: #0A0E18;
                border: 1.5px solid #283750;
                border-radius: 6px;
                color: #58A6FF;
                font-weight: bold;
                padding: 0 12px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
                background-color: #0D1424;
            }
        """)
        self.input_pages.textChanged.connect(self._on_page_input_changed)
        right_layout.addWidget(self.input_pages)

        # Quick preset buttons (e.g. "Erste 10 Seiten", "Alle")
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)

        btn_first10 = QPushButton("Erste 10 S.")
        btn_first10.setFixedHeight(26)
        btn_first10.setFont(QFont("Segoe UI", 8))
        btn_first10.setCursor(Qt.PointingHandCursor)
        btn_first10.setStyleSheet("background-color: #162035; color: #8B949E; border: 1px solid #243554; border-radius: 4px;")
        btn_first10.clicked.connect(lambda: self._apply_preset_range(1, min(10, self.total_pages), "Erste 10 Seiten"))
        preset_row.addWidget(btn_first10)

        btn_first20 = QPushButton("Erste 20 S.")
        btn_first20.setFixedHeight(26)
        btn_first20.setFont(QFont("Segoe UI", 8))
        btn_first20.setCursor(Qt.PointingHandCursor)
        btn_first20.setStyleSheet("background-color: #162035; color: #8B949E; border: 1px solid #243554; border-radius: 4px;")
        btn_first20.clicked.connect(lambda: self._apply_preset_range(1, min(20, self.total_pages), "Erste 20 Seiten"))
        preset_row.addWidget(btn_first20)

        btn_all = QPushButton("Alle Seiten")
        btn_all.setFixedHeight(26)
        btn_all.setFont(QFont("Segoe UI", 8))
        btn_all.setCursor(Qt.PointingHandCursor)
        btn_all.setStyleSheet("background-color: #162035; color: #8B949E; border: 1px solid #243554; border-radius: 4px;")
        btn_all.clicked.connect(lambda: self._apply_preset_range(1, self.total_pages, "Gesamt"))
        preset_row.addWidget(btn_all)

        btn_chunk30 = QPushButton("1–30")
        btn_chunk30.setFixedHeight(26)
        btn_chunk30.setFont(QFont("Segoe UI", 8))
        btn_chunk30.setCursor(Qt.PointingHandCursor)
        btn_chunk30.setStyleSheet("background-color: #162035; color: #8B949E; border: 1px solid #243554; border-radius: 4px;")
        btn_chunk30.clicked.connect(lambda: self._apply_preset_range(1, min(30, self.total_pages), "Teil 1"))
        preset_row.addWidget(btn_chunk30)

        preset_row.addStretch()
        right_layout.addLayout(preset_row)

        # Status badge for selection count
        self.lbl_selected_status = QLabel("Ausgewählt: 0 Seiten")
        self.lbl_selected_status.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_selected_status.setStyleSheet("""
            background-color: #111A2E;
            color: #8B949E;
            border: 1px solid #1E2D4A;
            border-radius: 4px;
            padding: 6px 12px;
        """)
        right_layout.addWidget(self.lbl_selected_status)

        # Output options
        opt_box = QFrame()
        opt_box.setStyleSheet("""
            QFrame {
                background-color: #0E1524;
                border: 1px solid #1F2D47;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        opt_layout = QVBoxLayout(opt_box)
        opt_layout.setSpacing(8)

        lbl_dest = QLabel("ZIELDATEINAME:")
        lbl_dest.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_dest.setStyleSheet("color: #8B949E; border: none;")
        opt_layout.addWidget(lbl_dest)

        raw_stem = os.path.splitext(os.path.basename(self.source_path))[0]
        self._default_base_stem = raw_stem
        self.input_filename = QLineEdit(f"{raw_stem} (Auszug).pdf")
        self.input_filename.setFont(QFont("Segoe UI", 9))
        self.input_filename.setFixedHeight(32)
        self.input_filename.setStyleSheet("""
            QLineEdit {
                background-color: #0A0E18;
                border: 1px solid #283750;
                border-radius: 4px;
                color: #F0F6FC;
                padding: 0 8px;
            }
        """)
        opt_layout.addWidget(self.input_filename)

        self.chk_attach_book = QCheckBox("📎 Als Kapitel an dieses Buch heften (empfohlen)")
        self.chk_attach_book.setChecked(True)
        self.chk_attach_book.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.chk_attach_book.setStyleSheet("color: #58A6FF; border: none;")
        self.chk_attach_book.setToolTip("Hängt den Auszug als Kapitel direkt in die Details dieses Buches ein, ohne den Hauptkatalog zu überfüllen.")
        opt_layout.addWidget(self.chk_attach_book)

        self.chk_on_desk = QCheckBox("📌 Direkt auf den Schreibtisch legen")
        self.chk_on_desk.setChecked(True)
        self.chk_on_desk.setFont(QFont("Segoe UI", 9))
        self.chk_on_desk.setStyleSheet("color: #C9D1D9; border: none; margin-left: 18px;")
        opt_layout.addWidget(self.chk_on_desk)

        self.chk_attach_book.toggled.connect(self._on_attach_toggled)

        self.chk_add_library = QCheckBox("📥 Als eigenständiges Buch in Campus Library aufnehmen")
        self.chk_add_library.setChecked(False)
        self.chk_add_library.setFont(QFont("Segoe UI", 8))
        self.chk_add_library.setStyleSheet("color: #8B949E; border: none;")
        opt_layout.addWidget(self.chk_add_library)

        right_layout.addWidget(opt_box)
        right_layout.addStretch()

        splitter.addWidget(right_widget)
        splitter.setSizes([380, 420])
        root_layout.addWidget(splitter, stretch=1)

        # 3. Actions Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setFont(QFont("Segoe UI", 9))
        btn_cancel.setFixedHeight(34)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #161F32;
                color: #8B949E;
                border: 1px solid #25334E;
                border-radius: 6px;
                padding: 0 16px;
            }
            QPushButton:hover {
                color: #F0F6FC;
                border-color: #58A6FF;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        actions_row.addWidget(btn_cancel)

        actions_row.addStretch()

        self.btn_extract = QPushButton("  ✂ Jetzt extrahieren")
        self.btn_extract.setIcon(create_vector_icon("download", "#FFFFFF", 14))
        self.btn_extract.setIconSize(QSize(14, 14))
        self.btn_extract.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_extract.setFixedHeight(34)
        self.btn_extract.setCursor(Qt.PointingHandCursor)
        self.btn_extract.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 0 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388BFD, stop:1 #58A6FF);
            }
            QPushButton:disabled {
                background: #1B2335;
                color: #6E7681;
                border-color: #242D40;
            }
        """)
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self._on_extract_clicked)
        actions_row.addWidget(self.btn_extract)

        root_layout.addLayout(actions_row)

    def _apply_preset_range(self, start_p: int, end_p: int, label: str) -> None:
        """Applies a preset range and updates filename."""
        self.input_pages.setText(f"{start_p}-{end_p}" if start_p != end_p else str(start_p))
        clean_lbl = re.sub(r'[\\/*?:"<>|]', "", label).strip()
        self.input_filename.setText(f"{self._default_base_stem} ({clean_lbl}).pdf")

    def _load_toc(self, custom_toc: Optional[List[Tuple[int, str, int]]] = None) -> None:
        """Loads bookmarks/TOC into tree widget with precomputed chapter spans."""
        self.tree_toc.clear()
        if not self.source_path or not os.path.isfile(self.source_path):
            return

        try:
            toc = custom_toc if custom_toc is not None else extract_pdf_toc(self.source_path)
            if not toc:
                self.btn_scan_toc.setVisible(True)
                self.btn_batch_split.setEnabled(False)
                item = QTreeWidgetItem(["Kein Inhaltsverzeichnis hinterlegt", "-", "-"])
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                self.tree_toc.addTopLevelItem(item)
                return

            self.btn_scan_toc.setVisible(False)
            self.btn_batch_split.setEnabled(True)
            self._toc_list = toc
            for idx, entry in enumerate(toc):
                lvl, title, start_page = entry
                end_page = self._compute_chapter_end_page(idx, lvl, start_page)
                
                span_str = f"S. {start_page}–{end_page}" if start_page != end_page else f"S. {start_page}"
                pages_count = (end_page - start_page + 1)
                count_str = f"{pages_count} S."

                # Indentation visually matching hierarchy level
                indent_prefix = "  " * max(0, lvl - 1)
                display_title = f"{indent_prefix}{title}"

                item = QTreeWidgetItem([display_title, span_str, count_str])
                item.setData(0, Qt.UserRole, (idx, start_page, end_page, title))
                self.tree_toc.addTopLevelItem(item)
        except Exception:
            item = QTreeWidgetItem(["Inhaltsverzeichnis konnte nicht gelesen werden", "-", "-"])
            self.tree_toc.addTopLevelItem(item)

    def _compute_chapter_end_page(self, idx: int, current_level: int, start_page: int) -> int:
        """Determines the boundary end page of a chapter based on tree hierarchy."""
        end_page = self.total_pages
        if not hasattr(self, '_toc_list'):
            return end_page

        for next_idx in range(idx + 1, len(self._toc_list)):
            next_lvl, next_title, next_p = self._toc_list[next_idx]
            if next_lvl <= current_level and next_p > start_page:
                end_page = next_p - 1
                break

        # Bounds sanity
        start_page = max(1, min(start_page, self.total_pages))
        end_page = max(start_page, min(end_page, self.total_pages))
        return end_page

    def _on_toc_item_selected(self, item: QTreeWidgetItem) -> None:
        """Calculates page span for clicked chapter, updates input and auto-generates clean filename."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        idx, start_page, end_page, title = data

        # Set range in input
        if start_page == end_page:
            self.input_pages.setText(str(start_page))
        else:
            self.input_pages.setText(f"{start_page}-{end_page}")

        # Smart Auto-Naming: e.g. "Thermodynamik - Kap. 3 Kreisprozesse.pdf"
        clean_title = re.sub(r'[\r\n\t]+', ' ', title).strip()
        clean_title = re.sub(r'^[0-9\.\s_-]+', '', clean_title).strip() or clean_title
        clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_title)[:60].strip()

        if clean_title:
            new_fname = f"{self._default_base_stem} - {clean_title}.pdf"
        else:
            new_fname = f"{self._default_base_stem} (S. {start_page}-{end_page}).pdf"

        self.input_filename.setText(new_fname)

    def _on_page_input_changed(self, text: str) -> None:
        pages = parse_page_ranges(text, self.total_pages)
        count = len(pages)
        if count > 0:
            self.lbl_selected_status.setText(f"✓ Ausgewählt: {count} Seiten")
            self.lbl_selected_status.setStyleSheet("""
                background-color: #12281D;
                color: #3FB950;
                border: 1px solid #238636;
                border-radius: 4px;
                padding: 6px 12px;
            """)
            self.btn_extract.setEnabled(True)
        else:
            self.lbl_selected_status.setText("Ausgewählt: 0 Seiten")
            self.lbl_selected_status.setStyleSheet("""
                background-color: #111A2E;
                color: #8B949E;
                border: 1px solid #1E2D4A;
                border-radius: 4px;
                padding: 6px 12px;
            """)
            self.btn_extract.setEnabled(False)

    def _on_attach_toggled(self, checked: bool) -> None:
        self.chk_on_desk.setEnabled(checked)
        if not checked:
            self.chk_on_desk.setChecked(False)

    def _on_extract_clicked(self) -> None:
        pages = parse_page_ranges(self.input_pages.text(), self.total_pages)
        if not pages:
            QMessageBox.warning(self, "Ungültige Auswahl", "Bitte gib mindestens eine gültige Seitenzahl an.")
            return

        out_fname = self.input_filename.text().strip()
        if not out_fname.lower().endswith(".pdf"):
            out_fname += ".pdf"

        # Ask destination folder or default to books storage
        default_dir = get_books_storage_dir()
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Auszug speichern unter",
            os.path.join(default_dir, out_fname),
            "PDF-Dokumente (*.pdf)"
        )
        if not target_path:
            return

        success, msg = extract_pdf_pages(self.source_path, pages, target_path)
        if not success:
            QMessageBox.critical(self, "Fehler", msg)
            return

        # 1. Attach directly to book if requested
        if self.chk_attach_book.isChecked():
            bid = str(self.book.get("id", ""))
            if bid:
                chapter_title = os.path.splitext(out_fname)[0]
                p_range_str = self.input_pages.text().strip()
                p_count = len(pages)
                f_size = os.path.getsize(target_path) if os.path.isfile(target_path) else 0
                put_on_desk = self.chk_on_desk.isChecked()
                add_book_extract(
                    parent_book_id=bid,
                    title=chapter_title,
                    file_path=target_path,
                    page_range=p_range_str,
                    page_count=p_count,
                    file_size=f_size,
                    on_desk=put_on_desk
                )
                msg += f"\n\n📎 Als Kapitel direkt an '{self.book.get('title', 'Dokument')}' angehängt!"
                if put_on_desk:
                    msg += " Und auf den Schreibtisch gelegt."

        # 2. Optionally index into library database as standalone book
        if self.chk_add_library.isChecked():
            try:
                indexed = index_single_book_file(target_path)
                if indexed:
                    msg += f"\n\n✓ Auch als eigenständiges Buch in Campus-Bibliothek aufgenommen unter '{indexed.get('categories_str', 'Allgemein')}'."
            except Exception as e:
                msg += f"\n\n(Hinweis: Konnte nicht in DB indiziert werden: {e})"

        # Rich completion dialog with direct launch options
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Extraktion erfolgreich")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(msg)

        btn_open_pdf = msg_box.addButton("📖 PDF öffnen", QMessageBox.ActionRole)
        btn_open_pdf.setStyleSheet("background-color: #1F6FEB; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        btn_show_folder = msg_box.addButton("📂 Im Ordner anzeigen (z.B. für NotebookLM)", QMessageBox.ActionRole)
        btn_show_folder.setStyleSheet("background-color: #21262D; color: #C9D1D9; padding: 6px 14px; border-radius: 4px;")

        btn_ok = msg_box.addButton("Schließen", QMessageBox.AcceptRole)

        msg_box.exec()

        if msg_box.clickedButton() == btn_open_pdf:
            open_pdf_in_edge(target_path)
        elif msg_box.clickedButton() == btn_show_folder:
            subprocess.run(["explorer", "/select,", os.path.normpath(target_path)])

        self.accept()

    def _on_batch_split_clicked(self) -> None:
        """Splits the entire document chapter by chapter based on TOC and attaches all to this book."""
        if not hasattr(self, '_toc_list') or not self._toc_list:
            QMessageBox.warning(
                self,
                "Kein Inhaltsverzeichnis",
                "Dieses PDF besitzt keine digitalen Lesezeichen / Kapitelmarken im Inhaltsverzeichnis.\n"
                "Ein automatischer Batch-Split ist nur bei Dokumenten mit Inhaltsverzeichnis möglich."
            )
            return

        # Precompute spans for Level 1 (main chapters)
        spans = compute_chapter_spans(self._toc_list, self.total_pages, max_level=1)
        if not spans:
            QMessageBox.warning(self, "Keine Kapitel", "Es konnten keine Hauptkapitel abgegrenzt werden.")
            return

        # Confirmation & Customization Prompt
        count = len(spans)
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Automatischen Kapitel-Split starten")
        confirm.setIcon(QMessageBox.Question)
        confirm.setText(
            f"Möchtest du das Dokument <b>{self.book.get('title', 'Buch')}</b> wirklich in "
            f"<b>{count} einzelne Kapitel-Dateien</b> zerlegen?"
        )
        confirm.setInformativeText(
            "Jedes Kapitel wird als eigenständige PDF gespeichert und direkt an dieses Buch geheftet.\n"
            "Ideal für NotebookLM, ChatGPT oder fokussiertes Lernen."
        )

        chk_desk = QCheckBox("Das 1. Kapitel direkt auf den Schreibtisch legen")
        chk_desk.setChecked(True)
        chk_desk.setStyleSheet("color: #58A6FF; font-weight: bold; margin-top: 8px;")
        confirm.setCheckBox(chk_desk)

        btn_cancel = confirm.addButton("Abbrechen", QMessageBox.RejectRole)
        btn_start = confirm.addButton(f"⚡ {count} Kapitel jetzt extrahieren", QMessageBox.AcceptRole)
        btn_start.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #8957E5); color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        confirm.exec()
        if confirm.clickedButton() != btn_start:
            return

        put_first_on_desk = chk_desk.isChecked()

        # Target directory: Dedicated subfolder in storage
        raw_stem = os.path.splitext(os.path.basename(self.source_path))[0]
        safe_stem = re.sub(r'[\\/*?:"<>|]', "", raw_stem)[:60].strip() or "Buch"
        default_dir = os.path.join(get_books_storage_dir(), f"{safe_stem}_Kapitel")

        # Create progress dialog
        prog = QProgressDialog("Kapitel werden extrahiert...", "Abbrechen", 0, count, self)
        prog.setWindowTitle("Kapitel-Split läuft")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        prog.setStyleSheet("""
            QProgressDialog {
                background-color: #121826;
                color: #F0F6FC;
                border: 1px solid #283750;
            }
            QLabel {
                color: #C9D1D9;
            }
            QProgressBar {
                background-color: #0A0E18;
                border: 1px solid #232F48;
                border-radius: 4px;
                text-align: center;
                color: #F0F6FC;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #8957E5);
                border-radius: 3px;
            }
            QPushButton {
                background-color: #1F293D;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 4px 12px;
            }
        """)

        def _update_prog(current, total, current_title):
            prog.setValue(current)
            prog.setLabelText(f"Extrahiere Kapitel {current} von {total}:\n{current_title[:55]}...")
            QApplication.processEvents()

        # Run batch extraction
        extracted_list = batch_extract_all_chapters(
            source_pdf_path=self.source_path,
            output_dir=default_dir,
            base_prefix=safe_stem,
            spans=spans,
            progress_callback=_update_prog
        )

        prog.close()

        if not extracted_list:
            QMessageBox.critical(self, "Fehler", "Die Kapitel konnten nicht extrahiert werden.")
            return

        # Register all into book_extracts
        bid = str(self.book.get("id", ""))
        if bid:
            for idx, item in enumerate(extracted_list):
                on_desk_val = put_first_on_desk if idx == 0 else False
                add_book_extract(
                    parent_book_id=bid,
                    title=item["title"],
                    file_path=item["file_path"],
                    page_range=item["page_range"],
                    page_count=item["page_count"],
                    file_size=item["file_size"],
                    on_desk=on_desk_val
                )

        # Success message with explorer shortcut
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Kapitel-Split erfolgreich abgeschlossen")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(f"🎉 Erfolgreich <b>{len(extracted_list)} Kapitel</b> extrahiert und an das Buch geheftet!")
        msg_box.setInformativeText(f"Gespeichert im Ordner:\n{default_dir}")

        btn_show_folder = msg_box.addButton("📂 Ordner öffnen (für NotebookLM)", QMessageBox.ActionRole)
        btn_show_folder.setStyleSheet("background-color: #1F6FEB; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        btn_close = msg_box.addButton("Fertig", QMessageBox.AcceptRole)

        msg_box.exec()

        if msg_box.clickedButton() == btn_show_folder:
            subprocess.run(["explorer", os.path.normpath(default_dir)])

        self.accept()

    def _on_scan_printed_toc_clicked(self) -> None:
        """Scans the beginning of the PDF using heuristics to find printed TOC entries and populates the tree."""
        if not self.source_path or not os.path.isfile(self.source_path):
            QMessageBox.warning(self, "Datei nicht gefunden", "Das PDF-Dokument konnte nicht gefunden werden.")
            return

        # Show busy cursor / scanning prompt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            detected = detect_printed_toc(self.source_path, max_scan_pages=30)
        finally:
            QApplication.restoreOverrideCursor()

        if not detected:
            QMessageBox.information(
                self,
                "Kein gedrucktes Inhaltsverzeichnis erkannt",
                "Auf den ersten 30 Seiten konnte kein typisches Inhaltsverzeichnis mit Seitenzahlen erkannt werden.\n\n"
                "💡 Tipp: Du kannst stattdessen unten auf '📦 In gleichmäßige Abschnitte zerlegen' klicken, "
                "um das PDF z. B. in handliche 30-Seiten-Kapitel für NotebookLM oder KI-Analysen aufzuteilen."
            )
            return

        self._load_toc(custom_toc=detected)
        QMessageBox.information(
            self,
            "Gedrucktes Inhaltsverzeichnis erkannt",
            f"🎉 Es wurden <b>{len(detected)} Kapitelüberschriften</b> auf den ersten Seiten erkannt!\n"
            "Die Kapitel stehen dir jetzt zur Schnellauswahl und zum automatischen Batch-Split zur Verfügung."
        )

    def _on_chunk_split_clicked(self) -> None:
        """Splits the entire document into equal-sized page chunks (e.g. 25, 30 or 50 pages)."""
        if self.total_pages <= 0:
            QMessageBox.warning(self, "Keine Seiten", "Das Dokument enthält keine gültigen Seiten.")
            return

        # Ask user for chunk size
        default_size = 30
        chunk_size, ok = QInputDialog.getInt(
            self,
            "Dokument in Abschnitte zerlegen",
            f"Dokumentenumfang: {self.total_pages} Seiten.\n"
            "Wie viele Seiten soll jeder Abschnitt umfassen (z. B. 20, 30, 50)?",
            default_size, 5, 200, 5
        )
        if not ok:
            return

        spans = compute_chunk_spans(self.total_pages, chunk_size=chunk_size)
        if not spans:
            QMessageBox.warning(self, "Fehler", "Abschnitte konnten nicht berechnet werden.")
            return

        count = len(spans)
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Abschnitts-Split starten")
        confirm.setIcon(QMessageBox.Question)
        confirm.setText(
            f"Möchtest du <b>{self.book.get('title', 'Dokument')}</b> in "
            f"<b>{count} Abschnitte</b> (jeweils ca. {chunk_size} Seiten) zerlegen?"
        )
        confirm.setInformativeText(
            "Jeder Abschnitt wird als eigenständige PDF gespeichert und direkt an dieses Buch geheftet.\n"
            "Ideal für NotebookLM, KI-Uploads oder fokussiertes Lernen."
        )

        chk_desk = QCheckBox("Den 1. Abschnitt direkt auf den Schreibtisch legen")
        chk_desk.setChecked(True)
        chk_desk.setStyleSheet("color: #58A6FF; font-weight: bold; margin-top: 8px;")
        confirm.setCheckBox(chk_desk)

        btn_cancel = confirm.addButton("Abbrechen", QMessageBox.RejectRole)
        btn_start = confirm.addButton(f"📦 {count} Abschnitte jetzt erstellen", QMessageBox.AcceptRole)
        btn_start.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #8957E5); color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        confirm.exec()
        if confirm.clickedButton() != btn_start:
            return

        put_first_on_desk = chk_desk.isChecked()

        raw_stem = os.path.splitext(os.path.basename(self.source_path))[0]
        safe_stem = re.sub(r'[\\/*?:"<>|]', "", raw_stem)[:60].strip() or "Buch"
        default_dir = os.path.join(get_books_storage_dir(), f"{safe_stem}_Abschnitte")

        prog = QProgressDialog("Abschnitte werden extrahiert...", "Abbrechen", 0, count, self)
        prog.setWindowTitle("Abschnitts-Split läuft")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        prog.setStyleSheet("""
            QProgressDialog {
                background-color: #121826;
                color: #F0F6FC;
                border: 1px solid #283750;
            }
            QLabel {
                color: #C9D1D9;
            }
            QProgressBar {
                background-color: #0A0E18;
                border: 1px solid #232F48;
                border-radius: 4px;
                text-align: center;
                color: #F0F6FC;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #8957E5);
                border-radius: 3px;
            }
            QPushButton {
                background-color: #1F293D;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 4px 12px;
            }
        """)

        def _update_prog(current, total, current_title):
            prog.setValue(current)
            prog.setLabelText(f"Erstelle Abschnitt {current} von {total}:\n{current_title[:55]}...")
            QApplication.processEvents()

        extracted_list = batch_extract_all_chapters(
            source_pdf_path=self.source_path,
            output_dir=default_dir,
            base_prefix=safe_stem,
            spans=spans,
            progress_callback=_update_prog
        )

        prog.close()

        if not extracted_list:
            QMessageBox.critical(self, "Fehler", "Die Abschnitte konnten nicht extrahiert werden.")
            return

        bid = str(self.book.get("id", ""))
        if bid:
            for idx, item in enumerate(extracted_list):
                on_desk_val = put_first_on_desk if idx == 0 else False
                add_book_extract(
                    parent_book_id=bid,
                    title=item["title"],
                    file_path=item["file_path"],
                    page_range=item["page_range"],
                    page_count=item["page_count"],
                    file_size=item["file_size"],
                    on_desk=on_desk_val
                )

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Abschnitte erfolgreich erstellt")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(f"🎉 Erfolgreich <b>{len(extracted_list)} Abschnitte</b> extrahiert und an das Buch geheftet!")
        msg_box.setInformativeText(f"Gespeichert im Ordner:\n{default_dir}")

        btn_show_folder = msg_box.addButton("📂 Ordner öffnen (für NotebookLM)", QMessageBox.ActionRole)
        btn_show_folder.setStyleSheet("background-color: #1F6FEB; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        btn_close = msg_box.addButton("Fertig", QMessageBox.AcceptRole)

        msg_box.exec()

        if msg_box.clickedButton() == btn_show_folder:
            subprocess.run(["explorer", os.path.normpath(default_dir)])

        self.accept()

