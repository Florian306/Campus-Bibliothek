"""Campus Inbox & Staging View for PySide6.
Provides an upload/drop-zone for newly acquired books, persistent queue handling (stored in SQLite),
instant front-cover/title extraction, AI faculty auto-assignment, duplicate detection,
and 1-click filing into the main library directory on Google Drive or local disk.
"""

import os
import shutil
import subprocess
from typing import Dict, List, Optional, Set
from PySide6.QtCore import Qt, QThread, Signal, QSize, QRect, QPoint, QModelIndex
from PySide6.QtGui import (
    QFont, QColor, QImage, QPixmap, QIcon, QDragEnterEvent, QDropEvent,
    QPainter, QPen, QBrush, QMouseEvent
)
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
    QCheckBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QLayout,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate
from core.config import get_inbox_directory, get_books_storage_dir, load_config, save_config
from core.library_db import (
    add_to_inbox_queue,
    get_inbox_queue,
    update_inbox_item,
    delete_inbox_item,
    check_inbox_duplicate,
    upsert_book,
    get_category_counts,
)
from ai.pdf_extractor import (
    extract_pdf_preview_text,
    extract_visual_title_and_author,
    sanitize_author_string,
    extract_publication_year,
)
from ai.isbn_lookup import extract_isbns, resolve_isbn_catalog
from ai.classifier import classify_textbook
from ai.categories import STANDARD_CATEGORIES
from core.delta_scanner import extract_edition_number
from core.cover_manager import extract_and_cache_cover


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
            front_text = ""

            # 1. Extract cover, title, author, edition, year, and ISBNs via PyMuPDF
            ed_num = 1
            ed_str = "1. Auflage"
            pub_year = None
            found_isbns = []

            if fitz:
                try:
                    doc = fitz.open(file_path)
                    page_count = len(doc)
                    vt, va = extract_visual_title_and_author(doc)
                    extracted_title = vt or ""
                    extracted_author = va or ""
                    # Grab first 8 pages text for ISBN, edition, year, and catalog identification
                    front_chunks = []
                    for p in range(min(8, page_count)):
                        front_chunks.append(doc[p].get_text("text"))
                    front_text = "\n".join(front_chunks)
                    
                    ed_num, ed_str = extract_edition_number(f"{fn}\n{extracted_title}\n{front_text}")
                    found_isbns = extract_isbns(f"ISBN {fn.replace('_', ' ')}\n{front_text}")
                    pub_year = extract_publication_year(front_text, doc.metadata, fn)
                    doc.close()
                except Exception:
                    pass

            # 2. Extract preview text for faculty AI classification
            text_snippet = ""
            try:
                text_snippet = extract_pdf_preview_text(file_path)
            except Exception:
                pass

            combined_lookup_text = f"{fn}\n{front_text}\n{text_snippet}"

            # If ISBN not found yet, try from preview snippet
            if not found_isbns:
                found_isbns = extract_isbns(combined_lookup_text)
            isbn_str = found_isbns[0] if found_isbns else None

            # 3. Check bibliographic catalog via ISBN
            catalog_match = None
            try:
                catalog_match = resolve_isbn_catalog(combined_lookup_text, self.existing_categories)
            except Exception:
                pass

            suggested_cat = None
            confidence = 0.5
            reason = ""

            if catalog_match:
                cat_cat, cat_auth, cat_title, cat_reason = catalog_match
                # Official catalog title is the authoritative bibliographic title
                if cat_title and len(cat_title) >= 3:
                    extracted_title = cat_title
                if cat_auth and (not extracted_author or extracted_author == "Unbekannt" or (cat_title and cat_auth.lower() in extracted_title.lower())):
                    extracted_author = cat_auth
                if cat_cat:
                    suggested_cat = cat_cat
                    confidence = 0.98
                    reason = cat_reason

            # Fallback to filename if still empty
            if not extracted_title:
                clean_name = os.path.splitext(fn)[0]
                extracted_title = clean_name.replace("_", " ").replace("-", " ").strip()

            # Sanitize author string (remove emojis, hearts, brackets)
            if extracted_author:
                extracted_author = sanitize_author_string(extracted_author)

            # 4. Classify textbook category if not already resolved by catalog
            if not suggested_cat:
                suggested_cat, confidence, reason = classify_textbook(
                    filename=fn,
                    text=text_snippet or front_text,
                    existing_folders=self.existing_categories,
                    title=extracted_title
                )

            # 5. Check for duplicates (using authoritative ISBN, Author, Title, and File Size)
            dup_warning = check_inbox_duplicate(
                title=extracted_title,
                filename=fn,
                author=extracted_author,
                isbn=isbn_str,
                file_size=file_size,
            )

            analysis_result = {
                "suggested_title": extracted_title,
                "suggested_author": extracted_author or "Unbekannt",
                "suggested_category": suggested_cat or "Sonstiges",
                "confidence": confidence,
                "page_count": page_count,
                "isbn": isbn_str,
                "edition": ed_num,
                "edition_str": ed_str,
                "year": pub_year,
                "duplicate_warning": dup_warning,
                "status": "ready"
            }

            # Update SQLite state immediately so progress survives interruptions
            update_inbox_item(
                item_id=item_id,
                suggested_title=extracted_title,
                suggested_author=extracted_author or "Unbekannt",
                suggested_category=suggested_cat,
                status="ready",
                isbn=isbn_str,
                edition=ed_num,
                edition_str=ed_str,
                year=pub_year,
                page_count=page_count,
                confidence=int(confidence * 100) if confidence <= 1.0 else int(confidence),
                duplicate_warning=dup_warning,
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


class CheckBoxHeader(QHeaderView):
    """Custom HeaderView that draws a pixel-perfect, native-matching Cyber-Obsidian checkbox in column 0."""
    check_all_toggled = Signal(bool)

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._checked = False
        self.setSectionsClickable(True)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if self._checked != checked:
            self._checked = checked
            self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        idx = self.logicalIndexAt(event.pos())
        if idx == 0:
            self._checked = not self._checked
            self.viewport().update()
            self.check_all_toggled.emit(self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()

        if logicalIndex == 0:
            sz = 16
            x = rect.x() + (rect.width() - sz) // 2
            y = rect.y() + (rect.height() - sz) // 2
            chk_rect = QRect(x, y, sz, sz)

            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            if self._checked:
                painter.setBrush(QBrush(QColor("#1F6FEB")))
                painter.setPen(QPen(QColor("#58A6FF"), 1.4))
            else:
                painter.setBrush(QBrush(QColor("#101726")))
                painter.setPen(QPen(QColor("#2B3D5E"), 1.2))
            painter.drawRoundedRect(chk_rect, 4, 4)

            if self._checked:
                pen = QPen(QColor("#FFFFFF"), 2)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawLine(x + 3, y + 8, x + 7, y + 12)
                painter.drawLine(x + 7, y + 12, x + 13, y + 4)
            painter.restore()


class InboxTableDelegate(QStyledItemDelegate):
    """Custom item delegate drawing sleek Cyber-Obsidian checkboxes in Column 0 without clumsy widget embedding."""
    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        if opt.state & QStyle.State_HasFocus:
            opt.state &= ~QStyle.State_HasFocus

        if index.column() == 0:
            is_checked = bool(index.data(Qt.UserRole))
            rect = option.rect
            sz = 16
            x = rect.x() + (rect.width() - sz) // 2
            y = rect.y() + (rect.height() - sz) // 2
            chk_rect = QRect(x, y, sz, sz)

            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            if is_checked:
                painter.setBrush(QBrush(QColor("#1F6FEB")))
                painter.setPen(QPen(QColor("#58A6FF"), 1.4))
            else:
                painter.setBrush(QBrush(QColor("#101726")))
                painter.setPen(QPen(QColor("#2B3D5E"), 1.2))
            painter.drawRoundedRect(chk_rect, 4, 4)

            if is_checked:
                pen = QPen(QColor("#FFFFFF"), 2)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawLine(x + 3, y + 8, x + 7, y + 12)
                painter.drawLine(x + 7, y + 12, x + 13, y + 4)
            painter.restore()
        else:
            super().paint(painter, opt, index)


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
        self._selected_item_ids: set[int] = set()

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

        btn_merge_studio = QPushButton("  Kapitel / PDFs zusammenführen")
        btn_merge_studio.setIcon(create_vector_icon("merge", "#D2A8FF", 14))
        btn_merge_studio.setCursor(Qt.PointingHandCursor)
        btn_merge_studio.setFixedHeight(34)
        btn_merge_studio.setToolTip("Mehrere Einzelkapitel oder PDF-Dateien inklusive Inhaltsverzeichnis zu einem Gesamtbuch verschmelzen")
        btn_merge_studio.setStyleSheet("""
            QPushButton {
                background-color: #1A162B;
                color: #D2A8FF;
                border: 1px solid #483278;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #272042;
                border-color: #8957E5;
                color: #FFFFFF;
            }
        """)
        btn_merge_studio.clicked.connect(self._open_merge_studio)
        top_row.addWidget(btn_merge_studio)

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
        btn_refresh.clicked.connect(lambda: self.sync_filesystem_with_db(force_reanalyze=True))
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
        queue_header.setSpacing(12)

        self.lbl_queue_count = QLabel("Warteschlange (0 Bücher)")
        self.lbl_queue_count.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_queue_count.setStyleSheet("color: #F0F6FC;")
        queue_header.addWidget(self.lbl_queue_count)

        self.lbl_queue_sub = QLabel("— Bereit zur Übernahme in den Bibliothekskatalog")
        self.lbl_queue_sub.setFont(QFont("Segoe UI", 9))
        self.lbl_queue_sub.setStyleSheet("color: #8B949E; margin-left: 2px;")
        queue_header.addWidget(self.lbl_queue_sub)
        queue_header.addStretch()

        # Batch Action: Delete Selected button (visible when items selected)
        self.btn_batch_delete = QPushButton("  Ausgewählte löschen")
        self.btn_batch_delete.setIcon(create_vector_icon("trash", "#FF7B72", 13))
        self.btn_batch_delete.setCursor(Qt.PointingHandCursor)
        self.btn_batch_delete.setFixedHeight(34)
        self.btn_batch_delete.setStyleSheet("""
            QPushButton {
                background-color: #211417;
                color: #FF7B72;
                border: 1px solid #482329;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #381920;
                border-color: #F85149;
                color: #FFFFFF;
            }
            QPushButton:disabled {
                background-color: #161214;
                color: #4A3034;
                border: 1px solid #2B1D20;
            }
        """)
        self.btn_batch_delete.setEnabled(False)
        self.btn_batch_delete.clicked.connect(self._delete_selected_items)
        queue_header.addWidget(self.btn_batch_delete)

        cfg = load_config()
        self.chk_subfolders = QCheckBox("Kategorie-Unterordner erstellen")
        self.chk_subfolders.setFont(QFont("Segoe UI", 9))
        self.chk_subfolders.setChecked(bool(cfg.get("inbox_create_subfolders", False)))
        self.chk_subfolders.setToolTip("Falls deaktiviert, werden Bücher direkt ohne Unterordner im Hauptordner abgelegt.")
        self.chk_subfolders.setStyleSheet("""
            QCheckBox {
                color: #C9D1D9;
                spacing: 6px;
                margin-left: 4px;
                margin-right: 4px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #304163;
                background-color: #121826;
            }
            QCheckBox::indicator:hover {
                border-color: #58A6FF;
            }
            QCheckBox::indicator:checked {
                background-color: #1F6FEB;
                border-color: #58A6FF;
            }
        """)
        self.chk_subfolders.toggled.connect(self._on_subfolders_toggled)
        queue_header.addWidget(self.chk_subfolders)

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
        self.table_delegate = InboxTableDelegate(self.table)
        self.table.setItemDelegate(self.table_delegate)

        # Custom CheckBox Header for column 0
        self.checkbox_header = CheckBoxHeader(Qt.Horizontal, self.table)
        self.checkbox_header.setFixedHeight(38)
        self.checkbox_header.check_all_toggled.connect(self._toggle_select_all)
        self.table.setHorizontalHeader(self.checkbox_header)

        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "", "BUCHTITEL & DATEINAME", "AUTOR", "KI-KATEGORIE", "STATUS", "DATEIGRÖSSE", "AKTION"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)

        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(2, 210)
        self.table.setColumnWidth(3, 210)
        self.table.setColumnWidth(4, 130)
        self.table.setColumnWidth(5, 125)
        self.table.setColumnWidth(6, 175)

        self.table.verticalHeader().setDefaultSectionSize(70)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0A0E17;
                color: #C9D1D9;
                border: 1px solid #162032;
                border-radius: 12px;
                selection-background-color: #131D2F;
                selection-color: #F0F6FC;
                font-size: 12px;
                outline: none;
            }
            QTableWidget::item {
                border-bottom: 1px solid #131C2B;
                padding: 4px 6px;
            }
            QTableWidget::item:selected {
                background-color: #131D2F;
            }
            QHeaderView::section {
                background-color: #0E1522;
                color: #8B949E;
                border: none;
                border-bottom: 1px solid #1D2A40;
                padding: 10px 8px;
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.6px;
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

    def sync_filesystem_with_db(self, force_reanalyze: bool = False) -> None:
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

        # 3. Start background AI classification for items still marked 'pending' or forced
        items_to_analyze = [it for it in self._items if force_reanalyze or it.get("status") == "pending"]
        if items_to_analyze:
            self._start_analysis_worker(items_to_analyze)

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
                w = self.table.cellWidget(r, 1)
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
        info_box.setSpacing(4)
        info_box.setAlignment(Qt.AlignVCenter)

        title_text = item.get("suggested_title") or os.path.splitext(item.get("filename", ""))[0]
        title_edit = QLineEdit(title_text)
        title_edit.setCursorPosition(0)
        title_edit.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title_edit.setToolTip(f"Klicke zum Bearbeiten des Titels\nDateiname: {item.get('filename')}")
        title_edit.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                color: #F0F6FC;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 1px 4px;
            }
            QLineEdit:hover {
                background-color: #121A2A;
                border-color: #23314A;
            }
            QLineEdit:focus {
                background-color: #17243B;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)

        def _on_title_changed(new_title: str, iid: int = item_id, it_dict: Dict = item):
            t_str = new_title.strip()
            it_dict["suggested_title"] = t_str
            # Live re-evaluate duplicate status when user changes title
            new_dup = check_inbox_duplicate(
                title=t_str,
                filename=it_dict.get("filename", ""),
                author=it_dict.get("suggested_author"),
                isbn=it_dict.get("isbn"),
                file_size=it_dict.get("file_size"),
            )
            it_dict["duplicate_warning"] = new_dup
            update_inbox_item(iid, suggested_title=t_str, duplicate_warning=new_dup)

            # Update status badge in table
            for r in range(self.table.rowCount()):
                if r < len(self._items) and self._items[r]["id"] == iid:
                    self._update_status_cell(r, it_dict)
                    break

        title_edit.textChanged.connect(_on_title_changed)
        info_box.addWidget(title_edit)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        lbl_fn = QLabel(item.get("filename", ""))
        lbl_fn.setFont(QFont("Segoe UI", 8))
        lbl_fn.setStyleSheet("color: #6E7681; border: none; background: transparent;")
        meta_row.addWidget(lbl_fn)

        isbn_val = item.get("isbn")
        if isbn_val:
            lbl_isbn = QLabel(f"ISBN: {isbn_val}")
            lbl_isbn.setFont(QFont("Segoe UI", 7, QFont.Bold))
            lbl_isbn.setStyleSheet("""
                color: #79C0FF;
                background-color: #0E1E38;
                border: 1px solid #1D3B6A;
                border-radius: 3px;
                padding: 1px 4px;
            """)
            meta_row.addWidget(lbl_isbn)

        meta_row.addStretch()
        info_box.addLayout(meta_row)

        lay.addLayout(info_box)
        lay.addStretch()
        return w

    def _toggle_select_all(self, checked: bool) -> None:
        """Selects or deselects all items in the queue."""
        if checked:
            self._selected_item_ids = {it["id"] for it in self._items}
        else:
            self._selected_item_ids.clear()

        # Update all row checkboxes in column 0
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, 0)
            if cell:
                cb = cell.findChild(QCheckBox)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(checked)
                    cb.blockSignals(False)

        self._update_batch_buttons_state()

    def _on_table_cell_clicked(self, row: int, col: int) -> None:
        """Toggles row selection when clicking column 0."""
        if col == 0 and 0 <= row < len(self._items):
            item_id = self._items[row]["id"]
            is_now_selected = item_id not in self._selected_item_ids
            if is_now_selected:
                self._selected_item_ids.add(item_id)
            else:
                self._selected_item_ids.discard(item_id)

            cell = self.table.cellWidget(row, 0)
            if cell:
                cb = cell.findChild(QCheckBox)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(is_now_selected)
                    cb.blockSignals(False)

            # Update header checkbox
            if len(self._items) > 0 and len(self._selected_item_ids) == len(self._items):
                self.checkbox_header.setChecked(True)
            else:
                self.checkbox_header.setChecked(False)

            self._update_batch_buttons_state()

    def _update_batch_buttons_state(self) -> None:
        count = len(self._selected_item_ids)
        if count > 0:
            self.btn_batch_delete.setEnabled(True)
            self.btn_batch_delete.setText(f"  {count} Ausgewählte löschen")
        else:
            self.btn_batch_delete.setEnabled(False)
            self.btn_batch_delete.setText("  Ausgewählte löschen")

    def _delete_selected_items(self) -> None:
        """Deletes all currently checked books from inbox queue and physical disk."""
        if not self._selected_item_ids:
            return

        count = len(self._selected_item_ids)
        ret = QMessageBox.question(
            self,
            f"{count} Bücher verwerfen & löschen?",
            f"Möchtest du wirklich die {count} ausgewählten Bücher aus der Warteschlange und von der Festplatte löschen?\n\nDieser Schritt kann nicht rückgängig gemacht werden.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        to_delete = list(self._selected_item_ids)
        for iid in to_delete:
            delete_inbox_item(iid, delete_file=True)

        self._selected_item_ids.clear()
        self.sync_filesystem_with_db()

    def _reload_table_data(self) -> None:
        self._items = get_inbox_queue()
        # Filter out items whose files no longer exist on disk
        valid_items = []
        for it in self._items:
            if os.path.exists(it["file_path"]):
                # Always ensure duplicate warnings are fresh and accurate
                dup_now = check_inbox_duplicate(
                    title=it.get("suggested_title", ""),
                    filename=it.get("filename", ""),
                    author=it.get("suggested_author"),
                    isbn=it.get("isbn"),
                    file_size=it.get("file_size"),
                )
                if it.get("duplicate_warning") != dup_now:
                    it["duplicate_warning"] = dup_now
                    update_inbox_item(it["id"], duplicate_warning=dup_now)
                valid_items.append(it)
            else:
                delete_inbox_item(it["id"])
        self._items = valid_items

        # Prune selection set
        all_ids = {it["id"] for it in self._items}
        self._selected_item_ids = self._selected_item_ids.intersection(all_ids)

        self.table.setRowCount(len(self._items))
        self.lbl_queue_count.setText(f"Warteschlange ({len(self._items)} Bücher)")
        self.btn_batch_file.setEnabled(len(self._items) > 0)
        self.checkbox_header.setEnabled(len(self._items) > 0)
        self.checkbox_header.setChecked(len(self._items) > 0 and len(self._selected_item_ids) == len(self._items))
        self._update_batch_buttons_state()
        self.queue_updated.emit(len(self._items))

        all_cats = [c[0] for c in get_category_counts()] or STANDARD_CATEGORIES

        for row, it in enumerate(self._items):
            item_id = it["id"]
            is_selected = item_id in self._selected_item_ids

            # Col 0: Real native QCheckBox centered in container
            chk_box = QWidget()
            chk_lay = QHBoxLayout(chk_box)
            chk_lay.setContentsMargins(0, 0, 0, 0)
            chk_lay.setAlignment(Qt.AlignCenter)
            cb = QCheckBox()
            cb.setCursor(Qt.PointingHandCursor)
            cb.setChecked(is_selected)
            cb.setStyleSheet("""
                QCheckBox {
                    background: transparent;
                }
                QCheckBox::indicator {
                    width: 17px;
                    height: 17px;
                    border-radius: 4px;
                    border: 1px solid #304163;
                    background-color: #101625;
                }
                QCheckBox::indicator:hover {
                    border-color: #58A6FF;
                    background-color: #141C30;
                }
                QCheckBox::indicator:checked {
                    background-color: #1F6FEB;
                    border-color: #58A6FF;
                }
            """)

            def _on_row_chk_toggled(checked: bool, iid: int = item_id):
                if checked:
                    self._selected_item_ids.add(iid)
                else:
                    self._selected_item_ids.discard(iid)

                if len(self._items) > 0 and len(self._selected_item_ids) == len(self._items):
                    self.checkbox_header.setChecked(True)
                else:
                    self.checkbox_header.setChecked(False)

                self._update_batch_buttons_state()

            cb.toggled.connect(_on_row_chk_toggled)
            chk_lay.addWidget(cb)
            self.table.setCellWidget(row, 0, chk_box)

            # Col 1: Styled Cover + Title Card Widget
            title_widget = self._create_title_widget(it)
            self.table.setCellWidget(row, 1, title_widget)

            # Col 2: Author (Editable LineEdit with fixed height & clean cyber obsidian styling)
            author_edit = QLineEdit(it.get("suggested_author") or "Unbekannt")
            author_edit.setCursorPosition(0)
            author_edit.setFixedHeight(34)
            author_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #101625;
                    color: #C9D1D9;
                    border: 1px solid #1E2B42;
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                }
                QLineEdit:hover {
                    border-color: #2F4468;
                }
                QLineEdit:focus {
                    border-color: #58A6FF;
                    background-color: #141E33;
                    color: #FFFFFF;
                }
            """)
            def _on_author_changed(txt: str, iid: int = item_id, item_dict: Dict = it) -> None:
                item_dict["suggested_author"] = txt
                new_dup = check_inbox_duplicate(
                    title=item_dict.get("suggested_title", ""),
                    filename=item_dict.get("filename", ""),
                    author=txt,
                    isbn=item_dict.get("isbn"),
                    file_size=item_dict.get("file_size"),
                )
                item_dict["duplicate_warning"] = new_dup
                update_inbox_item(iid, suggested_author=txt, duplicate_warning=new_dup)

                # Live re-render status cell
                for r in range(self.table.rowCount()):
                    if r < len(self._items) and self._items[r]["id"] == iid:
                        self._update_status_cell(r, item_dict)
                        break

            author_edit.textChanged.connect(_on_author_changed)
            self.table.setCellWidget(row, 2, author_edit)

            # Col 3: Category Combobox (fixed height & clean styling)
            combo_cat = QComboBox()
            combo_cat.setFixedHeight(34)
            combo_cat.setStyleSheet("""
                QComboBox {
                    background-color: #121A2A;
                    color: #58A6FF;
                    border: 1px solid #23314A;
                    border-radius: 6px;
                    padding: 0 10px;
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

            def _on_cat_changed(txt: str, iid: int = item_id, item_dict: Dict = it) -> None:
                item_dict["suggested_category"] = txt
                update_inbox_item(iid, suggested_category=txt)

            combo_cat.currentTextChanged.connect(_on_cat_changed)
            self.table.setCellWidget(row, 3, combo_cat)

            # Col 4: Status / Duplicate Warning Badge
            status_box = QWidget()
            s_lay = QHBoxLayout(status_box)
            s_lay.setContentsMargins(6, 4, 6, 4)
            s_lay.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(row, 4, status_box)
            self._render_status_badge(s_lay, it)

            # Col 5: File Size & Pages (Styled cyber pill)
            sz_mb = it.get("file_size", 0) / (1024 * 1024)
            p_cnt = it.get("page_count", 0)
            sz_txt = f"{sz_mb:.1f} MB • {p_cnt} S." if p_cnt > 0 else f"{sz_mb:.1f} MB"
            item_sz = QTableWidgetItem(sz_txt)
            item_sz.setTextAlignment(Qt.AlignCenter)
            item_sz.setFlags(item_sz.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 5, item_sz)

            # Col 6: Action buttons (Fixed width to avoid text truncation)
            act_box = QWidget()
            act_lay = QHBoxLayout(act_box)
            act_lay.setContentsMargins(6, 4, 6, 4)
            act_lay.setSpacing(6)
            act_lay.setAlignment(Qt.AlignCenter)

            btn_file = QPushButton("  Einsortieren")
            btn_file.setIcon(create_vector_icon("check", "#FFFFFF", 12))
            btn_file.setCursor(Qt.PointingHandCursor)
            btn_file.setFixedHeight(32)
            btn_file.setMinimumWidth(105)
            btn_file.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #287FFB);
                    color: #FFFFFF;
                    border: 1px solid #388BFD;
                    border-radius: 6px;
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

            btn_del = QPushButton()
            btn_del.setIcon(create_vector_icon("trash", "#FF7B72", 13))
            btn_del.setToolTip("Aus Posteingang entfernen & Datei löschen")
            btn_del.setFixedSize(32, 32)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("""
                QPushButton {
                    background: #1C1417;
                    border: 1px solid #482329;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: #381920;
                    border-color: #F85149;
                }
            """)
            btn_del.clicked.connect(lambda _, iid=item_id: self._delete_item(iid))
            act_lay.addWidget(btn_del)

            self.table.setCellWidget(row, 6, act_box)

    def _start_analysis_worker(self, items: List[Dict]) -> None:
        if self._analysis_thread and self._analysis_thread.isRunning():
            return
        cats = [c[0] for c in get_category_counts()] or STANDARD_CATEGORIES
        self._analysis_thread = InboxAnalysisWorker(items, cats, parent=self)
        self._analysis_thread.item_analyzed.connect(self._on_item_analyzed)
        self._analysis_thread.all_finished.connect(self._on_all_analyzed)
        self._analysis_thread.start()

    def _render_status_badge(self, lay: QLayout, item: Dict) -> None:
        """Renders modern cyber-obsidian status pill into the given layout."""
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()

        dup = item.get("duplicate_warning", "")
        conf = item.get("confidence", 0)
        status = item.get("status", "pending")

        if dup:
            lbl_dup = QLabel("⚠️ Duplikat")
            lbl_dup.setToolTip(f"Mögliches Duplikat:\n{dup}")
            lbl_dup.setStyleSheet("""
                color: #FFA657;
                font-weight: 700;
                background: #2D1A10;
                border: 1px solid #7C3D18;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
            """)
            lay.addWidget(lbl_dup)
        elif status == "ready":
            lbl_ready = QLabel(f"✓ Bereit ({conf}%)")
            lbl_ready.setStyleSheet("""
                color: #3FB950;
                font-weight: 700;
                background: #0D2616;
                border: 1px solid #1E542C;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
            """)
            lay.addWidget(lbl_ready)
        else:
            lbl_pend = QLabel("⏳ Analysiere...")
            lbl_pend.setStyleSheet("""
                color: #8B949E;
                font-weight: 600;
                background: #141C2B;
                border: 1px solid #222F47;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
            """)
            lay.addWidget(lbl_pend)

    def _update_status_cell(self, row: int, item: Dict) -> None:
        """Updates the status cell widget at the specified row."""
        stat_box = self.table.cellWidget(row, 4)
        if stat_box and stat_box.layout():
            self._render_status_badge(stat_box.layout(), item)

    def _on_item_analyzed(self, item_id: int, data: dict) -> None:
        # Update table row with analysis result
        for r in range(self.table.rowCount()):
            if r < len(self._items) and self._items[r]["id"] == item_id:
                # Update item title if changed
                if data.get("suggested_title"):
                    title_w = self.table.cellWidget(r, 1)
                    if title_w:
                        title_edits = title_w.findChildren(QLineEdit)
                        if title_edits:
                            title_edits[0].blockSignals(True)
                            title_edits[0].setText(data["suggested_title"])
                            title_edits[0].setCursorPosition(0)
                            title_edits[0].blockSignals(False)

                # Update author edit
                if data.get("suggested_author"):
                    auth_w = self.table.cellWidget(r, 2)
                    if isinstance(auth_w, QLineEdit):
                        auth_w.blockSignals(True)
                        auth_w.setText(data["suggested_author"])
                        auth_w.setCursorPosition(0)
                        auth_w.blockSignals(False)

                # Update category combo
                combo = self.table.cellWidget(r, 3)
                if isinstance(combo, QComboBox) and data.get("suggested_category"):
                    idx = combo.findText(data["suggested_category"])
                    if idx >= 0:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(idx)
                        combo.blockSignals(False)

                # Update status box via unified badge renderer
                self._items[r].update(data)
                self._update_status_cell(r, self._items[r])

                # Update size/pages
                p_cnt = data.get("page_count", 0)
                if p_cnt > 0:
                    it_sz = self.table.item(r, 5)
                    if it_sz and "Seiten" not in it_sz.text():
                        sz_mb = self._items[r].get("file_size", 0) / (1024 * 1024)
                        it_sz.setText(f"{sz_mb:.1f} MB\n{p_cnt} Seiten")
                break

    def _on_all_analyzed(self) -> None:
        self._items = get_inbox_queue()

    def _on_subfolders_toggled(self, checked: bool) -> None:
        cfg = load_config()
        cfg["inbox_create_subfolders"] = bool(checked)
        save_config(cfg)

    def _file_single_book(self, item_id: int) -> bool:
        """Moves the book into the target library directory and adds it to the SQLite catalog."""
        # Read the latest state from database or table cells to ensure manually edited authors/categories are preserved
        db_item = next((it for it in get_inbox_queue() if it["id"] == item_id), None)
        item = next((it for it in self._items if it["id"] == item_id), None)
        if not item and not db_item:
            return False
        if db_item and item:
            item.update(db_item)
        elif db_item:
            item = db_item

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
        isbn = item.get("isbn")
        edition = item.get("edition", 1) or 1
        edition_str = item.get("edition_str")
        year = item.get("year")

        # 1. Target directory: subfolder only if user explicitly enabled it
        create_subfolders = getattr(self, "chk_subfolders", None) and self.chk_subfolders.isChecked()
        if create_subfolders:
            target_dir = os.path.join(self.storage_dir, category)
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception:
                target_dir = self.storage_dir
        else:
            target_dir = self.storage_dir
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception:
                pass

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

        # Fallback inspection if page_count or metadata are still missing
        if page_count <= 0 or not isbn or not year or edition <= 1:
            try:
                import fitz
                doc = fitz.open(target_path)
                total_p = len(doc)
                if page_count <= 0:
                    page_count = total_p
                snippet = "\n".join(doc[p].get_text("text") for p in range(min(8, total_p)))
                if not isbn:
                    f_isbns = extract_isbns(f"ISBN {target_filename.replace('_', ' ')}\n{snippet}")
                    if f_isbns:
                        isbn = f_isbns[0]
                if edition <= 1:
                    ed_num, ed_s = extract_edition_number(f"{target_filename}\n{title}\n{snippet}")
                    if ed_num > 1:
                        edition = ed_num
                        edition_str = ed_s
                if not year:
                    year = extract_publication_year(snippet, doc.metadata, target_filename)
                doc.close()
            except Exception:
                pass

        # 4. Insert into main library database
        book_id = upsert_book(
            file_path=target_path,
            filename=target_filename,
            title=title,
            author=author,
            categories=[category],
            isbn=isbn,
            edition=edition,
            edition_str=edition_str,
            year=year,
            page_count=page_count,
            file_size=os.path.getsize(target_path) if os.path.exists(target_path) else file_size,
            file_mtime=os.path.getmtime(target_path) if os.path.exists(target_path) else 0.0,
            confidence=item.get("confidence", 90),
            audit_trail="Importiert via Campus-Inbox"
        )

        # 5. Pre-generate and cache book cover thumbnail
        try:
            extract_and_cache_cover(
                book_id=book_id,
                file_path=target_path,
                title=title,
                author=author,
                category=category,
                isbn=isbn
            )
        except Exception:
            pass

        # 6. Remove from inbox queue
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

    def _open_merge_studio(self) -> None:
        """Opens the PDF Merge Studio preloaded with current Inbox PDFs."""
        from ui.qt.dialogs.pdf_merge_dialog import PdfMergeDialog
        inbox_paths = [it["file_path"] for it in self._items if os.path.isfile(it.get("file_path", ""))]
        dlg = PdfMergeDialog(
            initial_files=inbox_paths,
            from_inbox=len(inbox_paths) > 0,
            parent=self.window(),
        )
        if dlg.exec():
            self.sync_filesystem_with_db()
            self.book_filed.emit()

