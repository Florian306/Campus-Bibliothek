"""Modern Integrated In-App PDF Reader Dialog for PySide6.
Features native QPdfView with high-DPI anti-aliased rendering, TOC sidebar,
real-time reading progress tracking in SQLite, note-taking panel, and AI explanation assistant.
"""

import os
import subprocess
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QFont, QColor, QKeySequence, QShortcut
try:
    from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
    from PySide6.QtPdfWidgets import QPdfView
    HAS_QT_PDF = True
except (ImportError, ModuleNotFoundError):
    QPdfDocument = None
    QPdfSearchModel = None
    QPdfView = None
    HAS_QT_PDF = False
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QLineEdit,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QWidget,
    QFrame,
    QScrollArea,
    QApplication,
    QMessageBox,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QGraphicsColorizeEffect,
)

from core.library_db import (
    update_reading_progress,
    get_book_notes,
    add_book_note,
    delete_book_note,
    open_pdf_in_edge,
    get_book_bookmarks,
    toggle_book_bookmark,
    is_page_bookmarked,
)
from ai.pdf_extractor import extract_pdf_toc, _TOC_CACHE
from ai.tutor_engine import _resolve_model
from ui.qt.theme import NoFocusItemDelegate
from ui.qt.icons import create_vector_icon, create_vector_pixmap


class AiExplainerWorker(QThread):
    finished_explanation = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, book_title: str, text_to_explain: str, prompt_mode: str = "explain", parent=None):
        super().__init__(parent)
        self.book_title = book_title
        self.text_to_explain = text_to_explain
        self.prompt_mode = prompt_mode

    def run(self):
        try:
            from core.config import load_config
            cfg = load_config()
            provider, model_name = _resolve_model()
            api_key = cfg.get("api_key", "")

            if self.prompt_mode == "summarize":
                system_prompt = (
                    "Du bist ein exzellenter Universitätsprofessor und Didaktiker. "
                    "Fasse den folgenden Lehrbuchauszug prägnant in 3-5 klaren Stichpunkten und einer Kernbotschaft zusammen. "
                    "Verwende sauberes Deutsch und Markdown."
                )
            else:
                system_prompt = (
                    "Du bist ein hilfsbereiter KI-Tutor für Studierende. "
                    "Erkläre den folgenden Fachbegriff oder Buchabschnitt verständlich, anschaulich und präzise. "
                    "Bringe falls hilfreich ein kurzes, einprägsames Praxisbeispiel. Verwende sauberes Deutsch und Markdown."
                )

            user_prompt = f"Fachbuch: {self.book_title}\n\nTextauszug:\n{self.text_to_explain}"

            if provider == "gemini" and api_key.strip():
                from google import genai
                client = genai.Client(api_key=api_key.strip())
                resp = client.models.generate_content(
                    model=model_name or "gemini-2.5-flash",
                    contents=f"{system_prompt}\n\n{user_prompt}"
                )
                self.finished_explanation.emit(resp.text.strip())
                return

            # Ollama
            import json
            import urllib.request
            url = "http://localhost:11434/api/generate"
            payload = {
                "model": model_name or "qwen2.5vl:latest",
                "prompt": f"<system>\n{system_prompt}\n</system>\n\n<user>\n{user_prompt}\n</user>",
                "stream": False,
                "options": {"temperature": 0.3, "num_ctx": 4096}
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.finished_explanation.emit(data.get("response", "").strip())

        except Exception as e:
            self.error_occurred.emit(str(e))


class PageThumbnailWorker(QThread):
    thumbnail_ready = Signal(int, bytes, int, int)  # page_idx, raw_samples, width, height

    def __init__(self, file_path: str, max_pages: int = 150, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.max_pages = max_pages
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if not self.file_path or not os.path.exists(self.file_path):
            return
        try:
            import fitz
            doc = fitz.open(self.file_path)
            total = min(len(doc), self.max_pages)
            for p_idx in range(total):
                if self._is_cancelled:
                    break
                try:
                    page = doc[p_idx]
                    pix = page.get_pixmap(dpi=36)
                    samples = bytes(pix.samples)
                    self.thumbnail_ready.emit(p_idx, samples, pix.width, pix.height)
                except Exception:
                    continue
            doc.close()
        except Exception:
            pass


class TocLoaderWorker(QThread):
    finished_toc = Signal(list)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        try:
            items = extract_pdf_toc(self.file_path) if self.file_path and os.path.exists(self.file_path) else []
        except Exception:
            items = []
        self.finished_toc.emit(items)


class PdfReaderDialog(QDialog):
    """Integrated In-App PDF Reader with TOC Navigation, Auto-Saved Progress, Notes & AI Assistant."""

    progress_updated = Signal(str, int)  # book_id, current_page

    def __init__(self, book: Dict[str, Any], initial_page: int = 1, toc_items: Optional[List] = None, parent=None):
        super().__init__(parent)
        self.book = book
        self.book_id = str(book.get("id", ""))
        self.file_path = book.get("file_path", "")
        self.book_title = book.get("title", "Dokument")
        self.initial_page = max(1, int(initial_page))
        self._preloaded_toc = toc_items

        self.setWindowTitle(f"Campus-Reader • {self.book_title}")
        self.resize(1300, 880)
        self.setMinimumSize(960, 640)
        self.setWindowFlags(
            Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        )
        self.setStyleSheet("""
            QDialog {
                background-color: #0B0F19;
                color: #F0F6FC;
            }
        """)

        self.doc = QPdfDocument(self) if HAS_QT_PDF else None
        self.view = QPdfView(self) if HAS_QT_PDF else None
        self.search_model = QPdfSearchModel(self) if HAS_QT_PDF and QPdfSearchModel else None
        if self.view and self.search_model and self.doc:
            self.search_model.setDocument(self.doc)
            self.view.setSearchModel(self.search_model)

        self._explainer_thread: Optional[AiExplainerWorker] = None
        self._toc_thread: Optional[TocLoaderWorker] = None
        self._thumb_thread: Optional[PageThumbnailWorker] = None
        self._is_jumping = False

        # Visual Theme / Filter Mode: "normal", "sepia", "dark"
        self._color_mode = "normal"
        self._color_effect: Optional[QGraphicsColorizeEffect] = None

        # Search index navigation state
        self._current_search_match_idx = -1
        self._total_search_matches = 0

        if not HAS_QT_PDF:
            # Fallback when QtPdf is not present in binary
            QMessageBox.information(
                self,
                "Integrierter Reader nicht verfügbar",
                "Das native QtPdf-Modul ist nicht verfügbar.\nDas Buch wird im Standard-PDF-Viewer (z.B. Edge) geöffnet.",
            )
            open_pdf_in_edge(self.file_path, page=self.initial_page)
            self.reject()
            return

        self._build_ui()
        self._setup_shortcuts()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._load_document)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # -------------------------------------------------------------
        # 1. Top Control Bar (Dark Glassmorphic Bar)
        # -------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setFixedHeight(50)
        top_bar.setStyleSheet("""
            QFrame {
                background-color: #0F1524;
                border-bottom: 1px solid #232F48;
            }
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 6, 16, 6)
        top_layout.setSpacing(10)

        # Toggle TOC Button
        self.btn_toggle_toc = QPushButton("  Inhalt")
        self.btn_toggle_toc.setIcon(create_vector_icon("notes", "#58A6FF", 14))
        self.btn_toggle_toc.setCheckable(True)
        self.btn_toggle_toc.setChecked(True)
        self.btn_toggle_toc.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_toc.setStyleSheet(self._button_style())
        self.btn_toggle_toc.clicked.connect(self._toggle_toc_panel)
        top_layout.addWidget(self.btn_toggle_toc)

        # Toggle Notes / AI Button
        self.btn_toggle_notes = QPushButton("  Notizen & KI")
        self.btn_toggle_notes.setIcon(create_vector_icon("book", "#A371F7", 14))
        self.btn_toggle_notes.setCheckable(True)
        self.btn_toggle_notes.setChecked(False)
        self.btn_toggle_notes.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_notes.setStyleSheet(self._button_style())
        self.btn_toggle_notes.clicked.connect(self._toggle_notes_panel)
        top_layout.addWidget(self.btn_toggle_notes)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("border: none; background-color: #232F48; width: 1px;")
        top_layout.addWidget(sep1)

        # Page Navigation: Prev, SpinBox, Total, Next
        btn_prev = QPushButton()
        btn_prev.setIcon(create_vector_icon("clock", "#C9D1D9", 14)) # left chevron fallback
        btn_prev.setText("◀")
        btn_prev.setFixedSize(30, 30)
        btn_prev.setCursor(Qt.PointingHandCursor)
        btn_prev.setStyleSheet(self._button_style())
        btn_prev.clicked.connect(self._prev_page)
        top_layout.addWidget(btn_prev)

        self.spin_page = QSpinBox()
        self.spin_page.setMinimum(1)
        self.spin_page.setMaximum(9999)
        self.spin_page.setValue(self.initial_page)
        self.spin_page.setFixedWidth(65)
        self.spin_page.setFixedHeight(30)
        self.spin_page.setAlignment(Qt.AlignCenter)
        self.spin_page.setStyleSheet("""
            QSpinBox {
                background-color: #141C2E;
                color: #FFFFFF;
                border: 1px solid #232F48;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        self.spin_page.valueChanged.connect(self._on_spin_page_changed)
        top_layout.addWidget(self.spin_page)

        self.lbl_total_pages = QLabel("/ 1")
        self.lbl_total_pages.setStyleSheet("color: #8B949E; font-size: 12px; border: none; background: transparent;")
        top_layout.addWidget(self.lbl_total_pages)

        btn_next = QPushButton()
        btn_next.setText("▶")
        btn_next.setFixedSize(30, 30)
        btn_next.setCursor(Qt.PointingHandCursor)
        btn_next.setStyleSheet(self._button_style())
        btn_next.clicked.connect(self._next_page)
        top_layout.addWidget(btn_next)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("border: none; background-color: #232F48; width: 1px;")
        top_layout.addWidget(sep2)

        # Zoom Controls
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedSize(30, 30)
        btn_zoom_out.setCursor(Qt.PointingHandCursor)
        btn_zoom_out.setStyleSheet(self._button_style())
        btn_zoom_out.clicked.connect(self._zoom_out)
        top_layout.addWidget(btn_zoom_out)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedSize(30, 30)
        btn_zoom_in.setCursor(Qt.PointingHandCursor)
        btn_zoom_in.setStyleSheet(self._button_style())
        btn_zoom_in.clicked.connect(self._zoom_in)
        top_layout.addWidget(btn_zoom_in)

        self.btn_fit_width = QPushButton("Breite anpassen")
        self.btn_fit_width.setCursor(Qt.PointingHandCursor)
        self.btn_fit_width.setFixedHeight(30)
        self.btn_fit_width.setStyleSheet(self._button_style())
        self.btn_fit_width.clicked.connect(self._fit_width)
        top_layout.addWidget(self.btn_fit_width)

        # Page Mode Toggle: MultiPage vs SinglePage
        self.btn_page_mode = QPushButton("  📜 Fortlaufend")
        self.btn_page_mode.setToolTip("Zwischen fortlaufendem Scrollen und Einzelseite wechseln")
        self.btn_page_mode.setCursor(Qt.PointingHandCursor)
        self.btn_page_mode.setFixedHeight(30)
        self.btn_page_mode.setStyleSheet(self._button_style())
        self.btn_page_mode.clicked.connect(self._toggle_page_mode)
        top_layout.addWidget(self.btn_page_mode)

        # Color Theme / Filter Mode Toggle
        self.btn_reading_theme = QPushButton("  ☀️ Normal")
        self.btn_reading_theme.setToolTip("Farbmodus wechseln (Normal / Sepia / Dunkel)")
        self.btn_reading_theme.setCursor(Qt.PointingHandCursor)
        self.btn_reading_theme.setFixedHeight(30)
        self.btn_reading_theme.setStyleSheet(self._button_style())
        self.btn_reading_theme.clicked.connect(self._cycle_reading_theme)
        top_layout.addWidget(self.btn_reading_theme)

        # Bookmark Toggle Button
        self.btn_bookmark = QPushButton("  ☆ Lesezeichen")
        self.btn_bookmark.setToolTip("Lesezeichen auf aktueller Seite setzen / entfernen (Strg+D)")
        self.btn_bookmark.setCursor(Qt.PointingHandCursor)
        self.btn_bookmark.setFixedHeight(30)
        self.btn_bookmark.setStyleSheet(self._button_style())
        self.btn_bookmark.clicked.connect(self._toggle_bookmark)
        top_layout.addWidget(self.btn_bookmark)

        # Search Toggle Button
        self.btn_search = QPushButton("  🔍 Suchen")
        self.btn_search.setToolTip("Volltextsuche einblenden (Strg+F)")
        self.btn_search.setCheckable(True)
        self.btn_search.setChecked(False)
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.setStyleSheet(self._button_style())
        self.btn_search.clicked.connect(self._toggle_search_bar)
        top_layout.addWidget(self.btn_search)

        top_layout.addStretch()

        # Book Title in Header
        lbl_center_title = QLabel(self.book_title)
        lbl_center_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_center_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        lbl_center_title.setMaximumWidth(320)
        top_layout.addWidget(lbl_center_title)

        # Fullscreen Toggle Button
        self.btn_fullscreen = QPushButton("  ⛶ Vollbild")
        self.btn_fullscreen.setToolTip("Vollbildmodus ein/ausschalten (F11)")
        self.btn_fullscreen.setCursor(Qt.PointingHandCursor)
        self.btn_fullscreen.setFixedHeight(30)
        self.btn_fullscreen.setStyleSheet(self._button_style())
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)
        top_layout.addWidget(self.btn_fullscreen)

        # Open externally in Edge button
        btn_edge = QPushButton("  In Edge")
        btn_edge.setIcon(create_vector_icon("research", "#58A6FF", 14))
        btn_edge.setToolTip("Dokument alternativ in Microsoft Edge öffnen")
        btn_edge.setCursor(Qt.PointingHandCursor)
        btn_edge.setFixedHeight(30)
        btn_edge.setStyleSheet(self._button_style())
        btn_edge.clicked.connect(self._open_in_edge)
        top_layout.addWidget(btn_edge)

        # Close Reader
        btn_close = QPushButton("Schließen")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setFixedHeight(30)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #211215;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 5px;
                padding: 0 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #381920;
                border-color: #F85149;
                color: #FFA198;
            }
        """)
        btn_close.clicked.connect(self.accept)
        top_layout.addWidget(btn_close)

        root_layout.addWidget(top_bar)

        # -------------------------------------------------------------
        # 1.5 Collapsible In-App Search Bar
        # -------------------------------------------------------------
        self.search_bar_frame = QFrame()
        self.search_bar_frame.setFixedHeight(44)
        self.search_bar_frame.setVisible(False)
        self.search_bar_frame.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border-bottom: 1px solid #232F48;
            }
        """)
        search_lay = QHBoxLayout(self.search_bar_frame)
        search_lay.setContentsMargins(20, 6, 20, 6)
        search_lay.setSpacing(8)

        lbl_s_icon = QLabel("🔍")
        lbl_s_icon.setStyleSheet("color: #58A6FF; font-size: 13px; background: transparent; border: none;")
        search_lay.addWidget(lbl_s_icon)

        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Text im Dokument suchen...")
        self.input_search.setFixedWidth(280)
        self.input_search.setFixedHeight(28)
        self.input_search.setStyleSheet("""
            QLineEdit {
                background-color: #1A2234;
                color: #FFFFFF;
                border: 1px solid #2D3D5D;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
            }
        """)
        self.input_search.textChanged.connect(self._on_search_query_changed)
        self.input_search.returnPressed.connect(self._search_next)
        search_lay.addWidget(self.input_search)

        self.btn_search_prev = QPushButton("◀ Vorheriger")
        self.btn_search_prev.setFixedHeight(28)
        self.btn_search_prev.setCursor(Qt.PointingHandCursor)
        self.btn_search_prev.setStyleSheet(self._button_style())
        self.btn_search_prev.clicked.connect(self._search_prev)
        search_lay.addWidget(self.btn_search_prev)

        self.btn_search_next = QPushButton("Nächster ▶")
        self.btn_search_next.setFixedHeight(28)
        self.btn_search_next.setCursor(Qt.PointingHandCursor)
        self.btn_search_next.setStyleSheet(self._button_style())
        self.btn_search_next.clicked.connect(self._search_next)
        search_lay.addWidget(self.btn_search_next)

        self.lbl_search_count = QLabel("")
        self.lbl_search_count.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold; background: transparent; border: none; padding-left: 8px;")
        search_lay.addWidget(self.lbl_search_count)

        search_lay.addStretch()

        btn_close_search = QPushButton("✕")
        btn_close_search.setFixedSize(24, 24)
        btn_close_search.setCursor(Qt.PointingHandCursor)
        btn_close_search.setStyleSheet("color: #8B949E; background: transparent; border: none; font-size: 14px; font-weight: bold;")
        btn_close_search.clicked.connect(lambda: self._toggle_search_bar(False))
        search_lay.addWidget(btn_close_search)

        root_layout.addWidget(self.search_bar_frame)

        # -------------------------------------------------------------
        # 2. Central Splitter Area: [TOC] | [QPdfView] | [Notes & AI]
        # -------------------------------------------------------------
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #162035;
                width: 2px;
            }
        """)

        # Left: TOC Panel
        self.toc_panel = self._build_toc_panel()
        self.splitter.addWidget(self.toc_panel)

        # Center: QPdfView
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setStyleSheet("""
            QPdfView {
                background-color: #0E131F;
                border: none;
            }
        """)
        self.splitter.addWidget(self.view)

        # Right: Notes & AI Explainer Panel
        self.notes_panel = self._build_notes_panel()
        self.notes_panel.setVisible(False)
        self.splitter.addWidget(self.notes_panel)

        # Initial Splitter ratios: 260px TOC, Main viewer, 320px Notes
        self.splitter.setSizes([260, 800, 320])
        root_layout.addWidget(self.splitter, stretch=1)

        # Connect QPdfView navigator signal
        nav = self.view.pageNavigator()
        nav.currentPageChanged.connect(self._on_pdf_page_changed)

    def _build_toc_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #0D111A;
                border-right: 1px solid #1E283D;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(6)

        # Tab widget for TOC, Bookmarks, and Thumbnails
        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                background: #141C2E;
                color: #8B949E;
                border: 1px solid #1E283D;
                border-bottom: none;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #1F2D4A;
                color: #58A6FF;
                border-color: #388BFD;
            }
            QTabBar::tab:hover:!selected {
                background: #182236;
                color: #C9D1D9;
            }
        """)

        # ---------------- Tab 1: Inhaltsverzeichnis (TOC) ----------------
        tab_toc = QWidget()
        lay_toc = QVBoxLayout(tab_toc)
        lay_toc.setContentsMargins(4, 6, 4, 4)
        lay_toc.setSpacing(6)

        self.tree_toc = QTreeWidget()
        self.tree_toc.setItemDelegate(NoFocusItemDelegate(self.tree_toc))
        self.tree_toc.setHeaderHidden(True)
        self.tree_toc.setAnimated(True)
        self.tree_toc.setIndentation(14)
        self.tree_toc.setStyleSheet("""
            QTreeWidget {
                background-color: transparent;
                color: #C9D1D9;
                border: none;
                outline: none;
                font-size: 12px;
            }
            QTreeWidget::item {
                padding: 5px 6px;
                border-radius: 5px;
                margin-bottom: 2px;
            }
            QTreeWidget::item:hover {
                background-color: #162035;
                color: #FFFFFF;
            }
            QTreeWidget::item:selected {
                background-color: #1F365D;
                color: #58A6FF;
                font-weight: 600;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #232F48;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #388BFD;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.tree_toc.itemClicked.connect(self._on_toc_item_clicked)
        lay_toc.addWidget(self.tree_toc)
        self.sidebar_tabs.addTab(tab_toc, "📑 Inhalt")

        # ---------------- Tab 2: Lesezeichen (Bookmarks) ----------------
        tab_bm = QWidget()
        lay_bm = QVBoxLayout(tab_bm)
        lay_bm.setContentsMargins(4, 6, 4, 4)
        lay_bm.setSpacing(6)

        self.list_bookmarks = QListWidget()
        self.list_bookmarks.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                color: #C9D1D9;
                border: none;
                outline: none;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-radius: 6px;
                margin-bottom: 4px;
                background-color: #141C2E;
                border: 1px solid #1E283D;
            }
            QListWidget::item:hover {
                background-color: #1F2D4A;
                border-color: #388BFD;
                color: #FFFFFF;
            }
            QListWidget::item:selected {
                background-color: #233658;
                border-color: #58A6FF;
                color: #58A6FF;
            }
        """)
        self.list_bookmarks.itemClicked.connect(self._on_bookmark_item_clicked)
        lay_bm.addWidget(self.list_bookmarks)
        self.sidebar_tabs.addTab(tab_bm, "⭐ Lesezeichen")

        # ---------------- Tab 3: Seiten-Vorschau (Thumbnails) ----------------
        tab_thumbs = QWidget()
        lay_thumbs = QVBoxLayout(tab_thumbs)
        lay_thumbs.setContentsMargins(4, 6, 4, 4)
        lay_thumbs.setSpacing(6)

        self.list_thumbnails = QListWidget()
        self.list_thumbnails.setViewMode(QListWidget.IconMode)
        self.list_thumbnails.setIconSize(QSize(90, 120))
        self.list_thumbnails.setGridSize(QSize(110, 150))
        self.list_thumbnails.setMovement(QListWidget.Static)
        self.list_thumbnails.setResizeMode(QListWidget.Adjust)
        self.list_thumbnails.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                color: #8B949E;
                border: none;
                outline: none;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 4px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
            QListWidget::item:hover {
                background-color: #162035;
                border-color: #388BFD;
                color: #FFFFFF;
            }
            QListWidget::item:selected {
                background-color: #1F365D;
                border-color: #58A6FF;
                color: #58A6FF;
                font-weight: bold;
            }
        """)
        self.list_thumbnails.itemClicked.connect(self._on_thumbnail_item_clicked)
        lay_thumbs.addWidget(self.list_thumbnails)
        self.sidebar_tabs.addTab(tab_thumbs, "🖼️ Vorschau")

        layout.addWidget(self.sidebar_tabs, stretch=1)
        return panel

    def _build_notes_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #0D111A;
                border-left: 1px solid #1E283D;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header with AI tools
        lbl_hdr = QLabel("KI-ASSISTENT & NOTIZEN")
        lbl_hdr.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_hdr.setStyleSheet("color: #A371F7; letter-spacing: 0.5px; border: none; background: transparent;")
        layout.addWidget(lbl_hdr)

        # Quick AI Action Buttons
        ai_btn_row = QHBoxLayout()
        btn_explain = QPushButton("💡 Begriff erklären")
        btn_explain.setCursor(Qt.PointingHandCursor)
        btn_explain.setStyleSheet("""
            QPushButton {
                background-color: #1E1A34;
                color: #D2A8FF;
                border: 1px solid #3C2B64;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2D2350;
                border-color: #A371F7;
            }
        """)
        btn_explain.clicked.connect(lambda: self._ask_ai("explain"))
        ai_btn_row.addWidget(btn_explain)

        btn_sum = QPushButton("📑 Seite fassen")
        btn_sum.setCursor(Qt.PointingHandCursor)
        btn_sum.setStyleSheet("""
            QPushButton {
                background-color: #162035;
                color: #79C0FF;
                border: 1px solid #283C64;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1F2D4A;
                border-color: #58A6FF;
            }
        """)
        btn_sum.clicked.connect(lambda: self._ask_ai("summarize"))
        ai_btn_row.addWidget(btn_sum)
        layout.addLayout(ai_btn_row)

        # AI Response Area
        self.txt_ai_response = QPlainTextEdit()
        self.txt_ai_response.setPlaceholderText("Markiere einen Text oder klicke auf 'Begriff erklären' / 'Seite fassen' für eine KI-Zusammenfassung.")
        self.txt_ai_response.setStyleSheet("""
            QPlainTextEdit {
                background-color: #121826;
                color: #F0F6FC;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
                line-height: 1.4;
            }
        """)
        layout.addWidget(self.txt_ai_response, stretch=1)

        # Book Notes List
        lbl_notes_title = QLabel("EIGENE NOTIZEN ZU DIESEM BUCH")
        lbl_notes_title.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_notes_title.setStyleSheet("color: #8B949E; letter-spacing: 0.5px; margin-top: 6px; border: none; background: transparent;")
        layout.addWidget(lbl_notes_title)

        self.scroll_notes = QScrollArea()
        self.scroll_notes.setWidgetResizable(True)
        self.scroll_notes.setStyleSheet("background: transparent; border: none;")
        self.notes_container = QWidget()
        self.notes_layout = QVBoxLayout(self.notes_container)
        self.notes_layout.setContentsMargins(0, 0, 0, 0)
        self.notes_layout.setSpacing(6)
        self.scroll_notes.setWidget(self.notes_container)
        layout.addWidget(self.scroll_notes, stretch=1)

        # Add new note input box
        add_box = QHBoxLayout()
        self.input_new_note = QLineEdit()
        self.input_new_note.setPlaceholderText("Notiz zur aktuellen Seite erfassen...")
        self.input_new_note.setStyleSheet("""
            QLineEdit {
                background-color: #141C2E;
                color: #FFFFFF;
                border: 1px solid #232F48;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 11px;
            }
        """)
        self.input_new_note.returnPressed.connect(self._add_current_page_note)
        add_box.addWidget(self.input_new_note, stretch=1)

        btn_save_note = QPushButton("Speichern")
        btn_save_note.setCursor(Qt.PointingHandCursor)
        btn_save_note.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 600;
            }
        """)
        btn_save_note.clicked.connect(self._add_current_page_note)
        add_box.addWidget(btn_save_note)
        layout.addLayout(add_box)

        self._refresh_notes_list()
        return panel

    def _button_style(self) -> str:
        return """
            QPushButton {
                background-color: #141C2E;
                color: #C9D1D9;
                border: 1px solid #232F48;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1A253D;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
            QPushButton:checked {
                background-color: #1F365A;
                border-color: #388BFD;
                color: #58A6FF;
            }
        """

    def _load_document(self) -> None:
        if not self.file_path or not os.path.exists(self.file_path):
            QMessageBox.critical(self, "Fehler", f"PDF-Datei nicht gefunden:\n{self.file_path}")
            return

        self.doc.load(self.file_path)
        p_count = self.doc.pageCount()
        self.lbl_total_pages.setText(f"/ {p_count}")
        self.spin_page.setMaximum(max(1, p_count))

        # Jump to initial page
        target_idx = max(0, min(self.initial_page - 1, p_count - 1))
        self.view.pageNavigator().jump(target_idx, self.view.pageNavigator().currentLocation(), self.view.pageNavigator().currentZoom())

        # Load TOC tree
        self._populate_toc()

        # Load Bookmarks list
        self._refresh_bookmarks_list()
        self._update_bookmark_button_state(self.initial_page)

        # Start background thumbnail generator
        self._start_thumbnail_generation()

    def _start_thumbnail_generation(self) -> None:
        if not self.file_path or not os.path.exists(self.file_path):
            return
        if self._thumb_thread and self._thumb_thread.isRunning():
            self._thumb_thread.cancel()
            self._thumb_thread.wait(200)

        self.list_thumbnails.clear()
        self._thumb_thread = PageThumbnailWorker(self.file_path, max_pages=150, parent=self)
        self._thumb_thread.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_thread.start()

    def _on_thumbnail_ready(self, page_idx: int, raw_samples: bytes, width: int, height: int) -> None:
        from PySide6.QtGui import QImage, QPixmap, QIcon
        try:
            qimg = QImage(raw_samples, width, height, width * 3, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            item = QListWidgetItem(QIcon(pixmap), f"S. {page_idx + 1}")
            item.setData(Qt.UserRole, page_idx + 1)
            item.setTextAlignment(Qt.AlignCenter)
            self.list_thumbnails.addItem(item)
        except Exception:
            pass

    def _on_thumbnail_item_clicked(self, item: QListWidgetItem) -> None:
        p_num = item.data(Qt.UserRole)
        if p_num:
            self._jump_to_page(int(p_num))

    def _refresh_bookmarks_list(self) -> None:
        self.list_bookmarks.clear()
        if not self.book_id:
            return
        bms = get_book_bookmarks(self.book_id)
        if not bms:
            empty_item = QListWidgetItem("Noch keine Lesezeichen gesetzt.\n(Klicke oben auf '☆ Lesezeichen' oder drücke Strg+D)")
            empty_item.setFlags(Qt.NoItemFlags)
            self.list_bookmarks.addItem(empty_item)
            return

        for bm in bms:
            p = bm.get("page_number", 1)
            title = bm.get("title") or f"Lesezeichen auf Seite {p}"
            tag = bm.get("tag", "Wichtig")
            item = QListWidgetItem(f"⭐ Seite {p} • {title} [{tag}]")
            item.setData(Qt.UserRole, p)
            self.list_bookmarks.addItem(item)

    def _on_bookmark_item_clicked(self, item: QListWidgetItem) -> None:
        p_num = item.data(Qt.UserRole)
        if p_num:
            self._jump_to_page(int(p_num))

    def _toggle_bookmark(self) -> None:
        curr_p = self.view.pageNavigator().currentPage() + 1
        now_bookmarked = toggle_book_bookmark(self.book_id, curr_p, title=f"S. {curr_p} im Buch", tag="Wichtig")
        self._update_bookmark_button_state(curr_p)
        self._refresh_bookmarks_list()

    def _update_bookmark_button_state(self, page_num: int) -> None:
        is_bm = is_page_bookmarked(self.book_id, page_num)
        if is_bm:
            self.btn_bookmark.setText("  ★ Gespeichert")
            self.btn_bookmark.setStyleSheet("""
                QPushButton {
                    background-color: #382A10;
                    color: #F2CC60;
                    border: 1px solid #D29922;
                    border-radius: 5px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #4A3716;
                    border-color: #E3B341;
                }
            """)
        else:
            self.btn_bookmark.setText("  ☆ Lesezeichen")
            self.btn_bookmark.setStyleSheet(self._button_style())

    def _cycle_reading_theme(self) -> None:
        modes = ["normal", "sepia", "dark"]
        curr_idx = modes.index(self._color_mode) if self._color_mode in modes else 0
        next_mode = modes[(curr_idx + 1) % len(modes)]
        self._set_reading_theme(next_mode)

    def _set_reading_theme(self, mode: str) -> None:
        self._color_mode = mode
        vp = self.view.viewport() if self.view else None
        if not vp:
            return

        if mode == "normal":
            vp.setGraphicsEffect(None)
            self.btn_reading_theme.setText("  ☀️ Normal")
            self.btn_reading_theme.setStyleSheet(self._button_style())
        elif mode == "sepia":
            effect = QGraphicsColorizeEffect(self)
            effect.setColor(QColor("#E8D8B8"))
            effect.setStrength(0.48)
            vp.setGraphicsEffect(effect)
            self.btn_reading_theme.setText("  📜 Sepia")
            self.btn_reading_theme.setStyleSheet("""
                QPushButton {
                    background-color: #2F2618;
                    color: #F8E3B6;
                    border: 1px solid #D4A359;
                    border-radius: 5px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """)
        elif mode == "dark":
            effect = QGraphicsColorizeEffect(self)
            effect.setColor(QColor("#2B3342"))
            effect.setStrength(0.78)
            vp.setGraphicsEffect(effect)
            self.btn_reading_theme.setText("  🌙 Dunkel")
            self.btn_reading_theme.setStyleSheet("""
                QPushButton {
                    background-color: #1A1F2C;
                    color: #8B949E;
                    border: 1px solid #388BFD;
                    border-radius: 5px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """)

    def _toggle_page_mode(self) -> None:
        if not self.view:
            return
        if self.view.pageMode() == QPdfView.PageMode.MultiPage:
            self.view.setPageMode(QPdfView.PageMode.SinglePage)
            self.btn_page_mode.setText("  📄 Einzelseite")
        else:
            self.view.setPageMode(QPdfView.PageMode.MultiPage)
            self.btn_page_mode.setText("  📜 Fortlaufend")

    def _toggle_search_bar(self, checked: Optional[bool] = None) -> None:
        if checked is None:
            is_visible = not self.search_bar_frame.isVisible()
        else:
            is_visible = checked
        self.search_bar_frame.setVisible(is_visible)
        self.btn_search.setChecked(is_visible)
        if is_visible:
            self.input_search.setFocus()
            self.input_search.selectAll()
        else:
            if self.search_model:
                self.search_model.setSearchString("")
            self.lbl_search_count.setText("")
            self._current_search_match_idx = -1
            self._total_search_matches = 0

    def _on_search_query_changed(self, text: str) -> None:
        query = text.strip()
        if not self.search_model:
            return
        self.search_model.setSearchString(query)
        total = self.search_model.count()
        self._total_search_matches = total
        if not query:
            self.lbl_search_count.setText("")
            self._current_search_match_idx = -1
            return

        if total == 0:
            self.lbl_search_count.setText("Keine Treffer")
            self._current_search_match_idx = -1
        else:
            self._current_search_match_idx = 0
            self.lbl_search_count.setText(f"1 von {total} Treffern")
            self._jump_to_search_result(0)

    def _search_next(self) -> None:
        if not self.search_model or self._total_search_matches <= 0:
            return
        self._current_search_match_idx = (self._current_search_match_idx + 1) % self._total_search_matches
        self.lbl_search_count.setText(f"{self._current_search_match_idx + 1} von {self._total_search_matches} Treffern")
        self._jump_to_search_result(self._current_search_match_idx)

    def _search_prev(self) -> None:
        if not self.search_model or self._total_search_matches <= 0:
            return
        self._current_search_match_idx = (self._current_search_match_idx - 1) % self._total_search_matches
        self.lbl_search_count.setText(f"{self._current_search_match_idx + 1} von {self._total_search_matches} Treffern")
        self._jump_to_search_result(self._current_search_match_idx)

    def _jump_to_search_result(self, match_idx: int) -> None:
        if not self.search_model or match_idx < 0 or match_idx >= self.search_model.count():
            return
        link = self.search_model.resultAtIndex(match_idx)
        if link and link.isValid():
            p = link.page()
            self._jump_to_page(p + 1)

    def _populate_toc(self) -> None:
        if self._preloaded_toc is not None:
            self._apply_toc_items(self._preloaded_toc)
            return

        # Check global in-memory cache first for zero-wait rendering
        if self.file_path:
            norm_path = os.path.abspath(self.file_path)
            if norm_path in _TOC_CACHE:
                self._apply_toc_items(_TOC_CACHE[norm_path])
                return

        # Load TOC via QThread worker with Qt Signal delivery
        self._toc_thread = TocLoaderWorker(self.file_path, parent=self)
        self._toc_thread.finished_toc.connect(self._apply_toc_items)
        self._toc_thread.start()

    def _apply_toc_items(self, toc_items: List) -> None:
        self.tree_toc.setUpdatesEnabled(False)
        self.tree_toc.clear()
        if not toc_items:
            empty_item = QTreeWidgetItem(["(Kein Inhaltsverzeichnis verfügbar)"])
            empty_item.setDisabled(True)
            self.tree_toc.addTopLevelItem(empty_item)
            self.tree_toc.setUpdatesEnabled(True)
            return

        stack = {}
        for item_data in toc_items:
            lvl = item_data[0]
            title = item_data[1]
            target_p = item_data[2]
            printed_p = item_data[3] if len(item_data) > 3 else target_p

            item = QTreeWidgetItem([f"{title} (S. {printed_p})"])
            item.setData(0, Qt.UserRole, target_p)

            if lvl == 1 or (lvl - 1) not in stack:
                self.tree_toc.addTopLevelItem(item)
            else:
                stack[lvl - 1].addChild(item)
            stack[lvl] = item

        for i in range(self.tree_toc.topLevelItemCount()):
            self.tree_toc.topLevelItem(i).setExpanded(True)
        self.tree_toc.setUpdatesEnabled(True)

    def _on_toc_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        page = item.data(0, Qt.UserRole)
        if page:
            p_int = max(1, int(page))
            self._jump_to_page(p_int)

    def _jump_to_page(self, page_num: int) -> None:
        p_count = self.doc.pageCount()
        if p_count <= 0:
            return
        idx = max(0, min(page_num - 1, p_count - 1))
        self._is_jumping = True
        self.spin_page.setValue(idx + 1)
        self.view.pageNavigator().jump(idx, self.view.pageNavigator().currentLocation(), self.view.pageNavigator().currentZoom())
        self._is_jumping = False
        self._record_progress(idx + 1)
        self._update_bookmark_button_state(idx + 1)
        self._sync_active_thumbnail(idx)

    def _on_pdf_page_changed(self, page_index: int) -> None:
        current_p = page_index + 1
        if not self._is_jumping:
            self.spin_page.blockSignals(True)
            self.spin_page.setValue(current_p)
            self.spin_page.blockSignals(False)
            self._record_progress(current_p)
            self._update_bookmark_button_state(current_p)
            self._sync_active_thumbnail(page_index)

    def _sync_active_thumbnail(self, page_index: int) -> None:
        if hasattr(self, "list_thumbnails") and self.list_thumbnails.count() > page_index:
            self.list_thumbnails.blockSignals(True)
            self.list_thumbnails.setCurrentRow(page_index)
            self.list_thumbnails.blockSignals(False)

    def _on_spin_page_changed(self, val: int) -> None:
        if not self._is_jumping:
            self._jump_to_page(val)

    def _prev_page(self) -> None:
        cur = self.view.pageNavigator().currentPage()
        if cur > 0:
            self._jump_to_page(cur)

    def _next_page(self) -> None:
        cur = self.view.pageNavigator().currentPage()
        if cur < self.doc.pageCount() - 1:
            self._jump_to_page(cur + 2)

    def _zoom_in(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(self.view.zoomFactor() * 1.15)

    def _zoom_out(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(self.view.zoomFactor() / 1.15)

    def _fit_width(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def _toggle_toc_panel(self) -> None:
        self.toc_panel.setVisible(self.btn_toggle_toc.isChecked())

    def _toggle_notes_panel(self) -> None:
        self.notes_panel.setVisible(self.btn_toggle_notes.isChecked())

    def _record_progress(self, page_num: int) -> None:
        if self.book_id:
            update_reading_progress(self.book_id, page_num)
            self.progress_updated.emit(self.book_id, page_num)

    def _open_in_edge(self) -> None:
        curr_p = self.view.pageNavigator().currentPage() + 1
        open_pdf_in_edge(self.file_path, page=curr_p)

    def _ask_ai(self, mode: str) -> None:
        self.notes_panel.setVisible(True)
        self.btn_toggle_notes.setChecked(True)

        curr_p = self.view.pageNavigator().currentPage() + 1
        # Extract text of current page using PyMuPDF
        import fitz
        page_text = ""
        try:
            doc = fitz.open(self.file_path)
            if 0 <= (curr_p - 1) < len(doc):
                page_text = doc[curr_p - 1].get_text("text").strip()
            doc.close()
        except Exception:
            pass

        if not page_text:
            self.txt_ai_response.setPlainText(f"Konnte auf Seite {curr_p} keinen auslesbaren Text ermitteln.")
            return

        self.txt_ai_response.setPlainText(f"⏳ KI analysiert Seite {curr_p}...")
        self._explainer_thread = AiExplainerWorker(self.book_title, page_text, prompt_mode=mode, parent=self)
        self._explainer_thread.finished_explanation.connect(lambda resp: self.txt_ai_response.setPlainText(resp))
        self._explainer_thread.error_occurred.connect(lambda err: self.txt_ai_response.setPlainText(f"Fehler bei KI-Analyse:\n{err}"))
        self._explainer_thread.start()

    def _add_current_page_note(self) -> None:
        text = self.input_new_note.text().strip()
        if not text:
            return
        curr_p = self.view.pageNavigator().currentPage() + 1
        add_book_note(self.book_id, text, page_number=curr_p)
        self.input_new_note.clear()
        self._refresh_notes_list()

    def _refresh_notes_list(self) -> None:
        while self.notes_layout.count() > 0:
            item = self.notes_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        notes = get_book_notes(self.book_id) if self.book_id else []
        if not notes:
            lbl_empty = QLabel("Keine Notizen erfasst.")
            lbl_empty.setStyleSheet("color: #6E7681; font-style: italic; font-size: 11px;")
            self.notes_layout.addWidget(lbl_empty)
            self.notes_layout.addStretch()
            return

        for n in notes:
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: #121826;
                    border: 1px solid #232F48;
                    border-radius: 4px;
                    padding: 4px 6px;
                }
            """)
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(6, 4, 6, 4)
            c_lay.setSpacing(2)

            top_row = QHBoxLayout()
            p_val = n.get("page_number")
            lbl_p = QLabel(f"Seite {p_val}" if p_val else "Notiz")
            lbl_p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            lbl_p.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
            top_row.addWidget(lbl_p)
            top_row.addStretch()

            btn_del = QPushButton("×")
            btn_del.setFixedSize(18, 18)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("color: #FF7B72; font-weight: bold; border: none; background: transparent;")
            btn_del.clicked.connect(lambda _, nid=n["id"]: self._delete_note(nid))
            top_row.addWidget(btn_del)
            c_lay.addLayout(top_row)

            lbl_txt = QLabel(n.get("note_text", ""))
            lbl_txt.setFont(QFont("Segoe UI", 9))
            lbl_txt.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
            lbl_txt.setWordWrap(True)
            c_lay.addWidget(lbl_txt)

            self.notes_layout.addWidget(card)

        self.notes_layout.addStretch()

    def _delete_note(self, note_id: int) -> None:
        delete_book_note(note_id)
        self._refresh_notes_list()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("  ⛶ Vollbild")
        else:
            self.showFullScreen()
            self.btn_fullscreen.setText("  ⛶ Fenster")

    def _setup_shortcuts(self) -> None:
        shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shortcut_esc.activated.connect(self.accept)

        shortcut_f11 = QShortcut(QKeySequence(Qt.Key_F11), self)
        shortcut_f11.activated.connect(self._toggle_fullscreen)

        shortcut_left = QShortcut(QKeySequence(Qt.Key_Left), self)
        shortcut_left.activated.connect(self._prev_page)

        shortcut_right = QShortcut(QKeySequence(Qt.Key_Right), self)
        shortcut_right.activated.connect(self._next_page)

        # Strg + F for Search Bar
        shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_find.activated.connect(self._toggle_search_bar)

        # Strg + D for Bookmark Toggle
        shortcut_bookmark = QShortcut(QKeySequence("Ctrl+D"), self)
        shortcut_bookmark.activated.connect(self._toggle_bookmark)

    def closeEvent(self, event) -> None:
        if self._thumb_thread and self._thumb_thread.isRunning():
            self._thumb_thread.cancel()
            self._thumb_thread.wait(200)
        super().closeEvent(event)
