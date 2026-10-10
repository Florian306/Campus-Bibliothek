"""Main Application Window for Campus Library AI (PySide6).
Delivers a high-end Cyber-Obsidian interface with glowing accents, razor-sharp vector icons,
and responsive stacked view routing.
"""

import os
from typing import Optional
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QIcon
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QStackedWidget,
    QFrame,
    QApplication,
)

from ui.qt.theme import DARK_STYLESHEET
from ui.qt.icons import create_vector_icon
from ui.qt.views.jarvis_view import JarvisView
from ui.qt.views.catalog_view import CatalogView
from ui.qt.views.desk_view import DeskView
from ui.qt.views.radar_view import RadarView
from ui.qt.views.sync_view import SyncView
from ui.qt.views.research_view import ResearchView
from ui.qt.views.textbook_search_view import TextbookSearchView
from ui.qt.views.academic_web_view import AcademicWebView
from ui.qt.views.exam_studio_view import ExamStudioView
from ui.qt.dialogs.quick_look import QuickLookDialog
from core.library_db import get_category_counts, get_all_research_papers


class CampusMainWindow(QMainWindow):
    """Flagship Main Application Window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Campus-Bibliothek AI – Virtueller Lehrbuch-Workspace")
        self.resize(1340, 860)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(DARK_STYLESHEET)

        # Set Window & Taskbar Icon
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app_icon.ico"))
        if not os.path.exists(icon_path):
            icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app_icon.png"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._nav_buttons = {}
        self._build_ui()
        self._setup_shortcuts()

        # Connect inter-view signals
        self.view_catalog.data_changed.connect(self._on_data_modified)
        self.view_desk.data_changed.connect(self._on_data_modified)
        self.view_sync.scan_finished.connect(self._on_data_modified)
        self.view_catalog.quick_look_requested.connect(self._open_quick_look_for_id)

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # -------------------------------------------------------------
        # 1. Left Navigation Sidebar (250px)
        # -------------------------------------------------------------
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(250)
        self.sidebar.setStyleSheet("""
            QFrame {
                background-color: #0F1422;
                border-right: 1px solid #232F48;
            }
        """)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 22, 14, 20)
        sidebar_layout.setSpacing(6)

        # Brand Header Pill
        brand_card = QFrame()
        brand_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #141C2E, stop:1 #1A243B);
                border: 1px solid #324468;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        brand_layout = QVBoxLayout(brand_card)
        brand_layout.setContentsMargins(12, 10, 12, 10)
        brand_layout.setSpacing(3)

        brand_top = QHBoxLayout()
        from ui.qt.icons import create_vector_pixmap
        lbl_logo = QLabel()
        lbl_logo.setPixmap(create_vector_pixmap("book", "#58A6FF", 20))
        lbl_logo.setStyleSheet("border: none; background: transparent;")
        brand_top.addWidget(lbl_logo)

        lbl_brand_name = QLabel("CAMPUS AI")
        lbl_brand_name.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_brand_name.setStyleSheet("color: #F0F6FC; border: none; background: transparent; letter-spacing: 0.5px;")
        brand_top.addWidget(lbl_brand_name)
        brand_top.addStretch()

        lbl_badge = QLabel("PRO")
        lbl_badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_badge.setStyleSheet("""
            background: #1F6FEB;
            color: #FFFFFF;
            border-radius: 4px;
            padding: 2px 6px;
        """)
        brand_top.addWidget(lbl_badge)
        brand_layout.addLayout(brand_top)

        lbl_sub = QLabel("Virtuelle Fachbibliothek")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        brand_layout.addWidget(lbl_sub)

        sidebar_layout.addWidget(brand_card)
        sidebar_layout.addSpacing(16)

        # Nav Header Label
        lbl_nav_header = QLabel("NAVIGATION")
        lbl_nav_header.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_nav_header.setStyleSheet("color: #526382; border: none; background: transparent; padding-left: 8px; letter-spacing: 1px;")
        sidebar_layout.addWidget(lbl_nav_header)

        # Nav Items with Vector Icons
        nav_items = [
            ("jarvis", "jarvis", "JARVIS Briefing", 0),
            ("catalog", "library", "Bibliothek & Katalog", 1),
            ("desk", "desk", "Mein Schreibtisch", 2),
            ("exam", "exam", "Klausur-Studio", 3),
            ("research", "research", "Paper & Forschung", 4),
            ("textbooks", "book", "Fachbuch-Suche", 5),
            ("web", "globe", "Fach-Websuche", 6),
            ("radar", "radar", "Auflagen-Radar", 7),
            ("sync", "sync", "Scan & Sync", 8),
        ]

        for key, icon_name, text, idx in nav_items:
            btn = QPushButton(f"  {text}")
            btn.setIcon(create_vector_icon(icon_name, "#58A6FF", 20))
            btn.setIconSize(QSize(20, 20))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(44)
            btn.clicked.connect(lambda checked, i=idx, k=key: self._switch_tab(k, i))
            sidebar_layout.addWidget(btn)
            self._nav_buttons[key] = btn

        sidebar_layout.addStretch()

        # Sidebar Footer Card (Statistics & Engine Status)
        stats_card = QFrame()
        stats_card.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        stats_layout = QVBoxLayout(stats_card)
        stats_layout.setContentsMargins(12, 10, 12, 10)
        stats_layout.setSpacing(4)

        status_top = QHBoxLayout()
        lbl_dot = QLabel("●")
        lbl_dot.setFont(QFont("Segoe UI", 9))
        lbl_dot.setStyleSheet("color: #3FB950; border: none; background: transparent;")
        status_top.addWidget(lbl_dot)

        lbl_engine = QLabel("SQLite Data-Lake")
        lbl_engine.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_engine.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        status_top.addWidget(lbl_engine)
        status_top.addStretch()
        stats_layout.addLayout(status_top)

        self.lbl_stats = QLabel("320 Fachbücher geladen")
        self.lbl_stats.setFont(QFont("Segoe UI", 9))
        self.lbl_stats.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        stats_layout.addWidget(self.lbl_stats)

        sidebar_layout.addWidget(stats_card)
        root_layout.addWidget(self.sidebar)

        # -------------------------------------------------------------
        # 2. Central Content Area (Stacked Views)
        # -------------------------------------------------------------
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #0B0F19;")

        self.view_jarvis = JarvisView(self)
        self.view_catalog = CatalogView(self)
        self.view_desk = DeskView(self)
        self.view_exam = ExamStudioView(self)
        self.view_research = ResearchView(self)
        self.view_textbooks = TextbookSearchView(self)
        self.view_academic_web = AcademicWebView(self)
        self.view_radar = RadarView(self)
        self.view_sync = SyncView(self)

        self.stack.addWidget(self.view_jarvis)
        self.stack.addWidget(self.view_catalog)
        self.stack.addWidget(self.view_desk)
        self.stack.addWidget(self.view_exam)
        self.stack.addWidget(self.view_research)
        self.stack.addWidget(self.view_textbooks)
        self.stack.addWidget(self.view_academic_web)
        self.stack.addWidget(self.view_radar)
        self.stack.addWidget(self.view_sync)

        root_layout.addWidget(self.stack, stretch=1)

        # Select first tab: JARVIS
        self._switch_tab("jarvis", 0)

    def _setup_shortcuts(self) -> None:
        shortcut_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        shortcut_space.activated.connect(self._on_space_pressed)

    def _switch_tab(self, key: str, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #182338, stop:1 #141C2E);
                        color: #FFFFFF;
                        border: 1px solid #388BFD;
                        border-left: 4px solid #58A6FF;
                        border-radius: 7px;
                        text-align: left;
                        padding-left: 12px;
                        font-weight: 700;
                        font-size: 13px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #8B949E;
                        border: 1px solid transparent;
                        border-radius: 7px;
                        text-align: left;
                        padding-left: 14px;
                        font-weight: 600;
                        font-size: 13px;
                    }
                    QPushButton:hover {
                        background-color: #151D2E;
                        color: #F0F6FC;
                        border-color: #232F48;
                    }
                """)

        # Trigger data refresh on tab activate
        if idx == 1:
            self.view_catalog.load_data()
        elif idx == 2:
            self.view_desk.load_data()
        elif idx == 3:
            self.view_exam.load_data()
        elif idx == 4:
            self.view_research.load_data()
        elif idx == 5:
            self.view_textbooks.load_data()
        elif idx == 7:
            self.view_radar.load_data()

    def update_sidebar_stats(self) -> None:
        cats = get_category_counts()
        total_b = sum(c[1] for c in cats)
        papers = get_all_research_papers()
        total_p = len(papers)
        if total_p > 0:
            self.lbl_stats.setText(f"{total_b} Bücher · {total_p} Paper")
        else:
            self.lbl_stats.setText(f"{total_b} Fachbücher indiziert")

    def _on_data_modified(self) -> None:
        self.update_sidebar_stats()
        self.view_catalog.load_data()
        self.view_exam.load_data()

    def _on_space_pressed(self) -> None:
        focus = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit
        if isinstance(focus, (QLineEdit, QPlainTextEdit)):
            return
        bid = self.view_catalog._get_active_book_id()
        if bid:
            self._open_quick_look_for_id(bid)

    def _open_quick_look_for_id(self, book_id: str) -> None:
        books = self.view_catalog.master_books
        book = next((b for b in books if str(b["id"]) == str(book_id)), None)
        if book:
            dlg = QuickLookDialog(book, self)
            dlg.exec()
            if getattr(dlg, "was_data_modified", False):
                self._on_data_modified()
            else:
                self.view_catalog._refresh_single_book(book_id)

    def closeEvent(self, event) -> None:
        """Instant zero-latency termination."""
        try:
            self.hide()
        except Exception:
            pass
        os._exit(0)
