"""Academic Research & Scientific Paper Sentinel View for PySide6.
Features arXiv & Semantic Scholar Discovery, FernUniversität in Hagen Institutional Proxy routing,
BibTeX citation export, and a completely isolated local Research Paper Archive.
"""

import os
import time
import threading
import urllib.parse
import subprocess
import webbrowser
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal, QObject, QSize, QTimer, QEvent
from PySide6.QtGui import QFont, QColor, QGuiApplication
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
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QDialog,
    QCheckBox,
    QComboBox,
    QSizePolicy,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.library_db import (
    save_research_paper,
    get_all_research_papers,
    delete_research_paper,
    get_institution_settings,
    update_institution_settings,
    open_pdf_in_edge,
    get_paper_category_counts,
    find_saved_research_paper,
)
from ai.paper_search import (
    search_all_papers,
    build_institution_url,
    download_paper_pdf,
    generate_paper_bibtex,
    generate_paper_apa7,
    FACULTY_SEARCH_TERMS,
    translate_abstract_to_german,
    clean_abstract_text,
    find_similar_papers,
)
from ai.curated_papers import seed_all_faculty_papers
from ai.daily_paper import get_daily_paper_highlight
from ai.categories import STANDARD_CATEGORIES
from ui.qt.dialogs.quick_look import QuickLookDialog


class PaperSearchSignals(QObject):
    """Thread-safe signals for background academic search and downloading."""
    search_finished = Signal(list)
    search_error = Signal(str)
    download_finished = Signal(str, str)  # paper_id, local_path
    download_error = Signal(str)


class InstitutionDialog(QDialog):
    """Configuration dialog for university EZProxy / Shibboleth access."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hochschul- & Bibliothekszugang")
        self.setFixedSize(520, 360)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F1422;
                border: 1px solid #232F48;
                border-radius: 10px;
            }
            QLabel {
                color: #F0F6FC;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #0B0F19;
                border: 1px solid #304163;
                border-radius: 6px;
                color: #F0F6FC;
                padding: 6px 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        lbl_t = QLabel("🏛️ Hochschul- & Lizenzzugang (EZProxy)")
        lbl_t.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(lbl_t)

        lbl_desc = QLabel(
            "Kostenpflichtige wissenschaftliche Fachartikel (Springer, IEEE, Wiley, JSTOR) "
            "werden automatisch über den lizenzierten Proxy deiner Hochschule geroutet."
        )
        lbl_desc.setStyleSheet("color: #8B949E; font-size: 11px; line-height: 1.4;")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        cfg = get_institution_settings()

        layout.addWidget(QLabel("Name der Hochschule / Universität:"))
        self.ent_name = QLineEdit(cfg.get("institution_name", "FernUniversität in Hagen"))
        layout.addWidget(self.ent_name)

        layout.addWidget(QLabel("EZProxy-Präfix der Universitätsbibliothek:"))
        self.ent_prefix = QLineEdit(cfg.get("ezproxy_prefix", "https://login.ub-proxy.fernuni-hagen.de/login?url="))
        layout.addWidget(self.ent_prefix)

        self.chk_auto = QCheckBox("Automatisch über Uni-Proxy leiten")
        self.chk_auto.setChecked(bool(cfg.get("auto_proxy", 1)))
        self.chk_auto.setStyleSheet("color: #C9D1D9; font-size: 12px;")
        layout.addWidget(self.chk_auto)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("background: transparent; color: #8B949E; border: 1px solid #30363D; border-radius: 6px; padding: 6px 14px;")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("Einstellungen speichern")
        btn_save.setObjectName("primaryButton")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-weight: bold; border: none; border-radius: 6px; padding: 6px 16px;")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _save(self) -> None:
        update_institution_settings(
            institution_name=self.ent_name.text().strip(),
            ezproxy_prefix=self.ent_prefix.text().strip(),
            auto_proxy=self.chk_auto.isChecked()
        )
        self.accept()


class PaperResultCard(QFrame):
    """Interactive result card for an online scientific paper with instant inspection and APA 7 citation."""

    inspect_requested = Signal(dict)
    apa_requested = Signal(dict)
    save_requested = Signal(dict)
    open_edge_requested = Signal(dict)
    open_uni_requested = Signal(dict)
    open_direct_requested = Signal(dict)
    bibtex_requested = Signal(dict)

    def __init__(self, paper: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.paper = paper
        self.abstract_visible = False
        self._translated_de = None
        self.is_selected = False
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Title & Badges
        top_h = QHBoxLayout()
        top_h.setSpacing(8)

        self.lbl_t = QLabel(paper.get("title", ""))
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

        cat = paper.get("category", "").strip()
        if cat:
            cat_badge = QLabel(f"🏷️ {cat}")
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

        cites = paper.get("citation_count", 0)
        if cites and cites > 0:
            cite_badge = QLabel(f"⭐ {cites:,} Zitationen".replace(",", "."))
            cite_badge.setStyleSheet("""
                background-color: #261B33;
                color: #D2A8FF;
                border: 1px solid #8957E5;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            """)
            top_h.addWidget(cite_badge)

        is_oa = bool(paper.get("is_open_access"))
        oa_badge = QLabel("🟢 Open Access" if is_oa else "🔒 Verlags-Paywall")
        oa_badge.setStyleSheet(f"""
            background-color: {'rgba(35, 134, 54, 0.25)' if is_oa else 'rgba(218, 54, 51, 0.2)'};
            color: {'#3FB950' if is_oa else '#F85149'};
            border: 1px solid {'#238636' if is_oa else '#DA3633'};
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        oa_badge.setToolTip("Freier Volltext verfügbar (Download möglich)" if is_oa else "Verlags-Abonnement erforderlich (Zugriff über Uni-Proxy)")
        top_h.addWidget(oa_badge)

        layout.addLayout(top_h)

        # Authors, Year, Journal
        authors = paper.get("authors", "Unbekannt")
        year = paper.get("year", "")
        journal = paper.get("journal", "")
        meta_str = f"von {authors} ({year}) · {journal}"
        lbl_meta = QLabel(meta_str)
        lbl_meta.setFont(QFont("Segoe UI", 9))
        lbl_meta.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        lbl_meta.setWordWrap(True)
        layout.addWidget(lbl_meta)

        # Abstract Container (collapsible with DE/EN toggle)
        self.abs_container = QWidget()
        self.abs_container.setVisible(False)
        abs_box_layout = QVBoxLayout(self.abs_container)
        abs_box_layout.setContentsMargins(0, 4, 0, 4)
        abs_box_layout.setSpacing(6)

        abs_top_row = QHBoxLayout()
        abs_top_row.setSpacing(6)

        lbl_abs_h = QLabel("Wissenschaftlicher Abstract:")
        lbl_abs_h.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold;")
        abs_top_row.addWidget(lbl_abs_h)

        abs_top_row.addStretch()

        self.btn_lang_de = QPushButton("🇩🇪 Deutsch")
        self.btn_lang_de.setCursor(Qt.PointingHandCursor)
        self.btn_lang_de.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
        self.btn_lang_de.clicked.connect(self._show_de_abstract)
        abs_top_row.addWidget(self.btn_lang_de)

        self.btn_lang_en = QPushButton("🇬🇧 Original")
        self.btn_lang_en.setCursor(Qt.PointingHandCursor)
        self.btn_lang_en.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
        self.btn_lang_en.clicked.connect(self._show_en_abstract)
        abs_top_row.addWidget(self.btn_lang_en)

        abs_box_layout.addLayout(abs_top_row)

        cleaned_abs = clean_abstract_text(paper.get("abstract", ""), paper.get("title"), paper.get("year"))
        self.lbl_abstract = QLabel(cleaned_abs)
        self.lbl_abstract.setFont(QFont("Segoe UI", 9))
        self.lbl_abstract.setStyleSheet("color: #C9D1D9; border: 1px solid #232F48; background: #0E1422; border-radius: 6px; padding: 10px; line-height: 1.5;")
        self.lbl_abstract.setWordWrap(True)
        abs_box_layout.addWidget(self.lbl_abstract)

        layout.addWidget(self.abs_container)

        # Action Buttons (Clean, balanced layout)
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)
        btn_bar.setAlignment(Qt.AlignVCenter)

        self.btn_toggle_abs = QPushButton("Abstract anzeigen ▾")
        self.btn_toggle_abs.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_abs.setStyleSheet("background: transparent; color: #58A6FF; border: none; font-size: 11px; font-weight: bold;")
        self.btn_toggle_abs.clicked.connect(self._toggle_abstract)
        btn_bar.addWidget(self.btn_toggle_abs)

        btn_bar.addStretch()

        # APA 7 Citation Copy
        self.btn_apa = QPushButton("  APA 7 zitieren")
        self.btn_apa.setIcon(create_vector_icon("copy", "#D2A8FF", 12))
        self.btn_apa.setIconSize(QSize(12, 12))
        self.btn_apa.setCursor(Qt.PointingHandCursor)
        self.btn_apa.setStyleSheet("background: #211933; border: 1px solid #8957E5; color: #D2A8FF; border-radius: 5px; padding: 4px 11px; font-size: 11px; font-weight: 600;")
        self.btn_apa.clicked.connect(self._copy_apa)
        btn_bar.addWidget(self.btn_apa)

        # Direct Open in Edge
        self.btn_edge = QPushButton("  In Edge öffnen")
        self.btn_edge.setIcon(create_vector_icon("desk", "#3FB950", 12))
        self.btn_edge.setIconSize(QSize(12, 12))
        self.btn_edge.setCursor(Qt.PointingHandCursor)
        self.btn_edge.setToolTip("Öffnet das Paper sofort in Microsoft Edge")
        self.btn_edge.setStyleSheet("background: #14281E; border: 1px solid #238636; color: #3FB950; border-radius: 5px; padding: 4px 11px; font-size: 11px; font-weight: 600;")
        self.btn_edge.clicked.connect(lambda: self.open_edge_requested.emit(self.paper))
        btn_bar.addWidget(self.btn_edge)

        # Save / Download Button
        is_oa_paper = bool(paper.get("is_open_access"))
        self.btn_save = QPushButton("  ⚡ PDF & Archiv sichern" if is_oa_paper else "  Speichern")
        self.btn_save.setIcon(create_vector_icon("download", "#FFFFFF", 12))
        self.btn_save.setIconSize(QSize(12, 12))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setToolTip("Lädt die Volltext-PDF-Datei direkt herunter und sichert sie im Archiv" if is_oa_paper else "Sichert das Paper im Archiv")
        if is_oa_paper:
            self.btn_save.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
                    border: none;
                    color: #FFFFFF;
                    border-radius: 5px;
                    padding: 4px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #2EA043;
                }
            """)
        else:
            self.btn_save.setStyleSheet("""
                QPushButton {
                    background: #1F6FEB;
                    border: none;
                    color: #FFFFFF;
                    border-radius: 5px;
                    padding: 4px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #388BFD;
                }
            """)
        self.btn_save.clicked.connect(lambda: self.save_requested.emit(self.paper))
        btn_bar.addWidget(self.btn_save)

        layout.addLayout(btn_bar)
        self._update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.inspect_requested.emit(self.paper)
        super().mousePressEvent(event)

    def _copy_apa(self) -> None:
        citation = generate_paper_apa7(self.paper)
        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText(citation)
        self.btn_apa.setText("  ✓ APA 7 kopiert!")
        self.btn_apa.setStyleSheet("background: #238636; border: 1px solid #2EA043; color: #FFFFFF; border-radius: 5px; padding: 4px 10px; font-size: 11px; font-weight: bold;")
        self.apa_requested.emit(self.paper)
        QTimer.singleShot(2200, self._reset_apa_button)

    def _reset_apa_button(self) -> None:
        self.btn_apa.setText("  APA 7 zitieren")
        self.btn_apa.setStyleSheet("background: #211933; border: 1px solid #8957E5; color: #D2A8FF; border-radius: 5px; padding: 4px 10px; font-size: 11px; font-weight: 600;")

    def _toggle_abstract(self) -> None:
        self.abstract_visible = not self.abstract_visible
        self.abs_container.setVisible(self.abstract_visible)
        self.btn_toggle_abs.setText("Abstract einklappen ▴" if self.abstract_visible else "Abstract anzeigen ▾")
        if self.abstract_visible and not getattr(self, "_translated_de", None):
            self._show_de_abstract()

    def _show_de_abstract(self) -> None:
        raw = clean_abstract_text(self.paper.get("abstract", ""), self.paper.get("title"), self.paper.get("year"))
        self.btn_lang_de.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
        self.btn_lang_en.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
        if not getattr(self, "_translated_de", None):
            self.lbl_abstract.setText("⏳ Übersetze Abstract ins Deutsche...")
            import threading
            def worker():
                de_text = translate_abstract_to_german(raw)
                self._translated_de = de_text
                from PySide6.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(self.lbl_abstract, "setText", Qt.QueuedConnection, de_text)
            threading.Thread(target=worker, daemon=True).start()
        else:
            self.lbl_abstract.setText(self._translated_de)

    def _show_en_abstract(self) -> None:
        raw = clean_abstract_text(self.paper.get("abstract", ""), self.paper.get("title"), self.paper.get("year"))
        self.btn_lang_en.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
        self.btn_lang_de.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
        self.lbl_abstract.setText(raw)

    def set_selected(self, selected: bool) -> None:
        if getattr(self, "is_selected", False) != selected:
            self.is_selected = selected
            self._update_style()

    def _update_style(self) -> None:
        if getattr(self, "is_selected", False):
            self.setStyleSheet("""
                PaperResultCard {
                    background-color: #17243B;
                    border: 1.5px solid #58A6FF;
                    border-left: 6px solid #58A6FF;
                    border-radius: 8px;
                }
                PaperResultCard:hover {
                    background-color: #1A2B47;
                    border-color: #79C0FF;
                    border-left: 6px solid #79C0FF;
                }
            """)
            if hasattr(self, "lbl_t"):
                self.lbl_t.setStyleSheet("color: #FFFFFF; font-weight: bold; border: none; background: transparent;")
            if hasattr(self, "badge_active"):
                self.badge_active.setVisible(True)
        else:
            self.setStyleSheet("""
                PaperResultCard {
                    background-color: #121826;
                    border: 1px solid #232F48;
                    border-left: 4px solid #2B384E;
                    border-radius: 8px;
                }
                PaperResultCard:hover {
                    background-color: #151E32;
                    border-color: #388BFD;
                    border-left: 4px solid #388BFD;
                }
            """)
            if hasattr(self, "lbl_t"):
                self.lbl_t.setStyleSheet("color: #E6EDF3; font-weight: bold; border: none; background: transparent;")
            if hasattr(self, "badge_active"):
                self.badge_active.setVisible(False)



class ResearchView(QWidget):
    """Dedicated Academic Research & Scientific Paper Hub."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "search"  # 'search' vs. 'archive'
        self._search_thread = None
        self._signals = PaperSearchSignals()
        self._signals.search_finished.connect(self._on_search_finished)
        self._signals.search_error.connect(self._on_search_error)
        self._signals.download_finished.connect(self._on_download_finished)
        self._signals.download_error.connect(self._on_download_error)

        self._saved_papers: List[Dict[str, Any]] = []
        self._active_saved_paper: Optional[Dict[str, Any]] = None
        self._active_search_paper: Optional[Dict[str, Any]] = None
        self._raw_search_results: List[Dict[str, Any]] = []
        self._search_cards: List[PaperResultCard] = []
        self._current_pdt: Optional[Dict[str, Any]] = None
        self._pdt_offset = 0
        self._pdt_collapsed = False
        self._inspector_visible = True

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 18)
        main_layout.setSpacing(14)

        # Top Header Bar: Title + Institution Badge
        top_bar = QHBoxLayout()
        top_bar.setAlignment(Qt.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)

        title_h = QHBoxLayout()
        title_h.setSpacing(8)
        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_pixmap("research", "#58A6FF", 22))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        title_h.addWidget(lbl_icon)

        lbl_t = QLabel("Paper & Forschungs-Lab")
        lbl_t.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_t.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        title_h.addWidget(lbl_t)
        title_h.addStretch()
        title_box.addLayout(title_h)

        lbl_sub = QLabel("Wissenschaftliche Literatur-Recherche (peDOCS Bildungsforschung, ERIC, OpenAlex, Crossref, arXiv) mit Lizenz-Routing")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        title_box.addWidget(lbl_sub)
        top_bar.addLayout(title_box, stretch=1)

        # University / Institution Banner
        cfg = get_institution_settings()
        inst_name = cfg.get("institution_name", "FernUniversität in Hagen")

        inst_card = QFrame()
        inst_card.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 4px 10px;
            }
        """)
        inst_layout = QHBoxLayout(inst_card)
        inst_layout.setContentsMargins(8, 4, 8, 4)
        inst_layout.setSpacing(8)

        lbl_inst_icon = QLabel()
        lbl_inst_icon.setPixmap(create_vector_pixmap("institution", "#58A6FF", 16))
        lbl_inst_icon.setStyleSheet("border: none; background: transparent;")
        inst_layout.addWidget(lbl_inst_icon)

        self.lbl_inst_title = QLabel(f"Zugang: {inst_name}")
        self.lbl_inst_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_inst_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        inst_layout.addWidget(self.lbl_inst_title)

        btn_cfg = QPushButton("⚙")
        btn_cfg.setToolTip("Hochschulzugang / Proxy konfigurieren")
        btn_cfg.setCursor(Qt.PointingHandCursor)
        btn_cfg.setStyleSheet("background: transparent; color: #8B949E; border: none; font-size: 13px;")
        btn_cfg.clicked.connect(self._open_institution_dialog)
        inst_layout.addWidget(btn_cfg)

        top_bar.addWidget(inst_card)
        main_layout.addLayout(top_bar)

        # Tab Navigation Switcher: [🌐 Globale Paper-Suche] vs [📂 Mein Paper-Archiv]
        switch_frame = QWidget()
        switch_frame.setStyleSheet("""
            QWidget {
                background-color: #0A0E17;
                border: 1px solid #1C2436;
                border-radius: 8px;
            }
        """)
        switch_layout = QHBoxLayout(switch_frame)
        switch_layout.setContentsMargins(4, 4, 4, 4)
        switch_layout.setSpacing(6)

        self.btn_tab_search = QPushButton("  Globale Paper-Recherche (peDOCS, ERIC, arXiv & Crossref)")
        self.btn_tab_search.setIcon(create_vector_icon("research", "#58A6FF", 16))
        self.btn_tab_search.setCursor(Qt.PointingHandCursor)
        self.btn_tab_search.setStyleSheet("""
            QPushButton {
                background-color: #1A263D;
                color: #58A6FF;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 7px 18px;
            }
        """)
        self.btn_tab_search.clicked.connect(lambda: self._set_mode("search"))
        switch_layout.addWidget(self.btn_tab_search)

        self.btn_tab_archive = QPushButton("  Mein Paper-Archiv (Gespeichert)")
        self.btn_tab_archive.setIcon(create_vector_icon("library", "#8B949E", 16))
        self.btn_tab_archive.setCursor(Qt.PointingHandCursor)
        self.btn_tab_archive.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #8B949E;
                font-size: 12px;
                font-weight: 500;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 7px 18px;
            }
            QPushButton:hover {
                background-color: #121826;
                color: #C9D1D9;
                border-color: #232F48;
            }
        """)
        self.btn_tab_archive.clicked.connect(lambda: self._set_mode("archive"))
        switch_layout.addWidget(self.btn_tab_archive)

        switch_layout.addStretch()

        # Toggle Inspector Visibility Button
        self.btn_toggle_inspector = QPushButton("  📖 Inspektor ausblenden")
        self.btn_toggle_inspector.setIcon(create_vector_icon("research", "#58A6FF", 14))
        self.btn_toggle_inspector.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_inspector.setStyleSheet("""
            QPushButton {
                background-color: #121A28;
                color: #58A6FF;
                border: 1px solid #1E2D48;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1A263D;
                color: #FFFFFF;
                border-color: #388BFD;
            }
        """)
        self.btn_toggle_inspector.clicked.connect(self._toggle_inspector)
        switch_layout.addWidget(self.btn_toggle_inspector)

        main_layout.addWidget(switch_frame)

        # =========================================================================
        # SECTION A: SEARCH & DISCOVERY CONTAINER
        # =========================================================================
        self.search_container = QWidget()
        s_layout = QVBoxLayout(self.search_container)
        s_layout.setContentsMargins(0, 4, 0, 0)
        s_layout.setSpacing(10)

        # Search Bar
        search_box = QHBoxLayout()
        search_box.setSpacing(8)

        self.ent_search = QLineEdit()
        self.ent_search.setPlaceholderText("Thema, Fachbegriff, DOI, arXiv-ID oder Autor suchen (z. B. Machine Learning, Attention, Strafrecht)...")
        self.ent_search.setFixedHeight(38)
        self.ent_search.setStyleSheet("""
            QLineEdit {
                background-color: #0D111A;
                border: 1px solid #232F48;
                border-radius: 6px;
                color: #F0F6FC;
                padding-left: 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
            }
        """)
        self.ent_search.returnPressed.connect(self._start_search)
        search_box.addWidget(self.ent_search, stretch=1)

        self.btn_search = QPushButton("  Paper suchen")
        self.btn_search.setIcon(create_vector_icon("search", "#FFFFFF", 16))
        self.btn_search.setObjectName("primaryButton")
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.setFixedHeight(38)
        self.btn_search.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-weight: bold; border: none; border-radius: 6px; padding: 0 18px;")
        self.btn_search.clicked.connect(self._start_search)
        search_box.addWidget(self.btn_search)

        self.btn_scholar = QPushButton("  Google Scholar")
        self.btn_scholar.setIcon(create_vector_icon("globe", "#58A6FF", 15))
        self.btn_scholar.setCursor(Qt.PointingHandCursor)
        self.btn_scholar.setFixedHeight(38)
        self.btn_scholar.setToolTip("Öffnet die aktuelle Suchanfrage direkt in Google Scholar (Microsoft Edge)")
        self.btn_scholar.setStyleSheet("""
            QPushButton {
                background: #16243E;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 6px;
                padding: 0 14px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #1F3660;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        self.btn_scholar.clicked.connect(self._open_google_scholar_search)
        search_box.addWidget(self.btn_scholar)

        s_layout.addLayout(search_box)

        # Quick Subject Chips across all academic faculties with slide arrows and wheel scrolling
        chips_container = QWidget()
        chips_container.setStyleSheet("background: transparent;")
        chips_outer_layout = QHBoxLayout(chips_container)
        chips_outer_layout.setContentsMargins(0, 0, 0, 0)
        chips_outer_layout.setSpacing(6)

        lbl_chip_hint = QLabel("Fachbereiche:")
        lbl_chip_hint.setStyleSheet("color: #6E7681; font-size: 11px; font-weight: bold; margin-right: 2px;")
        chips_outer_layout.addWidget(lbl_chip_hint)

        btn_arrow_style = """
            QPushButton {
                background-color: #16243E;
                border: 1px solid #2B3D5F;
                border-radius: 14px;
            }
            QPushButton:hover {
                background-color: #1F3660;
                border-color: #58A6FF;
            }
            QPushButton:pressed {
                background-color: #10192A;
            }
        """

        self.btn_chips_prev = QPushButton()
        self.btn_chips_prev.setFixedSize(28, 28)
        self.btn_chips_prev.setIcon(create_vector_icon("chevron_left", "#F0F6FC", 16))
        self.btn_chips_prev.setIconSize(QSize(16, 16))
        self.btn_chips_prev.setCursor(Qt.PointingHandCursor)
        self.btn_chips_prev.setStyleSheet(btn_arrow_style)
        self.btn_chips_prev.setToolTip("Fachbereiche nach links scrollen")
        chips_outer_layout.addWidget(self.btn_chips_prev)

        self.chips_scroll = QScrollArea()
        self.chips_scroll.setFixedHeight(36)
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chips_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        chips_widget = QWidget()
        chips_widget.setStyleSheet("background: transparent;")
        chips_layout = QHBoxLayout(chips_widget)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(6)

        for faculty_name, query_terms in FACULTY_SEARCH_TERMS.items():
            btn_chip = QPushButton(faculty_name)
            btn_chip.setCursor(Qt.PointingHandCursor)
            btn_chip.setStyleSheet("""
                QPushButton {
                    background-color: #121826;
                    border: 1px solid #232F48;
                    color: #8B949E;
                    border-radius: 5px;
                    padding: 4px 10px;
                    font-size: 11px;
                    white-space: nowrap;
                }
                QPushButton:hover {
                    background-color: #1A2438;
                    color: #58A6FF;
                    border-color: #388BFD;
                }
            """)
            btn_chip.clicked.connect(lambda checked, q=query_terms, fac=faculty_name: self._search_faculty(fac, q))
            chips_layout.addWidget(btn_chip)

        chips_layout.addStretch()
        self.chips_scroll.setWidget(chips_widget)
        chips_outer_layout.addWidget(self.chips_scroll, stretch=1)

        self.btn_chips_next = QPushButton()
        self.btn_chips_next.setFixedSize(28, 28)
        self.btn_chips_next.setIcon(create_vector_icon("chevron_right", "#F0F6FC", 16))
        self.btn_chips_next.setIconSize(QSize(16, 16))
        self.btn_chips_next.setCursor(Qt.PointingHandCursor)
        self.btn_chips_next.setStyleSheet(btn_arrow_style)
        self.btn_chips_next.setToolTip("Fachbereiche nach rechts scrollen")
        chips_outer_layout.addWidget(self.btn_chips_next)

        self.btn_chips_prev.clicked.connect(lambda: self.chips_scroll.horizontalScrollBar().setValue(self.chips_scroll.horizontalScrollBar().value() - 250))
        self.btn_chips_next.clicked.connect(lambda: self.chips_scroll.horizontalScrollBar().setValue(self.chips_scroll.horizontalScrollBar().value() + 250))
        self.chips_scroll.viewport().installEventFilter(self)

        s_layout.addWidget(chips_container)

        # Paper des Tages (Daily Academic Landmark Paper Highlight)
        self.pdt_card = self._build_paper_of_the_day_card()
        s_layout.addWidget(self.pdt_card)

        # Search Filter & Sorting Toolbar
        search_filter_bar = QHBoxLayout()
        search_filter_bar.setSpacing(10)
        search_filter_bar.setAlignment(Qt.AlignVCenter)

        lbl_sort = QLabel("Sortierung:")
        lbl_sort.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold;")
        search_filter_bar.addWidget(lbl_sort)

        self.combo_search_sort = QComboBox()
        self.combo_search_sort.addItems([
            "Relevanz (Standard)",
            "Erscheinungsjahr (Neueste zuerst)",
            "Erscheinungsjahr (Älteste zuerst)",
            "Zitationen (Meiste zuerst)"
        ])
        self.combo_search_sort.setStyleSheet("""
            QComboBox {
                background-color: #0D111A;
                border: 1px solid #232F48;
                border-radius: 5px;
                color: #C9D1D9;
                padding: 3px 8px;
                font-size: 11px;
                min-width: 170px;
            }
            QComboBox::drop-down { border: none; width: 14px; }
            QComboBox QAbstractItemView {
                background-color: #121826;
                border: 1px solid #232F48;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
            }
        """)
        self.combo_search_sort.currentIndexChanged.connect(self._apply_search_filters)
        search_filter_bar.addWidget(self.combo_search_sort)

        lbl_year = QLabel("Zeitraum:")
        lbl_year.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold; margin-left: 6px;")
        search_filter_bar.addWidget(lbl_year)

        self.combo_search_year = QComboBox()
        self.combo_search_year.addItems([
            "Alle Jahre",
            "Seit 2024 (Brandneu)",
            "Seit 2020 (Letzte 5 Jahre)",
            "Seit 2015 (Letzte 10 Jahre)"
        ])
        self.combo_search_year.setStyleSheet("""
            QComboBox {
                background-color: #0D111A;
                border: 1px solid #232F48;
                border-radius: 5px;
                color: #C9D1D9;
                padding: 3px 8px;
                font-size: 11px;
                min-width: 140px;
            }
            QComboBox::drop-down { border: none; width: 14px; }
            QComboBox QAbstractItemView {
                background-color: #121826;
                border: 1px solid #232F48;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
            }
        """)
        self.combo_search_year.currentIndexChanged.connect(self._apply_search_filters)
        search_filter_bar.addWidget(self.combo_search_year)

        lbl_lang = QLabel("Sprache:")
        lbl_lang.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold; margin-left: 6px;")
        search_filter_bar.addWidget(lbl_lang)

        self.combo_search_lang = QComboBox()
        self.combo_search_lang.addItems([
            "Alle Sprachen",
            "🇩🇪 Nur Deutsch (DE)",
            "🇬🇧 Nur Englisch (EN)"
        ])
        self.combo_search_lang.setStyleSheet("""
            QComboBox {
                background-color: #0D111A;
                border: 1px solid #232F48;
                border-radius: 5px;
                color: #C9D1D9;
                padding: 3px 8px;
                font-size: 11px;
                min-width: 140px;
            }
            QComboBox::drop-down { border: none; width: 14px; }
            QComboBox QAbstractItemView {
                background-color: #121826;
                border: 1px solid #232F48;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
            }
        """)
        self.combo_search_lang.currentIndexChanged.connect(self._apply_search_filters)
        search_filter_bar.addWidget(self.combo_search_lang)

        self.chk_oa_only = QCheckBox("🔓 Nur Open Access (Sofort-Volltext)")
        self.chk_oa_only.setCursor(Qt.PointingHandCursor)
        self.chk_oa_only.setStyleSheet("""
            QCheckBox {
                color: #3FB950;
                font-size: 11px;
                font-weight: bold;
                margin-left: 8px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid #238636;
                background-color: #0D111A;
            }
            QCheckBox::indicator:checked {
                background-color: #238636;
            }
        """)
        self.chk_oa_only.toggled.connect(self._apply_search_filters)
        search_filter_bar.addWidget(self.chk_oa_only)

        search_filter_bar.addStretch()
        s_layout.addLayout(search_filter_bar)

        # Search Results Status Banner
        self.lbl_search_status = QLabel("Gib einen Suchbegriff ein oder wähle oben eine Fakultät, um weltweite Paper zu durchforsten.")
        self.lbl_search_status.setStyleSheet("color: #8B949E; font-size: 11px; padding-top: 2px;")
        s_layout.addWidget(self.lbl_search_status)

        # Search Results Scroll Area
        self.scroll_search = QScrollArea()
        self.scroll_search.setWidgetResizable(True)
        self.scroll_search.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self.results_container = QWidget()
        self.results_container.setStyleSheet("background-color: transparent; border: none;")
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 6, 0)
        self.results_layout.setSpacing(10)
        self.results_layout.addStretch()

        self.scroll_search.setWidget(self.results_container)
        self.scroll_search.verticalScrollBar().valueChanged.connect(self._on_search_scroll)
        s_layout.addWidget(self.scroll_search, stretch=1)

        main_layout.addWidget(self.search_container, stretch=1)

        # =========================================================================
        # SECTION B: LOCAL SAVED RESEARCH ARCHIVE CONTAINER
        # =========================================================================
        self.archive_container = QWidget()
        self.archive_container.setVisible(False)
        arc_layout = QVBoxLayout(self.archive_container)
        arc_layout.setContentsMargins(0, 4, 0, 0)
        arc_layout.setSpacing(8)

        # Row 1: Title, Status Counter & Primary Archive Actions
        arc_title_bar = QHBoxLayout()
        arc_title_bar.setContentsMargins(0, 2, 0, 4)
        arc_title_bar.setSpacing(10)

        lbl_arc_heading = QLabel("📂 Gesicherte Forschungsarbeiten")
        lbl_arc_heading.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_arc_heading.setStyleSheet("color: #F0F6FC;")
        arc_title_bar.addWidget(lbl_arc_heading)

        self.lbl_arc_t = QLabel("0 Dokumente · 0 Offline-PDFs")
        self.lbl_arc_t.setStyleSheet("""
            QLabel {
                background-color: #121826;
                color: #8B949E;
                border: 1px solid #232F48;
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }
        """)
        arc_title_bar.addWidget(self.lbl_arc_t)

        arc_title_bar.addStretch()

        self.btn_seed_curated = QPushButton("⚡ Meilenstein-Paper erfassen")
        self.btn_seed_curated.setCursor(Qt.PointingHandCursor)
        self.btn_seed_curated.setFixedHeight(30)
        self.btn_seed_curated.setToolTip("Erfasst wissenschaftliche Meilenstein-Paper für alle 15 Fachbereiche im Archiv")
        self.btn_seed_curated.setStyleSheet("""
            QPushButton {
                background: #16243E;
                border: 1px solid #1F6FEB;
                color: #58A6FF;
                font-size: 11px;
                font-weight: 600;
                border-radius: 5px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #1F3660;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        self.btn_seed_curated.clicked.connect(self._seed_curated_papers)
        arc_title_bar.addWidget(self.btn_seed_curated)

        self.btn_open_folder = QPushButton("📁 Ordner öffnen")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setFixedHeight(30)
        self.btn_open_folder.setToolTip("Öffnet das Papers-Verzeichnis am Speicherort der Bücher im Explorer")
        self.btn_open_folder.setStyleSheet("""
            QPushButton {
                background: #141B29;
                border: 1px solid #232F48;
                color: #C9D1D9;
                font-size: 11px;
                border-radius: 5px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #1C273C;
                border-color: #388BFD;
                color: #FFFFFF;
            }
        """)
        self.btn_open_folder.clicked.connect(self._open_papers_folder)
        arc_title_bar.addWidget(self.btn_open_folder)

        arc_layout.addLayout(arc_title_bar)

        # Row 2: Filter & Search Toolbar Card
        arc_filter_card = QWidget()
        arc_filter_card.setStyleSheet("""
            QWidget#arcFilterCard {
                background-color: #0D111A;
                border: 1px solid #1F293D;
                border-radius: 7px;
            }
        """)
        arc_filter_card.setObjectName("arcFilterCard")
        arc_filter_bar = QHBoxLayout(arc_filter_card)
        arc_filter_bar.setContentsMargins(8, 6, 8, 6)
        arc_filter_bar.setSpacing(8)

        self.ent_arc_filter = QLineEdit()
        self.ent_arc_filter.setPlaceholderText("🔍 Archiv durchsuchen...")
        self.ent_arc_filter.setFixedHeight(30)
        self.ent_arc_filter.setClearButtonEnabled(True)
        self.ent_arc_filter.setStyleSheet("""
            QLineEdit {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 5px;
                color: #F0F6FC;
                padding: 2px 10px;
                font-size: 11px;
                min-width: 170px;
            }
            QLineEdit:focus { border-color: #58A6FF; }
        """)
        self.ent_arc_filter.textChanged.connect(self._load_archive_table)
        arc_filter_bar.addWidget(self.ent_arc_filter)

        self.combo_fac_filter = QComboBox()
        self.combo_fac_filter.setFixedHeight(30)
        self.combo_fac_filter.addItem("Alle Fachbereiche")
        for fac in STANDARD_CATEGORIES:
            if fac != "Sonstiges":
                self.combo_fac_filter.addItem(fac)
        self.combo_fac_filter.setStyleSheet("""
            QComboBox {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 5px;
                color: #C9D1D9;
                padding: 2px 10px;
                font-size: 11px;
                min-width: 135px;
            }
            QComboBox::drop-down { border: none; width: 14px; }
            QComboBox QAbstractItemView {
                background-color: #121826;
                border: 1px solid #232F48;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
            }
        """)
        self.combo_fac_filter.currentIndexChanged.connect(self._load_archive_table)
        arc_filter_bar.addWidget(self.combo_fac_filter)

        self.combo_pdf_filter = QComboBox()
        self.combo_pdf_filter.setFixedHeight(30)
        self.combo_pdf_filter.addItems([
            "Alle Dokumente",
            "● Nur Offline-PDFs",
            "○ Nur Online-Verlinkte"
        ])
        self.combo_pdf_filter.setStyleSheet("""
            QComboBox {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 5px;
                color: #C9D1D9;
                padding: 2px 10px;
                font-size: 11px;
                min-width: 140px;
            }
            QComboBox::drop-down { border: none; width: 14px; }
            QComboBox QAbstractItemView {
                background-color: #121826;
                border: 1px solid #232F48;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
            }
        """)
        self.combo_pdf_filter.currentIndexChanged.connect(self._load_archive_table)
        arc_filter_bar.addWidget(self.combo_pdf_filter)

        self.combo_arc_sort = QComboBox()
        self.combo_arc_sort.setFixedHeight(30)
        self.combo_arc_sort.addItems([
            "Neueste zuerst (Jahr ↓)",
            "Älteste zuerst (Jahr ↑)",
            "Zitationen (Meiste ↓)",
            "Titel (A-Z)"
        ])
        self.combo_arc_sort.setStyleSheet("""
            QComboBox {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 5px;
                color: #C9D1D9;
                padding: 2px 10px;
                font-size: 11px;
                min-width: 140px;
            }
            QComboBox::drop-down { border: none; width: 14px; }
            QComboBox QAbstractItemView {
                background-color: #121826;
                border: 1px solid #232F48;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
            }
        """)
        self.combo_arc_sort.currentIndexChanged.connect(self._load_archive_table)
        arc_filter_bar.addWidget(self.combo_arc_sort)

        arc_filter_bar.addStretch()
        arc_layout.addWidget(arc_filter_card)

        self.table_archive = QTableWidget()
        self.table_archive.setColumnCount(4)
        self.table_archive.setHorizontalHeaderLabels(["Titel & Autoren", "Fachbereich", "Jahr / Journal", "Status"])
        self.table_archive.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_archive.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_archive.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_archive.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_archive.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_archive.setSelectionMode(QTableWidget.SingleSelection)
        self.table_archive.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_archive.setFocusPolicy(Qt.ClickFocus)
        self.table_archive.verticalHeader().setVisible(False)
        self.table_archive.setStyleSheet("""
            QTableWidget {
                background-color: #0D111A;
                border: 1px solid #1F293D;
                border-radius: 8px;
                outline: 0px;
                selection-background-color: #172642;
            }
            QTableWidget::item {
                border: none;
                border-bottom: 1px solid #141B29;
                outline: none;
                padding: 6px 12px;
            }
            QTableWidget::item:focus {
                border: none;
                outline: none;
            }
            QTableWidget::item:selected {
                background-color: #1A2A47;
                color: #FFFFFF;
                border: none;
                outline: none;
            }
            QTableWidget::item:selected:focus {
                background-color: #1A2A47;
                color: #FFFFFF;
                border: none;
                outline: none;
            }
            QHeaderView::section {
                background-color: #101624;
                color: #8B949E;
                font-size: 11px;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #1F293D;
                padding: 8px 12px;
            }
        """)
        self.table_archive.cellClicked.connect(self._on_archive_cell_clicked)
        self.table_archive.cellDoubleClicked.connect(self._on_archive_double_clicked)
        self.table_archive.itemClicked.connect(lambda item: self._on_archive_cell_clicked(item.row(), 0))
        self.table_archive.itemSelectionChanged.connect(self._on_archive_selected)
        arc_layout.addWidget(self.table_archive, stretch=1)

        # =========================================================================
        # SECTION C: RIGHT UNIVERSAL PAPER INSPECTOR & APA 7 CITATION PANEL
        # =========================================================================
        self.arc_inspector = QFrame()
        self.arc_inspector.setStyleSheet("""
            QFrame#inspectorPanel {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 10px;
            }
        """)
        self.arc_inspector.setObjectName("inspectorPanel")
        ins_layout = QVBoxLayout(self.arc_inspector)
        ins_layout.setContentsMargins(16, 14, 16, 14)
        ins_layout.setSpacing(10)

        # Header Title
        ins_head = QHBoxLayout()
        ins_head.setSpacing(8)
        lbl_ins_icon = QLabel()
        lbl_ins_icon.setPixmap(create_vector_pixmap("research", "#58A6FF", 16))
        lbl_ins_icon.setStyleSheet("border: none; background: transparent;")
        ins_head.addWidget(lbl_ins_icon)

        lbl_ins_title = QLabel("Paper-Inspektor & Zitation")
        lbl_ins_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_ins_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        ins_head.addWidget(lbl_ins_title)
        ins_head.addStretch()

        self.btn_close_inspector = QPushButton("✕ Ausblenden")
        self.btn_close_inspector.setCursor(Qt.PointingHandCursor)
        self.btn_close_inspector.setFixedHeight(24)
        self.btn_close_inspector.setToolTip("Inspektor schließen / ausblenden für maximale Listenbreite")
        self.btn_close_inspector.setStyleSheet("""
            QPushButton {
                background: #162032;
                color: #8B949E;
                border: 1px solid #23314B;
                border-radius: 4px;
                padding: 1px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #202D45;
                color: #F0F6FC;
                border-color: #58A6FF;
            }
        """)
        self.btn_close_inspector.clicked.connect(self._toggle_inspector)
        ins_head.addWidget(self.btn_close_inspector)

        ins_layout.addLayout(ins_head)

        # Badges row: Category, Citations, Access, Archive Status
        self.ins_badge_row = QHBoxLayout()
        self.ins_badge_row.setSpacing(6)

        self.lbl_selected_status = QLabel("🌐 Online")
        self.lbl_selected_status.setStyleSheet("background: #141E33; color: #58A6FF; border: 1px solid #1F6FEB; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: bold;")
        self.lbl_selected_status.setVisible(False)
        self.ins_badge_row.addWidget(self.lbl_selected_status)

        self.lbl_selected_category = QLabel("")
        self.lbl_selected_category.setStyleSheet("background: #141E33; color: #79B8FF; border: 1px solid #23375C; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: 600;")
        self.lbl_selected_category.setVisible(False)
        self.ins_badge_row.addWidget(self.lbl_selected_category)

        self.lbl_selected_cites = QLabel("")
        self.lbl_selected_cites.setStyleSheet("background: #231738; color: #D2A8FF; border: 1px solid #6E40C9; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: 600;")
        self.lbl_selected_cites.setVisible(False)
        self.ins_badge_row.addWidget(self.lbl_selected_cites)

        self.lbl_selected_oa = QLabel("")
        self.lbl_selected_oa.setStyleSheet("background: #14281E; color: #3FB950; border: 1px solid #238636; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: 600;")
        self.lbl_selected_oa.setVisible(False)
        self.ins_badge_row.addWidget(self.lbl_selected_oa)

        self.ins_badge_row.addStretch()
        ins_layout.addLayout(self.ins_badge_row)

        self.lbl_selected_title = QLabel("Wähle ein Paper aus den Suchergebnissen oder dem Archiv...")
        self.lbl_selected_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_selected_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        self.lbl_selected_title.setWordWrap(True)
        ins_layout.addWidget(self.lbl_selected_title)

        self.lbl_selected_meta = QLabel("")
        self.lbl_selected_meta.setStyleSheet("color: #8B949E; font-size: 11px; border: none; background: transparent;")
        self.lbl_selected_meta.setWordWrap(True)
        ins_layout.addWidget(self.lbl_selected_meta)

        self.lbl_selected_doi = QLabel("")
        self.lbl_selected_doi.setStyleSheet("color: #58A6FF; font-size: 11px; border: none; background: transparent;")
        self.lbl_selected_doi.setOpenExternalLinks(True)
        self.lbl_selected_doi.setVisible(False)
        ins_layout.addWidget(self.lbl_selected_doi)

        # =====================================================================
        # APA 7 CITATION BOX (Instant copy for scientific papers)
        # =====================================================================
        self.apa_box = QFrame()
        self.apa_box.setStyleSheet("""
            QFrame#apaBoxFrame {
                background-color: #0A0F1A;
                border: 1px solid #1F293D;
                border-left: 3px solid #8957E5;
                border-radius: 8px;
            }
        """)
        self.apa_box.setObjectName("apaBoxFrame")
        apa_box_layout = QVBoxLayout(self.apa_box)
        apa_box_layout.setContentsMargins(10, 8, 10, 8)
        apa_box_layout.setSpacing(6)

        apa_header_row = QHBoxLayout()
        apa_header_row.setSpacing(6)

        lbl_apa_h = QLabel("📋 APA 7. Edition Zitation (Zitierfertig):")
        lbl_apa_h.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_apa_h.setStyleSheet("color: #D2A8FF; border: none; background: transparent;")
        apa_header_row.addWidget(lbl_apa_h)

        apa_header_row.addStretch()

        self.btn_copy_apa_ins = QPushButton("  APA 7 kopieren")
        self.btn_copy_apa_ins.setIcon(create_vector_icon("copy", "#FFFFFF", 12))
        self.btn_copy_apa_ins.setIconSize(QSize(12, 12))
        self.btn_copy_apa_ins.setCursor(Qt.PointingHandCursor)
        self.btn_copy_apa_ins.setStyleSheet("""
            QPushButton {
                background: #8957E5;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 5px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #A371F7;
            }
        """)
        self.btn_copy_apa_ins.clicked.connect(self._copy_ins_apa7)
        apa_header_row.addWidget(self.btn_copy_apa_ins)
        apa_box_layout.addLayout(apa_header_row)

        self.lbl_apa_citation = QLabel("Zitationsangabe wird nach Auswahl berechnet...")
        self.lbl_apa_citation.setFont(QFont("Segoe UI", 9))
        self.lbl_apa_citation.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_apa_citation.setStyleSheet("""
            color: #E6EDF3;
            background-color: #070B13;
            border: 1px solid #161F30;
            border-radius: 5px;
            padding: 8px 10px;
            line-height: 1.45;
        """)
        self.lbl_apa_citation.setWordWrap(True)
        apa_box_layout.addWidget(self.lbl_apa_citation)

        ins_layout.addWidget(self.apa_box)

        # Abstract Header with DE / EN Switcher
        abs_h_row = QHBoxLayout()
        abs_h_row.setSpacing(6)
        lbl_abs_title = QLabel("Wissenschaftlicher Abstract:")
        lbl_abs_title.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        abs_h_row.addWidget(lbl_abs_title)
        abs_h_row.addStretch()

        self.btn_ins_de = QPushButton("🇩🇪 Deutsch")
        self.btn_ins_de.setCursor(Qt.PointingHandCursor)
        self.btn_ins_de.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
        self.btn_ins_de.clicked.connect(self._show_ins_de_abstract)
        abs_h_row.addWidget(self.btn_ins_de)

        self.btn_ins_en = QPushButton("🇬🇧 Original")
        self.btn_ins_en.setCursor(Qt.PointingHandCursor)
        self.btn_ins_en.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
        self.btn_ins_en.clicked.connect(self._show_ins_en_abstract)
        abs_h_row.addWidget(self.btn_ins_en)
        ins_layout.addLayout(abs_h_row)

        # Scrollable Abstract Box
        abs_scroll = QScrollArea()
        abs_scroll.setWidgetResizable(True)
        abs_scroll.setStyleSheet("QScrollArea { background-color: #0A0E17; border: 1px solid #1F293D; border-radius: 6px; }")

        abs_content = QWidget()
        abs_content.setStyleSheet("background: transparent;")
        abs_c_layout = QVBoxLayout(abs_content)
        abs_c_layout.setContentsMargins(10, 10, 10, 10)

        self.lbl_selected_abstract = QLabel("")
        self.lbl_selected_abstract.setStyleSheet("color: #C9D1D9; font-size: 12px; line-height: 1.55; border: none; background: transparent;")
        self.lbl_selected_abstract.setWordWrap(True)
        abs_c_layout.addWidget(self.lbl_selected_abstract)
        abs_c_layout.addStretch()

        abs_scroll.setWidget(abs_content)
        ins_layout.addWidget(abs_scroll, stretch=1)

        # Action Buttons in Inspector (Organized in 2 structured tiers)
        ins_action_box = QVBoxLayout()
        ins_action_box.setSpacing(8)

        # Primary tier (Reading, Downloading, Archiving)
        row_primary = QHBoxLayout()
        row_primary.setSpacing(8)

        self.btn_open_pdf = QPushButton("  In Microsoft Edge öffnen")
        self.btn_open_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_open_pdf.setFixedHeight(36)
        self.btn_open_pdf.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)
        self.btn_open_pdf.clicked.connect(self._open_active_in_edge)
        row_primary.addWidget(self.btn_open_pdf, stretch=2)

        self.btn_dl_pdf_ins = QPushButton("  ⚡ PDF herunterladen")
        self.btn_dl_pdf_ins.setIcon(create_vector_icon("download", "#FFFFFF", 14))
        self.btn_dl_pdf_ins.setCursor(Qt.PointingHandCursor)
        self.btn_dl_pdf_ins.setFixedHeight(36)
        self.btn_dl_pdf_ins.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)
        self.btn_dl_pdf_ins.clicked.connect(self._download_and_open_active_pdf)
        row_primary.addWidget(self.btn_dl_pdf_ins, stretch=2)

        self.btn_save_ins = QPushButton("  📌 In Archiv sichern")
        self.btn_save_ins.setIcon(create_vector_icon("bookmark", "#58A6FF", 14))
        self.btn_save_ins.setCursor(Qt.PointingHandCursor)
        self.btn_save_ins.setFixedHeight(36)
        self.btn_save_ins.setStyleSheet("""
            QPushButton {
                background: #141E33;
                border: 1px solid #1F6FEB;
                color: #58A6FF;
                font-weight: 600;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1D2B4A;
                color: #FFFFFF;
            }
        """)
        self.btn_save_ins.clicked.connect(self._save_active_metadata_only)
        row_primary.addWidget(self.btn_save_ins, stretch=1)

        self.btn_del_paper = QPushButton("  Löschen")
        self.btn_del_paper.setIcon(create_vector_icon("trash", "#F85149", 13))
        self.btn_del_paper.setCursor(Qt.PointingHandCursor)
        self.btn_del_paper.setFixedHeight(36)
        self.btn_del_paper.setStyleSheet("""
            QPushButton {
                background: #211215;
                color: #F85149;
                border: 1px solid #4C1D24;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #38161B;
                border-color: #DA3633;
            }
        """)
        self.btn_del_paper.clicked.connect(self._delete_saved_paper)
        self.btn_del_paper.setVisible(False)
        row_primary.addWidget(self.btn_del_paper)

        ins_action_box.addLayout(row_primary)

        # Secondary tier (Deep research tools)
        row_secondary = QHBoxLayout()
        row_secondary.setSpacing(6)

        self.btn_find_similar = QPushButton("  🧠 Ähnliche Arbeiten")
        self.btn_find_similar.setIcon(create_vector_icon("radar", "#D2A8FF", 12))
        self.btn_find_similar.setCursor(Qt.PointingHandCursor)
        self.btn_find_similar.setFixedHeight(30)
        self.btn_find_similar.setToolTip("Entdeckt über den Zitationsgraphen (Semantic Scholar AI) direkt verwandte wissenschaftliche Studien zu diesem Paper")
        self.btn_find_similar.setStyleSheet("""
            QPushButton {
                background: #1C162E;
                border: 1px solid #6E40C9;
                color: #D2A8FF;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #2B1E48;
                border-color: #A371F7;
                color: #FFFFFF;
            }
        """)
        self.btn_find_similar.clicked.connect(self._discover_similar_papers)
        row_secondary.addWidget(self.btn_find_similar)

        self.btn_open_direct = QPushButton("  🔗 Direktlink / DOI")
        self.btn_open_direct.setIcon(create_vector_icon("search", "#C9D1D9", 12))
        self.btn_open_direct.setCursor(Qt.PointingHandCursor)
        self.btn_open_direct.setFixedHeight(30)
        self.btn_open_direct.setStyleSheet("""
            QPushButton {
                background: #121826;
                border: 1px solid #232F48;
                color: #C9D1D9;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1A2438;
                color: #58A6FF;
                border-color: #388BFD;
            }
        """)
        self.btn_open_direct.clicked.connect(self._open_active_direct)
        row_secondary.addWidget(self.btn_open_direct)

        self.btn_ins_uni = QPushButton("  🏛️ FernUni-Proxy")
        self.btn_ins_uni.setIcon(create_vector_icon("institution", "#D29922", 12))
        self.btn_ins_uni.setCursor(Qt.PointingHandCursor)
        self.btn_ins_uni.setFixedHeight(30)
        self.btn_ins_uni.setStyleSheet("""
            QPushButton {
                background: #1C1810;
                border: 1px solid #6E4A03;
                color: #E3B341;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #2E2210;
                border-color: #D29922;
                color: #FFF2C5;
            }
        """)
        self.btn_ins_uni.clicked.connect(self._open_ins_via_proxy)
        row_secondary.addWidget(self.btn_ins_uni)

        self.btn_copy_saved_bib = QPushButton("  📋 BibTeX")
        self.btn_copy_saved_bib.setIcon(create_vector_icon("copy", "#C9D1D9", 12))
        self.btn_copy_saved_bib.setCursor(Qt.PointingHandCursor)
        self.btn_copy_saved_bib.setFixedHeight(30)
        self.btn_copy_saved_bib.setStyleSheet("""
            QPushButton {
                background: #121826;
                border: 1px solid #232F48;
                color: #C9D1D9;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1A2438;
                color: #FFFFFF;
                border-color: #388BFD;
            }
        """)
        self.btn_copy_saved_bib.clicked.connect(self._copy_saved_bibtex)
        row_secondary.addWidget(self.btn_copy_saved_bib)

        ins_action_box.addLayout(row_secondary)
        ins_layout.addLayout(ins_action_box)

        # =========================================================================
        # UNIFIED MAIN SPLITTER: Left Panels (Search/Archive) vs Right Inspector
        # =========================================================================
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setStyleSheet("QSplitter::handle { background-color: #1F293D; width: 2px; }")

        self.left_panel = QWidget()
        left_panel_layout = QVBoxLayout(self.left_panel)
        left_panel_layout.setContentsMargins(0, 0, 6, 0)
        left_panel_layout.setSpacing(0)
        left_panel_layout.addWidget(self.search_container)
        left_panel_layout.addWidget(self.archive_container)

        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.arc_inspector)
        self.main_splitter.setStretchFactor(0, 5)
        self.main_splitter.setStretchFactor(1, 4)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, True)

        main_layout.addWidget(self.main_splitter, stretch=1)

    def _toggle_inspector(self) -> None:
        self.set_inspector_visible(not self.arc_inspector.isVisible())

    def set_inspector_visible(self, visible: bool) -> None:
        self._inspector_visible = visible
        self.arc_inspector.setVisible(visible)
        if hasattr(self, "btn_toggle_inspector"):
            if visible:
                self.btn_toggle_inspector.setText("  📖 Inspektor ausblenden")
                self.btn_toggle_inspector.setIcon(create_vector_icon("research", "#58A6FF", 14))
                self.btn_toggle_inspector.setStyleSheet("""
                    QPushButton {
                        background-color: #121A28;
                        color: #58A6FF;
                        border: 1px solid #1E2D48;
                        border-radius: 6px;
                        padding: 6px 14px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                    QPushButton:hover {
                        background-color: #1A263D;
                        color: #FFFFFF;
                        border-color: #388BFD;
                    }
                """)
            else:
                self.btn_toggle_inspector.setText("  📖 Inspektor einblenden")
                self.btn_toggle_inspector.setIcon(create_vector_icon("research", "#C9D1D9", 14))
                self.btn_toggle_inspector.setStyleSheet("""
                    QPushButton {
                        background-color: #162032;
                        color: #C9D1D9;
                        border: 1px solid #2B3D5E;
                        border-radius: 6px;
                        padding: 6px 14px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                    QPushButton:hover {
                        background-color: #1F2D48;
                        color: #58A6FF;
                        border-color: #388BFD;
                    }
                """)
        if visible and hasattr(self, "main_splitter"):
            sizes = self.main_splitter.sizes()
            if len(sizes) == 2 and sizes[1] < 100:
                total_w = sum(sizes) if sum(sizes) > 400 else 1000
                self.main_splitter.setSizes([int(total_w * 0.58), int(total_w * 0.42)])

    def load_data(self) -> None:
        """Loads saved research papers from database."""
        self._load_archive_table()

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        active_style = """
            QPushButton {
                background-color: #1A263D;
                color: #58A6FF;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 7px 18px;
            }
        """
        inactive_style = """
            QPushButton {
                background-color: transparent;
                color: #8B949E;
                font-size: 12px;
                font-weight: 500;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 7px 18px;
            }
            QPushButton:hover {
                background-color: #121826;
                color: #C9D1D9;
                border-color: #232F48;
            }
        """
        if mode == "search":
            self.btn_tab_search.setStyleSheet(active_style)
            self.btn_tab_search.setIcon(create_vector_icon("research", "#58A6FF", 16))
            self.btn_tab_archive.setStyleSheet(inactive_style)
            self.btn_tab_archive.setIcon(create_vector_icon("library", "#8B949E", 16))
            self.search_container.setVisible(True)
            self.archive_container.setVisible(False)
            if self._active_search_paper:
                self.inspect_paper(self._active_search_paper)
            elif self._raw_search_results:
                self.inspect_paper(self._raw_search_results[0])
        else:
            self.btn_tab_archive.setStyleSheet(active_style)
            self.btn_tab_archive.setIcon(create_vector_icon("library", "#58A6FF", 16))
            self.btn_tab_search.setStyleSheet(inactive_style)
            self.btn_tab_search.setIcon(create_vector_icon("research", "#8B949E", 16))
            self.search_container.setVisible(False)
            self.archive_container.setVisible(True)
            self._load_archive_table()

    def _open_institution_dialog(self) -> None:
        dlg = InstitutionDialog(self)
        if dlg.exec():
            cfg = get_institution_settings()
            self.lbl_inst_title.setText(f"Zugang: {cfg.get('institution_name')}")

    def _search_topic(self, topic_query: str) -> None:
        self.ent_search.setText(topic_query)
        self._start_search()

    def _search_faculty(self, faculty_name: str, query_terms: str) -> None:
        """Triggers a targeted academic literature search for a specific faculty."""
        self.ent_search.setText(query_terms)
        self._start_search()

    def _seed_curated_papers(self) -> None:
        """Seeds or refreshes landmark papers for all 15 academic faculties."""
        count = seed_all_faculty_papers(force=False)
        self._load_archive_table()
        if hasattr(self.parent(), "update_sidebar_stats"):
            self.parent().update_sidebar_stats()
        QMessageBox.information(
            self,
            "Meilenstein-Paper erfasst",
            f"Erfolgreich {count} neue wissenschaftliche Meilenstein-Paper für alle 15 Fachbereiche in dein lokales Archiv aufgenommen!" if count > 0 else "Alle Meilenstein-Paper für alle 15 Fachbereiche sind bereits vollständig im Archiv erfasst."
        )

    def _build_paper_of_the_day_card(self) -> QFrame:
        """Constructs an interactive daily highlight card for a landmark scientific paper."""
        card = QFrame()
        card.setObjectName("paperOfTheDayCard")
        card.setStyleSheet("""
            QFrame#paperOfTheDayCard {
                background: #0D1424;
                border: 1px solid #1E2B42;
                border-left: 3px solid #3B82F6;
                border-radius: 8px;
                padding: 10px 14px;
            }
            QFrame#paperOfTheDayCard:hover {
                border-color: #2D3E60;
                border-left: 3px solid #60A5FA;
            }
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(12, 10, 12, 10)
        c_lay.setSpacing(6)

        # --- ROW 1: Clean Header Navigation & Stream Controls ---
        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        # Section Brand Tag
        self.lbl_pdt_badge_day = QLabel("✨ IMPULS DES TAGES")
        self.lbl_pdt_badge_day.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_pdt_badge_day.setStyleSheet("""
            background: #142036;
            color: #60A5FA;
            border: 1px solid #1E3358;
            border-radius: 5px;
            padding: 3px 8px;
            letter-spacing: 0.5px;
        """)
        hdr.addWidget(self.lbl_pdt_badge_day)

        # Segmented Stream Switcher (Single unified pill bar)
        self.pdt_active_mode = "german"
        seg_frame = QFrame()
        seg_frame.setObjectName("pdtSegFrame")
        seg_frame.setStyleSheet("""
            QFrame#pdtSegFrame {
                background: #090E18;
                border: 1px solid #182336;
                border-radius: 6px;
            }
        """)
        seg_lay = QHBoxLayout(seg_frame)
        seg_lay.setContentsMargins(2, 2, 2, 2)
        seg_lay.setSpacing(2)

        pdt_btn_style = """
            QPushButton {
                background: transparent;
                color: #8B949E;
                border: none;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                color: #F0F6FC;
                background: #141C2B;
            }
        """
        self.btn_pdt_de = QPushButton("🇩🇪 Deutsch")
        self.btn_pdt_de.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_de.setFixedHeight(24)
        self.btn_pdt_de.setStyleSheet(pdt_btn_style)
        self.btn_pdt_de.clicked.connect(lambda: self._set_pdt_mode("german"))
        seg_lay.addWidget(self.btn_pdt_de)

        self.btn_pdt_int = QPushButton("🇬🇧 International")
        self.btn_pdt_int.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_int.setFixedHeight(24)
        self.btn_pdt_int.setStyleSheet(pdt_btn_style)
        self.btn_pdt_int.clicked.connect(lambda: self._set_pdt_mode("international"))
        seg_lay.addWidget(self.btn_pdt_int)

        self.btn_pdt_edu = QPushButton("🎓 Bildung")
        self.btn_pdt_edu.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_edu.setFixedHeight(24)
        self.btn_pdt_edu.setStyleSheet(pdt_btn_style)
        self.btn_pdt_edu.clicked.connect(lambda: self._set_pdt_mode("education"))
        seg_lay.addWidget(self.btn_pdt_edu)

        hdr.addWidget(seg_frame)
        hdr.addStretch()

        # Access Status Badge (Open Access vs Paywall)
        self.lbl_pdt_access = QLabel("🟢 Open Access")
        self.lbl_pdt_access.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_pdt_access.setStyleSheet("""
            background: rgba(35, 134, 54, 0.2);
            color: #3FB950;
            border: 1px solid #238636;
            border-radius: 5px;
            padding: 3px 8px;
        """)
        hdr.addWidget(self.lbl_pdt_access)

        # Refresh action button
        self.btn_pdt_refresh = QPushButton("🔄 Neuer Impuls")
        self.btn_pdt_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_refresh.setToolTip("Anderen Vorschlag aus diesem Bereich anzeigen")
        self.btn_pdt_refresh.setFixedHeight(26)
        self.btn_pdt_refresh.setStyleSheet("""
            QPushButton {
                background: #101726;
                color: #8B949E;
                border: 1px solid #1C273C;
                border-radius: 5px;
                padding: 2px 9px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #F0F6FC;
                border-color: #388BFD;
                background: #172238;
            }
        """)
        self.btn_pdt_refresh.clicked.connect(self._rotate_paper_of_the_day)
        hdr.addWidget(self.btn_pdt_refresh)

        # Toggle Collapse/Expand Button
        self.btn_pdt_toggle = QPushButton("▲ Einklappen")
        self.btn_pdt_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_toggle.setFixedHeight(26)
        self.btn_pdt_toggle.setStyleSheet("""
            QPushButton {
                background: #162035;
                color: #58A6FF;
                border: 1px solid #283C60;
                border-radius: 5px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1F3052;
                color: #FFFFFF;
                border-color: #58A6FF;
            }
        """)
        self.btn_pdt_toggle.clicked.connect(self._toggle_pdt_collapse)
        hdr.addWidget(self.btn_pdt_toggle)

        c_lay.addLayout(hdr)

        # Collapsible Body Container (Wraps Metadata, Title, Description, and Actions)
        self.pdt_body = QWidget()
        self.pdt_body.setStyleSheet("background: transparent; border: none;")
        body_lay = QVBoxLayout(self.pdt_body)
        body_lay.setContentsMargins(0, 4, 0, 0)
        body_lay.setSpacing(6)

        # --- ROW 2: Metadata Breadcrumbs (Faculty, Impact, Date, Database) ---
        self.lbl_pdt_meta_line = QLabel()
        self.lbl_pdt_meta_line.setFont(QFont("Segoe UI", 8))
        self.lbl_pdt_meta_line.setStyleSheet("color: #7D8590; border: none; margin-top: 2px;")
        body_lay.addWidget(self.lbl_pdt_meta_line)

        # --- ROW 3: Title ---
        self.lbl_pdt_title = QLabel()
        self.lbl_pdt_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_pdt_title.setStyleSheet("""
            QLabel {
                color: #F0F6FC;
                border: none;
                margin-top: 1px;
            }
            QLabel:hover {
                color: #58A6FF;
            }
        """)
        self.lbl_pdt_title.setWordWrap(True)
        self.lbl_pdt_title.setCursor(Qt.PointingHandCursor)
        self.lbl_pdt_title.mousePressEvent = lambda e: self._on_pdt_clicked()
        body_lay.addWidget(self.lbl_pdt_title)

        # --- ROW 4: Authors & Journal / Volume / Pages Citation ---
        self.lbl_pdt_meta = QLabel()
        self.lbl_pdt_meta.setFont(QFont("Segoe UI", 9))
        self.lbl_pdt_meta.setStyleSheet("color: #8B949E; border: none;")
        self.lbl_pdt_meta.setWordWrap(True)
        body_lay.addWidget(self.lbl_pdt_meta)

        # --- ROW 5: Insight & Abstract Card Container ---
        desc_box = QFrame()
        desc_box.setObjectName("pdtDescBox")
        desc_box.setStyleSheet("""
            QFrame#pdtDescBox {
                background: #090E17;
                border: 1px solid #162030;
                border-radius: 6px;
                padding: 6px 10px;
            }
        """)
        desc_lay = QVBoxLayout(desc_box)
        desc_lay.setContentsMargins(6, 4, 6, 4)
        desc_lay.setSpacing(3)

        self.lbl_pdt_desc = QLabel()
        self.lbl_pdt_desc.setTextFormat(Qt.RichText)
        self.lbl_pdt_desc.setFont(QFont("Segoe UI", 9))
        self.lbl_pdt_desc.setStyleSheet("color: #C9D1D9; border: none;")
        self.lbl_pdt_desc.setWordWrap(True)
        desc_lay.addWidget(self.lbl_pdt_desc)
        body_lay.addWidget(desc_box)

        # --- ROW 5.5: Buch-Brücke (Related Library Books) ---
        self.pdt_books_container = QFrame()
        self.pdt_books_container.setObjectName("pdtBooksContainer")
        self.pdt_books_container.setStyleSheet("""
            QFrame#pdtBooksContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0B1324, stop:0.5 #0D172B, stop:1 #0B1324);
                border: 1px solid #1C2D4B;
                border-left: 3px solid #388BFD;
                border-radius: 7px;
            }
        """)
        self.pdt_books_lay = QVBoxLayout(self.pdt_books_container)
        self.pdt_books_lay.setContentsMargins(10, 8, 10, 8)
        self.pdt_books_lay.setSpacing(8)
        self.pdt_books_container.setVisible(False)
        body_lay.addWidget(self.pdt_books_container)

        # --- ROW 6: Unified Action Buttons Row ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        # Primary action 1: Download PDF (OA)
        self.btn_pdt_dl = QPushButton("  ⚡ PDF herunterladen")
        self.btn_pdt_dl.setIcon(create_vector_icon("download", "#FFFFFF", 12))
        self.btn_pdt_dl.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_dl.setFixedHeight(28)
        self.btn_pdt_dl.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #2EA043;
                border-radius: 5px;
                padding: 3px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)
        self.btn_pdt_dl.clicked.connect(self._download_pdt_pdf)
        btn_row.addWidget(self.btn_pdt_dl)

        # Primary action 2: Via Uni-Proxy (Paywall)
        self.btn_pdt_proxy = QPushButton("  🎓 Via Uni-Proxy")
        self.btn_pdt_proxy.setIcon(create_vector_icon("institution", "#FFFFFF", 12))
        self.btn_pdt_proxy.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_proxy.setFixedHeight(28)
        self.btn_pdt_proxy.setToolTip("Öffnet das Paper über den Hochschul-Proxy (z.B. FernUni EZProxy)")
        self.btn_pdt_proxy.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border: 1px solid #388BFD;
                border-radius: 5px;
                padding: 3px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        self.btn_pdt_proxy.clicked.connect(self._open_pdt_via_proxy)
        btn_row.addWidget(self.btn_pdt_proxy)

        # Harmonious Secondary Slate Buttons
        sec_btn_css = """
            QPushButton {
                background: #121A28;
                color: #C9D1D9;
                border: 1px solid #1E2B40;
                border-radius: 5px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #1A263B;
                color: #F0F6FC;
                border-color: #314463;
            }
        """

        btn_open = QPushButton("  📖 In Edge")
        btn_open.setIcon(create_vector_icon("external", "#8B949E", 12))
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setFixedHeight(28)
        btn_open.setStyleSheet(sec_btn_css)
        btn_open.clicked.connect(self._open_pdt_in_edge)
        btn_row.addWidget(btn_open)

        btn_save = QPushButton("  📌 In Archiv")
        btn_save.setIcon(create_vector_icon("library", "#8B949E", 12))
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setFixedHeight(28)
        btn_save.setStyleSheet(sec_btn_css)
        btn_save.clicked.connect(self._save_pdt_to_archive)
        btn_row.addWidget(btn_save)

        self.btn_pdt_apa = QPushButton("  📋 APA 7 kopieren")
        self.btn_pdt_apa.setIcon(create_vector_icon("notes", "#8B949E", 12))
        self.btn_pdt_apa.setCursor(Qt.PointingHandCursor)
        self.btn_pdt_apa.setFixedHeight(28)
        self.btn_pdt_apa.setStyleSheet(sec_btn_css)
        self.btn_pdt_apa.clicked.connect(self._copy_pdt_apa7)
        btn_row.addWidget(self.btn_pdt_apa)

        btn_details = QPushButton("  🔍 Details")
        btn_details.setIcon(create_vector_icon("research", "#8B949E", 12))
        btn_details.setCursor(Qt.PointingHandCursor)
        btn_details.setFixedHeight(28)
        btn_details.setStyleSheet(sec_btn_css)
        btn_details.clicked.connect(self._on_pdt_clicked)
        btn_row.addWidget(btn_details)

        btn_row.addStretch()

        # Clickable DOI link on far right
        self.lbl_pdt_doi = QLabel()
        self.lbl_pdt_doi.setFont(QFont("Segoe UI", 8))
        self.lbl_pdt_doi.setStyleSheet("""
            QLabel {
                color: #58A6FF;
                border: none;
            }
            QLabel:hover {
                color: #79C0FF;
                text-decoration: underline;
            }
        """)
        self.lbl_pdt_doi.setCursor(Qt.PointingHandCursor)
        self.lbl_pdt_doi.mousePressEvent = lambda e: self._copy_pdt_doi()
        btn_row.addWidget(self.lbl_pdt_doi)

        body_lay.addLayout(btn_row)
        c_lay.addWidget(self.pdt_body)

        # Load initial recommendation
        self._load_paper_of_the_day("german")

        return card

    def _toggle_pdt_collapse(self) -> None:
        """Toggles between expanded full view and compact single-line view of Impuls des Tages."""
        self.set_pdt_collapsed(not self._pdt_collapsed)

    def set_pdt_collapsed(self, collapsed: bool) -> None:
        """Sets the collapsed state of the Impuls des Tages card."""
        self._pdt_collapsed = collapsed
        self.pdt_body.setVisible(not collapsed)
        if collapsed:
            self.btn_pdt_toggle.setText("▼ Ausklappen")
            self.btn_pdt_toggle.setStyleSheet("""
                QPushButton {
                    background: #142036;
                    color: #60A5FA;
                    border: 1px solid #1F6FEB;
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #1F3660;
                    color: #FFFFFF;
                }
            """)
            # Compact title snippet in badge when collapsed
            cur_title = (self._current_pdt or {}).get("title", "")
            if cur_title:
                self.lbl_pdt_badge_day.setText(f"✨ IMPULS: {cur_title[:45]}...")
        else:
            self.btn_pdt_toggle.setText("▲ Einklappen")
            self.btn_pdt_toggle.setStyleSheet("""
                QPushButton {
                    background: #162035;
                    color: #58A6FF;
                    border: 1px solid #283C60;
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #1F3052;
                    color: #FFFFFF;
                    border-color: #58A6FF;
                }
            """)
            self.lbl_pdt_badge_day.setText("✨ IMPULS DES TAGES")

    def _set_pdt_mode(self, mode: str) -> None:
        """Switches Paper des Tages stream between German, International, and Education instantly."""
        if self._pdt_collapsed:
            self.set_pdt_collapsed(False)
        self.pdt_active_mode = mode
        
        # Check cache immediately for zero latency
        from ai.daily_paper import _read_daily_cache
        cache = _read_daily_cache()
        cached_entry = cache.get(mode)
        if cached_entry and cached_entry.get("paper"):
            self._render_pdt_highlight(cached_entry["paper"], mode)
        else:
            # Show quick loading indicator and fetch in background thread so UI never freezes
            self.lbl_pdt_title.setText("⏳ Lade Paper des Tages...")
            import threading
            from PySide6.QtCore import QTimer
            def _bg_fetch():
                hl = get_daily_paper_highlight(category_mode=mode, force_refresh=False)
                QTimer.singleShot(0, lambda: self._render_pdt_highlight(hl, mode))
            threading.Thread(target=_bg_fetch, daemon=True).start()

    def _load_paper_of_the_day(self, category_mode: str = "german", force_refresh: bool = False) -> None:
        """Loads and updates the Paper des Tages card data."""
        if force_refresh:
            self.lbl_pdt_title.setText("⏳ Generiere neuen Forschungs-Impuls...")
            import threading
            from PySide6.QtCore import QTimer
            def _bg_fetch():
                hl = get_daily_paper_highlight(category_mode=category_mode, force_refresh=True)
                QTimer.singleShot(0, lambda: self._render_pdt_highlight(hl, category_mode))
            threading.Thread(target=_bg_fetch, daemon=True).start()
        else:
            self._set_pdt_mode(category_mode)

    def _render_pdt_highlight(self, highlight: Dict[str, Any], category_mode: str) -> None:
        """Renders the paper highlight data to UI."""
        try:
            self._current_pdt = highlight
            self.pdt_active_mode = category_mode

            # Update segmented stream buttons appearance
            act_css = "background: #1F6FEB; color: #FFFFFF; font-weight: 600; border: none; border-radius: 4px; padding: 2px 10px; font-size: 11px;"
            inact_css = "background: transparent; color: #8B949E; border: none; border-radius: 4px; padding: 2px 10px; font-size: 11px;"
            self.btn_pdt_de.setStyleSheet(act_css if category_mode == "german" else inact_css)
            self.btn_pdt_int.setStyleSheet(act_css if category_mode == "international" else inact_css)
            self.btn_pdt_edu.setStyleSheet(act_css if category_mode == "education" else inact_css)

            is_oa = bool(highlight.get("is_open_access"))
            if is_oa:
                self.lbl_pdt_access.setText("🟢 Open Access")
                self.lbl_pdt_access.setToolTip("Freier Volltext verfügbar: Kann direkt als PDF heruntergeladen oder in Edge gelesen werden.")
                self.lbl_pdt_access.setStyleSheet("""
                    background: rgba(35, 134, 54, 0.2);
                    color: #3FB950;
                    border: 1px solid #238636;
                    border-radius: 5px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                """)
                self.btn_pdt_dl.setVisible(True)
                self.btn_pdt_proxy.setVisible(False)
            else:
                self.lbl_pdt_access.setText("🔒 Paywall")
                self.lbl_pdt_access.setToolTip("Verlags-Abonnement erforderlich: Volltext über FernUni-Proxy, Universitätsnetzwerk oder Kauf abrufbar.")
                self.lbl_pdt_access.setStyleSheet("""
                    background: rgba(218, 54, 51, 0.2);
                    color: #F85149;
                    border: 1px solid #DA3633;
                    border-radius: 5px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                """)
                self.btn_pdt_dl.setVisible(False)
                self.btn_pdt_proxy.setVisible(True)
            if self._pdt_collapsed:
                t = highlight.get("title", "")
                self.lbl_pdt_badge_day.setText(f"✨ IMPULS: {t[:50]}...")
            else:
                self.lbl_pdt_badge_day.setText(f"✨ IMPULS DES TAGES • {highlight.get('date_str', '')}")

            fac = highlight.get("faculty", "Wissenschaft")
            crit = highlight.get("criterion_badge", "⭐ Peer-Reviewed")
            p_obj = highlight.get("paper") or {}
            src = p_obj.get("source", "Wissenschaftliche Datenbank")
            cits = int(highlight.get("citations") or 0)
            cit_str = f"⭐ {cits:,} Zitate".replace(",", ".") if cits > 0 else ""

            meta_parts = [f"🏛️ {fac}", crit]
            if cit_str:
                meta_parts.append(cit_str)
            meta_parts.append(f"📦 {src}")
            self.lbl_pdt_meta_line.setText("   •   ".join(meta_parts))

            self.lbl_pdt_title.setText(highlight.get("title", ""))

            authors = highlight.get("authors", "")
            year = highlight.get("year", "")
            journal = highlight.get("journal", "")
            volume = highlight.get("volume", "")
            issue = highlight.get("issue", "")
            pages = highlight.get("pages", "")
            j_part = journal
            if volume and issue:
                j_part += f", {volume}({issue})"
            elif volume:
                j_part += f", {volume}"
            if pages:
                j_part += f", {pages}"
            meta_str = f"{authors} ({year})" + (f" • {j_part}" if j_part else "")
            self.lbl_pdt_meta.setText(meta_str)

            reasoning = highlight.get("reasoning", "")
            teaser = highlight.get("teaser", "")
            intext = highlight.get("apa7_intext", "")
            doi_val = highlight.get("doi", "")

            # Inset box content: Clean insight + teaser
            self.lbl_pdt_desc.setText(
                f"<div style='margin-bottom: 3px; font-weight: 600; color: #58A6FF;'>💡 Forschungs-Impuls: "
                f"<span style='font-weight: normal; color: #C9D1D9;'>{reasoning}</span></div>"
                f"<div style='color: #8B949E; line-height: 1.35;'>{teaser}</div>"
            )

            # --- Buch-Brücke: Populate related library books ---
            while self.pdt_books_lay.count():
                child = self.pdt_books_lay.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
                elif child.layout():
                    while child.layout().count():
                        sub = child.layout().takeAt(0)
                        if sub.widget():
                            sub.widget().deleteLater()

            related = highlight.get("related_books") or []
            if related:
                header_row = QHBoxLayout()
                header_row.setContentsMargins(0, 0, 0, 2)
                
                lbl_bridge_title = QLabel("📚 Passend dazu in deiner Bibliothek:")
                lbl_bridge_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
                lbl_bridge_title.setStyleSheet("color: #58A6FF; border: none;")
                header_row.addWidget(lbl_bridge_title)

                lbl_bridge_hint = QLabel("Klicke auf ein Buch für Quick-Look & Inhaltsverzeichnis")
                lbl_bridge_hint.setFont(QFont("Segoe UI", 8))
                lbl_bridge_hint.setStyleSheet("color: #7D8590; border: none; font-style: italic;")
                header_row.addWidget(lbl_bridge_hint)
                header_row.addStretch()
                self.pdt_books_lay.addLayout(header_row)

                books_row = QHBoxLayout()
                books_row.setSpacing(10)
                for b_item in related:
                    b_title = b_item.get("title") or "Unbekannt"
                    b_author = b_item.get("author") or "o.A."
                    
                    # Modern card item using QFrame
                    card_frame = QFrame()
                    card_frame.setCursor(Qt.PointingHandCursor)
                    card_frame.setFixedHeight(50)
                    card_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    card_frame.setToolTip(f"«{b_title}»\nAutor: {b_author}\n\nKlicken für Volltext-Vorschau, Notizen & Inhaltsverzeichnis")
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
                    
                    card_lay = QHBoxLayout(card_frame)
                    card_lay.setContentsMargins(10, 6, 10, 6)
                    card_lay.setSpacing(8)

                    lbl_icon = QLabel("📖")
                    lbl_icon.setStyleSheet("border: none; font-size: 14px; background: transparent;")
                    card_lay.addWidget(lbl_icon)

                    text_col = QVBoxLayout()
                    text_col.setContentsMargins(0, 0, 0, 0)
                    text_col.setSpacing(2)

                    short_t = b_title[:30] + "…" if len(b_title) > 30 else b_title
                    lbl_t = QLabel(short_t)
                    lbl_t.setFont(QFont("Segoe UI", 9, QFont.Medium))
                    lbl_t.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
                    text_col.addWidget(lbl_t)

                    short_a = b_author[:26] + "…" if len(b_author) > 26 else b_author
                    lbl_a = QLabel(short_a)
                    lbl_a.setFont(QFont("Segoe UI", 8))
                    lbl_a.setStyleSheet("color: #8B949E; border: none; background: transparent;")
                    text_col.addWidget(lbl_a)

                    card_lay.addLayout(text_col)
                    card_lay.addStretch()

                    card_frame.mousePressEvent = lambda e, b=b_item: self._open_related_book(b)
                    books_row.addWidget(card_frame, 1)

                self.pdt_books_lay.addLayout(books_row)
                self.pdt_books_container.setVisible(True)
            else:
                self.pdt_books_container.setVisible(False)

            # DOI display on the right
            if doi_val:
                self.lbl_pdt_doi.setText(f"DOI: {doi_val}")
                self.lbl_pdt_doi.setToolTip(f"Klicken, um DOI zu kopieren:\nhttps://doi.org/{doi_val}")
                self.lbl_pdt_doi.setVisible(True)
            else:
                self.lbl_pdt_doi.setVisible(False)

            # Tooltip for APA button
            apa_full = highlight.get("apa7_ref", "")
            self.btn_pdt_apa.setToolTip(f"Scribbr APA 7 Zitation kopieren:\n{apa_full}\n\nVerweis im Text:\n{intext}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.lbl_pdt_title.setText("Impuls wird geladen...")
            self.lbl_pdt_meta.setText("Verbindung zum wissenschaftlichen Repository wird aufgebaut.")
            self.lbl_pdt_desc.setText(f"<div style='color: #8B949E;'>Bitte klicke oben auf <b>🔄 Neuer Impuls</b>, um diesen Bereich zu aktualisieren. ({e})</div>")

    def _open_related_book(self, book: Dict[str, Any]) -> None:
        """Opens Quick-Look dialog for a related library book found by Buch-Brücke."""
        try:
            dlg = QuickLookDialog(book, parent=self)
            dlg.exec()
        except Exception as e:
            self.lbl_search_status.setText(f"Fehler beim Öffnen von {book.get('title', '')}: {e}")


    def _copy_pdt_apa7(self) -> None:
        """Copies the Scribbr APA 7 citation of the current highlight to clipboard."""
        if not self._current_pdt:
            return
        apa = self._current_pdt.get("apa7_ref") or ""
        intext = self._current_pdt.get("apa7_intext") or ""
        if apa:
            clip = QGuiApplication.clipboard()
            if clip:
                clip.setText(apa)
            self.btn_pdt_apa.setText("  ✓ APA 7 kopiert!")
            self.btn_pdt_apa.setStyleSheet("background: #238636; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 3px 10px; font-size: 11px;")
            self.lbl_search_status.setText(f"✓ Scribbr APA 7 Zitation für «{intext}» in die Zwischenablage kopiert!")
            QTimer.singleShot(2200, lambda: self._reset_pdt_apa_button())

    def _reset_pdt_apa_button(self) -> None:
        self.btn_pdt_apa.setText("  📋 APA 7 kopieren")
        self.btn_pdt_apa.setStyleSheet("""
            QPushButton {
                background: #121A28;
                color: #C9D1D9;
                border: 1px solid #1E2B40;
                border-radius: 5px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #1A263B;
                color: #F0F6FC;
                border-color: #314463;
            }
        """)

    def _copy_pdt_doi(self) -> None:
        """Copies DOI URL to clipboard."""
        if not self._current_pdt:
            return
        doi = self._current_pdt.get("doi", "")
        if doi:
            clip = QGuiApplication.clipboard()
            if clip:
                url = f"https://doi.org/{doi}" if not doi.startswith("http") else doi
                clip.setText(url)
            self.lbl_search_status.setText(f"✓ DOI Link «https://doi.org/{doi}» in Zwischenablage kopiert!")

    def _rotate_paper_of_the_day(self) -> None:
        """Fetches fresh, live random paper recommendations for all 3 categories (Deutsch, International, Bildung)."""
        self.lbl_search_status.setText("🔄 Generiere neue Impulse für alle 3 Bereiche (Deutsch, International, Bildung)...")
        self._load_paper_of_the_day(self.pdt_active_mode, force_refresh=True)
        self.lbl_search_status.setText("✓ Frische Impulse für alle 3 Kategorien (Deutsch, International, Bildung) bereitgestellt!")

    def _on_pdt_clicked(self) -> None:
        if self._current_pdt:
            p = self._current_pdt.get("paper") or self._current_pdt
            self.inspect_paper(p)

    def _open_pdt_in_edge(self) -> None:
        if not self._current_pdt:
            return
        p = self._current_pdt.get("paper") or self._current_pdt
        self._open_active_in_edge(p)

    def _download_pdt_pdf(self) -> None:
        """Downloads Paper des Tages PDF directly into local library archive."""
        if not self._current_pdt:
            return
        p = self._current_pdt.get("paper") or self._current_pdt
        self._save_paper_to_archive(p)

    def _open_pdt_via_proxy(self) -> None:
        """Opens Paper des Tages via configured institutional university proxy."""
        if not self._current_pdt:
            return
        p = self._current_pdt.get("paper") or self._current_pdt
        self._open_via_university_proxy(p)

    def _save_pdt_to_archive(self) -> None:
        if not self._current_pdt:
            return
        p = self._current_pdt.get("paper", {})
        pid = save_research_paper(p)
        p["id"] = pid
        self._load_archive_table()
        self.lbl_search_status.setText(f"✓ «{p.get('title', '')[:35]}...» im persönlichen Archiv gesichert!")
        self.inspect_paper(p)

    def _open_google_scholar_search(self) -> None:
        """Opens current query or default keywords directly in Google Scholar via Microsoft Edge."""
        q = self.ent_search.text().strip()
        if not q:
            q = "Wissenschaftliche Arbeiten"
        encoded_q = urllib.parse.quote_plus(q)
        url = f"https://scholar.google.com/scholar?q={encoded_q}"
        self._launch_in_edge(url)

    def _start_search(self) -> None:
        q = self.ent_search.text().strip()
        if not q:
            return

        # Auto-collapse Impuls des Tages so search results take center stage
        if hasattr(self, "set_pdt_collapsed"):
            self.set_pdt_collapsed(True)

        self.btn_search.setEnabled(False)
        self.btn_search.setText("  Recherchiere...")
        self.lbl_search_status.setText(f"Recherchiere in Semantic Scholar, Europe PMC, peDOCS, ERIC, OpenAlex, Crossref & arXiv nach «{q}»...")

        # Clear existing result cards
        self._search_cards = []
        while self.results_layout.count() > 0:
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        def worker():
            try:
                results = search_all_papers(q, max_results=500)
                self._signals.search_finished.emit(results)
            except Exception as e:
                self._signals.search_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_search_filters(self) -> None:
        """Filters and sorts cached search results dynamically based on toolbar selections."""
        if not self._raw_search_results:
            return

        filtered = list(self._raw_search_results)

        # 1. Filter: Open Access Only
        if hasattr(self, "chk_oa_only") and self.chk_oa_only.isChecked():
            filtered = [p for p in filtered if bool(p.get("is_open_access"))]

        # 2. Filter: Publication Year
        if hasattr(self, "combo_search_year"):
            year_choice = self.combo_search_year.currentText()
            if "2024" in year_choice:
                filtered = [p for p in filtered if int(p.get("year") or 0) >= 2024]
            elif "2020" in year_choice:
                filtered = [p for p in filtered if int(p.get("year") or 0) >= 2020]
            elif "2015" in year_choice:
                filtered = [p for p in filtered if int(p.get("year") or 0) >= 2015]

        # 3. Filter: Language (Deutsch vs Englisch)
        if hasattr(self, "combo_search_lang"):
            lang_choice = self.combo_search_lang.currentText()
            if "Deutsch" in lang_choice:
                filtered = [p for p in filtered if self._is_german_paper(p)]
            elif "Englisch" in lang_choice:
                filtered = [p for p in filtered if not self._is_german_paper(p)]

        # 4. Sort Order
        if hasattr(self, "combo_search_sort"):
            sort_choice = self.combo_search_sort.currentText()
            if "Neueste" in sort_choice:
                filtered.sort(key=lambda p: int(p.get("year") or 0), reverse=True)
            elif "Älteste" in sort_choice:
                filtered.sort(key=lambda p: int(p.get("year") or 9999))
            elif "Zitationen" in sort_choice:
                filtered.sort(key=lambda p: int(p.get("citation_count") or 0), reverse=True)

        self._filtered_search_results = filtered
        self._rendered_count = 0
        self._render_batch_size = 35

        # Clear container
        while self.results_layout.count() > 0:
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._search_cards = []
        self._render_next_batch()

        if filtered:
            self.inspect_paper(filtered[0])

    def _is_german_paper(self, paper: Dict[str, Any]) -> bool:
        """Determines if a paper is written in German based on language tags, source, or lexical heuristics."""
        lang = (paper.get("language") or "").lower().strip()
        if lang in ("de", "ger", "deu", "german", "deutsch"):
            return True
        if lang in ("en", "eng", "english"):
            return False

        source = (paper.get("source") or "").lower()
        if "pedocs" in source:
            return True

        text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
        import re
        words = set(re.findall(r'\b[a-zäöüß]{2,}\b', text))
        german_markers = {
            "der", "die", "das", "und", "ist", "sind", "werden", "wurde", "eine", "einer", "einem",
            "eines", "für", "von", "mit", "im", "in", "den", "dem", "zur", "des", "als", "auf",
            "über", "nicht", "auch", "durch", "nach", "bei", "unter", "zwischen", "entwicklung",
            "forschung", "studie", "bildung", "pädagogik", "wissenschaft", "praxis", "analyse", "deutschland"
        }
        return len(words.intersection(german_markers)) >= 2

    def eventFilter(self, watched, event):
        """Translates vertical mouse wheel scrolling into horizontal scrolling for chips navigation."""
        if hasattr(self, "chips_scroll") and watched == self.chips_scroll.viewport():
            if event.type() == QEvent.Wheel:
                delta = event.angleDelta().y() or event.angleDelta().x()
                sb = self.chips_scroll.horizontalScrollBar()
                sb.setValue(sb.value() - delta)
                return True
        return super().eventFilter(watched, event)

    def _render_next_batch(self) -> None:
        """Renders the next batch of paper cards smoothly without UI freeze."""
        if not hasattr(self, "_filtered_search_results") or not self._filtered_search_results:
            return

        # Remove existing load more button or trailing stretch
        if hasattr(self, "btn_load_more") and self.btn_load_more:
            try:
                self.btn_load_more.deleteLater()
            except Exception:
                pass
            self.btn_load_more = None

        while self.results_layout.count() > 0:
            last_item = self.results_layout.itemAt(self.results_layout.count() - 1)
            if last_item and last_item.spacerItem():
                self.results_layout.takeAt(self.results_layout.count() - 1)
            else:
                break

        total = len(self._filtered_search_results)
        start_idx = self._rendered_count
        end_idx = min(start_idx + self._render_batch_size, total)

        for i in range(start_idx, end_idx):
            p = self._filtered_search_results[i]
            card = PaperResultCard(p)
            card.inspect_requested.connect(self.inspect_paper)
            card.apa_requested.connect(self._on_card_apa_copied)
            card.open_edge_requested.connect(self._open_active_in_edge)
            card.save_requested.connect(self._save_paper_to_archive)
            self.results_layout.addWidget(card)
            self._search_cards.append(card)

        self._rendered_count = end_idx

        # If more papers remain, append interactive load more button
        if self._rendered_count < total:
            rem = total - self._rendered_count
            self.btn_load_more = QPushButton(f"📥 Weitere {min(self._render_batch_size, rem)} Paper laden ({self._rendered_count} von {total} angezeigt) ▾")
            self.btn_load_more.setCursor(Qt.PointingHandCursor)
            self.btn_load_more.setFixedHeight(38)
            self.btn_load_more.setStyleSheet("""
                QPushButton {
                    background-color: #16243E;
                    color: #58A6FF;
                    border: 1px dashed #304163;
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: 600;
                    margin: 8px 0;
                }
                QPushButton:hover {
                    background-color: #1F3660;
                    border-color: #58A6FF;
                    color: #FFFFFF;
                }
            """)
            self.btn_load_more.clicked.connect(self._render_next_batch)
            self.results_layout.addWidget(self.btn_load_more)

        self.results_layout.addStretch()
        self.lbl_search_status.setText(f"✓ {total} wissenschaftliche Paper gefunden (zeige {self._rendered_count} von {total}) · Klicke zur Inspektion & Zitation:")

    def _on_search_scroll(self, val: int) -> None:
        """Trigger automatic lazy loading when user scrolls near the bottom."""
        sb = self.scroll_search.verticalScrollBar()
        if sb.maximum() > 0 and val >= sb.maximum() - 180:
            if hasattr(self, "_filtered_search_results") and self._rendered_count < len(self._filtered_search_results):
                self._render_next_batch()

    def _on_search_finished(self, results: List[Dict[str, Any]]) -> None:
        self.btn_search.setEnabled(True)
        self.btn_search.setText("  Paper suchen")

        if not results:
            self.lbl_search_status.setText("Keine Paper gefunden. Versuche allgemeinere englische oder deutsche Fachbegriffe.")
            self._raw_search_results = []
            return

        self._raw_search_results = list(results)
        self._apply_search_filters()
        self.scroll_search.verticalScrollBar().setValue(0)

    def _on_search_error(self, err_msg: str) -> None:
        self.btn_search.setEnabled(True)
        self.btn_search.setText("  Paper suchen")
        self.lbl_search_status.setText(f"Suchfehler: {err_msg[:60]}")

    def inspect_paper(self, paper: Dict[str, Any]) -> None:
        """Instantly inspects a paper in the right panel without requiring it to be saved."""
        if hasattr(self, "arc_inspector") and not self.arc_inspector.isVisible():
            self.set_inspector_visible(True)

        self._active_saved_paper = paper
        if self.mode == "search":
            self._active_search_paper = paper
        p = paper

        # Visually highlight the active card in the search results list
        target_id = p.get("id")
        target_title = (p.get("title") or "").strip().lower()
        for card in getattr(self, "_search_cards", []):
            cid = card.paper.get("id")
            ctitle = (card.paper.get("title") or "").strip().lower()
            is_match = bool((target_id and cid == target_id) or (target_title and ctitle == target_title))
            card.set_selected(is_match)

        # Check if this paper already exists in the local archive
        saved = find_saved_research_paper(p.get("id"), p.get("doi"), p.get("title"))
        if saved:
            self._active_saved_paper = {**p, **saved}
            p = self._active_saved_paper
            is_saved = True
        else:
            is_saved = bool(p.get("local_path") or p.get("created_at") or self.mode == "archive")

        has_pdf = bool(p.get("local_path") and os.path.exists(p.get("local_path")))
        is_oa = bool(p.get("is_open_access") or p.get("pdf_url"))

        # Status Badges in Inspector
        if is_saved:
            self.lbl_selected_status.setText("📁 Im Archiv")
            self.lbl_selected_status.setStyleSheet("background: #14281E; color: #3FB950; border: 1px solid #238636; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: bold;")
            self.lbl_selected_status.setVisible(True)
        else:
            self.lbl_selected_status.setText("🌐 Online")
            self.lbl_selected_status.setStyleSheet("background: #141E33; color: #58A6FF; border: 1px solid #1F6FEB; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: bold;")
            self.lbl_selected_status.setVisible(True)

        cat = p.get("category") or ""
        if cat:
            self.lbl_selected_category.setText(f"🏷️ {cat}")
            self.lbl_selected_category.setStyleSheet("background: #141E33; color: #79B8FF; border: 1px solid #23375C; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: 600;")
            self.lbl_selected_category.setVisible(True)
        else:
            self.lbl_selected_category.setVisible(False)

        cites = p.get("citation_count", 0)
        if cites and cites > 0:
            self.lbl_selected_cites.setText(f"⭐ {cites:,} Zitationen".replace(",", "."))
            self.lbl_selected_cites.setStyleSheet("background: #231738; color: #D2A8FF; border: 1px solid #6E40C9; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: 600;")
            self.lbl_selected_cites.setVisible(True)
        else:
            self.lbl_selected_cites.setVisible(False)

        if has_pdf:
            self.lbl_selected_oa.setText("● Offline-PDF vorhanden")
            self.lbl_selected_oa.setStyleSheet("background: #14281E; color: #3FB950; border: 1px solid #238636; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: bold;")
            self.lbl_selected_oa.setVisible(True)
        elif is_oa:
            self.lbl_selected_oa.setText("🟢 Open Access (Freier Download)")
            self.lbl_selected_oa.setStyleSheet("background: rgba(35, 134, 54, 0.22); color: #3FB950; border: 1px solid #238636; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: bold;")
            self.lbl_selected_oa.setVisible(True)
        else:
            self.lbl_selected_oa.setText("🔒 Verlags-Paywall (Uni-Login)")
            self.lbl_selected_oa.setStyleSheet("background: rgba(218, 54, 51, 0.2); color: #F85149; border: 1px solid #DA3633; border-radius: 10px; padding: 2px 10px; font-size: 10px; font-weight: bold;")
            self.lbl_selected_oa.setVisible(True)

        # Primary Action Buttons: Clear, non-redundant hierarchy
        if has_pdf:
            # 1. Local PDF is saved on disk: Clean primary read button + delete option
            self.btn_open_pdf.setText("  📖 Lokale PDF öffnen (Edge)")
            self.btn_open_pdf.setIcon(create_vector_icon("book", "#FFFFFF", 15))
            self.btn_open_pdf.setStyleSheet("""
                QPushButton {
                    background: #238636;
                    color: #FFFFFF;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 0 16px;
                    font-size: 12px;
                }
                QPushButton:hover { background: #2EA043; }
            """)
            self.btn_open_pdf.setVisible(True)
            self.btn_dl_pdf_ins.setVisible(False)
            self.btn_save_ins.setVisible(False)
            self.btn_del_paper.setVisible(True)

        elif is_saved:
            # 2. Saved in archive as metadata/bookmark: Download button + Edge button + delete
            if is_oa:
                self.btn_dl_pdf_ins.setText("  ⚡ PDF herunterladen")
                self.btn_dl_pdf_ins.setIcon(create_vector_icon("download", "#FFFFFF", 14))
                self.btn_dl_pdf_ins.setStyleSheet("""
                    QPushButton {
                        background: #238636;
                        color: #FFFFFF;
                        font-weight: bold;
                        border: none;
                        border-radius: 6px;
                        padding: 0 14px;
                        font-size: 11px;
                    }
                    QPushButton:hover { background: #2EA043; }
                """)
            else:
                self.btn_dl_pdf_ins.setText("  🎓 Via Uni-Proxy abrufen")
                self.btn_dl_pdf_ins.setIcon(create_vector_icon("institution", "#FFFFFF", 14))
                self.btn_dl_pdf_ins.setStyleSheet("""
                    QPushButton {
                        background: #1F6FEB;
                        color: #FFFFFF;
                        font-weight: bold;
                        border: none;
                        border-radius: 6px;
                        padding: 0 14px;
                        font-size: 11px;
                    }
                    QPushButton:hover { background: #388BFD; }
                """)
            self.btn_dl_pdf_ins.setVisible(True)

            self.btn_open_pdf.setText("  🌐 In Edge öffnen")
            self.btn_open_pdf.setIcon(create_vector_icon("desk", "#58A6FF", 14))
            self.btn_open_pdf.setStyleSheet("""
                QPushButton {
                    background: #141E33;
                    border: 1px solid #1F6FEB;
                    color: #58A6FF;
                    font-weight: 600;
                    border-radius: 6px;
                    padding: 0 14px;
                    font-size: 11px;
                }
                QPushButton:hover { background: #1D2B4A; color: #FFFFFF; }
            """)
            self.btn_open_pdf.setVisible(True)

            self.btn_save_ins.setVisible(False)
            self.btn_del_paper.setVisible(True)

        else:
            # 3. Online search result: Download & Save + Save Metadata + Edge
            if is_oa:
                self.btn_dl_pdf_ins.setText("  ⚡ PDF herunterladen & sichern")
                self.btn_dl_pdf_ins.setIcon(create_vector_icon("download", "#FFFFFF", 14))
                self.btn_dl_pdf_ins.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
                        color: #FFFFFF;
                        font-weight: bold;
                        border: none;
                        border-radius: 6px;
                        padding: 0 14px;
                        font-size: 11px;
                    }
                    QPushButton:hover { background: #2EA043; }
                """)
            else:
                self.btn_dl_pdf_ins.setText("  🎓 Via Uni-Proxy abrufen")
                self.btn_dl_pdf_ins.setIcon(create_vector_icon("institution", "#FFFFFF", 14))
                self.btn_dl_pdf_ins.setStyleSheet("""
                    QPushButton {
                        background: #1F6FEB;
                        color: #FFFFFF;
                        font-weight: bold;
                        border: none;
                        border-radius: 6px;
                        padding: 0 14px;
                        font-size: 11px;
                    }
                    QPushButton:hover { background: #388BFD; }
                """)
            self.btn_dl_pdf_ins.setVisible(True)

            self.btn_save_ins.setText("  📌 Nur Metadaten sichern")
            self.btn_save_ins.setIcon(create_vector_icon("bookmark", "#58A6FF", 14))
            self.btn_save_ins.setStyleSheet("""
                QPushButton {
                    background: #141E33;
                    border: 1px solid #1F6FEB;
                    color: #58A6FF;
                    font-weight: 600;
                    border-radius: 6px;
                    padding: 0 14px;
                    font-size: 11px;
                }
                QPushButton:hover { background: #1D2B4A; color: #FFFFFF; }
            """)
            self.btn_save_ins.setVisible(True)

            self.btn_open_pdf.setText("  🌐 In Edge öffnen")
            self.btn_open_pdf.setIcon(create_vector_icon("desk", "#C9D1D9", 14))
            self.btn_open_pdf.setStyleSheet("""
                QPushButton {
                    background: #141B29;
                    border: 1px solid #232F48;
                    color: #C9D1D9;
                    border-radius: 6px;
                    padding: 0 12px;
                    font-size: 11px;
                }
                QPushButton:hover { background: #1C273C; color: #FFFFFF; }
            """)
            self.btn_open_pdf.setVisible(True)
            self.btn_del_paper.setVisible(False)

        self.lbl_selected_title.setText(p.get("title", ""))
        self.lbl_selected_meta.setText(f"von {p.get('authors', 'Unbekannt')} ({p.get('year', '')}) · {p.get('journal', '')}")

        doi = p.get("doi", "").strip()
        if doi:
            clean_doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").replace("doi.org/", "").strip()
            self.lbl_selected_doi.setText(f"DOI: https://doi.org/{clean_doi}")
            self.lbl_selected_doi.setVisible(True)
        else:
            self.lbl_selected_doi.setVisible(False)

        # Generate APA 7th Edition Citation
        apa_citation = generate_paper_apa7(p)
        self.lbl_apa_citation.setText(apa_citation)

        # Display abstract immediately without freezing on spinner
        self._ins_translated_de = None
        raw_abs = clean_abstract_text(p.get("abstract") or "", p.get("title"), p.get("year"))
        if not raw_abs:
            raw_abs = "Kein Abstract erfasst. Volltext oder Publikation kann direkt in Microsoft Edge eingesehen werden."

        # Check if text is a placeholder
        is_placeholder = "kein" in raw_abs.lower() and "abstract" in raw_abs.lower()
        if is_placeholder:
            self.btn_ins_de.setVisible(False)
            self.btn_ins_en.setVisible(False)
            self.lbl_selected_abstract.setText(raw_abs)
        else:
            self.btn_ins_de.setVisible(True)
            self.btn_ins_en.setVisible(True)
            import re
            words = set(re.findall(r'\b[a-zäöüß]{2,}\b', raw_abs.lower()))
            german_words = {"der", "die", "das", "und", "ist", "sind", "werden", "wurde", "eine", "einer", "einem", "eines", "für", "von", "mit", "im", "in", "den", "dem", "zur", "des", "als", "auf"}
            is_german = len(words.intersection(german_words)) >= 2
            if is_german:
                self.btn_ins_de.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
                self.btn_ins_en.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
                self._ins_translated_de = raw_abs
                self.lbl_selected_abstract.setText(raw_abs)
            else:
                self.btn_ins_en.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
                self.btn_ins_de.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
                self.lbl_selected_abstract.setText(raw_abs)

        self.btn_ins_uni.setEnabled(True)

    def _copy_ins_apa7(self) -> None:
        """Copies the formatted APA 7th Edition citation to clipboard."""
        if not self._active_saved_paper:
            return
        citation = self.lbl_apa_citation.text().strip()
        if not citation:
            citation = generate_paper_apa7(self._active_saved_paper)
        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText(citation)
        self.btn_copy_apa_ins.setText("  ✓ APA 7 kopiert!")
        self.btn_copy_apa_ins.setStyleSheet("background: #238636; color: #FFFFFF; font-weight: bold; border: none; border-radius: 5px; padding: 4px 12px; font-size: 11px;")
        self.lbl_search_status.setText("✓ APA 7 Zitation erfolgreich in die Zwischenablage kopiert!")
        QTimer.singleShot(2200, self._reset_ins_apa_button)

    def _reset_ins_apa_button(self) -> None:
        self.btn_copy_apa_ins.setText("  APA 7 kopieren")
        self.btn_copy_apa_ins.setStyleSheet("""
            QPushButton {
                background: #8957E5;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 5px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #A371F7;
            }
        """)

    def _on_card_apa_copied(self, paper: Dict[str, Any]) -> None:
        title = paper.get("title", "")[:35]
        self.lbl_search_status.setText(f"✓ APA 7 Zitation für «{title}...» in Zwischenablage kopiert!")

    def _save_active_metadata_only(self) -> None:
        """Immediately saves the paper metadata into research_papers DB without downloading PDF."""
        if not self._active_saved_paper:
            return
        p = self._active_saved_paper
        pid = save_research_paper(p)
        p["id"] = pid
        title = p.get("title", "")
        self.lbl_search_status.setText(f"✓ «{title[:45]}...» erfolgreich im Archiv gesichert!")
        self._load_archive_table()
        self.inspect_paper(p)

    def _download_and_open_active_pdf(self) -> None:
        """Downloads the PDF in background or routes paywalled paper to institutional proxy."""
        if not self._active_saved_paper:
            return
        p = self._active_saved_paper
        loc = p.get("local_path")
        if loc and os.path.exists(loc):
            try:
                open_pdf_in_edge(loc)
            except Exception:
                try:
                    os.startfile(loc)
                except Exception:
                    pass
            return

        is_oa = bool(p.get("is_open_access") or p.get("pdf_url"))
        if not is_oa:
            self.lbl_search_status.setText("🔒 Artikel liegt im Verlags-Abo – öffne Volltext über Uni-Proxy / EZProxy...")
            self._open_via_university_proxy(p)
            return

        self._save_paper_to_archive(p)

    def _save_paper_to_archive(self, paper: Dict[str, Any]) -> None:
        """Downloads the PDF in background, saves paper to archive, and opens file upon completion."""
        self.lbl_search_status.setText(f"Lade Paper «{paper.get('title', '')[:30]}...» herunter...")

        def worker():
            local_path = download_paper_pdf(paper)
            if local_path and os.path.exists(local_path):
                paper["local_path"] = local_path
                pid = save_research_paper(paper)
                self._signals.download_finished.emit(pid, local_path)
            else:
                # Save metadata even if publisher requires browser proxy login
                save_research_paper(paper)
                self._signals.download_finished.emit(paper.get("id", ""), "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_finished(self, paper_id: str, local_path: str) -> None:
        if local_path and os.path.exists(local_path):
            filename = os.path.basename(local_path)
            self.lbl_search_status.setText(f"✓ PDF «{filename[:35]}...» erfolgreich heruntergeladen & im Archiv gesichert!")
            try:
                open_pdf_in_edge(local_path)
            except Exception:
                try:
                    os.startfile(local_path)
                except Exception:
                    pass
        else:
            self.lbl_search_status.setText("⚠️ Kein direkter PDF-Download verfügbar (Verlags-Login/Paywall nötig). Paper wird in Microsoft Edge geöffnet...")
            if self._active_saved_paper:
                self._open_active_in_edge()
        self._load_archive_table()
        # If currently active paper in inspector was the saved one, refresh inspector
        if self._active_saved_paper:
            saved = find_saved_research_paper(paper_id, self._active_saved_paper.get("doi"), self._active_saved_paper.get("title"))
            if saved:
                self.inspect_paper(saved)

    def _on_download_error(self, err: str) -> None:
        self.lbl_search_status.setText(f"Download-Hinweis: {err}")

    def _open_direct_paper(self, paper: Dict[str, Any]) -> None:
        """Opens the paper directly via DOI or web URL without university proxy."""
        doi = paper.get("doi", "").strip()
        if doi:
            clean = doi.replace("https://doi.org/", "").strip()
            target_url = f"https://doi.org/{clean}"
        elif paper.get("pdf_url"):
            target_url = paper.get("pdf_url")
        else:
            import urllib.parse
            q = urllib.parse.quote(paper.get("title", ""))
            target_url = f"https://scholar.google.com/scholar?q={q}"
        import webbrowser
        webbrowser.open(target_url)

    def _open_active_direct(self) -> None:
        if self._active_saved_paper:
            self._open_direct_paper(self._active_saved_paper)

    def _open_via_university_proxy(self, paper: Dict[str, Any]) -> None:
        cfg = get_institution_settings()
        prefix = cfg.get("ezproxy_prefix", "https://login.ub-proxy.fernuni-hagen.de/login?url=")
        target_url = build_institution_url(paper, prefix)
        import webbrowser
        webbrowser.open(target_url)

    def _copy_paper_bibtex(self, paper: Dict[str, Any]) -> None:
        bib = generate_paper_bibtex(paper)
        clip = QGuiApplication.clipboard()
        if clip:
            clip.setText(bib)
            self.lbl_search_status.setText("✓ BibTeX-Eintrag in die Zwischenablage kopiert!")

    def _discover_similar_papers(self) -> None:
        """Finds related papers via Semantic Scholar citation graph recommendations."""
        if not self._active_saved_paper:
            return
        p = self._active_saved_paper
        title = (p.get("title") or "").strip()
        if not title:
            return

        # Switch to search view
        self._set_mode("search")
        self.ent_search.setText(f"Ähnlich zu: {title[:50]}...")
        self.btn_search.setEnabled(False)
        self.btn_search.setText("  Recherchiere...")
        self.lbl_search_status.setText(f"Recherchiere im Zitationsgraphen nach thematisch verwandten Studien zu «{title[:45]}...»...")

        # Clear existing result cards
        self._search_cards = []
        while self.results_layout.count() > 0:
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        def worker():
            try:
                results = find_similar_papers(p, limit=35)
                self._signals.search_finished.emit(results)
            except Exception as e:
                self._signals.search_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _load_archive_table(self) -> None:
        selected_fac = self.combo_fac_filter.currentText() if hasattr(self, "combo_fac_filter") else "Alle Fachbereiche"
        if selected_fac == "Alle Fachbereiche":
            all_papers = get_all_research_papers()
        else:
            all_papers = get_all_research_papers(category=selected_fac)

        # 1. Filter by search query
        filter_txt = self.ent_arc_filter.text().strip().lower() if hasattr(self, "ent_arc_filter") else ""
        if filter_txt:
            all_papers = [
                p for p in all_papers
                if filter_txt in (p.get("title") or "").lower()
                or filter_txt in (p.get("authors") or "").lower()
                or filter_txt in (p.get("category") or "").lower()
            ]

        # 2. Filter by local PDF availability (Offline vs Online)
        pdf_choice = self.combo_pdf_filter.currentText() if hasattr(self, "combo_pdf_filter") else "Alle Dokumente"
        if "Offline-PDFs" in pdf_choice:
            all_papers = [p for p in all_papers if bool(p.get("local_path") and os.path.exists(p.get("local_path")))]
        elif "Online-Verlinkte" in pdf_choice:
            all_papers = [p for p in all_papers if not bool(p.get("local_path") and os.path.exists(p.get("local_path")))]

        # 3. Apply sorting
        sort_mode = self.combo_arc_sort.currentText() if hasattr(self, "combo_arc_sort") else "Neueste zuerst (Jahr ↓)"
        if "Neueste" in sort_mode:
            all_papers.sort(key=lambda p: int(p.get("year") or 0), reverse=True)
        elif "Älteste" in sort_mode:
            all_papers.sort(key=lambda p: int(p.get("year") or 9999))
        elif "Zitationen" in sort_mode:
            all_papers.sort(key=lambda p: int(p.get("citation_count") or 0), reverse=True)
        elif "Titel" in sort_mode:
            all_papers.sort(key=lambda p: (p.get("title") or "").lower())

        self._saved_papers = all_papers

        # Update title count
        total_all = len(get_all_research_papers())
        offline_count = sum(1 for p in all_papers if p.get("local_path") and os.path.exists(p.get("local_path")))
        if hasattr(self, "lbl_arc_t"):
            self.lbl_arc_t.setText(f"Gesicherte Artikel ({len(self._saved_papers)} von {total_all} · {offline_count} Offline-PDFs)")

        self.table_archive.blockSignals(True)
        self.table_archive.setRowCount(len(self._saved_papers))
        for r, p in enumerate(self._saved_papers):
            self.table_archive.setRowHeight(r, 48)

            title_str = f"{p.get('title', '')}\n{p.get('authors', '')}"
            item_t = QTableWidgetItem(title_str)
            item_t.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_archive.setItem(r, 0, item_t)

            cat_str = p.get("category") or "Interdisziplinär"
            item_c = QTableWidgetItem(cat_str)
            item_c.setFont(QFont("Segoe UI", 8))
            item_c.setForeground(QColor("#58A6FF"))
            item_c.setTextAlignment(Qt.AlignCenter)
            self.table_archive.setItem(r, 1, item_c)

            y_str = f"{p.get('year', '')} · {p.get('journal', '')[:20]}"
            item_y = QTableWidgetItem(y_str)
            item_y.setTextAlignment(Qt.AlignCenter)
            self.table_archive.setItem(r, 2, item_y)

            lp = p.get("local_path")
            has_pdf = False
            if lp and os.path.exists(lp):
                try:
                    with open(lp, "rb") as f_chk:
                        head = f_chk.read(512)
                    if head.startswith(b"%PDF") or b"%PDF" in head:
                        has_pdf = True
                    else:
                        # Non-PDF HTML landing page was accidentally saved in earlier versions: clean it up
                        try:
                            os.remove(lp)
                        except Exception:
                            pass
                        save_research_paper({**p, "local_path": "", "is_downloaded": 0})
                        p["local_path"] = ""
                        p["is_downloaded"] = 0
                except Exception:
                    pass

            stat_str = "● PDF Lokal" if has_pdf else "○ Metadaten"
            item_s = QTableWidgetItem(stat_str)
            item_s.setTextAlignment(Qt.AlignCenter)
            item_s.setForeground(QColor("#3FB950" if has_pdf else "#8B949E"))
            self.table_archive.setItem(r, 3, item_s)
        self.table_archive.blockSignals(False)

        # Automatically select and inspect active row or first item if available
        if len(self._saved_papers) > 0 and self.mode == "archive":
            target_row = 0
            if self._active_saved_paper:
                for idx, p_item in enumerate(self._saved_papers):
                    if p_item.get("id") == self._active_saved_paper.get("id") or p_item.get("title") == self._active_saved_paper.get("title"):
                        target_row = idx
                        break
            self.table_archive.selectRow(target_row)
            self.inspect_paper(self._saved_papers[target_row])

    def _on_archive_cell_clicked(self, row: int, col: int = 0) -> None:
        """Invoked when user clicks directly on any cell in the archive table."""
        if 0 <= row < len(self._saved_papers):
            self.table_archive.selectRow(row)
            self.inspect_paper(self._saved_papers[row])

    def _on_archive_selected(self) -> None:
        """Invoked when selection changes via keyboard arrows or selection model."""
        r = self.table_archive.currentRow()
        if 0 <= r < len(self._saved_papers):
            self.inspect_paper(self._saved_papers[r])

    def _on_archive_double_clicked(self, row: int, col: int = 0) -> None:
        """Opens the double-clicked archived paper directly in Microsoft Edge."""
        if 0 <= row < len(self._saved_papers):
            p = self._saved_papers[row]
            self.inspect_paper(p)
            self._open_active_in_edge(p)

    def _show_ins_de_abstract(self) -> None:
        if not self._active_saved_paper:
            return
        raw = clean_abstract_text(self._active_saved_paper.get("abstract", ""), self._active_saved_paper.get("title"), self._active_saved_paper.get("year"))
        if not raw or ("kein" in raw.lower() and "abstract" in raw.lower()):
            self.lbl_selected_abstract.setText(raw or "Kein Abstract erfasst.")
            return

        import re
        words = set(re.findall(r'\b[a-zäöüß]{2,}\b', raw.lower()))
        german_words = {"der", "die", "das", "und", "ist", "sind", "werden", "wurde", "eine", "einer", "einem", "eines", "für", "von", "mit", "im", "in", "den", "dem", "zur", "des", "als", "auf"}
        if len(words.intersection(german_words)) >= 3:
            # Already German, no web query needed
            self._ins_translated_de = raw
            self.lbl_selected_abstract.setText(raw)
            return

        self.btn_ins_de.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
        self.btn_ins_en.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
        if not getattr(self, "_ins_translated_de", None):
            self.lbl_selected_abstract.setText("⏳ Übersetze Abstract ins Deutsche...")
            import threading
            def worker():
                de_text = translate_abstract_to_german(raw)
                self._ins_translated_de = de_text
                from PySide6.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(self.lbl_selected_abstract, "setText", Qt.QueuedConnection, de_text)
            threading.Thread(target=worker, daemon=True).start()
        else:
            self.lbl_selected_abstract.setText(self._ins_translated_de)

    def _show_ins_en_abstract(self) -> None:
        if not self._active_saved_paper:
            return
        raw = clean_abstract_text(self._active_saved_paper.get("abstract", ""), self._active_saved_paper.get("title"), self._active_saved_paper.get("year"))
        self.btn_ins_en.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-size: 10px; font-weight: bold; border: none; border-radius: 4px; padding: 2px 8px;")
        self.btn_ins_de.setStyleSheet("background: #1A2234; color: #8B949E; font-size: 10px; border: 1px solid #30363D; border-radius: 4px; padding: 2px 8px;")
        self.lbl_selected_abstract.setText(raw)

    def _open_ins_via_proxy(self) -> None:
        if self._active_saved_paper:
            self._open_via_university_proxy(self._active_saved_paper)

    def _launch_in_edge(self, target: str) -> bool:
        """Launches a URL or local file directly in Microsoft Edge."""
        import subprocess, webbrowser, pathlib
        target_str = str(target).strip()
        if not target_str:
            return False

        edge_candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        ]
        edge_exe = None
        for cand in edge_candidates:
            if os.path.isfile(cand):
                edge_exe = cand
                break

        # A) LOCAL FILE (Must be passed directly to msedge.exe, because Edge blocks file:// in protocol handlers)
        if os.path.exists(target_str):
            abs_p = os.path.abspath(target_str)
            if edge_exe:
                try:
                    subprocess.Popen([edge_exe, abs_p])
                    return True
                except Exception:
                    pass
            try:
                os.startfile(abs_p)
                return True
            except Exception:
                return False

        # B) WEB URL (http / https) -> Directly execute msedge.exe first
        if edge_exe:
            try:
                subprocess.Popen([edge_exe, target_str])
                return True
            except Exception:
                pass

        # Fallback 1: Windows CMD start msedge
        try:
            ret = subprocess.run(["cmd", "/c", "start", "", "msedge", target_str], capture_output=True, text=True, check=False)
            if ret.returncode == 0:
                return True
        except Exception:
            pass

        # Fallback 2: Native protocol handler
        try:
            os.startfile(f"microsoft-edge:{target_str}")
            return True
        except Exception:
            pass

        # Fallback 3: Standard default browser
        try:
            webbrowser.open(target_str)
            return True
        except Exception:
            return False

    def _open_active_in_edge(self, paper: Optional[Dict[str, Any]] = None) -> None:
        """Opens the selected paper directly in Microsoft Edge (supports local files, direct PDFs, DOIs and Scholar)."""
        p = paper if isinstance(paper, dict) else self._active_saved_paper
        if not p:
            self.lbl_search_status.setText("ℹ️ Bitte wähle zuerst ein Paper aus der Liste aus, um es in Microsoft Edge zu öffnen.")
            return

        # Ensure UI inspector highlights the active paper
        if paper and isinstance(paper, dict):
            self.inspect_paper(paper)

        # 1. Local saved PDF exists and is valid?
        local_path = p.get("local_path")
        if local_path and os.path.exists(local_path):
            try:
                with open(local_path, "rb") as f_chk:
                    head = f_chk.read(512)
                is_valid = head.startswith(b"%PDF") or b"%PDF" in head
            except Exception:
                is_valid = False

            if is_valid:
                open_pdf_in_edge(local_path)
                self.lbl_search_status.setText(f"✓ Lokales PDF in Microsoft Edge geöffnet: {os.path.basename(local_path)}")
                return
            else:
                try:
                    os.remove(local_path)
                except Exception:
                    pass
                p["local_path"] = ""
                p["is_downloaded"] = 0
                save_research_paper(p)
                self._load_archive_table()
                self.inspect_paper(p)

        # 2. Direct online PDF URL (arXiv, Wiley, Europe PMC, Open Access)
        pdf_url = (p.get("pdf_url") or "").strip()
        if pdf_url and ("pdf" in pdf_url.lower() or "arxiv.org" in pdf_url.lower()):
            self._launch_in_edge(pdf_url)
            self.lbl_search_status.setText("✓ Volltext-PDF in Microsoft Edge geöffnet!")
            return

        # 3. DOI available -> Direct publisher publication in Edge
        doi = (p.get("doi") or "").strip()
        if doi:
            clean_doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").replace("doi.org/", "").strip()
            target_url = f"https://doi.org/{clean_doi}"
            self._launch_in_edge(target_url)
            self.lbl_search_status.setText("✓ Paper-Publikation in Microsoft Edge geöffnet!")
            return

        # 4. Handle.net, landing page, or arbitrary repository link
        url_cand = p.get("url") or p.get("landing_page_url") or pdf_url
        if url_cand:
            self._launch_in_edge(url_cand)
            self.lbl_search_status.setText("✓ Paper-Publikationslink in Microsoft Edge geöffnet!")
            return

        # 5. arXiv ID?
        arxiv_id = (p.get("arxiv_id") or "").strip()
        if arxiv_id:
            self._launch_in_edge(f"https://arxiv.org/abs/{arxiv_id}")
            self.lbl_search_status.setText("✓ arXiv Preprint in Microsoft Edge geöffnet!")
            return

        # 6. Search fallback on Google Scholar
        q_str = urllib.parse.quote(p.get("title", ""))
        self._launch_in_edge(f"https://scholar.google.com/scholar?q={q_str}")
        self.lbl_search_status.setText("✓ Wissenschaftliche Recherche in Edge gestartet!")

    def _open_saved_pdf(self) -> None:
        self._open_active_in_edge()

    def _copy_saved_bibtex(self) -> None:
        if self._active_saved_paper:
            bib = generate_paper_bibtex(self._active_saved_paper)
            clip = QGuiApplication.clipboard()
            if clip:
                clip.setText(bib)
                self.lbl_search_status.setText("✓ BibTeX-Eintrag in die Zwischenablage kopiert!")

    def _clear_inspector(self) -> None:
        self._active_saved_paper = None
        self._ins_translated_de = None
        self.lbl_selected_title.setText("Wähle ein Paper aus den Suchergebnissen oder dem Archiv...")
        self.lbl_selected_meta.setText("")
        self.lbl_selected_doi.setVisible(False)
        self.lbl_apa_citation.setText("")
        self.lbl_selected_abstract.setText("")
        self.lbl_selected_status.setVisible(False)
        self.lbl_selected_category.setVisible(False)
        self.lbl_selected_cites.setVisible(False)
        self.lbl_selected_oa.setVisible(False)
        self.btn_open_pdf.setEnabled(False)
        self.btn_save_ins.setVisible(False)
        self.btn_del_paper.setVisible(False)
        for card in getattr(self, "_search_cards", []):
            card.set_selected(False)

    def _delete_saved_paper(self) -> None:
        if not self._active_saved_paper:
            return

        title = self._active_saved_paper.get("title", "dieses Paper")
        loc = self._active_saved_paper.get("local_path")
        has_file = bool(loc and os.path.exists(loc))
        file_hint = "\n\n(Die lokale PDF-Datei wird ebenfalls von der Festplatte gelöscht.)" if has_file else ""

        ret = QMessageBox.question(
            self,
            "Paper löschen",
            f"Möchtest du das Paper wirklich aus deinem Archiv entfernen?\n\n\"{title[:80]}...\"{file_hint}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        pid = self._active_saved_paper.get("id")
        doi = self._active_saved_paper.get("doi")
        delete_research_paper(pid or "", local_path=loc, title=title, doi=doi)
        self._load_archive_table()
        if len(self._saved_papers) > 0:
            self.table_archive.selectRow(0)
            self.inspect_paper(self._saved_papers[0])
        else:
            self.table_archive.clearSelection()
            self._clear_inspector()
        self.lbl_search_status.setText("✓ Paper und lokale PDF-Datei erfolgreich aus dem Archiv gelöscht.")

    def _open_papers_folder(self) -> None:
        """Opens the papers folder at the books storage location in Windows Explorer."""
        from ai.paper_search import get_papers_dir
        folder = get_papers_dir()
        if os.path.exists(folder):
            try:
                os.startfile(folder)
            except Exception:
                import subprocess
                subprocess.Popen(["explorer", folder])

