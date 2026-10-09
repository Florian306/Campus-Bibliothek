"""Ultra-Modern Reading Desk View (Lesepult) for PySide6.
Features Cyber-Obsidian KPI cards, non-overlapping table cells, interactive Note Cards with pure vector icons, and zero-popup UX.
"""

import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtGui import QFont, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QPlainTextEdit,
    QLineEdit,
    QFrame,
    QScrollArea,
    QProgressBar,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate
from core.library_db import (
    get_desk_books,
    toggle_desk_item,
    update_reading_progress,
    get_book_notes,
    add_book_note,
    delete_book_note,
    open_pdf_in_edge,
    calculate_study_plan_metrics,
    log_daily_reading,
    get_book_pair,
    get_gamification_profile,
    get_all_books,
    get_desk_extracts,
    toggle_extract_desk,
    delete_book_extract,
)
from ui.qt.dialogs.study_plan_dialog import StudyPlanDialog
from ui.qt.dialogs.tutor_dialog import TutorStudioDialog
from ui.qt.dialogs.pdf_reader_dialog import PdfReaderDialog
from core.config import load_config
from ai.book_pairing import is_exercise_book, auto_pair_library


class QuickNoteInput(QPlainTextEdit):
    """Textarea that triggers immediate submit on Ctrl+Return."""
    submit_requested = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (event.modifiers() & Qt.ControlModifier):
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class NoteCard(QFrame):
    """Luxury interactive note card with pure vector icons, divider, timestamp, and actions."""

    delete_requested = Signal(int)

    def __init__(self, note_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.note_data = note_data
        self.note_id = note_data.get("id", 0)

        self.setStyleSheet("""
            NoteCard {
                background-color: #121826;
                border: 1px solid #232F48;
                border-left: 3px solid #388BFD;
                border-radius: 8px;
            }
            NoteCard:hover {
                background-color: #151E32;
                border-color: #388BFD;
                border-left: 3px solid #58A6FF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header Row: Clock Icon + Timestamp + Bookmark Icon + Page badge + Actions
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_row.setAlignment(Qt.AlignVCenter)

        lbl_clock = QLabel()
        lbl_clock.setPixmap(create_vector_pixmap("clock", "#8B949E", 14))
        lbl_clock.setStyleSheet("border: none; background: transparent;")
        header_row.addWidget(lbl_clock)

        created_ts = note_data.get("created_at") or time.time()
        time_str = time.strftime("%d.%m.%Y um %H:%M", time.localtime(created_ts))
        lbl_time = QLabel(time_str)
        lbl_time.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 500; border: none; background: transparent;")
        header_row.addWidget(lbl_time)

        p_num = note_data.get("page_number")
        if p_num is not None:
            badge_widget = QWidget()
            badge_widget.setStyleSheet("""
                background-color: #1A2438;
                border: 1px solid #304163;
                border-radius: 4px;
            """)
            badge_layout = QHBoxLayout(badge_widget)
            badge_layout.setContentsMargins(6, 2, 6, 2)
            badge_layout.setSpacing(4)
            badge_layout.setAlignment(Qt.AlignVCenter)

            lbl_bm_icon = QLabel()
            lbl_bm_icon.setPixmap(create_vector_pixmap("bookmark", "#58A6FF", 11))
            lbl_bm_icon.setStyleSheet("border: none; background: transparent;")
            badge_layout.addWidget(lbl_bm_icon)

            lbl_page = QLabel(f"Seite {p_num}")
            lbl_page.setStyleSheet("color: #58A6FF; font-size: 11px; font-weight: bold; border: none; background: transparent;")
            badge_layout.addWidget(lbl_page)

            header_row.addWidget(badge_widget)

        header_row.addStretch()

        # Copy single note button (Vector Icon)
        btn_copy = QPushButton()
        btn_copy.setIcon(create_vector_icon("copy", "#8B949E", 14))
        btn_copy.setIconSize(QSize(14, 14))
        btn_copy.setToolTip("Notiz in Zwischenablage kopieren")
        btn_copy.setFixedSize(28, 26)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background: #1A2234;
                border: 1px solid #28354E;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: #253350;
                border-color: #58A6FF;
            }
        """)
        btn_copy.clicked.connect(self._copy_content)
        header_row.addWidget(btn_copy)

        # Delete single note button (Vector Icon)
        btn_del = QPushButton()
        btn_del.setIcon(create_vector_icon("trash", "#8B949E", 14))
        btn_del.setIconSize(QSize(14, 14))
        btn_del.setToolTip("Notiz entfernen")
        btn_del.setFixedSize(28, 26)
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setStyleSheet("""
            QPushButton {
                background: #1A2234;
                border: 1px solid #28354E;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: #3B161B;
                border-color: #DA3633;
            }
        """)
        btn_del.clicked.connect(lambda: self.delete_requested.emit(self.note_id))
        header_row.addWidget(btn_del)

        layout.addLayout(header_row)

        # Subtle separator line
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #1A2438; border: none;")
        layout.addWidget(sep)

        # Note Content Text with generous padding
        lbl_content = QLabel(note_data.get("note_text", ""))
        lbl_content.setWordWrap(True)
        lbl_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_content.setStyleSheet("color: #F0F6FC; font-size: 13px; line-height: 1.55; border: none; background: transparent; padding: 2px 0;")
        layout.addWidget(lbl_content)

    def _copy_content(self) -> None:
        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText(self.note_data.get("note_text", ""))


class ExtractCard(QFrame):
    """High-end sleek card for attached chapters / extracts on the virtual desk."""

    remove_requested = Signal(str)

    def __init__(self, ext_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.ext_data = ext_data
        self.ext_id = str(ext_data.get("id", ""))
        self.file_path = ext_data.get("file_path", "")

        self.setStyleSheet("""
            ExtractCard {
                background-color: #121826;
                border: 1px solid #232F48;
                border-left: 3px solid #58A6FF;
                border-radius: 8px;
            }
            ExtractCard:hover {
                background-color: #151E32;
                border-color: #388BFD;
                border-left: 3px solid #79C0FF;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignVCenter)

        # Left: Chapter Icon in accent pill
        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_pixmap("download", "#58A6FF", 16))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(lbl_icon)

        # Center: Title & Subtitle Info (Parent book & page range)
        info_col = QVBoxLayout()
        info_col.setSpacing(3)

        title_txt = ext_data.get("title", "Auszug")
        lbl_title = QLabel(title_txt)
        lbl_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        lbl_title.setWordWrap(True)
        info_col.addWidget(lbl_title)

        p_range = ext_data.get("page_range") or "—"
        p_count = ext_data.get("page_count", 0)
        parent_title = ext_data.get("parent_title") or "Dokument"
        sub_txt = f"📖 Aus: {parent_title}   •   Seiten: {p_range} ({p_count} S.)"
        lbl_sub = QLabel(sub_txt)
        lbl_sub.setFont(QFont("Segoe UI", 8))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        info_col.addWidget(lbl_sub)

        layout.addLayout(info_col, stretch=1)

        # Right: Action Buttons
        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)

        # 1. Open PDF
        btn_open = QPushButton("  Öffnen")
        btn_open.setIcon(create_vector_icon("desk", "#FFFFFF", 12))
        btn_open.setIconSize(QSize(12, 12))
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(28)
        btn_open.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        btn_open.clicked.connect(self._open_pdf)
        actions_row.addWidget(btn_open)

        # 2. Explorer (For NotebookLM)
        btn_exp = QPushButton("  Explorer")
        btn_exp.setIcon(create_vector_icon("external", "#C9D1D9", 12))
        btn_exp.setIconSize(QSize(12, 12))
        btn_exp.setToolTip("Im Explorer markieren (z.B. für Drag & Drop in NotebookLM)")
        btn_exp.setCursor(Qt.PointingHandCursor)
        btn_exp.setFixedHeight(28)
        btn_exp.setStyleSheet("""
            QPushButton {
                background: #162035;
                color: #C9D1D9;
                border: 1px solid #283750;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1E2D4A;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_exp.clicked.connect(self._show_in_explorer)
        actions_row.addWidget(btn_exp)

        # 3. Unpin / Remove from desk
        btn_unpin = QPushButton()
        btn_unpin.setIcon(create_vector_icon("trash", "#8B949E", 13))
        btn_unpin.setIconSize(QSize(13, 13))
        btn_unpin.setToolTip("Vom Schreibtisch abheften")
        btn_unpin.setFixedSize(28, 28)
        btn_unpin.setCursor(Qt.PointingHandCursor)
        btn_unpin.setStyleSheet("""
            QPushButton {
                background: #161D2A;
                border: 1px solid #243044;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: #381920;
                border-color: #F85149;
            }
        """)
        btn_unpin.clicked.connect(lambda: self.remove_requested.emit(self.ext_id))
        actions_row.addWidget(btn_unpin)

        layout.addLayout(actions_row)

    def _open_pdf(self) -> None:
        if self.file_path and os.path.exists(self.file_path):
            cfg = load_config()
            if cfg.get("use_internal_reader", True):
                book_ctx = {
                    "id": self.ext_data.get("parent_book_id", ""),
                    "title": self.ext_data.get("title", "Auszug"),
                    "file_path": self.file_path,
                }
                dlg = PdfReaderDialog(book_ctx, initial_page=1, parent=self)
                dlg.exec()
            else:
                open_pdf_in_edge(self.file_path)

    def _show_in_explorer(self) -> None:
        if self.file_path and os.path.exists(self.file_path):
            subprocess.run(["explorer", "/select,", os.path.normpath(self.file_path)])


class DeskView(QWidget):
    """Flagship Reading Desk Studio with clean non-overlapping typography."""

    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.desk_books: List[Dict[str, Any]] = []
        self.active_book: Optional[Dict[str, Any]] = None

        self._build_ui()
        QTimer.singleShot(1500, self._auto_pair_background)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 18)
        main_layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. Top Hero Header: Title & Homogeneous KPI Stat Cards
        # -------------------------------------------------------------
        top_row = QHBoxLayout()
        top_row.setSpacing(16)
        top_row.setAlignment(Qt.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setSpacing(4)

        title_header = QHBoxLayout()
        title_header.setSpacing(8)
        lbl_title_icon = QLabel()
        lbl_title_icon.setPixmap(create_vector_pixmap("desk", "#58A6FF", 22))
        lbl_title_icon.setStyleSheet("border: none; background: transparent;")
        title_header.addWidget(lbl_title_icon)

        lbl_title = QLabel("Mein Schreibtisch · Aktive Lektüre")
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        title_header.addWidget(lbl_title)
        title_header.addStretch()
        title_box.addLayout(title_header)

        lbl_sub = QLabel("Fokussierter Lese-Workspace mit synchronisiertem Lesefortschritt & Exzerpten")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent; padding-left: 2px;")
        title_box.addWidget(lbl_sub)
        top_row.addLayout(title_box, stretch=1)

        # Equal-sized balanced KPI Cards (150px fixed width, 66px fixed height)
        self.card_active = self._create_stat_card("Aktive Bücher", "0", "book", "#388BFD")
        self.card_progress = self._create_stat_card("Lese-Fortschritt", "0 %", "check", "#2EA043")
        self.card_notes = self._create_stat_card("Verfasste Notizen", "0", "notes", "#A371F7")
        self.card_streak = self._create_stat_card("Streak & Rang", "🔥 0", "bulb", "#E3B341")

        top_row.addWidget(self.card_active)
        top_row.addWidget(self.card_progress)
        top_row.addWidget(self.card_notes)
        top_row.addWidget(self.card_streak)

        main_layout.addLayout(top_row)

        # -------------------------------------------------------------
        # 2. Main Split Area: Books Table (Left) & Notes Studio (Right)
        # -------------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1F293D;
                width: 2px;
            }
        """)

        # Left Container: Reading Queue Table
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(10)

        left_header = QHBoxLayout()
        lbl_queue_icon = QLabel()
        lbl_queue_icon.setPixmap(create_vector_pixmap("library", "#8B949E", 16))
        lbl_queue_icon.setStyleSheet("border: none; background: transparent;")
        left_header.addWidget(lbl_queue_icon)

        lbl_queue = QLabel("Laufende Semesterlektüre")
        lbl_queue.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_queue.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        left_header.addWidget(lbl_queue)
        left_header.addStretch()
        left_layout.addLayout(left_header)

        # High-performance Table without overlapping cells
        self.table_desk = QTableWidget()
        self.table_desk.setItemDelegate(NoFocusItemDelegate(self.table_desk))
        self.table_desk.setColumnCount(3)
        self.table_desk.setHorizontalHeaderLabels(["Buchtitel & Autor", "Lesestand", "Fortschritt"])
        self.table_desk.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_desk.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table_desk.setColumnWidth(1, 110)
        self.table_desk.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table_desk.setColumnWidth(2, 140)
        self.table_desk.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_desk.setSelectionMode(QTableWidget.SingleSelection)
        self.table_desk.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_desk.verticalHeader().setVisible(False)
        self.table_desk.setShowGrid(False)
        self.table_desk.setStyleSheet("""
            QTableWidget {
                background-color: #0D111A;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 4px;
                outline: 0;
                outline: none;
            }
            QTableWidget:focus {
                outline: 0;
                outline: none;
            }
            QTableWidget::item {
                border-bottom: 1px solid #161F30;
                padding: 0px;
                outline: 0;
                outline: none;
                border-top: none;
                border-left: none;
                border-right: none;
            }
            QTableWidget::item:focus,
            QTableWidget::item:selected:focus {
                outline: 0;
                outline: none;
                border-top: none;
                border-left: none;
                border-right: none;
            }
            QTableWidget::item:selected {
                background-color: #16243E;
                border-radius: 6px;
                outline: 0;
                outline: none;
            }
            QHeaderView::section {
                background-color: #121826;
                color: #8B949E;
                font-weight: 600;
                font-size: 11px;
                border: none;
                border-bottom: 1px solid #232F48;
                padding: 8px 12px;
            }
        """)
        self.table_desk.itemSelectionChanged.connect(self._on_book_selected)
        left_layout.addWidget(self.table_desk, stretch=3)

        # -------------------------------------------------------------
        # Angeheftete Kapitel & Exzerpte auf dem Schreibtisch
        # -------------------------------------------------------------
        extracts_header = QHBoxLayout()
        lbl_ext_icon = QLabel()
        lbl_ext_icon.setPixmap(create_vector_pixmap("download", "#58A6FF", 15))
        lbl_ext_icon.setStyleSheet("border: none; background: transparent;")
        extracts_header.addWidget(lbl_ext_icon)

        self.lbl_extracts_title = QLabel("Angeheftete Kapitel & Auszüge (0)")
        self.lbl_extracts_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_extracts_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        extracts_header.addWidget(self.lbl_extracts_title)
        extracts_header.addStretch()
        left_layout.addLayout(extracts_header)

        # Scroll area with elegant ExtractCards
        self.scroll_extracts = QScrollArea()
        self.scroll_extracts.setWidgetResizable(True)
        self.scroll_extracts.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
        """)

        self.extracts_cards_container = QWidget()
        self.extracts_cards_container.setStyleSheet("background-color: transparent; border: none;")
        self.extracts_cards_layout = QVBoxLayout(self.extracts_cards_container)
        self.extracts_cards_layout.setContentsMargins(0, 0, 4, 0)
        self.extracts_cards_layout.setSpacing(8)

        self.scroll_extracts.setWidget(self.extracts_cards_container)
        left_layout.addWidget(self.scroll_extracts, stretch=2)

        splitter.addWidget(left_container)

        # Right Container: Notes & Excerpt Studio
        right_container = QWidget()
        right_container.setStyleSheet("""
            QWidget {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 10px;
            }
        """)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(18, 16, 18, 16)
        right_layout.setSpacing(12)

        # Header Studio Bar
        header_studio = QHBoxLayout()
        header_studio.setSpacing(8)
        header_studio.setAlignment(Qt.AlignVCenter)

        lbl_studio_icon = QLabel()
        lbl_studio_icon.setPixmap(create_vector_pixmap("notes", "#58A6FF", 18))
        lbl_studio_icon.setStyleSheet("border: none; background: transparent;")
        header_studio.addWidget(lbl_studio_icon)

        lbl_panel_title = QLabel("Notizen & Exzerpte Studio")
        lbl_panel_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_panel_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        header_studio.addWidget(lbl_panel_title)

        header_studio.addStretch()

        self.btn_export_all = QPushButton("  Alle exportieren")
        self.btn_export_all.setIcon(create_vector_icon("export", "#C9D1D9", 14))
        self.btn_export_all.setIconSize(QSize(14, 14))
        self.btn_export_all.setToolTip("Alle Notizen dieses Buches formatiert als Markdown kopieren")
        self.btn_export_all.setCursor(Qt.PointingHandCursor)
        self.btn_export_all.setStyleSheet("""
            QPushButton {
                background-color: #1F293D;
                border: 1px solid #30363D;
                color: #C9D1D9;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #28334E;
                color: #FFFFFF;
                border-color: #58A6FF;
            }
        """)
        self.btn_export_all.clicked.connect(self._export_all_notes)
        header_studio.addWidget(self.btn_export_all)
        right_layout.addLayout(header_studio)

        # Active Book context card (Never overlaps, wraps cleanly)
        self.book_banner = QFrame()
        self.book_banner.setStyleSheet("""
            QFrame {
                background-color: #0E1422;
                border: 1px solid #1E2B45;
                border-radius: 7px;
                padding: 6px;
            }
        """)
        banner_layout = QVBoxLayout(self.book_banner)
        banner_layout.setContentsMargins(10, 8, 10, 8)
        banner_layout.setSpacing(2)

        self.lbl_book_title = QLabel("Wähle ein Buch aus der Semesterlektüre...")
        self.lbl_book_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_book_title.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        self.lbl_book_title.setWordWrap(True)
        banner_layout.addWidget(self.lbl_book_title)

        self.lbl_book_author = QLabel("")
        self.lbl_book_author.setFont(QFont("Segoe UI", 9))
        self.lbl_book_author.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        banner_layout.addWidget(self.lbl_book_author)

        right_layout.addWidget(self.book_banner)

        # Bookmark / Page Controller Box (Clean linear alignment)
        bookmark_card = QFrame()
        bookmark_card.setStyleSheet("""
            QFrame {
                background-color: #0F1524;
                border: 1px solid #232F48;
                border-radius: 7px;
            }
        """)
        bm_layout = QHBoxLayout(bookmark_card)
        bm_layout.setContentsMargins(12, 6, 12, 6)
        bm_layout.setSpacing(10)
        bm_layout.setAlignment(Qt.AlignVCenter)

        lbl_bm_icon = QLabel()
        lbl_bm_icon.setPixmap(create_vector_pixmap("bookmark", "#58A6FF", 15))
        lbl_bm_icon.setStyleSheet("border: none; background: transparent;")
        bm_layout.addWidget(lbl_bm_icon)

        lbl_bm = QLabel("Lesezeichen / Seite:")
        lbl_bm.setStyleSheet("color: #F0F6FC; border: none; background: transparent; font-weight: 600; font-size: 12px;")
        bm_layout.addWidget(lbl_bm)

        self.ent_page = QLineEdit()
        self.ent_page.setFixedWidth(64)
        self.ent_page.setFixedHeight(28)
        self.ent_page.setAlignment(Qt.AlignCenter)
        self.ent_page.setStyleSheet("""
            QLineEdit {
                background-color: #0B0F19;
                border: 1px solid #304163;
                border-radius: 5px;
                color: #F0F6FC;
                font-weight: bold;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
            }
        """)
        bm_layout.addWidget(self.ent_page)

        btn_save_p = QPushButton("  Speichern")
        btn_save_p.setIcon(create_vector_icon("check", "#FFFFFF", 12))
        btn_save_p.setIconSize(QSize(12, 12))
        btn_save_p.setFixedHeight(28)
        btn_save_p.setCursor(Qt.PointingHandCursor)
        btn_save_p.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: none;
                border-radius: 5px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        btn_save_p.clicked.connect(self._save_page)
        bm_layout.addWidget(btn_save_p)

        self.btn_read_book = QPushButton("  📖 PDF Lesen")
        self.btn_read_book.setIcon(create_vector_icon("desk", "#FFFFFF", 12))
        self.btn_read_book.setIconSize(QSize(12, 12))
        self.btn_read_book.setFixedHeight(28)
        self.btn_read_book.setCursor(Qt.PointingHandCursor)
        self.btn_read_book.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                border: none;
                border-radius: 5px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)
        self.btn_read_book.clicked.connect(self._read_active_book)
        bm_layout.addWidget(self.btn_read_book)

        self.lbl_page_feedback = QLabel("")
        self.lbl_page_feedback.setStyleSheet("color: #3FB950; font-size: 11px; border: none; background: transparent; font-weight: bold;")
        bm_layout.addWidget(self.lbl_page_feedback)
        bm_layout.addStretch()

        right_layout.addWidget(bookmark_card)

        # Note Input Box (Quick capture with Ctrl+Enter)
        input_box = QFrame()
        input_box.setStyleSheet("""
            QFrame {
                background-color: #0B0F19;
                border: 1px solid #232F48;
                border-radius: 8px;
            }
            QFrame:focus-within {
                border-color: #388BFD;
            }
        """)
        input_layout = QVBoxLayout(input_box)
        input_layout.setContentsMargins(12, 10, 12, 8)
        input_layout.setSpacing(8)

        self.txt_notes = QuickNoteInput()
        self.txt_notes.setPlaceholderText("Neuen Gedanken, Formel oder Zitat erfassen... (Strg + Enter zum Speichern)")
        self.txt_notes.setFixedHeight(75)
        self.txt_notes.setStyleSheet("""
            QPlainTextEdit {
                background-color: transparent;
                color: #F0F6FC;
                border: none;
                font-size: 13px;
                line-height: 1.45;
            }
        """)
        self.txt_notes.submit_requested.connect(self._add_note)
        input_layout.addWidget(self.txt_notes)

        input_bottom = QHBoxLayout()
        input_bottom.setSpacing(8)
        input_bottom.setAlignment(Qt.AlignVCenter)

        lbl_hint_icon = QLabel()
        lbl_hint_icon.setPixmap(create_vector_pixmap("bulb", "#6E7681", 14))
        lbl_hint_icon.setStyleSheet("border: none; background: transparent;")
        input_bottom.addWidget(lbl_hint_icon)

        lbl_hint = QLabel("Strg + Enter speichert sofort")
        lbl_hint.setStyleSheet("color: #6E7681; font-size: 11px; border: none; background: transparent;")
        input_bottom.addWidget(lbl_hint)

        self.lbl_note_feedback = QLabel("")
        self.lbl_note_feedback.setStyleSheet("color: #3FB950; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        input_bottom.addWidget(self.lbl_note_feedback)

        input_bottom.addStretch()

        btn_add_note = QPushButton("  Notiz sichern")
        btn_add_note.setIcon(create_vector_icon("plus", "#FFFFFF", 12))
        btn_add_note.setIconSize(QSize(12, 12))
        btn_add_note.setObjectName("primaryButton")
        btn_add_note.setCursor(Qt.PointingHandCursor)
        btn_add_note.setFixedHeight(30)
        btn_add_note.clicked.connect(self._add_note)
        input_bottom.addWidget(btn_add_note)

        input_layout.addLayout(input_bottom)
        right_layout.addWidget(input_box)

        # Notes History Section (Scroll Area with interactive cards)
        self.lbl_notes_count = QLabel("Bisherige Notizen (0)")
        self.lbl_notes_count.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_notes_count.setStyleSheet("color: #C9D1D9; border: none; background: transparent; padding-top: 4px;")
        right_layout.addWidget(self.lbl_notes_count)

        self.scroll_notes = QScrollArea()
        self.scroll_notes.setWidgetResizable(True)
        self.scroll_notes.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
        """)

        self.notes_container = QWidget()
        self.notes_container.setStyleSheet("background-color: transparent; border: none;")
        self.notes_layout = QVBoxLayout(self.notes_container)
        self.notes_layout.setContentsMargins(0, 0, 4, 0)
        self.notes_layout.setSpacing(10)
        self.notes_layout.addStretch()

        self.scroll_notes.setWidget(self.notes_container)
        right_layout.addWidget(self.scroll_notes, stretch=1)

        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, stretch=1)

        # -------------------------------------------------------------
        # 3. Bottom Action Bar
        # -------------------------------------------------------------
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        btn_open = QPushButton("  In Edge aufschlagen (gespeicherte Seite)")
        btn_open.setIcon(create_vector_icon("desk", "#FFFFFF", 18))
        btn_open.setObjectName("accentButton")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(38)
        btn_open.clicked.connect(self._open_active_pdf)
        bottom_bar.addWidget(btn_open)

        btn_tutor = QPushButton("  🎯 KI-Tutor & Klausur-Studio")
        btn_tutor.setCursor(Qt.PointingHandCursor)
        btn_tutor.setFixedHeight(38)
        btn_tutor.setStyleSheet("""
            QPushButton {
                background-color: #1A2438;
                border: 1px solid #388BFD;
                color: #58A6FF;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #253552;
                color: #FFFFFF;
                border-color: #79C0FF;
            }
        """)
        btn_tutor.clicked.connect(self._open_tutor_studio)
        bottom_bar.addWidget(btn_tutor)

        btn_remove = QPushButton("  Vom Schreibtisch entfernen")
        btn_remove.setIcon(create_vector_icon("trash", "#F85149", 16))
        btn_remove.setObjectName("dangerButton")
        btn_remove.setCursor(Qt.PointingHandCursor)
        btn_remove.setFixedHeight(38)
        btn_remove.clicked.connect(self._remove_from_desk)
        bottom_bar.addWidget(btn_remove)

        bottom_bar.addStretch()
        main_layout.addLayout(bottom_bar)

    def _create_stat_card(self, title: str, value: str, icon_name: str, accent_color: str) -> QFrame:
        card = QFrame()
        card.setFixedSize(150, 68)
        card.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161D2C, stop:1 #111724);
                border: 1px solid #232F48;
                border-top: 3px solid {accent_color};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        top_h = QHBoxLayout()
        top_h.setSpacing(6)
        top_h.setAlignment(Qt.AlignVCenter)

        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_pixmap(icon_name, accent_color, 14))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        top_h.addWidget(lbl_icon)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        top_h.addWidget(lbl_t)
        top_h.addStretch()
        layout.addLayout(top_h)

        lbl_v = QLabel(value)
        lbl_v.setObjectName("valueLabel")
        lbl_v.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_v.setStyleSheet("color: #F0F6FC; border: none; background: transparent; padding-top: 1px;")
        layout.addWidget(lbl_v)

        return card

    def load_data(self) -> None:
        """Refreshes desk books and updates dashboard metrics while preserving selection."""
        selected_id = str(self.active_book["id"]) if self.active_book else None
        self.desk_books = get_desk_books()
        self._render_table()
        self._render_extracts_table()
        self._update_metrics()

        # Restore selection seamlessly
        restored = False
        if selected_id:
            for r, b in enumerate(self.desk_books):
                if str(b.get("id")) == selected_id:
                    self.table_desk.selectRow(r)
                    self.active_book = b
                    restored = True
                    break
        if not restored and self.desk_books:
            self.table_desk.selectRow(0)
            self.active_book = self.desk_books[0]

        if self.active_book:
            title = self.active_book.get("title", "")
            author = self.active_book.get("author", "Unbekannt")
            self.lbl_book_title.setText(title)
            self.lbl_book_author.setText(f"von {author}")
            curr_p = max(1, int(self.active_book.get("current_page") or 1))
            self.ent_page.setText(str(curr_p))

        self._refresh_active_notes()
        self._refresh_study_plan()

    def _render_extracts_table(self) -> None:
        """Renders extracts and chapters placed on the desk as luxury cards."""
        # Clear existing card widgets
        while self.extracts_cards_layout.count() > 0:
            item = self.extracts_cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        extracts = get_desk_extracts()
        self.lbl_extracts_title.setText(f"Angeheftete Kapitel & Auszüge ({len(extracts)})")

        if not extracts:
            lbl_empty = QLabel("Keine Kapitel auf den Schreibtisch geheftet.\nDu kannst bei der Extraktion eines PDFs oder im Quick-Look Kapitel anheften.")
            lbl_empty.setStyleSheet("color: #6E7681; font-style: italic; padding: 18px; border: none; background: transparent;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            self.extracts_cards_layout.addWidget(lbl_empty)
            self.extracts_cards_layout.addStretch()
            return

        for ext in extracts:
            card = ExtractCard(ext, self)
            card.remove_requested.connect(self._remove_extract_from_desk)
            self.extracts_cards_layout.addWidget(card)

        self.extracts_cards_layout.addStretch()

    def _remove_extract_from_desk(self, extract_id: str) -> None:
        toggle_extract_desk(extract_id)
        self.load_data()
        self.data_changed.emit()

    def _update_metrics(self) -> None:
        cnt = len(self.desk_books)
        lbl_v_active = self.card_active.findChild(QLabel, "valueLabel")
        if lbl_v_active:
            lbl_v_active.setText(str(cnt))

        # Overall average progress
        if cnt > 0:
            avg_p = sum((b.get("progress_pct") or b.get("progress_percent") or 0) for b in self.desk_books) / cnt
            prog_str = f"{int(avg_p)} %"
        else:
            prog_str = "0 %"

        lbl_v_prog = self.card_progress.findChild(QLabel, "valueLabel")
        if lbl_v_prog:
            lbl_v_prog.setText(prog_str)

        # Total notes across all books on desk
        total_notes = sum(len(get_book_notes(str(b["id"]))) for b in self.desk_books)
        lbl_v_notes = self.card_notes.findChild(QLabel, "valueLabel")
        if lbl_v_notes:
            lbl_v_notes.setText(str(total_notes))

        # Gamification profile & streak
        profile = get_gamification_profile()
        streak = profile.get("current_streak", 0)
        lvl = profile.get("level", 1)
        lbl_v_streak = self.card_streak.findChild(QLabel, "valueLabel")
        if lbl_v_streak:
            lbl_v_streak.setText(f"🔥 {streak} · Lvl {lvl}")

    def _render_table(self) -> None:
        self.table_desk.setUpdatesEnabled(False)
        try:
            self.table_desk.setRowCount(len(self.desk_books))
            for r, b in enumerate(self.desk_books):
                # Generous row height of 66px to guarantee zero overlapping text
                self.table_desk.setRowHeight(r, 66)

                # Column 0: Clean Two-Line Book Title & Author
                title = b.get("title", "")
                author = b.get("author", "Unbekannt")
                cell_title = QWidget()
                cell_title.setStyleSheet("background: transparent;")
                cell_title_layout = QVBoxLayout(cell_title)
                cell_title_layout.setContentsMargins(12, 10, 12, 10)
                cell_title_layout.setSpacing(3)
                cell_title_layout.setAlignment(Qt.AlignVCenter)

                lbl_t = QLabel(title)
                lbl_t.setFont(QFont("Segoe UI", 10, QFont.Bold))
                lbl_t.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
                lbl_t.setFixedHeight(20)
                cell_title_layout.addWidget(lbl_t)

                lbl_a = QLabel(author)
                lbl_a.setFont(QFont("Segoe UI", 9))
                lbl_a.setStyleSheet("color: #8B949E; border: none; background: transparent;")
                lbl_a.setFixedHeight(18)
                cell_title_layout.addWidget(lbl_a)

                self.table_desk.setCellWidget(r, 0, cell_title)

                # Column 1: Reading Position Badge
                curr_p = max(1, int(b.get("current_page") or 1))
                total_p = b.get("page_count", 0)
                p_str = f"S. {curr_p} / {total_p}" if total_p > 0 else f"S. {curr_p}"
                item_p = QTableWidgetItem(p_str)
                item_p.setTextAlignment(Qt.AlignCenter)
                item_p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                item_p.setForeground(QColor("#C9D1D9"))
                self.table_desk.setItem(r, 1, item_p)

                # Column 2: Progress Bar Widget directly in cell (Non-overlapping layout)
                pct = max(0, min(100, int(b.get("progress_pct") or b.get("progress_percent") or 0)))
                p_container = QWidget()
                p_container.setStyleSheet("background: transparent;")
                p_layout = QVBoxLayout(p_container)
                p_layout.setContentsMargins(12, 14, 12, 14)
                p_layout.setSpacing(6)
                p_layout.setAlignment(Qt.AlignVCenter)

                p_bar = QProgressBar()
                p_bar.setRange(0, 100)
                p_bar.setValue(pct)
                p_bar.setFixedHeight(6)
                p_bar.setTextVisible(False)
                p_bar.setStyleSheet("""
                    QProgressBar {
                        background-color: #0D1117;
                        border: 1px solid #232F48;
                        border-radius: 3px;
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #58A6FF);
                        border-radius: 2px;
                    }
                """)
                p_layout.addWidget(p_bar)

                lbl_pct = QLabel(f"{pct} % gelesen")
                lbl_pct.setFont(QFont("Segoe UI", 9))
                lbl_pct.setFixedHeight(16)
                lbl_pct.setAlignment(Qt.AlignCenter)
                lbl_pct.setStyleSheet("color: #8B949E; border: none; background: transparent;")
                p_layout.addWidget(lbl_pct)

                self.table_desk.setCellWidget(r, 2, p_container)

        finally:
            self.table_desk.setUpdatesEnabled(True)

    def _on_book_selected(self) -> None:
        row = self.table_desk.currentRow()
        if 0 <= row < len(self.desk_books):
            self.active_book = self.desk_books[row]
            title = self.active_book.get("title", "")
            author = self.active_book.get("author", "Unbekannt")
            self.lbl_book_title.setText(title)
            self.lbl_book_author.setText(f"von {author}")
            curr_p = max(1, int(self.active_book.get("current_page") or 1))
            self.ent_page.setText(str(curr_p))
            self._refresh_active_notes()
            self._refresh_study_plan()
        else:
            self.active_book = None
            self.lbl_book_title.setText("Wähle ein Buch aus der Semesterlektüre...")
            self.lbl_book_author.setText("")
            self.ent_page.clear()
            self._refresh_active_notes()
            self._refresh_study_plan()

    def _refresh_active_notes(self) -> None:
        """Clears and re-populates the note cards for the selected book."""
        # Clear existing note card widgets safely
        while self.notes_layout.count() > 0:
            item = self.notes_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self.active_book:
            self.lbl_notes_count.setText("Bisherige Notizen (0)")
            lbl_empty = QLabel("Kein Buch ausgewählt.")
            lbl_empty.setStyleSheet("color: #6E7681; font-style: italic; padding: 20px; border: none; background: transparent;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            self.notes_layout.addWidget(lbl_empty)
            self.notes_layout.addStretch()
            return

        bid = str(self.active_book["id"])
        notes = get_book_notes(bid)
        self.lbl_notes_count.setText(f"Bisherige Notizen ({len(notes)})")

        if not notes:
            lbl_empty = QLabel("Noch keine Notizen erfasst.\nTippe oben deine erste Erkenntnis oder ein Zitat ein!")
            lbl_empty.setStyleSheet("color: #6E7681; font-style: italic; padding: 28px; border: none; background: transparent;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            self.notes_layout.addWidget(lbl_empty)
            self.notes_layout.addStretch()
            return

        for n in notes:
            card = NoteCard(n)
            card.delete_requested.connect(self._on_delete_note)
            self.notes_layout.addWidget(card)

        self.notes_layout.addStretch()

    def _save_page(self) -> None:
        if not self.active_book:
            return
        try:
            p = max(1, int(self.ent_page.text().strip()))
            bid = str(self.active_book["id"])
            old_p = max(1, int(self.active_book.get("current_page") or 1))
            update_reading_progress(bid, p)

            delta = max(0, p - old_p)
            xp_txt = ""
            if delta > 0:
                earned_xp = log_daily_reading(bid, delta)
                xp_txt = f" (+{earned_xp} XP)"

            self.lbl_page_feedback.setText(f"✓ Gespeichert!{xp_txt}")
            QTimer.singleShot(2500, lambda: self.lbl_page_feedback.setText(""))
            self.active_book["current_page"] = p
            self.load_data()
            self.data_changed.emit()
        except ValueError:
            pass

    def _read_active_book(self) -> None:
        if not self.active_book:
            return
        fpath = self.active_book.get("file_path", "")
        if not fpath or not os.path.exists(fpath):
            return
        curr_p = max(1, int(self.active_book.get("current_page") or 1))
        cfg = load_config()
        if cfg.get("use_internal_reader", True):
            dlg = PdfReaderDialog(self.active_book, initial_page=curr_p, parent=self)
            dlg.progress_updated.connect(lambda bid, p: self.load_data())
            dlg.exec()
            self.load_data()
            self.data_changed.emit()
        else:
            open_pdf_in_edge(fpath, page=curr_p)

    def _add_note(self) -> None:
        if not self.active_book:
            return
        txt = self.txt_notes.toPlainText().strip()
        if not txt:
            return

        bid = str(self.active_book["id"])
        try:
            p = int(self.ent_page.text().strip())
        except ValueError:
            p = None

        add_book_note(bid, txt, p)
        self.txt_notes.clear()
        self.txt_notes.setFocus()

        self.lbl_note_feedback.setText("✓ Notiz gesichert!")
        QTimer.singleShot(2500, lambda: self.lbl_note_feedback.setText(""))

        # Update note list immediately without modal popups
        self._refresh_active_notes()
        self._update_metrics()
        self.data_changed.emit()

    def _on_delete_note(self, note_id: int) -> None:
        delete_book_note(note_id)
        self._refresh_active_notes()
        self._update_metrics()
        self.data_changed.emit()

    def _export_all_notes(self) -> None:
        if not self.active_book:
            return
        bid = str(self.active_book["id"])
        notes = get_book_notes(bid)
        if not notes:
            return

        title = self.active_book.get("title", "Buch")
        lines = [f"# Exzerpte & Notizen zu: {title}\n"]
        for n in notes:
            created_ts = n.get("created_at") or time.time()
            time_str = time.strftime("%d.%m.%Y um %H:%M", time.localtime(created_ts))
            p_str = f" (Seite {n['page_number']})" if n.get("page_number") else ""
            lines.append(f"### {time_str}{p_str}\n")
            lines.append(f"{n.get('note_text', '')}\n")
            lines.append("---\n")

        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText("\n".join(lines))
            self.lbl_note_feedback.setText("✓ Alle Notizen kopiert!")
            QTimer.singleShot(2500, lambda: self.lbl_note_feedback.setText(""))

    def _open_active_pdf(self) -> None:
        if not self.active_book or not self.active_book.get("file_path"):
            return
        page = self.active_book.get("current_page", 1)
        open_pdf_in_edge(self.active_book["file_path"], page=page)

    def _remove_from_desk(self) -> None:
        if not self.active_book:
            return
        bid = str(self.active_book["id"])
        toggle_desk_item(bid)
        self.data_changed.emit()
        self.load_data()

    def _auto_pair_background(self) -> None:
        """Runs textbook-workbook pairing in background thread without blocking UI."""
        def _runner():
            try:
                books = get_all_books()
                if books:
                    auto_pair_library(books)
            except Exception:
                pass
        threading.Thread(target=_runner, daemon=True).start()

    def _refresh_study_plan(self) -> None:
        """Safe no-op: Study planning module moved to Klausur Studio."""
        pass

    def _open_plan_config(self) -> None:
        """Opens study plan configuration modal for the active book."""
        if not self.active_book:
            return
        dlg = StudyPlanDialog(self.active_book, parent=self)
        if dlg.exec():
            self._refresh_study_plan()
            self._update_metrics()
            self.data_changed.emit()

    def _open_tutor_studio(self) -> None:
        """Opens AI Tutor Studio modal with quizzes, exam simulation and cheat sheets."""
        if not self.active_book:
            return
        dlg = TutorStudioDialog(self.active_book, initial_mode="quiz", parent=self)
        dlg.xp_gained.connect(lambda xp: (self._refresh_study_plan(), self._update_metrics()))
        dlg.exec()
        self._refresh_study_plan()
        self._update_metrics()

    def _open_companion_workbook(self) -> None:
        """Directly opens paired companion workbook or textbook in Edge."""
        if not self.active_book:
            return
        try:
            bid = str(self.active_book["id"])
            pair = get_book_pair(bid)
            if pair and pair.get("file_path"):
                page = pair.get("current_page") or 1
                open_pdf_in_edge(pair["file_path"], page=page)
        except Exception:
            pass
