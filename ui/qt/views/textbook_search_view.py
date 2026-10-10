"""Academic Textbook Discovery & Monograph Search View for PySide6.
Features DNB, Google Books, Crossref & OpenLibrary federated search,
a collapsible Inspector with Book Cover, APA 7 & BibTeX citation generation,
Uni-EZProxy routing, and 1-Click Wishlist/Inventory integration.
"""

import os
import subprocess
import threading
import webbrowser
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal, QObject, QSize, QTimer
from PySide6.QtGui import QFont, QColor, QGuiApplication, QPixmap, QImage
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
    QMessageBox,
    QDialog,
    QCheckBox,
    QComboBox,
)
import urllib.request
import urllib.parse

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.library_db import (
    save_textbook,
    get_all_saved_textbooks,
    delete_saved_textbook,
    get_institution_settings,
    update_institution_settings,
    find_saved_textbook,
)
from ai.textbook_search import (
    search_all_textbooks,
    build_textbook_institution_url,
    generate_textbook_apa7,
    generate_textbook_bibtex,
    BOOK_FACULTY_KEYWORDS,
)
from ai.categories import STANDARD_CATEGORIES


def launch_in_browser(target_url: str) -> bool:
    """Launches an HTTP/HTTPS URL or file in Microsoft Edge with robust fallbacks."""
    url = str(target_url).strip()
    if not url:
        return False

    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for exe in edge_candidates:
        if os.path.isfile(exe):
            try:
                subprocess.Popen([exe, url])
                return True
            except Exception:
                pass

    # Fallback 1: Windows cmd start msedge
    try:
        ret = subprocess.run(["cmd", "/c", "start", "", "msedge", url], capture_output=True, text=True, check=False)
        if ret.returncode == 0:
            return True
    except Exception:
        pass

    # Fallback 2: Microsoft Edge protocol handler
    try:
        os.startfile(f"microsoft-edge:{url}")
        return True
    except Exception:
        pass

    # Fallback 3: Default system browser
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False



class TextbookSearchSignals(QObject):
    """Thread-safe signals for textbook search."""
    search_finished = Signal(list)
    search_error = Signal(str)


class TextbookResultCard(QFrame):
    """Interactive result card for an academic textbook."""

    inspect_requested = Signal(dict)
    save_requested = Signal(dict)
    apa_requested = Signal(dict)
    bibtex_requested = Signal(dict)
    open_edge_requested = Signal(dict)
    open_uni_requested = Signal(dict)

    def __init__(self, book: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.book = book
        self.is_selected = False
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header Row: Title & Badges
        top_h = QHBoxLayout()
        top_h.setSpacing(8)

        self.lbl_t = QLabel(book.get("title", ""))
        self.lbl_t.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_t.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        self.lbl_t.setWordWrap(True)
        top_h.addWidget(self.lbl_t, stretch=1)

        self.badge_active = QLabel("● Ausgewählt")
        self.badge_active.setStyleSheet("""
            background-color: #1F6FEB;
            color: #FFFFFF;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
        """)
        self.badge_active.setVisible(False)
        top_h.addWidget(self.badge_active)

        cat = book.get("category", "").strip()
        if cat:
            cat_badge = QLabel(f"📚 {cat}")
            cat_badge.setStyleSheet("""
                background-color: #16243E;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            """)
            top_h.addWidget(cat_badge)

        source = book.get("source", "").upper()
        if source:
            src_badge = QLabel(f"🔍 {source}")
            src_badge.setStyleSheet("""
                background-color: #1F192E;
                color: #BC8CFF;
                border: 1px solid #6E40C9;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 600;
            """)
            top_h.addWidget(src_badge)

        layout.addLayout(top_h)

        # Authors, Year, Publisher & ISBN
        authors = book.get("authors", "Autor unbekannt")
        year = book.get("year", "")
        publisher = book.get("publisher", "")
        isbn = book.get("isbn", "")
        pages = book.get("page_count", 0)

        meta_parts = []
        if authors:
            meta_parts.append(f"von {authors}")
        if year:
            meta_parts.append(f"({year})")
        if publisher:
            meta_parts.append(f"· {publisher}")
        if pages:
            meta_parts.append(f"· {pages} Seiten")
        if isbn:
            meta_parts.append(f"· ISBN: {isbn}")

        lbl_meta = QLabel(" ".join(meta_parts))
        lbl_meta.setFont(QFont("Segoe UI", 9))
        lbl_meta.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        lbl_meta.setWordWrap(True)
        layout.addWidget(lbl_meta)

        # Short snippet/description
        desc = book.get("description", "").strip()
        if desc:
            short_desc = desc if len(desc) <= 180 else desc[:177] + "..."
            lbl_desc = QLabel(short_desc)
            lbl_desc.setFont(QFont("Segoe UI", 9))
            lbl_desc.setStyleSheet("color: #6E7681; border: none; background: transparent; font-style: italic;")
            lbl_desc.setWordWrap(True)
            layout.addWidget(lbl_desc)

        # Action Buttons Row
        act_row = QHBoxLayout()
        act_row.setSpacing(8)

        self.btn_inspect = QPushButton(" Buch-Inspektor")
        self.btn_inspect.setIcon(create_vector_icon("search", "#58A6FF", 13))
        self.btn_inspect.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #1F6FEB;
                color: #FFFFFF;
            }
        """)
        self.btn_inspect.setCursor(Qt.PointingHandCursor)
        self.btn_inspect.clicked.connect(self._on_inspect_clicked)
        act_row.addWidget(self.btn_inspect)

        self.btn_apa = QPushButton(" APA 7")
        self.btn_apa.setIcon(create_vector_icon("edit", "#8B949E", 13))
        self.btn_apa.setStyleSheet("""
            QPushButton {
                background: #161B22;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #21262D;
                border-color: #58A6FF;
                color: #58A6FF;
            }
        """)
        self.btn_apa.setCursor(Qt.PointingHandCursor)
        self.btn_apa.clicked.connect(self._copy_apa_instant)
        act_row.addWidget(self.btn_apa)

        self.btn_bib = QPushButton(" BibTeX")
        self.btn_bib.setStyleSheet("""
            QPushButton {
                background: #161B22;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #21262D;
                border-color: #58A6FF;
                color: #58A6FF;
            }
        """)
        self.btn_bib.setCursor(Qt.PointingHandCursor)
        self.btn_bib.clicked.connect(self._copy_bibtex_instant)
        act_row.addWidget(self.btn_bib)

        act_row.addStretch()

        # University license access
        self.btn_uni = QPushButton(" Uni-Lizenz")
        self.btn_uni.setIcon(create_vector_icon("external", "#D2A8FF", 13))
        self.btn_uni.setStyleSheet("""
            QPushButton {
                background: #211534;
                color: #D2A8FF;
                border: 1px solid #8957E5;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #8957E5;
                color: #FFFFFF;
            }
        """)
        self.btn_uni.setCursor(Qt.PointingHandCursor)
        self.btn_uni.clicked.connect(self._on_open_uni)
        act_row.addWidget(self.btn_uni)

        # Save to wishlist/library button
        is_saved = bool(find_saved_textbook(self.book.get("title", ""), self.book.get("isbn", "")))
        self.btn_save = QPushButton(" Gemerkt" if is_saved else " Merken / Vormerken")
        self.btn_save.setIcon(create_vector_icon("star", "#E3B341" if is_saved else "#8B949E", 13))
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {'#2B220B' if is_saved else '#161B22'};
                color: {'#F2CC60' if is_saved else '#C9D1D9'};
                border: 1px solid {'#9E6A03' if is_saved else '#30363D'};
                border-radius: 5px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {'#9E6A03' if is_saved else '#21262D'};
                color: #FFFFFF;
            }}
        """)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._toggle_save)
        act_row.addWidget(self.btn_save)

        layout.addLayout(act_row)
        self._update_style()

    def _on_inspect_clicked(self) -> None:
        self.inspect_requested.emit(self.book)

    def _copy_apa_instant(self) -> None:
        citation = generate_textbook_apa7(self.book)
        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText(citation)
        self.btn_apa.setText(" ✓ APA 7 kopiert!")
        self.btn_apa.setStyleSheet("background: #238636; border: 1px solid #2EA043; color: #FFFFFF; border-radius: 5px; padding: 4px 10px; font-size: 11px; font-weight: bold;")
        self.apa_requested.emit(self.book)
        QTimer.singleShot(2000, self._reset_apa_btn)

    def _reset_apa_btn(self) -> None:
        self.btn_apa.setText(" APA 7")
        self.btn_apa.setStyleSheet("""
            QPushButton {
                background: #161B22;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #21262D;
                border-color: #58A6FF;
                color: #58A6FF;
            }
        """)

    def _copy_bibtex_instant(self) -> None:
        bib = generate_textbook_bibtex(self.book)
        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText(bib)
        self.btn_bib.setText(" ✓ BibTeX kopiert!")
        self.btn_bib.setStyleSheet("background: #238636; border: 1px solid #2EA043; color: #FFFFFF; border-radius: 5px; padding: 4px 10px; font-size: 11px; font-weight: bold;")
        self.bibtex_requested.emit(self.book)
        QTimer.singleShot(2000, self._reset_bib_btn)

    def _reset_bib_btn(self) -> None:
        self.btn_bib.setText(" BibTeX")
        self.btn_bib.setStyleSheet("""
            QPushButton {
                background: #161B22;
                color: #C9D1D9;
                border: 1px solid #30363D;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #21262D;
                border-color: #58A6FF;
                color: #58A6FF;
            }
        """)

    def _on_open_uni(self) -> None:
        self.open_uni_requested.emit(self.book)

    def update_save_status(self, is_saved: bool) -> None:
        self.btn_save.setText(" Gemerkt" if is_saved else " Merken / Vormerken")
        self.btn_save.setIcon(create_vector_icon("star", "#E3B341" if is_saved else "#8B949E", 13))
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {'#2B220B' if is_saved else '#161B22'};
                color: {'#F2CC60' if is_saved else '#C9D1D9'};
                border: 1px solid {'#9E6A03' if is_saved else '#30363D'};
                border-radius: 5px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {'#9E6A03' if is_saved else '#21262D'};
                color: #FFFFFF;
            }}
        """)

    def set_selected(self, selected: bool) -> None:
        self.is_selected = selected
        self.badge_active.setVisible(selected)
        self._update_style()

    def _update_style(self) -> None:
        if self.is_selected:
            self.setStyleSheet("""
                QFrame {
                    background-color: #141B2D;
                    border: 2px solid #388BFD;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #121826;
                    border: 1px solid #232F48;
                    border-radius: 8px;
                }
                QFrame:hover {
                    background-color: #162035;
                    border-color: #3B5078;
                }
            """)

    def _toggle_save(self) -> None:
        self.save_requested.emit(self.book)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.inspect_requested.emit(self.book)
        super().mousePressEvent(event)



class TextbookInspector(QFrame):
    """Side panel displaying full textbook metadata, cover, summary, and actions."""

    close_requested = Signal()
    save_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_book: Optional[Dict[str, Any]] = None
        self.setStyleSheet("""
            QFrame {
                background-color: #0F1422;
                border-left: 1px solid #232F48;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header with Close Button
        h_top = QHBoxLayout()
        lbl_h = QLabel("📖 Fachbuch-Inspektor")
        lbl_h.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_h.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        h_top.addWidget(lbl_h)
        h_top.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: #161B22;
                color: #8B949E;
                border: 1px solid #30363D;
                border-radius: 13px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #DA3633;
                color: #FFFFFF;
                border-color: #F85149;
            }
        """)
        btn_close.clicked.connect(self.close_requested.emit)
        h_top.addWidget(btn_close)
        layout.addLayout(h_top)

        # Scroll Area for Details
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        self.det_layout = QVBoxLayout(scroll_content)
        self.det_layout.setContentsMargins(0, 0, 8, 0)
        self.det_layout.setSpacing(12)

        # Cover image container
        self.lbl_cover = QLabel()
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setMinimumHeight(180)
        self.lbl_cover.setStyleSheet("""
            background-color: #141C2E;
            border: 1px dashed #304163;
            border-radius: 8px;
            color: #58A6FF;
            font-size: 11px;
        """)
        self.lbl_cover.setText("Kein Buchcover verfügbar")
        self.det_layout.addWidget(self.lbl_cover)

        # Title & Meta Labels
        self.lbl_title = QLabel("Wähle ein Fachbuch aus der Trefferliste")
        self.lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        self.lbl_title.setWordWrap(True)
        self.det_layout.addWidget(self.lbl_title)

        self.lbl_meta = QLabel()
        self.lbl_meta.setFont(QFont("Segoe UI", 9))
        self.lbl_meta.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        self.lbl_meta.setWordWrap(True)
        self.det_layout.addWidget(self.lbl_meta)

        # Description / Summary Box
        lbl_syn_t = QLabel("Klappentext & Inhaltsangabe:")
        lbl_syn_t.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_syn_t.setStyleSheet("color: #C9D1D9; border: none; background: transparent; margin-top: 6px;")
        self.det_layout.addWidget(lbl_syn_t)

        self.lbl_desc = QLabel("Keine Inhaltsangabe verfügbar.")
        self.lbl_desc.setFont(QFont("Segoe UI", 9))
        self.lbl_desc.setStyleSheet("""
            background-color: #121826;
            border: 1px solid #232F48;
            border-radius: 6px;
            padding: 10px;
            color: #C9D1D9;
            line-height: 1.4;
        """)
        self.lbl_desc.setWordWrap(True)
        self.det_layout.addWidget(self.lbl_desc)

        # APA 7 Box
        lbl_apa_t = QLabel("Zitation nach APA 7th Edition:")
        lbl_apa_t.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_apa_t.setStyleSheet("color: #C9D1D9; border: none; background: transparent; margin-top: 6px;")
        self.det_layout.addWidget(lbl_apa_t)

        self.lbl_apa = QLabel()
        self.lbl_apa.setFont(QFont("Segoe UI", 9))
        self.lbl_apa.setStyleSheet("""
            background-color: #121826;
            border: 1px solid #232F48;
            border-radius: 6px;
            padding: 8px;
            color: #58A6FF;
        """)
        self.lbl_apa.setWordWrap(True)
        self.det_layout.addWidget(self.lbl_apa)

        self.btn_copy_apa = QPushButton(" APA 7 kopieren")
        self.btn_copy_apa.setIcon(create_vector_icon("edit", "#58A6FF", 12))
        self.btn_copy_apa.setCursor(Qt.PointingHandCursor)
        self.btn_copy_apa.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1F6FEB;
                color: #FFFFFF;
            }
        """)
        self.btn_copy_apa.clicked.connect(self._copy_apa)
        self.det_layout.addWidget(self.btn_copy_apa)

        # Action Buttons
        self.det_layout.addSpacing(10)
        lbl_act = QLabel("Aktionen & Bibliothekszugriff:")
        lbl_act.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_act.setStyleSheet("color: #C9D1D9; border: none; background: transparent;")
        self.det_layout.addWidget(lbl_act)

        self.btn_uni = QPushButton(" Über Uni-Lizenz öffnen (EZProxy)")
        self.btn_uni.setIcon(create_vector_icon("external", "#D2A8FF", 14))
        self.btn_uni.setCursor(Qt.PointingHandCursor)
        self.btn_uni.setStyleSheet("""
            QPushButton {
                background: #211534;
                color: #D2A8FF;
                border: 1px solid #8957E5;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #8957E5;
                color: #FFFFFF;
            }
        """)
        self.btn_uni.clicked.connect(self._open_uni)
        self.det_layout.addWidget(self.btn_uni)

        self.btn_edge = QPushButton(" Vorschau in Microsoft Edge öffnen")
        self.btn_edge.setIcon(create_vector_icon("globe", "#58A6FF", 14))
        self.btn_edge.setCursor(Qt.PointingHandCursor)
        self.btn_edge.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1F6FEB;
                color: #FFFFFF;
            }
        """)
        self.btn_edge.clicked.connect(self._open_preview)
        self.det_layout.addWidget(self.btn_edge)

        self.btn_wishlist = QPushButton(" Auf Wunschliste / Gemerkt")
        self.btn_wishlist.setIcon(create_vector_icon("star", "#E3B341", 14))
        self.btn_wishlist.setCursor(Qt.PointingHandCursor)
        self.btn_wishlist.setStyleSheet("""
            QPushButton {
                background: #2B220B;
                color: #F2CC60;
                border: 1px solid #9E6A03;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #9E6A03;
                color: #FFFFFF;
            }
        """)
        self.btn_wishlist.clicked.connect(self._save_book)
        self.det_layout.addWidget(self.btn_wishlist)

        self.det_layout.addStretch()
        self.scroll.setWidget(scroll_content)
        layout.addWidget(self.scroll)

    def load_book(self, book: Dict[str, Any]) -> None:
        self.current_book = book
        self.lbl_title.setText(book.get("title", ""))

        authors = book.get("authors", "Autor unbekannt")
        year = book.get("year", "")
        publisher = book.get("publisher", "")
        isbn = book.get("isbn", "")
        pages = book.get("page_count", 0)
        source = book.get("source", "").upper()

        meta_lines = [
            f"<b>Autor(en):</b> {authors}",
            f"<b>Erscheinungsjahr:</b> {year or 'o. D.'}",
            f"<b>Verlag:</b> {publisher or 'Unbekannt'}",
            f"<b>ISBN:</b> {isbn or 'Keine'}",
            f"<b>Umfang:</b> {f'{pages} Seiten' if pages else 'Keine Angabe'}",
            f"<b>Quelle:</b> {source}",
        ]
        self.lbl_meta.setText("<br>".join(meta_lines))

        desc = book.get("description", "").strip()
        self.lbl_desc.setText(desc if desc else "Für dieses Werk liegt kein Abstract / Klappentext in den Bibliotheksmetadaten vor.")

        apa = generate_textbook_apa7(book)
        self.lbl_apa.setText(apa)

        # Update wishlist button state
        self.update_wishlist_state()

        # Load cover async if URL available or via ISBN
        cover_url = book.get("cover_url")
        if not cover_url and isbn:
            clean_isbn = "".join(c for c in isbn if c.isdigit())
            if clean_isbn:
                cover_url = f"https://covers.openlibrary.org/b/isbn/{clean_isbn}-M.jpg"

        if cover_url:
            self._fetch_cover_async(cover_url)
        else:
            self.lbl_cover.setPixmap(QPixmap())
            self.lbl_cover.setText("Kein Buchcover hinterlegt")

    def update_wishlist_state(self) -> None:
        if not self.current_book:
            return
        is_saved = bool(find_saved_textbook(self.current_book.get("title", ""), self.current_book.get("isbn", "")))
        self.btn_wishlist.setText(" ✓ Auf Wunschliste gespeichert" if is_saved else " + Auf Wunschliste / Merken")
        self.btn_wishlist.setIcon(create_vector_icon("star", "#E3B341" if is_saved else "#8B949E", 14))
        self.btn_wishlist.setStyleSheet(f"""
            QPushButton {{
                background: {'#2B220B' if is_saved else '#161B22'};
                color: {'#F2CC60' if is_saved else '#C9D1D9'};
                border: 1px solid {'#9E6A03' if is_saved else '#30363D'};
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {'#9E6A03' if is_saved else '#21262D'};
                color: #FFFFFF;
            }}
        """)

    def _fetch_cover_async(self, url: str) -> None:
        self.lbl_cover.setText("Lade Buchcover...")

        def worker():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = resp.read()
                    if data and len(data) > 300:
                        img = QImage.fromData(data)
                        if not img.isNull():
                            pix = QPixmap.fromImage(img).scaled(
                                140, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
                            )
                            QTimer.singleShot(0, lambda: self._apply_cover(pix))
                            return
            except Exception:
                pass
            QTimer.singleShot(0, lambda: self._apply_cover(None))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_cover(self, pix: Optional[QPixmap]) -> None:
        if pix:
            self.lbl_cover.setText("")
            self.lbl_cover.setPixmap(pix)
        else:
            self.lbl_cover.setPixmap(QPixmap())
            self.lbl_cover.setText("Kein Buchcover gefunden")

    def _copy_apa(self) -> None:
        if self.current_book:
            text = generate_textbook_apa7(self.current_book)
            clip = QGuiApplication.clipboard()
            if clip:
                clip.setText(text)
            self.btn_copy_apa.setText(" ✓ APA 7 kopiert!")
            self.btn_copy_apa.setStyleSheet("background: #238636; border: 1px solid #2EA043; color: #FFFFFF; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: bold;")
            QTimer.singleShot(2000, self._reset_inspector_apa)

    def _reset_inspector_apa(self) -> None:
        self.btn_copy_apa.setText(" APA 7 kopieren")
        self.btn_copy_apa.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1F6FEB;
                color: #FFFFFF;
            }
        """)

    def _open_uni(self) -> None:
        if self.current_book:
            url = build_textbook_institution_url(self.current_book)
            launch_in_browser(url)

    def _open_preview(self) -> None:
        if self.current_book:
            url = self.current_book.get("preview_url")
            if not url:
                title = self.current_book.get("title", "")
                url = f"https://www.google.de/search?tbm=bks&q={urllib.parse.quote(title)}"
            launch_in_browser(url)

    def _save_book(self) -> None:
        if self.current_book:
            self.save_requested.emit(self.current_book)
            self.update_wishlist_state()



class TextbookSearchView(QWidget):
    """Flagship Academic Textbook Discovery and Wishlist Hub."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = TextbookSearchSignals()
        self.signals.search_finished.connect(self._on_search_finished)
        self.signals.search_error.connect(self._on_search_error)

        self.current_mode = "online"  # "online" or "wishlist"
        self.active_cards: List[TextbookResultCard] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # 1. Top Header Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_pixmap("book", "#58A6FF", 24))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        top_bar.addWidget(lbl_icon)

        lbl_title = QLabel("Fachbuch-Recherche & Monographien")
        lbl_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        top_bar.addWidget(lbl_title)

        lbl_sub = QLabel("· DNB, Google Books & Crossref Scholarly")
        lbl_sub.setFont(QFont("Segoe UI", 10))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        top_bar.addWidget(lbl_sub)

        top_bar.addStretch()

        # Mode Selector (Online Search vs. Gemerkte Fachbücher)
        self.btn_mode_online = QPushButton(" Globale Fachbuch-Suche")
        self.btn_mode_online.setIcon(create_vector_icon("search", "#FFFFFF", 13))
        self.btn_mode_online.setCursor(Qt.PointingHandCursor)
        self.btn_mode_online.setStyleSheet("""
            background: #1F6FEB;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: bold;
            font-size: 11px;
        """)
        self.btn_mode_online.clicked.connect(lambda: self._set_mode("online"))
        top_bar.addWidget(self.btn_mode_online)

        self.btn_mode_saved = QPushButton(" Gemerkte Bücher / Wunschliste")
        self.btn_mode_saved.setIcon(create_vector_icon("star", "#8B949E", 13))
        self.btn_mode_saved.setCursor(Qt.PointingHandCursor)
        self.btn_mode_saved.setStyleSheet("""
            background: #161B22;
            color: #8B949E;
            border: 1px solid #30363D;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 600;
            font-size: 11px;
        """)
        self.btn_mode_saved.clicked.connect(lambda: self._set_mode("wishlist"))
        top_bar.addWidget(self.btn_mode_saved)

        # Inspector toggle button
        self.btn_toggle_inspector = QPushButton(" Inspektor einblenden")
        self.btn_toggle_inspector.setIcon(create_vector_icon("search", "#58A6FF", 13))
        self.btn_toggle_inspector.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_inspector.setStyleSheet("""
            background: #141C2E;
            color: #58A6FF;
            border: 1px solid #1F6FEB;
            border-radius: 6px;
            padding: 6px 12px;
            font-weight: 600;
            font-size: 11px;
        """)
        self.btn_toggle_inspector.clicked.connect(self._toggle_inspector)
        top_bar.addWidget(self.btn_toggle_inspector)

        root.addLayout(top_bar)

        # 2. Search & Faculty Chips Card
        search_card = QFrame()
        search_card.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        s_layout = QVBoxLayout(search_card)
        s_layout.setContentsMargins(12, 10, 12, 10)
        s_layout.setSpacing(10)

        # Input row
        inp_row = QHBoxLayout()
        inp_row.setSpacing(10)

        self.inp_search = QLineEdit()
        self.inp_search.setPlaceholderText("Fachbuch, Lehrbuch, Monographie oder Thema suchen (z.B. Lineare Algebra, Strafrecht AT, Biochemie)...")
        self.inp_search.setStyleSheet("""
            QLineEdit {
                background-color: #0B0F19;
                border: 1px solid #304163;
                border-radius: 6px;
                color: #F0F6FC;
                padding: 8px 14px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
            }
        """)
        self.inp_search.returnPressed.connect(self._trigger_search)
        inp_row.addWidget(self.inp_search, stretch=1)

        self.combo_year_filter = QComboBox()
        self.combo_year_filter.addItems([
            "Aktuelle Literatur (ab 2010)",
            "Moderne Literatur (ab 2000)",
            "Ab 1990",
            "Alle Jahre (inkl. Historisch)",
        ])
        self.combo_year_filter.setStyleSheet("""
            QComboBox {
                background-color: #0B0F19;
                color: #58A6FF;
                border: 1px solid #304163;
                border-radius: 6px;
                padding: 6px 12px;
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
        inp_row.addWidget(self.combo_year_filter)

        self.btn_search = QPushButton(" Fachbücher suchen")
        self.btn_search.setIcon(create_vector_icon("search", "#FFFFFF", 14))
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #388BFD;
            }
        """)
        self.btn_search.clicked.connect(self._trigger_search)
        inp_row.addWidget(self.btn_search)

        s_layout.addLayout(inp_row)

        # Quick Faculty Chips
        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)

        lbl_chips_t = QLabel("Schnellfilter:")
        lbl_chips_t.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold;")
        self.chips_row.addWidget(lbl_chips_t)

        popular_faculties = [
            "Mathematik", "Informatik & Programmierung", "Rechtswissenschaften & Jura",
            "Wirtschaftswissenschaften", "Physik & Astronomie", "Medizin & Pharmazie",
            "Psychologie & Soziologie"
        ]
        for fac in popular_faculties:
            btn_c = QPushButton(fac)
            btn_c.setCursor(Qt.PointingHandCursor)
            btn_c.setStyleSheet("""
                QPushButton {
                    background-color: #161B22;
                    color: #8B949E;
                    border: 1px solid #30363D;
                    border-radius: 12px;
                    padding: 3px 10px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #21262D;
                    border-color: #58A6FF;
                    color: #58A6FF;
                }
            """)
            btn_c.clicked.connect(lambda ch, f=fac: self._chip_clicked(f))
            self.chips_row.addWidget(btn_c)

        self.chips_row.addStretch()
        s_layout.addLayout(self.chips_row)

        root.addWidget(search_card)

        # 3. Splitter: Results List + Inspector
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #232F48;
                width: 2px;
            }
        """)

        # Left: Results Container with ScrollArea
        res_container = QWidget()
        res_layout = QVBoxLayout(res_container)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(6)

        # Results header status label
        self.lbl_status = QLabel("Gib einen Suchbegriff ein oder wähle einen Fachbereich.")
        self.lbl_status.setStyleSheet("color: #8B949E; font-size: 11px; padding: 2px 4px;")
        res_layout.addWidget(self.lbl_status)

        self.scroll_results = QScrollArea()
        self.scroll_results.setWidgetResizable(True)
        self.scroll_results.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.results_inner = QWidget()
        self.results_layout = QVBoxLayout(self.results_inner)
        self.results_layout.setContentsMargins(0, 0, 8, 0)
        self.results_layout.setSpacing(10)
        self.results_layout.addStretch()

        self.scroll_results.setWidget(self.results_inner)
        res_layout.addWidget(self.scroll_results)

        self.splitter.addWidget(res_container)

        # Right: Inspector Panel
        self.inspector = TextbookInspector()
        self.inspector.close_requested.connect(self._close_inspector)
        self.inspector.save_requested.connect(self._on_save_book)
        self.splitter.addWidget(self.inspector)

        # Set initial splitter proportions (70% left, 30% right)
        self.splitter.setSizes([750, 350])
        root.addWidget(self.splitter, stretch=1)

    def load_data(self) -> None:
        """Called on tab switch."""
        if self.current_mode == "wishlist":
            self._load_wishlist()

    def _set_mode(self, mode: str) -> None:
        self.current_mode = mode
        if mode == "online":
            self.btn_mode_online.setStyleSheet("""
                background: #1F6FEB; color: #FFFFFF; border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            """)
            self.btn_mode_saved.setStyleSheet("""
                background: #161B22; color: #8B949E; border: 1px solid #30363D; border-radius: 6px; padding: 6px 14px; font-weight: 600; font-size: 11px;
            """)
            self.lbl_status.setText("Globale Suche: Treffer aus DNB, Google Books & Crossref.")
        else:
            self.btn_mode_online.setStyleSheet("""
                background: #161B22; color: #8B949E; border: 1px solid #30363D; border-radius: 6px; padding: 6px 14px; font-weight: 600; font-size: 11px;
            """)
            self.btn_mode_saved.setStyleSheet("""
                background: #1F6FEB; color: #FFFFFF; border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            """)
            self._load_wishlist()

    def _chip_clicked(self, faculty: str) -> None:
        kw = BOOK_FACULTY_KEYWORDS.get(faculty, faculty)
        self.inp_search.setText(faculty)
        self._trigger_search(custom_query=kw)

    def _trigger_search(self, custom_query: Optional[str] = None) -> None:
        query = (custom_query or self.inp_search.text()).strip()
        if not query:
            return

        self._set_mode("online")
        self.btn_search.setEnabled(False)
        self.btn_search.setText(" Suche läuft...")
        self.lbl_status.setText(f"Recherchiere Fachliteratur zu »{query}« über DNB, Crossref, Open Library & Google Books...")

        # Determine min_year from dropdown
        idx = self.combo_year_filter.currentIndex()
        if idx == 0:
            min_yr = 2010
        elif idx == 1:
            min_yr = 2000
        elif idx == 2:
            min_yr = 1990
        else:
            min_yr = 0

        def worker():
            try:
                results = search_all_textbooks(query, min_year=min_yr, max_results=80)
                self.signals.search_finished.emit(results)
            except Exception as e:
                self.signals.search_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_finished(self, results: List[Dict[str, Any]]) -> None:
        self.btn_search.setEnabled(True)
        self.btn_search.setText(" Fachbücher suchen")
        self.lbl_status.setText(f"{len(results)} Fachbücher und Monographien gefunden.")

        self._render_cards(results)

    def _on_search_error(self, err_msg: str) -> None:
        self.btn_search.setEnabled(True)
        self.btn_search.setText(" Fachbücher suchen")
        self.lbl_status.setText(f"Fehler bei der Suche: {err_msg}")

    def _clear_results(self) -> None:
        self.active_cards.clear()
        while self.results_layout.count() > 1:
            child = self.results_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _render_cards(self, books: List[Dict[str, Any]]) -> None:
        self._clear_results()
        if not books:
            lbl_empty = QLabel("Keine Treffer zu dieser Suchanfrage gefunden.")
            lbl_empty.setStyleSheet("color: #8B949E; font-size: 12px; padding: 20px;")
            self.results_layout.insertWidget(0, lbl_empty)
            return

        first_card = None
        for i, book in enumerate(books):
            card = TextbookResultCard(book)
            card.inspect_requested.connect(self._select_card)
            card.save_requested.connect(self._on_save_book)
            card.apa_requested.connect(self._copy_apa)
            card.bibtex_requested.connect(self._copy_bibtex)
            card.open_edge_requested.connect(self._open_edge)
            card.open_uni_requested.connect(self._open_uni)
            self.active_cards.append(card)
            self.results_layout.insertWidget(i, card)
            if i == 0:
                first_card = card

        if first_card:
            self._select_card(books[0])

    def _select_card(self, book: Dict[str, Any]) -> None:
        # Show inspector if hidden
        if self.inspector.isHidden():
            self.inspector.show()
            self.btn_toggle_inspector.setText(" Inspektor ausblenden")
            self.splitter.setSizes([750, 350])

        for c in self.active_cards:
            is_match = (c.book.get("title") == book.get("title") and c.book.get("isbn") == book.get("isbn"))
            c.set_selected(is_match)

        self.inspector.load_book(book)

    def _toggle_inspector(self) -> None:
        if self.inspector.isVisible():
            self._close_inspector()
        else:
            self.inspector.show()
            self.btn_toggle_inspector.setText(" Inspektor ausblenden")
            self.splitter.setSizes([750, 350])

    def _close_inspector(self) -> None:
        self.inspector.hide()
        self.btn_toggle_inspector.setText(" Inspektor einblenden")

    def _copy_apa(self, book: Dict[str, Any]) -> None:
        text = generate_textbook_apa7(book)
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "Kopiert", "APA 7 Zitation wurde in die Zwischenablage kopiert.")

    def _copy_bibtex(self, book: Dict[str, Any]) -> None:
        text = generate_textbook_bibtex(book)
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "Kopiert", "BibTeX Eintrag wurde in die Zwischenablage kopiert.")

    def _open_edge(self, book: Dict[str, Any]) -> None:
        url = book.get("preview_url") or f"https://www.google.de/search?tbm=bks&q={urllib.parse.quote(book.get('title', ''))}"
        launch_in_browser(url)

    def _open_uni(self, book: Dict[str, Any]) -> None:
        url = build_textbook_institution_url(book)
        launch_in_browser(url)

    def _on_save_book(self, book: Dict[str, Any]) -> None:
        existing = find_saved_textbook(book.get("title", ""), book.get("isbn", ""))
        if existing:
            # Delete/remove
            delete_saved_textbook(existing.get("id"))
            QMessageBox.information(self, "Entfernt", f"»{book.get('title')}« wurde aus der Wunschliste entfernt.")
        else:
            # Save
            save_textbook(book)
            QMessageBox.information(self, "Gemerkt", f"»{book.get('title')}« wurde auf die Fachbuch-Wunschliste gesetzt.")

        # Update inspector button if active
        if self.inspector.current_book and self.inspector.current_book.get("title") == book.get("title"):
            self.inspector.update_wishlist_state()

        if self.current_mode == "wishlist":
            self._load_wishlist()
        else:
            # Refresh card save state
            for c in self.active_cards:
                if c.book.get("title") == book.get("title"):
                    is_saved = bool(find_saved_textbook(book.get("title", ""), book.get("isbn", "")))
                    c.update_save_status(is_saved)

    def _load_wishlist(self) -> None:
        books = get_all_saved_textbooks()
        self.lbl_status.setText(f"{len(books)} vorgemerkte Fachbücher auf deiner Wunschliste.")
        self._render_cards(books)

