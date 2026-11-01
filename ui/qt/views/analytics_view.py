"""Library Analytics & Statistics Dashboard for Campus-Bibliothek.
Renders high-end Cyber-Obsidian metrics, faculty distributions, publication timeline, and reading telemetry.
"""

from typing import Any, Dict, List, Optional, Tuple
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QLinearGradient, QPainterPath
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.library_db import get_db_connection, init_library_schema
from core.cover_manager import FACULTY_COLORS


class FacultyBarWidget(QWidget):
    """Segmented horizontal distribution bar with smooth rounded borders and category glow colors."""
    def __init__(self, cat_data: List[Tuple[str, int, int]], parent=None):
        super().__init__(parent)
        self.cat_data = cat_data  # [(cat_name, book_count, page_count), ...]
        self.total_books = sum(c[1] for c in cat_data) or 1
        self.setFixedHeight(12)
        self.setToolTip("Thematische Verteilung im Gesamtbestand")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        radius = 6.0

        # Create clipping path for clean rounded ends
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        painter.setClipPath(clip_path)

        # Background track
        painter.setBrush(QBrush(QColor("#151D2C")))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, w, h)

        # Draw segmented distribution
        cur_x = 0
        for i, (name, count, _) in enumerate(self.cat_data):
            pct = count / self.total_books
            seg_w = max(4, int(w * pct)) if count > 0 else 0
            if i == len(self.cat_data) - 1:
                seg_w = max(seg_w, w - cur_x)

            _, accent_col = FACULTY_COLORS.get(name, ("#161B22", "#58A6FF"))
            painter.setBrush(QBrush(QColor(accent_col)))
            painter.drawRect(cur_x, 0, seg_w, h)
            cur_x += seg_w
            if cur_x >= w:
                break


class TimelineHistogramWidget(QWidget):
    """Horizontal publication year histogram with custom bar rendering and value badges."""
    def __init__(self, year_data: List[Tuple[int, int]], parent=None):
        super().__init__(parent)
        self.year_data = year_data  # [(year, count), ...]
        self.max_cnt = max((y[1] for y in year_data), default=1)
        self.setFixedHeight(len(year_data) * 26 + 8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        w = self.width()
        bar_x = 48
        val_w = 40
        available_bar_w = max(10, w - bar_x - val_w - 12)

        y_offset = 6
        bar_height = 12

        font_year = QFont("Segoe UI", 9, QFont.Bold)
        font_val = QFont("Segoe UI", 9, QFont.Bold)

        for yr, cnt in self.year_data:
            # Year label
            painter.setFont(font_year)
            painter.setPen(QColor("#8B949E"))
            painter.drawText(0, y_offset + 9, 40, 14, Qt.AlignRight | Qt.AlignVCenter, str(yr))

            # Background bar track
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#131D2D")))
            painter.drawRoundedRect(bar_x, y_offset, available_bar_w, bar_height, 4, 4)

            # Filled gradient bar
            fill_w = max(6, int((cnt / self.max_cnt) * available_bar_w))
            grad = QLinearGradient(bar_x, 0, bar_x + fill_w, 0)
            grad.setColorAt(0.0, QColor("#1F6FEB"))
            grad.setColorAt(1.0, QColor("#58A6FF"))
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(bar_x, y_offset, fill_w, bar_height, 4, 4)

            # Value label
            painter.setFont(font_val)
            painter.setPen(QColor("#58A6FF"))
            painter.drawText(bar_x + fill_w + 10, y_offset - 1, val_w, 14, Qt.AlignLeft | Qt.AlignVCenter, str(cnt))

            y_offset += 26


class AnalyticsView(QWidget):
    """Interactive High-End Cyber-Obsidian Statistics & Analytics Dashboard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        init_library_schema()
        self._build_ui()
        self.load_data()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(30, 20, 30, 20)
        root_layout.setSpacing(16)

        # Header Row
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(create_vector_pixmap("research", "#58A6FF", 22))
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("""
            background: #131E33;
            border: 1px solid #233554;
            border-radius: 9px;
        """)
        header_row.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel("Bibliotheks-Statistik & Analyse-Cockpit")
        lbl_title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_title.setStyleSheet("color: #FFFFFF;")
        title_box.addWidget(lbl_title)

        lbl_sub = QLabel("Bestands-Kennzahlen, Fachbereichs-Verteilung und Lese-Fortschritt im Überblick")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_box.addWidget(lbl_sub)
        header_row.addLayout(title_box)

        header_row.addStretch()

        btn_refresh = QPushButton("  Aktualisieren")
        btn_refresh.setIcon(create_vector_icon("sync", "#C9D1D9", 13))
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
        self.content_layout.setContentsMargins(0, 4, 0, 16)
        self.content_layout.setSpacing(14)

        scroll.setWidget(self.content_container)
        root_layout.addWidget(scroll, stretch=1)

    def load_data(self) -> None:
        """Queries SQLite database for fresh metrics and re-renders dashboard cards."""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            l = item.layout()
            if l:
                while l.count():
                    child = l.takeAt(0)
                    cw = child.widget()
                    if cw:
                        cw.deleteLater()

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
        try:
            cur.execute("SELECT COALESCE(doc_type, 'book'), COUNT(*) FROM books GROUP BY COALESCE(doc_type, 'book');")
            doc_type_counts = dict(cur.fetchall())
        except Exception:
            doc_type_counts = {"book": total_books}

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

        # 4. Publication Years Timeline (top years sorted chronologically)
        cur.execute("""
            SELECT year, COUNT(*)
            FROM books
            WHERE year IS NOT NULL AND year >= 1990 AND year <= 2030
            GROUP BY year
            ORDER BY COUNT(*) DESC
            LIMIT 7;
        """)
        raw_year_stats = cur.fetchall()
        year_stats = sorted(raw_year_stats, key=lambda x: x[0], reverse=True)

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

        # =============================================================
        # Section A: 4 Big KPI Telemetry Cards (Pure Clean Obsidian)
        # =============================================================
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(14)

        kpi_row.addWidget(self._create_kpi_card(
            title="GESAMTBESTAND",
            value=f"{total_books:,}".replace(",", "."),
            subtext=f"{count_books} Fachbücher · {count_scripts} Studienbriefe",
            icon="library",
            accent="#58A6FF"
        ), stretch=1)

        kpi_row.addWidget(self._create_kpi_card(
            title="GESAMTUMFANG",
            value=f"{total_pages:,}".replace(",", ".") + " S.",
            subtext=f"Ø {int(total_pages / max(1, total_books))} Seiten pro Werk",
            icon="notes",
            accent="#3FB950"
        ), stretch=1)

        kpi_row.addWidget(self._create_kpi_card(
            title="SPEICHERVOLUMEN",
            value=f"{total_gb:.2f} GB",
            subtext=f"{total_bytes / (1024*1024):.0f} MB auf Festplatte",
            icon="sync",
            accent="#BC8CFF"
        ), stretch=1)

        kpi_row.addWidget(self._create_kpi_card(
            title="AKTIV AM PULTPULT",
            value=f"{desk_count} Werke",
            subtext=f"{desk_pages} gelesene Seiten im Fokus",
            icon="desk",
            accent="#FFA657"
        ), stretch=1)

        self.content_layout.addLayout(kpi_row)

        # =============================================================
        # Section B: Faculty Breakdown Bar & Cards
        # =============================================================
        cat_card = QFrame()
        cat_card.setObjectName("catCard")
        cat_card.setStyleSheet("""
            QFrame#catCard {
                background-color: #0E1522;
                border: 1px solid #1E2B42;
                border-radius: 12px;
            }
        """)
        cat_lay = QVBoxLayout(cat_card)
        cat_lay.setContentsMargins(20, 16, 20, 18)
        cat_lay.setSpacing(14)

        cat_head = QHBoxLayout()
        cat_title = QLabel("FACHBEREICHE & THEMATISCHE VERTEILUNG")
        cat_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        cat_title.setStyleSheet("color: #C9D1D9; letter-spacing: 0.5px;")
        cat_head.addWidget(cat_title)
        cat_head.addStretch()

        lbl_top_hint = QLabel(f"{len(cat_stats)} Fachbereiche indiziert")
        lbl_top_hint.setFont(QFont("Segoe UI", 9))
        lbl_top_hint.setStyleSheet("color: #6E7681;")
        cat_head.addWidget(lbl_top_hint)
        cat_lay.addLayout(cat_head)

        # Segmented colored distribution bar
        bar_widget = FacultyBarWidget([(c[0], c[1], c[2]) for c in cat_stats[:10]])
        cat_lay.addWidget(bar_widget)

        # Grid of top categories with percentage badges (NO brackets!)
        cats_grid = QGridLayout()
        cats_grid.setSpacing(10)
        for i, (c_name, c_cnt, c_pgs) in enumerate(cat_stats[:8]):
            pct = (c_cnt / max(1, total_books)) * 100
            _, accent_col = FACULTY_COLORS.get(c_name, ("#161B22", "#58A6FF"))

            pill = QFrame()
            pill.setObjectName("catPill")
            pill.setStyleSheet(f"""
                QFrame#catPill {{
                    background-color: #121A28;
                    border: 1px solid #1C273C;
                    border-radius: 8px;
                }}
            """)
            p_lay = QVBoxLayout(pill)
            p_lay.setContentsMargins(14, 10, 14, 10)
            p_lay.setSpacing(4)

            top_row = QHBoxLayout()
            # Clean colored indicator tag
            tag_dot = QLabel("▌")
            tag_dot.setFont(QFont("Segoe UI", 10, QFont.Bold))
            tag_dot.setStyleSheet(f"color: {accent_col};")
            top_row.addWidget(tag_dot)

            lbl_n = QLabel(c_name)
            lbl_n.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_n.setStyleSheet("color: #F0F6FC;")
            top_row.addWidget(lbl_n)
            top_row.addStretch()

            lbl_pct = QLabel(f"{pct:.1f}%")
            lbl_pct.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_pct.setStyleSheet(f"color: {accent_col};")
            top_row.addWidget(lbl_pct)
            p_lay.addLayout(top_row)

            bottom_row = QHBoxLayout()
            lbl_sub_stat = QLabel(f"{c_cnt} Bücher · {c_pgs:,} Seiten".replace(",", "."))
            lbl_sub_stat.setFont(QFont("Segoe UI", 8))
            lbl_sub_stat.setStyleSheet("color: #7D8590;")
            bottom_row.addWidget(lbl_sub_stat)
            p_lay.addLayout(bottom_row)

            r, c = divmod(i, 2)
            cats_grid.addWidget(pill, r, c)

        cat_lay.addLayout(cats_grid)
        self.content_layout.addWidget(cat_card)

        # =============================================================
        # Section C: Timeline & Extremes Side-by-Side
        # =============================================================
        row_c = QHBoxLayout()
        row_c.setSpacing(14)

        # Publication Timeline Card
        time_card = QFrame()
        time_card.setObjectName("timeCard")
        time_card.setStyleSheet("""
            QFrame#timeCard {
                background-color: #0E1522;
                border: 1px solid #1E2B42;
                border-radius: 12px;
            }
        """)
        time_lay = QVBoxLayout(time_card)
        time_lay.setContentsMargins(20, 16, 20, 18)
        time_lay.setSpacing(12)

        time_head = QHBoxLayout()
        lbl_time_header = QLabel("ERSCHEINUNGSJAHRE (ZEITSTRAHL)")
        lbl_time_header.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_time_header.setStyleSheet("color: #C9D1D9; letter-spacing: 0.5px;")
        time_head.addWidget(lbl_time_header)
        time_head.addStretch()

        cur.execute("SELECT AVG(year) FROM books WHERE year >= 1990 AND year <= 2030;")
        avg_year_row = cur.fetchone()
        avg_year = int(avg_year_row[0]) if avg_year_row and avg_year_row[0] else 0
        if avg_year > 0:
            lbl_avg = QLabel(f"Ø Jahrgang: {avg_year}")
            lbl_avg.setFont(QFont("Segoe UI", 9))
            lbl_avg.setStyleSheet("color: #6E7681;")
            time_head.addWidget(lbl_avg)
        time_lay.addLayout(time_head)

        # Custom Histogram
        if year_stats:
            histo = TimelineHistogramWidget(year_stats)
            time_lay.addWidget(histo)
        else:
            lbl_empty = QLabel("Keine Jahresangaben vorhanden.")
            lbl_empty.setStyleSheet("color: #6E7681; font-style: italic;")
            time_lay.addWidget(lbl_empty)

        time_lay.addStretch()
        row_c.addWidget(time_card, stretch=1)

        # Extremes & Highlights Card
        ext_card = QFrame()
        ext_card.setObjectName("extCard")
        ext_card.setStyleSheet("""
            QFrame#extCard {
                background-color: #0E1522;
                border: 1px solid #1E2B42;
                border-radius: 12px;
            }
        """)
        ext_lay = QVBoxLayout(ext_card)
        ext_lay.setContentsMargins(20, 16, 20, 18)
        ext_lay.setSpacing(10)

        lbl_ext_header = QLabel("BIBLIOTHEKS-HIGHLIGHTS & REKORDE")
        lbl_ext_header.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_ext_header.setStyleSheet("color: #C9D1D9; letter-spacing: 0.5px;")
        ext_lay.addWidget(lbl_ext_header)

        if thickest:
            t_box = self._create_mini_highlight(
                badge="UMFANGREICHSTES WERK",
                badge_col="#FFA657",
                icon="book",
                title=thickest[0],
                sub=f"{thickest[2]:,} Seiten · {thickest[1]}".replace(",", ".")
            )
            ext_lay.addWidget(t_box)

        if slimmest:
            s_box = self._create_mini_highlight(
                badge="KOMPAKTESTES DOKUMENT",
                badge_col="#3FB950",
                icon="notes",
                title=slimmest[0],
                sub=f"{slimmest[2]} Seiten · {slimmest[1]}"
            )
            ext_lay.addWidget(s_box)

        if author_stats:
            top_auth = author_stats[0]
            a_box = self._create_mini_highlight(
                badge="MEISTVERTRETENER AUTOR / VERLAG",
                badge_col="#BC8CFF",
                icon="trophy",
                title=top_auth[0],
                sub=f"{top_auth[1]} Titel im aktiven Katalog"
            )
            ext_lay.addWidget(a_box)

        ext_lay.addStretch()
        row_c.addWidget(ext_card, stretch=1)

        self.content_layout.addLayout(row_c)

    def _create_kpi_card(self, title: str, value: str, subtext: str, icon: str, accent: str) -> QFrame:
        card = QFrame()
        card.setObjectName("kpiCard")
        # Clean solid card without harsh 3px border-top bar
        card.setStyleSheet(f"""
            QFrame#kpiCard {{
                background-color: #0E1522;
                border: 1px solid #1E2B42;
                border-radius: 10px;
            }}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        top = QHBoxLayout()
        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_t.setStyleSheet("color: #8B949E; letter-spacing: 0.5px;")
        top.addWidget(lbl_t)
        top.addStretch()

        ico_badge = QLabel()
        ico_badge.setPixmap(create_vector_pixmap(icon, accent, 14))
        ico_badge.setFixedSize(26, 26)
        ico_badge.setAlignment(Qt.AlignCenter)
        ico_badge.setStyleSheet(f"""
            background: {accent}18;
            border-radius: 6px;
            border: 1px solid {accent}33;
        """)
        top.addWidget(ico_badge)
        lay.addLayout(top)

        lbl_v = QLabel(value)
        lbl_v.setFont(QFont("Segoe UI", 20, QFont.Bold))
        lbl_v.setStyleSheet("color: #FFFFFF;")
        lay.addWidget(lbl_v)

        lbl_s = QLabel(subtext)
        lbl_s.setFont(QFont("Segoe UI", 9))
        lbl_s.setStyleSheet("color: #6E7681;")
        lay.addWidget(lbl_s)
        return card

    def _create_mini_highlight(self, badge: str, badge_col: str, icon: str, title: str, sub: str) -> QFrame:
        f = QFrame()
        f.setObjectName("miniHighlight")
        f.setStyleSheet(f"""
            QFrame#miniHighlight {{
                background-color: #121A28;
                border: 1px solid #1C273C;
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(f)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)

        head_row = QHBoxLayout()
        lbl_b = QLabel(badge)
        lbl_b.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_b.setStyleSheet(f"color: {badge_col}; letter-spacing: 0.5px;")
        head_row.addWidget(lbl_b)
        head_row.addStretch()

        ico = QLabel()
        ico.setPixmap(create_vector_pixmap(icon, badge_col, 12))
        head_row.addWidget(ico)
        lay.addLayout(head_row)

        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_t.setStyleSheet("color: #F0F6FC;")
        lbl_t.setWordWrap(True)
        lbl_t.setMaximumHeight(38)
        lay.addWidget(lbl_t)

        lbl_s = QLabel(sub)
        lbl_s.setFont(QFont("Segoe UI", 8))
        lbl_s.setStyleSheet("color: #7D8590;")
        lay.addWidget(lbl_s)
        return f
