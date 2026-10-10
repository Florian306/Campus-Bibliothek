"""Campus Inbox & Staging View for PySide6.
Provides an upload/drop-zone for newly acquired books, persistent queue handling (stored in SQLite),
instant front-cover/title extraction, AI faculty auto-assignment, duplicate detection,
and 1-click filing into the main library directory on Google Drive or local disk.
"""

import os
import shutil
import subprocess
from typing import Dict, List, Optional
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QFont, QColor, QImage, QPixmap, QIcon, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFrame,
    QComboBox,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QApplication,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate
from core.config import get_inbox_directory, get_books_storage_dir
from core.library_db import (
    add_to_inbox_queue,
    get_inbox_queue,
    update_inbox_item,
    delete_inbox_item,
    check_inbox_duplicate,
    upsert_book,
    get_category_counts,
)
from ai.pdf_extractor import extract_pdf_preview_text, extract_visual_title_and_author
from ai.classifier import classify_textbook
from ai.categories import STANDARD_CATEGORIES


class InboxAnalysisWorker(QThread):
    """Background worker analyzing unanalyzed files in the inbox queue without freezing UI."""
    item_analyzed = Signal(int, dict)  # item_id, analyzed_data
    all_finished = Signal()

    def __init__(self, items: List[Dict], existing_categories: List[str], parent=None):
        super().__init__(parent)
        self.items = items
        self.existing_categories = existing_categories
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            import fitz
        except ImportError:
            fitz = None

        for item in self.items:
            if self._is_cancelled:
                break
            item_id = item["id"]
            file_path = item["file_path"]
            fn = item["filename"]

            if not os.path.exists(file_path):
                continue

            extracted_title = ""
            extracted_author = ""
            page_count = 0

            # 1. Extract cover, title, author via PyMuPDF
            if fitz:
                try:
                    doc = fitz.open(file_path)
                    page_count = len(doc)
                    vt, va = extract_visual_title_and_author(doc)
                    extracted_title = vt or ""
                    extracted_author = va or ""
                    doc.close()
                except Exception:
                    pass

            if not extracted_title:
                clean_name = os.path.splitext(fn)[0]
                extracted_title = clean_name.replace("_", " ").replace("-", " ").strip()

            # 2. Extract preview text for faculty AI classification
            text_snippet = ""
            try:
                text_snippet = extract_pdf_preview_text(file_path)
            except Exception:
                pass

            suggested_cat, confidence, reason = classify_textbook(
                filename=fn,
                text=text_snippet,
                existing_folders=self.existing_categories
            )

            # 3. Check for duplicates
            dup_warning = check_inbox_duplicate(extracted_title, fn)

            analysis_result = {
                "suggested_title": extracted_title,
                "suggested_author": extracted_author or "Unbekannt",
                "suggested_category": suggested_cat or "Sonstiges",
                "confidence": confidence,
                "page_count": page_count,
                "duplicate_warning": dup_warning,
                "status": "ready"
            }

            # Update SQLite state immediately so progress survives interruptions
            update_inbox_item(
                item_id=item_id,
                suggested_title=extracted_title,
                suggested_author=extracted_author or "Unbekannt",
                suggested_category=suggested_cat,
                status="ready"
            )

            self.item_analyzed.emit(item_id, analysis_result)

        self.all_finished.emit()


class DropZoneFrame(QFrame):
    """Interactive drag and drop target container for PDF files with sleek modern aesthetics."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._apply_normal_style()

    def _apply_normal_style(self):
        self.setStyleSheet("""
            QFrame#inboxDropZone {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0.8, stop:0 #111726, stop:1 #151F33);
                border: 2px dashed #283856;
                border-radius: 12px;
            }
            QFrame#inboxDropZone:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0.8, stop:0 #141C30, stop:1 #1A2742);
                border: 2px dashed #58A6FF;
            }
        """)

    def _apply_hover_style(self):
        self.setStyleSheet("""
            QFrame#inboxDropZone {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0.8, stop:0 #192642, stop:1 #1E3259);
                border: 2px dashed #79C0FF;
                border-radius: 12px;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_hover_style()

    def dragLeaveEvent(self, event) -> None:
        self._apply_normal_style()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        files = []
        for u in urls:
            path = u.toLocalFile()
            if path and os.path.exists(path) and path.lower().endswith(".pdf"):
                files.append(path)
        self._apply_normal_style()
        if files:
            self.files_dropped.emit(files)


class InboxCoverWorker(QThread):
    """Generates small cover pixmaps asynchronously to keep the UI silky smooth."""
    cover_ready = Signal(int, QPixmap)  # item_id, pixmap

    def __init__(self, items: List[Dict], parent=None):
        super().__init__(parent)
        self.items = items
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        import fitz
        for it in self.items:
            if self._is_cancelled:
                break
            item_id = it.get("id")
            fp = it.get("file_path", "")
            if not fp or not os.path.exists(fp):
                continue
            try:
                doc = fitz.open(fp)
                if len(doc) > 0:
                    page = doc[0]
                    # Render 48x68 thumbnail
                    rect = page.rect
                    scale = 68.0 / max(rect.height, 1)
                    mat = fitz.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                    qpix = QPixmap.fromImage(img)
                    doc.close()
                    self.cover_ready.emit(item_id, qpix)
                else:
                    doc.close()
            except Exception:
                pass


class InboxView(QWidget):
    """Staging and Intake Hub for new books."""
    queue_updated = Signal(int)  # emits count of remaining items
    book_filed = Signal()        # emits when a book was filed into the main catalog

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inbox_dir = get_inbox_directory()
        self.storage_dir = get_books_storage_dir()
        self._analysis_thread: Optional[InboxAnalysisWorker] = None
        self._cover_thread: Optional[InboxCoverWorker] = None
        self._cover_cache: Dict[int, QPixmap] = {}
        self._items: List[Dict] = []

        self._build_ui()
        self.sync_filesystem_with_db()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        # -------------------------------------------------------------
        # 1. Header Banner Row
        # -------------------------------------------------------------
        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        icon_badge = QLabel()
        icon_badge.setPixmap(create_vector_pixmap("inbox", "#58A6FF", 24))
        icon_badge.setFixedSize(44, 44)
        icon_badge.setAlignment(Qt.AlignCenter)
        icon_badge.setStyleSheet("""
            background: #141E33;
            border: 1px solid #283856;
            border-radius: 10px;
        """)
        top_row.addWidget(icon_badge)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.lbl_title = QLabel("Buch-Posteingang & Staging-Hub")
        self.lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.lbl_title.setStyleSheet("color: #F0F6FC;")
        title_row.addWidget(self.lbl_title)

        self.lbl_badge_status = QLabel("Warteschlange")
        self.lbl_badge_status.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_badge_status.setStyleSheet("""
            background-color: #12213D;
            color: #58A6FF;
            border: 1px solid #284475;
            border-radius: 9px;
            padding: 2px 8px;
        """)
        title_row.addWidget(self.lbl_badge_status)
        title_row.addStretch()
        title_box.addLayout(title_row)

        lbl_sub = QLabel(f"Neuanschaffungen prüfen, klassifizieren und per 1-Klick in die Bibliothek einsortieren")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_box.addWidget(lbl_sub)
        top_row.addLayout(title_box)
        top_row.addStretch()

        btn_open_folder = QPushButton("  _Inbox im Explorer")
        btn_open_folder.setIcon(create_vector_icon("export", "#58A6FF", 13))
        btn_open_folder.setCursor(Qt.PointingHandCursor)
        btn_open_folder.setFixedHeight(34)
        btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: #121927;
                color: #C9D1D9;
                border: 1px solid #233148;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1B263B;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_open_folder.clicked.connect(self._open_inbox_in_explorer)
        top_row.addWidget(btn_open_folder)

        btn_refresh = QPushButton("  Neu scannen")
        btn_refresh.setIcon(create_vector_icon("sync", "#58A6FF", 13))
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setFixedHeight(34)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #121927;
                color: #C9D1D9;
                border: 1px solid #233148;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1B263B;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_refresh.clicked.connect(self.sync_filesystem_with_db)
        top_row.addWidget(btn_refresh)

        root.addLayout(top_row)

        # -------------------------------------------------------------
        # 2. Sleek Compact Drag & Drop Banner
        # -------------------------------------------------------------
        self.drop_zone = DropZoneFrame()
        self.drop_zone.setObjectName("inboxDropZone")
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.drop_zone.setFixedHeight(105)

        dz_layout = QHBoxLayout(self.drop_zone)
        dz_layout.setContentsMargins(24, 12, 24, 12)
        dz_layout.setSpacing(18)

        dz_icon_frame = QFrame()
        dz_icon_frame.setFixedSize(54, 54)
        dz_icon_frame.setStyleSheet("""
            background: #141E33;
            border: 1px solid #283856;
            border-radius: 27px;
        """)
        dz_icon_lay = QVBoxLayout(dz_icon_frame)
        dz_icon_lay.setContentsMargins(0, 0, 0, 0)
        dz_icon_lay.setAlignment(Qt.AlignCenter)
        lbl_dz_icon = QLabel()
        lbl_dz_icon.setPixmap(create_vector_pixmap("arrow_up", "#58A6FF", 22))
        lbl_dz_icon.setStyleSheet("border: none; background: transparent;")
        lbl_dz_icon.setAlignment(Qt.AlignCenter)
        dz_icon_lay.addWidget(lbl_dz_icon)
        dz_layout.addWidget(dz_icon_frame)

        dz_text_col = QVBoxLayout()
        dz_text_col.setContentsMargins(0, 0, 0, 0)
        dz_text_col.setSpacing(3)
        dz_text_col.setAlignment(Qt.AlignVCenter)

        lbl_dz_title = QLabel("PDF-Bücher einfach per Drag & Drop hier ablegen")
        lbl_dz_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_dz_title.setStyleSheet("color: #F0F6FC; background: transparent; border: none;")
        dz_text_col.addWidget(lbl_dz_title)

        lbl_dz_sub = QLabel(f"Wird automatisch in '{os.path.basename(self.inbox_dir)}' zwischengespeichert und per KI analysiert.")
        lbl_dz_sub.setFont(QFont("Segoe UI", 9))
        lbl_dz_sub.setStyleSheet("color: #8B949E; background: transparent; border: none;")
        dz_text_col.addWidget(lbl_dz_sub)

        dz_layout.addLayout(dz_text_col)
        dz_layout.addStretch()

        btn_select_files = QPushButton("  Dateien auswählen...")
        btn_select_files.setIcon(create_vector_icon("plus", "#FFFFFF", 12))
        btn_select_files.setCursor(Qt.PointingHandCursor)
        btn_select_files.setFixedHeight(36)
        btn_select_files.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #287FFB);
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 7px;
                padding: 0 16px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2C7DF4, stop:1 #3B8CFF);
                border-color: #58A6FF;
            }
        """)
        btn_select_files.clicked.connect(self._browse_and_add_files)
        dz_layout.addWidget(btn_select_files)

        root.addWidget(self.drop_zone)

        # -------------------------------------------------------------
        # 3. Staging Queue Section Header
        # -------------------------------------------------------------
        queue_header = QHBoxLayout()
        queue_header.setContentsMargins(0, 4, 0, 0)
        self.lbl_queue_count = QLabel("Warteschlange (0 Bücher)")
        self.lbl_queue_count.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_queue_count.setStyleSheet("color: #F0F6FC;")
        queue_header.addWidget(self.lbl_queue_count)

        self.lbl_queue_sub = QLabel("— Bereit zur Übernahme in den Bibliothekskatalog")
        self.lbl_queue_sub.setFont(QFont("Segoe UI", 9))
        self.lbl_queue_sub.setStyleSheet("color: #8B949E; margin-left: 4px;")
        queue_header.addWidget(self.lbl_queue_sub)
        queue_header.addStretch()

        self.btn_batch_file = QPushButton("  Alle Bereiten einsortieren")
        self.btn_batch_file.setIcon(create_vector_icon("check", "#FFFFFF", 14))
        self.btn_batch_file.setCursor(Qt.PointingHandCursor)
        self.btn_batch_file.setFixedHeight(34)
        self.btn_batch_file.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
                color: #FFFFFF;
                border: 1px solid #3FB950;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2EA043, stop:1 #3FB950);
                border-color: #56D364;
            }
            QPushButton:disabled {
                background: #17261D;
                color: #486A53;
                border: 1px solid #233D2D;
            }
        """)
        self.btn_batch_file.clicked.connect(self._file_all_ready)
        queue_header.addWidget(self.btn_batch_file)

        root.addLayout(queue_header)

        # -------------------------------------------------------------
        # 4. Premium Modern Table Widget
        # -------------------------------------------------------------
        self.table = QTableWidget()
        self.table.setItemDelegate(NoFocusItemDelegate(self.table))
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "VORSCHAU & BUCHT общеTITEL", "AUTOR", "KI-KATEGORIE", "STATUS / DUPLIKAT", "DATEIGRÖSSE", "AKTION"
        ])
        self.table.setHorizontalHeaderLabels([
            "BUCHTITEL & COVER", "AUTOR", "KI-KATEGORIE", "STATUS", "DATEIGRÖSSE", "AKTION"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)

        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 170)

        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0B0F19;
                color: #C9D1D9;
                border: 1px solid #1A2436;
                border-radius: 10px;
                selection-background-color: #141E33;
                selection-color: #F0F6FC;
                font-size: 12px;
                outline: none;
            }
            QTableWidget::item {
                border-bottom: 1px solid #141C2B;
                padding: 6px 8px;
            }
            QTableWidget::item:selected {
                background-color: #141E33;
            }
            QHeaderView::section {
                background-color: #101624;
                color: #7D8590;
                border: none;
                border-bottom: 1px solid #1E2B40;
                padding: 10px 8px;
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.5px;
            }
        """)
        root.addWidget(self.table, stretch=1)

    def _open_inbox_in_explorer(self) -> None:
        if os.path.exists(self.inbox_dir):
            os.startfile(self.inbox_dir)

    def _browse_and_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "PDF-Bücher zum Importieren auswählen", "", "PDF-Dateien (*.pdf)"
        )
        if files:
            self._on_files_dropped(files)

    def _on_files_dropped(self, files: List[str]) -> None:
        """Copies external files into the _Inbox directory and registers them in the persistent queue."""
        imported_count = 0
        for src in files:
            if not os.path.exists(src) or not src.lower().endswith(".pdf"):
                continue
            fn = os.path.basename(src)
            dest = os.path.join(self.inbox_dir, fn)

            # Avoid self-copy
            if os.path.abspath(src).lower() != os.path.abspath(dest).lower():
                # Handle filename collision
                base_name, ext = os.path.splitext(fn)
                counter = 1
                while os.path.exists(dest):
                    dest = os.path.join(self.inbox_dir, f"{base_name} ({counter}){ext}")
                    counter += 1
                try:
                    shutil.copy2(src, dest)
                except Exception:
                    continue

            add_to_inbox_queue(file_path=dest, status="pending")
            imported_count += 1

        if imported_count > 0:
            self.sync_filesystem_with_db()

    def sync_filesystem_with_db(self) -> None:
        """Scans the physical _Inbox directory on disk and reconciles with SQLite queue."""
        if not os.path.exists(self.inbox_dir):
            return

        # 1. Add any files found in the folder to DB if not present
        existing_in_db = {item["file_path"].lower(): item for item in get_inbox_queue()}
        for entry in os.listdir(self.inbox_dir):
            if entry.lower().endswith(".pdf"):
                full_p = os.path.abspath(os.path.join(self.inbox_dir, entry))
                if full_p.lower() not in existing_in_db:
                    add_to_inbox_queue(file_path=full_p, status="pending")

        # 2. Reload queue
        self._reload_table_data()

        # 3. Start background AI classification for items still marked 'pending'
        pending_items = [it for it in self._items if it.get("status") == "pending"]
        if pending_items:
            self._start_analysis_worker(pending_items)

        # 4. Generate small cover previews in background
        self._start_cover_worker(self._items)

    def _start_cover_worker(self, items: List[Dict]) -> None:
        needed = [it for it in items if it["id"] not in self._cover_cache]
        if not needed:
            return
        if self._cover_thread and self._cover_thread.isRunning():
            self._cover_thread.cancel()
            self._cover_thread.wait(200)
        self._cover_thread = InboxCoverWorker(needed, parent=self)
        self._cover_thread.cover_ready.connect(self._on_cover_ready)
        self._cover_thread.start()

    def _on_cover_ready(self, item_id: int, pixmap: QPixmap) -> None:
        self._cover_cache[item_id] = pixmap
        # Update row cell widget
        for r in range(self.table.rowCount()):
            if r < len(self._items) and self._items[r]["id"] == item_id:
                w = self.table.cellWidget(r, 0)
                if w:
                    lbl_icon = w.findChild(QLabel, "coverLabel")
                    if lbl_icon:
                        lbl_icon.setPixmap(pixmap.scaled(38, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                break

    def _create_title_widget(self, item: Dict) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 6, 8, 6)
        lay.setSpacing(12)

        item_id = item["id"]
        cover_lbl = QLabel()
        cover_lbl.setObjectName("coverLabel")
        cover_lbl.setFixedSize(38, 52)
        cover_lbl.setAlignment(Qt.AlignCenter)
        cover_lbl.setStyleSheet("""
            background: #141B2B;
            border: 1px solid #23334E;
            border-radius: 4px;
        """)

        if item_id in self._cover_cache:
            cover_lbl.setPixmap(self._cover_cache[item_id].scaled(38, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            cover_lbl.setPixmap(create_vector_pixmap("book", "#58A6FF", 18))

        lay.addWidget(cover_lbl)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        info_box.setAlignment(Qt.AlignVCenter)

        title_text = item.get("suggested_title") or os.path.splitext(item.get("filename", ""))[0]
        lbl_t = QLabel(title_text)
        lbl_t.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_t.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        lbl_t.setToolTip(f"Klicke zum Bearbeiten\nDateiname: {item.get('filename')}")
        info_box.addWidget(lbl_t)

        lbl_fn = QLabel(item.get("filename", ""))
        lbl_fn.setFont(QFont("Segoe UI", 8))
        lbl_fn.setStyleSheet("color: #6E7681; border: none; background: transparent;")
        info_box.addWidget(lbl_fn)

        lay.addLayout(info_box)
        lay.addStretch()
        return w

    def _reload_table_data(self) -> None:
        self._items = get_inbox_queue()
        # Filter out items whose files no longer exist on disk
        valid_items = []
        for it in self._items:
            if os.path.exists(it["file_path"]):
                valid_items.append(it)
            else:
                delete_inbox_item(it["id"])
        self._items = valid_items

        self.table.setRowCount(len(self._items))
        self.lbl_queue_count.setText(f"Warteschlange ({len(self._items)} Bücher)")
        self.btn_batch_file.setEnabled(len(self._items) > 0)
        self.queue_updated.emit(len(self._items))

        all_cats = [c[0] for c in get_category_counts()] or STANDARD_CATEGORIES

        for row, it in enumerate(self._items):
            item_id = it["id"]

            # Col 0: Styled Cover + Title Card Widget
            title_widget = self._create_title_widget(it)
            self.table.setCellWidget(row, 0, title_widget)

            # Col 1: Author (Editable LineEdit)
            author_edit = QLineEdit(it.get("suggested_author") or "Unbekannt")
            author_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #121A2A;
                    color: #C9D1D9;
                    border: 1px solid #23314A;
                    border-radius: 5px;
                    padding: 5px 8px;
                    font-size: 11px;
                }
                QLineEdit:focus {
                    border-color: #58A6FF;
                    background-color: #17243B;
                    color: #FFFFFF;
                }
            """)
            author_edit.textChanged.connect(lambda txt, iid=item_id: update_inbox_item(iid, suggested_author=txt))
            self.table.setCellWidget(row, 1, author_edit)

            # Col 2: Category Combobox
            combo_cat = QComboBox()
            combo_cat.setStyleSheet("""
                QComboBox {
                    background-color: #121A2A;
                    color: #58A6FF;
                    border: 1px solid #23314A;
                    border-radius: 5px;
                    padding: 5px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QComboBox:hover {
                    border-color: #58A6FF;
                }
                QComboBox::drop-down { border: none; }
                QComboBox QAbstractItemView {
                    background-color: #121A2A;
                    color: #C9D1D9;
                    selection-background-color: #1F6FEB;
                    selection-color: #FFFFFF;
                    border: 1px solid #23314A;
                    outline: none;
                }
            """)
            combo_cat.addItems(all_cats)
            cur_cat = it.get("suggested_category", "Sonstiges")
            idx = combo_cat.findText(cur_cat)
            if idx >= 0:
                combo_cat.setCurrentIndex(idx)
            combo_cat.currentTextChanged.connect(lambda txt, iid=item_id: update_inbox_item(iid, suggested_category=txt))
            self.table.setCellWidget(row, 2, combo_cat)

            # Col 3: Status / Duplicate Warning Badge
            dup = it.get("duplicate_warning", "")
            conf = it.get("confidence", 0)
            status = it.get("status", "pending")
            status_box = QWidget()
            s_lay = QHBoxLayout(status_box)
            s_lay.setContentsMargins(6, 4, 6, 4)
            s_lay.setAlignment(Qt.AlignCenter)

            if dup:
                lbl_dup = QLabel("⚠️ Duplikat")
                lbl_dup.setToolTip(dup)
                lbl_dup.setStyleSheet("""
                    color: #FFA657;
                    font-weight: bold;
                    background: #2D1A10;
                    border: 1px solid #633616;
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 10px;
                """)
                s_lay.addWidget(lbl_dup)
            elif status == "ready":
                lbl_ready = QLabel(f"✓ Bereit ({conf}%)")
                lbl_ready.setStyleSheet("""
                    color: #3FB950;
                    font-weight: bold;
                    background: #0D2616;
                    border: 1px solid #1E542C;
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 10px;
                """)
                s_lay.addWidget(lbl_ready)
            else:
                lbl_pend = QLabel("⏳ Analysiere...")
                lbl_pend.setStyleSheet("""
                    color: #8B949E;
                    background: #141C2B;
                    border: 1px solid #222F47;
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 10px;
                """)
                s_lay.addWidget(lbl_pend)

            self.table.setCellWidget(row, 3, status_box)

            # Col 4: File Size & Pages
            sz_mb = it.get("file_size", 0) / (1024 * 1024)
            p_cnt = it.get("page_count", 0)
            sz_txt = f"{sz_mb:.1f} MB\n{p_cnt} Seiten" if p_cnt > 0 else f"{sz_mb:.1f} MB"
            item_sz = QTableWidgetItem(sz_txt)
            item_sz.setTextAlignment(Qt.AlignCenter)
            item_sz.setFlags(item_sz.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 4, item_sz)

            # Col 5: Action buttons (Fixed width to avoid text truncation)
            act_box = QWidget()
            act_lay = QHBoxLayout(act_box)
            act_lay.setContentsMargins(6, 4, 6, 4)
            act_lay.setSpacing(6)
            act_lay.setAlignment(Qt.AlignCenter)

            btn_file = QPushButton(" Einsortieren")
            btn_file.setIcon(create_vector_icon("check", "#FFFFFF", 12))
            btn_file.setCursor(Qt.PointingHandCursor)
            btn_file.setFixedHeight(30)
            btn_file.setMinimumWidth(110)
            btn_file.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #287FFB);
                    color: #FFFFFF;
                    border: 1px solid #388BFD;
                    border-radius: 5px;
                    padding: 0 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2C7DF4, stop:1 #3B8CFF);
                    border-color: #58A6FF;
                }
            """)
            btn_file.clicked.connect(lambda _, iid=item_id: self._file_single_book(iid))
            act_lay.addWidget(btn_file)

            btn_del = QPushButton("×")
            btn_del.setToolTip("Aus Posteingang entfernen & Datei löschen")
            btn_del.setFixedSize(30, 30)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("""
                QPushButton {
                    color: #FF7B72;
                    background: #1C1417;
                    border: 1px solid #482329;
                    border-radius: 5px;
                    font-size: 15px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #381920;
                    border-color: #F85149;
                    color: #FFFFFF;
                }
            """)
            btn_del.clicked.connect(lambda _, iid=item_id: self._delete_item(iid))
            act_lay.addWidget(btn_del)

            self.table.setCellWidget(row, 5, act_box)

    def _start_analysis_worker(self, items: List[Dict]) -> None:
        if self._analysis_thread and self._analysis_thread.isRunning():
            return
        cats = [c[0] for c in get_category_counts()] or STANDARD_CATEGORIES
        self._analysis_thread = InboxAnalysisWorker(items, cats, parent=self)
        self._analysis_thread.item_analyzed.connect(self._on_item_analyzed)
        self._analysis_thread.all_finished.connect(self._on_all_analyzed)
        self._analysis_thread.start()

    def _on_item_analyzed(self, item_id: int, data: dict) -> None:
        # Update table row with analysis result
        for r in range(self.table.rowCount()):
            if r < len(self._items) and self._items[r]["id"] == item_id:
                # Update item title if changed
                if data.get("suggested_title"):
                    title_w = self.table.cellWidget(r, 0)
                    if title_w:
                        lbls = title_w.findChildren(QLabel)
                        if len(lbls) >= 2:
                            lbls[1].setText(data["suggested_title"])

                # Update author edit
                if data.get("suggested_author"):
                    auth_w = self.table.cellWidget(r, 1)
                    if isinstance(auth_w, QLineEdit):
                        auth_w.blockSignals(True)
                        auth_w.setText(data["suggested_author"])
                        auth_w.blockSignals(False)

                # Update category combo
                combo = self.table.cellWidget(r, 2)
                if isinstance(combo, QComboBox) and data.get("suggested_category"):
                    idx = combo.findText(data["suggested_category"])
                    if idx >= 0:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(idx)
                        combo.blockSignals(False)

                # Update status box
                stat_box = self.table.cellWidget(r, 3)
                if stat_box:
                    dup = data.get("duplicate_warning", "")
                    conf = data.get("confidence", 0)
                    lay = stat_box.layout()
                    while lay.count():
                        w = lay.takeAt(0).widget()
                        if w:
                            w.deleteLater()
                    if dup:
                        lbl_dup = QLabel("⚠️ Duplikat")
                        lbl_dup.setToolTip(dup)
                        lbl_dup.setStyleSheet("""
                            color: #FFA657;
                            font-weight: bold;
                            background: #2D1A10;
                            border: 1px solid #633616;
                            border-radius: 6px;
                            padding: 4px 8px;
                            font-size: 10px;
                        """)
                        lay.addWidget(lbl_dup)
                    else:
                        lbl_ready = QLabel(f"✓ Bereit ({conf}%)")
                        lbl_ready.setStyleSheet("""
                            color: #3FB950;
                            font-weight: bold;
                            background: #0D2616;
                            border: 1px solid #1E542C;
                            border-radius: 6px;
                            padding: 4px 8px;
                            font-size: 10px;
                        """)
                        lay.addWidget(lbl_ready)

                # Update size/pages
                p_cnt = data.get("page_count", 0)
                if p_cnt > 0:
                    it_sz = self.table.item(r, 4)
                    if it_sz and "Seiten" not in it_sz.text():
                        sz_mb = self._items[r].get("file_size", 0) / (1024 * 1024)
                        it_sz.setText(f"{sz_mb:.1f} MB\n{p_cnt} Seiten")
                break

    def _on_all_analyzed(self) -> None:
        self._items = get_inbox_queue()

    def _file_single_book(self, item_id: int) -> bool:
        """Moves the book into its chosen category folder and adds it to the SQLite catalog."""
        item = next((it for it in self._items if it["id"] == item_id), None)
        if not item:
            return False

        src_path = item["file_path"]
        if not os.path.exists(src_path):
            delete_inbox_item(item_id)
            self._reload_table_data()
            return False

        title = item.get("suggested_title") or item.get("filename", "")
        author = item.get("suggested_author") or "Unbekannt"
        category = item.get("suggested_category") or "Sonstiges"
        page_count = item.get("page_count", 0)
        file_size = item.get("file_size", 0)

        # 1. Target directory: G:\Meine Ablage\Bücher\<Category>
        target_dir = os.path.join(self.storage_dir, category)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            target_dir = self.storage_dir

        # 2. Build clean filename
        sanitized_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:80]
        sanitized_author = "".join(c for c in author if c not in r'\/:*?"<>|').strip()[:50]
        if sanitized_author and sanitized_author != "Unbekannt":
            target_filename = f"{sanitized_author} - {sanitized_title}.pdf"
        else:
            target_filename = f"{sanitized_title}.pdf"

        target_path = os.path.join(target_dir, target_filename)
        # Avoid overwriting
        counter = 1
        base_target, ext = os.path.splitext(target_filename)
        while os.path.exists(target_path):
            target_filename = f"{base_target} ({counter}){ext}"
            target_path = os.path.join(target_dir, target_filename)
            counter += 1

        # 3. Move physical file
        try:
            shutil.move(src_path, target_path)
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Verschieben", f"Konnte Datei nicht verschieben:\n{e}")
            return False

        # 4. Insert into main library database
        upsert_book(
            file_path=target_path,
            filename=target_filename,
            title=title,
            author=author,
            categories=[category],
            page_count=page_count,
            file_size=file_size,
            file_mtime=os.path.getmtime(target_path) if os.path.exists(target_path) else 0.0,
            confidence=item.get("confidence", 90),
            audit_trail="Importiert via Campus-Inbox"
        )

        # 5. Remove from inbox queue
        delete_inbox_item(item_id)
        self._reload_table_data()
        self.book_filed.emit()
        return True

    def _file_all_ready(self) -> None:
        """Batch-files all books that have been analyzed and are ready."""
        ready_items = [it for it in self._items if it.get("status") == "ready"]
        if not ready_items:
            QMessageBox.information(self, "Keine bereiten Bücher", "Es gibt derzeit keine analysierten Bücher zum Einsortieren.")
            return

        success_count = 0
        for it in ready_items:
            if self._file_single_book(it["id"]):
                success_count += 1

        QMessageBox.information(
            self,
            "Erfolgreich einsortiert",
            f"Es wurden {success_count} Buch/Bücher sauber in deine Bibliothek einsortiert!"
        )

    def _delete_item(self, item_id: int) -> None:
        ret = QMessageBox.question(
            self,
            "Buch verwerfen",
            "Möchtest du dieses Buch aus der Warteschlange entfernen und die Datei aus dem _Inbox-Ordner löschen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            delete_inbox_item(item_id, delete_file=True)
            self._reload_table_data()
