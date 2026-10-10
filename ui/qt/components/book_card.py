"""Modern 3D-Styled Book Card Widget for the Virtual Shelf in PySide6.
Features dynamic faculty glow badges, smooth hover animations, book spine accents, and reading progress.
"""

from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage, QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
)
from core.cover_manager import get_cached_cover, generate_fallback_cover, FACULTY_COLORS
from ui.qt.icons import create_vector_pixmap


class BookCard(QFrame):
    """High-End 3D Book Card with glossy accents and faculty color badges."""

    clicked = Signal(str)
    double_clicked = Signal(str)
    context_menu_requested = Signal(str, object)

    CARD_WIDTH = 176
    CARD_HEIGHT = 308
    COVER_WIDTH = 142
    COVER_HEIGHT = 196

    def __init__(self, book: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.book = book
        self.book_id = str(book["id"])
        self.is_selected = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._build_ui()
        self._update_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # 1. Top Bar: Faculty Glow Badge & Desk Reading Indicator
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)

        cat_str = self.book.get("categories_str") or "Sonstiges"
        cats = [c.strip() for c in cat_str.split("|") if c.strip()]
        first_cat = self.book.get("primary_category") or (cats[0] if cats else "Sonstiges")
        _, accent_col = FACULTY_COLORS.get(first_cat, ("#161B22", "#58A6FF"))

        display_cat = (first_cat[:12] + "…") if len(first_cat) > 13 else first_cat
        if len(cats) > 1:
            display_cat = f"{first_cat[:9]} +{len(cats)-1}"

        # Pill container with semi-transparent tinted background
        pill = QFrame()
        pill.setStyleSheet(f"""
            QFrame {{
                background-color: #0F1626;
                border: 1px solid {accent_col}55;
                border-radius: 4px;
                padding: 1px 4px;
            }}
        """)
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(4, 1, 4, 1)
        pill_layout.setSpacing(3)

        dot = QLabel("●")
        dot.setFont(QFont("Segoe UI", 7))
        dot.setStyleSheet(f"color: {accent_col}; border: none; background: transparent;")
        pill_layout.addWidget(dot)

        self.lbl_cat = QLabel(display_cat)
        self.lbl_cat.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_cat.setStyleSheet(f"color: {accent_col}; border: none; background: transparent;")
        pill_layout.addWidget(self.lbl_cat)

        top_bar.addWidget(pill)
        top_bar.addStretch()

        is_desk = bool(self.book.get("is_on_desk"))
        pct = self.book.get("reading_progress") or 0
        ext_cnt = int(self.book.get("extract_count") or 0)

        # Right side indicators: Extracts badge & Desk badge
        indicators_layout = QHBoxLayout()
        indicators_layout.setContentsMargins(0, 0, 0, 0)
        indicators_layout.setSpacing(4)

        if ext_cnt > 0:
            ext_badge = QFrame()
            ext_badge.setToolTip(f"{ext_cnt} angeheftete(s) Kapitel / Auszug")
            ext_badge.setStyleSheet("""
                QFrame {
                    background-color: #101E36;
                    border: 1px solid #1F6FEB;
                    border-radius: 4px;
                    padding: 1px 4px;
                }
            """)
            eb_layout = QHBoxLayout(ext_badge)
            eb_layout.setContentsMargins(3, 1, 3, 1)
            eb_layout.setSpacing(2)

            lbl_ext_icon = QLabel()
            lbl_ext_icon.setPixmap(create_vector_pixmap("download", "#58A6FF", 10))
            lbl_ext_icon.setStyleSheet("border: none; background: transparent;")
            eb_layout.addWidget(lbl_ext_icon)

            lbl_ext_num = QLabel(str(ext_cnt))
            lbl_ext_num.setFont(QFont("Segoe UI", 7, QFont.Bold))
            lbl_ext_num.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
            eb_layout.addWidget(lbl_ext_num)

            indicators_layout.addWidget(ext_badge)

        self.desk_badge = QWidget()
        desk_badge_layout = QHBoxLayout(self.desk_badge)
        desk_badge_layout.setContentsMargins(0, 0, 0, 0)
        desk_badge_layout.setSpacing(3)

        lbl_bm = QLabel()
        lbl_bm.setPixmap(create_vector_pixmap("bookmark", "#58A6FF", 12))
        lbl_bm.setStyleSheet("border: none; background: transparent;")
        desk_badge_layout.addWidget(lbl_bm)

        self.lbl_pct = QLabel(f"{pct}%" if pct > 0 else "")
        self.lbl_pct.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_pct.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        self.lbl_pct.setVisible(pct > 0)
        desk_badge_layout.addWidget(self.lbl_pct)

        indicators_layout.addWidget(self.desk_badge)
        self.desk_badge.setVisible(is_desk)

        top_bar.addLayout(indicators_layout)
        layout.addLayout(top_bar)

        # 2. Cover Container (Deep shadow & subtle bevel border)
        cover_frame = QFrame()
        cover_frame.setFixedSize(self.COVER_WIDTH, self.COVER_HEIGHT)
        cover_frame.setStyleSheet("""
            QFrame {
                background-color: #090D16;
                border: 1px solid #232F48;
                border-radius: 6px;
            }
        """)
        cv_layout = QVBoxLayout(cover_frame)
        cv_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_cover = QLabel()
        self.lbl_cover.setFixedSize(self.COVER_WIDTH - 2, self.COVER_HEIGHT - 2)
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setStyleSheet("border: none; background: transparent; border-radius: 5px;")
        self._load_cover_image(first_cat)
        cv_layout.addWidget(self.lbl_cover)

        layout.addWidget(cover_frame, alignment=Qt.AlignCenter)

        # 3. Title (Allocated 2 lines height)
        raw_title = self.book.get("title") or "Ohne Titel"
        short_title = (raw_title[:38] + "…") if len(raw_title) > 40 else raw_title
        self.lbl_title = QLabel(short_title)
        self.lbl_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        self.lbl_title.setFixedHeight(34)
        layout.addWidget(self.lbl_title)

        # 4. Author (1 line, muted)
        raw_author = self.book.get("author") or "Unbekannter Autor"
        short_author = (raw_author[:22] + "…") if len(raw_author) > 23 else raw_author
        self.lbl_author = QLabel(short_author)
        self.lbl_author.setFont(QFont("Segoe UI", 8))
        self.lbl_author.setAlignment(Qt.AlignCenter)
        self.lbl_author.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        layout.addWidget(self.lbl_author)

        # 5. Glowing Reading Progress Bar
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(pct)
        self.prog_bar.setTextVisible(False)
        self.prog_bar.setFixedHeight(3)
        self.prog_bar.setStyleSheet("""
            QProgressBar {
                background-color: #121826;
                border: none;
                border-radius: 1px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #3FB950);
                border-radius: 1px;
            }
        """)
        if not (is_desk and pct > 0):
            self.prog_bar.hide()
        layout.addWidget(self.prog_bar)

    def _load_cover_image(self, category: str) -> None:
        cached_pil = get_cached_cover(self.book_id)
        if not cached_pil:
            cached_pil = generate_fallback_cover(
                self.book.get("title", ""),
                self.book.get("author", ""),
                category
            )

        if cached_pil:
            try:
                rgb_pil = cached_pil.convert("RGB")
                w, h = rgb_pil.size
                qim = QImage(rgb_pil.tobytes(), w, h, w * 3, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(qim).scaled(
                    self.COVER_WIDTH - 2, self.COVER_HEIGHT - 2,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.lbl_cover.setPixmap(pixmap)
            except Exception:
                pass

    def update_book_data(self, updated_book: Dict[str, Any]) -> None:
        """Dynamically updates reading progress and desk status on this existing card without rebuilding."""
        self.book = updated_book
        is_desk = bool(updated_book.get("is_on_desk"))
        pct = int(updated_book.get("reading_progress") or 0)

        if hasattr(self, "desk_badge"):
            self.desk_badge.setVisible(is_desk)
        if hasattr(self, "lbl_pct"):
            if pct > 0 and is_desk:
                self.lbl_pct.setText(f"{pct}%")
                self.lbl_pct.setVisible(True)
            else:
                self.lbl_pct.setVisible(False)

        if hasattr(self, "prog_bar"):
            self.prog_bar.setValue(pct)
            self.prog_bar.setVisible(is_desk and pct > 0)

    def set_selected(self, selected: bool) -> None:
        self.is_selected = selected
        self._update_style()

    def _update_style(self, hover: bool = False) -> None:
        if self.is_selected:
            bg = "#1A253C"
            border = "#58A6FF"
        elif hover:
            bg = "#162035"
            border = "#388BFD"
        else:
            bg = "#121826"
            border = "#232F48"

        self.setStyleSheet(f"""
            BookCard {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 9px;
            }}
        """)

    def enterEvent(self, event):
        if not self.is_selected:
            self._update_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.is_selected:
            self._update_style(hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.book_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self.book_id)
        super().mouseDoubleClickEvent(event)

    def _on_context_menu(self, pos):
        self.context_menu_requested.emit(self.book_id, self.mapToGlobal(pos))
