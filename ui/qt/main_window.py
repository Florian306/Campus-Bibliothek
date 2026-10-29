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
from ui.qt.dialogs.quick_look import QuickLookDialog
from core.library_db import get_category_counts, get_all_research_papers, get_inbox_count


class CampusMainWindow(QMainWindow):
    """Flagship Main Application Window with high-performance Lazy-View loading."""

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
        self._views_cache = {}
        self._build_ui()
        self._setup_shortcuts()
        self._setup_tray()
        self._start_startup_update_check()

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
            ("scripts", "notes", "Studienbriefe & Skripte", 2),
            ("inbox", "inbox", "Posteingang", 3),
            ("desk", "desk", "Mein Schreibtisch", 4),
            ("research", "research", "Paper & Forschung", 5),
            ("textbooks", "book", "Fachbuch-Suche", 6),
            ("web", "globe", "Fach-Websuche", 7),
            ("radar", "radar", "Auflagen-Radar", 8),
            ("sync", "sync", "Scan & Sync", 9),
        ]

        for key, icon_name, text, idx in nav_items:
            safe_text = text.replace("&", "&&")
            btn = QPushButton(f"  {safe_text}")
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
        # 2. Central Content Area (Stacked Views with Lazy Instantiation)
        # -------------------------------------------------------------
        self.stack = QStackedWidget(central_widget)
        self.stack.setStyleSheet("background-color: #0B0F19;")

        root_layout.addWidget(self.stack, stretch=1)

        # Select initial view (JARVIS Briefing)
        self._switch_tab("jarvis", 0)

    def _setup_tray(self) -> None:
        """Configures Windows System Tray icon for instant background reopen."""
        from PySide6.QtWidgets import QSystemTrayIcon, QMenu
        from PySide6.QtGui import QAction

        self.tray_icon = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = self.windowIcon()
        if icon.isNull():
            return

        self.tray_icon = QSystemTrayIcon(icon, self)
        tray_menu = QMenu(self)
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #161B22;
                color: #F0F6FC;
                border: 1px solid #30363D;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #1F6FEB;
            }
        """)

        act_show = QAction("Campus-Bibliothek öffnen", self)
        act_show.triggered.connect(self._restore_from_tray)
        tray_menu.addAction(act_show)

        tray_menu.addSeparator()

        act_quit = QAction("Beenden", self)
        act_quit.triggered.connect(self._force_quit)
        tray_menu.addAction(act_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showMaximized()
        self.activateWindow()
        self.raise_()

    def _force_quit(self) -> None:
        if self.tray_icon:
            self.tray_icon.hide()
        try:
            from core.config import load_app_config
            from core.github_sync import GitHubSyncService
            cfg = load_app_config()
            if cfg.github_auto_sync and cfg.github_token.strip():
                GitHubSyncService.push_to_gist()
        except Exception:
            pass
        os._exit(0)

    def _get_or_create_view(self, key: str, idx: int) -> QWidget:
        """Lazily creates and attaches a view only when activated."""
        if key in self._views_cache:
            return self._views_cache[key]

        view = None
        if key == "jarvis":
            from ui.qt.views.jarvis_view import JarvisView
            view = JarvisView(self.stack)
        elif key == "catalog":
            from ui.qt.views.catalog_view import CatalogView
            view = CatalogView(mode="books", parent=self.stack)
            view.data_changed.connect(self._on_data_modified)
            view.quick_look_requested.connect(self._open_quick_look_for_id)
        elif key == "scripts":
            from ui.qt.views.catalog_view import CatalogView
            view = CatalogView(mode="study_scripts", parent=self.stack)
            view.data_changed.connect(self._on_data_modified)
            view.quick_look_requested.connect(self._open_quick_look_for_id)
        elif key == "inbox":
            from ui.qt.views.inbox_view import InboxView
            view = InboxView(self.stack)
            view.book_filed.connect(self._on_data_modified)
            view.queue_updated.connect(self._update_inbox_badge)
        elif key == "desk":
            from ui.qt.views.desk_view import DeskView
            view = DeskView(self.stack)
            view.data_changed.connect(self._on_data_modified)
        elif key == "research":
            from ui.qt.views.research_view import ResearchView
            view = ResearchView(self.stack)
        elif key == "textbooks":
            from ui.qt.views.textbook_search_view import TextbookSearchView
            view = TextbookSearchView(self.stack)
        elif key == "web":
            from ui.qt.views.academic_web_view import AcademicWebView
            view = AcademicWebView(self.stack)
        elif key == "radar":
            from ui.qt.views.radar_view import RadarView
            view = RadarView(self.stack)
        elif key == "sync":
            from ui.qt.views.sync_view import SyncView
            view = SyncView(self.stack)
            view.scan_finished.connect(self._on_data_modified)
            view.update_available_signal.connect(self._on_update_available_badge)

        if view:
            self._views_cache[key] = view
            if self.stack.indexOf(view) == -1:
                self.stack.addWidget(view)

        return view

    # Backward-compatible property proxies for direct attribute access
    @property
    def view_jarvis(self):
        return self._get_or_create_view("jarvis", 0)

    @property
    def view_catalog(self):
        return self._get_or_create_view("catalog", 1)

    @property
    def view_scripts(self):
        return self._get_or_create_view("scripts", 2)

    @property
    def view_inbox(self):
        return self._get_or_create_view("inbox", 3)

    @property
    def view_desk(self):
        return self._get_or_create_view("desk", 4)

    @property
    def view_research(self):
        return self._get_or_create_view("research", 5)

    @property
    def view_textbooks(self):
        return self._get_or_create_view("textbooks", 6)

    @property
    def view_academic_web(self):
        return self._get_or_create_view("web", 7)

    @property
    def view_radar(self):
        return self._get_or_create_view("radar", 8)

    @property
    def view_sync(self):
        return self._get_or_create_view("sync", 9)

    def _setup_shortcuts(self) -> None:
        shortcut_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        shortcut_space.activated.connect(self._on_space_pressed)

    def _switch_tab(self, key: str, idx: int) -> None:
        # 1. Lazily ensure view is created
        view = self._get_or_create_view(key, idx)
        if view:
            self.stack.setCurrentWidget(view)

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
        if idx in (1, 2):
            if hasattr(view, "master_books") and not view.master_books:
                view.load_data()
        elif idx == 3:
            if hasattr(view, "sync_filesystem_with_db"):
                view.sync_filesystem_with_db()
        elif idx in (4, 5, 6, 8, 9):
            if hasattr(view, "load_data"):
                view.load_data()

    def update_sidebar_stats(self) -> None:
        cats = get_category_counts()
        total_b = sum(c[1] for c in cats)
        papers = get_all_research_papers()
        total_p = len(papers)
        if total_p > 0:
            self.lbl_stats.setText(f"{total_b} Dokumente · {total_p} Paper")
        else:
            self.lbl_stats.setText(f"{total_b} Dokumente indiziert")

        self._update_inbox_badge(get_inbox_count())

    def _update_inbox_badge(self, count: int) -> None:
        btn_inbox = self._nav_buttons.get("inbox")
        if btn_inbox:
            if count > 0:
                btn_inbox.setText(f"  Posteingang ({count})")
            else:
                btn_inbox.setText("  Posteingang")

    def _start_startup_update_check(self) -> None:
        import threading
        from PySide6.QtCore import QTimer
        from core.update_checker import check_for_updates

        def _worker():
            avail, latest, _, _ = check_for_updates()
            if avail and latest:
                QTimer.singleShot(0, lambda: self._on_update_available_badge(latest))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_available_badge(self, latest_ver: str) -> None:
        btn_sync = self._nav_buttons.get("sync")
        if btn_sync and latest_ver:
            btn_sync.setText(f"  Scan && Sync  •  v{latest_ver} ⬆")

    def _on_data_modified(self) -> None:
        self.update_sidebar_stats()
        if "catalog" in self._views_cache:
            self.view_catalog.load_data()
        if "scripts" in self._views_cache:
            self.view_scripts.load_data()

    def _on_space_pressed(self) -> None:
        # Space shortcut is for Catalog and Studienbriefe
        curr_widget = self.stack.currentWidget()
        cat_view = self._views_cache.get("catalog")
        scripts_view = self._views_cache.get("scripts")
        if curr_widget not in (cat_view, scripts_view) or not curr_widget:
            return
        focus = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QPushButton
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QPushButton)):
            return
        bid = curr_widget._get_active_book_id()
        if bid:
            self._open_quick_look_for_id(bid)

    def _open_quick_look_for_id(self, book_id: str) -> None:
        from core.library_db import get_book_by_id
        book = get_book_by_id(book_id)
        if book:
            dlg = QuickLookDialog(book, self)
            dlg.exec()
            if getattr(dlg, "was_data_modified", False):
                self._on_data_modified()
            else:
                if "catalog" in self._views_cache:
                    self.view_catalog._refresh_single_book(book_id)
                if "scripts" in self._views_cache:
                    self.view_scripts._refresh_single_book(book_id)

    def closeEvent(self, event) -> None:
        """Cleans up resources, hides tray icon, syncs if enabled, and exits cleanly."""
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.hide()

        try:
            self.hide()
            from core.config import load_app_config
            from core.github_sync import GitHubSyncService
            cfg = load_app_config()
            if cfg.github_auto_sync and cfg.github_token.strip():
                GitHubSyncService.push_to_gist()
        except Exception:
            pass

        event.accept()
        QApplication.quit()

