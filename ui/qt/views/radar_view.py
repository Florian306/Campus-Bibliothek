"""Edition Sentinel and Duplicate Finder View for PySide6.
Tracks newer textbook editions via Google Books/DNB and detects duplicate files.
"""

import threading
from typing import Any, Dict, List
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QProgressBar,
)

from ui.qt.icons import create_vector_icon
from ui.qt.theme import NoFocusItemDelegate
from core.library_db import get_all_books, get_edition_alerts, open_pdf_in_edge


class EditionScanSignals(QObject):
    """Signals for thread-safe background edition checks."""
    progress = Signal(int, int, str)
    finished = Signal(int)
    error = Signal(str)


class RadarView(QWidget):
    """View monitoring outdated textbook editions and detecting duplicate PDFs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "editions"  # 'editions' vs. 'duplicates'
        self._duplicate_filter = "all"
        self._alerts: List[Dict[str, Any]] = []
        self._duplicates: List[Dict[str, Any]] = []
        self._scan_thread = None

        self._signals = EditionScanSignals()
        self._signals.progress.connect(self._on_check_progress)
        self._signals.finished.connect(self._on_check_finished)
        self._signals.error.connect(self._on_check_error)

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 22, 24, 20)
        main_layout.setSpacing(14)

        # Header Bar
        top_bar = QHBoxLayout()

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        self.lbl_title = QLabel("Auflagen-Radar & Literatur-Aktualität")
        self.lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.lbl_title.setStyleSheet("color: #F0F6FC;")
        title_box.addWidget(self.lbl_title)

        self.lbl_sub = QLabel("Automatischer Abgleich gegen Kataloge & Erkennung redundanter Dubletten")
        self.lbl_sub.setFont(QFont("Segoe UI", 9))
        self.lbl_sub.setStyleSheet("color: #8B949E;")
        title_box.addWidget(self.lbl_sub)
        top_bar.addLayout(title_box)

        top_bar.addStretch()

        # Mode switcher buttons
        switch_frame = QWidget()
        switch_frame.setStyleSheet("""
            QWidget {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
            }
        """)
        switch_layout = QHBoxLayout(switch_frame)
        switch_layout.setContentsMargins(3, 3, 3, 3)
        switch_layout.setSpacing(4)

        self.btn_mode_editions = QPushButton("  Auflagen-Radar")
        self.btn_mode_editions.setIcon(create_vector_icon("radar", "#FFFFFF", 16))
        self.btn_mode_editions.setCursor(Qt.PointingHandCursor)
        self.btn_mode_editions.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD); color: #FFFFFF; font-weight: bold; border: none; border-radius: 5px; padding: 6px 14px;")
        self.btn_mode_editions.clicked.connect(lambda: self._set_mode("editions"))
        switch_layout.addWidget(self.btn_mode_editions)

        self.btn_mode_duplicates = QPushButton("  Dubletten-Finder")
        self.btn_mode_duplicates.setIcon(create_vector_icon("notes", "#8B949E", 16))
        self.btn_mode_duplicates.setCursor(Qt.PointingHandCursor)
        self.btn_mode_duplicates.setStyleSheet("background-color: transparent; color: #8B949E; border: none; border-radius: 5px; padding: 6px 14px;")
        self.btn_mode_duplicates.clicked.connect(lambda: self._set_mode("duplicates"))
        switch_layout.addWidget(self.btn_mode_duplicates)

        top_bar.addWidget(switch_frame)

        self.btn_action = QPushButton("  Auflagen online abgleichen")
        self.btn_action.setIcon(create_vector_icon("sync", "#FFFFFF", 16))
        self.btn_action.setObjectName("primaryButton")
        self.btn_action.setCursor(Qt.PointingHandCursor)
        self.btn_action.setFixedHeight(36)
        self.btn_action.clicked.connect(self._on_action_clicked)
        top_bar.addWidget(self.btn_action)

        main_layout.addLayout(top_bar)

        # Status / Progress banner (hidden by default)
        self.status_bar_container = QWidget()
        self.status_bar_container.setVisible(False)
        self.status_bar_container.setStyleSheet("""
            QWidget {
                background-color: #161B22;
                border: 1px solid #30363D;
                border-radius: 6px;
                padding: 4px 8px;
            }
        """)
        status_layout = QHBoxLayout(self.status_bar_container)
        status_layout.setContentsMargins(10, 4, 10, 4)
        status_layout.setSpacing(10)

        self.lbl_status = QLabel("Bereit")
        self.lbl_status.setStyleSheet("color: #58A6FF; font-size: 11px; font-weight: 600; border: none;")
        status_layout.addWidget(self.lbl_status, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0D1117;
                border: 1px solid #232F48;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #58A6FF);
                border-radius: 3px;
            }
        """)
        status_layout.addWidget(self.progress_bar)

        # Filter Chips Bar for Duplicates (All, Identical, Multi-volume, Chapters)
        self.filter_bar_container = QWidget()
        self.filter_bar_container.setVisible(False)
        self.filter_bar_container.setStyleSheet("background: transparent; border: none;")
        filter_layout = QHBoxLayout(self.filter_bar_container)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(6)

        lbl_filter = QLabel("Kategorie-Filter:")
        lbl_filter.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        filter_layout.addWidget(lbl_filter)

        self.btn_f_all = QPushButton("Alle Funde")
        self.btn_f_dupes = QPushButton("Echte Dubletten")
        self.btn_f_vols = QPushButton("Mehrbändige Werke (Bände)")
        self.btn_f_chaps = QPushButton("Buch-Einzelkapitel")

        self._filter_btns = [
            (self.btn_f_all, "all"),
            (self.btn_f_dupes, "duplicates_only"),
            (self.btn_f_vols, "multi_volume"),
            (self.btn_f_chaps, "chapters"),
        ]

        for btn, mode in self._filter_btns:
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda checked=False, m=mode: self._set_duplicate_filter(m))
            filter_layout.addWidget(btn)

        filter_layout.addStretch()
        main_layout.addWidget(self.filter_bar_container)

        # Main Table
        self.table_radar = QTableWidget()
        self.table_radar.setItemDelegate(NoFocusItemDelegate(self.table_radar))
        self.table_radar.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_radar.setSelectionMode(QTableWidget.SingleSelection)
        self.table_radar.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_radar.verticalHeader().setVisible(False)
        self.table_radar.cellDoubleClicked.connect(self._on_row_double_clicked)
        main_layout.addWidget(self.table_radar, stretch=1)

    def load_data(self) -> None:
        """Loads alerts or duplicates according to active mode."""
        if self.mode == "editions":
            self._load_editions()
        else:
            self._load_duplicates()

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "editions":
            self.lbl_title.setText("Auflagen-Radar & Neuauflagen-Sentinel")
            self.btn_mode_editions.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD); color: #FFFFFF; font-weight: bold; border: none; border-radius: 5px; padding: 6px 14px;")
            self.btn_mode_duplicates.setStyleSheet("background-color: transparent; color: #8B949E; border: none; border-radius: 5px; padding: 6px 14px;")
            self.btn_action.setText("  Auflagen online abgleichen")
            if hasattr(self, "filter_bar_container"):
                self.filter_bar_container.setVisible(False)
        else:
            self.lbl_title.setText("Dubletten-Finder (Identische Bücher & Werkbände)")
            self.btn_mode_duplicates.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD); color: #FFFFFF; font-weight: bold; border: none; border-radius: 5px; padding: 6px 14px;")
            self.btn_mode_editions.setStyleSheet("background-color: transparent; color: #8B949E; border: none; border-radius: 5px; padding: 6px 14px;")
            self.btn_action.setText("  Bibliothek nach Dubletten scannen")
            if hasattr(self, "filter_bar_container"):
                self.filter_bar_container.setVisible(True)
                self._update_filter_button_styles()
        self.load_data()

    def _set_duplicate_filter(self, filter_mode: str) -> None:
        self._duplicate_filter = filter_mode
        self._update_filter_button_styles()
        self._load_duplicates()

    def _update_filter_button_styles(self) -> None:
        active_chip = "background-color: #1F6FEB; color: #FFFFFF; font-weight: bold; font-size: 11px; border: 1px solid #388BFD; border-radius: 13px; padding: 2px 12px;"
        inactive_chip = "background-color: #121826; color: #8B949E; font-size: 11px; border: 1px solid #232F48; border-radius: 13px; padding: 2px 12px;"
        for btn, m in getattr(self, "_filter_btns", []):
            btn.setStyleSheet(active_chip if m == self._duplicate_filter else inactive_chip)

    def _load_editions(self) -> None:
        self._alerts = get_edition_alerts()
        self.table_radar.setColumnCount(6)
        self.table_radar.setHorizontalHeaderLabels(["Buchtitel", "Autor", "Vorhandene Auflage", "Verfügbare Neuauflage", "Status", "Quelle"])
        self.table_radar.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_radar.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_radar.setRowCount(len(self._alerts))

        for r, a in enumerate(self._alerts):
            self.table_radar.setItem(r, 0, QTableWidgetItem(a.get("title", "")))
            self.table_radar.setItem(r, 1, QTableWidgetItem(a.get("author", "")))

            c_ed = f"{a.get('current_edition', 1)}. Auflage"
            item_c = QTableWidgetItem(c_ed)
            item_c.setTextAlignment(Qt.AlignCenter)
            self.table_radar.setItem(r, 2, item_c)

            l_ed = f"{a.get('latest_edition', 1)}. Auflage ({a.get('latest_year') or 'Neu'})"
            item_l = QTableWidgetItem(l_ed)
            item_l.setTextAlignment(Qt.AlignCenter)
            self.table_radar.setItem(r, 3, item_l)

            diff_cnt = a.get("latest_edition", 1) - a.get("current_edition", 1)
            diff_str = f"+{diff_cnt} Neuauflage{'n' if diff_cnt > 1 else ''}"
            item_d = QTableWidgetItem(diff_str)
            item_d.setTextAlignment(Qt.AlignCenter)
            item_d.setForeground(QColor("#F0883E"))
            self.table_radar.setItem(r, 4, item_d)

            self.table_radar.setItem(r, 5, QTableWidgetItem(a.get("source", "DNB / Google")))

    def _load_duplicates(self) -> None:
        from core.duplicate_finder import find_library_duplicates
        dupes_groups = find_library_duplicates(filter_mode=self._duplicate_filter)
        self._duplicates = []
        for g in dupes_groups:
            reason = g["reason"]
            cat = g.get("category", "identical_duplicate")
            for b in g["books"]:
                self._duplicates.append({"book": b, "reason": reason, "category": cat})

        self.table_radar.setColumnCount(5)
        self.table_radar.setHorizontalHeaderLabels(["Buchtitel", "Autor", "Auflage / Seiten", "Kategorie & Zuordnung", "Dateigröße"])
        self.table_radar.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_radar.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_radar.setRowCount(len(self._duplicates))

        cat_colors = {
            "identical_duplicate": "#F85149",  # Red / Warning
            "multi_volume": "#58A6FF",         # Blue / Info
            "book_chapters": "#D29922",        # Orange-Yellow / Notice
        }

        for r, item in enumerate(self._duplicates):
            b = item["book"]
            reason = item["reason"]
            cat = item.get("category", "identical_duplicate")
            
            self.table_radar.setItem(r, 0, QTableWidgetItem(b.get("title", "")))
            self.table_radar.setItem(r, 1, QTableWidgetItem(b.get("author", "")))

            ed_str = f"{b.get('edition', 1)}. Aufl. ({b.get('page_count', '?')} S.)"
            item_ed = QTableWidgetItem(ed_str)
            item_ed.setTextAlignment(Qt.AlignCenter)
            self.table_radar.setItem(r, 2, item_ed)

            item_reason = QTableWidgetItem(reason)
            color_hex = cat_colors.get(cat, "#C9D1D9")
            item_reason.setForeground(QColor(color_hex))
            self.table_radar.setItem(r, 3, item_reason)

            size_mb = f"{b.get('file_size', 0) / (1024*1024):.1f} MB"
            item_size = QTableWidgetItem(size_mb)
            item_size.setTextAlignment(Qt.AlignCenter)
            self.table_radar.setItem(r, 4, item_size)

    def _on_action_clicked(self) -> None:
        if self.mode == "editions":
            self._start_online_check()
        else:
            self._load_duplicates()
            QMessageBox.information(
                self,
                "Dubletten-Scan",
                f"{len(self._duplicates)} Einträge in der gewählten Kategorie ({self._duplicate_filter}) gefunden."
            )

    def _start_online_check(self) -> None:
        if self._scan_thread and self._scan_thread.is_alive():
            return

        self.btn_action.setEnabled(False)
        self.btn_action.setText("  Prüfe online...")
        self.status_bar_container.setVisible(True)
        self.lbl_status.setText("Initialisiere Online-Abfrage gegen Google Books / DNB...")
        self.progress_bar.setValue(0)

        def worker():
            try:
                from ai.edition_checker import check_for_newer_edition
                import time
                books = get_all_books()
                # Limit scan batch to 30 relevant books for fast responsive check
                target_books = [b for b in books if b.get("title") and len(b.get("title", "")) > 4][:30]
                total = len(target_books)
                found = 0

                if total == 0:
                    self._signals.finished.emit(0)
                    return

                for idx, b in enumerate(target_books):
                    title_snippet = (b.get("title") or "")[:28]
                    self._signals.progress.emit(idx + 1, total, title_snippet)
                    res = check_for_newer_edition(b, timeout=3.5)
                    if res:
                        found += 1
                    time.sleep(0.15)  # gentle rate limit against Google Books API

                self._signals.finished.emit(found)
            except Exception as e:
                self._signals.error.emit(str(e))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    def _on_check_progress(self, current: int, total: int, title: str) -> None:
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(f"Prüfe {current}/{total}: «{title}»...")

    def _on_check_finished(self, found: int) -> None:
        self.btn_action.setEnabled(True)
        self.btn_action.setText("  Auflagen online abgleichen")
        self.progress_bar.setValue(100)
        if found > 0:
            self.lbl_status.setText(f"✓ Abgleich abgeschlossen: {found} neuere Auflagen im Bestand aufgespürt!")
        else:
            self.lbl_status.setText("✓ Abgleich abgeschlossen: Alle geprüften Lehrbücher sind aktuell.")
        self._load_editions()

    def _on_check_error(self, err_msg: str) -> None:
        self.btn_action.setEnabled(True)
        self.btn_action.setText("  Auflagen online abgleichen")
        self.lbl_status.setText(f"Hinweis: Online-Katalog temporär nicht erreichbar ({err_msg[:40]})")

    def _on_row_double_clicked(self, row: int, col: int) -> None:
        if self.mode == "editions" and 0 <= row < len(self._alerts):
            bid = str(self._alerts[row]["book_id"])
            books = get_all_books()
            book = next((b for b in books if str(b["id"]) == bid), None)
            if book and book.get("file_path"):
                open_pdf_in_edge(book["file_path"])
        elif self.mode == "duplicates" and 0 <= row < len(self._duplicates):
            b = self._duplicates[row]["book"]
            if b.get("file_path"):
                open_pdf_in_edge(b["file_path"])
