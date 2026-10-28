"""Dialog for merging multiple PDF files / individual book chapters into a single book.
Provides natural chapter sorting (Frontmatter -> Chapters 1..N -> Backmatter),
interactive bookmark title editing, automatic hierarchical PDF Table of Contents (TOC) generation,
catalog group detection, and direct indexing into the Campus Library with optional cleanup.
"""

import os
import re
import subprocess
from collections import defaultdict
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
    QTreeWidget,
    QTreeWidgetItem,
)

from core.pdf_tools import (
    get_pdf_page_count,
    suggest_chapter_sort_key,
    clean_chapter_bookmark_title,
    strip_common_book_prefix,
    merge_pdf_files,
    parse_page_ranges,
)
from core.config import get_books_storage_dir, get_inbox_directory, load_config
from core.library_db import (
    get_all_books,
    upsert_book,
    delete_book,
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


class CatalogPickerDialog(QDialog):
    """Smart modal dialog to pick existing books or auto-detected multi-part book groups from the catalog."""

    def __init__(self, doc_type: str = "book", parent=None):
        super().__init__(parent)
        self.doc_type = doc_type
        self.selected_books: List[Dict[str, Any]] = []
        self.all_books = get_all_books()

        self.setWindowTitle("Kapitel & Bücher aus Katalog auswählen")
        self.resize(760, 540)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #0D121D;
                border: 1px solid #283750;
            }
        """)
        self._build_ui()
        self._populate_tree()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        lbl_hdr = QLabel("📚 Bücher oder mehrteilige Kapitel-Gruppen aus dem Katalog wählen")
        lbl_hdr.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_hdr.setStyleSheet("color: #F0F6FC;")
        lay.addWidget(lbl_hdr)

        lbl_sub = QLabel(
            "Tipp: Mehrteilige Bücher (gleicher Buchtitel im Katalog) sind ganz oben als Gruppe zusammengefasst – "
            "ein Haken bei der Gruppe wählt sofort alle zugehörigen Kapitel aus!"
        )
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E;")
        lbl_sub.setWordWrap(True)
        lay.addWidget(lbl_sub)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Katalog filtern nach Buchtitel, Dateiname oder Autor...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedHeight(36)
        self.search_edit.setStyleSheet("""
            QLineEdit {
                background-color: #090D16;
                color: #F0F6FC;
                border: 1px solid #263552;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
            }
        """)
        self.search_edit.textChanged.connect(self._populate_tree)
        lay.addWidget(self.search_edit)

        self.tree = QTreeWidget()
        self.tree.setItemDelegate(NoFocusItemDelegate(self.tree))
        self.tree.setHeaderLabels(["Buchtitel / Kapitel-Gruppe", "Dateiname", "Autor", "Seiten"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.Fixed)
        self.tree.setColumnWidth(1, 220)
        self.tree.setColumnWidth(3, 70)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #090D16;
                color: #C9D1D9;
                border: 1px solid #1E2B45;
                border-radius: 8px;
                font-size: 12px;
                outline: none;
            }
            QTreeWidget::item {
                padding: 6px 4px;
                border-bottom: 1px solid #131B2B;
            }
            QTreeWidget::item:hover {
                background-color: #141E33;
            }
            QHeaderView::section {
                background-color: #101624;
                color: #8B949E;
                border: none;
                border-bottom: 1px solid #1E2B45;
                padding: 8px;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        self.tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.tree, stretch=1)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #141C2E;
                color: #C9D1D9;
                border: 1px solid #263552;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()

        self.btn_ok = QPushButton("Ausgewählte übernehmen (0)")
        self.btn_ok.setFixedHeight(36)
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setEnabled(False)
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: 1px solid #58A6FF;
                border-radius: 6px;
                padding: 0 20px;
                font-weight: bold;
            }
            QPushButton:disabled {
                background: #141C2E;
                color: #48546A;
                border-color: #1E2B45;
            }
        """)
        self.btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(self.btn_ok)
        lay.addLayout(btn_row)

    def _populate_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        q = self.search_edit.text().strip().lower()

        filtered = [
            b for b in self.all_books
            if b.get("file_path") and os.path.isfile(b["file_path"])
            and (
                not q
                or q in (b.get("title") or "").lower()
                or q in (b.get("filename") or "").lower()
                or q in (b.get("author") or "").lower()
            )
        ]

        # Group by normalized title to surface multi-chapter books at the very top
        by_title: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for b in filtered:
            norm_t = (b.get("title") or "").strip()
            by_title[norm_t].append(b)

        multi_groups = {t: lst for t, lst in by_title.items() if len(lst) >= 2}
        singles = [lst[0] for t, lst in by_title.items() if len(lst) == 1]

        # 1. Add Multi-Part Groups first
        for title_name, group_books in sorted(multi_groups.items(), key=lambda x: (-len(x[1]), x[0].lower())):
            total_p = sum(int(b.get("page_count") or 0) for b in group_books)
            grp_item = QTreeWidgetItem([
                f"📦 {title_name} ({len(group_books)} Einzelteile erkannt)",
                f"{len(group_books)} PDF-Dateien",
                group_books[0].get("author", ""),
                f"{total_p} S.",
            ])
            grp_item.setFlags(grp_item.flags() | Qt.ItemIsUserCheckable)
            grp_item.setCheckState(0, Qt.Unchecked)
            grp_item.setForeground(0, QColor("#58A6FF"))
            grp_item.setFont(0, QFont("Segoe UI", 10, QFont.Bold))
            self.tree.addTopLevelItem(grp_item)

            for b in sorted(group_books, key=lambda x: suggest_chapter_sort_key(x.get("file_path", ""), x.get("title", ""))):
                child = QTreeWidgetItem([
                    b.get("title", ""),
                    b.get("filename", ""),
                    b.get("author", ""),
                    f"{b.get('page_count', 0)} S.",
                ])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                child.setData(0, Qt.UserRole, b)
                grp_item.addChild(child)

            grp_item.setExpanded(True)

        # 2. Add Individual Books
        for b in sorted(singles, key=lambda x: (x.get("title") or "").lower()):
            item = QTreeWidgetItem([
                b.get("title", ""),
                b.get("filename", ""),
                b.get("author", ""),
                f"{b.get('page_count', 0)} S.",
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, b)
            self.tree.addTopLevelItem(item)

        self.tree.blockSignals(False)
        self._update_count()

    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 0:
            return
        self.tree.blockSignals(True)
        state = item.checkState(0)
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, state)
        self.tree.blockSignals(False)
        self._update_count()

    def _collect_checked_books(self) -> List[Dict[str, Any]]:
        result = []
        seen_ids = set()

        def _visit(node: QTreeWidgetItem):
            b = node.data(0, Qt.UserRole)
            if b and node.checkState(0) == Qt.Checked:
                bid = str(b.get("id"))
                if bid not in seen_ids:
                    seen_ids.add(bid)
                    result.append(b)
            for i in range(node.childCount()):
                _visit(node.child(i))

        for idx in range(self.tree.topLevelItemCount()):
            _visit(self.tree.topLevelItem(idx))
        return result

    def _update_count(self) -> None:
        checked = self._collect_checked_books()
        self.btn_ok.setText(f"Ausgewählte übernehmen ({len(checked)})")
        self.btn_ok.setEnabled(len(checked) > 0)

    def _on_accept(self) -> None:
        self.selected_books = self._collect_checked_books()
        self.accept()


class PdfMergeDialog(QDialog):
    """Studio dialog for merging individual PDF chapters or documents into a complete textbook."""

    def __init__(
        self,
        initial_files: Optional[List[str]] = None,
        catalog_books: Optional[List[Dict[str, Any]]] = None,
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
        self._catalog_book_ids_by_path: Dict[str, str] = {}
        self.merged_book_id: Optional[str] = None
        self.merged_file_path: Optional[str] = None

        self.setWindowTitle("PDF-Merge-Studio – Kapitel & PDFs zu Gesamtbuch zusammenführen")
        self.resize(1180, 740)
        self.setMinimumSize(1020, 640)
        self.setAcceptDrops(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #0B0F19;
                border: 1px solid #23324D;
            }
        """)

        self._build_ui()

        # Preload catalog_books if passed directly from CatalogView
        if catalog_books:
            self._ingest_catalog_books(catalog_books)
        elif base_book and base_book.get("file_path") and os.path.isfile(base_book["file_path"]):
            self._ingest_catalog_books([base_book])

        if initial_files:
            self.add_files(initial_files, auto_sort=True)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # -------------------------------------------------------------
        # 1. Header Banner
        # -------------------------------------------------------------
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #141E33, stop:1 #0F1626);
                border: 1px solid #263859;
                border-radius: 10px;
            }
        """)
        h_lay = QHBoxLayout(header_card)
        h_lay.setContentsMargins(16, 12, 16, 12)
        h_lay.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(create_vector_pixmap("merge", "#58A6FF", 24))
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: #182640; border: 1px solid #2E456E; border-radius: 9px;")
        h_lay.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        lbl_h1 = QLabel("PDF-Merge-Studio & Kapitel-Assembler")
        lbl_h1.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lbl_h1.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        title_col.addWidget(lbl_h1)

        lbl_sub = QLabel(
            "Fügt einzelne Buchkapitel, Deckblatt, Inhaltsverzeichnis und Register verlustfrei zu einem Gesamtbuch zusammen."
        )
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        title_col.addWidget(lbl_sub)
        h_lay.addLayout(title_col, stretch=1)

        self.lbl_summary_badge = QLabel("0 Dateien · 0 Seiten gesamt")
        self.lbl_summary_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_summary_badge.setStyleSheet("""
            background-color: #13223E;
            color: #58A6FF;
            border: 1px solid #2B487A;
            border-radius: 8px;
            padding: 8px 16px;
        """)
        h_lay.addWidget(self.lbl_summary_badge)

        root.addWidget(header_card)

        # -------------------------------------------------------------
        # 2. Main Splitter (Left: Chapter Table, Right: Book Metadata & Options)
        # -------------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(12)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")

        # --- LEFT PANEL: Chapter Table & Ordering ---
        left_panel = QWidget()
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(10)

        # Toolbar above table (generous spacing, zero text clipping)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_add_files = QPushButton("  Dateien...")
        btn_add_files.setIcon(create_vector_icon("plus", "#FFFFFF", 13))
        btn_add_files.setCursor(Qt.PointingHandCursor)
        btn_add_files.setFixedHeight(34)
        btn_add_files.setToolTip("Einzelne PDF-Dateien von der Festplatte auswählen")
        btn_add_files.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: 1px solid #58A6FF;
                border-radius: 6px;
                padding: 0 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2B7BF4, stop:1 #58A6FF);
            }
        """)
        btn_add_files.clicked.connect(self._browse_files)
        toolbar.addWidget(btn_add_files)

        btn_from_catalog = QPushButton("  Aus Katalog wählen...")
        btn_from_catalog.setIcon(create_vector_icon("library", "#58A6FF", 14))
        btn_from_catalog.setCursor(Qt.PointingHandCursor)
        btn_from_catalog.setFixedHeight(34)
        btn_from_catalog.setToolTip("Bereits im Katalog vorhandene Einzelkapitel oder Bücher auswählen")
        btn_from_catalog.setStyleSheet(self._secondary_btn_style())
        btn_from_catalog.clicked.connect(self._pick_from_catalog)
        toolbar.addWidget(btn_from_catalog)

        btn_add_folder = QPushButton("  Ordner...")
        btn_add_folder.setIcon(create_vector_icon("export", "#58A6FF", 13))
        btn_add_folder.setCursor(Qt.PointingHandCursor)
        btn_add_folder.setFixedHeight(34)
        btn_add_folder.setStyleSheet(self._secondary_btn_style())
        btn_add_folder.setToolTip("Alle PDF-Dateien aus einem Ordner laden")
        btn_add_folder.clicked.connect(self._browse_folder)
        toolbar.addWidget(btn_add_folder)

        btn_load_inbox = QPushButton("  _Inbox")
        btn_load_inbox.setIcon(create_vector_icon("inbox", "#58A6FF", 13))
        btn_load_inbox.setCursor(Qt.PointingHandCursor)
        btn_load_inbox.setFixedHeight(34)
        btn_load_inbox.setStyleSheet(self._secondary_btn_style())
        btn_load_inbox.setToolTip("Alle aktuell im Posteingang (_Inbox) liegenden PDF-Dateien laden")
        btn_load_inbox.clicked.connect(self._load_from_inbox)
        toolbar.addWidget(btn_load_inbox)

        toolbar.addStretch()

        btn_auto_sort = QPushButton("  Kapitel-Sortierung")
        btn_auto_sort.setIcon(create_vector_icon("sync", "#D2A8FF", 13))
        btn_auto_sort.setCursor(Qt.PointingHandCursor)
        btn_auto_sort.setFixedHeight(34)
        btn_auto_sort.setStyleSheet("""
            QPushButton {
                background-color: #1A1833;
                color: #D2A8FF;
                border: 1px solid #4A357A;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #26224A;
                border-color: #8957E5;
                color: #FFFFFF;
            }
        """)
        btn_auto_sort.setToolTip(
            "Sortiert automatisch in Buch-Reihenfolge:\n"
            "Deckblatt -> Titel -> Impressum -> Inhaltsverzeichnis -> Kapitel 1..N -> Literatur -> Register -> Rückseite"
        )
        btn_auto_sort.clicked.connect(self._auto_sort_chapters)
        toolbar.addWidget(btn_auto_sort)

        btn_clear = QPushButton("Leeren")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setFixedHeight(34)
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #1D1318;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #321820;
                border-color: #F85149;
                color: #FFFFFF;
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
            "#", "LESEZEICHEN IM INHALTSVERZEICHNIS", "QUELLDATEI", "SEITEN / BEREICH", "AKTION"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)

        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 195)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 114)

        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #090D16;
                color: #C9D1D9;
                border: 1px solid #1E2B45;
                border-radius: 10px;
                selection-background-color: #141E33;
                font-size: 12px;
                outline: none;
            }
            QTableWidget::item {
                border-bottom: 1px solid #131B2B;
                padding: 4px 8px;
            }
            QHeaderView::section {
                background-color: #101624;
                color: #8B949E;
                border: none;
                border-bottom: 1px solid #1E2B45;
                padding: 10px 8px;
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.5px;
            }
        """)
        left_lay.addWidget(self.table, stretch=1)

        lbl_drop_hint = QLabel(
            "💡 Tipp: Ziehe Dateien einfach per Drag & Drop hierher. Die Lesezeichen-Spalte bildet später das "
            "anklickbare Inhaltsverzeichnis (TOC) deines zusammengeführten Buches."
        )
        lbl_drop_hint.setFont(QFont("Segoe UI", 9))
        lbl_drop_hint.setStyleSheet("color: #8B949E;")
        lbl_drop_hint.setWordWrap(True)
        left_lay.addWidget(lbl_drop_hint)

        splitter.addWidget(left_panel)

        # --- RIGHT PANEL: Book Metadata & Output Settings ---
        right_panel = QFrame()
        right_panel.setFixedWidth(365)
        right_panel.setStyleSheet("""
            QFrame#mergeConfigCard {
                background-color: #101726;
                border: 1px solid #1F2D47;
                border-radius: 10px;
            }
        """)
        right_panel.setObjectName("mergeConfigCard")
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(18, 18, 18, 18)
        right_lay.setSpacing(8)

        lbl_cfg_hdr = QLabel("GESAMTBUCH-METADATEN")
        lbl_cfg_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_cfg_hdr.setStyleSheet("color: #58A6FF; letter-spacing: 0.6px;")
        right_lay.addWidget(lbl_cfg_hdr)

        # Title
        right_lay.addWidget(self._field_label("Buchtitel / Modultitel:"))
        self.input_title = QLineEdit()
        self.input_title.setFixedHeight(36)
        self.input_title.setPlaceholderText("z. B. Einführung in die Physische Geographie")
        self.input_title.setStyleSheet(self._input_style())
        self.input_title.textChanged.connect(self._update_suggested_filename)
        right_lay.addWidget(self.input_title)

        # Author
        right_lay.addWidget(self._field_label("Autor / Herausgeber:"))
        self.input_author = QLineEdit()
        self.input_author.setFixedHeight(36)
        self.input_author.setPlaceholderText("z. B. Roland Baumhauer")
        self.input_author.setStyleSheet(self._input_style())
        self.input_author.textChanged.connect(self._update_suggested_filename)
        right_lay.addWidget(self.input_author)

        # Category
        right_lay.addWidget(self._field_label("Fachbereich / Kategorie:"))
        self.combo_category = QComboBox()
        self.combo_category.setFixedHeight(36)
        self.combo_category.setStyleSheet(self._combo_style())
        all_cats = [c[0] for c in get_category_counts()] or STANDARD_CATEGORIES
        for std_c in STANDARD_CATEGORIES:
            if std_c not in all_cats:
                all_cats.append(std_c)
        self.combo_category.addItems(all_cats)
        right_lay.addWidget(self.combo_category)

        # Document Type
        right_lay.addWidget(self._field_label("Dokumenttyp:"))
        self.combo_doctype = QComboBox()
        self.combo_doctype.setFixedHeight(36)
        self.combo_doctype.setStyleSheet(self._combo_style())
        self.combo_doctype.addItem("Fachbuch / Lehrbuch", "book")
        self.combo_doctype.addItem("Studienbrief / Vorlesungsskript", "study_script")
        if self.default_doc_type == "study_script":
            self.combo_doctype.setCurrentIndex(1)
        right_lay.addWidget(self.combo_doctype)

        # Output Filename
        right_lay.addWidget(self._field_label("Zieldateiname:"))
        self.input_filename = QLineEdit("Zusammengefuehrtes_Buch.pdf")
        self.input_filename.setFixedHeight(36)
        self.input_filename.setStyleSheet(self._input_style())
        right_lay.addWidget(self.input_filename)

        right_lay.addSpacing(8)

        # Options Header
        lbl_opt_hdr = QLabel("MERGE- & KATALOG-OPTIONEN")
        lbl_opt_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_opt_hdr.setStyleSheet("color: #58A6FF; letter-spacing: 0.6px;")
        right_lay.addWidget(lbl_opt_hdr)

        self.chk_generate_toc = QCheckBox("PDF-Inhaltsverzeichnis (Lesezeichen) erzeugen")
        self.chk_generate_toc.setChecked(True)
        self.chk_generate_toc.setStyleSheet(self._checkbox_style("#F0F6FC", bold=True))
        self.chk_generate_toc.setToolTip(
            "Erzeugt für jede Datei automatisch ein Kapitel-Lesezeichen im zusammengeführten PDF."
        )
        right_lay.addWidget(self.chk_generate_toc)

        self.chk_preserve_sub_toc = QCheckBox("Unter-Lesezeichen aus Kapiteln übernehmen")
        self.chk_preserve_sub_toc.setChecked(True)
        self.chk_preserve_sub_toc.setStyleSheet(self._checkbox_style("#8B949E"))
        right_lay.addWidget(self.chk_preserve_sub_toc)
        self.chk_generate_toc.toggled.connect(self.chk_preserve_sub_toc.setEnabled)

        self.chk_add_to_library = QCheckBox("Direkt in Campus-Bibliothek aufnehmen")
        self.chk_add_to_library.setChecked(True)
        self.chk_add_to_library.setStyleSheet(self._checkbox_style("#3FB950", bold=True))
        right_lay.addWidget(self.chk_add_to_library)

        self.chk_place_on_desk = QCheckBox("Auf meinen Schreibtisch legen")
        self.chk_place_on_desk.setChecked(False)
        self.chk_place_on_desk.setStyleSheet(self._checkbox_style("#C9D1D9"))
        right_lay.addWidget(self.chk_place_on_desk)
        self.chk_add_to_library.toggled.connect(self.chk_place_on_desk.setEnabled)

        self.chk_replace_catalog_parts = QCheckBox("Alte Einzelteile aus Katalog ersetzen & löschen")
        self.chk_replace_catalog_parts.setChecked(True)
        self.chk_replace_catalog_parts.setStyleSheet(self._checkbox_style("#FFA657", bold=True))
        self.chk_replace_catalog_parts.setToolTip(
            "Entfernt nach erfolgreichem Zusammenführen die alten Einzelkapitel-Einträge (und deren Einzel-PDFs) "
            "aus dem Katalog, sodass nur noch das fertige Gesamtbuch im Regal steht."
        )
        self.chk_replace_catalog_parts.setVisible(False)
        right_lay.addWidget(self.chk_replace_catalog_parts)

        self.chk_cleanup_inbox = QCheckBox("Einzeldateien danach aus _Inbox entfernen")
        self.chk_cleanup_inbox.setChecked(bool(self.from_inbox))
        self.chk_cleanup_inbox.setStyleSheet(self._checkbox_style("#FFA657"))
        self.chk_cleanup_inbox.setToolTip(
            "Löscht nach erfolgreichem Zusammenführen die ursprünglichen Einzelkapitel aus dem _Inbox-Ordner."
        )
        right_lay.addWidget(self.chk_cleanup_inbox)

        right_lay.addStretch()

        splitter.addWidget(right_panel)
        splitter.setSizes([760, 365])
        root.addWidget(splitter, stretch=1)

        # -------------------------------------------------------------
        # 3. Bottom Action Bar
        # -------------------------------------------------------------
        footer = QHBoxLayout()
        footer.setSpacing(12)

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(38)
        btn_cancel.setStyleSheet(self._secondary_btn_style())
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        footer.addStretch()

        self.btn_merge = QPushButton("  Jetzt zu Gesamtbuch zusammenführen")
        self.btn_merge.setIcon(create_vector_icon("merge", "#FFFFFF", 16))
        self.btn_merge.setIconSize(QSize(16, 16))
        self.btn_merge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_merge.setFixedHeight(40)
        self.btn_merge.setCursor(Qt.PointingHandCursor)
        self.btn_merge.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
                color: #FFFFFF;
                border: 1px solid #3FB950;
                border-radius: 8px;
                padding: 0 24px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2EA043, stop:1 #3FB950);
                border-color: #56D364;
            }
            QPushButton:disabled {
                background: #141E18;
                color: #486852;
                border-color: #1F3326;
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
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setStyleSheet("color: #C9D1D9; border: none; background: transparent; margin-top: 2px;")
        return lbl

    def _input_style(self) -> str:
        return """
            QLineEdit {
                background-color: #090D16;
                color: #F0F6FC;
                border: 1px solid #263552;
                border-radius: 6px;
                padding: 0 10px;
                font-size: 12px;
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
                border-radius: 6px;
                padding: 0 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QComboBox:hover {
                border-color: #58A6FF;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #101726;
                color: #C9D1D9;
                selection-background-color: #1F6FEB;
                selection-color: #FFFFFF;
                border: 1px solid #263552;
                outline: none;
                padding: 4px;
            }
        """

    def _checkbox_style(self, color: str, bold: bool = False) -> str:
        weight = "bold" if bold else "normal"
        return f"""
            QCheckBox {{
                color: {color};
                font-size: 11px;
                font-weight: {weight};
                spacing: 8px;
                border: none;
                background: transparent;
                padding: 2px 0;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
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

    def _mini_icon_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #141E33;
                border: 1px solid #283A5E;
                border-radius: 5px;
                padding: 0px;
            }
            QPushButton:hover:enabled {
                background-color: #1F6FEB;
                border-color: #58A6FF;
            }
            QPushButton:disabled {
                background-color: #0C111C;
                border-color: #161F30;
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
    # Catalog & File Ingestion
    # ------------------------------------------------------------------
    def _pick_from_catalog(self) -> None:
        dlg = CatalogPickerDialog(doc_type=self.default_doc_type, parent=self)
        if dlg.exec() and dlg.selected_books:
            self._ingest_catalog_books(dlg.selected_books)

    def _ingest_catalog_books(self, books: List[Dict[str, Any]]) -> None:
        paths = []
        for b in books:
            fp = b.get("file_path", "")
            if fp and os.path.isfile(fp):
                norm_p = os.path.abspath(fp)
                paths.append(norm_p)
                if b.get("id"):
                    self._catalog_book_ids_by_path[norm_p.lower()] = str(b["id"])

        # Pre-fill metadata from first catalog book with valid metadata
        for b in books:
            t = (b.get("title") or "").strip()
            a = (b.get("author") or "").strip()
            cat = (b.get("primary_category") or "").strip()
            if t and not self.input_title.text().strip():
                self.input_title.setText(t)
            if a and a != "Unbekannt" and not self.input_author.text().strip():
                # Take first 2 authors if comma-separated list is huge
                authors_split = [x.strip() for x in a.split(",") if x.strip()]
                clean_a = ", ".join(authors_split[:3]) if len(authors_split) > 3 else a
                self.input_author.setText(clean_a)
            if cat:
                idx = self.combo_category.findText(cat)
                if idx >= 0:
                    self.combo_category.setCurrentIndex(idx)

        if paths:
            self.add_files(paths, auto_sort=True)

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
        # Map any file that already exists in our library catalog so we can offer clean replacement
        all_cat_books = {
            os.path.abspath(b["file_path"]).lower(): b
            for b in get_all_books()
            if b.get("file_path")
        }

        added_any = False
        for fp in file_paths:
            if not fp or not os.path.isfile(fp) or not fp.lower().endswith(".pdf"):
                continue
            norm_p = os.path.abspath(fp)
            low_p = norm_p.lower()
            if low_p in existing_paths:
                continue

            if low_p in all_cat_books:
                cat_b = all_cat_books[low_p]
                self._catalog_book_ids_by_path[low_p] = str(cat_b["id"])

            p_count = get_pdf_page_count(norm_p)
            bm_title = clean_chapter_bookmark_title(norm_p)

            self._items.append({
                "file_path": norm_p,
                "filename": os.path.basename(norm_p),
                "bookmark_title": bm_title,
                "page_count": p_count,
                "page_range": "",
            })
            existing_paths.add(low_p)
            added_any = True

        if not added_any:
            return

        self._infer_book_metadata_if_empty()

        if auto_sort and len(self._items) > 1:
            self._items.sort(key=lambda x: suggest_chapter_sort_key(x["file_path"], x["bookmark_title"]))

        # Strip redundant shared book title prefixes from chapter bookmarks (e.g. "Einfhrung in die Physische Geographie ...")
        strip_common_book_prefix(self._items, self.input_title.text().strip())

        self._update_catalog_replace_visibility()
        self._refresh_table()

    def _update_catalog_replace_visibility(self) -> None:
        cat_count = sum(
            1 for it in self._items
            if os.path.abspath(it["file_path"]).lower() in self._catalog_book_ids_by_path
        )
        if cat_count > 0:
            self.chk_replace_catalog_parts.setText(
                f"Alte {cat_count} Einzelteile aus Katalog ersetzen & löschen"
            )
            self.chk_replace_catalog_parts.setVisible(True)
        else:
            self.chk_replace_catalog_parts.setVisible(False)

    def _infer_book_metadata_if_empty(self) -> None:
        """Auto-detects book title, author, and category from catalog, inbox records, or first PDF chapter."""
        if not self._items:
            return

        first_path = os.path.abspath(self._items[0]["file_path"])

        # 1. Check catalog records first
        all_cat_books = {
            os.path.abspath(b["file_path"]).lower(): b
            for b in get_all_books()
            if b.get("file_path")
        }
        for it in self._items:
            cb = all_cat_books.get(os.path.abspath(it["file_path"]).lower())
            if cb:
                if not self.input_title.text().strip() and cb.get("title"):
                    self.input_title.setText(cb["title"])
                if not self.input_author.text().strip() and cb.get("author") and cb["author"] != "Unbekannt":
                    authors_split = [x.strip() for x in cb["author"].split(",") if x.strip()]
                    clean_a = ", ".join(authors_split[:2]) if len(authors_split) > 2 else cb["author"]
                    self.input_author.setText(clean_a)
                if cb.get("primary_category"):
                    idx = self.combo_category.findText(cb["primary_category"])
                    if idx >= 0:
                        self.combo_category.setCurrentIndex(idx)
                break

        # 2. Check inbox queue
        inbox_map = {os.path.abspath(it["file_path"]).lower(): it for it in get_inbox_queue() if it.get("file_path")}
        ib_entry = inbox_map.get(first_path.lower())
        if ib_entry:
            if not self.input_title.text().strip() and ib_entry.get("suggested_title"):
                raw_t = ib_entry["suggested_title"]
                raw_t = re.sub(r'\s*[-–—:]?\s*(?:Kapitel|Chapter|Teil|Kurseinheit|KE)\s*\d+.*$', '', raw_t, flags=re.I).strip()
                if raw_t:
                    self.input_title.setText(raw_t)
            if not self.input_author.text().strip() and ib_entry.get("suggested_author") and ib_entry["suggested_author"] != "Unbekannt":
                self.input_author.setText(ib_entry["suggested_author"])
            if ib_entry.get("suggested_category"):
                idx = self.combo_category.findText(ib_entry["suggested_category"])
                if idx >= 0:
                    self.combo_category.setCurrentIndex(idx)

        # 3. Inspect first PDF directly via PyMuPDF if still missing
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
        safe_t = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:70]
        # Keep filename author concise (first author surname/name)
        first_author = author.split(",")[0].strip() if author else ""
        safe_a = "".join(c for c in first_author if c not in r'\/:*?"<>|').strip()[:35]
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
        strip_common_book_prefix(self._items, self.input_title.text().strip())
        self._refresh_table()

    def _clear_all(self) -> None:
        self._items.clear()
        self._catalog_book_ids_by_path.clear()
        self._update_catalog_replace_visibility()
        self._refresh_table()

    def _move_row(self, index: int, direction: int) -> None:
        new_idx = index + direction
        if 0 <= index < len(self._items) and 0 <= new_idx < len(self._items):
            self._items[index], self._items[new_idx] = self._items[new_idx], self._items[index]
            self._refresh_table()
            self.table.selectRow(new_idx)

    def _remove_row(self, index: int) -> None:
        if 0 <= index < len(self._items):
            removed = self._items.pop(index)
            low_p = os.path.abspath(removed["file_path"]).lower()
            self._catalog_book_ids_by_path.pop(low_p, None)
            self._update_catalog_replace_visibility()
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
            item_num.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_num.setFlags(item_num.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, item_num)

            # Col 1: Editable Bookmark Title (Starts left-aligned at index 0!)
            bm_edit = QLineEdit()
            bm_edit.setText(it.get("bookmark_title", ""))
            bm_edit.setCursorPosition(0)
            bm_edit.setPlaceholderText("Kapitelname im Inhaltsverzeichnis...")
            bm_edit.setToolTip(it.get("bookmark_title", ""))
            bm_edit.setFixedHeight(32)
            bm_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #101829;
                    color: #F0F6FC;
                    border: 1px solid #22324F;
                    border-radius: 5px;
                    padding: 0 10px;
                    font-size: 12px;
                    font-weight: 600;
                }
                QLineEdit:focus {
                    border-color: #58A6FF;
                    background-color: #16223A;
                }
            """)
            bm_edit.textChanged.connect(lambda txt, r=row: self._on_bookmark_edited(r, txt))
            bm_container = QWidget()
            bm_lay = QHBoxLayout(bm_container)
            bm_lay.setContentsMargins(6, 4, 6, 4)
            bm_lay.addWidget(bm_edit)
            self.table.setCellWidget(row, 1, bm_container)

            # Col 2: Original Filename
            fn_item = QTableWidgetItem(it.get("filename", ""))
            fn_item.setForeground(QColor("#8B949E"))
            fn_item.setToolTip(it.get("file_path", ""))
            fn_item.setFlags(fn_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, fn_item)

            # Col 3: Page Range Input (optional filter per file)
            range_edit = QLineEdit(p_range)
            range_edit.setPlaceholderText(f"Alle ({p_cnt} S.)")
            range_edit.setToolTip(f"Optional: Nur bestimmte Seiten übernehmen (z.B. 1-{max(1, p_cnt)})")
            range_edit.setAlignment(Qt.AlignCenter)
            range_edit.setFixedHeight(32)
            range_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #0D1422;
                    color: #79C0FF;
                    border: 1px solid #1E2C46;
                    border-radius: 5px;
                    padding: 0 6px;
                    font-size: 11px;
                }
                QLineEdit:focus {
                    border-color: #58A6FF;
                }
            """)
            range_edit.textChanged.connect(lambda txt, r=row: self._on_range_edited(r, txt))
            rng_container = QWidget()
            rng_lay = QHBoxLayout(rng_container)
            rng_lay.setContentsMargins(6, 4, 6, 4)
            rng_lay.addWidget(range_edit)
            self.table.setCellWidget(row, 3, rng_container)

            # Col 4: Up / Down / Remove Buttons with razor-sharp vector icons
            act_w = QWidget()
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(4, 4, 4, 4)
            act_l.setSpacing(5)
            act_l.setAlignment(Qt.AlignCenter)

            btn_up = QPushButton()
            btn_up.setIcon(create_vector_icon("arrow_up", "#58A6FF" if row > 0 else "#30363D", 14))
            btn_up.setIconSize(QSize(14, 14))
            btn_up.setFixedSize(28, 28)
            btn_up.setCursor(Qt.PointingHandCursor)
            btn_up.setEnabled(row > 0)
            btn_up.setToolTip("Kapitel nach oben verschieben")
            btn_up.setStyleSheet(self._mini_icon_btn_style())
            btn_up.clicked.connect(lambda _, r=row: self._move_row(r, -1))
            act_l.addWidget(btn_up)

            btn_down = QPushButton()
            is_not_last = row < len(self._items) - 1
            btn_down.setIcon(create_vector_icon("arrow_down", "#58A6FF" if is_not_last else "#30363D", 14))
            btn_down.setIconSize(QSize(14, 14))
            btn_down.setFixedSize(28, 28)
            btn_down.setCursor(Qt.PointingHandCursor)
            btn_down.setEnabled(is_not_last)
            btn_down.setToolTip("Kapitel nach unten verschieben")
            btn_down.setStyleSheet(self._mini_icon_btn_style())
            btn_down.clicked.connect(lambda _, r=row: self._move_row(r, 1))
            act_l.addWidget(btn_down)

            btn_rm = QPushButton()
            btn_rm.setIcon(create_vector_icon("trash", "#FF7B72", 14))
            btn_rm.setIconSize(QSize(14, 14))
            btn_rm.setFixedSize(28, 28)
            btn_rm.setCursor(Qt.PointingHandCursor)
            btn_rm.setToolTip("Aus Merge-Liste entfernen")
            btn_rm.setStyleSheet("""
                QPushButton {
                    background-color: #211216;
                    border: 1px solid #482329;
                    border-radius: 5px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #381920;
                    border-color: #F85149;
                }
            """)
            btn_rm.clicked.connect(lambda _, r=row: self._remove_row(r))
            act_l.addWidget(btn_rm)

            self.table.setCellWidget(row, 4, act_w)

        self.lbl_summary_badge.setText(f"{len(self._items)} Dateien · {total_pages} Seiten gesamt")
        self.btn_merge.setEnabled(len(self._items) >= 2)

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

        # Prefer directory of first catalog item if merging inside existing storage
        first_dir = os.path.dirname(os.path.abspath(self._items[0]["file_path"]))
        inbox_dir_norm = os.path.abspath(get_inbox_directory()).lower()
        if first_dir and not first_dir.lower().startswith(inbox_dir_norm) and os.path.isdir(first_dir):
            default_dir = first_dir
        else:
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
                "Bitte wähle einen eigenen Dateinamen für das zusammengeführte Gesamtbuch."
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
            prog.setLabelText(f"Füge Abschnitt {curr} von {total} ein:\n{ch_title[:60]}")
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

        # 1. Index into SQLite Library Database if requested
        if self.chk_add_to_library.isChecked():
            isbn = None
            edition = 1
            edition_str = "1. Auflage"
            year = None
            try:
                import fitz
                doc = fitz.open(target_path)
                front_txt = ""
                for p in range(min(12, len(doc))):
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
                audit_trail=f"PDF-Merge-Studio ({len(self._items)} Teile zusammengeführt)",
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

            msg += f"\n\n✓ Direkt als '{title}' ({total_merged_pages} Seiten) in die Campus-Bibliothek aufgenommen!"

        # 2. Replace old catalog single-chapter entries if checked
        if self.chk_replace_catalog_parts.isVisible() and self.chk_replace_catalog_parts.isChecked():
            replaced_cnt = 0
            for it in self._items:
                low_p = os.path.abspath(it["file_path"]).lower()
                old_bid = self._catalog_book_ids_by_path.get(low_p)
                if old_bid and old_bid != self.merged_book_id:
                    ok_del, _ = delete_book(old_bid, delete_file=True)
                    if ok_del:
                        replaced_cnt += 1
            if replaced_cnt > 0:
                msg += f"\n🧹 {replaced_cnt} alte Einzelkapitel-Einträge wurden aus dem Katalog ersetzt und bereinigt."

        # 3. Optional cleanup of source chapter files from _Inbox
        if self.chk_cleanup_inbox.isChecked():
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
