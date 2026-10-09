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
)

from ui.qt.icons import create_vector_icon
from core.config import load_config, save_config, load_app_config, save_app_config
from core.github_sync import GitHubSyncService
from core.update_checker import check_for_updates, CURRENT_VERSION


class ScanSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(dict)
    log_message = Signal(str)


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

        cfg = load_config()
        self.source_dir = cfg.get("last_directory") or r"G:\Meine Ablage\Bücher"
        if not os.path.exists(self.source_dir):
            self.source_dir = os.path.expanduser("~")

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 22, 24, 20)
        main_layout.setSpacing(14)

        # Title
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel("Scan & Sync Center (Data-Lake)")
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC;")
        title_box.addWidget(lbl_title)

        lbl_sub = QLabel("Inkrementeller Datenabgleich – Bereits katalogisierte Bücher werden in Millisekunden übersprungen")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_box.addWidget(lbl_sub)
        main_layout.addLayout(title_box)

        # 1. Source Folder Panel
        card_dir = QFrame()
        card_dir.setStyleSheet("""
            QFrame {
                background-color: #161B22;
                border: 1px solid #30363D;
                border-radius: 8px;
            }
        """)
        dir_layout = QVBoxLayout(card_dir)
        dir_layout.setContentsMargins(16, 14, 16, 14)
        dir_layout.setSpacing(8)

        lbl_dir_title = QLabel("Quellverzeichnis (Google Drive oder lokaler Ordner):")
        lbl_dir_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_dir_title.setStyleSheet("color: #F0F6FC; border: none;")
        dir_layout.addWidget(lbl_dir_title)

        dir_box = QHBoxLayout()
        self.lbl_path = QLabel(self.source_dir)
        self.lbl_path.setStyleSheet("""
            QLabel {
                background-color: #0D1117;
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 6px 10px;
                color: #F0F6FC;
            }
        """)
        dir_box.addWidget(self.lbl_path, stretch=1)

        btn_browse = QPushButton("Ordner wählen...")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self._choose_dir)
        dir_box.addWidget(btn_browse)

        dir_layout.addLayout(dir_box)
        main_layout.addWidget(card_dir)

        # 2. Delta-Scan Control Panel
        card_scan = QFrame()
        card_scan.setStyleSheet("""
            QFrame {
                background-color: #161B22;
                border: 1px solid #30363D;
                border-radius: 8px;
            }
        """)
        scan_layout = QVBoxLayout(card_scan)
        scan_layout.setContentsMargins(16, 14, 16, 14)
        scan_layout.setSpacing(10)

        lbl_scan_title = QLabel("Inkrementeller Delta-Scan:")
        lbl_scan_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_scan_title.setStyleSheet("color: #F0F6FC; border: none;")
        scan_layout.addWidget(lbl_scan_title)

        lbl_scan_sub = QLabel("Bereits erfasste PDFs werden in Millisekunden übersprungen. Nur neue oder geänderte Bücher werden verarbeitet.")
        lbl_scan_sub.setFont(QFont("Segoe UI", 9))
        lbl_scan_sub.setStyleSheet("color: #8B949E; border: none;")
        scan_layout.addWidget(lbl_scan_sub)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        scan_layout.addWidget(self.progress_bar)

        ctrl_row = QHBoxLayout()
        self.btn_start = QPushButton("  Delta-Scan starten")
        self.btn_start.setIcon(create_vector_icon("sync", "#FFFFFF", 16))
        self.btn_start.setObjectName("primaryButton")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._start_scan)
        ctrl_row.addWidget(self.btn_start)

        self.lbl_status = QLabel("Bereit für Delta-Scan")
        self.lbl_status.setStyleSheet("color: #8B949E; border: none; font-size: 11px;")
        ctrl_row.addWidget(self.lbl_status)
        ctrl_row.addStretch()

        scan_layout.addLayout(ctrl_row)
        main_layout.addWidget(card_scan)

        # -------------------------------------------------------------
        # 3. GitHub Cloud-Sync & Auto-Updates Card
        # -------------------------------------------------------------
        card_github = QFrame()
        card_github.setStyleSheet("""
            QFrame {
                background-color: #161B22;
                border: 1px solid #30363D;
                border-radius: 8px;
            }
        """)
        gh_layout = QVBoxLayout(card_github)
        gh_layout.setContentsMargins(16, 14, 16, 14)
        gh_layout.setSpacing(10)

        gh_header_row = QHBoxLayout()
        lbl_gh_title = QLabel("GitHub Cloud-Sync & Updates")
        lbl_gh_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_gh_title.setStyleSheet("color: #F0F6FC; border: none;")
        gh_header_row.addWidget(lbl_gh_title)

        lbl_app_ver = QLabel(f"Version: v{CURRENT_VERSION}")
        lbl_app_ver.setStyleSheet("color: #58A6FF; font-weight: bold; background: #0D1117; padding: 2px 8px; border-radius: 4px; border: 1px solid #30363D;")
        gh_header_row.addWidget(lbl_app_ver)
        gh_header_row.addStretch()

        btn_chk_update = QPushButton("  Auf Updates prüfen")
        btn_chk_update.setIcon(create_vector_icon("research", "#58A6FF", 14))
        btn_chk_update.setCursor(Qt.PointingHandCursor)
        btn_chk_update.setStyleSheet("""
            QPushButton {
                background-color: #21262D;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background-color: #30363D;
                color: #FFFFFF;
            }
        """)
        btn_chk_update.clicked.connect(self._check_github_updates)
        gh_header_row.addWidget(btn_chk_update)
        gh_layout.addLayout(gh_header_row)

        lbl_gh_sub = QLabel("Sichere deinen Lesefortschritt, Buch-Notizen und Kategorien in deinem privaten GitHub Gist.")
        lbl_gh_sub.setFont(QFont("Segoe UI", 9))
        lbl_gh_sub.setStyleSheet("color: #8B949E; border: none;")
        gh_layout.addWidget(lbl_gh_sub)

        # Sync buttons row
        gh_btns_row = QHBoxLayout()

        btn_token = QPushButton("GitHub Token einrichten...")
        btn_token.setCursor(Qt.PointingHandCursor)
        btn_token.setStyleSheet("""
            QPushButton {
                background-color: #21262D;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #30363D;
                color: #FFFFFF;
            }
        """)
        btn_token.clicked.connect(self._configure_github_token)
        gh_btns_row.addWidget(btn_token)

        self.btn_push_gist = QPushButton("  In Cloud sichern (Push)")
        self.btn_push_gist.setIcon(create_vector_icon("desk", "#3FB950", 14))
        self.btn_push_gist.setCursor(Qt.PointingHandCursor)
        self.btn_push_gist.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #2EA043;
                border-radius: 4px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #2EA043;
            }
        """)
        self.btn_push_gist.clicked.connect(self._push_to_github)
        gh_btns_row.addWidget(self.btn_push_gist)

        self.btn_pull_gist = QPushButton("  Aus Cloud laden (Pull)")
        self.btn_pull_gist.setIcon(create_vector_icon("sync", "#58A6FF", 14))
        self.btn_pull_gist.setCursor(Qt.PointingHandCursor)
        self.btn_pull_gist.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #388BFD;
                border-radius: 4px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #388BFD;
            }
        """)
        self.btn_pull_gist.clicked.connect(self._pull_from_github)
        gh_btns_row.addWidget(self.btn_pull_gist)

        self.lbl_sync_status = QLabel("Kein Token konfiguriert")
        self.lbl_sync_status.setStyleSheet("color: #8B949E; border: none; font-size: 11px;")
        gh_btns_row.addWidget(self.lbl_sync_status)
        gh_btns_row.addStretch()

        gh_layout.addLayout(gh_btns_row)
        main_layout.addWidget(card_github)
        self._refresh_github_status()

        # 3. Terminal Log
        card_log = QFrame()
        card_log.setStyleSheet("""
            QFrame {
                background-color: #161B22;
                border: 1px solid #30363D;
                border-radius: 8px;
            }
        """)
        log_layout = QVBoxLayout(card_log)
        log_layout.setContentsMargins(14, 12, 14, 12)
        log_layout.setSpacing(6)

        lbl_log_h = QLabel("Ereignis-Protokoll:")
        lbl_log_h.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_log_h.setStyleSheet("color: #F0F6FC; border: none;")
        log_layout.addWidget(lbl_log_h)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setFont(QFont("Consolas", 9))
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0D1117;
                color: #58A6FF;
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 6px;
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

    def _append_log(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{ts}] {text}")

    def _refresh_github_status(self) -> None:
        cfg = load_app_config()
        if cfg.github_token.strip():
            gist_info = f" (Gist: {cfg.github_gist_id[:8]}...)" if cfg.github_gist_id else ""
            self.lbl_sync_status.setText(f"Verbunden{gist_info}")
            self.lbl_sync_status.setStyleSheet("color: #3FB950; border: none; font-size: 11px;")
            self.btn_push_gist.setEnabled(True)
            self.btn_pull_gist.setEnabled(True)
        else:
            self.lbl_sync_status.setText("Kein Token konfiguriert")
            self.lbl_sync_status.setStyleSheet("color: #8B949E; border: none; font-size: 11px;")
            self.btn_push_gist.setEnabled(False)
            self.btn_pull_gist.setEnabled(False)

    def _configure_github_token(self) -> None:
        cfg = load_app_config()
        token, ok = QInputDialog.getText(
            self,
            "GitHub Personal Access Token",
            "Gib dein GitHub Personal Access Token ein (Berechtigung: 'gist'):\n\n"
            "Erstellen unter: github.com/settings/tokens (classic) -> Haken bei 'gist'",
            QLineEdit.Password,
            cfg.github_token,
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
        self._append_log("GitHub Sync: Starte Upload in privaten Gist...")
        success, msg = GitHubSyncService.push_to_gist()
        self._append_log(f"GitHub Sync: {msg}")
        self._refresh_github_status()
        if success:
            QMessageBox.information(self, "Cloud-Sicherung erfolgreich", msg)
        else:
            QMessageBox.critical(self, "Cloud-Sicherung fehlgeschlagen", msg)

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

        self._append_log("GitHub Sync: Lade Snapshot aus Gist...")
        success, msg = GitHubSyncService.pull_from_gist()
        self._append_log(f"GitHub Sync: {msg}")
        if success:
            self.scan_finished.emit()
            QMessageBox.information(self, "Synchronisation abgeschlossen", msg)
        else:
            QMessageBox.critical(self, "Download fehlgeschlagen", msg)

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
            msg = notes or "Kein Release gefunden."
            self._append_log(f"Updater: Keine neuen Releases gefunden ({msg}).")
            QMessageBox.information(self, "Updates", f"Aktuelle Version: v{CURRENT_VERSION}\n\nEs wurden keine neueren Versionen gefunden.")
