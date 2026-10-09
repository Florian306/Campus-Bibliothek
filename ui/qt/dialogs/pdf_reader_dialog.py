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
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    HAS_QT_PDF = True
except (ImportError, ModuleNotFoundError):
    QPdfDocument = None
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
)

from core.library_db import (
    update_reading_progress,
    get_book_notes,
    add_book_note,
    delete_book_note,
    open_pdf_in_edge,
)
from ai.pdf_extractor import extract_pdf_toc
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
        self._explainer_thread: Optional[AiExplainerWorker] = None
        self._is_jumping = False

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

        top_layout.addStretch()

        # Book Title in Header
        lbl_center_title = QLabel(self.book_title)
        lbl_center_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_center_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        lbl_center_title.setMaximumWidth(450)
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
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(8)

        lbl_hdr = QLabel("INHALTSVERZEICHNIS")
        lbl_hdr.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_hdr.setStyleSheet("color: #58A6FF; letter-spacing: 0.5px; border: none; background: transparent;")
        layout.addWidget(lbl_hdr)

        self.tree_toc = QTreeWidget()
        self.tree_toc.setItemDelegate(NoFocusItemDelegate(self.tree_toc))
        self.tree_toc.setHeaderHidden(True)
        self.tree_toc.setAnimated(True)
        self.tree_toc.setIndentation(16)
        self.tree_toc.setStyleSheet("""
            QTreeWidget {
                background-color: transparent;
                color: #C9D1D9;
                border: none;
                outline: none;
                font-size: 12px;
            }
            QTreeWidget::item {
                padding: 6px 8px;
                border-radius: 6px;
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
        layout.addWidget(self.tree_toc, stretch=1)

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

    def _populate_toc(self) -> None:
        if self._preloaded_toc is not None:
            self._apply_toc_items(self._preloaded_toc)
            return

        # Load TOC in background to keep PDF reader immediately responsive
        def bg_load():
            try:
                items = extract_pdf_toc(self.file_path)
            except Exception:
                items = []
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._apply_toc_items(items))

        import threading
        threading.Thread(target=bg_load, daemon=True).start()

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

    def _on_pdf_page_changed(self, page_index: int) -> None:
        current_p = page_index + 1
        if not self._is_jumping:
            self.spin_page.blockSignals(True)
            self.spin_page.setValue(current_p)
            self.spin_page.blockSignals(False)
            self._record_progress(current_p)

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
