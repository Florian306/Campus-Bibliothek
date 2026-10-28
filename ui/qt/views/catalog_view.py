"""Catalog and Library View for PySide6.
Provides dual view modes: Interactive Shelf Grid & Searchable Table List.
Supports Ctrl/Shift multi-selection and 1-click sibling chapter group merging.
"""

import os
import subprocess
from typing import Any, Dict, List, Optional, Set
from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtGui import QFont, QColor, QAction
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QScrollArea,
    QGridLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMenu,
    QApplication,
    QMessageBox,
    QCheckBox,
    QComboBox,
    QFrame,
)

from ui.qt.components.book_card import BookCard
from ui.qt.components.category_chips import CategoryChipsBar
from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate
from core.library_db import (
    get_all_books,
    get_book_by_id,
    get_category_counts,
    toggle_desk_item,
    update_reading_progress,
    open_pdf_in_edge,
    get_book_categories,
    delete_book,
    set_book_doc_type,
)
from core.config import load_config
from ui.qt.dialogs.pdf_reader_dialog import PdfReaderDialog


class CatalogView(QWidget):
    """Main Catalog and Library browser."""

    book_launched = Signal(str)       # book_id
    quick_look_requested = Signal(str) # book_id
    desk_toggled = Signal(str)        # book_id
    data_changed = Signal()

    def __init__(self, mode: str = "books", parent=None):
        super().__init__(parent)
        self.mode = mode  # "books" or "study_scripts"
        self.doc_type_filter = "study_script" if mode == "study_scripts" else "book"
        self.master_books: List[Dict[str, Any]] = []
        self.filtered_books: List[Dict[str, Any]] = []
        self.selected_book_id: Optional[str] = None
        self.selected_book_ids: Set[str] = set()
        self.current_category = "Alle"
        self.search_term = ""
        self.sort_mode = "title_asc"
        self.active_letter: str = "Alle"
        self._letter_buttons: Dict[str, QPushButton] = {}

        # Shelf cards cache
        self.cards_dict: Dict[str, BookCard] = {}
        self._shelf_render_idx = 0
        self._current_cols = 0
        self._shelf_batch_timer = QTimer(self)
        self._shelf_batch_timer.setInterval(15)
        self._shelf_batch_timer.timeout.connect(self._render_next_shelf_batch)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._handle_debounced_resize)

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 22, 24, 20)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. Top Header Bar
        # -------------------------------------------------------------
        top_bar = QHBoxLayout()

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title_row = QHBoxLayout()
        title_text = "Studienbriefe & Vorlesungsskripte" if self.mode == "study_scripts" else "Katalog & Literaturverzeichnis"
        lbl_title = QLabel(title_text)
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC;")
        title_row.addWidget(lbl_title)

        init_badge = "0 Studienbriefe" if self.mode == "study_scripts" else "0 Bücher"
        self.lbl_badge_total = QLabel(init_badge)
        self.lbl_badge_total.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_badge_total.setStyleSheet("""
            QLabel {
                background-color: #162035;
                color: #58A6FF;
                border: 1px solid #233454;
                border-radius: 10px;
                padding: 3px 12px;
            }
        """)
        title_row.addWidget(self.lbl_badge_total)
        title_row.addStretch()
        title_box.addLayout(title_row)

        desc_text = (
            "Zentrales Register aller archivierten Kurseinheiten, Module und Skripte"
            if self.mode == "study_scripts"
            else "Zentrales Register aller archivierten Fach- und Lehrbücher mit Volltext-Index"
        )
        lbl_desc = QLabel(desc_text)
        lbl_desc.setFont(QFont("Segoe UI", 9))
        lbl_desc.setStyleSheet("color: #8B949E;")
        title_box.addWidget(lbl_desc)

        top_bar.addLayout(title_box)
        top_bar.addStretch()

        # View Mode Switcher
        switch_frame = QWidget()
        switch_frame.setStyleSheet("""
            QWidget {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
            }
        """)
        switch_layout = QHBoxLayout(switch_frame)
        switch_layout.setContentsMargins(3, 3, 3, 3)
        switch_layout.setSpacing(4)

        self.btn_shelf = QPushButton("  Bücherregal")
        self.btn_shelf.setIcon(create_vector_icon("library", "#FFFFFF", 16))
        self.btn_shelf.setCursor(Qt.PointingHandCursor)
        self.btn_shelf.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD); color: #FFFFFF; font-weight: bold; border: none; border-radius: 5px; padding: 6px 14px;")
        self.btn_shelf.clicked.connect(lambda: self._set_view_mode("shelf"))
        switch_layout.addWidget(self.btn_shelf)

        self.btn_table = QPushButton("  Tabelle")
        self.btn_table.setIcon(create_vector_icon("notes", "#8B949E", 16))
        self.btn_table.setCursor(Qt.PointingHandCursor)
        self.btn_table.setStyleSheet("background-color: transparent; color: #8B949E; border: none; border-radius: 5px; padding: 6px 14px;")
        self.btn_table.clicked.connect(lambda: self._set_view_mode("table"))
        switch_layout.addWidget(self.btn_table)

        top_bar.addWidget(switch_frame)

        # Sort Mode Selector
        self.combo_sort = QComboBox()
        self.combo_sort.setFixedHeight(34)
        self.combo_sort.setFixedWidth(185)
        self.combo_sort.setCursor(Qt.PointingHandCursor)
        self.combo_sort.setToolTip("Sortierreihenfolge für Bücherregal & Tabelle")
        self.combo_sort.addItem("↕  Titel (A – Z)", "title_asc")
        self.combo_sort.addItem("↕  Titel (Z – A)", "title_desc")
        self.combo_sort.addItem("↕  Zuletzt hinzugefügt", "recent")
        self.combo_sort.addItem("↕  Erscheinungsjahr (Neu)", "year_desc")
        self.combo_sort.addItem("↕  Seitenzahl (Umfang)", "pages_desc")
        self.combo_sort.addItem("↕  Autor (A – Z)", "author_asc")
        self.combo_sort.setStyleSheet("""
            QComboBox {
                background-color: #121826;
                color: #C9D1D9;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QComboBox:hover {
                border-color: #58A6FF;
                color: #FFFFFF;
            }
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QComboBox QAbstractItemView {
                background-color: #141C2E;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
                selection-color: #FFFFFF;
                border: 1px solid #324468;
                border-radius: 6px;
                padding: 4px;
                outline: none;
            }
        """)
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)
        top_bar.addWidget(self.combo_sort)

        # Search Input
        self.ent_search = QLineEdit()
        self.ent_search.setPlaceholderText("🔍 Suchen nach Titel, Autor, Fach...")
        self.ent_search.setFixedWidth(260)
        self.ent_search.setFixedHeight(34)
        self.ent_search.textChanged.connect(self._on_search_changed)
        self.ent_search.setClearButtonEnabled(True)
        top_bar.addWidget(self.ent_search)

        main_layout.addLayout(top_bar)

        # -------------------------------------------------------------
        # 2. Category Chips Bar & A-Z Quick Jump Bar
        # -------------------------------------------------------------
        self.chips_bar = CategoryChipsBar(self)
        self.chips_bar.category_selected.connect(self._on_category_selected)
        main_layout.addWidget(self.chips_bar)

        # Compact Alphabetical Quick-Filter Strip (Alle | A B C ... Z)
        az_frame = QFrame(self)
        az_frame.setFixedHeight(30)
        az_frame.setStyleSheet("""
            QFrame {
                background-color: #0D121F;
                border: 1px solid #1B253B;
                border-radius: 7px;
            }
        """)
        az_layout = QHBoxLayout(az_frame)
        az_layout.setContentsMargins(6, 2, 6, 2)
        az_layout.setSpacing(2)

        letters = ["Alle"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
        for ltr in letters:
            btn_l = QPushButton(ltr)
            btn_l.setCursor(Qt.PointingHandCursor)
            btn_l.setFixedHeight(22)
            if ltr == "Alle":
                btn_l.setFixedWidth(42)
            else:
                btn_l.setFixedWidth(24)
            btn_l.clicked.connect(lambda checked=False, l=ltr: self._on_letter_selected(l))
            az_layout.addWidget(btn_l)
            self._letter_buttons[ltr] = btn_l
        az_layout.addStretch()
        self._update_letter_bar_styles()
        main_layout.addWidget(az_frame)

        # -------------------------------------------------------------
        # 3. Stacked View Container (Shelf vs. Table)
        # -------------------------------------------------------------
        self.stacked_views = QStackedWidget(self)

        # View 0: Virtual Shelf ScrollArea
        self.shelf_scroll = QScrollArea(self.stacked_views)
        self.shelf_scroll.setWidgetResizable(True)
        self.shelf_scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.shelf_container = QWidget(self.shelf_scroll)
        self.shelf_container.setStyleSheet("background-color: transparent;")
        self.shelf_grid = QGridLayout(self.shelf_container)
        self.shelf_grid.setContentsMargins(4, 8, 4, 16)
        self.shelf_grid.setSpacing(16)
        self.shelf_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.shelf_scroll.setWidget(self.shelf_container)

        self.stacked_views.addWidget(self.shelf_scroll)

        # View 1: Catalog Table
        self.table_books = QTableWidget(self.stacked_views)
        self.table_books.setItemDelegate(NoFocusItemDelegate(self.table_books))
        self.table_books.setColumnCount(7)
        self.table_books.setHorizontalHeaderLabels(["Pult", "Buchtitel", "Autor", "Auflage", "Seiten", "Kapitel", "Fachbereiche"])
        self.table_books.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_books.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_books.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.table_books.setColumnWidth(5, 75)
        self.table_books.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_books.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table_books.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_books.verticalHeader().setVisible(False)
        self.table_books.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table_books.cellDoubleClicked.connect(self._on_table_double_click)
        self.table_books.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_books.customContextMenuRequested.connect(self._on_table_context_menu)
        self.stacked_views.addWidget(self.table_books)

        main_layout.addWidget(self.stacked_views)

        # -------------------------------------------------------------
        # 4. Action / Status Footer
        # -------------------------------------------------------------
        footer = QHBoxLayout()
        self.lbl_table_count = QLabel("Lade Daten...")
        self.lbl_table_count.setStyleSheet("""
            QLabel {
                background-color: #1F2937;
                color: #58A6FF;
                border: 1px solid #30363D;
                border-radius: 6px;
                padding: 4px 10px;
                font-weight: bold;
            }
        """)
        footer.addWidget(self.lbl_table_count)

        lbl_tips_icon = QLabel()
        lbl_tips_icon.setPixmap(create_vector_pixmap("bulb", "#8B949E", 14))
        lbl_tips_icon.setStyleSheet("border: none; background: transparent;")
        footer.addWidget(lbl_tips_icon)

        lbl_tips = QLabel("Tipp: Strg/Shift-Klick für Mehrfachauswahl • Rechtsklick zum Kapitel-Zusammenführen")
        lbl_tips.setStyleSheet("color: #8B949E; font-size: 11px;")
        footer.addWidget(lbl_tips)
        footer.addStretch()

        btn_open = QPushButton("  PDF öffnen")
        btn_open.setIcon(create_vector_icon("desk", "#FFFFFF", 16))
        btn_open.setObjectName("primaryButton")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(34)
        btn_open.clicked.connect(self._open_selected_book)
        footer.addWidget(btn_open)

        btn_quick = QPushButton("  Quick-Look")
        btn_quick.setIcon(create_vector_icon("search", "#58A6FF", 16))
        btn_quick.setCursor(Qt.PointingHandCursor)
        btn_quick.setFixedHeight(34)
        btn_quick.clicked.connect(self._open_quick_look_dialog)
        footer.addWidget(btn_quick)

        self.btn_desk = QPushButton("  Auf Schreibtisch")
        self.btn_desk.setIcon(create_vector_icon("check", "#3FB950", 16))
        self.btn_desk.setCursor(Qt.PointingHandCursor)
        self.btn_desk.setFixedHeight(34)
        self.btn_desk.clicked.connect(self._toggle_selected_desk)
        footer.addWidget(self.btn_desk)

        self.btn_merge = QPushButton("  Kapitel / PDFs zusammenführen")
        self.btn_merge.setIcon(create_vector_icon("merge", "#D2A8FF", 15))
        self.btn_merge.setCursor(Qt.PointingHandCursor)
        self.btn_merge.setFixedHeight(34)
        self.btn_merge.setToolTip("Einzelne Kapitel-PDFs oder markierte Bücher inklusive Inhaltsverzeichnis zu einem Gesamtbuch zusammenführen")
        self.btn_merge.setStyleSheet("""
            QPushButton {
                background-color: #1A162B;
                color: #D2A8FF;
                border: 1px solid #483278;
                border-radius: 6px;
                font-weight: 600;
                font-size: 12px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #272042;
                border-color: #8957E5;
                color: #FFFFFF;
            }
        """)
        self.btn_merge.clicked.connect(self._on_footer_merge_clicked)
        footer.addWidget(self.btn_merge)

        self.btn_del = QPushButton("  Buch entfernen")
        self.btn_del.setIcon(create_vector_icon("trash", "#FF7B72", 15))
        self.btn_del.setCursor(Qt.PointingHandCursor)
        self.btn_del.setFixedHeight(34)
        self.btn_del.setStyleSheet("""
            QPushButton {
                background-color: #211215;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 6px;
                font-weight: 600;
                font-size: 12px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #381920;
                border-color: #F85149;
                color: #FFA198;
            }
        """)
        self.btn_del.clicked.connect(self._delete_selected_book)
        footer.addWidget(self.btn_del)

        main_layout.addLayout(footer)

    def load_data(self) -> None:
        """Loads books from SQLite filtered by doc_type and triggers filter application."""
        self.master_books = get_all_books(doc_type=self.doc_type_filter)
        cat_counts = get_category_counts(doc_type=self.doc_type_filter)
        total_cnt = len(self.master_books)
        self.chips_bar.populate(cat_counts, total_unique_count=total_cnt)

        # Prune cached cards that no longer exist in master_books
        current_ids = {str(b["id"]) for b in self.master_books}
        stale_ids = [bid for bid in self.cards_dict if bid not in current_ids]
        for bid in stale_ids:
            card = self.cards_dict.pop(bid)
            card.hide()
            card.deleteLater()

        self.selected_book_ids = {bid for bid in self.selected_book_ids if bid in current_ids}
        if self.selected_book_id not in current_ids:
            self.selected_book_id = None

        unit = "Studienbriefe" if self.mode == "study_scripts" else "Bücher"
        self.lbl_badge_total.setText(f"{total_cnt} {unit}")
        self._update_merge_button_label()
        self.apply_filter()

    def _set_view_mode(self, mode: str) -> None:
        if mode == "shelf":
            self.stacked_views.setCurrentIndex(0)
            self.btn_shelf.setStyleSheet("background-color: #1F6FEB; color: #FFFFFF; font-weight: bold; border: none; border-radius: 4px; padding: 5px 12px;")
            self.btn_table.setStyleSheet("background-color: transparent; color: #8B949E; border: none; border-radius: 4px; padding: 5px 12px;")
        else:
            self.stacked_views.setCurrentIndex(1)
            self.btn_table.setStyleSheet("background-color: #1F6FEB; color: #FFFFFF; font-weight: bold; border: none; border-radius: 4px; padding: 5px 12px;")
            self.btn_shelf.setStyleSheet("background-color: transparent; color: #8B949E; border: none; border-radius: 4px; padding: 5px 12px;")
            self._populate_table()

    def _on_category_selected(self, category: str) -> None:
        self.current_category = category
        self.apply_filter()

    def _on_search_changed(self, text: str) -> None:
        self.search_term = text.strip().lower()
        self.apply_filter()

    def _on_sort_changed(self, _index: int = 0) -> None:
        self.sort_mode = self.combo_sort.currentData() or "title_asc"
        self.apply_filter()

    def _on_letter_selected(self, letter: str) -> None:
        self.active_letter = letter
        self._update_letter_bar_styles()
        self.apply_filter()

    def _update_letter_bar_styles(self) -> None:
        for ltr, btn in self._letter_buttons.items():
            if ltr == self.active_letter:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1F6FEB;
                        color: #FFFFFF;
                        border: 1px solid #58A6FF;
                        border-radius: 4px;
                        font-size: 10px;
                        font-weight: bold;
                        padding: 0px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #8B949E;
                        border: none;
                        border-radius: 4px;
                        font-size: 10px;
                        font-weight: 600;
                        padding: 0px;
                    }
                    QPushButton:hover {
                        background-color: #1A243B;
                        color: #F0F6FC;
                    }
                """)

    def apply_filter(self) -> None:
        """Instant filtering (<2ms) across category, initial letter, search term, and sort mode."""
        books = list(self.master_books)

        if self.current_category != "Alle":
            target = self.current_category
            books = [b for b in books if target in (b.get("categories_str") or "")]

        if self.active_letter != "Alle":
            target_ltr = self.active_letter.upper()
            umlaut_map = {"Ä": "A", "Ö": "O", "Ü": "U"}
            filtered_by_letter = []
            for b in books:
                t_clean = (b.get("title") or "").lstrip(" ([{„\"'").upper()
                first_ch = t_clean[0] if t_clean else ""
                first_ch = umlaut_map.get(first_ch, first_ch)
                if first_ch == target_ltr:
                    filtered_by_letter.append(b)
            books = filtered_by_letter

        if self.search_term:
            q = self.search_term
            books = [
                b for b in books
                if q in b["title"].lower()
                or q in b["author"].lower()
                or q in (b.get("categories_str") or "").lower()
            ]

        # Sort filtered books according to selected sort_mode
        if self.sort_mode == "title_desc":
            books.sort(key=lambda x: (x.get("title") or "").lower(), reverse=True)
        elif self.sort_mode == "recent":
            books.sort(key=lambda x: float(x.get("file_mtime") or 0.0), reverse=True)
        elif self.sort_mode == "year_desc":
            books.sort(key=lambda x: (int(x.get("year") or 0), int(x.get("edition") or 1)), reverse=True)
        elif self.sort_mode == "pages_desc":
            books.sort(key=lambda x: int(x.get("page_count") or 0), reverse=True)
        elif self.sort_mode == "author_asc":
            books.sort(key=lambda x: ((x.get("author") or "ZZZ").lower(), (x.get("title") or "").lower()))
        else:
            books.sort(key=lambda x: (x.get("title") or "").lower())

        self.filtered_books = books
        unit = "Studienbriefen" if self.mode == "study_scripts" else "Büchern"
        self.lbl_table_count.setText(f"{len(books)} von {len(self.master_books)} {unit}")

        if self.stacked_views.currentIndex() == 0:
            self._render_shelf_grid()
        else:
            self._populate_table()

    def _render_shelf_grid(self) -> None:
        """Starts batch rendering for the shelf grid with flicker-free updates."""
        self._shelf_batch_timer.stop()

        # Flush pending layouts -> real viewport width on first show
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)

        cols, gap, side_margin = self._calculate_shelf_geometry()
        self._current_cols = cols

        # Freeze visual painting on container during bulk layout update
        self.shelf_container.setUpdatesEnabled(False)
        try:
            self.shelf_grid.setHorizontalSpacing(gap)
            self.shelf_grid.setVerticalSpacing(18)
            self.shelf_grid.setContentsMargins(side_margin, 10, side_margin, 20)

            # Collect active book IDs for current filter
            active_ids = {str(b["id"]) for b in self.filtered_books}

            # Hide cards that are filtered out
            for bid, card in self.cards_dict.items():
                if bid not in active_ids and card.isVisible():
                    card.hide()

            # Remove layout items without hiding active cards to avoid visual flash
            while self.shelf_grid.count():
                self.shelf_grid.takeAt(0)

            self._shelf_render_idx = 0
            self._render_next_shelf_batch(batch_size=36)
        finally:
            self.shelf_container.setUpdatesEnabled(True)

    def _calculate_shelf_geometry(self) -> tuple[int, int, int]:
        """Calculates optimal column count, horizontal gap, and side margin to fill width evenly."""
        avail_w = max(400, self.shelf_scroll.viewport().width() - 24)
        card_w = BookCard.CARD_WIDTH  # 176px
        min_gap = 14
        cols = max(2, min(14, (avail_w + min_gap) // (card_w + min_gap)))
        rem = avail_w - (cols * card_w)
        gap = max(min_gap, rem // max(1, cols - 1)) if cols > 1 else min_gap
        leftover = rem - (gap * (cols - 1))
        side_margin = max(8, (leftover + 24) // 2)
        return cols, gap, side_margin

    def _render_next_shelf_batch(self, batch_size: int = 48) -> None:
        if not self.filtered_books:
            return

        cols = self._current_cols or self._calculate_shelf_geometry()[0]

        start = self._shelf_render_idx
        end = min(start + batch_size, len(self.filtered_books))

        for idx in range(start, end):
            b = self.filtered_books[idx]
            bid = str(b["id"])

            if bid not in self.cards_dict:
                card = BookCard(b, self.shelf_container)
                card.clicked.connect(self._on_card_clicked)
                card.double_clicked.connect(self._on_card_double_clicked)
                card.context_menu_requested.connect(self._show_book_context_menu)
                self.cards_dict[bid] = card
            else:
                card = self.cards_dict[bid]
                card.book = b

            card.set_selected(bid in self.selected_book_ids)
            r, c = divmod(idx, cols)
            self.shelf_grid.addWidget(card, r, c)
            if not card.isVisible():
                card.show()

        self._shelf_render_idx = end
        if self._shelf_render_idx < len(self.filtered_books):
            self._shelf_batch_timer.start()
        else:
            self._shelf_batch_timer.stop()

    def _populate_table(self) -> None:
        """Populates the QTableWidget with current filtered books."""
        self.table_books.setRowCount(len(self.filtered_books))
        for r, b in enumerate(self.filtered_books):
            is_desk = bool(b.get("is_on_desk"))
            desk_str = "● Pult" if is_desk else "—"
            item_desk = QTableWidgetItem(desk_str)
            item_desk.setTextAlignment(Qt.AlignCenter)
            if is_desk:
                item_desk.setForeground(QColor("#58A6FF"))
                item_desk.setFont(QFont("Segoe UI", 9, QFont.Bold))
            else:
                item_desk.setForeground(QColor("#6E7681"))
            self.table_books.setItem(r, 0, item_desk)

            self.table_books.setItem(r, 1, QTableWidgetItem(b.get("title", "")))
            self.table_books.setItem(r, 2, QTableWidgetItem(b.get("author", "")))

            ed_str = f"{b.get('edition', 1)}. Aufl."
            item_ed = QTableWidgetItem(ed_str)
            item_ed.setTextAlignment(Qt.AlignCenter)
            self.table_books.setItem(r, 3, item_ed)

            item_p = QTableWidgetItem(str(b.get("page_count", 0)))
            item_p.setTextAlignment(Qt.AlignCenter)
            self.table_books.setItem(r, 4, item_p)

            ext_cnt = int(b.get("extract_count") or 0)
            ext_str = f"📎 {ext_cnt}" if ext_cnt > 0 else "—"
            item_ext = QTableWidgetItem(ext_str)
            item_ext.setTextAlignment(Qt.AlignCenter)
            if ext_cnt > 0:
                item_ext.setForeground(QColor("#58A6FF"))
                item_ext.setFont(QFont("Segoe UI", 9, QFont.Bold))
            else:
                item_ext.setForeground(QColor("#6E7681"))
            self.table_books.setItem(r, 5, item_ext)

            cat_str = (b.get("categories_str") or "").replace("|", "•")
            self.table_books.setItem(r, 6, QTableWidgetItem(cat_str))

    def _on_card_clicked(self, book_id: str) -> None:
        """Handles single click on a shelf book card with Explorer-like multi-selection."""
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ControlModifier:
            # Ctrl+Click: Toggle individual item in/out of selection set (just like Windows Explorer)
            if book_id in self.selected_book_ids:
                self.selected_book_ids.remove(book_id)
                if self.selected_book_id == book_id:
                    self.selected_book_id = next(iter(self.selected_book_ids)) if self.selected_book_ids else None
            else:
                self.selected_book_ids.add(book_id)
                self.selected_book_id = book_id
        elif mods & Qt.ShiftModifier and self.selected_book_id:
            # Shift+Click: Range selection from last anchor
            ids_order = [str(b["id"]) for b in self.filtered_books]
            if self.selected_book_id in ids_order and book_id in ids_order:
                i1 = ids_order.index(self.selected_book_id)
                i2 = ids_order.index(book_id)
                start, end = min(i1, i2), max(i1, i2)
                for bid in ids_order[start:end + 1]:
                    self.selected_book_ids.add(bid)
            else:
                self.selected_book_ids = {book_id}
                self.selected_book_id = book_id
        else:
            # Normal click: Single selection
            self.selected_book_ids = {book_id}
            self.selected_book_id = book_id

        self._sync_card_selection_styles()
        self._update_merge_button_label()

    def _sync_card_selection_styles(self) -> None:
        for bid, card in self.cards_dict.items():
            card.set_selected(bid in self.selected_book_ids)

    def _on_table_selection_changed(self) -> None:
        if self.stacked_views.currentIndex() != 1:
            return
        rows = {idx.row() for idx in self.table_books.selectedIndexes()}
        self.selected_book_ids = {
            str(self.filtered_books[r]["id"])
            for r in rows
            if 0 <= r < len(self.filtered_books)
        }
        if len(self.selected_book_ids) == 1:
            self.selected_book_id = next(iter(self.selected_book_ids))
        self._update_merge_button_label()

    def _update_merge_button_label(self) -> None:
        cnt = len(self.selected_book_ids)
        if cnt >= 2:
            self.btn_merge.setText(f"  {cnt} ausgewählte zusammenführen")
            self.btn_del.setText(f"  {cnt} Bücher entfernen")
            self.btn_desk.setText(f"  {cnt} auf Schreibtisch")
        else:
            self.btn_merge.setText("  Kapitel / PDFs zusammenführen")
            self.btn_del.setText("  Buch entfernen")
            self.btn_desk.setText("  Auf Schreibtisch")

    def _find_sibling_books_by_title(self, book: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Finds all books in master_books that share the exact same normalized title."""
        norm_t = (book.get("title") or "").strip().lower()
        if not norm_t or len(norm_t) < 3:
            return [book]
        return [
            b for b in self.master_books
            if (b.get("title") or "").strip().lower() == norm_t
        ]

    def _on_card_double_clicked(self, book_id: str) -> None:
        self.selected_book_id = book_id
        self.selected_book_ids = {book_id}
        self._sync_card_selection_styles()
        self._launch_book(book_id)

    def _on_table_double_click(self, row: int, col: int) -> None:
        if 0 <= row < len(self.filtered_books):
            bid = str(self.filtered_books[row]["id"])
            self.selected_book_id = bid
            self.selected_book_ids = {bid}
            self._launch_book(bid)

    def _open_selected_book(self) -> None:
        bid = self._get_active_book_id()
        if bid:
            self._launch_book(bid)

    def _open_quick_look_dialog(self) -> None:
        bid = self._get_active_book_id()
        if bid:
            self.quick_look_requested.emit(bid)

    def _toggle_selected_desk(self) -> None:
        if len(self.selected_book_ids) >= 2:
            for bid in list(self.selected_book_ids):
                toggle_desk_item(bid)
            self.data_changed.emit()
            self.load_data()
            return

        bid = self._get_active_book_id()
        if bid:
            toggle_desk_item(bid)
            self.data_changed.emit()
            self.load_data()

    def _get_active_book_id(self) -> Optional[str]:
        if self.stacked_views.currentIndex() == 0:
            if self.selected_book_id:
                return self.selected_book_id
            if self.selected_book_ids:
                return next(iter(self.selected_book_ids))
            if self.filtered_books:
                return str(self.filtered_books[0]["id"])
            return None
        else:
            r = self.table_books.currentRow()
            if 0 <= r < len(self.filtered_books):
                return str(self.filtered_books[r]["id"])
            return None

    def _refresh_single_book(self, book_id: str) -> None:
        """Updates reading progress and state for a single book without rebuilding the shelf."""
        updated = get_book_by_id(book_id)
        if not updated:
            return

        # Update in master_books
        for i, b in enumerate(self.master_books):
            if str(b.get("id")) == str(book_id):
                self.master_books[i] = updated
                break

        # Update in filtered_books
        for i, b in enumerate(self.filtered_books):
            if str(b.get("id")) == str(book_id):
                self.filtered_books[i] = updated
                if self.stacked_views.currentIndex() == 1:
                    is_desk = bool(updated.get("is_on_desk"))
                    desk_str = "● Pult" if is_desk else "—"
                    item_desk = QTableWidgetItem(desk_str)
                    item_desk.setTextAlignment(Qt.AlignCenter)
                    if is_desk:
                        item_desk.setForeground(QColor("#58A6FF"))
                        item_desk.setFont(QFont("Segoe UI", 9, QFont.Bold))
                    else:
                        item_desk.setForeground(QColor("#6E7681"))
                    self.table_books.setItem(i, 0, item_desk)
                break

        bid_str = str(book_id)
        if bid_str in self.cards_dict:
            card = self.cards_dict[bid_str]
            card.update_book_data(updated)

    def _launch_book(self, book_id: str) -> None:
        book = next((b for b in self.master_books if str(b["id"]) == str(book_id)), None)
        if not book or not book.get("file_path"):
            return
        saved_page = book.get("current_page") or 1
        cfg = load_config()
        if cfg.get("use_internal_reader", True):
            dlg = PdfReaderDialog(book, initial_page=saved_page, parent=self.window())
            dlg.exec()
            self._refresh_single_book(book_id)
        else:
            open_pdf_in_edge(book["file_path"], page=saved_page)

    def _show_book_context_menu(self, book_id: str, global_pos) -> None:
        if book_id not in self.selected_book_ids:
            self.selected_book_id = book_id
            self.selected_book_ids = {book_id}
            self._sync_card_selection_styles()
            self._update_merge_button_label()

        book = next((b for b in self.master_books if str(b["id"]) == str(book_id)), None)
        if not book:
            return

        menu = QMenu(self)

        # 1. Check if multiple cards are currently selected
        if len(self.selected_book_ids) >= 2:
            sel_books = [b for b in self.master_books if str(b["id"]) in self.selected_book_ids]
            act_merge_sel = menu.addAction(
                create_vector_icon("merge", "#D2A8FF", 14),
                f"🔗 {len(sel_books)} ausgewählte Bücher zusammenführen..."
            )
            act_merge_sel.triggered.connect(lambda: self._open_merge_dialog(catalog_books=sel_books))

            act_desk_sel = menu.addAction(
                create_vector_icon("check", "#3FB950", 14),
                f"📌 {len(sel_books)} ausgewählte auf Schreibtisch umschalten"
            )
            act_desk_sel.triggered.connect(self._toggle_selected_desk)

            act_del_sel = menu.addAction(
                create_vector_icon("trash", "#FF7B72", 14),
                f"🗑️ {len(sel_books)} ausgewählte Bücher entfernen..."
            )
            act_del_sel.triggered.connect(self._delete_multiple_books_prompt)
            menu.addSeparator()

        # 2. Check if this book has multiple sibling parts in the catalog (same book title!)
        siblings = self._find_sibling_books_by_title(book)
        if len(siblings) >= 2:
            short_t = (book.get("title") or "Buch")[:36]
            act_merge_siblings = menu.addAction(
                create_vector_icon("merge", "#58A6FF", 14),
                f"🔗 Alle {len(siblings)} Teile von „{short_t}“ zusammenführen..."
            )
            act_merge_siblings.triggered.connect(lambda: self._open_merge_dialog(catalog_books=siblings))
            menu.addSeparator()

        act_ql = menu.addAction(create_vector_icon("search", "#58A6FF", 14), "Quick-Look & Details (Leertaste)")
        act_ql.triggered.connect(lambda: self.quick_look_requested.emit(book_id))

        act_open = menu.addAction(create_vector_icon("desk", "#58A6FF", 14), "PDF direkt in Edge öffnen")
        act_open.triggered.connect(lambda: self._launch_book(book_id))

        act_exp = menu.addAction(create_vector_icon("export", "#8B949E", 14), "Im Windows Explorer anzeigen")
        act_exp.triggered.connect(lambda: self._show_in_explorer(book.get("file_path", "")))

        act_extract = menu.addAction(create_vector_icon("notes", "#E3B341", 14), "Seiten / Kapitel extrahieren...")
        act_extract.triggered.connect(lambda: self._extract_book_pages(book))

        act_merge = menu.addAction(create_vector_icon("merge", "#D2A8FF", 14), "Weitere Kapitel / PDFs an dieses Buch anfügen...")
        act_merge.triggered.connect(lambda: self._open_merge_dialog(base_book=book))

        ext_cnt = int(book.get("extract_count") or 0)
        if ext_cnt > 0:
            act_show_ext = menu.addAction(create_vector_icon("bookmark", "#D2A8FF", 14), f"Angeheftete Kapitel ({ext_cnt}) anzeigen...")
            act_show_ext.triggered.connect(lambda: self.quick_look_requested.emit(book_id))

        is_on_desk = bool(book.get("is_on_desk"))
        desk_text = "Vom Schreibtisch entfernen" if is_on_desk else "Auf den Schreibtisch legen"
        desk_icon = create_vector_icon("trash", "#FF7B72", 14) if is_on_desk else create_vector_icon("check", "#3FB950", 14)
        act_desk = menu.addAction(desk_icon, desk_text)
        act_desk.triggered.connect(lambda: self._toggle_desk_action(book_id))

        menu.addSeparator()

        # Classification Switcher
        current_dtype = book.get("doc_type") or "book"
        if current_dtype == "study_script":
            act_reclass = menu.addAction(create_vector_icon("library", "#58A6FF", 14), "Als Fachbuch einordnen")
            act_reclass.triggered.connect(lambda: self._reclassify_doc(book_id, "book"))
        else:
            act_reclass = menu.addAction(create_vector_icon("notes", "#58A6FF", 14), "Als Studienbrief / Skript einordnen")
            act_reclass.triggered.connect(lambda: self._reclassify_doc(book_id, "study_script"))

        # Citations Submenu
        cite_menu = menu.addMenu(create_vector_icon("copy", "#58A6FF", 14), "Zitat kopieren")
        act_bib = cite_menu.addAction(create_vector_icon("copy", "#8B949E", 13), "Als BibTeX kopieren (LaTeX)")
        act_bib.triggered.connect(lambda: self._copy_citation(book, "bibtex"))
        act_apa = cite_menu.addAction(create_vector_icon("copy", "#8B949E", 13), "Als APA 7 kopieren")
        act_apa.triggered.connect(lambda: self._copy_citation(book, "apa"))
        act_md = cite_menu.addAction(create_vector_icon("copy", "#8B949E", 13), "Als Markdown-Link kopieren")
        act_md.triggered.connect(lambda: self._copy_citation(book, "md"))

        menu.addSeparator()

        # Delete Book Action
        act_del = menu.addAction(create_vector_icon("trash", "#FF7B72", 14), "Aus Katalog entfernen...")
        act_del.triggered.connect(lambda: self._delete_book_prompt(book_id))

        menu.exec(global_pos)

    def _on_table_context_menu(self, pos) -> None:
        r = self.table_books.currentRow()
        if 0 <= r < len(self.filtered_books):
            bid = str(self.filtered_books[r]["id"])
            self._show_book_context_menu(bid, self.table_books.mapToGlobal(pos))

    def _show_in_explorer(self, path: str) -> None:
        if path and os.path.exists(path):
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])

    def _toggle_desk_action(self, book_id: str) -> None:
        toggle_desk_item(book_id)
        self.data_changed.emit()
        self.load_data()

    def _reclassify_doc(self, book_id: str, new_doc_type: str) -> None:
        set_book_doc_type(book_id, new_doc_type)
        if str(book_id) in self.cards_dict:
            card = self.cards_dict.pop(str(book_id))
            card.hide()
            card.deleteLater()
        self.data_changed.emit()
        self.load_data()

    def _extract_book_pages(self, book: Dict[str, Any]) -> None:
        from ui.qt.dialogs.pdf_extract_dialog import PdfExtractDialog
        dlg = PdfExtractDialog(book, parent=self.window())
        if dlg.exec():
            self.data_changed.emit()
            self.load_data()

    def _on_footer_merge_clicked(self) -> None:
        """Smart handler for the footer Merge button:
        - If >=2 books are selected, merges those selected books.
        - If 1 book is selected and it has sibling parts in the catalog (same title), automatically loads all siblings!
        - Otherwise opens the Merge Studio.
        """
        if len(self.selected_book_ids) >= 2:
            sel_books = [b for b in self.master_books if str(b["id"]) in self.selected_book_ids]
            self._open_merge_dialog(catalog_books=sel_books)
            return

        bid = self._get_active_book_id()
        if bid:
            book = next((b for b in self.master_books if str(b["id"]) == str(bid)), None)
            if book:
                siblings = self._find_sibling_books_by_title(book)
                if len(siblings) >= 2:
                    self._open_merge_dialog(catalog_books=siblings)
                    return

        self._open_merge_dialog()

    def _open_merge_dialog(
        self,
        base_book: Optional[Dict[str, Any]] = None,
        catalog_books: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        from ui.qt.dialogs.pdf_merge_dialog import PdfMergeDialog
        dlg = PdfMergeDialog(
            catalog_books=catalog_books,
            default_doc_type=self.doc_type_filter,
            base_book=base_book,
            parent=self.window(),
        )
        if dlg.exec():
            self.selected_book_ids.clear()
            self.selected_book_id = None
            self.data_changed.emit()
            self.load_data()

    def _copy_citation(self, book: Dict[str, Any], fmt: str) -> None:
        from core.citations import generate_bibtex, generate_apa, generate_markdown_link
        if fmt == "bibtex":
            txt = generate_bibtex(book)
        elif fmt == "apa":
            txt = generate_apa(book)
        else:
            txt = generate_markdown_link(book)
        QApplication.clipboard().setText(txt)

    def _delete_selected_book(self) -> None:
        if len(self.selected_book_ids) >= 2:
            self._delete_multiple_books_prompt()
            return
        bid = self._get_active_book_id()
        if bid:
            self._delete_book_prompt(bid)

    def _delete_multiple_books_prompt(self) -> None:
        """Batch removal dialog for multiple selected books in the catalog."""
        ids_to_del = list(self.selected_book_ids)
        if not ids_to_del:
            return

        cnt = len(ids_to_del)
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(f"{cnt} Bücher entfernen")
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setText(f"Möchtest du wirklich die <b>{cnt} ausgewählten Bücher</b> aus dem Katalog entfernen?")
        msg_box.setInformativeText("Notizen, Lesefortschritt und Index-Daten dieser Bücher werden gelöscht.")

        chk_delete_file = QCheckBox("Auch alle zugehörigen PDF-Dateien von der Festplatte löschen")
        chk_delete_file.setStyleSheet("color: #FF7B72; font-weight: bold; margin-top: 10px;")
        msg_box.setCheckBox(chk_delete_file)

        btn_cancel = msg_box.addButton("Abbrechen", QMessageBox.RejectRole)
        btn_del = msg_box.addButton(f"{cnt} Bücher entfernen", QMessageBox.AcceptRole)
        btn_del.setStyleSheet("background-color: #DA3633; color: #FFFFFF; font-weight: bold; padding: 6px 14px; border-radius: 4px;")

        msg_box.exec()

        if msg_box.clickedButton() == btn_del:
            delete_file_disk = chk_delete_file.isChecked()
            for bid in ids_to_del:
                success, _ = delete_book(bid, delete_file=delete_file_disk)
                if success and str(bid) in self.cards_dict:
                    card = self.cards_dict.pop(str(bid))
                    card.hide()
                    card.deleteLater()

            self.selected_book_ids.clear()
            self.selected_book_id = None
            self.data_changed.emit()
            self.load_data()

    def _delete_book_prompt(self, book_id: str) -> None:
        book = next((b for b in self.master_books if str(b["id"]) == str(book_id)), None)
        if not book:
            return

        title = book.get("title", "Dieses Buch")
        file_path = book.get("file_path", "")

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
            success, err = delete_book(book_id, delete_file=delete_file_disk)
            if success:
                if str(book_id) in self.cards_dict:
                    card = self.cards_dict.pop(str(book_id))
                    card.hide()
                    card.deleteLater()
                self.selected_book_ids.discard(str(book_id))
                if self.selected_book_id == str(book_id):
                    self.selected_book_id = None
                self.data_changed.emit()
                self.load_data()
            else:
                QMessageBox.critical(self, "Fehler beim Löschen", err or "Unbekannter Fehler.")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.stacked_views.currentIndex() == 0 and self.filtered_books:
            self._resize_timer.start()

    def _handle_debounced_resize(self) -> None:
        if self.stacked_views.currentIndex() != 0 or not self.filtered_books:
            return
        new_cols, _, _ = self._calculate_shelf_geometry()
        if new_cols != self._current_cols:
            self._render_shelf_grid()
