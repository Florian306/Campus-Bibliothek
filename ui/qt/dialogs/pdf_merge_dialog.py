"""Dialog for merging multiple PDF files / individual book chapters into a single book.
Provides natural chapter sorting (Frontmatter -> Chapters 1..N -> Backmatter),
interactive bookmark title editing, automatic hierarchical PDF Table of Contents (TOC) generation,
and direct indexing into the Campus Library or Inbox cleanup.
"""

import os
import re
import subprocess
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QDragEnterEvent, QDropEvent, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFrame,
    QFileDialog,
    QMessageBox,
    QCheckBox,
    QComboBox,
    QSplitter,
    QWidget,
    QProgressDialog,
    QApplication,
)

from core.pdf_tools import (
    get_pdf_page_count,
    suggest_chapter_sort_key,
    clean_chapter_bookmark_title,
    merge_pdf_files,
    parse_page_ranges,
)
from core.config import get_books_storage_dir, get_inbox_directory, load_config
from core.library_db import (
    upsert_book,
    get_category_counts,
    get_inbox_queue,
    delete_inbox_item,
    open_pdf_in_edge,
    toggle_desk_item,
)
from core.cover_manager import extract_and_cache_cover
from ai.pdf_extractor import (
    extract_visual_title_and_author,
    sanitize_author_string,
    extract_publication_year,
)
from ai.isbn_lookup import extract_isbns
from ai.categories import STANDARD_CATEGORIES
from core.delta_scanner import extract_edition_number
from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate


class PdfMergeDialog(QDialog):
    """Studio dialog for merging individual PDF chapters or documents into a complete textbook."""

    def __init__(
        self,
        initial_files: Optional[List[str]] = None,
        from_inbox: bool = False,
        default_doc_type: str = "book",
        base_book: Optional[Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.from_inbox = from_inbox
        self.default_doc_type = default_doc_type
        self.base_book = base_book
        self._items: List[Dict[str, Any]] = []
        self.merged_book_id: Optional[str] = None
        self.merged_file_path: Optional[str] = None

        self.setWindowTitle("PDF-Merge-Studio – Kapitel & PDFs zu Gesamtbuch zusammenführen")
        self.resize(1020, 680)
        self.setMinimumSize(860, 560)
        self.setAcceptDrops(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #0D121D;
                border: 1px solid #283750;
            }
        """)

        self._build_ui()

        # Preload initial files if provided
        if base_book and base_book.get("file_path") and os.path.isfile(base_book["file_path"]):
            self.add_files([base_book["file_path"]], auto_sort=False)
            self.input_title.setText(base_book.get("title", ""))
            self.input_author.setText(base_book.get("author", "Unbekannt"))
            cat = (base_book.get("primary_category") or "").strip()
            if cat:
                idx = self.combo_category.findText(cat)
                if idx >= 0:
                    self.combo_category.setCurrentIndex(idx)

        if initial_files:
            self.add_files(initial_files, auto_sort=True)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        # -------------------------------------------------------------
        # 1. Header Banner
        # -------------------------------------------------------------
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #151F34, stop:1 #101726);
                border: 1px solid #263859;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        h_lay = QHBoxLayout(header_card)
        h_lay.setContentsMargins(12, 6, 12, 6)
        h_lay.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(create_vector_pixmap("merge", "#58A6FF", 26))
        icon_lbl.setFixedSize(42, 42)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: #182640; border: 1px solid #2E456E; border-radius: 8px;")
        h_lay.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        lbl_h1 = QLabel("PDF-Merge-Studio & Kapitel-Assembler")
        lbl_h1.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_h1.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        title_col.addWidget(lbl_h1)

        lbl_sub = QLabel(
            "Fügt einzelne Buchkapitel, Vorwort und Anhänge verlustfrei zusammen – inkl. automatischer PDF-Lesezeichen (TOC)."
        )
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        title_col.addWidget(lbl_sub)
        h_lay.addLayout(title_col, stretch=1)

        self.lbl_summary_badge = QLabel("0 Dateien · 0 Seiten")
        self.lbl_summary_badge.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_summary_badge.setStyleSheet("""
            background-color: #13223E;
            color: #58A6FF;
            border: 1px solid #2B487A;
            border-radius: 8px;
            padding: 6px 12px;
        """)
        h_lay.addWidget(self.lbl_summary_badge)

        root.addWidget(header_card)

        # -------------------------------------------------------------
        # 2. Main Splitter (Left: Chapter List & Toolbar, Right: Book Metadata & Options)
        # -------------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)

        # --- LEFT PANEL: Chapter Table & Ordering ---
        left_panel = QWidget()
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(0, 0, 10, 0)
        left_lay.setSpacing(8)

        # Toolbar above table
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        btn_add_files = QPushButton("  Dateien hinzufügen...")
        btn_add_files.setIcon(create_vector_icon("plus", "#FFFFFF", 13))
        btn_add_files.setCursor(Qt.PointingHandCursor)
        btn_add_files.setFixedHeight(32)
        btn_add_files.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: 1px solid #58A6FF;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2B7BF4, stop:1 #58A6FF);
            }
        """)
        btn_add_files.clicked.connect(self._browse_files)
        toolbar.addWidget(btn_add_files)

        btn_add_folder = QPushButton("  Kapitel-Ordner laden...")
        btn_add_folder.setIcon(create_vector_icon("library", "#58A6FF", 13))
        btn_add_folder.setCursor(Qt.PointingHandCursor)
        btn_add_folder.setFixedHeight(32)
        btn_add_folder.setStyleSheet(self._secondary_btn_style())
        btn_add_folder.setToolTip("Lädt alle PDF-Dateien aus einem ausgewählten Ordner")
        btn_add_folder.clicked.connect(self._browse_folder)
        toolbar.addWidget(btn_add_folder)

        btn_load_inbox = QPushButton("  Aus _Inbox laden")
        btn_load_inbox.setIcon(create_vector_icon("inbox", "#58A6FF", 13))
        btn_load_inbox.setCursor(Qt.PointingHandCursor)
        btn_load_inbox.setFixedHeight(32)
        btn_load_inbox.setStyleSheet(self._secondary_btn_style())
        btn_load_inbox.setToolTip("Lädt alle aktuell im Posteingang (_Inbox) liegenden PDF-Dateien")
        btn_load_inbox.clicked.connect(self._load_from_inbox)
        toolbar.addWidget(btn_load_inbox)

        toolbar.addStretch()

        btn_auto_sort = QPushButton("  🪄 Kapitel automatisch sortieren")
        btn_auto_sort.setCursor(Qt.PointingHandCursor)
        btn_auto_sort.setFixedHeight(32)
        btn_auto_sort.setStyleSheet("""
            QPushButton {
                background-color: #1A1833;
                color: #D2A8FF;
                border: 1px solid #4A357A;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #26224A;
                border-color: #8957E5;
                color: #FFFFFF;
            }
        """)
        btn_auto_sort.setToolTip("Sortiert Frontmatter nach vorn, Kapitel natürlich (1, 2, ... 10) und Anhang ans Ende")
        btn_auto_sort.clicked.connect(self._auto_sort_chapters)
        toolbar.addWidget(btn_auto_sort)

        btn_clear = QPushButton("Liste leeren")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setFixedHeight(32)
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #1D1318;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 6px;
                padding: 0 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #321820;
                border-color: #F85149;
            }
        """)
        btn_clear.clicked.connect(self._clear_all)
        toolbar.addWidget(btn_clear)

        left_lay.addLayout(toolbar)

        # Table of PDFs / Chapters
        self.table = QTableWidget()
        self.table.setItemDelegate(NoFocusItemDelegate(self.table))
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "#", "KAPITEL-LESEZEICHEN (IM INHALTSVERZEICHNIS)", "DATEINAME", "SEITEN / BEREICH", "REIHENFOLGE"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)

        self.table.setColumnWidth(0, 38)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(3, 115)
        self.table.setColumnWidth(4, 110)

        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #090D16;
                color: #C9D1D9;
                border: 1px solid #1E2B45;
                border-radius: 8px;
                selection-background-color: #141E33;
                font-size: 12px;
                outline: none;
            }
            QTableWidget::item {
                border-bottom: 1px solid #131B2B;
                padding: 4px 6px;
            }
            QHeaderView::section {
                background-color: #101624;
                color: #7D8590;
                border: none;
                border-bottom: 1px solid #1E2B45;
                padding: 8px 6px;
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.4px;
            }
        """)
        left_lay.addWidget(self.table, stretch=1)

        lbl_drop_hint = QLabel(
            "💡 Tipp: Du kannst PDF-Dateien auch direkt per Drag & Drop in dieses Fenster ziehen. "
            "Die Lesezeichen-Namen werden direkt als anklickbares Inhaltsverzeichnis ins Buch eingebettet."
        )
        lbl_drop_hint.setFont(QFont("Segoe UI", 8))
        lbl_drop_hint.setStyleSheet("color: #6E7681;")
        lbl_drop_hint.setWordWrap(True)
        left_lay.addWidget(lbl_drop_hint)

        splitter.addWidget(left_panel)

        # --- RIGHT PANEL: Book Metadata & Output Settings ---
        right_panel = QFrame()
        right_panel.setFixedWidth(330)
        right_panel.setStyleSheet("""
            QFrame#mergeConfigCard {
                background-color: #101726;
                border: 1px solid #1F2D47;
                border-radius: 10px;
            }
        """)
        right_panel.setObjectName("mergeConfigCard")
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(16, 16, 16, 16)
        right_lay.setSpacing(10)

        lbl_cfg_hdr = QLabel("📘 GESAMTBUCH-METADATEN")
        lbl_cfg_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_cfg_hdr.setStyleSheet("color: #58A6FF; letter-spacing: 0.5px;")
        right_lay.addWidget(lbl_cfg_hdr)

        # Title
        right_lay.addWidget(self._field_label("Buchtitel / Modultitel:"))
        self.input_title = QLineEdit()
        self.input_title.setPlaceholderText("z. B. Thermodynamik Grundlagen")
        self.input_title.setStyleSheet(self._input_style())
        self.input_title.textChanged.connect(self._update_suggested_filename)
        right_lay.addWidget(self.input_title)

        # Author
        right_lay.addWidget(self._field_label("Autor / Herausgeber:"))
        self.input_author = QLineEdit()
        self.input_author.setPlaceholderText("z. B. Peter Stephan")
        self.input_author.setStyleSheet(self._input_style())
        self.input_author.textChanged.connect(self._update_suggested_filename)
        right_lay.addWidget(self.input_author)

        # Category & DocType Row
        right_lay.addWidget(self._field_label("Fachbereich / Kategorie:"))
        self.combo_category = QComboBox()
        self.combo_category.setStyleSheet(self._combo_style())
        all_cats = [c[0] for c in get_category_counts()] or STANDARD_CATEGORIES
        for std_c in STANDARD_CATEGORIES:
            if std_c not in all_cats:
                all_cats.append(std_c)
        self.combo_category.addItems(all_cats)
        right_lay.addWidget(self.combo_category)

        right_lay.addWidget(self._field_label("Dokumenttyp:"))
        self.combo_doctype = QComboBox()
        self.combo_doctype.setStyleSheet(self._combo_style())
        self.combo_doctype.addItem("📚 Fachbuch / Lehrbuch", "book")
        self.combo_doctype.addItem("📝 Studienbrief / Vorlesungsskript", "study_script")
        if self.default_doc_type == "study_script":
            self.combo_doctype.setCurrentIndex(1)
        right_lay.addWidget(self.combo_doctype)

        # Output Filename
        right_lay.addWidget(self._field_label("Zieldateiname:"))
        self.input_filename = QLineEdit("Zusammengefuehrtes_Buch.pdf")
        self.input_filename.setStyleSheet(self._input_style())
        right_lay.addWidget(self.input_filename)

        right_lay.addSpacing(4)

        # Options Header
        lbl_opt_hdr = QLabel("⚙ MERGE- & KATALOG-OPTIONEN")
        lbl_opt_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_opt_hdr.setStyleSheet("color: #58A6FF; letter-spacing: 0.5px;")
        right_lay.addWidget(lbl_opt_hdr)

        self.chk_generate_toc = QCheckBox("📑 PDF-Inhaltsverzeichnis (Lesezeichen) erzeugen")
        self.chk_generate_toc.setChecked(True)
        self.chk_generate_toc.setStyleSheet(self._checkbox_style("#F0F6FC", bold=True))
        self.chk_generate_toc.setToolTip(
            "Erzeugt für jede Datei automatisch ein Kapitel-Lesezeichen im zusammengeführten PDF."
        )
        right_lay.addWidget(self.chk_generate_toc)

        self.chk_preserve_sub_toc = QCheckBox("↳ Unter-Lesezeichen aus Kapiteln übernehmen")
        self.chk_preserve_sub_toc.setChecked(True)
        self.chk_preserve_sub_toc.setStyleSheet(self._checkbox_style("#8B949E"))
        right_lay.addWidget(self.chk_preserve_sub_toc)

        self.chk_generate_toc.toggled.connect(self.chk_preserve_sub_toc.setEnabled)

        self.chk_add_to_library = QCheckBox("📥 Direkt in Campus-Bibliothek aufnehmen")
        self.chk_add_to_library.setChecked(True)
        self.chk_add_to_library.setStyleSheet(self._checkbox_style("#3FB950", bold=True))
        right_lay.addWidget(self.chk_add_to_library)

        self.chk_place_on_desk = QCheckBox("📌 Auf meinen Schreibtisch legen")
        self.chk_place_on_desk.setChecked(False)
        self.chk_place_on_desk.setStyleSheet(self._checkbox_style("#C9D1D9"))
        right_lay.addWidget(self.chk_place_on_desk)

        self.chk_add_to_library.toggled.connect(self.chk_place_on_desk.setEnabled)

        self.chk_cleanup_inbox = QCheckBox("🧹 Einzeldateien danach aus _Inbox entfernen")
        self.chk_cleanup_inbox.setChecked(bool(self.from_inbox))
        self.chk_cleanup_inbox.setStyleSheet(self._checkbox_style("#FFA657"))
        self.chk_cleanup_inbox.setToolTip(
            "Löscht nach erfolgreichem Zusammenführen die ursprünglichen Einzelkapitel aus dem _Inbox-Ordner."
        )
        right_lay.addWidget(self.chk_cleanup_inbox)

        right_lay.addStretch()

        splitter.addWidget(right_panel)
        splitter.setSizes([660, 330])
        root.addWidget(splitter, stretch=1)

        # -------------------------------------------------------------
        # 3. Bottom Action Bar
        # -------------------------------------------------------------
        footer = QHBoxLayout()
        footer.setSpacing(10)

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet(self._secondary_btn_style())
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        footer.addStretch()

        self.btn_merge = QPushButton("  🔗 Jetzt zu Gesamtbuch zusammenführen")
        self.btn_merge.setIcon(create_vector_icon("merge", "#FFFFFF", 16))
        self.btn_merge.setIconSize(QSize(16, 16))
        self.btn_merge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_merge.setFixedHeight(38)
        self.btn_merge.setCursor(Qt.PointingHandCursor)
        self.btn_merge.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
                color: #FFFFFF;
                border: 1px solid #3FB950;
                border-radius: 7px;
                padding: 0 22px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2EA043, stop:1 #3FB950);
                border-color: #56D364;
            }
            QPushButton:disabled {
                background: #16221B;
                color: #486852;
                border-color: #213629;
            }
        """)
        self.btn_merge.setEnabled(False)
        self.btn_merge.clicked.connect(self._execute_merge)
        footer.addWidget(self.btn_merge)

        root.addLayout(footer)

    # ------------------------------------------------------------------
    # Styling Helpers
    # ------------------------------------------------------------------
    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        return lbl

    def _input_style(self) -> str:
        return """
            QLineEdit {
                background-color: #090D16;
                color: #F0F6FC;
                border: 1px solid #263552;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
                background-color: #0D1424;
            }
        """

    def _combo_style(self) -> str:
        return """
            QComboBox {
                background-color: #090D16;
                color: #58A6FF;
                border: 1px solid #263552;
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QComboBox:hover {
                border-color: #58A6FF;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #101726;
                color: #C9D1D9;
                selection-background-color: #1F6FEB;
                selection-color: #FFFFFF;
                border: 1px solid #263552;
                outline: none;
            }
        """

    def _checkbox_style(self, color: str, bold: bool = False) -> str:
        weight = "bold" if bold else "normal"
        return f"""
            QCheckBox {{
                color: {color};
                font-size: 11px;
                font-weight: {weight};
                spacing: 7px;
                border: none;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 15px;
                height: 15px;
                border-radius: 4px;
                border: 1px solid #304163;
                background-color: #090D16;
            }}
            QCheckBox::indicator:hover {{
                border-color: #58A6FF;
            }}
            QCheckBox::indicator:checked {{
                background-color: #1F6FEB;
                border-color: #58A6FF;
            }}
        """

    def _secondary_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #131B2E;
                color: #C9D1D9;
                border: 1px solid #253552;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1B2742;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """

    # ------------------------------------------------------------------
    # Drag & Drop Support
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        dropped_files = []
        for u in urls:
            local_p = u.toLocalFile()
            if not local_p or not os.path.exists(local_p):
                continue
            if os.path.isdir(local_p):
                for entry in sorted(os.listdir(local_p)):
                    fp = os.path.join(local_p, entry)
                    if os.path.isfile(fp) and fp.lower().endswith(".pdf"):
                        dropped_files.append(fp)
            elif local_p.lower().endswith(".pdf"):
                dropped_files.append(local_p)
        if dropped_files:
            self.add_files(dropped_files, auto_sort=True)

    # ------------------------------------------------------------------
    # File Management & Sorting
    # ------------------------------------------------------------------
    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "PDF-Kapitel oder Dokumente zum Zusammenführen auswählen",
            "",
            "PDF-Dateien (*.pdf)"
        )
        if files:
            self.add_files(files, auto_sort=len(self._items) == 0)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ordner mit Kapitel-PDFs auswählen")
        if not folder or not os.path.isdir(folder):
            return
        pdf_files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(folder, f))
        ]
        if not pdf_files:
            QMessageBox.information(self, "Keine PDFs", "In diesem Ordner wurden keine PDF-Dateien gefunden.")
            return
        self.add_files(pdf_files, auto_sort=True)

    def _load_from_inbox(self) -> None:
        inbox_items = get_inbox_queue()
        paths = [it["file_path"] for it in inbox_items if os.path.isfile(it.get("file_path", ""))]
        if not paths:
            inbox_dir = get_inbox_directory()
            if os.path.isdir(inbox_dir):
                paths = [
                    os.path.join(inbox_dir, f)
                    for f in os.listdir(inbox_dir)
                    if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(inbox_dir, f))
                ]
        if not paths:
            QMessageBox.information(self, "Posteingang leer", "Im Posteingang (_Inbox) befinden sich aktuell keine PDF-Dateien.")
            return
        self.from_inbox = True
        self.chk_cleanup_inbox.setChecked(True)
        self.add_files(paths, auto_sort=True)

    def add_files(self, file_paths: List[str], auto_sort: bool = True) -> None:
        existing_paths = {os.path.abspath(it["file_path"]).lower() for it in self._items}
        added_any = False

        for fp in file_paths:
            if not fp or not os.path.isfile(fp) or not fp.lower().endswith(".pdf"):
                continue
            norm_p = os.path.abspath(fp)
            if norm_p.lower() in existing_paths:
                continue

            p_count = get_pdf_page_count(norm_p)
            bm_title = clean_chapter_bookmark_title(norm_p)

            self._items.append({
                "file_path": norm_p,
                "filename": os.path.basename(norm_p),
                "bookmark_title": bm_title,
                "page_count": p_count,
                "page_range": "",
            })
            existing_paths.add(norm_p.lower())
            added_any = True

        if not added_any:
            return

        if auto_sort and len(self._items) > 1:
            self._items.sort(key=lambda x: suggest_chapter_sort_key(x["file_path"], x["bookmark_title"]))

        self._infer_book_metadata_if_empty()
        self._refresh_table()

    def _infer_book_metadata_if_empty(self) -> None:
        """Auto-detects book title, author, and category from inbox records or first PDF chapter."""
        if not self._items:
            return

        # 1. Check if any file is already analyzed in inbox_queue
        inbox_map = {os.path.abspath(it["file_path"]).lower(): it for it in get_inbox_queue() if it.get("file_path")}
        first_path = os.path.abspath(self._items[0]["file_path"])

        if not self.input_title.text().strip():
            # Try common prefix across filenames or folder name
            parent_folder = os.path.basename(os.path.dirname(first_path))
            if parent_folder and parent_folder.lower() not in ("_inbox", "desktop", "downloads", "documents", "bücher", "books"):
                clean_folder = re.sub(r'_?kapitel$', '', parent_folder, flags=re.I).replace("_", " ").strip()
                if len(clean_folder) >= 4:
                    self.input_title.setText(clean_folder)

        # Inspect first file via PyMuPDF or Inbox metadata
        ib_entry = inbox_map.get(first_path.lower())
        if ib_entry:
            if not self.input_title.text().strip() and ib_entry.get("suggested_title"):
                raw_t = ib_entry["suggested_title"]
                # Strip trailing chapter markers from title
                raw_t = re.sub(r'\s*[-–—:]?\s*(?:Kapitel|Chapter|Teil|Kurseinheit|KE)\s*\d+.*$', '', raw_t, flags=re.I).strip()
                if raw_t:
                    self.input_title.setText(raw_t)
            if not self.input_author.text().strip() and ib_entry.get("suggested_author") and ib_entry["suggested_author"] != "Unbekannt":
                self.input_author.setText(ib_entry["suggested_author"])
            if ib_entry.get("suggested_category"):
                idx = self.combo_category.findText(ib_entry["suggested_category"])
                if idx >= 0:
                    self.combo_category.setCurrentIndex(idx)

        if not self.input_title.text().strip() or not self.input_author.text().strip():
            try:
                import fitz
                doc = fitz.open(first_path)
                vt, va = extract_visual_title_and_author(doc)
                doc.close()
                if vt and not self.input_title.text().strip():
                    clean_vt = re.sub(r'\s*[-–—:]?\s*(?:Kapitel|Chapter|Teil|Kurseinheit|KE)\s*\d+.*$', '', vt, flags=re.I).strip()
                    self.input_title.setText(clean_vt or vt)
                if va and not self.input_author.text().strip():
                    self.input_author.setText(sanitize_author_string(va))
            except Exception:
                pass

        if not self.input_title.text().strip():
            base_t = self._items[0]["bookmark_title"]
            base_t = re.sub(r'^\d+\s*[-–.]\s*', '', base_t).strip()
            self.input_title.setText(base_t or "Zusammengeführtes Fachbuch")

        if not self.input_author.text().strip():
            self.input_author.setText("Unbekannt")

        self._update_suggested_filename()

    def _update_suggested_filename(self) -> None:
        title = self.input_title.text().strip()
        author = self.input_author.text().strip()
        safe_t = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:75]
        safe_a = "".join(c for c in author if c not in r'\/:*?"<>|').strip()[:45]
        if not safe_t:
            return
        if safe_a and safe_a.lower() != "unbekannt":
            self.input_filename.setText(f"{safe_a} - {safe_t}.pdf")
        else:
            self.input_filename.setText(f"{safe_t}.pdf")

    def _auto_sort_chapters(self) -> None:
        if len(self._items) < 2:
            return
        self._items.sort(key=lambda x: suggest_chapter_sort_key(x["file_path"], x["bookmark_title"]))
        self._refresh_table()

    def _clear_all(self) -> None:
        self._items.clear()
        self._refresh_table()

    def _move_row(self, index: int, direction: int) -> None:
        new_idx = index + direction
        if 0 <= index < len(self._items) and 0 <= new_idx < len(self._items):
            self._items[index], self._items[new_idx] = self._items[new_idx], self._items[index]
            self._refresh_table()
            self.table.selectRow(new_idx)

    def _remove_row(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._items.pop(index)
            self._refresh_table()

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._items))
        total_pages = 0

        for row, it in enumerate(self._items):
            p_cnt = it.get("page_count", 0)
            p_range = (it.get("page_range") or "").strip()
            if p_range:
                sel = parse_page_ranges(p_range, p_cnt)
                eff_pages = len(sel) if sel else p_cnt
            else:
                eff_pages = p_cnt
            total_pages += eff_pages

            # Col 0: Order badge
            item_num = QTableWidgetItem(f"{row + 1}")
            item_num.setTextAlignment(Qt.AlignCenter)
            item_num.setForeground(QColor("#58A6FF"))
            item_num.setFont(QFont("Segoe UI", 9, QFont.Bold))
            item_num.setFlags(item_num.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, item_num)

            # Col 1: Editable Bookmark Title
            bm_edit = QLineEdit(it.get("bookmark_title", ""))
            bm_edit.setPlaceholderText("Kapitelname im Inhaltsverzeichnis...")
            bm_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #101829;
                    color: #F0F6FC;
                    border: 1px solid #22324F;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QLineEdit:focus {
                    border-color: #58A6FF;
                    background-color: #16223A;
                }
            """)
            bm_edit.textChanged.connect(lambda txt, r=row: self._on_bookmark_edited(r, txt))
            self.table.setCellWidget(row, 1, bm_edit)

            # Col 2: Original Filename
            fn_item = QTableWidgetItem(it.get("filename", ""))
            fn_item.setForeground(QColor("#8B949E"))
            fn_item.setToolTip(it.get("file_path", ""))
            fn_item.setFlags(fn_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, fn_item)

            # Col 3: Page Range Input (optional filter per file)
            range_edit = QLineEdit(p_range)
            range_edit.setPlaceholderText(f"Alle ({p_cnt} S.)")
            range_edit.setToolTip(f"Optional: Nur bestimmte Seiten aus dieser PDF übernehmen (z.B. 1-{max(1, p_cnt-1)})")
            range_edit.setAlignment(Qt.AlignCenter)
            range_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #0D1422;
                    color: #79C0FF;
                    border: 1px solid #1E2C46;
                    border-radius: 4px;
                    padding: 3px 6px;
                    font-size: 10px;
                }
                QLineEdit:focus {
                    border-color: #58A6FF;
                }
            """)
            range_edit.textChanged.connect(lambda txt, r=row: self._on_range_edited(r, txt))
            self.table.setCellWidget(row, 3, range_edit)

            # Col 4: Up / Down / Remove Buttons
            act_w = QWidget()
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(4, 2, 4, 2)
            act_l.setSpacing(4)
            act_l.setAlignment(Qt.AlignCenter)

            btn_up = QPushButton("▲")
            btn_up.setFixedSize(26, 26)
            btn_up.setCursor(Qt.PointingHandCursor)
            btn_up.setEnabled(row > 0)
            btn_up.setToolTip("Kapitel nach oben verschieben")
            btn_up.setStyleSheet(self._mini_icon_btn_style())
            btn_up.clicked.connect(lambda _, r=row: self._move_row(r, -1))
            act_l.addWidget(btn_up)

            btn_down = QPushButton("▼")
            btn_down.setFixedSize(26, 26)
            btn_down.setCursor(Qt.PointingHandCursor)
            btn_down.setEnabled(row < len(self._items) - 1)
            btn_down.setToolTip("Kapitel nach unten verschieben")
            btn_down.setStyleSheet(self._mini_icon_btn_style())
            btn_down.clicked.connect(lambda _, r=row: self._move_row(r, 1))
            act_l.addWidget(btn_down)

            btn_rm = QPushButton("✕")
            btn_rm.setFixedSize(26, 26)
            btn_rm.setCursor(Qt.PointingHandCursor)
            btn_rm.setToolTip("Aus Liste entfernen")
            btn_rm.setStyleSheet("""
                QPushButton {
                    background-color: #1F1216;
                    color: #FF7B72;
                    border: 1px solid #482329;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #381920;
                    border-color: #F85149;
                    color: #FFFFFF;
                }
            """)
            btn_rm.clicked.connect(lambda _, r=row: self._remove_row(r))
            act_l.addWidget(btn_rm)

            self.table.setCellWidget(row, 4, act_w)

        self.lbl_summary_badge.setText(f"{len(self._items)} Dateien · {total_pages} Seiten gesamt")
        self.btn_merge.setEnabled(len(self._items) >= 2)

    def _mini_icon_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #131C2E;
                color: #8B949E;
                border: 1px solid #243452;
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover:enabled {
                background-color: #1F6FEB;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
            QPushButton:disabled {
                background-color: #0C111C;
                color: #30363D;
                border-color: #161F30;
            }
        """

    def _on_bookmark_edited(self, row: int, text: str) -> None:
        if 0 <= row < len(self._items):
            self._items[row]["bookmark_title"] = text

    def _on_range_edited(self, row: int, text: str) -> None:
        if 0 <= row < len(self._items):
            self._items[row]["page_range"] = text.strip()
            total_pages = 0
            for it in self._items:
                p_cnt = it.get("page_count", 0)
                pr = (it.get("page_range") or "").strip()
                if pr:
                    sel = parse_page_ranges(pr, p_cnt)
                    total_pages += len(sel) if sel else p_cnt
                else:
                    total_pages += p_cnt
            self.lbl_summary_badge.setText(f"{len(self._items)} Dateien · {total_pages} Seiten gesamt")

    # ------------------------------------------------------------------
    # Execution Logic
    # ------------------------------------------------------------------
    def _execute_merge(self) -> None:
        if len(self._items) < 2:
            QMessageBox.warning(self, "Zu wenige Dateien", "Bitte füge mindestens 2 PDF-Dateien hinzu.")
            return

        title = self.input_title.text().strip() or "Zusammengeführtes Buch"
        author = self.input_author.text().strip() or "Unbekannt"
        category = self.combo_category.currentText().strip() or "Sonstiges"
        doc_type = self.combo_doctype.currentData() or "book"

        out_fname = self.input_filename.text().strip()
        if not out_fname.lower().endswith(".pdf"):
            out_fname += ".pdf"
        out_fname = "".join(c for c in out_fname if c not in r'\/:*?"<>|').strip() or "Gesamtbuch.pdf"

        storage_dir = get_books_storage_dir()
        cfg = load_config()
        if cfg.get("inbox_create_subfolders", False):
            default_dir = os.path.join(storage_dir, category)
            os.makedirs(default_dir, exist_ok=True)
        else:
            default_dir = storage_dir
            os.makedirs(default_dir, exist_ok=True)

        default_target = os.path.join(default_dir, out_fname)

        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Zusammengeführtes Gesamtbuch speichern unter",
            default_target,
            "PDF-Dokumente (*.pdf)"
        )
        if not target_path:
            return

        # Prevent overwriting one of the source files directly while reading
        norm_target = os.path.abspath(target_path).lower()
        source_norms = {os.path.abspath(it["file_path"]).lower() for it in self._items}
        if norm_target in source_norms:
            QMessageBox.warning(
                self,
                "Quelldatei-Konflikt",
                "Die Zieldatei darf nicht identisch mit einer der geöffneten Quelldateien sein.\n"
                "Bitte wähle einen neuen Dateinamen für das zusammengeführte Buch."
            )
            return

        # Progress Dialog
        prog = QProgressDialog("Kapitel werden zusammengefügt...", None, 0, len(self._items), self)
        prog.setWindowTitle("PDF-Merge läuft")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        def _on_prog(curr, total, ch_title):
            prog.setValue(curr)
            prog.setLabelText(f"Füge Kapitel {curr} von {total} ein:\n{ch_title[:60]}")
            QApplication.processEvents()

        meta_dict = {
            "title": title,
            "author": author,
            "subject": category,
        }

        ok, msg, total_merged_pages = merge_pdf_files(
            items=self._items,
            target_pdf_path=target_path,
            metadata=meta_dict,
            generate_toc=self.chk_generate_toc.isChecked(),
            preserve_sub_bookmarks=self.chk_preserve_sub_toc.isChecked(),
            progress_callback=_on_prog,
        )
        prog.close()

        if not ok:
            QMessageBox.critical(self, "Fehler beim Zusammenführen", msg)
            return

        self.merged_file_path = target_path

        # Index into SQLite Library Database if requested
        if self.chk_add_to_library.isChecked():
            isbn = None
            edition = 1
            edition_str = "1. Auflage"
            year = None
            try:
                import fitz
                doc = fitz.open(target_path)
                front_txt = ""
                for p in range(min(10, len(doc))):
                    front_txt += doc[p].get_text("text") + "\n"
                isbns = extract_isbns(f"ISBN {out_fname}\n{front_txt}")
                if isbns:
                    isbn = isbns[0]
                edition, edition_str = extract_edition_number(f"{out_fname}\n{front_txt}")
                year = extract_publication_year(front_txt, doc.metadata, out_fname)
                doc.close()
            except Exception:
                pass

            f_size = os.path.getsize(target_path) if os.path.isfile(target_path) else 0
            f_mtime = os.path.getmtime(target_path) if os.path.isfile(target_path) else 0.0

            book_id = upsert_book(
                file_path=target_path,
                filename=os.path.basename(target_path),
                title=title,
                author=author,
                categories=[category],
                isbn=isbn,
                edition=edition,
                edition_str=edition_str,
                year=year,
                page_count=total_merged_pages,
                file_size=f_size,
                file_mtime=f_mtime,
                confidence=100,
                audit_trail=f"PDF-Merge-Studio ({len(self._items)} Kapitel zusammengeführt)",
                doc_type=doc_type,
            )
            self.merged_book_id = book_id

            try:
                extract_and_cache_cover(
                    book_id=book_id,
                    file_path=target_path,
                    title=title,
                    author=author,
                    category=category,
                    isbn=isbn,
                )
            except Exception:
                pass

            if self.chk_place_on_desk.isChecked():
                try:
                    toggle_desk_item(book_id)
                except Exception:
                    pass

            msg += f"\n\n✓ Direkt als '{title}' in die Campus-Bibliothek aufgenommen!"

        # Optional cleanup of source chapter files from _Inbox
        if self.chk_cleanup_inbox.isChecked():
            inbox_dir_norm = os.path.abspath(get_inbox_directory()).lower()
            inbox_rows = get_inbox_queue()
            inbox_by_path = {os.path.abspath(r["file_path"]).lower(): r["id"] for r in inbox_rows if r.get("file_path")}
            removed_cnt = 0

            for it in self._items:
                src_p = os.path.abspath(it["file_path"])
                src_low = src_p.lower()
                if src_low in inbox_by_path:
                    delete_inbox_item(inbox_by_path[src_low], delete_file=True)
                    removed_cnt += 1
                elif src_low.startswith(inbox_dir_norm) and os.path.isfile(src_p):
                    try:
                        os.remove(src_p)
                        removed_cnt += 1
                    except Exception:
                        pass

            if removed_cnt > 0:
                msg += f"\n🧹 {removed_cnt} Einzelkapitel-Dateien wurden aus dem Posteingang bereinigt."

        # Completion Dialog
        done_box = QMessageBox(self)
        done_box.setWindowTitle("Gesamtbuch erfolgreich erstellt")
        done_box.setIcon(QMessageBox.Information)
        done_box.setText(msg)

        btn_open = done_box.addButton("📖 Buch jetzt öffnen", QMessageBox.ActionRole)
        btn_open.setStyleSheet("background-color: #1F6FEB; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        btn_folder = done_box.addButton("📂 Im Explorer zeigen", QMessageBox.ActionRole)
        btn_folder.setStyleSheet("background-color: #21262D; color: #C9D1D9; padding: 6px 14px; border-radius: 4px;")

        done_box.addButton("Fertig", QMessageBox.AcceptRole)
        done_box.exec()

        if done_box.clickedButton() == btn_open:
            open_pdf_in_edge(target_path)
        elif done_box.clickedButton() == btn_folder:
            subprocess.run(["explorer", "/select,", os.path.normpath(target_path)])

        self.accept()

