"""Full-Text Search Results View & Preview Dialog for Campus-Bibliothek.
Displays instant search hits across book contents with page jumps, highlighted snippets, and cover badges.
"""

from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
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


class FullTextResultItem(QFrame):
    """Single full-text match result showing document info, page number badge, and highlighted snippet."""

    page_jump_requested = Signal(str, int)  # (file_path, page_number)

    def __init__(self, data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.data = data
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("ftsResultItem")
        self.setStyleSheet("""
            QFrame#ftsResultItem {
                background-color: #101625;
                border: 1px solid #1C273C;
                border-radius: 8px;
            }
            QFrame#ftsResultItem:hover {
                background-color: #141D30;
                border-color: #388BFD;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Header Row: Title, Author, Page Badge, and Open Button
        head_row = QHBoxLayout()
        head_row.setSpacing(10)

        # Document Icon
        ico_lbl = QLabel()
        ico_lbl.setPixmap(create_vector_pixmap("notes" if self.data.get("doc_type") == "study_script" else "book", "#58A6FF", 16))
        head_row.addWidget(ico_lbl)

        # Title & Author
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        lbl_title = QLabel(self.data.get("title", "Unbekannt"))
        lbl_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        title_box.addWidget(lbl_title)

        author_str = self.data.get("author", "Unbekannter Autor")
        year_str = f" ({self.data.get('year')})" if self.data.get("year") else ""
        lbl_sub = QLabel(f"{author_str}{year_str}")
        lbl_sub.setFont(QFont("Segoe UI", 8))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        title_box.addWidget(lbl_sub)
        head_row.addLayout(title_box, stretch=1)

        # Page Number Badge
        page_num = self.data.get("page_number", 1)
        lbl_page = QLabel(f"Seite {page_num}")
        lbl_page.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_page.setStyleSheet("""
            background-color: #1A2740;
            color: #58A6FF;
            border: 1px solid #283D66;
            border-radius: 6px;
            padding: 4px 10px;
        """)
        head_row.addWidget(lbl_page)

        # Jump Button
        btn_open = QPushButton("  Zur Seite springen")
        btn_open.setIcon(create_vector_icon("research", "#FFFFFF", 12))
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(28)
        btn_open.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: none;
                border-radius: 5px;
                padding: 0 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #58A6FF;
            }
        """)
        btn_open.clicked.connect(self._on_jump_clicked)
        head_row.addWidget(btn_open)

        layout.addLayout(head_row)

        # Snippet Box
        snippet_html = self.data.get("snippet", "")
        if snippet_html:
            lbl_snip = QLabel(f"» {snippet_html} «")
            lbl_snip.setTextFormat(Qt.RichText)
            lbl_snip.setWordWrap(True)
            lbl_snip.setFont(QFont("Segoe UI", 9))
            lbl_snip.setStyleSheet("""
                background-color: #0B0F19;
                color: #C9D1D9;
                border: 1px solid #162032;
                border-radius: 6px;
                padding: 8px 12px;
            """)
            layout.addWidget(lbl_snip)

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
