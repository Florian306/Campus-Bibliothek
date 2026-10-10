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
    """Interactive drag and drop target container for PDF files."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121826, stop:1 #162035);
                border: 2px dashed #2E4268;
                border-radius: 10px;
                padding: 16px;
            }
            QFrame:hover {
                border-color: #58A6FF;
                background-color: #17243B;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QFrame {
                    background-color: #1D2D4A;
                    border: 2px dashed #58A6FF;
                    border-radius: 10px;
                    padding: 16px;
                }
            """)

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121826, stop:1 #162035);
                border: 2px dashed #2E4268;
                border-radius: 10px;
                padding: 16px;
            }
        """)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        files = []
        for u in urls:
            path = u.toLocalFile()
            if path and os.path.exists(path) and path.lower().endswith(".pdf"):
                files.append(path)
        self.dragLeaveEvent(event)
        if files:
            self.files_dropped.emit(files)


class InboxView(QWidget):
    """Staging and Intake Hub for new books."""
    queue_updated = Signal(int)  # emits count of remaining items
    book_filed = Signal()        # emits when a book was filed into the main catalog

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inbox_dir = get_inbox_directory()
        self.storage_dir = get_books_storage_dir()
        self._analysis_thread: Optional[InboxAnalysisWorker] = None
        self._items: List[Dict] = []

        self._build_ui()
        self.sync_filesystem_with_db()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        # Header Title Row
        top_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        self.lbl_title = QLabel("📥 Buch-Posteingang & Staging-Hub")
        self.lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.lbl_title.setStyleSheet("color: #F0F6FC;")
        title_box.addWidget(self.lbl_title)

        lbl_sub = QLabel(f"Warteschlange für Neuanschaffungen • Persistenter Staging-Ordner: {self.inbox_dir}")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_box.addWidget(lbl_sub)
        top_row.addLayout(title_box)
        top_row.addStretch()

        btn_open_folder = QPushButton("  _Inbox im Explorer öffnen")
        btn_open_folder.setIcon(create_vector_icon("export", "#58A6FF", 14))
        btn_open_folder.setCursor(Qt.PointingHandCursor)
        btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: #141C2E;
                color: #C9D1D9;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1A253D;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_open_folder.clicked.connect(self._open_inbox_in_explorer)
        top_row.addWidget(btn_open_folder)

        btn_refresh = QPushButton("  Neu scannen")
        btn_refresh.setIcon(create_vector_icon("sync", "#58A6FF", 14))
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #141C2E;
                color: #C9D1D9;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1A253D;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_refresh.clicked.connect(self.sync_filesystem_with_db)
        top_row.addWidget(btn_refresh)

        root.addLayout(top_row)

        # -------------------------------------------------------------
        # 1. Drag & Drop Dropzone
        # -------------------------------------------------------------
        self.drop_zone = DropZoneFrame()
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        dz_layout = QVBoxLayout(self.drop_zone)
        dz_layout.setContentsMargins(16, 14, 16, 14)
        dz_layout.setAlignment(Qt.AlignCenter)
        dz_layout.setSpacing(6)

        lbl_dz_icon = QLabel("📥")
        lbl_dz_icon.setStyleSheet("font-size: 26px; background: transparent; border: none;")
        lbl_dz_icon.setAlignment(Qt.AlignCenter)
        dz_layout.addWidget(lbl_dz_icon)

        lbl_dz_txt = QLabel("Neue PDF-Bücher einfach per Drag & Drop hierher ziehen")
        lbl_dz_txt.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_dz_txt.setStyleSheet("color: #F0F6FC; background: transparent; border: none;")
        lbl_dz_txt.setAlignment(Qt.AlignCenter)
        dz_layout.addWidget(lbl_dz_txt)

        lbl_dz_hint = QLabel("Die Dateien landen sicher in der Warteschlange und gehen auch beim Schließen nicht verloren.")
        lbl_dz_hint.setFont(QFont("Segoe UI", 9))
        lbl_dz_hint.setStyleSheet("color: #8B949E; background: transparent; border: none;")
        lbl_dz_hint.setAlignment(Qt.AlignCenter)
        dz_layout.addWidget(lbl_dz_hint)

        btn_select_files = QPushButton("Oder Dateien auswählen...")
        btn_select_files.setCursor(Qt.PointingHandCursor)
        btn_select_files.setFixedWidth(180)
        btn_select_files.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 5px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
                margin-top: 4px;
            }
            QPushButton:hover {
                background-color: #388BFD;
            }
        """)
        btn_select_files.clicked.connect(self._browse_and_add_files)
        dz_layout.addWidget(btn_select_files, alignment=Qt.AlignCenter)

        root.addWidget(self.drop_zone)

        # -------------------------------------------------------------
        # 2. Staging Queue Table
        # -------------------------------------------------------------
        queue_header = QHBoxLayout()
        self.lbl_queue_count = QLabel("Warteschlange (0 Bücher)")
        self.lbl_queue_count.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_queue_count.setStyleSheet("color: #F0F6FC;")
        queue_header.addWidget(self.lbl_queue_count)
        queue_header.addStretch()

        self.btn_batch_file = QPushButton("  ⚡ Alle Bereiten einsortieren")
        self.btn_batch_file.setIcon(create_vector_icon("check", "#FFFFFF", 14))
        self.btn_batch_file.setCursor(Qt.PointingHandCursor)
        self.btn_batch_file.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                border: 1px solid #2EA043;
                border-radius: 5px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2EA043;
            }
        """)
        self.btn_batch_file.clicked.connect(self._file_all_ready)
        queue_header.addWidget(self.btn_batch_file)

        root.addLayout(queue_header)

        self.table = QTableWidget()
        self.table.setItemDelegate(NoFocusItemDelegate(self.table))
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Vorschau & Titel", "Autor", "KI-Kategorie", "Status / Duplikat", "Dateigröße", "Aktion"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0E131F;
                color: #C9D1D9;
                border: 1px solid #1E283D;
                border-radius: 8px;
                gridline-color: #172033;
                selection-background-color: #1A2640;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #121826;
                color: #8B949E;
                border: none;
                border-bottom: 1px solid #1E283D;
                padding: 8px;
                font-weight: bold;
                font-size: 11px;
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
                except Exception as e:
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
        self.queue_updated.emit(len(self._items))

        all_cats = [c[0] for c in get_category_counts()] or STANDARD_CATEGORIES

        for row, it in enumerate(self._items):
            item_id = it["id"]
            # Col 0: Title Edit & Icon
            title_val = it.get("suggested_title") or it.get("filename", "")
            item_title = QTableWidgetItem(f"  📖 {title_val}")
            item_title.setToolTip(f"Datei: {it['filename']}\nKlicke zum Bearbeiten")
            self.table.setItem(row, 0, item_title)

            # Col 1: Author
            author_val = it.get("suggested_author") or "Unbekannt"
            item_author = QTableWidgetItem(author_val)
            self.table.setItem(row, 1, item_author)

            # Col 2: Category Combobox
            combo_cat = QComboBox()
            combo_cat.setStyleSheet("""
                QComboBox {
                    background-color: #141C2E;
                    color: #58A6FF;
                    border: 1px solid #232F48;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QComboBox::drop-down { border: none; }
            """)
            combo_cat.addItems(all_cats)
            cur_cat = it.get("suggested_category", "Sonstiges")
            idx = combo_cat.findText(cur_cat)
            if idx >= 0:
                combo_cat.setCurrentIndex(idx)
            combo_cat.currentTextChanged.connect(lambda txt, iid=item_id: update_inbox_item(iid, suggested_category=txt))
            self.table.setCellWidget(row, 2, combo_cat)

            # Col 3: Status / Duplicate Warning
            dup = it.get("duplicate_warning", "")
            conf = it.get("confidence", 0)
            status = it.get("status", "pending")
            status_box = QWidget()
            s_lay = QHBoxLayout(status_box)
            s_lay.setContentsMargins(6, 4, 6, 4)
            s_lay.setSpacing(6)

            if dup:
                lbl_dup = QLabel("⚠️ Duplikat")
                lbl_dup.setToolTip(dup)
                lbl_dup.setStyleSheet("color: #F0883E; font-weight: bold; background: #2B1E12; border: 1px solid #6E4016; border-radius: 4px; padding: 2px 6px; font-size: 11px;")
                s_lay.addWidget(lbl_dup)
            elif status == "ready":
                lbl_ready = QLabel(f"✓ Bereit ({conf}%)")
                lbl_ready.setStyleSheet("color: #3FB950; font-weight: bold; background: #0E2416; border: 1px solid #1E502C; border-radius: 4px; padding: 2px 6px; font-size: 11px;")
                s_lay.addWidget(lbl_ready)
            else:
                lbl_pend = QLabel("⏳ Analysiere...")
                lbl_pend.setStyleSheet("color: #8B949E; font-size: 11px;")
                s_lay.addWidget(lbl_pend)

            s_lay.addStretch()
            self.table.setCellWidget(row, 3, status_box)

            # Col 4: File Size
            sz_mb = it.get("file_size", 0) / (1024 * 1024)
            p_cnt = it.get("page_count", 0)
            sz_txt = f"{sz_mb:.1f} MB" + (f" ({p_cnt} S.)" if p_cnt > 0 else "")
            item_sz = QTableWidgetItem(sz_txt)
            item_sz.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item_sz)

            # Col 5: Action buttons
            act_box = QWidget()
            act_lay = QHBoxLayout(act_box)
            act_lay.setContentsMargins(4, 4, 4, 4)
            act_lay.setSpacing(6)

            btn_file = QPushButton("Einsortieren")
            btn_file.setCursor(Qt.PointingHandCursor)
            btn_file.setStyleSheet("""
                QPushButton {
                    background-color: #1F6FEB;
                    color: #FFFFFF;
                    border: 1px solid #388BFD;
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #388BFD;
                }
            """)
            btn_file.clicked.connect(lambda _, iid=item_id: self._file_single_book(iid))
            act_lay.addWidget(btn_file)

            btn_del = QPushButton("×")
            btn_del.setToolTip("Aus Posteingang entfernen")
            btn_del.setFixedSize(24, 24)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("""
                QPushButton {
                    color: #FF7B72;
                    background: transparent;
                    border: 1px solid #482329;
                    border-radius: 4px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #381920;
                    border-color: #F85149;
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
                    it_title = self.table.item(r, 0)
                    if it_title:
                        it_title.setText(f"  📖 {data['suggested_title']}")

                # Update author
                if data.get("suggested_author"):
                    it_auth = self.table.item(r, 1)
                    if it_auth:
                        it_auth.setText(data['suggested_author'])

                # Update category combo
                combo = self.table.cellWidget(r, 2)
                if isinstance(combo, QComboBox) and data.get("suggested_category"):
                    idx = combo.findText(data["suggested_category"])
                    if idx >= 0:
                        combo.setCurrentIndex(idx)

                # Update status box
                stat_box = self.table.cellWidget(r, 3)
                if stat_box:
                    dup = data.get("duplicate_warning", "")
                    conf = data.get("confidence", 0)
                    # Re-layout
                    lay = stat_box.layout()
                    while lay.count():
                        w = lay.takeAt(0).widget()
                        if w:
                            w.deleteLater()
                    if dup:
                        lbl_dup = QLabel("⚠️ Duplikat")
                        lbl_dup.setToolTip(dup)
                        lbl_dup.setStyleSheet("color: #F0883E; font-weight: bold; background: #2B1E12; border: 1px solid #6E4016; border-radius: 4px; padding: 2px 6px; font-size: 11px;")
                        lay.addWidget(lbl_dup)
                    else:
                        lbl_ready = QLabel(f"✓ Bereit ({conf}%)")
                        lbl_ready.setStyleSheet("color: #3FB950; font-weight: bold; background: #0E2416; border: 1px solid #1E502C; border-radius: 4px; padding: 2px 6px; font-size: 11px;")
                        lay.addWidget(lbl_ready)
                    lay.addStretch()

                # Update size/pages
                p_cnt = data.get("page_count", 0)
                if p_cnt > 0:
                    it_sz = self.table.item(r, 4)
                    if it_sz and "S." not in it_sz.text():
                        it_sz.setText(f"{it_sz.text()} ({p_cnt} S.)")
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
