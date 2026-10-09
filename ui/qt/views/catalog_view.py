"""Catalog and Library View for PySide6.
Provides dual view modes: Interactive Shelf Grid & Searchable Table List.
"""

import os
import subprocess
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal, QTimer
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
)

from ui.qt.components.book_card import BookCard
from ui.qt.components.category_chips import CategoryChipsBar
from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate
from core.library_db import (
    get_all_books,
    get_category_counts,
    toggle_desk_item,
    update_reading_progress,
    open_pdf_in_edge,
    get_book_categories,
    delete_book,
)
from core.config import load_config
from ui.qt.dialogs.pdf_reader_dialog import PdfReaderDialog


class CatalogView(QWidget):
    """Main Catalog and Library browser."""

    book_launched = Signal(str)       # book_id
    quick_look_requested = Signal(str) # book_id
    desk_toggled = Signal(str)        # book_id
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.master_books: List[Dict[str, Any]] = []
        self.filtered_books: List[Dict[str, Any]] = []
        self.selected_book_id: Optional[str] = None
        self.current_category = "Alle"
        self.search_term = ""

        # Shelf cards cache
        self.cards_dict: Dict[str, BookCard] = {}
        self._shelf_render_idx = 0
        self._shelf_batch_timer = QTimer(self)
        self._shelf_batch_timer.setInterval(15)
        self._shelf_batch_timer.timeout.connect(self._render_next_shelf_batch)

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
        lbl_title = QLabel("Katalog & Literaturverzeichnis")
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC;")
        title_row.addWidget(lbl_title)

        self.lbl_badge_total = QLabel("0 Bücher")
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

        lbl_desc = QLabel("Zentrales Register aller archivierten Fach- und Lehrbücher mit Volltext-Index")
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

        # Search Input
        self.ent_search = QLineEdit()
        self.ent_search.setPlaceholderText("🔍 Suchen nach Titel, Autor, Fach...")
        self.ent_search.setFixedWidth(280)
        self.ent_search.textChanged.connect(self._on_search_changed)
        self.ent_search.setClearButtonEnabled(True)
        top_bar.addWidget(self.ent_search)

        main_layout.addLayout(top_bar)

        # -------------------------------------------------------------
        # 2. Category Chips Bar
        # -------------------------------------------------------------
        self.chips_bar = CategoryChipsBar(self)
        self.chips_bar.category_selected.connect(self._on_category_selected)
        main_layout.addWidget(self.chips_bar)

        # -------------------------------------------------------------
        # 3. Stacked View Container (Shelf vs. Table)
        # -------------------------------------------------------------
        self.stacked_views = QStackedWidget(self)

        # View 0: Virtual Shelf ScrollArea
        self.shelf_scroll = QScrollArea()
        self.shelf_scroll.setWidgetResizable(True)
        self.shelf_scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.shelf_container = QWidget()
        self.shelf_container.setStyleSheet("background-color: transparent;")
        self.shelf_grid = QGridLayout(self.shelf_container)
        self.shelf_grid.setContentsMargins(4, 8, 4, 16)
        self.shelf_grid.setSpacing(16)
        self.shelf_scroll.setWidget(self.shelf_container)

        self.stacked_views.addWidget(self.shelf_scroll)

        # View 1: Catalog Table
        self.table_books = QTableWidget()
        self.table_books.setItemDelegate(NoFocusItemDelegate(self.table_books))
        self.table_books.setColumnCount(7)
        self.table_books.setHorizontalHeaderLabels(["Pult", "Buchtitel", "Autor", "Auflage", "Seiten", "Kapitel", "Fachbereiche"])
        self.table_books.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_books.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_books.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.table_books.setColumnWidth(5, 75)
        self.table_books.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_books.setSelectionMode(QTableWidget.SingleSelection)
        self.table_books.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_books.verticalHeader().setVisible(False)
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

        lbl_tips = QLabel("Tipp: Leertaste für Quick-Look • Doppelklick öffnet PDF • Rechtsklick für Zitate & Notizen")
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

        btn_desk = QPushButton("  Auf Schreibtisch")
        btn_desk.setIcon(create_vector_icon("check", "#3FB950", 16))
        btn_desk.setCursor(Qt.PointingHandCursor)
        btn_desk.setFixedHeight(34)
        btn_desk.clicked.connect(self._toggle_selected_desk)
        footer.addWidget(btn_desk)

        btn_del = QPushButton("  Buch entfernen")
        btn_del.setIcon(create_vector_icon("trash", "#FF7B72", 15))
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setFixedHeight(34)
        btn_del.setStyleSheet("""
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
        btn_del.clicked.connect(self._delete_selected_book)
        footer.addWidget(btn_del)

        main_layout.addLayout(footer)

    def load_data(self) -> None:
        """Loads all books from SQLite and triggers filter application."""
        self.master_books = get_all_books()
        cat_counts = get_category_counts()
        self.chips_bar.populate(cat_counts)
        self.cards_dict.clear()

        total_cnt = len(self.master_books)
        self.lbl_badge_total.setText(f"{total_cnt} Bücher")
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

    def apply_filter(self) -> None:
        """Instant filtering (<2ms) across category and search term."""
        books = self.master_books

        if self.current_category != "Alle":
            target = self.current_category
            books = [b for b in books if target in (b.get("categories_str") or "")]

        if self.search_term:
            q = self.search_term
            books = [
                b for b in books
                if q in b["title"].lower()
                or q in b["author"].lower()
                or q in (b.get("categories_str") or "").lower()
            ]

        self.filtered_books = books
        self.lbl_table_count.setText(f"{len(books)} von {len(self.master_books)} Büchern")

        if self.stacked_views.currentIndex() == 0:
            self._render_shelf_grid()
        else:
            self._populate_table()

    def _render_shelf_grid(self) -> None:
        """Starts batch rendering for the shelf grid without freezing the UI."""
        self._shelf_batch_timer.stop()

        # Clear existing layout items
        while self.shelf_grid.count():
            item = self.shelf_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()

        self._shelf_render_idx = 0
        self._render_next_shelf_batch(batch_size=24)

    def _render_next_shelf_batch(self, batch_size: int = 28) -> None:
        if not self.filtered_books:
            return

        cols = max(2, min(7, self.shelf_scroll.width() // (BookCard.CARD_WIDTH + 18)))
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
                card.setParent(self.shelf_container)
                card.show()

            card.set_selected(bid == self.selected_book_id)
            r, c = divmod(idx, cols)
            self.shelf_grid.addWidget(card, r, c)

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
        old_id = self.selected_book_id
        self.selected_book_id = book_id
        if old_id and old_id in self.cards_dict:
            self.cards_dict[old_id].set_selected(False)
        if book_id in self.cards_dict:
            self.cards_dict[book_id].set_selected(True)

    def _on_card_double_clicked(self, book_id: str) -> None:
        self.selected_book_id = book_id
        self._launch_book(book_id)

    def _on_table_double_click(self, row: int, col: int) -> None:
        if 0 <= row < len(self.filtered_books):
            bid = str(self.filtered_books[row]["id"])
            self.selected_book_id = bid
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
        bid = self._get_active_book_id()
        if bid:
            toggle_desk_item(bid)
            self.data_changed.emit()
            self.load_data()

    def _get_active_book_id(self) -> Optional[str]:
        if self.stacked_views.currentIndex() == 0:
            if self.selected_book_id:
                return self.selected_book_id
            if self.filtered_books:
                return str(self.filtered_books[0]["id"])
            return None
        else:
            r = self.table_books.currentRow()
            if 0 <= r < len(self.filtered_books):
                return str(self.filtered_books[r]["id"])
            return None

    def _launch_book(self, book_id: str) -> None:
        book = next((b for b in self.master_books if str(b["id"]) == str(book_id)), None)
        if not book or not book.get("file_path"):
            return
        saved_page = book.get("current_page") or 1
        cfg = load_config()
        if cfg.get("use_internal_reader", True):
            dlg = PdfReaderDialog(book, initial_page=saved_page, parent=self)
            dlg.progress_updated.connect(lambda bid, p: self.load_data())
            dlg.exec()
            self.load_data()
        else:
            open_pdf_in_edge(book["file_path"], page=saved_page)

    def _show_book_context_menu(self, book_id: str, global_pos) -> None:
        self._on_card_clicked(book_id)
        book = next((b for b in self.master_books if str(b["id"]) == str(book_id)), None)
        if not book:
            return

        menu = QMenu(self)
        act_ql = menu.addAction("Quick-Look & Details (Leertaste)")
        act_ql.triggered.connect(lambda: self.quick_look_requested.emit(book_id))

        act_open = menu.addAction("PDF direkt in Edge öffnen")
        act_open.triggered.connect(lambda: self._launch_book(book_id))

        act_exp = menu.addAction("Im Explorer anzeigen")
        act_exp.triggered.connect(lambda: self._show_in_explorer(book.get("file_path", "")))

        act_extract = menu.addAction("✂ Seiten / Kapitel extrahieren...")
        act_extract.triggered.connect(lambda: self._extract_book_pages(book))

        ext_cnt = int(book.get("extract_count") or 0)
        if ext_cnt > 0:
            act_show_ext = menu.addAction(f"📎 Angeheftete Kapitel ({ext_cnt}) anzeigen...")
            act_show_ext.triggered.connect(lambda: self.quick_look_requested.emit(book_id))

        act_desk = menu.addAction("Auf Schreibtisch / entfernen")
        act_desk.triggered.connect(lambda: self._toggle_desk_action(book_id))

        menu.addSeparator()

        # Delete Book Action
        act_del = menu.addAction(create_vector_icon("trash", "#FF7B72", 14), "Buch aus Katalog entfernen...")
        act_del.triggered.connect(lambda: self._delete_book_prompt(book_id))

        menu.addSeparator()

        # Citations Submenu
        cite_menu = menu.addMenu("Zitat kopieren")
        act_bib = cite_menu.addAction("Als BibTeX kopieren (LaTeX)")
        act_bib.triggered.connect(lambda: self._copy_citation(book, "bibtex"))
        act_apa = cite_menu.addAction("Als APA 7 kopieren")
        act_apa.triggered.connect(lambda: self._copy_citation(book, "apa"))
        act_md = cite_menu.addAction("Als Markdown-Link kopieren")
        act_md.triggered.connect(lambda: self._copy_citation(book, "md"))

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

    def _extract_book_pages(self, book: Dict[str, Any]) -> None:
        from ui.qt.dialogs.pdf_extract_dialog import PdfExtractDialog
        dlg = PdfExtractDialog(book, parent=self)
        if dlg.exec():
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
        bid = self._get_active_book_id()
        if bid:
            self._delete_book_prompt(bid)

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
                # Remove card from cache if present
                if str(book_id) in self.cards_dict:
                    card = self.cards_dict.pop(str(book_id))
                    card.hide()
                    card.deleteLater()
                if self.selected_book_id == str(book_id):
                    self.selected_book_id = None
                self.data_changed.emit()
                self.load_data()
            else:
                QMessageBox.critical(self, "Fehler beim Löschen", err or "Unbekannter Fehler.")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.stacked_views.currentIndex() == 0 and self.filtered_books:
            # Re-flow cards dynamically on window resize
            QTimer.singleShot(50, self._render_shelf_grid)

