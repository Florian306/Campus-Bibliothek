"""Study Plan Configuration Modal Dialog for PySide6.
Allows students to set exam deadlines or daily reading quotas with adaptive pacing.
"""

import time
from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QDateEdit,
    QSpinBox,
    QRadioButton,
    QButtonGroup,
    QFrame,
)

from core.library_db import get_study_plan, save_study_plan, delete_study_plan
from ui.qt.icons import create_vector_icon, create_vector_pixmap


class StudyPlanDialog(QDialog):
    """Configuration dialog for setting dynamic study deadlines or page goals."""

    def __init__(self, book: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.book = book
        self.book_id = str(book.get("id", ""))
        self.book_title = book.get("title", "Fachbuch")

        self.setWindowTitle(f"Lernplan konfigurieren • {self.book_title}")
        self.resize(520, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #0E1422;
                border: 1px solid #232F48;
            }
        """)

        self._build_ui()
        self._load_existing()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        # Header
        h_row = QHBoxLayout()
        h_row.setSpacing(10)
        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_pixmap("notes", "#58A6FF", 22))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        h_row.addWidget(lbl_icon)

        t_box = QVBoxLayout()
        t_box.setSpacing(2)
        lbl_title = QLabel("Adaptiver Lernplan")
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none;")
        t_box.addWidget(lbl_title)

        lbl_sub = QLabel(self.book_title)
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #8B949E; border: none;")
        t_box.addWidget(lbl_sub)
        h_row.addLayout(t_box, stretch=1)
        layout.addLayout(h_row)

        # Card container
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(12)

        # Mode Selection
        lbl_mode_h = QLabel("<b>Wähle deinen Planungs-Typ:</b>")
        lbl_mode_h.setStyleSheet("color: #F0F6FC; border: none;")
        c_layout.addWidget(lbl_mode_h)

        self.group_mode = QButtonGroup(self)
        self.rb_deadline = QRadioButton("Prüfungs- & Deadline-Modus (berechnet Tagespensum)")
        self.rb_deadline.setStyleSheet("color: #F0F6FC; font-weight: 600; border: none;")
        self.rb_deadline.setChecked(True)
        self.group_mode.addButton(self.rb_deadline)
        c_layout.addWidget(self.rb_deadline)

        # Deadline date row
        self.row_date = QHBoxLayout()
        lbl_d = QLabel("  Prüfungstermin:")
        lbl_d.setStyleSheet("color: #8B949E; border: none;")
        self.row_date.addWidget(lbl_d)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate().addDays(30))
        self.date_edit.setStyleSheet("""
            QDateEdit {
                background-color: #0B0F19;
                color: #F0F6FC;
                border: 1px solid #304163;
                border-radius: 5px;
                padding: 4px 8px;
            }
        """)
        self.row_date.addWidget(self.date_edit, stretch=1)
        c_layout.addLayout(self.row_date)

        # Buffer days row
        self.row_buffer = QHBoxLayout()
        lbl_buf = QLabel("  Puffer- / Wiederholungstage vor Prüfung:")
        lbl_buf.setStyleSheet("color: #8B949E; border: none;")
        self.row_buffer.addWidget(lbl_buf)

        self.spin_buffer = QSpinBox()
        self.spin_buffer.setRange(0, 30)
        self.spin_buffer.setValue(3)
        self.spin_buffer.setStyleSheet("background-color: #0B0F19; color: #F0F6FC; border: 1px solid #304163; padding: 4px;")
        self.row_buffer.addWidget(self.spin_buffer)
        c_layout.addLayout(self.row_buffer)

        # Separator line
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #1F293D; border: none;")
        c_layout.addWidget(sep)

        self.rb_pace = QRadioButton("Feste tägliche Dosis (z. B. 15 Seiten/Tag)")
        self.rb_pace.setStyleSheet("color: #F0F6FC; font-weight: 600; border: none;")
        self.group_mode.addButton(self.rb_pace)
        c_layout.addWidget(self.rb_pace)

        self.row_pages = QHBoxLayout()
        lbl_p = QLabel("  Ziel-Seiten pro Tag:")
        lbl_p.setStyleSheet("color: #8B949E; border: none;")
        self.row_pages.addWidget(lbl_p)

        self.spin_pages = QSpinBox()
        self.spin_pages.setRange(1, 200)
        self.spin_pages.setValue(15)
        self.spin_pages.setStyleSheet("background-color: #0B0F19; color: #F0F6FC; border: 1px solid #304163; padding: 4px;")
        self.row_pages.addWidget(self.spin_pages)
        c_layout.addLayout(self.row_pages)

        layout.addWidget(card)

        # Bottom buttons
        btn_row = QHBoxLayout()
        self.btn_delete = QPushButton("Plan löschen")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setStyleSheet("background-color: #211317; color: #FF7B72; border: 1px solid #6E2229; border-radius: 5px; padding: 6px 12px;")
        self.btn_delete.clicked.connect(self._delete)
        self.btn_delete.setVisible(False)
        btn_row.addWidget(self.btn_delete)

        btn_row.addStretch()

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("Lernplan aktivieren")
        btn_save.setObjectName("primaryButton")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet("background: #1F6FEB; color: #FFFFFF; font-weight: bold; border-radius: 6px; padding: 6px 16px;")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _load_existing(self) -> None:
        plan = get_study_plan(self.book_id)
        if plan:
            self.btn_delete.setVisible(True)
            mode = plan.get("mode", "deadline")
            if mode == "pace":
                self.rb_pace.setChecked(True)
            else:
                self.rb_deadline.setChecked(True)

            target_ts = plan.get("target_date")
            if target_ts:
                t_struct = time.localtime(target_ts)
                self.date_edit.setDate(QDate(t_struct.tm_year, t_struct.tm_mon, t_struct.tm_mday))

            self.spin_buffer.setValue(plan.get("buffer_days", 3))
            self.spin_pages.setValue(plan.get("daily_pages_target", 15))

    def _save(self) -> None:
        mode = "pace" if self.rb_pace.isChecked() else "deadline"
        qdate = self.date_edit.date()
        target_ts = time.mktime((qdate.year(), qdate.month(), qdate.day(), 23, 59, 59, 0, 0, -1))
        daily_p = self.spin_pages.value()
        buffer_d = self.spin_buffer.value()

        save_study_plan(
            book_id=self.book_id,
            target_date=target_ts,
            daily_pages=daily_p,
            mode=mode,
            buffer_days=buffer_d
        )
        self.accept()

    def _delete(self) -> None:
        delete_study_plan(self.book_id)
        self.accept()
