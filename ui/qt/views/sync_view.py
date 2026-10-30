"""Scan & Sync Center View for PySide6.
Delivers a Bento-Grid Command Dashboard with Live System KPIs, Incremental Delta-Scanner,
GitHub Cloud-Sync, Live Update & Release Feed, and Activity Console.
"""

import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QObject, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QFileDialog,
    QFrame,
    QMessageBox,
    QLineEdit,
    QInputDialog,
    QCheckBox,
    QScrollArea,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.config import (
    load_config,
    save_config,
    load_app_config,
    save_app_config,
    get_database_path,
)
from core.github_sync import GitHubSyncService
from core.update_checker import (
    check_for_updates,
    fetch_recent_releases,
    CURRENT_VERSION,
    FALLBACK_CHANGELOG,
)
from core.error_handler import humanize_error


class ScanSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(dict)
    log_message = Signal(str)
    sync_completed = Signal(bool, bool, str)  # is_push, success, message
    update_check_done = Signal(bool, str, str, str, list)  # avail, latest_ver, dl_url, notes, releases


class SyncView(QWidget):
    """Scan & Sync Command Dashboard."""

    scan_finished = Signal()
    update_available_signal = Signal(str)  # emits latest version when an update is found

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_scanning = False
        self.stop_event = threading.Event()
        self._pending_update_url: Optional[str] = None
        self._pending_update_ver: Optional[str] = None
        self._pending_update_notes: Optional[str] = None

        self.signals = ScanSignals()
        self.signals.progress.connect(self._on_progress)
        self.signals.finished.connect(self._on_finished)
        self.signals.log_message.connect(self._append_log)
        self.signals.sync_completed.connect(self._on_sync_completed)
        self.signals.update_check_done.connect(self._on_update_check_done)

        cfg = load_config()
        self.source_dir = cfg.get("last_directory") or r"G:\Meine Ablage\Bücher"
        if not os.path.exists(self.source_dir):
            self.source_dir = os.path.expanduser("~")

        self._build_ui()
        self.load_data()
        self._start_background_update_check(silent=True)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(26, 20, 26, 20)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. Hero Header with Live Version & Update Action
        # -------------------------------------------------------------
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        icon_badge = QLabel()
        icon_badge.setPixmap(create_vector_pixmap("sync", "#58A6FF", 28))
        icon_badge.setStyleSheet(
            "background-color: #131D31; border: 1px solid #263859; border-radius: 8px; padding: 6px;"
        )
        header_row.addWidget(icon_badge)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        lbl_title = QLabel("Scan & Sync Command Center")
        lbl_title.setFont(QFont("Segoe UI", 17, QFont.Bold))
        lbl_title.setStyleSheet("color: #FFFFFF; letter-spacing: 0.4px;")
        title_col.addWidget(lbl_title)

        lbl_sub = QLabel(
            "Inkrementeller PDF-Data-Lake, verschlüsseltes Cloud-Backup & automatische Versions-Überwachung"
        )
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_col.addWidget(lbl_sub)
        header_row.addLayout(title_col, stretch=1)

        # Header Badges & Actions
        badges_row = QHBoxLayout()
        badges_row.setSpacing(10)

        self.lbl_vault_pill = QLabel("🔒 Windows-Tresor (DPAPI)")
        self.lbl_vault_pill.setToolTip(
            "Alle Passwörter, Token und geheimen URLs sind mit der Windows Data Protection API verschlüsselt."
        )
        self.lbl_vault_pill.setStyleSheet("""
            QLabel {
                background: rgba(35, 134, 54, 0.16);
                color: #3FB950;
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #2EA043;
                border-radius: 6px;
                padding: 6px 12px;
            }
        """)
        badges_row.addWidget(self.lbl_vault_pill)

        self.lbl_header_ver = QLabel(f"v{CURRENT_VERSION}")
        self.lbl_header_ver.setStyleSheet("""
            QLabel {
                background: #162035;
                color: #58A6FF;
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #233554;
                border-radius: 6px;
                padding: 6px 12px;
            }
        """)
        badges_row.addWidget(self.lbl_header_ver)

        self.btn_chk_update = QPushButton("  Auf Updates prüfen")
        self.btn_chk_update.setIcon(create_vector_icon("research", "#58A6FF", 14))
        self.btn_chk_update.setCursor(Qt.PointingHandCursor)
        self.btn_chk_update.setStyleSheet("""
            QPushButton {
                background-color: #121826;
                color: #C9D1D9;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1C2438;
                border-color: #388BFD;
                color: #FFFFFF;
            }
        """)
        self.btn_chk_update.clicked.connect(lambda: self._start_background_update_check(silent=False))
        badges_row.addWidget(self.btn_chk_update)

        header_row.addLayout(badges_row)
        main_layout.addLayout(header_row)

        # -------------------------------------------------------------
        # 2. Live KPI Metric Strip (5 Compact Telemetry Cards)
        # -------------------------------------------------------------
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self.kpi_books_val, self.kpi_books_sub, kpi_card_1 = self._create_kpi_card(
            "library", "#58A6FF", "0 Dokumente", "Indizierte Fachliteratur im Data-Lake"
        )
        self.kpi_pages_val, self.kpi_pages_sub, kpi_card_2 = self._create_kpi_card(
            "book", "#A371F7", "0 Seiten", "Gesamtumfang & Fachkategorien"
        )
        self.kpi_study_val, self.kpi_study_sub, kpi_card_study = self._create_kpi_card(
            "clock", "#F778BA", "0 Std. Lernzeit", "Ø 2 Min/Seite akademisches Lesetempo"
        )
        self.kpi_desk_val, self.kpi_desk_sub, kpi_card_3 = self._create_kpi_card(
            "notes", "#E3B341", "0 aktiv · 0 Notizen", "Schreibtisch & Wissens-Annotationen"
        )
        self.kpi_rel_val, self.kpi_rel_sub, kpi_card_4 = self._create_kpi_card(
            "check", "#3FB950", f"v{CURRENT_VERSION} Aktuell", "Prüfe GitHub Release-Kanal..."
        )

        kpi_row.addWidget(kpi_card_1, stretch=1)
        kpi_row.addWidget(kpi_card_2, stretch=1)
        kpi_row.addWidget(kpi_card_study, stretch=1)
        kpi_row.addWidget(kpi_card_3, stretch=1)
        kpi_row.addWidget(kpi_card_4, stretch=1)
        main_layout.addLayout(kpi_row)

        # -------------------------------------------------------------
        # 3. Two-Column Action Grid: [Local Data-Lake] | [GitHub Cloud-Sync]
        # -------------------------------------------------------------
        grid_row = QHBoxLayout()
        grid_row.setSpacing(14)

        # === LEFT COLUMN: Local Data-Lake & Delta-Scan ===
        card_local = QFrame()
        card_local.setObjectName("card_local")
        card_local.setStyleSheet("""
            QFrame#card_local {
                background-color: #101624;
                border: 1px solid #22304C;
                border-radius: 12px;
            }
        """)
        local_layout = QVBoxLayout(card_local)
        local_layout.setContentsMargins(18, 16, 18, 16)
        local_layout.setSpacing(11)

        local_h_box = QHBoxLayout()
        lbl_local_icon = QLabel()
        lbl_local_icon.setPixmap(create_vector_pixmap("desk", "#58A6FF", 18))
        lbl_local_icon.setStyleSheet("border: none; background: transparent;")
        local_h_box.addWidget(lbl_local_icon)

        lbl_local_title = QLabel("Lokaler Data-Lake (Delta-Scanner)")
        lbl_local_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_local_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        local_h_box.addWidget(lbl_local_title)
        local_h_box.addStretch()

        self.lbl_storage_badge = QLabel("Google Drive / Lokal")
        self.lbl_storage_badge.setStyleSheet("""
            QLabel {
                background-color: #162035;
                color: #79C0FF;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 9px;
                border-radius: 5px;
                border: 1px solid #25395C;
            }
        """)
        local_h_box.addWidget(self.lbl_storage_badge)
        local_layout.addLayout(local_h_box)

        dir_box = QHBoxLayout()
        dir_box.setSpacing(8)
        self.lbl_path = QLabel(self.source_dir)
        self.lbl_path.setToolTip(self.source_dir)
        self.lbl_path.setStyleSheet("""
            QLabel {
                background-color: #090D16;
                border: 1px solid #22304C;
                border-radius: 6px;
                padding: 7px 12px;
                color: #E6EDF3;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        dir_box.addWidget(self.lbl_path, stretch=1)

        btn_browse = QPushButton("Ordner wählen")
        btn_browse.setIcon(create_vector_icon("export", "#C9D1D9", 13))
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setFixedHeight(34)
        btn_browse.setStyleSheet("""
            QPushButton {
                background-color: #1A2234;
                color: #C9D1D9;
                border: 1px solid #2E3E5B;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #23304A;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_browse.clicked.connect(self._choose_dir)
        dir_box.addWidget(btn_browse)
        local_layout.addLayout(dir_box)

        lbl_scan_info = QLabel(
            "Prüft Datei-Zeitstempel & Größen inkrementell in Millisekunden. Erkennt ISBN, Auflage, Erscheinungsjahr und Cover vollautomatisch."
        )
        lbl_scan_info.setWordWrap(True)
        lbl_scan_info.setStyleSheet("color: #8B949E; border: none; background: transparent; font-size: 11px;")
        local_layout.addWidget(lbl_scan_info)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #090D16;
                border: 1px solid #22304C;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #3FB950);
                border-radius: 3px;
            }
        """)
        local_layout.addWidget(self.progress_bar)

        scan_action_row = QHBoxLayout()
        scan_action_row.setSpacing(12)

        self.btn_start = QPushButton("  Delta-Scan starten")
        self.btn_start.setIcon(create_vector_icon("sync", "#FFFFFF", 15))
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(36)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #238636);
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 0 18px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388BFD, stop:1 #2EA043);
                border-color: #58A6FF;
            }
            QPushButton:disabled {
                background: #1C2433;
                border-color: #2E384D;
                color: #6E7681;
            }
        """)
        self.btn_start.clicked.connect(self._start_scan)
        scan_action_row.addWidget(self.btn_start)

        self.lbl_status = QLabel("Bereit für inkrementellen Abgleich")
        self.lbl_status.setStyleSheet("color: #8B949E; border: none; background: transparent; font-size: 11px;")
        scan_action_row.addWidget(self.lbl_status, stretch=1)

        local_layout.addLayout(scan_action_row)
        grid_row.addWidget(card_local, stretch=1)

        # === RIGHT COLUMN: GitHub Cloud-Sync & Snapshot Backup ===
        card_gh = QFrame()
        card_gh.setObjectName("card_gh")
        card_gh.setStyleSheet("""
            QFrame#card_gh {
                background-color: #101624;
                border: 1px solid #22304C;
                border-radius: 12px;
            }
        """)
        gh_layout = QVBoxLayout(card_gh)
        gh_layout.setContentsMargins(18, 16, 18, 16)
        gh_layout.setSpacing(11)

        gh_h_box = QHBoxLayout()
        lbl_gh_icon = QLabel()
        lbl_gh_icon.setPixmap(create_vector_pixmap("globe", "#3FB950", 18))
        lbl_gh_icon.setStyleSheet("border: none; background: transparent;")
        gh_h_box.addWidget(lbl_gh_icon)

        lbl_gh_title = QLabel("Cloud-Synchronisation (GitHub Gist)")
        lbl_gh_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_gh_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        gh_h_box.addWidget(lbl_gh_title)
        gh_h_box.addStretch()

        self.lbl_sync_status = QLabel("Prüfe...")
        self.lbl_sync_status.setStyleSheet("""
            QLabel {
                background-color: #162035;
                color: #8B949E;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 9px;
                border-radius: 5px;
                border: 1px solid #233554;
            }
        """)
        gh_h_box.addWidget(self.lbl_sync_status)
        gh_layout.addLayout(gh_h_box)

        lbl_gh_info = QLabel(
            "Sichert Lesefortschritt, Notizen, Favoriten und Buch-Metadaten komprimiert in deinem privaten GitHub Gist."
        )
        lbl_gh_info.setWordWrap(True)
        lbl_gh_info.setStyleSheet("color: #8B949E; border: none; background: transparent; font-size: 11px;")
        gh_layout.addWidget(lbl_gh_info)

        gh_actions_row = QHBoxLayout()
        gh_actions_row.setSpacing(8)

        btn_token = QPushButton("  Token (Tresor)")
        btn_token.setIcon(create_vector_icon("lock", "#79C0FF", 14))
        btn_token.setCursor(Qt.PointingHandCursor)
        btn_token.setFixedHeight(36)
        btn_token.setStyleSheet("""
            QPushButton {
                background-color: #1A2234;
                color: #C9D1D9;
                border: 1px solid #2E3E5B;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #23304A;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_token.clicked.connect(self._configure_github_token)
        gh_actions_row.addWidget(btn_token)

        self.btn_push_gist = QPushButton("  In Cloud sichern")
        self.btn_push_gist.setIcon(create_vector_icon("export", "#FFFFFF", 14))
        self.btn_push_gist.setCursor(Qt.PointingHandCursor)
        self.btn_push_gist.setFixedHeight(36)
        self.btn_push_gist.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #2EA043;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2EA043;
                border-color: #3FB950;
            }
            QPushButton:disabled {
                background-color: #16241C;
                border-color: #203B2A;
                color: #506859;
            }
        """)
        self.btn_push_gist.clicked.connect(self._push_to_github)
        gh_actions_row.addWidget(self.btn_push_gist, stretch=1)

        self.btn_pull_gist = QPushButton("  Aus Cloud laden")
        self.btn_pull_gist.setIcon(create_vector_icon("download", "#FFFFFF", 14))
        self.btn_pull_gist.setCursor(Qt.PointingHandCursor)
        self.btn_pull_gist.setFixedHeight(36)
        self.btn_pull_gist.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #388BFD;
                border-color: #58A6FF;
            }
            QPushButton:disabled {
                background-color: #141F30;
                border-color: #1E2D44;
                color: #4A5B75;
            }
        """)
        self.btn_pull_gist.clicked.connect(self._pull_from_github)
        gh_actions_row.addWidget(self.btn_pull_gist, stretch=1)
        gh_layout.addLayout(gh_actions_row)

        self.chk_auto_sync = QCheckBox("Automatischer Cloud-Sync (beim Beenden der App && nach Delta-Scans)")
        self.chk_auto_sync.setStyleSheet("""
            QCheckBox {
                color: #C9D1D9;
                font-size: 11px;
                font-weight: 500;
                spacing: 8px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #2E3E5B;
                background-color: #090D16;
            }
            QCheckBox::indicator:checked {
                background-color: #238636;
                border-color: #3FB950;
            }
        """)
        self.chk_auto_sync.toggled.connect(self._on_auto_sync_toggled)
        gh_layout.addWidget(self.chk_auto_sync)

        grid_row.addWidget(card_gh, stretch=1)
        main_layout.addLayout(grid_row)

        # -------------------------------------------------------------
        # 4. Bottom Split Row: [Release & Update Feed] | [Live Event Console]
        # -------------------------------------------------------------
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(14)

        # === BOTTOM LEFT: Software-Updates & Versions-Historie ===
        card_updates = QFrame()
        card_updates.setObjectName("card_updates")
        card_updates.setStyleSheet("""
            QFrame#card_updates {
                background-color: #101624;
                border: 1px solid #22304C;
                border-radius: 12px;
            }
        """)
        up_layout = QVBoxLayout(card_updates)
        up_layout.setContentsMargins(18, 14, 18, 14)
        up_layout.setSpacing(10)

        up_head = QHBoxLayout()
        lbl_up_icon = QLabel()
        lbl_up_icon.setPixmap(create_vector_pixmap("trophy", "#E3B341", 17))
        lbl_up_icon.setStyleSheet("border: none; background: transparent;")
        up_head.addWidget(lbl_up_icon)

        lbl_up_title = QLabel("Software-Updates & Neuerungen")
        lbl_up_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_up_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        up_head.addWidget(lbl_up_title)
        up_head.addStretch()

        self.lbl_update_pill = QLabel("Aktuell")
        self.lbl_update_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(35, 134, 54, 0.16);
                color: #3FB950;
                font-size: 10px;
                font-weight: bold;
                padding: 3px 9px;
                border-radius: 5px;
                border: 1px solid #2EA043;
            }
        """)
        up_head.addWidget(self.lbl_update_pill)
        up_layout.addLayout(up_head)

        # Dynamic Update Available Callout Banner (hidden when up-to-date)
        self.update_banner = QFrame()
        self.update_banner.setObjectName("update_banner")
        self.update_banner.setStyleSheet("""
            QFrame#update_banner {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #14281D, stop:1 #122138);
                border: 1px solid #2EA043;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        banner_lay = QHBoxLayout(self.update_banner)
        banner_lay.setContentsMargins(10, 8, 10, 8)
        banner_lay.setSpacing(10)

        self.lbl_banner_text = QLabel("Neues Update verfügbar!")
        self.lbl_banner_text.setWordWrap(True)
        self.lbl_banner_text.setStyleSheet("color: #F0F6FC; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        banner_lay.addWidget(self.lbl_banner_text, stretch=1)

        self.btn_install_update = QPushButton("⚡ Jetzt installieren")
        self.btn_install_update.setCursor(Qt.PointingHandCursor)
        self.btn_install_update.setFixedHeight(30)
        self.btn_install_update.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                border: 1px solid #3FB950;
                border-radius: 5px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2EA043;
            }
        """)
        self.btn_install_update.clicked.connect(self._trigger_one_click_update)
        banner_lay.addWidget(self.btn_install_update)
        self.update_banner.hide()
        up_layout.addWidget(self.update_banner)

        # Scrollable Release Cards Feed
        rel_scroll = QScrollArea()
        rel_scroll.setWidgetResizable(True)
        rel_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; } QWidget { background: transparent; }")
        self.rel_container = QWidget()
        self.rel_list_layout = QVBoxLayout(self.rel_container)
        self.rel_list_layout.setContentsMargins(0, 0, 4, 0)
        self.rel_list_layout.setSpacing(8)
        rel_scroll.setWidget(self.rel_container)
        up_layout.addWidget(rel_scroll, stretch=1)

        bottom_row.addWidget(card_updates, stretch=1)

        # === BOTTOM RIGHT: Live Terminal & Synchronisations-Protokoll ===
        card_log = QFrame()
        card_log.setObjectName("card_log")
        card_log.setStyleSheet("""
            QFrame#card_log {
                background-color: #101624;
                border: 1px solid #22304C;
                border-radius: 12px;
            }
        """)
        log_layout = QVBoxLayout(card_log)
        log_layout.setContentsMargins(18, 14, 18, 14)
        log_layout.setSpacing(10)

        log_h_box = QHBoxLayout()
        lbl_terminal_icon = QLabel()
        lbl_terminal_icon.setPixmap(create_vector_pixmap("notes", "#58A6FF", 16))
        lbl_terminal_icon.setStyleSheet("border: none; background: transparent;")
        log_h_box.addWidget(lbl_terminal_icon)

        lbl_log_h = QLabel("Echtzeit-Systemkonsole & Diagnose")
        lbl_log_h.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_log_h.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        log_h_box.addWidget(lbl_log_h)
        log_h_box.addStretch()

        btn_clear_log = QPushButton("Protokoll leeren")
        btn_clear_log.setCursor(Qt.PointingHandCursor)
        btn_clear_log.setStyleSheet("""
            QPushButton {
                background-color: #1A2234;
                color: #8B949E;
                border: 1px solid #2E3E5B;
                border-radius: 4px;
                padding: 3px 10px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #23304A;
                color: #C9D1D9;
            }
        """)
        btn_clear_log.clicked.connect(lambda: self.txt_log.clear())
        log_h_box.addWidget(btn_clear_log)
        log_layout.addLayout(log_h_box)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setFont(QFont("Consolas", 9))
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #090D16;
                color: #79C0FF;
                border: 1px solid #1E2B44;
                border-radius: 8px;
                padding: 10px;
                line-height: 1.45;
            }
        """)
        log_layout.addWidget(self.txt_log, stretch=1)
        bottom_row.addWidget(card_log, stretch=1)

        main_layout.addLayout(bottom_row, stretch=1)

        # Populate initial release cards & system ready log
        self._populate_release_cards(FALLBACK_CHANGELOG)
        self._refresh_github_status()
        self._append_log(f"System initialisiert • Campus-Bibliothek AI v{CURRENT_VERSION} bereit.")
        self._append_log("Windows-Tresor (DPAPI) aktiv • Sensible Zugangsdaten sind hardwaregebunden geschützt.")

    def _create_kpi_card(self, icon_name: str, color_hex: str, value_text: str, sub_text: str):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #101624;
                border: 1px solid #22304C;
                border-radius: 10px;
            }}
        """)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(12)

        ic = QLabel()
        ic.setPixmap(create_vector_pixmap(icon_name, color_hex, 22))
        ic.setFixedSize(38, 38)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid {color_hex}44;
                border-radius: 8px;
            }}
        """)
        lay.addWidget(ic)

        col = QVBoxLayout()
        col.setSpacing(2)
        lbl_val = QLabel(value_text)
        lbl_val.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_val.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        col.addWidget(lbl_val)

        lbl_sub = QLabel(sub_text)
        lbl_sub.setFont(QFont("Segoe UI", 8))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        col.addWidget(lbl_sub)

        lay.addLayout(col, stretch=1)
        return lbl_val, lbl_sub, card

    def load_data(self) -> None:
        """Refreshes live SQLite telemetry counters for the 4 KPI cards."""
        try:
            db_path = get_database_path()
            if not os.path.exists(db_path):
                return
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*), COALESCE(SUM(page_count), 0), COALESCE(SUM(file_size), 0) FROM books")
            row = cur.fetchone() or (0, 0, 0)
            total_books = int(row[0] or 0)
            total_pages = int(row[1] or 0)
            total_bytes = int(row[2] or 0)

            cur.execute("SELECT COUNT(DISTINCT category) FROM book_categories")
            cat_count = int((cur.fetchone() or (0,))[0] or 0)

            desk_count = 0
            try:
                cur.execute("SELECT COUNT(*) FROM desk_items")
                desk_count = int((cur.fetchone() or (0,))[0] or 0)
            except Exception:
                pass

            notes_count = 0
            try:
                cur.execute("SELECT COUNT(*) FROM book_notes")
                notes_count = int((cur.fetchone() or (0,))[0] or 0)
            except Exception:
                pass

            conn.close()

            gb_size = total_bytes / (1024 ** 3)
            size_str = f"{gb_size:.2f} GB" if gb_size >= 0.1 else f"{total_bytes / (1024 ** 2):.0f} MB"
            self.kpi_books_val.setText(f"{total_books:,} Dokumente".replace(",", "."))
            self.kpi_books_sub.setText(f"Data-Lake Umfang: {size_str}")

            self.kpi_pages_val.setText(f"{total_pages:,} Seiten".replace(",", "."))
            self.kpi_pages_sub.setText(f"Verteilt auf {cat_count} Fachbereiche")

            # Calculate realistic academic reading & study time (Ø 2 minutes per page for academic reading/learning)
            study_hours = int(total_pages * 2.0 / 60.0)
            study_days_24h = study_hours / 24.0
            # Daily study tempo: 2 hours/day (~60 pages/day)
            study_years = study_hours / (2.0 * 365.25)
            # Daily pages target: e.g. 50 pages/day -> days to complete
            days_at_50_pages = int(total_pages / 50.0) if total_pages > 0 else 0
            pages_per_h = 30  # ~2 min per page

            if study_hours >= 100:
                years_str = f"{study_years:.1f}".replace(".", ",")
                self.kpi_study_val.setText(f"~{study_hours:,} Std. ({total_pages:,} S.)".replace(",", "."))
                self.kpi_study_sub.setText(f"~30 S./Std. · {days_at_50_pages:,} Tage bei 50 S./Tag (ca. {years_str} J.)".replace(",", "."))
            else:
                self.kpi_study_val.setText(f"{study_hours} Std. ({total_pages} S.)")
                self.kpi_study_sub.setText("Ø 30 Seiten/Std. akademisches Lesetempo")

            self.kpi_desk_val.setText(f"{desk_count} am Tisch · {notes_count} Notizen")
            self.kpi_desk_sub.setText("Lese-Fortschritt & Wissenskarten")
        except Exception:
            pass

    def _populate_release_cards(self, releases: List[Dict[str, str]]) -> None:
        while self.rel_list_layout.count():
            item = self.rel_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, rel in enumerate(releases):
            ver = rel.get("version", "")
            date_str = rel.get("date", "")
            title = rel.get("title", f"Update v{ver}")
            notes = rel.get("notes", "")
            is_current = (ver == CURRENT_VERSION)

            item_card = QFrame()
            border_col = "#238636" if idx == 0 and not is_current else ("#2A3F66" if is_current else "#1D283E")
            bg_col = "#0C1320" if is_current else "#0B101B"
            item_card.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg_col};
                    border: 1px solid {border_col};
                    border-radius: 8px;
                }}
            """)
            c_lay = QVBoxLayout(item_card)
            c_lay.setContentsMargins(12, 9, 12, 9)
            c_lay.setSpacing(4)

            top_r = QHBoxLayout()
            badge_ver = QLabel(f"v{ver}")
            badge_col = "#3FB950" if is_current else "#58A6FF"
            badge_ver.setStyleSheet(f"""
                QLabel {{
                    background-color: #152238;
                    color: {badge_col};
                    font-size: 10px;
                    font-weight: bold;
                    padding: 2px 7px;
                    border-radius: 4px;
                    border: none;
                }}
            """)
            top_r.addWidget(badge_ver)

            lbl_t = QLabel(title)
            lbl_t.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_t.setStyleSheet("color: #E6EDF3; border: none; background: transparent;")
            top_r.addWidget(lbl_t, stretch=1)

            lbl_d = QLabel("Installiert" if is_current else date_str)
            lbl_d.setStyleSheet(
                f"color: {'#3FB950' if is_current else '#6E7681'}; font-size: 9px; font-weight: bold; border: none; background: transparent;"
            )
            top_r.addWidget(lbl_d)
            c_lay.addLayout(top_r)

            lbl_n = QLabel(notes)
            lbl_n.setWordWrap(True)
            lbl_n.setStyleSheet("color: #8B949E; font-size: 10px; border: none; background: transparent; line-height: 1.3;")
            c_lay.addWidget(lbl_n)

            self.rel_list_layout.addWidget(item_card)

        self.rel_list_layout.addStretch()

    def _start_background_update_check(self, silent: bool = True) -> None:
        self._silent_check = silent
        self.btn_chk_update.setEnabled(False)
        self.btn_chk_update.setText("  Prüfe GitHub...")
        if not silent:
            self._append_log(f"Updater: Prüfe Releases auf Florian306/Campus-Bibliothek...")

        def worker():
            avail, latest, url, notes = check_for_updates()
            releases = fetch_recent_releases(limit=4)
            self.signals.update_check_done.emit(
                bool(avail),
                str(latest or ""),
                str(url or ""),
                str(notes or ""),
                releases,
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(
        self, avail: bool, latest: str, url: str, notes: str, releases: list
    ) -> None:
        self.btn_chk_update.setEnabled(True)
        self.btn_chk_update.setText("  Auf Updates prüfen")
        silent = getattr(self, "_silent_check", True)

        if releases:
            self._populate_release_cards(releases)

        if avail and latest and url:
            self._pending_update_ver = latest
            self._pending_update_url = url
            self._pending_update_notes = notes

            self.lbl_update_pill.setText(f"Update v{latest} verfügbar!")
            self.lbl_update_pill.setStyleSheet("""
                QLabel {
                    background-color: rgba(227, 179, 65, 0.20);
                    color: #E3B341;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 3px 9px;
                    border-radius: 5px;
                    border: 1px solid #D29922;
                }
            """)
            self.kpi_rel_val.setText(f"Update v{latest} bereit!")
            self.kpi_rel_val.setStyleSheet("color: #E3B341; border: none; background: transparent;")
            self.kpi_rel_sub.setText(f"Installiert: v{CURRENT_VERSION} ➔ Neu: v{latest}")

            self.lbl_banner_text.setText(
                f"🚀 Neue Version v{latest} ist auf GitHub verfügbar! (Aktuell installiert: v{CURRENT_VERSION})"
            )
            self.update_banner.show()
            self._append_log(f"Updater: Neues Update v{latest} gefunden! Bereit zur 1-Klick-Installation.")
            self.update_available_signal.emit(latest)

            if not silent:
                self._trigger_one_click_update()
        else:
            self.update_banner.hide()
            self.lbl_update_pill.setText(f"v{CURRENT_VERSION} • Aktuell")
            self.kpi_rel_val.setText(f"v{CURRENT_VERSION} Aktuell")
            self.kpi_rel_val.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
            self.kpi_rel_sub.setText("Neueste GitHub-Version installiert")
            if not silent:
                self._append_log(f"Updater: Du verwendest bereits die neueste Version (v{CURRENT_VERSION}).")
                QMessageBox.information(
                    self,
                    "Software auf dem neuesten Stand",
                    f"Du verwendest bereits die aktuellste Version (v{CURRENT_VERSION}).",
                )

    def _trigger_one_click_update(self) -> None:
        if not self._pending_update_ver or not self._pending_update_url:
            return
        latest = self._pending_update_ver
        url = self._pending_update_url
        notes = self._pending_update_notes or ""

        box = QMessageBox(self)
        box.setWindowTitle("Update verfügbar!")
        box.setIcon(QMessageBox.Information)
        box.setText(
            f"Eine neuere Version von Campus-Bibliothek ist verfügbar: <b>v{latest}</b> (Aktuell: v{CURRENT_VERSION})"
        )
        box.setInformativeText(
            f"Möchtest du das Update jetzt direkt automatisch herunterladen und installieren?\n\nÄnderungen:\n{notes[:350]}"
        )

        btn_auto = box.addButton("Jetzt automatisch aktualisieren", QMessageBox.AcceptRole)
        btn_github = box.addButton("Release-Seite öffnen", QMessageBox.ActionRole)
        box.addButton("Später", QMessageBox.RejectRole)

        box.exec()
        clicked = box.clickedButton()
        if clicked == btn_auto:
            from ui.qt.dialogs.auto_updater_dialog import UpdateProgressDialog
            dlg = UpdateProgressDialog(self, url, latest)
            dlg.exec()
        elif clicked == btn_github:
            import webbrowser
            webbrowser.open(f"https://github.com/Florian306/Campus-Bibliothek/releases/tag/v{latest}")

    def _choose_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Quellverzeichnis wählen", self.source_dir)
        if folder:
            self.source_dir = folder
            self.lbl_path.setText(folder)
            self.lbl_path.setToolTip(folder)
            cfg = load_config()
            cfg["last_directory"] = folder
            save_config(cfg)
            self._append_log(f"Quellverzeichnis geändert: {folder}")

    def _start_scan(self) -> None:
        if self.is_scanning:
            return
        self.is_scanning = True
        self.btn_start.setEnabled(False)
        self.btn_start.setText("  Scanne...")
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Initialisiere Delta-Scan...")
        self._append_log(f"Starte Delta-Scan in: {self.source_dir}")

        def worker():
            from core.delta_scanner import run_delta_scan
            last_ui = 0.0

            def on_progress(curr, total, fname, is_delta, book_data=None):
                nonlocal last_ui
                now = time.time()
                if is_delta or (now - last_ui >= 0.05) or curr == total:
                    last_ui = now
                    pct = int((curr / max(1, total)) * 100)
                    tag = "NEU" if is_delta else "OK"
                    msg = f"{curr}/{total} ({pct}%) · [{tag}] {fname[:38]}"
                    self.signals.progress.emit(pct, msg)

            stats = run_delta_scan(
                source_dir=self.source_dir,
                progress_callback=on_progress,
                stop_event=self.stop_event,
            )
            self.signals.finished.emit(stats)

        threading.Thread(target=worker, daemon=True).start()

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_finished(self, stats: Dict[str, int]) -> None:
        self.is_scanning = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("  Delta-Scan starten")
        self.progress_bar.setValue(100)
        summary = (
            f"Scan fertig! {stats['total']} PDFs geprüft "
            f"({stats['new_or_updated']} neu/aktualisiert, {stats['unchanged']} unverändert)."
        )
        self.lbl_status.setText(summary)
        self._append_log(f"✓ {summary}")
        self.load_data()
        self.scan_finished.emit()
        QMessageBox.information(self, "Scan abgeschlossen", summary)

        cfg = load_app_config()
        if cfg.github_auto_sync and cfg.github_token.strip() and stats.get("new_or_updated", 0) > 0:
            self._append_log("GitHub Sync: Starte automatischen Cloud-Sync nach Delta-Scan...")
            self._push_to_github()

    def _append_log(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{ts}]  {text}")

    def _refresh_github_status(self) -> None:
        cfg = load_app_config()
        has_token = bool(cfg.github_token.strip())
        if has_token:
            gist_info = f" (Gist: {cfg.github_gist_id[:8]}...)" if cfg.github_gist_id else ""
            self.lbl_sync_status.setText(f"● Verbunden{gist_info}")
            self.lbl_sync_status.setStyleSheet("""
                QLabel {
                    background-color: rgba(35, 134, 54, 0.18);
                    color: #3FB950;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 3px 9px;
                    border-radius: 5px;
                    border: 1px solid #238636;
                }
            """)
            self.btn_push_gist.setEnabled(True)
            self.btn_pull_gist.setEnabled(True)
            self.chk_auto_sync.setEnabled(True)
        else:
            self.lbl_sync_status.setText("Kein Token konfiguriert")
            self.lbl_sync_status.setStyleSheet("""
                QLabel {
                    background-color: #162035;
                    color: #8B949E;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 3px 9px;
                    border-radius: 5px;
                    border: 1px solid #233554;
                }
            """)
            self.btn_push_gist.setEnabled(False)
            self.btn_pull_gist.setEnabled(False)
            self.chk_auto_sync.setEnabled(False)

        self.chk_auto_sync.blockSignals(True)
        self.chk_auto_sync.setChecked(bool(cfg.github_auto_sync))
        self.chk_auto_sync.blockSignals(False)

    def _on_auto_sync_toggled(self, checked: bool) -> None:
        cfg = load_app_config()
        cfg.github_auto_sync = checked
        save_app_config(cfg)
        status_text = "aktiviert" if checked else "deaktiviert"
        self._append_log(f"GitHub Sync: Automatischer Cloud-Sync {status_text}.")

    def _configure_github_token(self) -> None:
        cfg = load_app_config()
        has_existing = bool(cfg.github_token.strip())
        prompt_text = (
            "🔒 Ein GitHub Token ist bereits sicher im Windows-Tresor (DPAPI) hinterlegt.\n"
            "Gib ein neues Token ein, um es zu ersetzen (oder lasse das Feld leer, um das Token zu löschen):\n\n"
            "Erstellen unter: github.com/settings/tokens (classic) -> Haken bei 'gist'"
            if has_existing
            else "Gib dein GitHub Personal Access Token ein (Berechtigung: 'gist'):\n\n"
            "Erstellen unter: github.com/settings/tokens (classic) -> Haken bei 'gist'"
        )
        token, ok = QInputDialog.getText(
            self,
            "GitHub Personal Access Token (Windows-Tresor)",
            prompt_text,
            QLineEdit.Password,
            "",
        )
        if ok and token is not None:
            token = token.strip()
            if token:
                valid, msg = GitHubSyncService.test_token(token)
                if not valid:
                    QMessageBox.warning(self, "Token ungültig", msg)
                    return
                cfg.github_token = token
                save_app_config(cfg)
                self._append_log(f"GitHub: {msg}")
                QMessageBox.information(self, "Verbunden", msg)
            else:
                cfg.github_token = ""
                save_app_config(cfg)
                self._append_log("GitHub: Token aus dem Tresor entfernt.")
            self._refresh_github_status()

    def _push_to_github(self) -> None:
        self.btn_push_gist.setEnabled(False)
        self.btn_pull_gist.setEnabled(False)
        self.lbl_sync_status.setText("Sichere Daten in GitHub Gist...")
        self.lbl_sync_status.setStyleSheet("""
            QLabel {
                background-color: rgba(227, 179, 65, 0.18);
                color: #E3B341;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 9px;
                border-radius: 5px;
                border: 1px solid #9E6A03;
            }
        """)
        self._append_log("GitHub Sync: Starte Upload in privaten Gist (komprimiere SQLite Metadaten)...")

        def task():
            try:
                success, msg = GitHubSyncService.push_to_gist()
            except Exception as e:
                success, msg = False, f"Unerwarteter Fehler: {str(e)}"
            self.signals.sync_completed.emit(True, success, msg)

        threading.Thread(target=task, daemon=True).start()

    def _pull_from_github(self) -> None:
        reply = QMessageBox.question(
            self,
            "Bibliothek synchronisieren",
            "Möchtest du den gesicherten Stand aus der GitHub Cloud laden und in deine lokale Bibliothek zusammenführen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_pull_gist.setEnabled(False)
        self.btn_push_gist.setEnabled(False)
        self.lbl_sync_status.setText("Lade Snapshot aus GitHub Cloud...")
        self.lbl_sync_status.setStyleSheet("""
            QLabel {
                background-color: rgba(227, 179, 65, 0.18);
                color: #E3B341;
                font-size: 10px;
                font-weight: 600;
                padding: 3px 9px;
                border-radius: 5px;
                border: 1px solid #9E6A03;
            }
        """)
        self._append_log("GitHub Sync: Lade Snapshot aus Gist...")

        def task():
            try:
                success, msg = GitHubSyncService.pull_from_gist()
            except Exception as e:
                success, msg = False, f"Unerwarteter Fehler: {str(e)}"
            self.signals.sync_completed.emit(False, success, msg)

        threading.Thread(target=task, daemon=True).start()

    def _on_sync_completed(self, is_push: bool, success: bool, msg: str) -> None:
        self.btn_push_gist.setEnabled(True)
        self.btn_pull_gist.setEnabled(True)
        self._append_log(f"GitHub Sync: {msg}")
        self._refresh_github_status()
        self.load_data()
        if is_push:
            if success:
                QMessageBox.information(self, "Cloud-Sicherung erfolgreich", msg)
            else:
                friendly = humanize_error(msg, "Cloud-Sicherung fehlgeschlagen")
                QMessageBox.critical(self, "Cloud-Sicherung fehlgeschlagen", friendly)
        else:
            if success:
                self.scan_finished.emit()
                QMessageBox.information(self, "Synchronisation abgeschlossen", msg)
            else:
                friendly = humanize_error(msg, "Download fehlgeschlagen")
                QMessageBox.critical(self, "Download fehlgeschlagen", friendly)
