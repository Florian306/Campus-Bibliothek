"""Scan & Sync Center View for PySide6.
Handles source directory selection, multi-threaded incremental Delta-Scan, and terminal logging.
"""

import os
import threading
import time
from typing import Dict
from PySide6.QtCore import Qt, Signal, QObject
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
)

from ui.qt.icons import create_vector_icon
from core.config import load_config, save_config, load_app_config, save_app_config
from core.github_sync import GitHubSyncService
from core.update_checker import check_for_updates, CURRENT_VERSION
from core.error_handler import humanize_error


class ScanSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(dict)
    log_message = Signal(str)
    sync_completed = Signal(bool, bool, str)  # is_push, success, message


class SyncView(QWidget):
    """Scan and Sync Center."""

    scan_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_scanning = False
        self.stop_event = threading.Event()
        self.signals = ScanSignals()
        self.signals.progress.connect(self._on_progress)
        self.signals.finished.connect(self._on_finished)
        self.signals.log_message.connect(self._append_log)
        self.signals.sync_completed.connect(self._on_sync_completed)

        cfg = load_config()
        self.source_dir = cfg.get("last_directory") or r"G:\Meine Ablage\Bücher"
        if not os.path.exists(self.source_dir):
            self.source_dir = os.path.expanduser("~")

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(18)

        # -------------------------------------------------------------
        # Hero Header with live status chips
        # -------------------------------------------------------------
        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        lbl_title = QLabel("Scan & Sync Center")
        lbl_title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_title.setStyleSheet("color: #FFFFFF; letter-spacing: 0.5px;")
        title_col.addWidget(lbl_title)

        lbl_sub = QLabel("Inkrementeller Datenabgleich & Cloud-Synchronisation für deinen Campus-Datenbestand")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_col.addWidget(lbl_sub)
        header_row.addLayout(title_col, stretch=1)

        # Header Badges & Actions
        badges_row = QHBoxLayout()
        badges_row.setSpacing(10)

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

        btn_chk_update = QPushButton("  Auf Updates prüfen")
        btn_chk_update.setIcon(create_vector_icon("research", "#58A6FF", 14))
        btn_chk_update.setCursor(Qt.PointingHandCursor)
        btn_chk_update.setStyleSheet("""
            QPushButton {
                background-color: #121826;
                color: #C9D1D9;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1C2438;
                border-color: #388BFD;
                color: #FFFFFF;
            }
        """)
        btn_chk_update.clicked.connect(self._check_github_updates)
        badges_row.addWidget(btn_chk_update)

        header_row.addLayout(badges_row)
        main_layout.addLayout(header_row)

        # -------------------------------------------------------------
        # Two-Column Bento Grid: [Local Data-Lake] | [GitHub Cloud-Sync]
        # -------------------------------------------------------------
        grid_row = QHBoxLayout()
        grid_row.setSpacing(16)

        # === LEFT COLUMN: Local Data-Lake & Delta-Scan ===
        card_local = QFrame()
        card_local.setStyleSheet("""
            QFrame#card_local {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 12px;
            }
        """)
        card_local.setObjectName("card_local")
        local_layout = QVBoxLayout(card_local)
        local_layout.setContentsMargins(20, 18, 20, 18)
        local_layout.setSpacing(14)

        # Left Card Header
        local_h_box = QHBoxLayout()
        lbl_local_icon = QLabel()
        lbl_local_icon.setPixmap(create_vector_icon("desk", "#58A6FF", 18).pixmap(18, 18))
        lbl_local_icon.setStyleSheet("border: none; background: transparent;")
        local_h_box.addWidget(lbl_local_icon)

        lbl_local_title = QLabel("Lokaler Data-Lake (Delta-Scan)")
        lbl_local_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_local_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        local_h_box.addWidget(lbl_local_title)
        local_h_box.addStretch()
        local_layout.addLayout(local_h_box)

        lbl_dir_sub = QLabel("Wähle dein lokales Verzeichnis oder Google Drive:")
        lbl_dir_sub.setStyleSheet("color: #8B949E; border: none; background: transparent; font-size: 11px;")
        local_layout.addWidget(lbl_dir_sub)

        # Path input row with browse button
        dir_box = QHBoxLayout()
        dir_box.setSpacing(8)
        self.lbl_path = QLabel(self.source_dir)
        self.lbl_path.setToolTip(self.source_dir)
        self.lbl_path.setStyleSheet("""
            QLabel {
                background-color: #0B0F19;
                border: 1px solid #232F48;
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
        btn_browse.setStyleSheet("""
            QPushButton {
                background-color: #1A2234;
                color: #C9D1D9;
                border: 1px solid #2E3E5B;
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 11px;
                font-weight: 500;
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

        # Divider line
        div_l = QFrame()
        div_l.setFrameShape(QFrame.HLine)
        div_l.setFixedHeight(1)
        div_l.setStyleSheet("background: #1C263A; border: none;")
        local_layout.addWidget(div_l)

        lbl_scan_info = QLabel("Erkennt blitzschnell neue oder geänderte PDF-Bücher. Bereits vorhandene Metadaten bleiben geschützt.")
        lbl_scan_info.setWordWrap(True)
        lbl_scan_info.setStyleSheet("color: #8B949E; border: none; background: transparent; font-size: 11px; line-height: 1.3;")
        local_layout.addWidget(lbl_scan_info)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0B0F19;
                border: 1px solid #232F48;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #58A6FF);
                border-radius: 3px;
            }
        """)
        local_layout.addWidget(self.progress_bar)

        # Scan trigger & status
        scan_action_row = QHBoxLayout()
        scan_action_row.setSpacing(12)

        self.btn_start = QPushButton("  Delta-Scan starten")
        self.btn_start.setIcon(create_vector_icon("sync", "#FFFFFF", 15))
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(38)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #238636);
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 0 18px;
                font-weight: bold;
                font-size: 12px;
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

        self.lbl_status = QLabel("Bereit für Delta-Scan")
        self.lbl_status.setStyleSheet("color: #8B949E; border: none; background: transparent; font-size: 11px;")
        scan_action_row.addWidget(self.lbl_status, stretch=1)

        local_layout.addLayout(scan_action_row)
        local_layout.addStretch()
        grid_row.addWidget(card_local, stretch=1)

        # === RIGHT COLUMN: GitHub Cloud-Sync & Snapshot Backup ===
        card_gh = QFrame()
        card_gh.setStyleSheet("""
            QFrame#card_gh {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 12px;
            }
        """)
        card_gh.setObjectName("card_gh")
        gh_layout = QVBoxLayout(card_gh)
        gh_layout.setContentsMargins(20, 18, 20, 18)
        gh_layout.setSpacing(14)

        # Header with Connection Badge
        gh_h_box = QHBoxLayout()
        lbl_gh_icon = QLabel()
        lbl_gh_icon.setPixmap(create_vector_icon("bulb", "#3FB950", 18).pixmap(18, 18))
        lbl_gh_icon.setStyleSheet("border: none; background: transparent;")
        gh_h_box.addWidget(lbl_gh_icon)

        lbl_gh_title = QLabel("Cloud-Synchronisation (GitHub Gist)")
        lbl_gh_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_gh_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        gh_h_box.addWidget(lbl_gh_title)
        gh_h_box.addStretch()

        self.lbl_sync_status = QLabel("Prüfe...")
        self.lbl_sync_status.setStyleSheet("""
            QLabel {
                background-color: #162035;
                color: #8B949E;
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
                border-radius: 6px;
                border: 1px solid #233554;
            }
        """)
        gh_h_box.addWidget(self.lbl_sync_status)
        gh_layout.addLayout(gh_h_box)

        lbl_gh_info = QLabel("Sichere Lesefortschritt, Notizen, Favoriten und Buchdaten verschlüsselt in einem privaten GitHub Gist.")
        lbl_gh_info.setWordWrap(True)
        lbl_gh_info.setStyleSheet("color: #8B949E; border: none; background: transparent; font-size: 11px; line-height: 1.3;")
        gh_layout.addWidget(lbl_gh_info)

        # Action Buttons Row (Token, Push, Pull)
        gh_actions_row = QHBoxLayout()
        gh_actions_row.setSpacing(10)

        btn_token = QPushButton("Token konfigurieren")
        btn_token.setCursor(Qt.PointingHandCursor)
        btn_token.setFixedHeight(38)
        btn_token.setStyleSheet("""
            QPushButton {
                background-color: #1A2234;
                color: #C9D1D9;
                border: 1px solid #2E3E5B;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: 500;
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
        self.btn_push_gist.setFixedHeight(38)
        self.btn_push_gist.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #2EA043;
                border-radius: 6px;
                padding: 0 16px;
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
        gh_actions_row.addWidget(self.btn_push_gist)

        self.btn_pull_gist = QPushButton("  Aus Cloud laden")
        self.btn_pull_gist.setIcon(create_vector_icon("download", "#FFFFFF", 14))
        self.btn_pull_gist.setCursor(Qt.PointingHandCursor)
        self.btn_pull_gist.setFixedHeight(38)
        self.btn_pull_gist.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 0 16px;
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
        gh_actions_row.addWidget(self.btn_pull_gist)
        gh_layout.addLayout(gh_actions_row)

        # Divider line
        div_r = QFrame()
        div_r.setFrameShape(QFrame.HLine)
        div_r.setFixedHeight(1)
        div_r.setStyleSheet("background: #1C263A; border: none;")
        gh_layout.addWidget(div_r)

        # Auto-sync option toggle
        self.chk_auto_sync = QCheckBox("Automatischer Cloud-Sync (beim Beenden der App & nach Delta-Scans)")
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
                background-color: #0B0F19;
            }
            QCheckBox::indicator:checked {
                background-color: #238636;
                border-color: #3FB950;
            }
        """)
        self.chk_auto_sync.toggled.connect(self._on_auto_sync_toggled)
        gh_layout.addWidget(self.chk_auto_sync)

        gh_layout.addStretch()
        grid_row.addWidget(card_gh, stretch=1)

        main_layout.addLayout(grid_row)
        self._refresh_github_status()

        # -------------------------------------------------------------
        # 3. Terminal & Event Protokoll
        # -------------------------------------------------------------
        card_log = QFrame()
        card_log.setStyleSheet("""
            QFrame#card_log {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 12px;
            }
        """)
        card_log.setObjectName("card_log")
        log_layout = QVBoxLayout(card_log)
        log_layout.setContentsMargins(18, 14, 18, 16)
        log_layout.setSpacing(10)

        log_h_box = QHBoxLayout()
        lbl_terminal_icon = QLabel()
        lbl_terminal_icon.setPixmap(create_vector_icon("notes", "#58A6FF", 16).pixmap(16, 16))
        lbl_terminal_icon.setStyleSheet("border: none; background: transparent;")
        log_h_box.addWidget(lbl_terminal_icon)

        lbl_log_h = QLabel("Ereignis- & Synchronisationsprotokoll")
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
                background-color: #0B0F19;
                color: #58A6FF;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 10px;
                line-height: 1.4;
            }
        """)
        log_layout.addWidget(self.txt_log)
        main_layout.addWidget(card_log, stretch=1)

    def _choose_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Quellverzeichnis wählen", self.source_dir)
        if folder:
            self.source_dir = folder
            self.lbl_path.setText(folder)
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
                    tag = "NEU" if is_delta else "Unverändert"
                    msg = f"{curr}/{total} ({pct}%) | [{tag}] {fname[:35]}"
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
        summary = f"Scan fertig! {stats['total']} PDFs geprüft ({stats['new_or_updated']} analysiert, {stats['unchanged']} unverändert)."
        self.lbl_status.setText(summary)
        self._append_log(summary)
        self.scan_finished.emit()
        QMessageBox.information(self, "Scan abgeschlossen", summary)

        # Trigger auto-sync after scan if enabled and new/updated books were found
        cfg = load_app_config()
        if cfg.github_auto_sync and cfg.github_token.strip() and stats.get("new_or_updated", 0) > 0:
            self._append_log("GitHub Sync: Starte automatischen Cloud-Sync nach Delta-Scan...")
            self._push_to_github()

    def _append_log(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{ts}] {text}")

    def _refresh_github_status(self) -> None:
        cfg = load_app_config()
        has_token = bool(cfg.github_token.strip())
        if has_token:
            gist_info = f" (Gist: {cfg.github_gist_id[:8]}...)" if cfg.github_gist_id else ""
            self.lbl_sync_status.setText(f"Verbunden{gist_info}")
            self.lbl_sync_status.setStyleSheet("""
                QLabel {
                    background-color: rgba(35, 134, 54, 0.18);
                    color: #3FB950;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 4px 10px;
                    border-radius: 6px;
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
                    font-size: 11px;
                    font-weight: 600;
                    padding: 4px 10px;
                    border-radius: 6px;
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
            if has_existing else
            "Gib dein GitHub Personal Access Token ein (Berechtigung: 'gist'):\n\n"
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
                self._append_log("GitHub: Token entfernt.")
            self._refresh_github_status()

    def _push_to_github(self) -> None:
        self.btn_push_gist.setEnabled(False)
        self.btn_pull_gist.setEnabled(False)
        self.lbl_sync_status.setText("Sichere Daten in GitHub Gist...")
        self.lbl_sync_status.setStyleSheet("""
            QLabel {
                background-color: rgba(227, 179, 65, 0.18);
                color: #E3B341;
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
                border-radius: 6px;
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
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
                border-radius: 6px;
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

    def _check_github_updates(self) -> None:
        self._append_log(f"Updater: Prüfe Releases auf Florian306/Campus-Bibliothek...")
        avail, latest, url, notes = check_for_updates()
        if avail and latest and url:
            self._append_log(f"Updater: Neues Update verfügbar (v{latest})!")
            box = QMessageBox(self)
            box.setWindowTitle("Update verfügbar!")
            box.setIcon(QMessageBox.Information)
            box.setText(f"Eine neuere Version von Campus-Bibliothek ist verfügbar: <b>v{latest}</b> (Aktuell: v{CURRENT_VERSION})")
            box.setInformativeText(f"Möchtest du das Update jetzt direkt automatisch herunterladen und installieren?\n\nÄnderungen:\n{notes[:300]}")
            
            btn_auto = box.addButton("Jetzt automatisch aktualisieren", QMessageBox.AcceptRole)
            btn_github = box.addButton("Release-Seite öffnen", QMessageBox.ActionRole)
            btn_cancel = box.addButton("Später", QMessageBox.RejectRole)
            
            box.exec()
            clicked = box.clickedButton()
            if clicked == btn_auto:
                from ui.qt.dialogs.auto_updater_dialog import UpdateProgressDialog
                dlg = UpdateProgressDialog(self, url, latest)
                dlg.exec()
            elif clicked == btn_github:
                import webbrowser
                webbrowser.open(f"https://github.com/Florian306/Campus-Bibliothek/releases/tag/v{latest}")
        elif latest:
            self._append_log(f"Updater: Du verwendest bereits die neueste Version (v{CURRENT_VERSION}).")
            QMessageBox.information(self, "Aktuell", f"Du verwendest bereits die neueste Version (v{CURRENT_VERSION}).")
        else:
            if notes and ("http" in notes.lower() or "error" in notes.lower() or "failed" in notes.lower()):
                friendly = humanize_error(notes, "Update-Prüfung")
                self._append_log(f"Updater: {friendly.replace(chr(10), ' ')}")
                QMessageBox.warning(self, "Verbindungsfehler beim Update-Check", friendly)
            else:
                self._append_log("Updater: Keine neueren Versionen gefunden.")
                QMessageBox.information(self, "Updates", f"Aktuelle Version: v{CURRENT_VERSION}\n\nEs wurden keine neueren Versionen gefunden.")
