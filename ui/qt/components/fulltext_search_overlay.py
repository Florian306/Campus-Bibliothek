"""Full-Text Search Results View & Preview Dialog for Campus-Bibliothek.
Displays instant search hits across book contents with page jumps, highlighted snippets, and cover badges.
"""

from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.fulltext_search import search_fulltext, get_fts_index_stats
from core.cover_manager import get_book_cover_blob


class FullTextResultItem(QFrame):
    """Single full-text match result card with document cover thumbnail, page badge, and highlighted snippet."""

    page_jump_requested = Signal(str, int)  # (file_path, page_number)

    def __init__(self, data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.data = data
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("ftsResultItem")
        self.setStyleSheet("""
            QFrame#ftsResultItem {
                background-color: #0E1524;
                border: 1px solid #1C273C;
                border-left: 3px solid #58A6FF;
                border-radius: 9px;
            }
            QFrame#ftsResultItem:hover {
                background-color: #131E33;
                border-color: #388BFD;
                border-left: 3px solid #79B8FF;
            }
        """)

        main_row = QHBoxLayout(self)
        main_row.setContentsMargins(14, 12, 14, 12)
        main_row.setSpacing(14)

        # 1. Left Thumbnail Column
        self.thumb_lbl = QLabel()
        self.thumb_lbl.setFixedSize(48, 68)
        self.thumb_lbl.setAlignment(Qt.AlignCenter)
        self.thumb_lbl.setStyleSheet("""
            background-color: #080C14;
            border: 1px solid #1F2C44;
            border-radius: 5px;
        """)

        # Load cover blob if available
        book_id = self.data.get("book_id")
        loaded_thumb = False
        if book_id:
            try:
                blob = get_book_cover_blob(book_id)
                if blob:
                    pm = QPixmap()
                    if pm.loadFromData(blob):
                        scaled = pm.scaled(48, 68, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                        self.thumb_lbl.setPixmap(scaled)
                        loaded_thumb = True
            except Exception:
                loaded_thumb = False

        if not loaded_thumb:
            self.thumb_lbl.setPixmap(create_vector_pixmap(
                "notes" if self.data.get("doc_type") == "study_script" else "book",
                "#58A6FF",
                20
            ))

        main_row.addWidget(self.thumb_lbl)

        # 2. Middle Content Column
        content_box = QVBoxLayout()
        content_box.setSpacing(6)

        # Header: Title + Author
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        lbl_title = QLabel(self.data.get("title", "Unbekannt"))
        lbl_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        title_row.addWidget(lbl_title)

        author_str = self.data.get("author", "Unbekannter Autor")
        year_str = f" · {self.data.get('year')}" if self.data.get("year") else ""
        lbl_sub = QLabel(f"von {author_str}{year_str}")
        lbl_sub.setFont(QFont("Segoe UI", 8))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        title_row.addWidget(lbl_sub)
        title_row.addStretch()

        content_box.addLayout(title_row)

        # Highlighted Snippet Box
        snippet_html = self.data.get("snippet", "")
        if snippet_html:
            lbl_snip = QLabel(f"» {snippet_html} «")
            lbl_snip.setTextFormat(Qt.RichText)
            lbl_snip.setWordWrap(True)
            lbl_snip.setFont(QFont("Segoe UI", 9))
            lbl_snip.setStyleSheet("""
                background-color: #070B12;
                color: #C9D1D9;
                border: 1px solid #162032;
                border-radius: 6px;
                padding: 6px 12px;
                line-height: 1.45;
            """)
            content_box.addWidget(lbl_snip)

        main_row.addLayout(content_box, stretch=1)

        # 3. Right Action Column: Page Number Badge + Jump Button
        action_box = QVBoxLayout()
        action_box.setSpacing(8)
        action_box.setAlignment(Qt.AlignCenter)

        page_num = self.data.get("page_number", 1)
        lbl_page = QLabel(f"SEITE {page_num}")
        lbl_page.setAlignment(Qt.AlignCenter)
        lbl_page.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_page.setStyleSheet("""
            background-color: #152238;
            color: #79C0FF;
            border: 1px solid #233758;
            border-radius: 5px;
            padding: 4px 10px;
            font-size: 10px;
            letter-spacing: 0.5px;
        """)
        action_box.addWidget(lbl_page)

        btn_open = QPushButton("  Zur Seite springen")
        btn_open.setIcon(create_vector_icon("research", "#FFFFFF", 12))
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(30)
        btn_open.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 0 14px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #58A6FF;
            }
        """)
        btn_open.clicked.connect(self._on_jump_clicked)
        action_box.addWidget(btn_open)

        main_row.addLayout(action_box)

    def _on_jump_clicked(self) -> None:
        file_path = self.data.get("file_path")
        page_num = self.data.get("page_number", 1)
        if file_path:
            self.page_jump_requested.emit(file_path, page_num)


class FullTextSearchOverlay(QWidget):
    """Full-page overlay or container displaying real-time full-text search results."""

    open_reader_requested = Signal(str, int)  # (file_path, page_number)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        # Stats & Header bar
        self.header_frame = QFrame()
        self.header_frame.setStyleSheet("""
            QFrame {
                background-color: #0E1522;
                border: 1px solid #1E2B42;
                border-radius: 8px;
            }
        """)
        h_lay = QHBoxLayout(self.header_frame)
        h_lay.setContentsMargins(14, 8, 14, 8)

        self.lbl_info = QLabel("🔍 Volltext-Suche in allen archivierten Buchseiten")
        self.lbl_info.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_info.setStyleSheet("color: #C9D1D9; border: none; background: transparent;")
        h_lay.addWidget(self.lbl_info)
        h_lay.addStretch()

        self.lbl_hits = QLabel("0 Fundstellen")
        self.lbl_hits.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_hits.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        h_lay.addWidget(self.lbl_hits)

        main_layout.addWidget(self.header_frame)

        # Scroll area for hit results
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        self.results_container = QWidget()
        self.results_container.setStyleSheet("background-color: transparent;")
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 4, 8, 12)
        self.results_layout.setSpacing(10)

        self.scroll.setWidget(self.results_container)
        main_layout.addWidget(self.scroll, stretch=1)

    def perform_search(self, query: str) -> None:
        """Executes full-text query and renders result cards."""
        # Clear previous items
        while self.results_layout.count() > 0:
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        clean_q = query.strip()
        if not clean_q or len(clean_q) < 2:
            self.lbl_hits.setText("Suchbegriff eingeben...")
            return

        matches = search_fulltext(clean_q, limit=60)
        self.lbl_hits.setText(f"{len(matches)} Fundstellen")

        if not matches:
            lbl_empty = QLabel(
                f"Keine Textpassagen für «{clean_q}» im Volltext-Index gefunden.\n\n"
                "💡 Tipp: Öffne den 'Scan & Sync' Tab und klicke auf 'Index aktualisieren',\n"
                "um alle Buchseiten für die sekundenschnelle Volltextsuche einzulesen."
            )
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setFont(QFont("Segoe UI", 10))
            lbl_empty.setStyleSheet("color: #8B949E; line-height: 1.5; padding: 40px;")
            self.results_layout.addWidget(lbl_empty)
            return

        for data in matches:
            item = FullTextResultItem(data)
            item.page_jump_requested.connect(self._on_jump_requested)
            self.results_layout.addWidget(item)

        self.results_layout.addStretch()
        self.results_container.adjustSize()
        self.scroll.verticalScrollBar().setValue(0)

    def _on_jump_requested(self, file_path: str, page_num: int) -> None:
        self.open_reader_requested.emit(file_path, page_num)
