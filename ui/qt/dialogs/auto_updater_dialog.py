"""In-App Auto-Update Downloader and Installer for Campus-Bibliothek.
Downloads the release setup executable into the local temp directory,
shows download progress, executes the installer, and gracefully terminates the running app.
"""

import os
import sys
import subprocess
import tempfile
import urllib.request
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QMessageBox,
)
from PySide6.QtGui import QFont

from ui.qt.icons import create_vector_icon


class UpdateDownloadThread(QThread):
    progress = Signal(int, int)  # downloaded_bytes, total_bytes
    finished = Signal(str)       # path to downloaded file
    error = Signal(str)

    def __init__(self, download_url: str, version_tag: str):
        super().__init__()
        self.download_url = download_url
        self.version_tag = version_tag
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": "Campus-Bibliothek-Updater"},
            )

            temp_dir = tempfile.gettempdir()
            ext = ".zip" if self.download_url.lower().endswith(".zip") else ".exe"
            filename = f"Campus-Bibliothek-Update-v{self.version_tag}{ext}"
            target_path = os.path.join(temp_dir, filename)

            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                chunk_size = 64 * 1024  # 64 KB

                with open(target_path, "wb") as f:
                    while True:
                        if self._is_cancelled:
                            return
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size)

            if not self._is_cancelled:
                self.finished.emit(target_path)
        except Exception as e:
            self.error.emit(str(e))


class UpdateProgressDialog(QDialog):
    """Modern progress dialog for downloading and launching the updater."""

    def __init__(self, parent, download_url: str, version_tag: str):
        super().__init__(parent)
        self.download_url = download_url
        self.version_tag = version_tag
        self.downloaded_file = ""

        self.setWindowTitle(f"Campus-Bibliothek AI – Update auf v{version_tag}")
        self.setFixedSize(460, 210)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #0D1117;
                color: #C9D1D9;
            }
        """)

        self._build_ui()
        self._start_download()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header_layout = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(create_vector_icon("sync", "#58A6FF", 26).pixmap(26, 26))
        header_layout.addWidget(icon_lbl)

        title_vbox = QVBoxLayout()
        title_lbl = QLabel(f"Aktualisierung auf v{self.version_tag}")
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title_lbl.setStyleSheet("color: #F0F6FC;")
        title_vbox.addWidget(title_lbl)

        self.status_lbl = QLabel("Verbindung zu GitHub wird hergestellt...")
        self.status_lbl.setFont(QFont("Segoe UI", 9))
        self.status_lbl.setStyleSheet("color: #8B949E;")
        title_vbox.addWidget(self.status_lbl)

        header_layout.addLayout(title_vbox)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(12)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet("""
            QProgressBar {
                background-color: #21262D;
                border: 1px solid #30363D;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #58A6FF);
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.bar)

        self.details_lbl = QLabel("0 MB / 0 MB")
        self.details_lbl.setFont(QFont("Segoe UI", 9))
        self.details_lbl.setStyleSheet("color: #8B949E;")
        layout.addWidget(self.details_lbl)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton("Abbrechen")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #21262D;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 5px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #30363D;
                color: #FFFFFF;
            }
        """)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    def _start_download(self):
        self.thread = UpdateDownloadThread(self.download_url, self.version_tag)
        self.thread.progress.connect(self._on_progress)
        self.thread.finished.connect(self._on_finished)
        self.thread.error.connect(self._on_error)
        self.thread.start()

    def _on_progress(self, current: int, total: int):
        cur_mb = current / (1024 * 1024)
        if total > 0:
            tot_mb = total / (1024 * 1024)
            pct = int((current / total) * 100)
            self.bar.setValue(pct)
            self.status_lbl.setText(f"Lade Installationspaket herunter ({pct}%)...")
            self.details_lbl.setText(f"{cur_mb:.1f} MB von {tot_mb:.1f} MB")
        else:
            self.status_lbl.setText("Lade Installationspaket herunter...")
            self.details_lbl.setText(f"{cur_mb:.1f} MB")

    def _on_finished(self, target_path: str):
        self.downloaded_file = target_path
        self.bar.setValue(100)
        self.status_lbl.setText("Download abgeschlossen! Starte Installation...")
        self.details_lbl.setText("Das Programm wird nun neu gestartet.")
        # Launch either the Delta Patch replacement or the full silent installer
        try:
            if target_path.lower().endswith(".zip"):
                # Fast Delta Patch: Extract zip into application directory and restart
                app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                exe_path = os.path.join(app_dir, "Buchsortierer.exe")
                
                # We spawn a detached PowerShell script that waits 1.5s for this process to exit,
                # extracts the patch files over the app directory, and relaunches the app.
                ps_script = (
                    f"Start-Sleep -Milliseconds 1500; "
                    f"Expand-Archive -Path '{target_path}' -DestinationPath '{app_dir}' -Force; "
                    f"Start-Process -FilePath '{exe_path}'; "
                    f"Remove-Item -Path '{target_path}' -Force -ErrorAction SilentlyContinue"
                )
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )
                sys.exit(0)
            else:
                # /VERYSILENT: Komplett unsichtbare Hintergrundinstallation (kein Setup-Fenster)
                # /SP-: Keine Bestätigung für Sprache / Start
                # /CLOSEAPPLICATIONS: Schließt alte Instanzen sauber
                # /FORCECLOSEAPPLICATIONS: Verhindert Sperrung von Dateien
                cmd = [target_path, "/VERYSILENT", "/SP-", "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS"]
                subprocess.Popen(cmd)
                sys.exit(0)
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Ausführen des Updates", f"Konnte {target_path} nicht installieren:\n{e}")
            self.reject()

    def _on_error(self, err_msg: str):
        QMessageBox.critical(self, "Download-Fehler", f"Das Update konnte nicht geladen werden:\n{err_msg}")
        self.reject()

    def _on_cancel(self):
        if hasattr(self, "thread") and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait(2000)
        self.reject()
