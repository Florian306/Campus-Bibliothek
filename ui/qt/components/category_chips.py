"""Adaptive Category Filter Chips Bar for PySide6.
Dynamically adjusts visible category chips on window resize without text truncation.
Highlights selected categories from 'Weitere Fachbereiche' both in the bar and menu.
"""

from typing import List, Tuple, Optional
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton,
    QMenu,
    QSizePolicy,
)
from ui.qt.icons import create_vector_icon


class CategoryChipsBar(QWidget):
    """Horizontal adaptive chip bar for instant faceted category filtering."""

    category_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_category: str = "Alle"
        self.category_counts: List[Tuple[str, int]] = []
        self._buttons: dict = {}
        self.btn_more: Optional[QPushButton] = None
        self._last_signature = None

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(8)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(30)
        self._resize_timer.timeout.connect(self._rebuild_chips)

    def populate(self, category_counts: List[Tuple[str, int]]) -> None:
        self.category_counts = category_counts
        self._last_signature = None
        self._rebuild_chips()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _rebuild_chips(self) -> None:
        if not self.category_counts:
            return

        avail_w = self.width()
        if avail_w < 150:
            if self.parentWidget():
                avail_w = max(avail_w, self.parentWidget().width() - 40)
            if avail_w < 150:
                avail_w = 900

        total_books = sum(c[1] for c in self.category_counts)
        fm = QFontMetrics(self.font())

        # Width of 'Alle' chip
        w_all = fm.horizontalAdvance(f"Alle  •  {total_books}") + 32
        w_all = max(w_all, 85)

        # Width of 'Weitere Fachbereiche' button
        w_more = fm.horizontalAdvance("  Weitere Fachbereiche ▾") + 46
        w_more = max(w_more, 175)

        # Priority order: if an individual category is selected, prioritize it to ensure visibility
        active_cat = self.active_category
        active_entry = next((c for c in self.category_counts if c[0] == active_cat), None)
        other_cats = [c for c in self.category_counts if c[0] != active_cat]

        if active_entry:
            candidate_order = [active_entry] + other_cats
        else:
            candidate_order = list(self.category_counts)

        # Determine visible chips and overflow
        space_for_chips = avail_w - w_all - w_more - 24
        visible_cats: List[Tuple[str, int]] = []
        overflow_cats: List[Tuple[str, int]] = []
        used_w = 0

        # Check if ALL candidates fit without needing a dropdown
        total_needed = sum(fm.horizontalAdvance(f"{c[0]}  •  {c[1]}") + 40 for c in candidate_order)
        if total_needed <= (avail_w - w_all - 16):
            visible_cats = list(candidate_order)
            overflow_cats = []
        else:
            for cat, count in candidate_order:
                chip_w = fm.horizontalAdvance(f"{cat}  •  {count}") + 32
                if visible_cats and (used_w + chip_w + 8 > space_for_chips):
                    overflow_cats.append((cat, count))
                else:
                    used_w += (chip_w + 8)
                    visible_cats.append((cat, count))

        # Check signature to avoid redundant widget recreation
        sig = (self.active_category, tuple(c[0] for c in visible_cats), len(overflow_cats))
        if sig == self._last_signature:
            self._update_chip_styles(overflow_cats)
            return
        self._last_signature = sig

        # Clear layout
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._buttons.clear()
        self.btn_more = None

        # 1. 'Alle' Chip
        btn_all = self._create_chip("Alle", f"Alle  •  {total_books}")
        btn_all.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.main_layout.addWidget(btn_all)
        self._buttons["Alle"] = btn_all

        # 2. Visible Category Chips
        for cat, count in visible_cats:
            btn = self._create_chip(cat, f"{cat}  •  {count}")
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.main_layout.addWidget(btn)
            self._buttons[cat] = btn

        # 3. 'Weitere Fachbereiche' Dropdown
        if overflow_cats:
            btn_more = QPushButton("  Weitere Fachbereiche ▾")
            btn_more.setIcon(create_vector_icon("plus", "#8B949E", 12))
            btn_more.setCursor(Qt.PointingHandCursor)
            btn_more.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            menu = QMenu(btn_more)
            menu.setStyleSheet("""
                QMenu {
                    background-color: #141C2E;
                    color: #F0F6FC;
                    border: 1px solid #324468;
                    border-radius: 8px;
                    padding: 6px 0px;
                }
                QMenu::item {
                    padding: 8px 22px;
                    font-size: 13px;
                }
                QMenu::item:selected {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                    color: #FFFFFF;
                }
            """)

            is_overflow_active = any(c[0] == self.active_category for c in overflow_cats)
            if is_overflow_active:
                act_cnt = next(c[1] for c in overflow_cats if c[0] == self.active_category)
                act_label = self.active_category.replace("&", "&&")
                btn_more.setText(f"  {act_label}  •  {act_cnt} ▾")
                btn_more.setIcon(create_vector_icon("check", "#FFFFFF", 12))

            for cat, count in overflow_cats:
                is_selected = (cat == self.active_category)
                prefix = "✓  " if is_selected else "    "
                cat_display = cat.replace("&", "&&")
                action = menu.addAction(f"{prefix}{cat_display} ({count})")
                action.triggered.connect(lambda checked=False, c=cat: self._on_chip_clicked(c))

            btn_more.setMenu(menu)
            self.main_layout.addWidget(btn_more)
            self.btn_more = btn_more
            self._buttons["_more_"] = btn_more

        self.main_layout.addStretch()
        self._update_chip_styles(overflow_cats)

    def _create_chip(self, category: str, label: str) -> QPushButton:
        btn = QPushButton(label.replace("&", "&&"))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._on_chip_clicked(category))
        return btn

    def _on_chip_clicked(self, category: str) -> None:
        self.active_category = category
        self._last_signature = None
        self._rebuild_chips()
        self.category_selected.emit(category)

    def set_active(self, category: str) -> None:
        self.active_category = category
        self._last_signature = None
        self._rebuild_chips()

    def _update_chip_styles(self, overflow_cats: Optional[List[Tuple[str, int]]] = None) -> None:
        if overflow_cats is None:
            overflow_cats = []

        is_overflow_active = any(c[0] == self.active_category for c in overflow_cats)

        for cat, btn in self._buttons.items():
            if cat == "_more_":
                if is_overflow_active:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #1F6FEB;
                            color: #FFFFFF;
                            border: 1px solid #388BFD;
                            border-radius: 14px;
                            padding: 5px 14px;
                            font-weight: bold;
                            outline: none;
                        }
                        QPushButton:hover {
                            background-color: #388BFD;
                        }
                    """)
                else:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #161B22;
                            color: #8B949E;
                            border: 1px solid #30363D;
                            border-radius: 14px;
                            padding: 5px 14px;
                            font-weight: 500;
                            outline: none;
                        }
                        QPushButton:hover {
                            color: #F0F6FC;
                            border-color: #58A6FF;
                            background-color: #21262D;
                        }
                    """)
                continue

            if cat == self.active_category:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1F6FEB;
                        color: #FFFFFF;
                        border: 1px solid #388BFD;
                        border-radius: 14px;
                        padding: 5px 14px;
                        font-weight: bold;
                        outline: none;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #161B22;
                        color: #8B949E;
                        border: 1px solid #30363D;
                        border-radius: 14px;
                        padding: 5px 14px;
                        font-weight: 500;
                        outline: none;
                    }
                    QPushButton:hover {
                        color: #F0F6FC;
                        border-color: #58A6FF;
                        background-color: #21262D;
                    }
                """)
