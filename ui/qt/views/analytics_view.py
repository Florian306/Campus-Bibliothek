"""Library Analytics & Statistics Dashboard for Campus-Bibliothek.
Renders high-end Cyber-Obsidian metrics, faculty distributions, publication timeline, and reading telemetry.
"""

from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QPainter, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QProgressBar,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.library_db import get_db_connection
from core.cover_manager import FACULTY_COLORS


class FacultyBarWidget(QWidget):
    """Custom bar widget visualizing faculty distribution with vibrant glow colors."""
    def __init__(self, cat_data: List[tuple[str, int, int]], parent=None):
        super().__init__(parent)
        self.cat_data = cat_data  # [(cat_name, book_count, page_count), ...]
        self.total_books = sum(c[1] for c in cat_data) or 1
        self.setFixedHeight(18)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        radius = 5

        # Background track
        painter.setBrush(QBrush(QColor("#101625")))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        # Segmented colored distribution
        cur_x = 0
        for name, count, _ in self.cat_data:
            pct = count / self.total_books
            seg_w = max(2, int(w * pct))
            _, accent_col = FACULTY_COLORS.get(name, ("#161B22", "#58A6FF"))
            painter.setBrush(QBrush(QColor(accent_col)))
            painter.drawRect(cur_x, 0, seg_w, h)
            cur_x += seg_w


class AnalyticsView(QWidget):
    """Interactive Cyber-Obsidian Statistics & Analytics Dashboard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(28, 22, 28, 22)
        root_layout.setSpacing(16)

        # Header Row
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(create_vector_pixmap("research", "#58A6FF", 24))
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("""
            background: #141E33;
            border: 1px solid #283856;
            border-radius: 10px;
        """)
        header_row.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel("Bibliotheks-Statistik & Analyse-Cockpit")
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC;")
        title_box.addWidget(lbl_title)

        lbl_sub = QLabel("Bestands-Kennzahlen, Fachbereichs-Verteilung und Lese-Fortschritt im Überblick")
        lbl_sub.setFont(QFont("Segoe UI", 10))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_box.addWidget(lbl_sub)
        header_row.addLayout(title_box)

        header_row.addStretch()

        btn_refresh = QPushButton("  Aktualisieren")
        btn_refresh.setIcon(create_vector_icon("sync", "#C9D1D9", 14))
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setFixedHeight(34)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background: #141C2B;
                color: #C9D1D9;
                border: 1px solid #23314A;
                border-radius: 6px;
                padding: 0 14px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #1D2A40;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_refresh.clicked.connect(self.load_data)
        header_row.addWidget(btn_refresh)
        root_layout.addLayout(header_row)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.content_container = QWidget()
        self.content_container.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 8, 0, 16)
        self.content_layout.setSpacing(20)

        scroll.setWidget(self.content_container)
        root_layout.addWidget(scroll, stretch=1)

    def load_data(self) -> None:
        """Queries SQLite database for fresh metrics and re-renders dashboard cards."""
        # Clear existing widgets in content layout
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Total Metrics
        cur.execute("SELECT COUNT(*), COALESCE(SUM(page_count), 0), COALESCE(SUM(file_size), 0) FROM books;")
        row_totals = cur.fetchone()
        total_books = row_totals[0] if row_totals else 0
        total_pages = row_totals[1] if row_totals else 0
        total_bytes = row_totals[2] if row_totals else 0
        total_gb = total_bytes / (1024 * 1024 * 1024)

        # 2. Document Types count
        cur.execute("SELECT COALESCE(doc_type, 'book'), COUNT(*) FROM books GROUP BY COALESCE(doc_type, 'book');")
        doc_type_counts = dict(cur.fetchall())
        count_books = doc_type_counts.get("book", 0)
        count_scripts = doc_type_counts.get("study_script", 0)

        # 3. Top Categories
        cur.execute("""
            SELECT category, COUNT(DISTINCT b.id) as cnt, COALESCE(SUM(b.page_count), 0) as pgs
            FROM book_categories bc
            JOIN books b ON bc.book_id = b.id
            GROUP BY category
            ORDER BY cnt DESC;
        """)
        cat_stats = cur.fetchall()

        # 4. Publication Years Timeline
        cur.execute("""
            SELECT year, COUNT(*)
            FROM books
            WHERE year IS NOT NULL AND year >= 1990 AND year <= 2030
            GROUP BY year
            ORDER BY year DESC
            LIMIT 12;
        """)
        year_stats = cur.fetchall()

        # 5. Top Authors
        cur.execute("""
            SELECT author, COUNT(*) as cnt
            FROM books
            WHERE author IS NOT NULL AND author != '' AND author != 'Unbekannt'
            GROUP BY author
            ORDER BY cnt DESC
            LIMIT 6;
        """)
        author_stats = cur.fetchall()

        # 6. Extremes (Thickest vs Slimmest)
        cur.execute("SELECT title, author, page_count FROM books WHERE page_count > 0 ORDER BY page_count DESC LIMIT 1;")
        thickest = cur.fetchone()
        cur.execute("SELECT title, author, page_count FROM books WHERE page_count > 0 ORDER BY page_count ASC LIMIT 1;")
        slimmest = cur.fetchone()

        # 7. Desk reading activity
        cur.execute("SELECT COUNT(*), COALESCE(SUM(current_page), 0) FROM desk_items;")
        desk_row = cur.fetchone()
        desk_count = desk_row[0] if desk_row else 0
        desk_pages = desk_row[1] if desk_row else 0

        # -------------------------------------------------------------
        # Section A: 4 Big KPI Telemetry Cards
        # -------------------------------------------------------------
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(14)

        kpi_grid.addWidget(self._create_kpi_card(
            title="GESAMTBESTAND",
            value=f"{total_books:,}".replace(",", "."),
            subtext=f"{count_books} Fachbücher · {count_scripts} Studienbriefe",
            icon="library",
            accent="#58A6FF"
        ), 0, 0)

        kpi_grid.addWidget(self._create_kpi_card(
            title="GESAMTUMFANG",
            value=f"{total_pages:,}".replace(",", ".") + " S.",
            subtext=f"Ø {int(total_pages / max(1, total_books))} Seiten pro Werk",
            icon="notes",
            accent="#3FB950"
        ), 0, 1)

        kpi_grid.addWidget(self._create_kpi_card(
            title="SPEICHERVOLUMEN",
            value=f"{total_gb:.2f} GB",
            subtext=f"{total_bytes / (1024*1024):.0f} MB Datenbestand",
            icon="sync",
            accent="#BC8CFF"
        ), 0, 2)

        kpi_grid.addWidget(self._create_kpi_card(
            title="AKTIV AM PULTPULT",
            value=f"{desk_count} Werke",
            subtext=f"{desk_pages} gelesene Seiten im Fokus",
            icon="desk",
            accent="#FFA657"
        ), 0, 3)

        self.content_layout.addLayout(kpi_grid)

        # -------------------------------------------------------------
        # Section B: Faculty Breakdown Bar & Cards
        # -------------------------------------------------------------
        cat_card = QFrame()
        cat_card.setStyleSheet("""
            QFrame#catCard {
                background-color: #0E1522;
                border: 1px solid #1E2B42;
                border-radius: 12px;
            }
        """)
        cat_card.setObjectName("catCard")
        cat_lay = QVBoxLayout(cat_card)
        cat_lay.setContentsMargins(20, 18, 20, 20)
        cat_lay.setSpacing(14)

        cat_title = QLabel("FACHBEREICHE & THEMATISCHE VERTEILUNG")
        cat_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        cat_title.setStyleSheet("color: #F0F6FC; letter-spacing: 0.5px;")
        cat_lay.addWidget(cat_title)

        # Continuous colored visual bar
        bar_widget = FacultyBarWidget([(c[0], c[1], c[2]) for c in cat_stats[:10]])
        cat_lay.addWidget(bar_widget)

        # Grid of top categories with percentage badges
        cats_grid = QGridLayout()
        cats_grid.setSpacing(10)
        for i, (c_name, c_cnt, c_pgs) in enumerate(cat_stats[:8]):
            pct = (c_cnt / max(1, total_books)) * 100
            _, accent_col = FACULTY_COLORS.get(c_name, ("#161B22", "#58A6FF"))
            
            pill = QFrame()
            pill.setStyleSheet(f"""
                QFrame {{
                    background-color: #121A2A;
                    border: 1px solid {accent_col}33;
                    border-radius: 8px;
                    padding: 8px 12px;
                }}
            """)
            p_lay = QVBoxLayout(pill)
            p_lay.setContentsMargins(4, 4, 4, 4)
            p_lay.setSpacing(4)

            top_row = QHBoxLayout()
            lbl_dot = QLabel("●")
            lbl_dot.setStyleSheet(f"color: {accent_col}; font-size: 11px;")
            top_row.addWidget(lbl_dot)
            lbl_n = QLabel(c_name)
            lbl_n.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_n.setStyleSheet("color: #F0F6FC;")
            top_row.addWidget(lbl_n)
            top_row.addStretch()

            lbl_pct = QLabel(f"{pct:.1f}%")
            lbl_pct.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_pct.setStyleSheet(f"color: {accent_col};")
            top_row.addWidget(lbl_pct)
            p_lay.addLayout(top_row)

            lbl_sub_stat = QLabel(f"{c_cnt} Bücher · {c_pgs:,} Seiten".replace(",", "."))
            lbl_sub_stat.setFont(QFont("Segoe UI", 8))
            lbl_sub_stat.setStyleSheet("color: #8B949E;")
            p_lay.addWidget(lbl_sub_stat)

            r, c = divmod(i, 2)
            cats_grid.addWidget(pill, r, c)

        cat_lay.addLayout(cats_grid)
        self.content_layout.addWidget(cat_card)

        # -------------------------------------------------------------
        # Section C: Timeline & Extremes Side-by-Side
        # -------------------------------------------------------------
        row_c = QHBoxLayout()
        row_c.setSpacing(14)

        # Publication Timeline Card
        time_card = QFrame()
        time_card.setStyleSheet("background-color: #0E1522; border: 1px solid #1E2B42; border-radius: 12px; padding: 16px;")
        time_lay = QVBoxLayout(time_card)
        time_lay.setSpacing(12)

        lbl_time_header = QLabel("ERSCHEINUNGSJAHRE (ZEITSTRAHL)")
        lbl_time_header.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_time_header.setStyleSheet("color: #F0F6FC;")
        time_lay.addWidget(lbl_time_header)

        max_year_cnt = max((y[1] for y in year_stats), default=1)
        for yr, y_cnt in year_stats[:6]:
            y_row = QHBoxLayout()
            y_lbl = QLabel(str(yr))
            y_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            y_lbl.setFixedWidth(40)
            y_lbl.setStyleSheet("color: #C9D1D9;")
            y_row.addWidget(y_lbl)

            prog = QProgressBar()
            prog.setMaximum(max_year_cnt)
            prog.setValue(y_cnt)
            prog.setTextVisible(False)
            prog.setFixedHeight(8)
            prog.setStyleSheet("""
                QProgressBar {
                    background-color: #141C2B;
                    border: none;
                    border-radius: 4px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #58A6FF);
                    border-radius: 4px;
                }
            """)
            y_row.addWidget(prog, stretch=1)

            y_val = QLabel(f"{y_cnt}")
            y_val.setFixedWidth(28)
            y_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            y_val.setFont(QFont("Segoe UI", 9, QFont.Bold))
            y_val.setStyleSheet("color: #58A6FF;")
            y_row.addWidget(y_val)
            time_lay.addLayout(y_row)

        time_lay.addStretch()
        row_c.addWidget(time_card, stretch=1)

        # Extremes & Curiosities Card
        ext_card = QFrame()
        ext_card.setStyleSheet("background-color: #0E1522; border: 1px solid #1E2B42; border-radius: 12px; padding: 16px;")
        ext_lay = QVBoxLayout(ext_card)
        ext_lay.setSpacing(12)

        lbl_ext_header = QLabel("BIBLIOTHEKS-HIGHLIGHTS & REKORDE")
        lbl_ext_header.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_ext_header.setStyleSheet("color: #F0F6FC;")
        ext_lay.addWidget(lbl_ext_header)

        if thickest:
            t_box = self._create_mini_highlight(
                badge="📖 UMFANGREICHSTES WERK",
                badge_col="#FFA657",
                title=thickest[0],
                sub=f"{thickest[2]:,} Seiten · {thickest[1]}".replace(",", ".")
            )
            ext_lay.addWidget(t_box)

        if slimmest:
            s_box = self._create_mini_highlight(
                badge="⚡ KOMPAKTESTES SKRIPT / BUCH",
                badge_col="#3FB950",
                title=slimmest[0],
                sub=f"{slimmest[2]} Seiten · {slimmest[1]}"
            )
            ext_lay.addWidget(s_box)

        if author_stats:
            top_auth = author_stats[0]
            a_box = self._create_mini_highlight(
                badge="🏆 MEISTVERTRETENER AUTOR / VERLAG",
                badge_col="#BC8CFF",
                title=top_auth[0],
                sub=f"{top_auth[1]} Titel im aktiven Katalog"
            )
            ext_lay.addWidget(a_box)

        ext_lay.addStretch()
        row_c.addWidget(ext_card, stretch=1)

        self.content_layout.addLayout(row_c)

    def _create_kpi_card(self, title: str, value: str, subtext: str, icon: str, accent: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #0E1522;
                border: 1px solid #1E2B42;
                border-top: 3px solid {accent};
                border-radius: 10px;
                padding: 12px;
            }}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_t.setStyleSheet("color: #8B949E; letter-spacing: 0.5px;")
        top.addWidget(lbl_t)
        top.addStretch()

        ico = QLabel()
        ico.setPixmap(create_vector_pixmap(icon, accent, 14))
        top.addWidget(ico)
        lay.addLayout(top)

        lbl_v = QLabel(value)
        lbl_v.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_v.setStyleSheet("color: #F0F6FC;")
        lay.addWidget(lbl_v)

        lbl_s = QLabel(subtext)
        lbl_s.setFont(QFont("Segoe UI", 9))
        lbl_s.setStyleSheet("color: #6E7681;")
        lay.addWidget(lbl_s)
        return card

    def _create_mini_highlight(self, badge: str, badge_col: str, title: str, sub: str) -> QFrame:
        f = QFrame()
        f.setStyleSheet("""
            QFrame {
                background-color: #121A2A;
                border: 1px solid #1C273C;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        lay = QVBoxLayout(f)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(3)

        lbl_b = QLabel(badge)
        lbl_b.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_b.setStyleSheet(f"color: {badge_col}; letter-spacing: 0.5px;")
        lay.addWidget(lbl_b)

        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_t.setStyleSheet("color: #F0F6FC;")
        lbl_t.setWordWrap(True)
        lay.addWidget(lbl_t)

        lbl_s = QLabel(sub)
        lbl_s.setFont(QFont("Segoe UI", 8))
        lbl_s.setStyleSheet("color: #8B949E;")
        lay.addWidget(lbl_s)
        return f
