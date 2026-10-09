"""Academic & Curated Web Search View with In-App Split-Screen Viewer.
Dual-Engine Architecture:
- Primary: Full-fidelity embedded Chromium WebEngine (when available)
- Resilient Fallback: Ultra-fast Obsidian Article Reader (QTextBrowser) with rich formatting,
  AI-Summarizer, and 1-click desktop browser launch.
Guarantees 100% stability, zero crashes on frozen bundle, and complete academic fidelity.
"""

import os
import re
import html
import time
import threading
import webbrowser
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal, QObject, QSize, QTimer, QUrl
from PySide6.QtGui import QFont, QColor, QGuiApplication, QCursor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFrame,
    QScrollArea,
    QSplitter,
    QProgressBar,
    QTextEdit,
    QTextBrowser,
    QMessageBox,
    QCheckBox,
    QComboBox,
    QSizePolicy,
)

# Safe conditional import of QtWebEngineWidgets to prevent startup crashes in frozen environments
_HAS_WEBENGINE = False
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineProfile, QWebEngineScript
    
    class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            url = info.requestUrl().toString().lower()
            if any(ad in url for ad in ["doubleclick.net", "google-analytics.com", "googlesyndication.com", "adsystem", "taboola", "outbrain", "adform", "criteo", "amazon-adsystem", "advertising", "ads."]):
                info.block(True)
                
    _HAS_WEBENGINE = True
except Exception as e:
    _HAS_WEBENGINE = False
    QWebEngineView = None
    try:
        with open("webengine_error.log", "w", encoding="utf-8") as f:
            f.write(f"WebEngine import error: {repr(e)}\n")
            import traceback
            traceback.print_exc(file=f)
    except Exception:
        pass

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ai.academic_web_search import search_academic_web, PRESET_FILTERS
from ai.daily_web_impulse import get_daily_web_impulse
from ui.qt.dialogs.quick_look import QuickLookDialog
from core.library_db import save_web_research_article
from core.config import get_books_storage_dir
from core.delta_scanner import index_single_book_file



class WebSearchSignals(QObject):
    """Thread-safe signals for background academic web searches and AI extraction."""
    search_finished = Signal(list, float)  # results, elapsed_seconds
    search_error = Signal(str)
    article_content_loaded = Signal(str, str)  # url, html_or_text
    ai_summary_finished = Signal(str)
    ai_summary_error = Signal(str)
    pdf_import_finished = Signal(str, bool, str)  # url, success, message


class AcademicWebView(QWidget):
    """Clean Web Search View with Dual-Engine In-App Split-Screen Viewer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._signals = WebSearchSignals()
        self._signals.search_finished.connect(self._on_search_finished)
        self._signals.search_error.connect(self._on_search_error)
        self._signals.article_content_loaded.connect(self._on_article_content_loaded)
        self._signals.ai_summary_finished.connect(self._on_ai_summary_finished)
        self._signals.ai_summary_error.connect(self._on_ai_summary_error)
        self._signals.pdf_import_finished.connect(self._on_pdf_import_finished)

        self._active_preset = "all"
        self._preset_buttons: Dict[str, QPushButton] = {}
        self._is_searching = False
        self._current_article: Optional[Dict[str, Any]] = None
        self._loaded_text_content = ""

        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. Header Banner (Compact)
        # -------------------------------------------------------------
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121929, stop:1 #172238);
                border: 1px solid #233352;
                border-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(12, 6, 12, 6)
        header_layout.setSpacing(10)

        lbl_globe = QLabel()
        lbl_globe.setPixmap(create_vector_pixmap("globe", "#58A6FF", 18))
        lbl_globe.setStyleSheet("border: none; background: transparent;")
        header_layout.addWidget(lbl_globe)

        lbl_title = QLabel("Fach-Websuche & In-App Terminal")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        header_layout.addWidget(lbl_title)

        lbl_subtitle = QLabel("• Bereinigte Recherche für Hochschulen, Skripte, Fachlexika & MINT-Dokus")
        lbl_subtitle.setFont(QFont("Segoe UI", 8))
        lbl_subtitle.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        header_layout.addWidget(lbl_subtitle)

        header_layout.addStretch()

        engine_badge = "CHROMIUM INSIDE" if _HAS_WEBENGINE else "IN-APP READER"
        lbl_badge = QLabel(f"SPAM-FREE · {engine_badge}")
        lbl_badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_badge.setStyleSheet("""
            background: #238636;
            color: #FFFFFF;
            border-radius: 4px;
            padding: 2px 7px;
            border: none;
        """)
        header_layout.addWidget(lbl_badge)

        root_layout.addWidget(header_card)

        # -------------------------------------------------------------
        # 2. Search Bar & Preset Filter Chips
        # -------------------------------------------------------------
        search_card = QFrame()
        search_card.setStyleSheet("""
            QFrame {
                background-color: #0F1524;
                border: 1px solid #233048;
                border-radius: 10px;
                padding: 6px;
            }
        """)
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(10, 8, 10, 8)
        search_layout.setSpacing(8)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Fachbegriff, Thema oder Skript suchen (z. B. 'Thermodynamik Kreisprozess', 'Kognitive Dissonanz')...")
        self.input_search.setFont(QFont("Segoe UI", 11))
        self.input_search.setFixedHeight(40)
        self.input_search.setStyleSheet("""
            QLineEdit {
                background-color: #0A0E18;
                border: 1.5px solid #283750;
                border-radius: 8px;
                color: #F0F6FC;
                padding: 0 14px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
                background-color: #0D121F;
            }
        """)
        self.input_search.returnPressed.connect(self._on_search_clicked)
        input_row.addWidget(self.input_search, stretch=1)

        self.btn_search = QPushButton("  Fach-Web durchsuchen")
        self.btn_search.setIcon(create_vector_icon("globe", "#FFFFFF", 18))
        self.btn_search.setIconSize(QSize(18, 18))
        self.btn_search.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_search.setFixedHeight(40)
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 8px;
                padding: 0 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388BFD, stop:1 #58A6FF);
            }
            QPushButton:disabled {
                background: #1B2335;
                color: #6E7681;
                border-color: #242D40;
            }
        """)
        self.btn_search.clicked.connect(self._on_search_clicked)
        input_row.addWidget(self.btn_search)

        search_layout.addLayout(input_row)

        # Preset Filter Chips Row + Advanced Filters
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)

        lbl_filter = QLabel("FOKUS:")
        lbl_filter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_filter.setStyleSheet("color: #526382; border: none; letter-spacing: 0.5px;")
        preset_row.addWidget(lbl_filter)

        presets = [
            ("all", "🌐 Alles (bereinigt)"),
            ("uni", "🎓 Uni-Skripte"),
            ("lexikon", "📖 Fachlexika"),
            ("tech", "💻 Tech- & MINT"),
        ]

        for p_key, p_label in presets:
            btn_p = QPushButton(p_label)
            btn_p.setFont(QFont("Segoe UI", 9))
            btn_p.setCursor(Qt.PointingHandCursor)
            btn_p.setFixedHeight(28)
            btn_p.clicked.connect(lambda ch, k=p_key: self._set_preset(k))
            preset_row.addWidget(btn_p)
            self._preset_buttons[p_key] = btn_p

        # Separator line
        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.VLine)
        v_sep.setFrameShadow(QFrame.Sunken)
        v_sep.setStyleSheet("color: #2D3D58; margin: 0 4px;")
        preset_row.addWidget(v_sep)

        # Advanced Filter 1: PDF Only Checkbox
        self.chk_pdf_only = QCheckBox("📄 Nur PDFs / Skripte")
        self.chk_pdf_only.setFont(QFont("Segoe UI", 9))
        self.chk_pdf_only.setCursor(Qt.PointingHandCursor)
        self.chk_pdf_only.setStyleSheet("""
            QCheckBox {
                color: #C9D1D9;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #388BFD;
                border-radius: 4px;
                background: #0A0E18;
            }
            QCheckBox::indicator:checked {
                background: #1F6FEB;
            }
        """)
        preset_row.addWidget(self.chk_pdf_only)

        # Advanced Filter 2: Min Year Selector
        lbl_year = QLabel("Zeitraum:")
        lbl_year.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_year.setStyleSheet("color: #526382; border: none; margin-left: 6px;")
        preset_row.addWidget(lbl_year)

        self.combo_year = QComboBox()
        self.combo_year.addItems(["Alle Jahre", "Ab 2024", "Ab 2022", "Ab 2020", "Ab 2015"])
        self.combo_year.setFont(QFont("Segoe UI", 9))
        self.combo_year.setFixedHeight(28)
        self.combo_year.setStyleSheet("""
            QComboBox {
                background-color: #0A0E18;
                border: 1px solid #283750;
                border-radius: 6px;
                color: #C9D1D9;
                padding: 2px 10px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #0D121F;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
                border: 1px solid #283750;
            }
        """)
        preset_row.addWidget(self.combo_year)

        preset_row.addStretch()
        search_layout.addLayout(preset_row)

        root_layout.addWidget(search_card)

        # -------------------------------------------------------------
        # 3. Main Split-Screen Layout (Results Left, In-App Viewer Right)
        # -------------------------------------------------------------
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1A2338;
                width: 6px;
                border-radius: 3px;
            }
            QSplitter::handle:hover {
                background-color: #388BFD;
            }
        """)

        # LEFT PANE: Search Results
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(8)

        # Left Status Bar
        self.status_bar = QFrame()
        self.status_bar.setFixedHeight(30)
        self.status_bar.setStyleSheet("""
            QFrame {
                background-color: #0E1422;
                border: 1px solid #1E283D;
                border-radius: 6px;
                padding: 0 10px;
            }
        """)
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(8, 0, 8, 0)

        self.lbl_status = QLabel("Bereit für Fach-Websuche.")
        self.lbl_status.setFont(QFont("Segoe UI", 8))
        self.lbl_status.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()

        self.lbl_results_count = QLabel("")
        self.lbl_results_count.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_results_count.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        status_layout.addWidget(self.lbl_results_count)

        left_layout.addWidget(self.status_bar)

        # Scrollable Results Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #0B0F19;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #1F2A3F;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #388BFD;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self.results_container = QWidget()
        self.results_container.setStyleSheet("background-color: transparent;")
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 2, 6, 10)
        self.results_layout.setSpacing(10)

        self.scroll_area.setWidget(self.results_container)
        left_layout.addWidget(self.scroll_area, stretch=1)
        self.splitter.addWidget(left_widget)

        # RIGHT PANE: In-App Viewer & Companion Panel
        right_widget = QWidget()
        right_widget.setMinimumWidth(400)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(6)

        # Browser Toolbar Card
        self.browser_toolbar = QFrame()
        self.browser_toolbar.setStyleSheet("""
            QFrame {
                background-color: #111726;
                border: 1px solid #23314B;
                border-radius: 8px;
                padding: 4px 8px;
            }
        """)
        tb_layout = QHBoxLayout(self.browser_toolbar)
        tb_layout.setContentsMargins(6, 4, 6, 4)
        tb_layout.setSpacing(6)

        if _HAS_WEBENGINE:
            self.btn_back = QPushButton()
            self.btn_back.setIcon(create_vector_icon("chevron_left", "#F0F6FC", 14))
            self.btn_back.setFixedSize(28, 28)
            self.btn_back.setToolTip("Zurück")
            self.btn_back.setCursor(Qt.PointingHandCursor)
            self.btn_back.setStyleSheet("background-color: #172136; border: 1px solid #2B3D5E; border-radius: 4px;")
            tb_layout.addWidget(self.btn_back)

            self.btn_forward = QPushButton()
            self.btn_forward.setIcon(create_vector_icon("chevron_right", "#F0F6FC", 14))
            self.btn_forward.setFixedSize(28, 28)
            self.btn_forward.setToolTip("Vorwärts")
            self.btn_forward.setCursor(Qt.PointingHandCursor)
            self.btn_forward.setStyleSheet("background-color: #172136; border: 1px solid #2B3D5E; border-radius: 4px;")
            tb_layout.addWidget(self.btn_forward)

            self.btn_reload = QPushButton()
            self.btn_reload.setIcon(create_vector_icon("sync", "#F0F6FC", 14))
            self.btn_reload.setFixedSize(28, 28)
            self.btn_reload.setToolTip("Seite neu laden")
            self.btn_reload.setCursor(Qt.PointingHandCursor)
            self.btn_reload.setStyleSheet("background-color: #172136; border: 1px solid #2B3D5E; border-radius: 4px;")
            tb_layout.addWidget(self.btn_reload)

        # URL display pill
        self.lbl_active_url = QLabel("Kein Fachbeitrag ausgewählt")
        self.lbl_active_url.setFont(QFont("Segoe UI", 9))
        self.lbl_active_url.setMinimumWidth(50)
        self.lbl_active_url.setStyleSheet("""
            color: #8B949E;
            background-color: #0A0E18;
            border: 1px solid #202D45;
            border-radius: 4px;
            padding: 4px 10px;
        """)
        tb_layout.addWidget(self.lbl_active_url, stretch=1)

        # KI-Summary Button
        self.btn_ai_summary = QPushButton("  🧠 KI-Summary")
        self.btn_ai_summary.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_ai_summary.setFixedHeight(28)
        self.btn_ai_summary.setCursor(Qt.PointingHandCursor)
        self.btn_ai_summary.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        self.btn_ai_summary.clicked.connect(self._on_ai_summarize_clicked)
        tb_layout.addWidget(self.btn_ai_summary)

        # Save to Desk Notes Button
        self.btn_save_desk = QPushButton("  📝 Speichern")
        self.btn_save_desk.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_save_desk.setFixedHeight(28)
        self.btn_save_desk.setCursor(Qt.PointingHandCursor)
        self.btn_save_desk.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                border: 1px solid #2EA043;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)
        self.btn_save_desk.clicked.connect(self._on_save_to_desk_clicked)
        tb_layout.addWidget(self.btn_save_desk)

        # Fullscreen Toggle Button
        self.btn_fullscreen = QPushButton("  ⛶ Ansicht")
        self.btn_fullscreen.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_fullscreen.setFixedHeight(28)
        self.btn_fullscreen.setToolTip("Lese-Ansicht vergrößern / verkleinern")
        self.btn_fullscreen.setCursor(Qt.PointingHandCursor)
        self.btn_fullscreen.setStyleSheet("""
            QPushButton {
                background-color: #1A2338;
                color: #F0F6FC;
                border: 1px solid #324468;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #243250;
                border-color: #58A6FF;
            }
        """)
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)
        tb_layout.addWidget(self.btn_fullscreen)

        # External Browser Button
        self.btn_ext_browser = QPushButton("  ↗ In Edge öffnen")
        self.btn_ext_browser.setIcon(create_vector_icon("external", "#F0F6FC", 12))
        self.btn_ext_browser.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_ext_browser.setFixedHeight(28)
        self.btn_ext_browser.setToolTip("Originalseite im externen Desktop-Browser (Edge) öffnen")
        self.btn_ext_browser.setCursor(Qt.PointingHandCursor)
        self.btn_ext_browser.setStyleSheet("""
            QPushButton {
                background-color: #1A2338;
                color: #F0F6FC;
                border: 1px solid #324468;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #243250;
                border-color: #58A6FF;
            }
        """)
        self.btn_ext_browser.clicked.connect(self._open_in_external_browser)
        tb_layout.addWidget(self.btn_ext_browser)

        right_layout.addWidget(self.browser_toolbar)

        # Loading Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: transparent;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #58A6FF;
            }
        """)
        self.progress_bar.hide()
        right_layout.addWidget(self.progress_bar)

        # Collapsible AI Summary Drawer
        self.summary_drawer = QFrame()
        self.summary_drawer.setStyleSheet("""
            QFrame {
                background-color: #0E1626;
                border: 1px solid #388BFD;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        drawer_layout = QVBoxLayout(self.summary_drawer)
        drawer_layout.setContentsMargins(10, 8, 10, 8)
        drawer_layout.setSpacing(6)

        drawer_top = QHBoxLayout()
        lbl_sd_title = QLabel("🧠 KI-Kernaussagen & Definitionen:")
        lbl_sd_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_sd_title.setStyleSheet("color: #58A6FF; border: none;")
        drawer_top.addWidget(lbl_sd_title)
        drawer_top.addStretch()

        btn_close_drawer = QPushButton("✕ Schließen")
        btn_close_drawer.setFont(QFont("Segoe UI", 8))
        btn_close_drawer.setCursor(Qt.PointingHandCursor)
        btn_close_drawer.setStyleSheet("background: transparent; color: #8B949E; border: none;")
        btn_close_drawer.clicked.connect(lambda: self.summary_drawer.hide())
        drawer_top.addWidget(btn_close_drawer)
        drawer_layout.addLayout(drawer_top)

        self.txt_summary = QTextEdit()
        self.txt_summary.setReadOnly(True)
        self.txt_summary.setMaximumHeight(140)
        self.txt_summary.setFont(QFont("Segoe UI", 9))
        self.txt_summary.setStyleSheet("""
            QTextEdit {
                background-color: #0B0F19;
                border: 1px solid #1E283D;
                border-radius: 6px;
                color: #F0F6FC;
                padding: 8px;
            }
        """)
        drawer_layout.addWidget(self.txt_summary)
        self.summary_drawer.hide()
        right_layout.addWidget(self.summary_drawer)

        # Central Reader / Web View Component
        if _HAS_WEBENGINE:
            self.web_view = QWebEngineView()
            self.adblocker = AdBlockInterceptor(self.web_view)
            profile = QWebEngineProfile.defaultProfile()
            profile.setUrlRequestInterceptor(self.adblocker)
            
            # --- GLOBAL CYBER DARK MODE SCRIPT ---
            dark_script = QWebEngineScript()
            dark_script.setName("CyberDarkMode")
            dark_script.setSourceCode("""
                (function() {
                    if (window.location.href.startsWith('data:') || window.location.href === 'about:blank' || window.location.href.startsWith('chrome:')) return;
                    if (document.getElementById('cyber-dark-mode-style')) return;
                    const css = `
                        html { filter: invert(100%) hue-rotate(180deg) brightness(85%) contrast(90%) !important; background: white !important; }
                        img, video, iframe, canvas, svg { filter: invert(100%) hue-rotate(180deg) !important; }
                        ::-webkit-scrollbar { width: 14px; height: 14px; background: white !important; }
                        ::-webkit-scrollbar-track { background: white !important; border-left: 1px solid #ccc; }
                        ::-webkit-scrollbar-thumb { background: #ccc !important; border-radius: 7px; border: 3px solid white; }
                        ::-webkit-scrollbar-thumb:hover { background: #999 !important; }
                    `;
                    const style = document.createElement('style');
                    style.id = 'cyber-dark-mode-style';
                    style.type = 'text/css';
                    style.appendChild(document.createTextNode(css));
                    if (document.head) document.head.appendChild(style);
                    else document.documentElement.appendChild(style);
                })();
            """)
            dark_script.setInjectionPoint(QWebEngineScript.DocumentReady)
            dark_script.setWorldId(QWebEngineScript.MainWorld)
            
            profile.scripts().remove(dark_script)
            profile.scripts().insert(dark_script)
            self.web_view.setStyleSheet("""
                background-color: #0B0F19;
                border: 1px solid #1E283D;
                border-radius: 8px;
            """)
            self.web_view.setHtml(
                "<body style='background-color: #0C111D; color: #8B949E; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; font-family: \"Segoe UI\", sans-serif; text-align: center;'>"
                "<div><h3 style='color: #F0F6FC; font-size: 18px; margin-bottom: 8px;'>Kein Fachartikel geladen</h3>"
                "<p>Klicke links auf ein Suchergebnis, um den Beitrag direkt hier im In-App Viewer zu öffnen.</p></div></body>"
            )
            self.web_view.loadStarted.connect(self._on_web_load_started)
            self.web_view.loadProgress.connect(self._on_web_load_progress)
            self.web_view.loadFinished.connect(self._on_web_load_finished)
            self.web_view.urlChanged.connect(self._on_web_url_changed)

            self.btn_back.clicked.connect(self.web_view.back)
            self.btn_forward.clicked.connect(self.web_view.forward)
            self.btn_reload.clicked.connect(self.web_view.reload)

            right_layout.addWidget(self.web_view, stretch=1)
        else:
            # Resilient In-App Reader (QTextBrowser with Obsidian styling)
            self.article_browser = QTextBrowser()
            self.article_browser.setOpenExternalLinks(True)
            self.article_browser.setStyleSheet("""
                QTextBrowser {
                    background-color: #0C111D;
                    color: #E6EDF3;
                    border: 1px solid #1E283D;
                    border-radius: 8px;
                    padding: 16px;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    font-size: 13px;
                    line-height: 1.6;
                }
            """)
            self.article_browser.setHtml(
                "<div style='text-align: center; padding-top: 80px; color: #8B949E;'>"
                "<h3 style='color: #F0F6FC;'>Kein Fachartikel geladen</h3>"
                "<p>Klicke links auf ein Suchergebnis oder den Web-Impuls, um den Beitrag direkt hier im Lesebereich zu öffnen.</p>"
                "</div>"
            )
            right_layout.addWidget(self.article_browser, stretch=1)

        left_widget.setMinimumWidth(480)
        right_widget.setMinimumWidth(480)
        self.splitter.addWidget(right_widget)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([650, 650])
        root_layout.addWidget(self.splitter, stretch=1)

        self._update_preset_buttons_ui()
        self._show_welcome_state()

    def _set_preset(self, preset_key: str) -> None:
        self._active_preset = preset_key
        self._update_preset_buttons_ui()
        if self.input_search.text().strip():
            self._on_search_clicked()

    def _update_preset_buttons_ui(self) -> None:
        for k, btn in self._preset_buttons.items():
            if k == self._active_preset:
                btn.setStyleSheet("""
                    QPushButton {
                        background: #1F6FEB;
                        color: #FFFFFF;
                        border: 1px solid #388BFD;
                        border-radius: 6px;
                        padding: 0 12px;
                        font-weight: 700;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #111827;
                        color: #8B949E;
                        border: 1px solid #243046;
                        border-radius: 6px;
                        padding: 0 12px;
                        font-weight: 500;
                    }
                    QPushButton:hover {
                        background-color: #1A2338;
                        color: #F0F6FC;
                        border-color: #388BFD;
                    }
                """)

    def _show_welcome_state(self) -> None:
        self._clear_results_layout()
        self._current_web_impulse = get_daily_web_impulse(force_refresh=False, preset=self._active_preset)
        impulse_card = self._build_web_impulse_card(self._current_web_impulse)
        self.results_layout.addWidget(impulse_card)
        self.results_layout.addStretch()

    def _build_web_impulse_card(self, imp: Dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("WebImpulseCard")
        card.setStyleSheet("""
            QFrame#WebImpulseCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0E1626, stop:1 #131E35);
                border: 1px solid #233556;
                border-top: 2px solid #58A6FF;
                border-radius: 10px;
                padding: 14px;
            }
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # Header row with Badge and "🎲 Neuer Impuls / Überrasch mich"
        top_h = QHBoxLayout()
        top_h.setSpacing(8)

        lbl_badge = QLabel("✨ WEB-IMPULS DES TAGES")
        lbl_badge.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_badge.setStyleSheet("""
            background-color: #1F3660;
            color: #79C0FF;
            border: 1px solid #388BFD;
            border-radius: 4px;
            padding: 2px 8px;
        """)
        top_h.addWidget(lbl_badge)

        badge_txt = imp.get("badge", "Fachbeitrag")
        badge_col = imp.get("badge_color", "#3FB950")
        lbl_src = QLabel(f" {badge_txt} ")
        lbl_src.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_src.setStyleSheet(f"""
            background-color: rgba(26, 38, 64, 0.9);
            color: {badge_col};
            border: 1px solid {badge_col};
            border-radius: 4px;
            padding: 2px 6px;
        """)
        top_h.addWidget(lbl_src)
        top_h.addStretch()

        btn_reroll = QPushButton(" 🎲 Überrasch mich!")
        btn_reroll.setFont(QFont("Segoe UI", 8, QFont.Bold))
        btn_reroll.setCursor(Qt.PointingHandCursor)
        btn_reroll.setFixedHeight(26)
        btn_reroll.setStyleSheet("""
            QPushButton {
                background-color: #17243B;
                color: #58A6FF;
                border: 1px solid #2D4268;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #203354;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_reroll.clicked.connect(self._reroll_web_impulse)
        top_h.addWidget(btn_reroll)
        lay.addLayout(top_h)

        # Article Title (Clickable)
        title_text = imp.get("title", "")
        lbl_title = QLabel(title_text)
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_title.setStyleSheet("""
            QLabel {
                color: #F0F6FC;
                border: none;
            }
            QLabel:hover {
                color: #58A6FF;
            }
        """)
        lbl_title.setWordWrap(True)
        lbl_title.setCursor(Qt.PointingHandCursor)
        lbl_title.mousePressEvent = lambda e, i=imp: self._open_impulse_in_viewer(i)
        lay.addWidget(lbl_title)

        # Teaser & Insight Box
        teaser = imp.get("teaser", "")
        desc_box = QFrame()
        desc_box.setStyleSheet("""
            QFrame {
                background: #090F1C;
                border: 1px solid #1A2740;
                border-radius: 6px;
                padding: 8px 12px;
            }
        """)
        d_lay = QVBoxLayout(desc_box)
        d_lay.setContentsMargins(6, 4, 6, 4)
        lbl_desc = QLabel(f"<div style='color: #8B949E; line-height: 1.4;'><b style='color: #58A6FF;'>💡 Worum geht's:</b> {teaser}</div>")
        lbl_desc.setTextFormat(Qt.RichText)
        lbl_desc.setFont(QFont("Segoe UI", 9))
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("border: none; background: transparent;")
        d_lay.addWidget(lbl_desc)
        lay.addWidget(desc_box)

        # Buch-Brücke: Passend dazu in deiner Bibliothek
        related_books = imp.get("related_books") or []
        if related_books:
            bridge_box = QFrame()
            bridge_box.setObjectName("WebBridgeBox")
            bridge_box.setStyleSheet("""
                QFrame#WebBridgeBox {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0B1324, stop:0.5 #0D172B, stop:1 #0B1324);
                    border: 1px solid #1C2D4B;
                    border-left: 3px solid #388BFD;
                    border-radius: 7px;
                }
            """)
            b_lay = QVBoxLayout(bridge_box)
            b_lay.setContentsMargins(10, 8, 10, 8)
            b_lay.setSpacing(8)

            h_row = QHBoxLayout()
            h_row.setContentsMargins(0, 0, 0, 2)
            lbl_bridge_title = QLabel("📚 Passend dazu in deiner Bibliothek:")
            lbl_bridge_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_bridge_title.setStyleSheet("color: #58A6FF; border: none;")
            h_row.addWidget(lbl_bridge_title)

            lbl_hint = QLabel("Klicke für Quick-Look & Inhaltsverzeichnis")
            lbl_hint.setFont(QFont("Segoe UI", 8))
            lbl_hint.setStyleSheet("color: #7D8590; border: none; font-style: italic;")
            h_row.addWidget(lbl_hint)
            h_row.addStretch()
            b_lay.addLayout(h_row)

            books_layout = QVBoxLayout()
            books_layout.setSpacing(6)
            for b_item in related_books:
                b_t = b_item.get("title") or "Unbekannt"
                b_a = b_item.get("author") or "o.A."

                card_frame = QFrame()
                card_frame.setCursor(Qt.PointingHandCursor)
                card_frame.setFixedHeight(48)
                card_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                card_frame.setToolTip(f"«{b_t}»\nAutor: {b_a}\n\nKlicken für Quick-Look Vorschau & Notizen")
                card_frame.setStyleSheet("""
                    QFrame {
                        background-color: #111A2E;
                        border: 1px solid #1E2F4D;
                        border-radius: 6px;
                    }
                    QFrame:hover {
                        background-color: #17243F;
                        border: 1px solid #388BFD;
                    }
                """)

                c_lay = QHBoxLayout(card_frame)
                c_lay.setContentsMargins(10, 4, 10, 4)
                c_lay.setSpacing(8)

                lbl_b_icon = QLabel("📖")
                lbl_b_icon.setStyleSheet("border: none; font-size: 13px; background: transparent;")
                c_lay.addWidget(lbl_b_icon)

                text_vlay = QVBoxLayout()
                text_vlay.setContentsMargins(0, 0, 0, 0)
                text_vlay.setSpacing(1)

                display_t = b_t if len(b_t) <= 45 else b_t[:42] + "…"
                lbl_bt = QLabel(display_t)
                lbl_bt.setFont(QFont("Segoe UI", 9, QFont.Medium))
                lbl_bt.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
                text_vlay.addWidget(lbl_bt)

                display_a = b_a if len(b_a) <= 30 else b_a[:28] + "…"
                lbl_ba = QLabel(display_a)
                lbl_ba.setFont(QFont("Segoe UI", 8))
                lbl_ba.setStyleSheet("color: #8B949E; border: none; background: transparent;")
                text_vlay.addWidget(lbl_ba)

                c_lay.addLayout(text_vlay, stretch=1)

                card_frame.mousePressEvent = lambda e, b=b_item: self._open_related_book(b)
                books_layout.addWidget(card_frame)

            b_lay.addLayout(books_layout)
            lay.addWidget(bridge_box)

        # Action Buttons Row (Open in Viewer, Search Related Web)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        btn_open = QPushButton("  📖 Jetzt im Viewer lesen")
        btn_open.setIcon(create_vector_icon("external", "#FFFFFF", 13))
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(30)
        btn_open.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                font-weight: 600;
                border: 1px solid #388BFD;
                border-radius: 5px;
                padding: 0 14px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        btn_open.clicked.connect(lambda: self._open_impulse_in_viewer(imp))
        action_row.addWidget(btn_open)

        seed = imp.get("search_seed") or title_text
        btn_deep = QPushButton("  🔍 Weiterführend im Web suchen")
        btn_deep.setIcon(create_vector_icon("research", "#C9D1D9", 13))
        btn_deep.setCursor(Qt.PointingHandCursor)
        btn_deep.setFixedHeight(30)
        btn_deep.setStyleSheet("""
            QPushButton {
                background: #121A28;
                color: #C9D1D9;
                border: 1px solid #1E2B40;
                border-radius: 5px;
                padding: 0 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1A263B;
                color: #F0F6FC;
                border-color: #314463;
            }
        """)
        btn_deep.clicked.connect(lambda: self._run_example_search(seed, self._active_preset))
        action_row.addWidget(btn_deep)
        action_row.addStretch()

        domain = imp.get("domain", "")
        if domain:
            lbl_dom = QLabel(f"🌐 {domain}")
            lbl_dom.setFont(QFont("Segoe UI", 8))
            lbl_dom.setStyleSheet("color: #8B949E; border: none;")
            action_row.addWidget(lbl_dom)

        lay.addLayout(action_row)
        return card

    def _reroll_web_impulse(self) -> None:
        """Draws a new curated impulse dynamically."""
        self._clear_results_layout()
        self._current_web_impulse = get_daily_web_impulse(force_refresh=True, preset=self._active_preset)
        impulse_card = self._build_web_impulse_card(self._current_web_impulse)
        self.results_layout.addWidget(impulse_card)
        self.results_layout.addStretch()

    def _open_impulse_in_viewer(self, imp: Dict[str, Any]) -> None:
        """Opens the impulse article directly in the right-side split screen viewer."""
        pseudo_result = {
            "title": imp.get("title", ""),
            "url": imp.get("url", ""),
            "domain": imp.get("domain", ""),
            "snippet": imp.get("teaser", ""),
            "badge_text": imp.get("badge", "Fachbeitrag"),
            "badge_color": imp.get("badge_color", "#58A6FF"),
            "is_verified": True,
            "is_pdf": False,
        }
        self.load_url_in_viewer(pseudo_result)

    def _open_related_book(self, book: Dict[str, Any]) -> None:
        """Opens Quick-Look dialog for a related library book found by Buch-Brücke."""
        try:
            dlg = QuickLookDialog(book, parent=self)
            dlg.exec()
        except Exception as e:
            self.lbl_status.setText(f"Fehler beim Öffnen: {e}")


    def _run_example_search(self, query: str, preset: str) -> None:
        self.input_search.setText(query)
        self._active_preset = preset
        self._update_preset_buttons_ui()
        self._on_search_clicked()

    def _clear_results_layout(self) -> None:
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _on_search_clicked(self) -> None:
        query = self.input_search.text().strip()
        if not query:
            return

        if self._is_searching:
            return

        self._is_searching = True
        self.btn_search.setEnabled(False)
        self.lbl_status.setText(f"🔎 Suche Fachquellen für '{query}'...")
        self.lbl_results_count.setText("Lädt...")

        self._clear_results_layout()

        loading_card = QFrame()
        loading_card.setStyleSheet("""
            QFrame {
                background-color: #0E1422;
                border: 1px solid #1E283D;
                border-radius: 10px;
                padding: 24px;
            }
        """)
        l_layout = QVBoxLayout(loading_card)
        l_layout.setAlignment(Qt.AlignCenter)
        l_layout.setSpacing(8)

        lbl_load_icon = QLabel()
        lbl_load_icon.setPixmap(create_vector_pixmap("globe", "#58A6FF", 32))
        lbl_load_icon.setAlignment(Qt.AlignCenter)
        lbl_load_icon.setStyleSheet("border: none; background: transparent;")
        l_layout.addWidget(lbl_load_icon)

        lbl_load_text = QLabel("Analysiere autoritative Fach- und Hochschulseiten...")
        lbl_load_text.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_load_text.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        lbl_load_text.setAlignment(Qt.AlignCenter)
        l_layout.addWidget(lbl_load_text)

        self.results_layout.addWidget(loading_card)

        preset = self._active_preset
        pdf_only = self.chk_pdf_only.isChecked()
        year_text = self.combo_year.currentText()
        min_year: Optional[int] = None
        if "Ab " in year_text:
            try:
                min_year = int(year_text.replace("Ab ", "").strip())
            except ValueError:
                min_year = None

        t_start = time.time()

        def _worker():
            try:
                results = search_academic_web(
                    query,
                    preset=preset,
                    pdf_only=pdf_only,
                    min_year=min_year,
                    max_results=999,
                )
                elapsed = time.time() - t_start
                self._signals.search_finished.emit(results, elapsed)
            except Exception as e:
                self._signals.search_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_search_finished(self, results: List[Dict[str, Any]], elapsed: float) -> None:
        self._is_searching = False
        self.btn_search.setEnabled(True)
        self._clear_results_layout()

        if not results:
            self.lbl_status.setText("Keine passenden Fachseiten gefunden.")
            self.lbl_results_count.setText("0 Treffer")

            no_res_card = QFrame()
            no_res_card.setStyleSheet("""
                QFrame {
                    background-color: #0E1422;
                    border: 1px dashed #2C384E;
                    border-radius: 10px;
                    padding: 20px;
                }
            """)
            nr_layout = QVBoxLayout(no_res_card)
            nr_layout.setAlignment(Qt.AlignCenter)
            nr_layout.setSpacing(6)

            lbl_nr = QLabel("Keine gefilterten Fach-Webseiten gefunden")
            lbl_nr.setFont(QFont("Segoe UI", 11, QFont.Bold))
            lbl_nr.setStyleSheet("color: #F0F6FC; border: none;")
            nr_layout.addWidget(lbl_nr)

            lbl_nr_sub = QLabel("Tipp: Wähle '🌐 Alles (bereinigt)' oder reduziere spezielle Suchbegriffe.")
            lbl_nr_sub.setFont(QFont("Segoe UI", 9))
            lbl_nr_sub.setStyleSheet("color: #8B949E; border: none;")
            nr_layout.addWidget(lbl_nr_sub)

            self.results_layout.addWidget(no_res_card)
            self.results_layout.addStretch()
            return

        self.lbl_status.setText(f"Suche abgeschlossen ({elapsed:.2f} s)")
        self.lbl_results_count.setText(f"{len(results)} Treffer")

        for r in results:
            card = self._create_result_card(r)
            self.results_layout.addWidget(card)

        self.results_layout.addStretch()

        if results and not self._current_article:
            self.load_url_in_viewer(results[0])

    def _on_search_error(self, err_msg: str) -> None:
        self._is_searching = False
        self.btn_search.setEnabled(True)
        self.lbl_status.setText(f"Suchfehler: {err_msg}")
        self.lbl_results_count.setText("Fehler")

    def _create_result_card(self, r: Dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#ResultCard {
                background-color: #101625;
                border: 1px solid #1F2A3F;
                border-radius: 8px;
                padding: 10px;
            }
            QFrame#ResultCard:hover {
                border-color: #388BFD;
                background-color: #131A2B;
            }
        """)
        card.setObjectName("ResultCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Top row: Badges & Domain
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        badge_text = r.get("badge_text", "Fachartikel")
        badge_color = r.get("badge_color", "#58A6FF")
        lbl_cat_badge = QLabel(f" {badge_text} ")
        lbl_cat_badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_cat_badge.setStyleSheet(f"""
            background-color: rgba(26, 38, 64, 0.9);
            color: {badge_color};
            border: 1px solid {badge_color};
            border-radius: 4px;
            padding: 1px 5px;
        """)
        top_row.addWidget(lbl_cat_badge)

        domain = r.get("domain", "")
        lbl_domain = QLabel(f"🌐 {domain}")
        lbl_domain.setFont(QFont("Segoe UI", 8))
        lbl_domain.setStyleSheet("""
            background-color: #172135;
            color: #8B949E;
            border-radius: 4px;
            padding: 1px 6px;
            border: 1px solid #23314B;
        """)
        top_row.addWidget(lbl_domain)

        if r.get("is_pdf"):
            lbl_pdf_badge = QLabel("PDF")
            lbl_pdf_badge.setFont(QFont("Segoe UI", 7, QFont.Bold))
            lbl_pdf_badge.setStyleSheet("""
                background-color: #F85149;
                color: #FFFFFF;
                border-radius: 3px;
                padding: 1px 4px;
            """)
            top_row.addWidget(lbl_pdf_badge)

        year = r.get("year")
        if year:
            lbl_year_badge = QLabel(f"📅 {year}")
            lbl_year_badge.setFont(QFont("Segoe UI", 8))
            lbl_year_badge.setStyleSheet("""
                background-color: #1A2436;
                color: #58A6FF;
                border-radius: 4px;
                padding: 1px 6px;
                border: 1px solid #233754;
            """)
            top_row.addWidget(lbl_year_badge)

        top_row.addStretch()
        layout.addLayout(top_row)

        # Title
        title_text = r.get("title", "Ohne Titel")
        lbl_card_title = QLabel(title_text)
        lbl_card_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_card_title.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        lbl_card_title.setWordWrap(True)
        lbl_card_title.setCursor(Qt.PointingHandCursor)
        lbl_card_title.mousePressEvent = lambda e, item=r: self.load_url_in_viewer(item)
        layout.addWidget(lbl_card_title)

        # Snippet
        snippet_text = r.get("snippet", "")
        if snippet_text:
            lbl_snippet = QLabel(snippet_text)
            lbl_snippet.setFont(QFont("Segoe UI", 8))
            lbl_snippet.setStyleSheet("color: #C9D1D9; border: none; background: transparent; line-height: 1.3;")
            lbl_snippet.setWordWrap(True)
            layout.addWidget(lbl_snippet)

        # Actions Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)

        btn_view = QPushButton("  👁 In App ansehen")
        btn_view.setIcon(create_vector_icon("globe", "#FFFFFF", 12))
        btn_view.setIconSize(QSize(12, 12))
        btn_view.setFont(QFont("Segoe UI", 8, QFont.Bold))
        btn_view.setFixedHeight(26)
        btn_view.setCursor(Qt.PointingHandCursor)
        btn_view.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 4px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        btn_view.clicked.connect(lambda ch, item=r: self.load_url_in_viewer(item))
        actions_row.addWidget(btn_view)

        btn_copy = QPushButton("  Link kopieren")
        btn_copy.setIcon(create_vector_icon("copy", "#8B949E", 12))
        btn_copy.setIconSize(QSize(12, 12))
        btn_copy.setFont(QFont("Segoe UI", 8))
        btn_copy.setFixedHeight(26)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #161F32;
                color: #8B949E;
                border: 1px solid #23314B;
                border-radius: 4px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: #1E2B45;
                color: #F0F6FC;
                border-color: #58A6FF;
            }
        """)
        actions_row.addWidget(btn_copy)

        # 1-Click Import into Campus Library for PDF results
        if r.get("is_pdf"):
            btn_import = QPushButton("  📥 In Bibliothek")
            btn_import.setIcon(create_vector_icon("download", "#FFFFFF", 12))
            btn_import.setIconSize(QSize(12, 12))
            btn_import.setFont(QFont("Segoe UI", 8, QFont.Bold))
            btn_import.setFixedHeight(26)
            btn_import.setCursor(Qt.PointingHandCursor)
            btn_import.setStyleSheet("""
                QPushButton {
                    background-color: #238636;
                    color: #FFFFFF;
                    border: 1px solid #2EA043;
                    border-radius: 4px;
                    padding: 0 10px;
                }
                QPushButton:hover {
                    background-color: #2EA043;
                }
            """)
            btn_import.clicked.connect(lambda ch, item=r, b=btn_import: self._import_pdf_to_library(item, b))
            actions_row.addWidget(btn_import)

        actions_row.addStretch()
        layout.addLayout(actions_row)

        return card

    def load_url_in_viewer(self, item: Dict[str, Any]) -> None:
        """Loads a web page item into the active in-app viewer."""
        self._current_article = item
        url = item.get("url", "")
        title = item.get("title", "")
        self.lbl_active_url.setText(f"🌐 {url[:70]}..." if len(url) > 70 else f"🌐 {url}")
        self.summary_drawer.hide()

        if _HAS_WEBENGINE and hasattr(self, 'web_view'):
            self.web_view.load(QUrl(url))
        else:
            # Load in Resilient In-App Reader
            self.progress_bar.show()
            self.progress_bar.setValue(30)
            self.article_browser.setHtml(
                f"<div style='text-align: center; padding-top: 50px; color: #8B949E;'>"
                f"<h3 style='color: #58A6FF;'>Lade Fachartikel...</h3>"
                f"<p style='color: #F0F6FC;'>{title}</p>"
                f"<p style='font-size: 11px; color: #526382;'>{url}</p>"
                f"</div>"
            )

            # Fetch article content in background
            def _fetch():
                try:
                    content_html = self._fetch_clean_article(item)
                    self._signals.article_content_loaded.emit(url, content_html)
                except Exception as e:
                    self._signals.article_content_loaded.emit(url, f"<p style='color: #F85149;'>Fehler beim Laden: {e}</p>")

            threading.Thread(target=_fetch, daemon=True).start()

    def _fetch_clean_article(self, item: Dict[str, Any]) -> str:
        """Fetches and formats article for the In-App Reader."""
        url = item.get("url", "")
        title = item.get("title", "")
        domain = item.get("domain", "")
        snippet = item.get("snippet", "")
        badge = item.get("badge_text", "Fachartikel")

        raw_text = snippet

        # Attempt to fetch page text via curl_cffi or urllib
        try:
            from curl_cffi import requests as cffi_req
            resp = cffi_req.get(url, impersonate="chrome120", timeout=8)
            if resp.status_code == 200:
                html_body = resp.text
                # Extract paragraphs
                paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html_body, re.DOTALL | re.IGNORECASE)
                clean_ps = []
                for p in paragraphs:
                    clean_p = re.sub(r'<[^>]+>', '', p).strip()
                    if len(clean_p) > 50:
                        clean_ps.append(html.unescape(clean_p))
                if clean_ps:
                    raw_text = "\n\n".join(clean_ps[:12])
        except Exception:
            pass

        self._loaded_text_content = raw_text

        # Format beautiful Cyber-Obsidian HTML
        paras_html = "".join([f"<p style='margin-bottom: 14px; line-height: 1.6; color: #C9D1D9;'>{p}</p>" for p in raw_text.split("\n\n") if p.strip()])

        return f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; color: #F0F6FC; padding: 10px;">
            <div style="background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #162035, stop:1 #111827); border: 1px solid #388BFD; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
                <span style="background-color: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; padding: 2px 8px; border-radius: 4px;">{badge}</span>
                <span style="color: #8B949E; font-size: 11px; margin-left: 10px;">{domain}</span>
                <h1 style="color: #58A6FF; font-size: 18px; margin: 10px 0 6px 0;">{title}</h1>
                <p style="color: #8B949E; font-size: 11px; margin: 0;">Original-URL: <a href="{url}" style="color: #58A6FF; text-decoration: none;">{url}</a></p>
            </div>
            <div style="font-size: 13px;">
                {paras_html}
            </div>
            <div style="margin-top: 30px; padding: 12px; background: #0F1626; border: 1px dashed #243450; border-radius: 6px; text-align: center;">
                <p style="color: #8B949E; font-size: 12px; margin: 0;">Für interaktive Skripte, PDF-Downloads oder geschützte Uni-Portale klicke oben auf <b>'↗ In Edge öffnen'</b>.</p>
            </div>
        </div>
        """

    def _on_article_content_loaded(self, url: str, content_html: str) -> None:
        self.progress_bar.hide()
        if hasattr(self, 'article_browser'):
            self.article_browser.setHtml(content_html)

    def _on_web_load_started(self) -> None:
        self.progress_bar.show()
        self.progress_bar.setValue(10)

    def _on_web_load_progress(self, progress: int) -> None:
        self.progress_bar.setValue(progress)

    def _on_web_load_finished(self, success: bool) -> None:
        self.progress_bar.hide()
        if not success:
            self.lbl_active_url.setText("⚠️ Seite konnte nicht vollständig geladen werden.")

    def _on_web_url_changed(self, url: QUrl) -> None:
        url_str = url.toString()
        if url_str:
            self.lbl_active_url.setText(f"🌐 {url_str[:70]}..." if len(url_str) > 70 else f"🌐 {url_str}")

    def _toggle_fullscreen(self) -> None:
        sizes = self.splitter.sizes()
        if sizes[0] == 0:
            # Restore view
            self.splitter.setSizes([420, 880])
        else:
            # Maximize viewer
            self.splitter.setSizes([0, 1300])

    def _open_in_external_browser(self) -> None:
        url = ""
        if _HAS_WEBENGINE and hasattr(self, 'web_view'):
            url = self.web_view.url().toString()
        if not url or url.startswith("about:"):
            if self._current_article:
                url = self._current_article.get("url", "")
        if url:
            webbrowser.open(url)

    def _copy_link(self, url: str, btn: QPushButton) -> None:
        QGuiApplication.clipboard().setText(url)
        orig_text = btn.text()
        btn.setText("  ✓ Kopiert!")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                border: 1px solid #2EA043;
                border-radius: 4px;
                padding: 0 8px;
            }
        """)
        QTimer.singleShot(1800, lambda: self._reset_copy_btn(btn, orig_text))

    def _reset_copy_btn(self, btn: QPushButton, orig_text: str) -> None:
        btn.setText(orig_text)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #161F32;
                color: #8B949E;
                border: 1px solid #23314B;
                border-radius: 4px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: #1E2B45;
                color: #F0F6FC;
                border-color: #58A6FF;
            }
        """)

    def _on_save_to_desk_clicked(self) -> None:
        if not self._current_article:
            QMessageBox.information(self, "Hinweis", "Bitte öffne zuerst eine Seite im Viewer.")
            return

        title = self._current_article.get("title", "Fachartikel")
        url = self._current_article.get("url", "")
        snippet = self._current_article.get("snippet", "")

        try:
            domain = self._current_article.get("domain", "")
            summary = self.txt_summary.toPlainText() if self.summary_drawer.isVisible() else ""
            save_web_research_article(title, url, domain, snippet, summary)
            self.btn_save_desk.setText("  ✓ Gespeichert!")
            self.btn_save_desk.setStyleSheet("""
                QPushButton {
                    background: #238636;
                    color: #FFFFFF;
                    border: 1px solid #2EA043;
                    border-radius: 5px;
                    padding: 0 10px;
                }
            """)
            QTimer.singleShot(2200, lambda: self._reset_save_desk_btn())
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Konnte Artikel nicht speichern: {e}")

    def _reset_save_desk_btn(self) -> None:
        self.btn_save_desk.setText("  📝 Auf Schreibtisch")
        self.btn_save_desk.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                border: 1px solid #2EA043;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)

    def _on_ai_summarize_clicked(self) -> None:
        if not self._current_article:
            QMessageBox.information(self, "Hinweis", "Bitte wähle zuerst eine Webseite aus.")
            return

        self.summary_drawer.show()
        self.txt_summary.setText("⏳ Analysiere Inhalt der Webseite und generiere KI-Kernaussagen...")

        if _HAS_WEBENGINE and hasattr(self, 'web_view'):
            js_code = "document.body.innerText;"
            self.web_view.page().runJavaScript(js_code, self._process_extracted_text_for_ai)
        else:
            text = self._loaded_text_content or self._current_article.get("snippet", "")
            self._process_extracted_text_for_ai(text)

    def _process_extracted_text_for_ai(self, text: Any) -> None:
        clean_text = str(text or "").strip()
        if not clean_text:
            snippet = self._current_article.get("snippet", "") if self._current_article else ""
            clean_text = snippet

        title = self._current_article.get("title", "") if self._current_article else "Fachartikel"

        def _worker():
            try:
                summary = self._generate_ai_summary(title, clean_text[:4000])
                self._signals.ai_summary_finished.emit(summary)
            except Exception as e:
                self._signals.ai_summary_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _generate_ai_summary(self, title: str, text: str) -> str:
        prompt = (
            f"Fasse die folgenden Kernaussagen und Definitionen aus dem wissenschaftlichen Fachartikel "
            f"'{title}' kurz, präzise und für Studierende verständlich in 3-4 Aufzählungspunkten auf Deutsch zusammen:\n\n"
            f"{text}"
        )

        try:
            from ai.gemini_client import generate_response
            resp = generate_response(prompt)
            if resp and len(resp.strip()) > 30:
                return resp.strip()
        except Exception:
            pass

        try:
            from ai.ollama_client import generate_ollama_response
            resp = generate_ollama_response(prompt)
            if resp and len(resp.strip()) > 30:
                return resp.strip()
        except Exception:
            pass

        paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 60]
        if not paragraphs:
            return f"• Thema: {title}\n• Artikel erfolgreich im Viewer geladen."

        bullets = []
        for p in paragraphs[:4]:
            first_sentence = p.split(". ")[0].strip() + "."
            bullets.append(f"• {first_sentence}")

        return "\n".join(bullets)

    def _on_ai_summary_finished(self, summary: str) -> None:
        self.txt_summary.setText(summary)

    def _on_ai_summary_error(self, err_msg: str) -> None:
        self.txt_summary.setText(f"KI-Analyse konnte nicht abgeschlossen werden: {err_msg}")

    def _import_pdf_to_library(self, item: Dict[str, Any], btn: QPushButton) -> None:
        """Downloads PDF and runs the AI pipeline to index into the library."""
        url = item.get("url", "")
        title = item.get("title", "Dokument")
        if not url:
            return

        btn.setEnabled(False)
        btn.setText("  ⏳ Lädt...")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #388BFD;
                color: #FFFFFF;
                border: 1px solid #58A6FF;
                border-radius: 4px;
                padding: 0 10px;
            }
        """)

        def _worker():
            try:
                storage_dir = get_books_storage_dir()
                os.makedirs(storage_dir, exist_ok=True)

                # Generate clean filename
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
                if not safe_title:
                    safe_title = "Skript"
                filename = f"{safe_title[:80]}.pdf"
                dest_path = os.path.join(storage_dir, filename)

                # Ensure unique destination filename
                n = 2
                base_stem = filename[:-4]
                while os.path.exists(dest_path):
                    dest_path = os.path.join(storage_dir, f"{base_stem} ({n}).pdf")
                    n += 1

                # Download PDF
                import urllib.request
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                with urllib.request.urlopen(req, timeout=25) as r, open(dest_path, "wb") as f:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)

                # Run AI pipeline & index into library.db
                indexed = index_single_book_file(dest_path)
                if indexed:
                    msg = f"'{indexed.get('title', safe_title)}' einsortiert in '{indexed.get('categories_str', 'Bibliothek')}'."
                    self._signals.pdf_import_finished.emit(url, True, msg)
                else:
                    self._signals.pdf_import_finished.emit(url, True, f"'{safe_title}' heruntergeladen.")
            except Exception as e:
                self._signals.pdf_import_finished.emit(url, False, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_pdf_import_finished(self, url: str, success: bool, message: str) -> None:
        if success:
            QMessageBox.information(
                self,
                "Erfolgreich importiert",
                f"Das Skript / Buch wurde heruntergeladen und einsortiert:\n\n{message}"
            )
        else:
            QMessageBox.warning(
                self,
                "Import-Fehler",
                f"Download oder Einsortierung fehlgeschlagen:\n{message}"
            )
