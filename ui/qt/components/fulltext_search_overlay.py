"""Full-Text Search Results View & Interactive Preview Inspector for Campus-Bibliothek.
Groups hits logically by document with collapsible accordion cards, snippet expanders,
and an instant right-side page rendering preview inspector.
"""

from typing import Any, Dict, List, Optional
import os
import pymupdf
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QFont, QColor, QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSplitter,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.fulltext_search import search_fulltext, get_fts_index_stats
from core.cover_manager import get_book_cover_blob


class HitSnippetRow(QFrame):
    """Single page match row with quick jump button, page badge, and preview selector."""

    page_selected = Signal(str, int)  # (file_path, page_number)
    open_reader_requested = Signal(str, int)

    def __init__(self, hit_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.hit_data = hit_data
        self.file_path = hit_data.get("file_path", "")
        self.page_num = hit_data.get("page_number", 1)
        self.snippet_html = hit_data.get("snippet", "")
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("hitSnippetRow")
        self.setStyleSheet("""
            QFrame#hitSnippetRow {
                background-color: #0B101B;
                border: 1px solid #182234;
                border-radius: 7px;
            }
            QFrame#hitSnippetRow:hover {
                background-color: #121A2C;
                border-color: #388BFD;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # Page Badge
        lbl_p = QLabel(f"S. {self.page_num}")
        lbl_p.setAlignment(Qt.AlignCenter)
        lbl_p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_p.setFixedWidth(54)
        lbl_p.setStyleSheet("""
            background-color: #152238;
            color: #79C0FF;
            border: 1px solid #233758;
            border-radius: 4px;
            padding: 3px 6px;
        """)
        layout.addWidget(lbl_p)

        # Snippet Text
        lbl_snip = QLabel(f"» {self.snippet_html} «")
        lbl_snip.setTextFormat(Qt.RichText)
        lbl_snip.setWordWrap(True)
        lbl_snip.setFont(QFont("Segoe UI", 9))
        lbl_snip.setStyleSheet("color: #C9D1D9; border: none; background: transparent; line-height: 1.4;")
        layout.addWidget(lbl_snip, stretch=1)

        # Actions
        btn_preview = QPushButton("Vorschau")
        btn_preview.setCursor(Qt.PointingHandCursor)
        btn_preview.setFixedHeight(26)
        btn_preview.setStyleSheet("""
            QPushButton {
                background-color: #162032;
                color: #8B949E;
                border: 1px solid #253550;
                border-radius: 4px;
                padding: 0 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1F2D44;
                color: #FFFFFF;
                border-color: #58A6FF;
            }
        """)
        btn_preview.clicked.connect(lambda: self.page_selected.emit(self.file_path, self.page_num))
        layout.addWidget(btn_preview)

        btn_jump = QPushButton("Öffnen ↗")
        btn_jump.setCursor(Qt.PointingHandCursor)
        btn_jump.setFixedHeight(26)
        btn_jump.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #58A6FF;
            }
        """)
        btn_jump.clicked.connect(lambda: self.open_reader_requested.emit(self.file_path, self.page_num))
        layout.addWidget(btn_jump)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.page_selected.emit(self.file_path, self.page_num)
        super().mousePressEvent(event)


class BookGroupAccordionItem(QFrame):
    """Group card representing all matches within a specific book with collapsible hit list."""

    preview_requested = Signal(str, int)
    open_requested = Signal(str, int)

    def __init__(self, book_title: str, book_data: Dict[str, Any], hits: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.book_title = book_title
        self.book_data = book_data
        self.hits = hits
        self._is_expanded = True
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("bookGroupItem")
        self.setStyleSheet("""
            QFrame#bookGroupItem {
                background-color: #0E1524;
                border: 1px solid #1C273C;
                border-radius: 10px;
            }
        """)

        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(12, 10, 12, 10)
        main_vbox.setSpacing(8)

        # Header Row
        header_widget = QWidget()
        header_widget.setCursor(Qt.PointingHandCursor)
        h_lay = QHBoxLayout(header_widget)
        h_lay.setContentsMargins(0, 0, 0, 0)
        h_lay.setSpacing(12)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(38, 52)
        thumb_lbl.setAlignment(Qt.AlignCenter)
        thumb_lbl.setStyleSheet("background-color: #080C14; border: 1px solid #1F2C44; border-radius: 4px;")

        book_id = self.book_data.get("book_id")
        loaded_thumb = False
        if book_id:
            try:
                blob = get_book_cover_blob(book_id)
                if blob:
                    pm = QPixmap()
                    if pm.loadFromData(blob):
                        thumb_lbl.setPixmap(pm.scaled(38, 52, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                        loaded_thumb = True
            except Exception:
                pass
        if not loaded_thumb:
            thumb_lbl.setPixmap(create_vector_pixmap("book", "#58A6FF", 18))
        h_lay.addWidget(thumb_lbl)

        # Meta info
        meta_box = QVBoxLayout()
        meta_box.setSpacing(3)
        lbl_t = QLabel(self.book_title)
        lbl_t.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_t.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        meta_box.addWidget(lbl_t)

        author_str = self.book_data.get("author", "Unbekannter Autor")
        year_str = f" · {self.book_data.get('year')}" if self.book_data.get("year") else ""
        lbl_sub = QLabel(f"von {author_str}{year_str}")
        lbl_sub.setFont(QFont("Segoe UI", 8))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        meta_box.addWidget(lbl_sub)
        h_lay.addLayout(meta_box, stretch=1)

        # Hit count pill badge
        count_pill = QLabel(f"{len(self.hits)} Fundstelle{'n' if len(self.hits) > 1 else ''}")
        count_pill.setFont(QFont("Segoe UI", 9, QFont.Bold))
        count_pill.setStyleSheet("""
            background-color: #121D30;
            color: #58A6FF;
            border: 1px solid #1F365A;
            border-radius: 12px;
            padding: 4px 12px;
        """)
        h_lay.addWidget(count_pill)

        self.btn_toggle = QPushButton("▼")
        self.btn_toggle.setFixedSize(24, 24)
        self.btn_toggle.setStyleSheet("background: transparent; color: #8B949E; border: none; font-size: 11px;")
        self.btn_toggle.clicked.connect(self._toggle_expanded)
        h_lay.addWidget(self.btn_toggle)

        header_widget.mousePressEvent = lambda e: self._toggle_expanded()
        main_vbox.addWidget(header_widget)

        # Collapsible Container for hits
        self.hits_container = QWidget()
        self.hits_layout = QVBoxLayout(self.hits_container)
        self.hits_layout.setContentsMargins(6, 4, 6, 4)
        self.hits_layout.setSpacing(6)

        for h in self.hits:
            row = HitSnippetRow(h)
            row.page_selected.connect(self.preview_requested.emit)
            row.open_reader_requested.connect(self.open_requested.emit)
            self.hits_layout.addWidget(row)

        main_vbox.addWidget(self.hits_container)

    def _toggle_expanded(self) -> None:
        self._is_expanded = not self._is_expanded
        self.hits_container.setVisible(self._is_expanded)
        self.btn_toggle.setText("▼" if self._is_expanded else "▶")


class FullTextPagePreviewInspector(QFrame):
    """Right-side preview inspector showing rendered high-res PDF page snapshot."""

    open_in_reader = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path = ""
        self._current_page = 1
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QFrame {
                background-color: #0B0F19;
                border-left: 1px solid #1E293B;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # Top Bar
        top_bar = QHBoxLayout()
        self.lbl_head = QLabel("Seitenvorschau")
        self.lbl_head.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_head.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        top_bar.addWidget(self.lbl_head)
        top_bar.addStretch()

        self.btn_open = QPushButton("Im Reader öffnen ↗")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.setFixedHeight(28)
        self.btn_open.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: none;
                border-radius: 5px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background: #58A6FF; }
        """)
        self.btn_open.clicked.connect(self._on_open_clicked)
        top_bar.addWidget(self.btn_open)
        layout.addLayout(top_bar)

        # Page Snapshot Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: 1px solid #1C273C; border-radius: 8px; background-color: #070A12; }")

        self.lbl_page_render = QLabel()
        self.lbl_page_render.setAlignment(Qt.AlignCenter)
        self.lbl_page_render.setStyleSheet("background-color: #070A12; color: #8B949E; font-size: 11px;")
        self.lbl_page_render.setText("Wähle einen Treffer aus,\num eine direkte Seitenvorschau anzuzeigen.")
        self.scroll.setWidget(self.lbl_page_render)
        layout.addWidget(self.scroll, stretch=1)

    def load_page_preview(self, file_path: str, page_num: int) -> None:
        self._current_path = file_path
        self._current_page = page_num
        self.lbl_head.setText(f"Vorschau: Seite {page_num}")

        if not file_path or not os.path.exists(file_path):
            self.lbl_page_render.setText("Dokument nicht gefunden")
            return

        try:
            doc = pymupdf.open(file_path)
            idx = max(0, min(page_num - 1, doc.page_count - 1))
            page = doc.load_page(idx)
            # Render page at 1.4x scale for crisp inspection
            mat = pymupdf.Matrix(1.4, 1.4)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            pm = QPixmap.fromImage(img)
            self.lbl_page_render.setPixmap(pm)
            doc.close()
        except Exception as e:
            self.lbl_page_render.setText(f"Vorschau konnte nicht gerendert werden:\n{e}")

    def _on_open_clicked(self) -> None:
        if self._current_path:
            self.open_in_reader.emit(self._current_path, self._current_page)


class FullTextSearchOverlay(QWidget):
    """Full-page overlay container displaying book-grouped full-text search results and side preview."""

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

        # Splitter: Left Result Cards, Right Page Preview Inspector
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1A2436;
                width: 2px;
            }
        """)

        # Left Scroll area for grouped hit results
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.results_container = QWidget()
        self.results_container.setStyleSheet("background-color: transparent;")
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 4, 8, 12)
        self.results_layout.setSpacing(10)

        self.scroll.setWidget(self.results_container)
        self.splitter.addWidget(self.scroll)

        # Right Preview Inspector
        self.preview_inspector = FullTextPagePreviewInspector()
        self.preview_inspector.open_in_reader.connect(self._on_jump_requested)
        self.splitter.addWidget(self.preview_inspector)

        self.splitter.setSizes([650, 450])
        main_layout.addWidget(self.splitter, stretch=1)

    def perform_search(self, query: str) -> None:
        """Executes full-text query, groups hits by book and renders interactive accordion cards."""
        while self.results_layout.count() > 0:
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        clean_q = query.strip()
        if not clean_q or len(clean_q) < 2:
            self.lbl_hits.setText("Suchbegriff eingeben...")
            return

        matches = search_fulltext(clean_q, limit=120)
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

        # Group matches by book_id / title
        grouped: Dict[str, Dict[str, Any]] = {}
        for m in matches:
            b_key = str(m.get("book_id") or m.get("title"))
            if b_key not in grouped:
                grouped[b_key] = {
                    "title": m.get("title", "Unbekannt"),
                    "book_data": m,
                    "hits": [],
                }
            grouped[b_key]["hits"].append(m)

        first_hit = matches[0]
        for b_info in grouped.values():
            accordion = BookGroupAccordionItem(
                b_info["title"],
                b_info["book_data"],
                b_info["hits"]
            )
            accordion.preview_requested.connect(self.preview_inspector.load_page_preview)
            accordion.open_requested.connect(self._on_jump_requested)
            self.results_layout.addWidget(accordion)

        self.results_layout.addStretch()
        self.results_container.adjustSize()
        self.scroll.verticalScrollBar().setValue(0)

        # Automatically preview first hit
        if first_hit.get("file_path"):
            self.preview_inspector.load_page_preview(first_hit["file_path"], first_hit.get("page_number", 1))

    def _on_jump_requested(self, file_path: str, page_num: int) -> None:
        self.open_reader_requested.emit(file_path, page_num)
