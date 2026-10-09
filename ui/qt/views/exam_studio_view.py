"""Klausur-Studio & Prüfungssimulation View for Campus Library AI.
Provides full-featured timed exam simulations, active recall speed sprints,
Socratic oral examinations, 1-page formula & cheat sheet generation,
and comprehensive exam history analytics with GPA / Notenspiegel tracking.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, QTimer, QSize, Signal, QThread
from PySide6.QtGui import QFont, QColor, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QStackedWidget,
    QPlainTextEdit,
    QLineEdit,
    QSpinBox,
    QFrame,
    QScrollArea,
    QApplication,
    QComboBox,
    QButtonGroup,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDialog,
    QMessageBox,
    QSplitter,
    QCheckBox,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate
from ui.qt.latex_renderer import format_latex_html, clean_umlauts
from core.library_db import (
    open_pdf_in_edge,
    get_desk_books,
    get_all_books,
    get_all_research_papers,
    save_quiz_result,
    get_quiz_history,
    get_exam_statistics,
    delete_quiz_history_item,
    add_user_xp,
    get_gamification_profile,
    save_habit_study_plan,
    get_habit_study_plan,
)
from ai.tutor_engine import (
    extract_chapter_text,
    get_book_substantive_chapters,
    get_available_ai_models,
    generate_active_recall_quiz,
    generate_exam_simulation,
    generate_socratic_turn,
    generate_cheat_sheet,
)
from ai.study_planner import (
    analyze_text_complexity,
    generate_habit_study_plan,
    adapt_plan_for_missed_days,
)
from ai.worksheet_generator import (
    generate_worksheet_content,
    render_exercise_plot,
    build_worksheet_pdf,
)


class WorksheetWorkerThread(QThread):
    """Background worker for asynchronous didactic worksheet generation."""
    finished = Signal(dict)
    error_occurred = Signal(str)

    def __init__(
        self,
        title: str,
        chapter: str,
        text: str,
        start_page: int = 1,
        end_page: int = 20,
        difficulty: str = "standard",
        model_id: str = "",
        parent=None
    ):
        super().__init__(parent)
        self.title = title
        self.chapter = chapter
        self.text = text
        self.start_page = start_page
        self.end_page = end_page
        self.difficulty = difficulty
        self.model_id = model_id

    def run(self):
        try:
            res = generate_worksheet_content(
                self.title,
                self.chapter,
                self.text,
                start_page=self.start_page,
                end_page=self.end_page,
                difficulty=self.difficulty,
                model_id=self.model_id
            )
            self.finished.emit(res)
        except Exception as e:
            self.error_occurred.emit(str(e))



class ComplexityWorkerThread(QThread):
    """Background worker for text complexity and difficulty analysis."""
    finished = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, text: str, total_pages: int = 1, parent=None):
        super().__init__(parent)
        self.text = text
        self.total_pages = total_pages

    def run(self):
        try:
            res = analyze_text_complexity(self.text, self.total_pages)
            self.finished.emit(res)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ExamAiWorkerThread(QThread):
    """Background worker for asynchronous LLM synthesis (quiz, exam, cheat sheet)."""
    finished_quiz = Signal(dict)
    finished_exam = Signal(dict)
    finished_cheat_sheet = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, mode: str, title: str, chapter: str, text: str, model_id: str = "", duration_min: int = 30, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.title = title
        self.chapter = chapter
        self.text = text
        self.model_id = model_id
        self.duration_min = duration_min

    def run(self):
        try:
            if self.mode == "quiz":
                res = generate_active_recall_quiz(
                    self.title, self.chapter, self.text, num_questions=5, model_id=self.model_id
                )
                self.finished_quiz.emit(res)
            elif self.mode == "exam":
                res = generate_exam_simulation(
                    self.title, self.chapter, self.text, duration_minutes=self.duration_min, model_id=self.model_id
                )
                self.finished_exam.emit(res)
            elif self.mode == "cheat_sheet":
                res = generate_cheat_sheet(
                    self.title, self.chapter, self.text, model_id=self.model_id
                )
                self.finished_cheat_sheet.emit(res)
        except Exception as e:
            self.error_occurred.emit(str(e))


class SocraticWorkerThread(QThread):
    """Background worker for conversational turns with the Socratic Professor."""
    finished_turn = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, title: str, chapter: str, text: str, history: List[Dict[str, str]], model_id: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.chapter = chapter
        self.text = text
        self.history = history
        self.model_id = model_id

    def run(self):
        try:
            res = generate_socratic_turn(
                self.title, self.chapter, self.text, self.history, model_id=self.model_id
            )
            self.finished_turn.emit(res)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ExamArchiveDetailDialog(QDialog):
    """Modal displaying historical exam feedback, student answers, and master solutions."""
    def __init__(self, item: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Klausur-Gutachten • {item.get('source_title', 'Klausur')}")
        self.resize(780, 560)
        self.setStyleSheet("""
            QDialog {
                background-color: #0E1422;
                border: 1px solid #232F48;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Header card
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background-color: #141C2E;
                border: 1px solid #324468;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        hc_layout = QVBoxLayout(header_card)
        hc_layout.setContentsMargins(12, 10, 12, 10)
        hc_layout.setSpacing(4)

        title = item.get("source_title", "Unbekanntes Werk")
        chapter = item.get("chapter_title", "Allgemeiner Stoff")
        grade = item.get("grade", "—")
        score = item.get("score_percent", 0)
        mode = item.get("mode", "Klausur")
        date_str = time.strftime("%d.%m.%Y, %H:%M Uhr", time.localtime(item.get("created_at", time.time())))

        lbl_title = QLabel(f"🎓 {title}")
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none;")
        hc_layout.addWidget(lbl_title)

        lbl_sub = QLabel(f"Thema: {chapter}  •  Absolviert am: {date_str}  •  Modus: {mode}")
        lbl_sub.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        hc_layout.addWidget(lbl_sub)

        # Grade pill
        is_passed = score >= 50
        grade_pill = QLabel(f"Note: {grade}  ({score} %)")
        grade_pill.setFont(QFont("Segoe UI", 11, QFont.Bold))
        grade_pill.setStyleSheet(f"""
            background-color: {'#11261B' if is_passed else '#2A1217'};
            color: {'#3FB950' if is_passed else '#F85149'};
            border: 1px solid {'#232F48' if is_passed else '#DA3633'};
            border-radius: 6px;
            padding: 4px 10px;
        """)
        hc_layout.addWidget(grade_pill)
        layout.addWidget(header_card)

        # Scroll Area for Questions and Feedback
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 4, 0, 4)
        scroll_layout.setSpacing(10)

        raw_details = item.get("details_json", "")
        parsed = {}
        try:
            if raw_details:
                parsed = json.loads(raw_details)
        except Exception:
            parsed = {}

        if isinstance(parsed, dict) and "details" in parsed:
            for q_idx, detail in enumerate(parsed["details"]):
                correct = detail.get("correct", False)
                stat_col = "#3FB950" if correct else "#F85149"
                stat_icon = "✓ Richtig" if correct else "✕ Nicht korrekt"
                border_col = "#238636" if correct else "#DA3633"
                accent_pill_bg = "rgba(35, 134, 54, 0.15)" if correct else "rgba(218, 54, 51, 0.15)"

                q_card = QFrame()
                q_card.setStyleSheet(f"""
                    QFrame {{
                        background-color: #111726;
                        border: 1px solid #1E2D4A;
                        border-left: 4px solid {border_col};
                        border-radius: 8px;
                        padding: 4px;
                    }}
                """)
                qc_lay = QVBoxLayout(q_card)
                qc_lay.setContentsMargins(14, 10, 14, 12)
                qc_lay.setSpacing(8)

                # Header row
                hdr_row = QHBoxLayout()
                hdr_row.setSpacing(8)
                lbl_num = QLabel(f"AUFGABE {q_idx + 1}")
                lbl_num.setFont(QFont("Segoe UI", 9, QFont.Bold))
                lbl_num.setStyleSheet("color: #8B949E; border: none; letter-spacing: 0.5px;")
                hdr_row.addWidget(lbl_num)

                stat_pill = QLabel(f" {stat_icon} ")
                stat_pill.setFont(QFont("Segoe UI", 9, QFont.Bold))
                stat_pill.setStyleSheet(f"""
                    background-color: {accent_pill_bg};
                    color: {stat_col};
                    border: 1px solid {border_col};
                    border-radius: 4px;
                    padding: 2px 8px;
                """)
                hdr_row.addWidget(stat_pill)
                hdr_row.addStretch()
                qc_lay.addLayout(hdr_row)

                # Question text with LaTeX
                q_html = format_latex_html(detail.get('question', ''), text_color="#F0F6FC", math_color="#F0F6FC", font_size=11)
                lbl_q_txt = QLabel(q_html)
                lbl_q_txt.setTextFormat(Qt.RichText)
                lbl_q_txt.setWordWrap(True)
                lbl_q_txt.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
                lbl_q_txt.setStyleSheet("color: #F0F6FC; border: none; line-height: 1.4;")
                qc_lay.addWidget(lbl_q_txt)

                # Answer container
                ans_box = QFrame()
                ans_box.setStyleSheet(f"""
                    QFrame {{
                        background: {'rgba(35, 134, 54, 0.08)' if correct else 'rgba(218, 54, 51, 0.08)'};
                        border: 1px solid {'rgba(35, 134, 54, 0.3)' if correct else 'rgba(218, 54, 51, 0.3)'};
                        border-radius: 6px;
                    }}
                """)
                ans_lay = QVBoxLayout(ans_box)
                ans_lay.setContentsMargins(10, 8, 10, 8)
                ans_lay.setSpacing(5)

                u_html = format_latex_html(detail.get('user_answer', 'Keine'), text_color=stat_col, math_color=stat_col, font_size=11)
                lbl_user = QLabel(f"<b>Ihre Antwort:</b> {u_html}")
                lbl_user.setTextFormat(Qt.RichText)
                lbl_user.setWordWrap(True)
                lbl_user.setStyleSheet(f"color: {stat_col}; border: none; font-size: 11px;")
                ans_lay.addWidget(lbl_user)

                if not correct:
                    c_html = format_latex_html(detail.get('correct_answer', ''), text_color="#3FB950", math_color="#3FB950", font_size=11)
                    lbl_corr = QLabel(f"<b>Musterlösung:</b> {c_html}")
                    lbl_corr.setTextFormat(Qt.RichText)
                    lbl_corr.setWordWrap(True)
                    lbl_corr.setStyleSheet("color: #3FB950; border: none; font-size: 11px;")
                    ans_lay.addWidget(lbl_corr)

                qc_lay.addWidget(ans_box)

                if detail.get("explanation"):
                    expl_box = QFrame()
                    expl_box.setStyleSheet("""
                        QFrame {
                            background: rgba(31, 111, 235, 0.07);
                            border: 1px solid rgba(88, 166, 255, 0.22);
                            border-radius: 6px;
                        }
                    """)
                    expl_lay = QVBoxLayout(expl_box)
                    expl_lay.setContentsMargins(10, 8, 10, 8)
                    expl_lay.setSpacing(3)

                    lbl_expl_hdr = QLabel("💡 Fachliche Begründung & Herleitung:")
                    lbl_expl_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
                    lbl_expl_hdr.setStyleSheet("color: #58A6FF; border: none;")
                    expl_lay.addWidget(lbl_expl_hdr)

                    e_html = format_latex_html(detail.get('explanation', ''), text_color="#C9D1D9", math_color="#C9D1D9", font_size=10)
                    lbl_exp = QLabel(e_html)
                    lbl_exp.setTextFormat(Qt.RichText)
                    lbl_exp.setWordWrap(True)
                    lbl_exp.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none; line-height: 1.4;")
                    expl_lay.addWidget(lbl_exp)

                    qc_lay.addWidget(expl_box)

                scroll_layout.addWidget(q_card)
        elif isinstance(parsed, list):
            for q_idx, q in enumerate(parsed):
                q_card = QFrame()
                q_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 8px; padding: 10px;")
                qc_lay = QVBoxLayout(q_card)
                qc_lay.setSpacing(6)
                q_html = format_latex_html(q.get('question', ''), text_color="#F0F6FC", math_color="#58A6FF", font_size=11)
                lbl_q = QLabel(f"<b>Frage {q_idx+1}:</b> {q_html}")
                lbl_q.setTextFormat(Qt.RichText)
                lbl_q.setWordWrap(True)
                qc_lay.addWidget(lbl_q)
                c_idx = q.get("correct_index", 0)
                opts = q.get("options", [])
                ans_str = opts[c_idx] if 0 <= c_idx < len(opts) else ""
                c_html = format_latex_html(ans_str, text_color="#3FB950", math_color="#3FB950", font_size=11)
                lbl_sol = QLabel(f"<b>Musterlösung:</b> {c_html}")
                lbl_sol.setTextFormat(Qt.RichText)
                lbl_sol.setWordWrap(True)
                qc_lay.addWidget(lbl_sol)
                if q.get("explanation"):
                    e_html = format_latex_html(q.get('explanation', ''), text_color="#8B949E", math_color="#58A6FF", font_size=10)
                    lbl_exp = QLabel(f"<i>Erklärung:</i> {e_html}")
                    lbl_exp.setTextFormat(Qt.RichText)
                    lbl_exp.setWordWrap(True)
                    qc_lay.addWidget(lbl_exp)
                scroll_layout.addWidget(q_card)
        else:
            scroll_layout.addWidget(QLabel("Keine detaillierten Aufgabendaten archiviert."))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        # Close button
        btn_close = QPushButton("Schließen")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #388BFD;
            }
        """)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)


class ExamStudioView(QWidget):
    """Universal High-Performance Exam Preparation & Simulation Studio View."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_source_type = "desk"  # 'desk' (default), 'books', 'papers'
        self.available_desk_books: List[Dict[str, Any]] = []
        self.available_books: List[Dict[str, Any]] = []
        self.available_papers: List[Dict[str, Any]] = []
        self.selected_item: Optional[Dict[str, Any]] = None
        self.available_chapters: List[Dict[str, Any]] = []
        self.current_chapter_title = ""
        self.current_chapter_text = ""

        # Timed Exam State
        self.exam_worker: Optional[ExamAiWorkerThread] = None
        self.socratic_worker: Optional[SocraticWorkerThread] = None
        self.exam_timer = QTimer(self)
        self.exam_timer.setInterval(1000)
        self.exam_timer.timeout.connect(self._on_exam_timer_tick)
        self.exam_seconds_left = 0
        self.exam_total_seconds = 0
        self.exam_data: Dict[str, Any] = {}
        self.exam_user_answers: Dict[int, int] = {}

        # Speed Quiz State
        self.quiz_data: Dict[str, Any] = {}
        self.quiz_questions: List[Dict[str, Any]] = []
        self.quiz_current_idx = 0
        self.quiz_score = 0
        self.quiz_streak = 0

        # Socratic State
        self.socratic_history: List[Dict[str, str]] = []
        self.socratic_turn_count = 0

        # Habit Planner & Complexity State
        self.current_habit_plan: Optional[Dict[str, Any]] = None
        self.current_complexity: Optional[Dict[str, Any]] = None
        self._complexity_worker: Optional[ComplexityWorkerThread] = None

        # Worksheet Generator State
        self.current_worksheet_data: Optional[Dict[str, Any]] = None
        self.current_worksheet_plot_path: Optional[str] = None
        self.last_worksheet_pdf_path: Optional[str] = None
        self._worksheet_worker: Optional[WorksheetWorkerThread] = None

        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 16, 18, 16)
        root_layout.setSpacing(12)

        # -------------------------------------------------------------
        # 1. TOP HEADER & GAMIFICATION STATS HUD
        # -------------------------------------------------------------
        header_bar = QFrame()
        header_bar.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #121A2C, stop:1 #17223B);
                border: 1px solid #232F48;
                border-radius: 10px;
                padding: 10px 14px;
            }
        """)
        hb_layout = QHBoxLayout(header_bar)
        hb_layout.setContentsMargins(10, 6, 10, 6)
        hb_layout.setSpacing(16)

        # Title block
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_pixmap("exam", "#58A6FF", 22))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        top_row.addWidget(lbl_icon)

        lbl_title = QLabel("KLAUSUR-STUDIO & PRÜFUNGSSIMULATION")
        lbl_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; letter-spacing: 0.5px;")
        top_row.addWidget(lbl_title)

        badge_pro = QLabel("CAMPUS EXAM SUITE")
        badge_pro.setFont(QFont("Segoe UI", 8, QFont.Bold))
        badge_pro.setStyleSheet("""
            background: #1F6FEB;
            color: #FFFFFF;
            border-radius: 4px;
            padding: 2px 7px;
        """)
        top_row.addWidget(badge_pro)
        top_row.addStretch()
        title_box.addLayout(top_row)

        lbl_subtitle = QLabel("Klausursimulationen unter Realbedingungen • Active-Recall • Mündliche Prüfungen • Notenspiegel")
        lbl_subtitle.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        title_box.addWidget(lbl_subtitle)
        hb_layout.addLayout(title_box, stretch=1)

        # Gamification & Notenspiegel KPI Chips
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        # Rank & XP Card
        self.card_xp = QFrame()
        self.card_xp.setStyleSheet("""
            QFrame {
                background: #0B101D;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 4px 10px;
            }
        """)
        xp_lay = QVBoxLayout(self.card_xp)
        xp_lay.setContentsMargins(6, 4, 6, 4)
        xp_lay.setSpacing(3)
        self.lbl_rank = QLabel("🏆 Level 1 • Ersti")
        self.lbl_rank.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_rank.setStyleSheet("color: #E3B341; border: none;")
        xp_lay.addWidget(self.lbl_rank)

        self.bar_xp = QProgressBar()
        self.bar_xp.setFixedHeight(6)
        self.bar_xp.setRange(0, 100)
        self.bar_xp.setValue(35)
        self.bar_xp.setTextVisible(False)
        self.bar_xp.setStyleSheet("""
            QProgressBar {
                background-color: #1A243B;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3B341, stop:1 #F2CC60);
                border-radius: 3px;
            }
        """)
        xp_lay.addWidget(self.bar_xp)
        kpi_row.addWidget(self.card_xp)

        # GPA / Ø Note Chip
        self.card_gpa = QFrame()
        self.card_gpa.setStyleSheet("""
            QFrame {
                background: #0B101D;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 4px 10px;
            }
        """)
        gpa_lay = QVBoxLayout(self.card_gpa)
        gpa_lay.setContentsMargins(6, 4, 6, 4)
        gpa_lay.setSpacing(1)
        lbl_gpa_tit = QLabel("Ø NOTENSPIEGEL")
        lbl_gpa_tit.setStyleSheet("color: #8B949E; font-size: 8px; font-weight: bold; border: none;")
        gpa_lay.addWidget(lbl_gpa_tit)
        self.lbl_gpa_val = QLabel("1.8 (Gut)")
        self.lbl_gpa_val.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_gpa_val.setStyleSheet("color: #3FB950; border: none;")
        gpa_lay.addWidget(self.lbl_gpa_val)
        kpi_row.addWidget(self.card_gpa)

        # Streak Chip
        self.card_streak = QFrame()
        self.card_streak.setStyleSheet("""
            QFrame {
                background: #0B101D;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 4px 10px;
            }
        """)
        strk_lay = QVBoxLayout(self.card_streak)
        strk_lay.setContentsMargins(6, 4, 6, 4)
        strk_lay.setSpacing(1)
        lbl_strk_tit = QLabel("LERN-STREAK")
        lbl_strk_tit.setStyleSheet("color: #8B949E; font-size: 8px; font-weight: bold; border: none;")
        strk_lay.addWidget(lbl_strk_tit)
        self.lbl_streak_val = QLabel("🔥 1 Tag")
        self.lbl_streak_val.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_streak_val.setStyleSheet("color: #F0883E; border: none;")
        strk_lay.addWidget(self.lbl_streak_val)
        kpi_row.addWidget(self.card_streak)

        hb_layout.addLayout(kpi_row)
        root_layout.addWidget(header_bar)

        # -------------------------------------------------------------
        # 2. SOURCE CONTROL DECK (Lernstoff-Zentrale)
        # -------------------------------------------------------------
        source_deck = QFrame()
        source_deck.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 8px 12px;
            }
        """)
        sd_layout = QHBoxLayout(source_deck)
        sd_layout.setContentsMargins(10, 6, 10, 6)
        sd_layout.setSpacing(10)

        # Source Type Switcher Buttons (Compact segmented pills)
        self.btn_src_desk = QPushButton("🖥️ Schreibtisch")
        self.btn_src_desk.setCheckable(True)
        self.btn_src_desk.setChecked(True)
        self.btn_src_desk.setCursor(Qt.PointingHandCursor)
        self.btn_src_desk.setFixedHeight(30)
        self.btn_src_desk.setToolTip("Aktuell auf dem Schreibtisch liegende Werke")
        self.btn_src_desk.clicked.connect(lambda: self._set_source_type("desk"))

        self.btn_src_books = QPushButton("📚 Fachbücher")
        self.btn_src_books.setCheckable(True)
        self.btn_src_books.setCursor(Qt.PointingHandCursor)
        self.btn_src_books.setFixedHeight(30)
        self.btn_src_books.setToolTip("Gesamte Fachbibliothek mit allen Lehrbüchern")
        self.btn_src_books.clicked.connect(lambda: self._set_source_type("books"))

        self.btn_src_papers = QPushButton("📄 Paper & Studien")
        self.btn_src_papers.setCheckable(True)
        self.btn_src_papers.setCursor(Qt.PointingHandCursor)
        self.btn_src_papers.setFixedHeight(30)
        self.btn_src_papers.setToolTip("Gespeicherte wissenschaftliche Paper & Forschungsartikel")
        self.btn_src_papers.clicked.connect(lambda: self._set_source_type("papers"))

        sd_layout.addWidget(self.btn_src_desk)
        sd_layout.addWidget(self.btn_src_books)
        sd_layout.addWidget(self.btn_src_papers)
        self._update_source_type_buttons()

        # Separator line
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("background-color: #232F48; max-width: 1px; margin: 4px 2px;")
        sd_layout.addWidget(sep1)

        # Source Selection Dropdown (Books / Desk / Papers)
        self.combo_source = QComboBox()
        self.combo_source.setFixedHeight(30)
        self.combo_source.setMinimumWidth(220)
        self.combo_source.setStyleSheet("""
            QComboBox {
                background-color: #0B0F19;
                border: 1px solid #324468;
                border-radius: 6px;
                color: #F0F6FC;
                padding: 3px 10px;
                font-size: 12px;
            }
            QComboBox:hover {
                border-color: #58A6FF;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #141C2E;
                color: #F0F6FC;
                selection-background-color: #1F6FEB;
                border: 1px solid #324468;
                padding: 4px;
            }
        """)
        self.combo_source.currentIndexChanged.connect(self._on_source_item_changed)
        sd_layout.addWidget(self.combo_source, stretch=4)

        # Chapter / Section Dropdown
        self.combo_chapter = QComboBox()
        self.combo_chapter.setFixedHeight(30)
        self.combo_chapter.setMinimumWidth(180)
        self.combo_chapter.setStyleSheet(self.combo_source.styleSheet())
        self.combo_chapter.currentIndexChanged.connect(self._on_chapter_changed)
        sd_layout.addWidget(self.combo_chapter, stretch=3)

        # In Edge öffnen Button
        self.btn_edge_open = QPushButton("  In Edge")
        self.btn_edge_open.setIcon(create_vector_icon("external", "#58A6FF", 14))
        self.btn_edge_open.setCursor(Qt.PointingHandCursor)
        self.btn_edge_open.setFixedHeight(30)
        self.btn_edge_open.setToolTip("Öffnet das Fachbuch direkt an der gewählten Startseite in Microsoft Edge")
        self.btn_edge_open.setStyleSheet("""
            QPushButton {
                background-color: #142036;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 6px;
                padding: 4px 10px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1F6FEB;
                color: #FFFFFF;
            }
        """)
        self.btn_edge_open.clicked.connect(self._open_current_in_edge)
        sd_layout.addWidget(self.btn_edge_open)

        # AI Model Selector
        self.combo_ai_model = QComboBox()
        self.combo_ai_model.setFixedHeight(30)
        self.combo_ai_model.setFixedWidth(175)
        self.combo_ai_model.setStyleSheet(self.combo_source.styleSheet())
        sd_layout.addWidget(self.combo_ai_model)

        root_layout.addWidget(source_deck)

        # -------------------------------------------------------------
        # 3. SUB-NAVIGATION TABS & SCOPE DECK (ROW 2)
        # -------------------------------------------------------------
        nav_tab_bar = QFrame()
        nav_tab_bar.setStyleSheet("""
            QFrame {
                background-color: #0E1422;
                border-bottom: 2px solid #232F48;
                padding-bottom: 2px;
            }
        """)
        ntb_layout = QHBoxLayout(nav_tab_bar)
        ntb_layout.setContentsMargins(4, 0, 4, 4)
        ntb_layout.setSpacing(6)

        self.mode_buttons = {}
        modes = [
            ("planner", "notes", "📅  Lern- & Rhythmusplaner", 0),
            ("worksheet", "book", "📄  Arbeitsblatt-Studio", 1),
            ("exam", "exam", "📝  Klausursimulation", 2),
            ("quiz", "sync", "⚡  Active-Recall Sprint", 3),
            ("socratic", "institution", "🎙️  Mündliche Prüfung", 4),
            ("cheat_sheet", "notes", "📑  1-Page Spickzettel", 5),
            ("archive", "history", "📊  Notenspiegel & Historie", 6),
        ]
        self.mode_indices = {k: idx for k, _, _, idx in modes}

        for key, icon_n, label, idx in modes:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(36)
            btn.clicked.connect(lambda checked, i=idx, k=key: self._switch_mode_tab(k, i))
            ntb_layout.addWidget(btn)
            self.mode_buttons[key] = btn

        ntb_layout.addStretch()

        # Integrated Scope Control on the right of the tab bar
        scope_box = QFrame()
        scope_box.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 2px 6px;
            }
        """)
        scope_lay = QHBoxLayout(scope_box)
        scope_lay.setContentsMargins(6, 2, 6, 2)
        scope_lay.setSpacing(8)

        lbl_p_from = QLabel("Stoff: S.")
        lbl_p_from.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 600; border: none;")
        scope_lay.addWidget(lbl_p_from)

        spin_style = """
            QSpinBox {
                background-color: #0B0F19;
                border: 1px solid #324468;
                border-radius: 5px;
                color: #F0F6FC;
                padding-left: 6px;
                padding-right: 20px;
                font-weight: 700;
                font-size: 11px;
            }
            QSpinBox:focus {
                border-color: #1F6FEB;
                background-color: #0E1626;
            }
            QSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 17px;
                border-left: 1px solid #232F48;
                border-bottom: 1px solid #232F48;
                background-color: #141C2E;
                border-top-right-radius: 4px;
            }
            QSpinBox::up-button:hover {
                background-color: #1F6FEB;
            }
            QSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 17px;
                border-left: 1px solid #232F48;
                background-color: #141C2E;
                border-bottom-right-radius: 4px;
            }
            QSpinBox::down-button:hover {
                background-color: #1F6FEB;
            }
        """

        self.spin_page_start = QSpinBox()
        self.spin_page_start.setRange(1, 9999)
        self.spin_page_start.setValue(1)
        self.spin_page_start.setFixedHeight(28)
        self.spin_page_start.setFixedWidth(72)
        self.spin_page_start.setAlignment(Qt.AlignCenter)
        self.spin_page_start.setStyleSheet(spin_style)
        self.spin_page_start.valueChanged.connect(self._on_page_spin_changed)
        scope_lay.addWidget(self.spin_page_start)

        lbl_p_to = QLabel("bis")
        lbl_p_to.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 600; border: none;")
        scope_lay.addWidget(lbl_p_to)

        self.spin_page_end = QSpinBox()
        self.spin_page_end.setRange(1, 9999)
        self.spin_page_end.setValue(25)
        self.spin_page_end.setFixedHeight(28)
        self.spin_page_end.setFixedWidth(72)
        self.spin_page_end.setAlignment(Qt.AlignCenter)
        self.spin_page_end.setStyleSheet(spin_style)
        self.spin_page_end.valueChanged.connect(self._on_page_spin_changed)
        scope_lay.addWidget(self.spin_page_end)

        self.lbl_selected_scope = QLabel("📄 25 Seiten Stoff")
        self.lbl_selected_scope.setStyleSheet("""
            QLabel {
                background-color: #141F32;
                color: #58A6FF;
                border: 1px solid #1F6FEB;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        scope_lay.addWidget(self.lbl_selected_scope)

        ntb_layout.addWidget(scope_box)
        root_layout.addWidget(nav_tab_bar)

        # -------------------------------------------------------------
        # 4. CENTRAL STACKED WIDGET FOR THE 5 MODES
        # -------------------------------------------------------------
        self.mode_stack = QStackedWidget()
        self.mode_stack.setStyleSheet("background: transparent;")

        self.page_planner = self._build_planner_page()
        self.page_worksheet = self._build_worksheet_page()
        self.page_exam = self._build_exam_simulator_page()
        self.page_quiz = self._build_active_recall_page()
        self.page_socratic = self._build_socratic_page()
        self.page_cheat = self._build_cheat_sheet_page()
        self.page_archive = self._build_archive_page()

        self.mode_stack.addWidget(self.page_planner)
        self.mode_stack.addWidget(self.page_worksheet)
        self.mode_stack.addWidget(self.page_exam)
        self.mode_stack.addWidget(self.page_quiz)
        self.mode_stack.addWidget(self.page_socratic)
        self.mode_stack.addWidget(self.page_cheat)
        self.mode_stack.addWidget(self.page_archive)

        root_layout.addWidget(self.mode_stack, stretch=1)

        # Initial Tab Selection
        self._switch_mode_tab("planner", 0)

        # Populate AI models
        self._populate_ai_models()

    def _update_source_type_buttons(self) -> None:
        active_css = """
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: bold;
                font-size: 11px;
            }
        """
        inactive_css = """
            QPushButton {
                background: #141C2E;
                color: #8B949E;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1B253D;
                color: #F0F6FC;
            }
        """
        if self.active_source_type == "desk":
            self.btn_src_desk.setStyleSheet(active_css)
            self.btn_src_books.setStyleSheet(inactive_css)
            self.btn_src_papers.setStyleSheet(inactive_css)
        elif self.active_source_type == "books":
            self.btn_src_desk.setStyleSheet(inactive_css)
            self.btn_src_books.setStyleSheet(active_css)
            self.btn_src_papers.setStyleSheet(inactive_css)
        else:
            self.btn_src_desk.setStyleSheet(inactive_css)
            self.btn_src_books.setStyleSheet(inactive_css)
            self.btn_src_papers.setStyleSheet(active_css)

    def _set_source_type(self, src_type: str) -> None:
        self.active_source_type = src_type
        self.btn_src_desk.setChecked(src_type == "desk")
        self.btn_src_books.setChecked(src_type == "books")
        self.btn_src_papers.setChecked(src_type == "papers")
        self._update_source_type_buttons()
        self._populate_source_dropdown()

    def _switch_mode_tab(self, key: str, idx: Optional[int] = None) -> None:
        target_idx = self.mode_indices.get(key, idx if idx is not None else 0)
        self.mode_stack.setCurrentIndex(target_idx)
        for k, btn in self.mode_buttons.items():
            if k == key:
                btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1F6FEB, stop:1 #174EB8);
                        color: #FFFFFF;
                        border: 1px solid #388BFD;
                        border-radius: 6px;
                        font-weight: bold;
                        padding: 6px 14px;
                        font-size: 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #8B949E;
                        border: 1px solid transparent;
                        border-radius: 6px;
                        font-weight: 600;
                        padding: 6px 14px;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background-color: #141C2E;
                        color: #F0F6FC;
                    }
                """)

        if key == "archive":
            self._load_archive_data()

    # -----------------------------------------------------------------
    # DATA LOADING & INITIALIZATION
    # -----------------------------------------------------------------
    def load_data(self) -> None:
        """Called whenever the Klausur-Studio view is activated in CampusMainWindow."""
        try:
            self.available_desk_books = get_desk_books()
            self.available_books = get_all_books()
            self.available_papers = get_all_research_papers()
        except Exception:
            self.available_desk_books = []
            self.available_books = []
            self.available_papers = []

        self._populate_source_dropdown()
        self._update_gamification_hud()
        self._load_archive_data()

    def _populate_ai_models(self) -> None:
        self.combo_ai_model.clear()
        models = get_available_ai_models()
        if not models:
            self.combo_ai_model.addItem("Ollama (Lokal)", "ollama")
            return
        for m in models:
            self.combo_ai_model.addItem(m.get("name", "Modell"), m.get("id", ""))

    def _populate_source_dropdown(self) -> None:
        self.combo_source.blockSignals(True)
        self.combo_source.clear()

        if self.active_source_type == "desk":
            if not self.available_desk_books:
                self.combo_source.addItem("⚠️ Schreibtisch ist leer (Bücher unter 'Mein Schreibtisch' ablegen)", None)
            else:
                for b in self.available_desk_books:
                    title = b.get("title", "Unbekannter Titel")
                    p_curr = max(1, int(b.get("current_page") or 1))
                    p_tot = b.get("total_pages") or b.get("page_count") or "?"
                    label = f"🖥️ {title[:48]}  [Aktuell S. {p_curr} / {p_tot}]"
                    self.combo_source.addItem(label, b)
        elif self.active_source_type == "books":
            if not self.available_books:
                self.combo_source.addItem("Keine Lehrbücher in der Bibliothek vorhanden", None)
            else:
                for b in self.available_books:
                    title = b.get("title", "Unbekannter Titel")
                    author = b.get("author", "")
                    label = f"📚 {title[:55]}" + (f" ({author[:25]})" if author else "")
                    self.combo_source.addItem(label, b)
        else:
            if not self.available_papers:
                self.combo_source.addItem("Keine archivierten Paper vorhanden", None)
            else:
                for p in self.available_papers:
                    title = p.get("title", "Unbekanntes Paper")
                    year = p.get("year", "")
                    label = f"📄 {title[:55]}" + (f" [{year}]" if year else "")
                    self.combo_source.addItem(label, p)

        self.combo_source.blockSignals(False)
        self._on_source_item_changed(0)

    def _on_source_item_changed(self, idx: int) -> None:
        item = self.combo_source.itemData(idx) if idx >= 0 else self.combo_source.currentData()
        if not item:
            item = self.combo_source.currentData()
        self.selected_item = item
        self.combo_source.setToolTip(self.combo_source.currentText())
        if not item:
            self.combo_chapter.clear()
            self.combo_chapter.addItem("Kein Werk ausgewählt", None)
            return

        fp = item.get("file_path") or item.get("local_path") or ""
        total_p = max(1, int(item.get("page_count") or item.get("total_pages") or 50))
        curr_p = max(1, min(total_p, int(item.get("current_page") or 1)))

        self.spin_page_start.blockSignals(True)
        self.spin_page_end.blockSignals(True)
        self.spin_page_start.setRange(1, total_p)
        self.spin_page_end.setRange(1, total_p)
        self.spin_page_start.blockSignals(False)
        self.spin_page_end.blockSignals(False)

        self.combo_chapter.blockSignals(True)
        self.combo_chapter.clear()

        # Parse substantive chapters from TOC
        chapters = []
        if fp and os.path.exists(fp):
            try:
                chapters = get_book_substantive_chapters(fp)
            except Exception:
                chapters = []

        # 1. Option: Always include current desk reading position
        reading_end = min(total_p, curr_p + 20)
        self.combo_chapter.addItem(
            f"📍 Aktuelle Leseposition (S. {curr_p}–{reading_end})",
            {"title": f"Aktuelle Leseposition (S. {curr_p}-{reading_end})", "start_page": curr_p, "end_page": reading_end}
        )

        # 2. Add substantive chapters from PDF
        if chapters:
            self.available_chapters = chapters
            for ch in chapters:
                self.combo_chapter.addItem(f"📖 {ch['display']}", ch)
        else:
            # Fallback sections
            self.available_chapters = []
            if self.active_source_type in ("books", "desk"):
                self.combo_chapter.addItem(f"📖 Gesamtwerk / Repetitorium (S. 1–{min(total_p, 40)})", {
                    "title": "Repetitorium", "start_page": 1, "end_page": min(total_p, 40)
                })
            else:
                self.combo_chapter.addItem(f"📄 Paper-Volltext (S. 1–{min(total_p, 20)})", {
                    "title": "Paper-Volltext", "start_page": 1, "end_page": min(total_p, 20)
                })

        # 3. Add custom page range item
        self.combo_chapter.addItem("🎯 Eigener Seitenbereich (unten anpassen)", {
            "title": f"Benutzerdefinierter Bereich (S. {curr_p}-{reading_end})",
            "start_page": curr_p,
            "end_page": reading_end,
            "is_custom": True
        })

        self.combo_chapter.blockSignals(False)
        self._on_chapter_changed(0)
        self._load_planner_for_current_book()
        self._update_worksheet_scope_label()

    def _on_chapter_changed(self, idx: int) -> None:
        data = self.combo_chapter.itemData(idx) if idx >= 0 else self.combo_chapter.currentData()
        if not data:
            data = self.combo_chapter.currentData()
        if not data:
            return
        sp = data.get("start_page", 1)
        ep = data.get("end_page", sp + 20)

        self.spin_page_start.blockSignals(True)
        self.spin_page_end.blockSignals(True)
        self.spin_page_start.setValue(sp)
        self.spin_page_end.setValue(ep)
        self.spin_page_start.blockSignals(False)
        self.spin_page_end.blockSignals(False)

        self.current_chapter_title = data.get("title", "Klausurstoff")
        self.combo_chapter.setToolTip(self.combo_chapter.currentText())
        self._update_scope_badge()
        self._update_worksheet_scope_label()

    def _on_page_spin_changed(self) -> None:
        sp = self.spin_page_start.value()
        ep = self.spin_page_end.value()
        if sp > ep:
            self.spin_page_end.blockSignals(True)
            self.spin_page_end.setValue(sp)
            self.spin_page_end.blockSignals(False)
            ep = sp

        ch_data = self.combo_chapter.currentData()
        if ch_data and (sp != ch_data.get("start_page") or ep != ch_data.get("end_page")):
            self.current_chapter_title = f"Seitenbereich (S. {sp}–{ep})"

        self._update_scope_badge()
        self._update_worksheet_scope_label()

    def _update_scope_badge(self) -> None:
        sp = self.spin_page_start.value()
        ep = self.spin_page_end.value()
        count = max(1, ep - sp + 1)
        self.lbl_selected_scope.setText(f"📄 {count} {'Seite' if count == 1 else 'Seiten'} Prüfungsstoff (S. {sp}–{ep})")

    def _open_current_in_edge(self) -> None:
        if not self.selected_item:
            return
        fp = self.selected_item.get("file_path") or self.selected_item.get("local_path") or ""
        sp = self.spin_page_start.value()
        if fp and os.path.exists(fp):
            open_pdf_in_edge(fp, sp)
        elif self.selected_item.get("pdf_url"):
            open_pdf_in_edge(self.selected_item.get("pdf_url"), 1)

    def _update_gamification_hud(self) -> None:
        prof = get_gamification_profile()
        stats = get_exam_statistics()

        lvl = prof.get("level", 1)
        title = prof.get("title", "Ersti")
        streak = prof.get("current_streak", 0)
        pct = prof.get("progress_pct", 0)

        self.lbl_rank.setText(f"🏆 Level {lvl} • {title}")
        self.bar_xp.setValue(pct)
        self.lbl_streak_val.setText(f"🔥 {streak} {'Tag' if streak == 1 else 'Tage'}")

        gpa = stats.get("gpa", 0.0)
        if gpa > 0:
            self.lbl_gpa_val.setText(f"Ø {gpa:.1f}")
            self.lbl_gpa_val.setStyleSheet("color: #3FB950; font-weight: bold; border: none;")
        else:
            self.lbl_gpa_val.setText("— (Keine Note)")
            self.lbl_gpa_val.setStyleSheet("color: #8B949E; border: none;")

    def _extract_active_text(self) -> str:
        if not self.selected_item:
            return ""
        fp = self.selected_item.get("file_path") or self.selected_item.get("local_path") or ""
        sp = self.spin_page_start.value()
        ep = self.spin_page_end.value()
        text = extract_chapter_text(fp, sp, ep, max_chars=14000)
        if not text and self.selected_item.get("abstract"):
            text = f"Titel: {self.selected_item.get('title')}\nAbstract:\n{self.selected_item.get('abstract')}"
        return text

    # =================================================================
    # PAGE 0: 📅 LERN- & RHYTHMUSPLANER (HABIT-ORIENTIERTES SELBSTSTUDIUM)
    # =================================================================
    def _build_planner_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        # 1. TOP CARDS DECK (Komplexität, Rhythmus-Ziele, Adaptiver Puffer)
        deck_cards = QHBoxLayout()
        deck_cards.setSpacing(10)

        # Card 1: Text-Komplexität & Lesetempo
        card_comp = QFrame()
        card_comp.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        c_lay = QVBoxLayout(card_comp)
        c_lay.setSpacing(6)

        lbl_c_head = QLabel("🔍 Text-Komplexitätsanalyse")
        lbl_c_head.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_c_head.setStyleSheet("color: #58A6FF; border: none;")
        c_lay.addWidget(lbl_c_head)

        self.lbl_plan_complexity_badge = QLabel("Score: — / 5.0")
        self.lbl_plan_complexity_badge.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_plan_complexity_badge.setStyleSheet("color: #F0F6FC; border: none;")
        c_lay.addWidget(self.lbl_plan_complexity_badge)

        self.lbl_plan_pace = QLabel("Geschätztes Tempo: ~3.5 Min. / Seite")
        self.lbl_plan_pace.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        c_lay.addWidget(self.lbl_plan_pace)

        self.lbl_plan_metrics = QLabel("Flesch: — · Fachwörter: — · Formeln: —")
        self.lbl_plan_metrics.setStyleSheet("color: #6E7681; font-size: 10px; border: none;")
        c_lay.addWidget(self.lbl_plan_metrics)

        c_lay.addStretch()

        self.btn_plan_analyze = QPushButton("  🔍 Text analysieren")
        self.btn_plan_analyze.setCursor(Qt.PointingHandCursor)
        self.btn_plan_analyze.setStyleSheet("""
            QPushButton {
                background-color: #162035;
                color: #C9D1D9;
                border: 1px solid #2D3E63;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #1F2D48; border-color: #58A6FF; color: #FFFFFF; }
        """)
        self.btn_plan_analyze.clicked.connect(self._run_complexity_analysis)
        c_lay.addWidget(self.btn_plan_analyze)
        deck_cards.addWidget(card_comp, stretch=1)

        # Card 2: Privater Lernrhythmus (Kein Deadlinestress)
        card_rhythm = QFrame()
        card_rhythm.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        r_lay = QVBoxLayout(card_rhythm)
        r_lay.setSpacing(6)

        lbl_r_head = QLabel("📅 Privater Lernrhythmus")
        lbl_r_head.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_r_head.setStyleSheet("color: #3FB950; border: none;")
        r_lay.addWidget(lbl_r_head)

        lbl_r_sub = QLabel("Kontinuierliches Selbststudium • Jeden Tag etwas machen")
        lbl_r_sub.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        r_lay.addWidget(lbl_r_sub)

        min_box = QHBoxLayout()
        min_box.setSpacing(8)
        lbl_min = QLabel("Tägliche Lesezeit:")
        lbl_min.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none;")
        min_box.addWidget(lbl_min)

        self.spin_daily_min = QSpinBox()
        self.spin_daily_min.setRange(5, 180)
        self.spin_daily_min.setSingleStep(5)
        self.spin_daily_min.setValue(20)
        self.spin_daily_min.setSuffix(" Min.")
        self.spin_daily_min.setStyleSheet("""
            QSpinBox {
                background-color: #0B0F19;
                border: 1px solid #28395A;
                border-radius: 5px;
                color: #F0F6FC;
                padding: 3px 8px;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        min_box.addWidget(self.spin_daily_min)
        min_box.addStretch()
        r_lay.addLayout(min_box)

        self.chk_buffer_weekend = QPushButton("✓ Wochenenden als Pufferpause freihalten")
        self.chk_buffer_weekend.setCheckable(True)
        self.chk_buffer_weekend.setChecked(True)
        self.chk_buffer_weekend.setCursor(Qt.PointingHandCursor)
        self.chk_buffer_weekend.setStyleSheet("""
            QPushButton {
                background-color: #0E1626;
                color: #8B949E;
                border: 1px solid #1E2E4E;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 10px;
                text-align: left;
            }
            QPushButton:checked {
                background-color: #132438;
                color: #58A6FF;
                border-color: #1F6FEB;
                font-weight: bold;
            }
        """)
        r_lay.addWidget(self.chk_buffer_weekend)

        r_lay.addStretch()

        self.btn_generate_habit_plan = QPushButton("⚡ Rhythmusplan generieren")
        self.btn_generate_habit_plan.setCursor(Qt.PointingHandCursor)
        self.btn_generate_habit_plan.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1F6FEB, stop:1 #174EB8);
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background: #388BFD; }
        """)
        self.btn_generate_habit_plan.clicked.connect(self._generate_habit_plan)
        r_lay.addWidget(self.btn_generate_habit_plan)
        deck_cards.addWidget(card_rhythm, stretch=1)

        # Card 3: Adaptiver Puffer & Prokrastinations-Hilfe
        card_adapt = QFrame()
        card_adapt.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        a_lay = QVBoxLayout(card_adapt)
        a_lay.setSpacing(6)

        lbl_a_head = QLabel("🛌 Adaptiver Puffer & Pause")
        lbl_a_head.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_a_head.setStyleSheet("color: #E3B341; border: none;")
        a_lay.addWidget(lbl_a_head)

        lbl_a_sub = QLabel("Tag verpasst? Kein Problem – passe den Plan flexibel an:")
        lbl_a_sub.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        lbl_a_sub.setWordWrap(True)
        a_lay.addWidget(lbl_a_sub)

        act_box = QHBoxLayout()
        act_box.setSpacing(6)

        self.btn_shift_plan = QPushButton("🛌 1 Tag pausiert")
        self.btn_shift_plan.setToolTip("Elastic Shift: Verschiebt Folgetage nach hinten, ohne das tägliche Pensum zu erhöhen.")
        self.btn_shift_plan.setCursor(Qt.PointingHandCursor)
        self.btn_shift_plan.setStyleSheet("""
            QPushButton {
                background-color: #211B14;
                color: #F0883E;
                border: 1px solid #6E4413;
                border-radius: 5px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #382715; border-color: #F0883E; }
        """)
        self.btn_shift_plan.clicked.connect(self._shift_plan_missed_day)
        act_box.addWidget(self.btn_shift_plan)

        self.btn_catchup_plan = QPushButton("⚖️ Sanft aufholen")
        self.btn_catchup_plan.setToolTip("Verteilt noch nicht gelesene Seiten gleichmäßig auf verbleibende Einheiten.")
        self.btn_catchup_plan.setCursor(Qt.PointingHandCursor)
        self.btn_catchup_plan.setStyleSheet("""
            QPushButton {
                background-color: #14241B;
                color: #3FB950;
                border: 1px solid #1B4728;
                border-radius: 5px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #1C3B29; border-color: #3FB950; }
        """)
        self.btn_catchup_plan.clicked.connect(self._catch_up_plan)
        act_box.addWidget(self.btn_catchup_plan)
        a_lay.addLayout(act_box)

        self.lbl_plan_overview = QLabel("Noch kein Rhythmusplan für dieses Buch erstellt.")
        self.lbl_plan_overview.setStyleSheet("color: #6E7681; font-size: 10px; border: none;")
        self.lbl_plan_overview.setWordWrap(True)
        a_lay.addWidget(self.lbl_plan_overview)

        a_lay.addStretch()
        deck_cards.addWidget(card_adapt, stretch=1)
        layout.addLayout(deck_cards)

        # 2. SESSIONS TIMETABLE
        table_card = QFrame()
        table_card.setStyleSheet("""
            QFrame {
                background-color: #0E1422;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        t_lay = QVBoxLayout(table_card)
        t_lay.setContentsMargins(10, 10, 10, 10)
        t_lay.setSpacing(8)

        t_head_box = QHBoxLayout()
        self.lbl_plan_table_header = QLabel("📅 TÄGLICHE LERNEINHEITEN & FORTSCHRITT")
        self.lbl_plan_table_header.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_plan_table_header.setStyleSheet("color: #F0F6FC; border: none;")
        t_head_box.addWidget(self.lbl_plan_table_header)
        t_head_box.addStretch()

        lbl_hint = QLabel("💡 Doppelklick auf eine Zeile schlägt das Buch an dieser Seite im Viewer auf")
        lbl_hint.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        t_head_box.addWidget(lbl_hint)
        t_lay.addLayout(t_head_box)

        self.table_planner_sessions = QTableWidget()
        self.table_planner_sessions.setColumnCount(7)
        self.table_planner_sessions.setHorizontalHeaderLabels([
            "Einheit", "Datum", "Wochentag", "Seitenbereich", "Dauer", "Fokus / Thema", "Status / Aktion"
        ])
        self.table_planner_sessions.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_planner_sessions.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_planner_sessions.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_planner_sessions.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_planner_sessions.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_planner_sessions.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table_planner_sessions.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table_planner_sessions.verticalHeader().setVisible(False)
        self.table_planner_sessions.setAlternatingRowColors(True)
        self.table_planner_sessions.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_planner_sessions.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_planner_sessions.setItemDelegate(NoFocusItemDelegate(self.table_planner_sessions))
        self.table_planner_sessions.setStyleSheet("""
            QTableWidget {
                background-color: #0B0F19;
                alternate-background-color: #111726;
                gridline-color: #1A2438;
                border: 1px solid #1F2D48;
                border-radius: 6px;
                color: #C9D1D9;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #141C2E;
                color: #8B949E;
                border: none;
                border-bottom: 1px solid #232F48;
                padding: 6px 8px;
                font-weight: 600;
                font-size: 11px;
            }
            QTableWidget::item:selected {
                background-color: #1F3660;
                color: #FFFFFF;
            }
        """)
        self.table_planner_sessions.cellDoubleClicked.connect(self._on_planner_row_double_clicked)
        t_lay.addWidget(self.table_planner_sessions)
        layout.addWidget(table_card, stretch=1)

        return container

    def _run_complexity_analysis(self) -> None:
        """Triggers asynchronous analysis of reading difficulty and pace."""
        text = self._extract_active_text()
        if not text:
            self.lbl_plan_complexity_badge.setText("⚠️ Kein Text verfügbar")
            return

        self.btn_plan_analyze.setEnabled(False)
        self.btn_plan_analyze.setText("  ⏳ Analysiere...")
        tot_p = max(1, self.spin_page_end.value() - self.spin_page_start.value() + 1)

        self._complexity_worker = ComplexityWorkerThread(text, total_pages=tot_p, parent=self)
        self._complexity_worker.finished.connect(self._on_complexity_analyzed)
        self._complexity_worker.error_occurred.connect(self._on_complexity_error)
        self._complexity_worker.start()

    def _on_complexity_analyzed(self, res: Dict[str, Any]) -> None:
        self.current_complexity = res
        self.btn_plan_analyze.setEnabled(True)
        self.btn_plan_analyze.setText("  🔍 Text analysieren")

        score = res.get("score", 3.0)
        lvl = res.get("level", "Mittelschwer")
        color = "#3FB950" if score <= 2.2 else ("#58A6FF" if score <= 3.3 else ("#E3B341" if score <= 4.2 else "#F85149"))
        self.lbl_plan_complexity_badge.setText(f"Score: {score:.1f} / 5.0 • {lvl}")
        self.lbl_plan_complexity_badge.setStyleSheet(f"color: {color}; font-weight: bold; border: none;")

        pace = res.get("min_per_page", 3.5)
        self.lbl_plan_pace.setText(f"Geschätztes Tempo: ~{pace:.1f} Min. / Seite")

        flesch = res.get("flesch_de", 50.0)
        term_d = res.get("term_density", "Mittel")
        form_d = res.get("formula_density", "Gering")
        self.lbl_plan_metrics.setText(f"Flesch-DE: {flesch:.0f} · Fachwörter: {term_d} · Formeln: {form_d}")

    def _on_complexity_error(self, err: str) -> None:
        self.btn_plan_analyze.setEnabled(True)
        self.btn_plan_analyze.setText("  🔍 Text analysieren")
        self.lbl_plan_complexity_badge.setText("⚠️ Analyse fehlgeschlagen")

    def _generate_habit_plan(self) -> None:
        """Constructs and stores a new daily self-study rhythm plan."""
        if not self.selected_item:
            return

        bid = str(self.selected_item.get("id") or "1")
        title = self.selected_item.get("title", "Werk")
        tot_p = max(1, int(self.selected_item.get("page_count") or self.selected_item.get("total_pages") or 100))
        curr_p = max(1, min(tot_p, int(self.selected_item.get("current_page") or 1)))

        study_days = [0, 1, 2, 3, 4] if self.chk_buffer_weekend.isChecked() else [0, 1, 2, 3, 4, 5, 6]
        d_min = self.spin_daily_min.value()

        plan = generate_habit_study_plan(
            book_id=bid,
            title=title,
            total_pages=tot_p,
            start_page=curr_p,
            complexity_meta=self.current_complexity,
            mode="daily_time",
            daily_minutes=d_min,
            study_days=study_days,
        )

        save_habit_study_plan(bid, plan)
        self.current_habit_plan = plan
        self._render_planner_timeline()

    def _load_planner_for_current_book(self) -> None:
        """Loads saved habit plan from SQLite when switching books."""
        if not self.selected_item:
            self.current_habit_plan = None
            self._render_planner_timeline()
            return

        bid = str(self.selected_item.get("id") or "1")
        saved = get_habit_study_plan(bid)
        if saved:
            self.current_habit_plan = saved
            comp = saved.get("complexity")
            if comp:
                self._on_complexity_analyzed(comp)
            self._render_planner_timeline()
        else:
            self.current_habit_plan = None
            self.lbl_plan_complexity_badge.setText("Score: — / 5.0")
            self.lbl_plan_complexity_badge.setStyleSheet("color: #F0F6FC; border: none;")
            self.lbl_plan_pace.setText("Geschätztes Tempo: ~3.5 Min. / Seite")
            self.lbl_plan_metrics.setText("Flesch: — · Fachwörter: — · Formeln: —")
            self._render_planner_timeline()

    def _render_planner_timeline(self) -> None:
        """Renders session rows in the timetable."""
        if not self.current_habit_plan or "sessions" not in self.current_habit_plan:
            self.table_planner_sessions.setRowCount(0)
            self.lbl_plan_overview.setText("Noch kein Rhythmusplan für dieses Buch erstellt.")
            self.lbl_plan_table_header.setText("📅 TÄGLICHE LERNEINHEITEN (KEIN PLAN)")
            return

        sessions = self.current_habit_plan.get("sessions", [])
        self.table_planner_sessions.setRowCount(len(sessions))

        done_cnt = sum(1 for s in sessions if s.get("completed"))
        tot_cnt = len(sessions)
        comp_date = self.current_habit_plan.get("completion_date", "—")
        daily_min = self.current_habit_plan.get("daily_minutes", 20)
        tot_hours = self.current_habit_plan.get("total_est_hours", 0.0)

        pct = int(done_cnt / tot_cnt * 100) if tot_cnt > 0 else 0
        self.lbl_plan_overview.setText(
            f"📅 Zielhorizont: ~{comp_date} · Gesamt: ca. {tot_hours:.1f} Std. ({daily_min} Min./Tag)\n"
            f"🔥 Fortschritt: {done_cnt} von {tot_cnt} Einheiten erledigt ({pct}%)"
        )
        self.lbl_plan_table_header.setText(f"📅 TÄGLICHE LERNEINHEITEN ({done_cnt}/{tot_cnt} ERLEDIGT)")

        for r_idx, s in enumerate(sessions):
            s_idx = s.get("session_idx", r_idx + 1)
            is_done = s.get("completed", False)
            is_buf = s.get("is_buffer", False)

            item_nr = QTableWidgetItem(f"#{s_idx}")
            item_nr.setTextAlignment(Qt.AlignCenter)
            if is_done:
                item_nr.setForeground(QColor("#3FB950"))
            self.table_planner_sessions.setItem(r_idx, 0, item_nr)

            item_date = QTableWidgetItem(s.get("date_display", ""))
            item_date.setTextAlignment(Qt.AlignCenter)
            self.table_planner_sessions.setItem(r_idx, 1, item_date)

            item_w = QTableWidgetItem(s.get("weekday", ""))
            item_w.setTextAlignment(Qt.AlignCenter)
            self.table_planner_sessions.setItem(r_idx, 2, item_w)

            if is_buf:
                item_p = QTableWidgetItem("🧠 Konsolidierung & Quiz")
                item_p.setForeground(QColor("#58A6FF"))
            else:
                sp = s.get("start_page", 1)
                ep = s.get("end_page", sp)
                item_p = QTableWidgetItem(f"S. {sp} – {ep} ({s.get('page_count', 0)} S.)")
            item_p.setTextAlignment(Qt.AlignCenter)
            self.table_planner_sessions.setItem(r_idx, 3, item_p)

            dur_m = s.get("est_minutes", daily_min)
            item_d = QTableWidgetItem(f"~{dur_m} Min.")
            item_d.setTextAlignment(Qt.AlignCenter)
            self.table_planner_sessions.setItem(r_idx, 4, item_d)

            ch_txt = s.get("chapter", "Lerneinheit")
            item_f = QTableWidgetItem(ch_txt)
            self.table_planner_sessions.setItem(r_idx, 5, item_f)

            btn_act = QPushButton("✓ Erledigt" if is_done else "Offen (Erledigen)")
            btn_act.setCursor(Qt.PointingHandCursor)
            if is_done:
                btn_act.setStyleSheet("""
                    QPushButton {
                        background-color: #143321;
                        color: #3FB950;
                        border: 1px solid #238636;
                        border-radius: 4px;
                        padding: 2px 8px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                """)
            else:
                btn_act.setStyleSheet("""
                    QPushButton {
                        background-color: #162035;
                        color: #C9D1D9;
                        border: 1px solid #2D3E63;
                        border-radius: 4px;
                        padding: 2px 8px;
                        font-size: 11px;
                    }
                    QPushButton:hover { background-color: #1F2D48; border-color: #58A6FF; color: #FFFFFF; }
                """)
            btn_act.clicked.connect(lambda checked, idx=s_idx: self._toggle_session_completed(idx))
            self.table_planner_sessions.setCellWidget(r_idx, 6, btn_act)

    def _shift_plan_missed_day(self) -> None:
        """Shifts remaining unfinished days forward by 1 day (Elastic shift)."""
        if not self.current_habit_plan:
            return
        self.current_habit_plan = adapt_plan_for_missed_days(self.current_habit_plan, days_missed=1, strategy="extend")
        save_habit_study_plan(self.current_habit_plan.get("book_id"), self.current_habit_plan)
        self._render_planner_timeline()

    def _catch_up_plan(self) -> None:
        """Gently distributes missed pages across remaining sessions."""
        if not self.current_habit_plan:
            return
        self.current_habit_plan = adapt_plan_for_missed_days(self.current_habit_plan, days_missed=1, strategy="catch_up")
        save_habit_study_plan(self.current_habit_plan.get("book_id"), self.current_habit_plan)
        self._render_planner_timeline()

    def _toggle_session_completed(self, session_idx: int) -> None:
        """Toggles done state and rewards XP."""
        if not self.current_habit_plan:
            return
        sessions = self.current_habit_plan.get("sessions", [])
        for s in sessions:
            if s.get("session_idx") == session_idx:
                was_done = s.get("completed", False)
                s["completed"] = not was_done
                if not was_done:
                    s["completed_at"] = time.time()
                    add_user_xp(15)
                    self._update_gamification_hud()
                else:
                    s["completed_at"] = None
                break

        save_habit_study_plan(self.current_habit_plan.get("book_id"), self.current_habit_plan)
        self._render_planner_timeline()

    def _on_planner_row_double_clicked(self, row: int, col: int) -> None:
        """Opens the selected session in Edge at its start page."""
        if not self.current_habit_plan:
            return
        sessions = self.current_habit_plan.get("sessions", [])
        if 0 <= row < len(sessions):
            sp = sessions[row].get("start_page", 1)
            fp = self.selected_item.get("file_path") or self.selected_item.get("local_path") if self.selected_item else ""
            if fp and os.path.exists(fp):
                open_pdf_in_edge(fp, sp)

    def _update_worksheet_scope_label(self) -> None:
        """Updates the worksheet banner to reflect current selected title and chapter."""
        title = self.selected_item.get("title", "Kein Werk") if self.selected_item else "Kein Werk"
        ch = self.current_chapter_title or "Kapitel"
        sp = self.spin_page_start.value()
        ep = self.spin_page_end.value()
        if hasattr(self, 'lbl_ws_scope'):
            self.lbl_ws_scope.setText(f"📄 Arbeitsblatt-Studio • {title[:38]} (Kapitel: {ch[:28]} · S. {sp}–{ep})")

        # Auto-switch to mathstral if current book is Mathematics / STEM
        if hasattr(self, 'combo_ws_model') and self.selected_item:
            from ai.worksheet_generator import is_stem_or_math_context
            if is_stem_or_math_context(title, ch, ""):
                for i in range(self.combo_ws_model.count()):
                    if "mathstral" in self.combo_ws_model.itemData(i).lower():
                        self.combo_ws_model.setCurrentIndex(i)
                        break

    # =================================================================
    # PAGE 1: 📄 ARBEITSBLATT-STUDIO (DIDAKTISCHE AUFGABEN & REPORTLAB PDF)
    # =================================================================
    def _build_worksheet_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # 1. ACTION & SETTINGS BAR
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 10px 14px;
            }
        """)
        b_lay = QVBoxLayout(bar)
        b_lay.setSpacing(8)

        # Row 1: Scope label & Status
        r1 = QHBoxLayout()
        self.lbl_ws_scope = QLabel("📄 Arbeitsblatt-Studio • Bereit für didaktische Aufbereitung")
        self.lbl_ws_scope.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_ws_scope.setStyleSheet("color: #F0F6FC; border: none;")
        r1.addWidget(self.lbl_ws_scope)
        r1.addStretch()

        self.lbl_ws_status = QLabel("")
        self.lbl_ws_status.setStyleSheet("color: #388BFD; font-weight: bold; font-size: 11px; border: none;")
        r1.addWidget(self.lbl_ws_status)
        b_lay.addLayout(r1)

        # Row 2: Controls & Action buttons
        r2 = QHBoxLayout()
        r2.setSpacing(10)

        lbl_diff = QLabel("Niveau:")
        lbl_diff.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 600; border: none;")
        r2.addWidget(lbl_diff)

        self.combo_ws_level = QComboBox()
        self.combo_ws_level.addItem("Grundlagen (AFB I)", "basic")
        self.combo_ws_level.addItem("Standard (AFB I–III)", "standard")
        self.combo_ws_level.addItem("Klausurniveau (AFB II–III)", "advanced")
        self.combo_ws_level.setCurrentIndex(1)
        self.combo_ws_level.setStyleSheet("""
            QComboBox {
                background-color: #0B0F19;
                border: 1px solid #28395A;
                border-radius: 5px;
                color: #F0F6FC;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
        """)
        r2.addWidget(self.combo_ws_level)

        lbl_model = QLabel("🤖 Modell:")
        lbl_model.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 600; border: none;")
        r2.addWidget(lbl_model)

        self.combo_ws_model = QComboBox()
        self.combo_ws_model.setStyleSheet("""
            QComboBox {
                background-color: #0B0F19;
                border: 1px solid #28395A;
                border-radius: 5px;
                color: #F0F6FC;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
                min-width: 170px;
            }
            QComboBox::drop-down { border: none; }
        """)
        self._populate_ws_ai_models()
        r2.addWidget(self.combo_ws_model)

        self.chk_ws_plot = QPushButton("✓ Diagramm-Plot (300 DPI PNG)")
        self.chk_ws_plot.setCheckable(True)
        self.chk_ws_plot.setChecked(True)
        self.chk_ws_plot.setCursor(Qt.PointingHandCursor)
        self.chk_ws_plot.setStyleSheet("""
            QPushButton {
                background-color: #0E1626;
                color: #8B949E;
                border: 1px solid #1E2E4E;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:checked {
                background-color: #132438;
                color: #58A6FF;
                border-color: #1F6FEB;
                font-weight: bold;
            }
        """)
        r2.addWidget(self.chk_ws_plot)

        r2.addStretch()

        self.btn_gen_worksheet = QPushButton("✨ Arbeitsblatt generieren")
        self.btn_gen_worksheet.setCursor(Qt.PointingHandCursor)
        self.btn_gen_worksheet.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1F6FEB, stop:1 #174EB8);
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background: #388BFD; }
        """)
        self.btn_gen_worksheet.clicked.connect(self._start_worksheet_generation)
        r2.addWidget(self.btn_gen_worksheet)

        self.btn_export_pdf = QPushButton("📄 PDF drucken (ReportLab)")
        self.btn_export_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_export_pdf.setEnabled(False)
        self.btn_export_pdf.setStyleSheet("""
            QPushButton {
                background-color: #143321;
                color: #3FB950;
                border: 1px solid #238636;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover:enabled { background-color: #1D4B30; color: #FFFFFF; }
            QPushButton:disabled { background-color: #111B15; color: #486350; border-color: #183321; }
        """)
        self.btn_export_pdf.clicked.connect(self._export_worksheet_pdf)
        r2.addWidget(self.btn_export_pdf)

        self.btn_open_pdf = QPushButton("👁️ Im Viewer öffnen")
        self.btn_open_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_open_pdf.setEnabled(False)
        self.btn_open_pdf.setStyleSheet("""
            QPushButton {
                background-color: #1A2438;
                color: #C9D1D9;
                border: 1px solid #28395A;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover:enabled { background-color: #253552; border-color: #58A6FF; color: #FFFFFF; }
            QPushButton:disabled { background-color: #111726; color: #485368; border-color: #192235; }
        """)
        self.btn_open_pdf.clicked.connect(self._open_last_worksheet_pdf)
        r2.addWidget(self.btn_open_pdf)

        b_lay.addLayout(r2)
        layout.addWidget(bar)

        # 2. MAIN PREVIEW SPLITTER (Arbeitsblatt Left, Musterlösung Right)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #232F48;
                width: 4px;
            }
        """)

        # LEFT: Printable Worksheet Preview
        box_left = QFrame()
        box_left.setStyleSheet("background-color: #0D111A; border: 1px solid #1E283D; border-radius: 8px;")
        bl_lay = QVBoxLayout(box_left)
        bl_lay.setContentsMargins(12, 10, 12, 10)
        bl_lay.setSpacing(8)

        lbl_bl_head = QLabel("📄 ARBEITSBLATT (ÜBUNGSAUFGABEN & TABELLEN)")
        lbl_bl_head.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_bl_head.setStyleSheet("color: #58A6FF; border: none;")
        bl_lay.addWidget(lbl_bl_head)

        scroll_left = QScrollArea()
        scroll_left.setWidgetResizable(True)
        scroll_left.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.ws_preview_container = QWidget()
        self.ws_preview_layout = QVBoxLayout(self.ws_preview_container)
        self.ws_preview_layout.setContentsMargins(4, 4, 4, 4)
        self.ws_preview_layout.setSpacing(12)

        lbl_init_hint = QLabel("Klicke auf «✨ Arbeitsblatt generieren», um aus dem ausgewählten Kapitel didaktische Aufgaben, Lückentexte, Tabellen und Grafiken zu erstellen.")
        lbl_init_hint.setStyleSheet("color: #8B949E; font-size: 12px; border: none; padding: 20px;")
        lbl_init_hint.setWordWrap(True)
        lbl_init_hint.setAlignment(Qt.AlignCenter)
        self.ws_preview_layout.addWidget(lbl_init_hint)
        self.ws_preview_layout.addStretch()

        scroll_left.setWidget(self.ws_preview_container)
        bl_lay.addWidget(scroll_left)
        splitter.addWidget(box_left)

        # RIGHT: Master Solution / Answer Key Preview
        box_right = QFrame()
        box_right.setStyleSheet("background-color: #0D111A; border: 1px solid #1E283D; border-radius: 8px;")
        br_lay = QVBoxLayout(box_right)
        br_lay.setContentsMargins(12, 10, 12, 10)
        br_lay.setSpacing(8)

        lbl_br_head = QLabel("🔑 MUSTERLÖSUNG & KORREKTURBLATT (SEPARATER ANHANG)")
        lbl_br_head.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_br_head.setStyleSheet("color: #3FB950; border: none;")
        br_lay.addWidget(lbl_br_head)

        scroll_right = QScrollArea()
        scroll_right.setWidgetResizable(True)
        scroll_right.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.ws_solution_container = QWidget()
        self.ws_solution_layout = QVBoxLayout(self.ws_solution_container)
        self.ws_solution_layout.setContentsMargins(4, 4, 4, 4)
        self.ws_solution_layout.setSpacing(12)

        lbl_sol_hint = QLabel("Die Musterlösung für den Selbst-Check wird automatisch auf einer separaten Lösungsseite für den Ausdruck erzeugt.")
        lbl_sol_hint.setStyleSheet("color: #8B949E; font-size: 12px; border: none; padding: 20px;")
        lbl_sol_hint.setWordWrap(True)
        lbl_sol_hint.setAlignment(Qt.AlignCenter)
        self.ws_solution_layout.addWidget(lbl_sol_hint)
        self.ws_solution_layout.addStretch()

        scroll_right.setWidget(self.ws_solution_container)
        br_lay.addWidget(scroll_right)
        splitter.addWidget(box_right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, stretch=1)

        return container

    def _populate_ws_ai_models(self) -> None:
        """Populates AI model selector for worksheets, prioritizing mathstral for STEM."""
        self.combo_ws_model.clear()
        models = get_available_ai_models()
        math_idx = -1

        # Check if mathstral is installed locally
        has_mathstral = any("mathstral" in m.get("id", "").lower() for m in models)
        if has_mathstral:
            for m in models:
                m_id = m.get("id", "")
                m_name = m.get("name", m_id)
                if "mathstral" in m_id.lower():
                    label = f"🧮 {m_name} ★ Mathe & MINT"
                    math_idx = self.combo_ws_model.count()
                    self.combo_ws_model.addItem(label, m_id)
                else:
                    self.combo_ws_model.addItem(m_name, m_id)
        else:
            self.combo_ws_model.addItem("🧮 mathstral:latest (Empfohlen für Mathe)", "ollama:mathstral:latest")
            math_idx = 0
            for m in models:
                self.combo_ws_model.addItem(m.get("name", m.get("id", "")), m.get("id", ""))

        if math_idx >= 0:
            self.combo_ws_model.setCurrentIndex(math_idx)

    def _start_worksheet_generation(self) -> None:
        """Triggers AI generation of worksheet didactic contents."""
        text = self._extract_active_text()
        if not text:
            self.lbl_ws_status.setText("⚠️ Kein Text verfügbar")
            return

        title = self.selected_item.get("title", "Werk") if self.selected_item else "Werk"
        chapter = self.current_chapter_title or "Kapitel"
        sp = self.spin_page_start.value()
        ep = self.spin_page_end.value()

        self.btn_gen_worksheet.setEnabled(False)
        self.btn_gen_worksheet.setText("  ⏳ Generiere...")
        self.lbl_ws_status.setText(f"Erstelle Aufgaben zu S. {sp}–{ep}...")

        mid = self.combo_ws_model.currentData() if hasattr(self, 'combo_ws_model') else ""
        diff = self.combo_ws_level.currentData() if hasattr(self, 'combo_ws_level') else "standard"
        self._worksheet_worker = WorksheetWorkerThread(
            title, chapter, text,
            start_page=sp, end_page=ep,
            difficulty=diff,
            model_id=mid or "ollama:mathstral:latest",
            parent=self
        )
        self._worksheet_worker.finished.connect(self._on_worksheet_generated)
        self._worksheet_worker.error_occurred.connect(self._on_worksheet_error)
        self._worksheet_worker.start()

    def _on_worksheet_generated(self, data: Dict[str, Any]) -> None:
        self.current_worksheet_data = data
        self.btn_gen_worksheet.setEnabled(True)
        self.btn_gen_worksheet.setText("✨ Arbeitsblatt generieren")
        self.btn_export_pdf.setEnabled(True)
        self.lbl_ws_status.setText("✓ Arbeitsblatt bereit")

        # Generate 300 DPI PNG diagram if requested
        if self.chk_ws_plot.isChecked():
            try:
                self.current_worksheet_plot_path = render_exercise_plot("timeline", data.get("diagram_data"))
            except Exception:
                self.current_worksheet_plot_path = None
        else:
            self.current_worksheet_plot_path = None

        self._render_worksheet_preview()

    def _on_worksheet_error(self, err: str) -> None:
        self.btn_gen_worksheet.setEnabled(True)
        self.btn_gen_worksheet.setText("✨ Arbeitsblatt generieren")
        self.lbl_ws_status.setText(f"⚠️ Fehler: {err[:35]}")

    def _render_worksheet_preview(self) -> None:
        """Renders interactive preview cards for exercises and master answer key."""
        if not self.current_worksheet_data:
            return

        while self.ws_preview_layout.count():
            item = self.ws_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        while self.ws_solution_layout.count():
            item = self.ws_solution_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        data = self.current_worksheet_data
        subj = data.get("subject", "Übung")
        tot_pts = data.get("total_points", 20)
        dur = data.get("target_time_min", 45)
        sp = data.get("start_page", self.spin_page_start.value())
        ep = data.get("end_page", self.spin_page_end.value())
        is_math = data.get("is_math_mode", False) or bool(data.get("task1_classification") or data.get("task3_truth_table"))

        # ----------------- LEFT PANEL: WORKSHEET -----------------
        h_card = QFrame()
        h_card.setStyleSheet("background-color: #121826; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
        h_lay = QVBoxLayout(h_card)
        lbl_h_t = QLabel(f"<b>THEMA: {subj.upper()}</b>")
        lbl_h_t.setStyleSheet("color: #F0F6FC; font-size: 13px; border: none;")
        h_lay.addWidget(lbl_h_t)
        mode_badge = "🧮 <b>Mathematik-Modus (Mathstral)</b> · " if is_math else ""
        lbl_h_meta = QLabel(f"{mode_badge}📖 Buchseiten: <b>S. {sp}–{ep}</b> · ⏱️ Zeit: ca. {dur} Min. · Gesamtpunktzahl: {tot_pts} P.")
        lbl_h_meta.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        h_lay.addWidget(lbl_h_meta)
        self.ws_preview_layout.addWidget(h_card)

        if is_math:
            # MATH TASK 1: Classification
            t1_class = data.get("task1_classification", {})
            if t1_class:
                c_card = QFrame()
                c_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                c_lay = QVBoxLayout(c_card)
                lbl_c_head = QLabel("<b>Teil 1: Klassifikation mathematischer Aussagen & Formen (AFB I)</b>")
                lbl_c_head.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
                c_lay.addWidget(lbl_c_head)

                lbl_c_instr = QLabel(t1_class.get("instruction", "Klassifiziere die folgenden Ausdrücke:"))
                lbl_c_instr.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
                c_lay.addWidget(lbl_c_instr)

                for idx, it in enumerate(t1_class.get("items", []), 1):
                    expr = it.get("expr", "")
                    pts = it.get("points", 1)
                    lbl_it = QLabel(f"<b>1.{idx}:</b> <font color='#58A6FF'><b>« {expr} »</b></font> <font color='#6E7681'>({pts} P.)</font>")
                    lbl_it.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none;")
                    c_lay.addWidget(lbl_it)
                    lbl_line = QLabel("Klassifikation: ___________________________ | Begründung: _____________________________________")
                    lbl_line.setStyleSheet("color: #2D3E63; font-size: 10px; border: none;")
                    c_lay.addWidget(lbl_line)
                self.ws_preview_layout.addWidget(c_card)

            # MATH TASK 2: Calculations
            t2_calc = data.get("task2_calculation", {})
            if t2_calc:
                calc_card = QFrame()
                calc_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                cl_lay = QVBoxLayout(calc_card)
                lbl_calc_head = QLabel("<b>Teil 2: Logische Auswertungen & Wahrheitswert-Berechnung (AFB II)</b>")
                lbl_calc_head.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
                cl_lay.addWidget(lbl_calc_head)

                lbl_calc_instr = QLabel(t2_calc.get("instruction", "Bestimme den Wahrheitswert:"))
                lbl_calc_instr.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
                cl_lay.addWidget(lbl_calc_instr)

                for idx, st in enumerate(t2_calc.get("subtasks", []), 1):
                    expr = st.get("expr", "")
                    pts = st.get("points", 2)
                    lbl_st = QLabel(f"<b>2.{idx}:</b> Berechne Wahrheitswert für: <b><font color='#58A6FF'>{expr}</font></b> <font color='#6E7681'>({pts} P.)</font>")
                    lbl_st.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none;")
                    cl_lay.addWidget(lbl_st)
                    lbl_sline = QLabel("Rechenweg: __________________________________________________________________  Ergebnis = [   ]")
                    lbl_sline.setStyleSheet("color: #2D3E63; font-size: 10px; border: none;")
                    cl_lay.addWidget(lbl_sline)
                self.ws_preview_layout.addWidget(calc_card)

            # MATH TASK 3: Truth Table
            t3_tab = data.get("task3_truth_table", {})
            if t3_tab:
                tt_card = QFrame()
                tt_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                tt_lay = QVBoxLayout(tt_card)
                lbl_tt_head = QLabel(f"<b>Teil 3: Wahrheitstabelle zum Ausfüllen ({t3_tab.get('points', 5)} P.)</b>")
                lbl_tt_head.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
                tt_lay.addWidget(lbl_tt_head)

                cols = t3_tab.get("columns", ["A", "B", "Ausdruck"])
                hdr_html = " | ".join(f"<b>{c}</b>" for c in cols)
                lbl_thdr = QLabel(f"Tabelle: {t3_tab.get('title', '')}<br/><font color='#58A6FF'>{hdr_html}</font>")
                lbl_thdr.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none; padding: 4px;")
                tt_lay.addWidget(lbl_thdr)
                self.ws_preview_layout.addWidget(tt_card)

            # MATH TASK 4: Proof / Paradox
            t4_proof = data.get("task4_proof", {})
            if t4_proof:
                p_card = QFrame()
                p_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                p_lay = QVBoxLayout(p_card)
                lbl_p_head = QLabel(f"<b>Teil 5: {t4_proof.get('title', 'Formaler Beweis')} ({t4_proof.get('points', 4)} P.)</b>")
                lbl_p_head.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
                p_lay.addWidget(lbl_p_head)

                sc = t4_proof.get("scenario", "")
                if sc:
                    sc_box = QFrame()
                    sc_box.setStyleSheet("background-color: #121E30; border: 1px solid #1F4E85; border-radius: 5px; padding: 8px;")
                    sb_lay = QVBoxLayout(sc_box)
                    lbl_sc = QLabel(f"<b>Ausgangsbasis:</b> {sc}")
                    lbl_sc.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none;")
                    lbl_sc.setWordWrap(True)
                    sb_lay.addWidget(lbl_sc)
                    p_lay.addWidget(sc_box)

                lbl_q = QLabel(f"<b>Beweisaufgabe:</b> {t4_proof.get('question', '')}")
                lbl_q.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none; padding-top: 4px;")
                lbl_q.setWordWrap(True)
                p_lay.addWidget(lbl_q)

                lbl_plines = QLabel("_________________________________________________________________________________________\n_________________________________________________________________________________________")
                lbl_plines.setStyleSheet("color: #2D3E63; font-size: 11px; border: none;")
                p_lay.addWidget(lbl_plines)
                self.ws_preview_layout.addWidget(p_card)

        else:
            # STANDARD MODE
            defs = data.get("task1_definitions", [])
            if defs:
                t1_card = QFrame()
                t1_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                t1_lay = QVBoxLayout(t1_card)
                lbl_t1 = QLabel("<b>Teil 1: Fachbegriffe & Definitionen (Reproduktion)</b>")
                lbl_t1.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
                t1_lay.addWidget(lbl_t1)
                for idx, d in enumerate(defs, 1):
                    pts = d.get("points", 3)
                    lbl_q = QLabel(f"<b>Aufgabe 1.{idx}:</b> {d.get('question', '')} <font color='#6E7681'>({pts} P.)</font>")
                    lbl_q.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none;")
                    lbl_q.setWordWrap(True)
                    t1_lay.addWidget(lbl_q)
                    lbl_lines = QLabel("_________________________________________________________________________________________\n_________________________________________________________________________________________")
                    lbl_lines.setStyleSheet("color: #2D3E63; font-size: 11px; border: none;")
                    t1_lay.addWidget(lbl_lines)
                self.ws_preview_layout.addWidget(t1_card)

            cloze = data.get("task2_cloze", {})
            if cloze:
                t2_card = QFrame()
                t2_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                t2_lay = QVBoxLayout(t2_card)
                lbl_t2 = QLabel(f"<b>Teil 2: {cloze.get('title', 'Lückentext')} ({cloze.get('points', 5)} P.)</b>")
                lbl_t2.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
                t2_lay.addWidget(lbl_t2)
                pool = cloze.get("word_pool", [])
                if pool:
                    p_box = QFrame()
                    p_box.setStyleSheet("background-color: #162035; border: 1px solid #2D3E63; border-radius: 5px; padding: 6px;")
                    p_lay = QVBoxLayout(p_box)
                    lbl_p_h = QLabel("<b>Didaktischer Begriffsspeicher:</b>")
                    lbl_p_h.setStyleSheet("color: #C9D1D9; font-size: 10px; border: none;")
                    p_lay.addWidget(lbl_p_h)
                    lbl_p_words = QLabel("   •   ".join(f"[{w}]" for w in pool))
                    lbl_p_words.setStyleSheet("color: #58A6FF; font-size: 11px; font-weight: bold; border: none;")
                    lbl_p_words.setWordWrap(True)
                    p_lay.addWidget(lbl_p_words)
                    t2_lay.addWidget(p_box)
                lbl_c_body = QLabel(cloze.get("text_with_blanks", ""))
                lbl_c_body.setStyleSheet("color: #F0F6FC; font-size: 11px; line-height: 1.4; border: none; padding-top: 6px;")
                lbl_c_body.setWordWrap(True)
                t2_lay.addWidget(lbl_c_body)
                self.ws_preview_layout.addWidget(t2_card)

            transfer = data.get("task3_transfer", {})
            if transfer:
                t3_card = QFrame()
                t3_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                t3_lay = QVBoxLayout(t3_card)
                lbl_t3 = QLabel("<b>Teil 4: Praxisnahe Fallstudie & Transfer (AFB III)</b>")
                lbl_t3.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
                t3_lay.addWidget(lbl_t3)
                sc = transfer.get("scenario", "")
                if sc:
                    sc_box = QFrame()
                    sc_box.setStyleSheet("background-color: #121E30; border: 1px solid #1F4E85; border-radius: 5px; padding: 8px;")
                    sc_lay = QVBoxLayout(sc_box)
                    lbl_sc = QLabel(f"<b>Ausgangsszenario:</b><br/>{sc}")
                    lbl_sc.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none;")
                    lbl_sc.setWordWrap(True)
                    sc_lay.addWidget(lbl_sc)
                    t3_lay.addWidget(sc_box)
                for idx, tq in enumerate(transfer.get("questions", []), 1):
                    pts = tq.get("points", 4)
                    lbl_sub = QLabel(f"<b>Aufgabe 4.{idx}:</b> {tq.get('subtask', '')} <font color='#6E7681'>({pts} P.)</font>")
                    lbl_sub.setStyleSheet("color: #F0F6FC; font-size: 11px; border: none;")
                    lbl_sub.setWordWrap(True)
                    t3_lay.addWidget(lbl_sub)
                    lbl_l = QLabel("_________________________________________________________________________________________\n_________________________________________________________________________________________")
                    lbl_l.setStyleSheet("color: #2D3E63; font-size: 11px; border: none;")
                    t3_lay.addWidget(lbl_l)
                self.ws_preview_layout.addWidget(t3_card)

        # Shared Diagram preview if generated
        if self.current_worksheet_plot_path and os.path.exists(self.current_worksheet_plot_path):
            diag_card = QFrame()
            diag_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
            d_lay = QVBoxLayout(diag_card)
            lbl_d_head = QLabel("<b>Grafische Datenanalyse & Ablaufgraph (300 DPI PNG)</b>")
            lbl_d_head.setStyleSheet("color: #58A6FF; font-size: 12px; border: none;")
            d_lay.addWidget(lbl_d_head)
            from PySide6.QtGui import QPixmap
            pix = QPixmap(self.current_worksheet_plot_path)
            if not pix.isNull():
                lbl_img = QLabel()
                scaled_pix = pix.scaledToWidth(520, Qt.SmoothTransformation)
                lbl_img.setPixmap(scaled_pix)
                lbl_img.setAlignment(Qt.AlignCenter)
                lbl_img.setStyleSheet("background-color: #FFFFFF; border-radius: 4px; padding: 4px; border: 1px solid #CBD5E1;")
                d_lay.addWidget(lbl_img)
            self.ws_preview_layout.addWidget(diag_card)

        self.ws_preview_layout.addStretch()

        # ----------------- RIGHT PANEL: ANSWER KEY -----------------
        sol_head = QFrame()
        sol_head.setStyleSheet("background-color: #121826; border: 1px solid #232F48; border-radius: 6px; padding: 8px;")
        sh_lay = QVBoxLayout(sol_head)
        lbl_sh = QLabel("<b>LÖSUNGSBLATT • ERWARTUNGSHORIZONT</b>")
        lbl_sh.setStyleSheet("color: #3FB950; font-size: 12px; border: none;")
        sh_lay.addWidget(lbl_sh)
        lbl_sh_sub = QLabel("Wird im ReportLab-PDF auf einer separaten Anhangsseite gedruckt.")
        lbl_sh_sub.setStyleSheet("color: #8B949E; font-size: 10px; border: none;")
        sh_lay.addWidget(lbl_sh_sub)
        self.ws_solution_layout.addWidget(sol_head)

        if is_math:
            t1_class = data.get("task1_classification", {})
            if t1_class:
                s1_card = QFrame()
                s1_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                s1_lay = QVBoxLayout(s1_card)
                s1_lay.addWidget(QLabel("<font color='#3FB950'><b>Musterlösung Teil 1 (Klassifikation):</b></font>"))
                for idx, it in enumerate(t1_class.get("items", []), 1):
                    lbl_it = QLabel(f"<b>1.{idx} {it.get('expr')}:</b> <font color='#3FB950'>{it.get('solution')}</font>")
                    lbl_it.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none;")
                    lbl_it.setWordWrap(True)
                    s1_lay.addWidget(lbl_it)
                self.ws_solution_layout.addWidget(s1_card)

            t2_calc = data.get("task2_calculation", {})
            if t2_calc:
                s2_card = QFrame()
                s2_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                s2_lay = QVBoxLayout(s2_card)
                s2_lay.addWidget(QLabel("<font color='#3FB950'><b>Musterlösung Teil 2 (Wahrheitswerte):</b></font>"))
                for idx, st in enumerate(t2_calc.get("subtasks", []), 1):
                    lbl_st = QLabel(f"<b>2.{idx} {st.get('expr')}:</b> <font color='#3FB950'><b>{st.get('solution')}</b></font>")
                    lbl_st.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none;")
                    lbl_st.setWordWrap(True)
                    s2_lay.addWidget(lbl_st)
                self.ws_solution_layout.addWidget(s2_card)

            t3_tab = data.get("task3_truth_table", {})
            if t3_tab:
                s3_card = QFrame()
                s3_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                s3_lay = QVBoxLayout(s3_card)
                s3_lay.addWidget(QLabel("<font color='#3FB950'><b>Musterlösung Teil 3 (Wahrheitstabelle vollständig):</b></font>"))
                for r in t3_tab.get("rows", []):
                    lbl_r = QLabel("   |   ".join(str(c) for c in r))
                    lbl_r.setStyleSheet("color: #3FB950; font-family: monospace; font-size: 11px; border: none;")
                    s3_lay.addWidget(lbl_r)
                self.ws_solution_layout.addWidget(s3_card)

            t4_proof = data.get("task4_proof", {})
            if t4_proof:
                s4_card = QFrame()
                s4_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                s4_lay = QVBoxLayout(s4_card)
                s4_lay.addWidget(QLabel("<font color='#3FB950'><b>Musterlösung Teil 5 (Beweisgang):</b></font>"))
                lbl_sol = QLabel(t4_proof.get("solution", ""))
                lbl_sol.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none;")
                lbl_sol.setWordWrap(True)
                s4_lay.addWidget(lbl_sol)
                self.ws_solution_layout.addWidget(s4_card)

        else:
            # STANDARD SOLUTIONS
            defs = data.get("task1_definitions", [])
            if defs:
                s1_card = QFrame()
                s1_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                s1_lay = QVBoxLayout(s1_card)
                s1_lay.addWidget(QLabel("<font color='#3FB950'><b>Musterlösung Teil 1 (Definitionen):</b></font>"))
                for idx, d in enumerate(defs, 1):
                    lbl_a = QLabel(f"<b>1.{idx}:</b> {d.get('answer', '')}")
                    lbl_a.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none;")
                    lbl_a.setWordWrap(True)
                    s1_lay.addWidget(lbl_a)
                self.ws_solution_layout.addWidget(s1_card)

            cloze = data.get("task2_cloze", {})
            if cloze and "solutions" in cloze:
                s2_card = QFrame()
                s2_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                s2_lay = QVBoxLayout(s2_card)
                s2_lay.addWidget(QLabel("<font color='#3FB950'><b>Lösung Teil 2 (Lückentext):</b></font>"))
                s_lines = "   ·   ".join(f"<b>{k}</b> = {v}" for k, v in cloze.get("solutions", {}).items())
                lbl_s2 = QLabel(s_lines)
                lbl_s2.setStyleSheet("color: #58A6FF; font-size: 11px; border: none;")
                lbl_s2.setWordWrap(True)
                s2_lay.addWidget(lbl_s2)
                self.ws_solution_layout.addWidget(s2_card)

            transfer = data.get("task3_transfer", {})
            if transfer and "questions" in transfer:
                s3_card = QFrame()
                s3_card.setStyleSheet("background-color: #111726; border: 1px solid #232F48; border-radius: 6px; padding: 10px;")
                s3_lay = QVBoxLayout(s3_card)
                s3_lay.addWidget(QLabel("<font color='#3FB950'><b>Bewertungskriterien Teil 4 (Transfer):</b></font>"))
                for idx, tq in enumerate(transfer.get("questions", []), 1):
                    lbl_tq = QLabel(f"<b>4.{idx}:</b> {tq.get('answer', '')}")
                    lbl_tq.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none;")
                    lbl_tq.setWordWrap(True)
                    s3_lay.addWidget(lbl_tq)
                self.ws_solution_layout.addWidget(s3_card)

        self.ws_solution_layout.addStretch()

    def _export_worksheet_pdf(self) -> None:
        """Compiles professional printable DIN A4 worksheet with ReportLab and opens it."""
        if not self.current_worksheet_data:
            return

        title = self.selected_item.get("title", "Werk") if self.selected_item else "Werk"
        chapter = self.current_chapter_title or "Kapitel"

        try:
            pdf_path = build_worksheet_pdf(
                book_title=title,
                chapter_title=chapter,
                exercise_data=self.current_worksheet_data,
                plot_image_path=self.current_worksheet_plot_path
            )
            self.last_worksheet_pdf_path = pdf_path
            self.btn_open_pdf.setEnabled(True)
            self.lbl_ws_status.setText(f"✓ PDF exportiert: {os.path.basename(pdf_path)}")

            # Open automatically in Microsoft Edge / System PDF Viewer
            open_pdf_in_edge(pdf_path)
        except Exception as e:
            self.lbl_ws_status.setText(f"⚠️ PDF-Fehler: {str(e)[:35]}")

    def _open_last_worksheet_pdf(self) -> None:
        """Opens last compiled ReportLab PDF."""
        if self.last_worksheet_pdf_path and os.path.exists(self.last_worksheet_pdf_path):
            open_pdf_in_edge(self.last_worksheet_pdf_path)

    # =================================================================
    # PAGE 2: 📝 KLAUSURSIMULATION (TIMED EXAM SUITE)
    # =================================================================
    def _build_exam_simulator_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        self.exam_stack = QStackedWidget()

        # SUB-PAGE 0: Pre-Exam Briefing & Config
        self.sub_exam_start = QFrame()
        self.sub_exam_start.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 10px;
                padding: 24px;
            }
        """)
        es_layout = QVBoxLayout(self.sub_exam_start)
        es_layout.setSpacing(16)
        es_layout.setAlignment(Qt.AlignCenter)

        lbl_sim_icon = QLabel()
        lbl_sim_icon.setPixmap(create_vector_pixmap("exam", "#58A6FF", 48))
        lbl_sim_icon.setAlignment(Qt.AlignCenter)
        lbl_sim_icon.setStyleSheet("border: none; background: transparent;")
        es_layout.addWidget(lbl_sim_icon)

        lbl_sim_head = QLabel("KLAUSURSIMULATION UNTER REALBEDINGUNGEN")
        lbl_sim_head.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_sim_head.setStyleSheet("color: #F0F6FC; border: none;")
        lbl_sim_head.setAlignment(Qt.AlignCenter)
        es_layout.addWidget(lbl_sim_head)

        lbl_sim_desc = QLabel(
            "Testen Sie Ihren Wissensstand wie in einer echten Hochschulprüfung.\n"
            "Die KI generiert auf Basis Ihres ausgewählten Lehrbuchkapitels anspruchsvolle Klausuraufgaben.\n"
            "Nach Ablauf der Prüfungszeit oder vorzeitiger Abgabe erfolgt die offizielle Notengebung (1,0 bis 5,0) "
            "inklusive Kriterien-Gutachten und Musterlösung."
        )
        lbl_sim_desc.setWordWrap(True)
        lbl_sim_desc.setAlignment(Qt.AlignCenter)
        lbl_sim_desc.setStyleSheet("color: #8B949E; font-size: 13px; max-width: 650px; line-height: 1.4; border: none;")
        es_layout.addWidget(lbl_sim_desc)

        # Settings Pill Box
        cfg_box = QHBoxLayout()
        cfg_box.setSpacing(16)
        cfg_box.setAlignment(Qt.AlignCenter)

        lbl_dur = QLabel("Prüfungsdauer:")
        lbl_dur.setStyleSheet("color: #F0F6FC; font-weight: bold; border: none;")
        cfg_box.addWidget(lbl_dur)

        self.combo_exam_dur = QComboBox()
        self.combo_exam_dur.addItem("⏱️ 15 Minuten (Kurzklausur)", 15)
        self.combo_exam_dur.addItem("⏱️ 30 Minuten (Standard)", 30)
        self.combo_exam_dur.addItem("⏱️ 45 Minuten (Große Klausur)", 45)
        self.combo_exam_dur.setCurrentIndex(1)
        self.combo_exam_dur.setStyleSheet("""
            QComboBox {
                background: #0B0F19;
                border: 1px solid #324468;
                border-radius: 6px;
                color: #F0F6FC;
                padding: 6px 12px;
                font-size: 12px;
            }
        """)
        cfg_box.addWidget(self.combo_exam_dur)

        es_layout.addLayout(cfg_box)

        self.btn_start_exam = QPushButton("  🚀 Klausur austeilen & Prüfung starten")
        self.btn_start_exam.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.btn_start_exam.setCursor(Qt.PointingHandCursor)
        self.btn_start_exam.setFixedHeight(48)
        self.btn_start_exam.setMinimumWidth(320)
        self.btn_start_exam.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF;
                border: 1px solid #58A6FF;
                border-radius: 8px;
                padding: 10px 24px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        self.btn_start_exam.clicked.connect(self._start_exam_generation)
        es_layout.addWidget(self.btn_start_exam, alignment=Qt.AlignCenter)

        self.lbl_exam_gen_status = QLabel("")
        self.lbl_exam_gen_status.setStyleSheet("color: #58A6FF; font-weight: bold; border: none;")
        self.lbl_exam_gen_status.setAlignment(Qt.AlignCenter)
        es_layout.addWidget(self.lbl_exam_gen_status)

        self.exam_stack.addWidget(self.sub_exam_start)

        # SUB-PAGE 1: Live Exam In-Progress
        self.sub_exam_live = QWidget()
        live_layout = QVBoxLayout(self.sub_exam_live)
        live_layout.setContentsMargins(0, 0, 0, 0)
        live_layout.setSpacing(10)

        # Floating Exam Timer & Header Bar
        timer_bar = QFrame()
        timer_bar.setStyleSheet("""
            QFrame {
                background: #101625;
                border: 1px solid #324468;
                border-radius: 8px;
                padding: 8px 14px;
            }
        """)
        tb_lay = QHBoxLayout(timer_bar)
        tb_lay.setContentsMargins(8, 4, 8, 4)

        self.lbl_live_timer = QLabel("⏱️ Verbleibend: 30:00")
        self.lbl_live_timer.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_live_timer.setStyleSheet("color: #D2A8FF; border: none;")
        tb_lay.addWidget(self.lbl_live_timer)

        tb_lay.addStretch()

        self.lbl_exam_points_stat = QLabel("Punkte: 0 / 30")
        self.lbl_exam_points_stat.setStyleSheet("color: #8B949E; font-weight: 600; border: none;")
        tb_lay.addWidget(self.lbl_exam_points_stat)

        self.btn_submit_exam = QPushButton("  Klausur abgeben & benoten lassen")
        self.btn_submit_exam.setIcon(create_vector_icon("check", "#FFFFFF", 14))
        self.btn_submit_exam.setCursor(Qt.PointingHandCursor)
        self.btn_submit_exam.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #2EA043;
            }
        """)
        self.btn_submit_exam.clicked.connect(self._submit_exam)
        tb_lay.addWidget(self.btn_submit_exam)

        live_layout.addWidget(timer_bar)

        # Scroll Area for Exam Questions
        self.exam_scroll = QScrollArea()
        self.exam_scroll.setWidgetResizable(True)
        self.exam_scroll.setStyleSheet("background: transparent; border: none;")
        self.exam_scroll_content = QWidget()
        self.exam_questions_layout = QVBoxLayout(self.exam_scroll_content)
        self.exam_questions_layout.setContentsMargins(0, 0, 0, 0)
        self.exam_questions_layout.setSpacing(12)
        self.exam_scroll.setWidget(self.exam_scroll_content)

        live_layout.addWidget(self.exam_scroll, stretch=1)
        self.exam_stack.addWidget(self.sub_exam_live)

        # SUB-PAGE 2: Exam Results & Master Solution
        self.sub_exam_result = QWidget()
        res_layout = QVBoxLayout(self.sub_exam_result)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(12)

        self.card_result_banner = QFrame()
        self.card_result_banner.setStyleSheet("""
            QFrame {
                background: #11261B;
                border: 2px solid #238636;
                border-radius: 8px;
                padding: 14px;
            }
        """)
        self.rb_layout = QVBoxLayout(self.card_result_banner)
        self.rb_layout.setSpacing(6)
        res_layout.addWidget(self.card_result_banner)

        # Scroll area for review
        self.res_scroll = QScrollArea()
        self.res_scroll.setWidgetResizable(True)
        self.res_scroll.setStyleSheet("background: transparent; border: none;")
        self.res_scroll_content = QWidget()
        self.res_items_layout = QVBoxLayout(self.res_scroll_content)
        self.res_items_layout.setContentsMargins(0, 0, 0, 0)
        self.res_items_layout.setSpacing(10)
        self.res_scroll.setWidget(self.res_scroll_content)
        res_layout.addWidget(self.res_scroll, stretch=1)

        # Bottom result actions
        b_bar = QHBoxLayout()
        b_bar.setSpacing(12)

        btn_retake = QPushButton("🔄 Neue Klausur erstellen")
        btn_retake.setCursor(Qt.PointingHandCursor)
        btn_retake.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #F0F6FC;
                border: 1px solid #324468;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1F6FEB;
            }
        """)
        btn_retake.clicked.connect(lambda: self.exam_stack.setCurrentIndex(0))
        b_bar.addWidget(btn_retake)

        btn_to_archive = QPushButton("📊 Im Notenspiegel anzeigen")
        btn_to_archive.setCursor(Qt.PointingHandCursor)
        btn_to_archive.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        btn_to_archive.clicked.connect(lambda: self._switch_mode_tab("archive", 4))
        b_bar.addWidget(btn_to_archive)

        b_bar.addStretch()
        res_layout.addLayout(b_bar)

        self.exam_stack.addWidget(self.sub_exam_result)

        layout.addWidget(self.exam_stack)
        return container

    def _start_exam_generation(self) -> None:
        text = self._extract_active_text()
        if not text:
            QMessageBox.warning(self, "Kein Textinhalt", "Bitte wählen Sie ein Werk mit verfügbarem Text aus.")
            return

        title = self.selected_item.get("title", "Fachwerk") if self.selected_item else "Fachwerk"
        chapter = self.current_chapter_title or "Klausurstoff"
        dur_min = int(self.combo_exam_dur.currentData() or 30)
        model_id = self.combo_ai_model.currentData() or ""

        self.lbl_exam_gen_status.setText("⏳ Generiere Klausurfragen & Punkteverteilung via KI...")
        self.btn_start_exam.setEnabled(False)

        self.exam_worker = ExamAiWorkerThread("exam", title, chapter, text, model_id=model_id, duration_min=dur_min, parent=self)
        self.exam_worker.finished_exam.connect(self._on_exam_generated)
        self.exam_worker.error_occurred.connect(self._on_exam_error)
        self.exam_worker.start()

    def _on_exam_error(self, err: str) -> None:
        self.lbl_exam_gen_status.setText(f"⚠️ Fehler: {err[:80]}")
        self.btn_start_exam.setEnabled(True)

    def _on_exam_generated(self, exam_dict: Dict[str, Any]) -> None:
        self.lbl_exam_gen_status.setText("")
        self.btn_start_exam.setEnabled(True)
        self.exam_data = exam_dict
        self.exam_user_answers.clear()

        # Setup Timer
        dur_sec = exam_dict.get("duration_seconds", 30 * 60)
        self.exam_seconds_left = dur_sec
        self.exam_total_seconds = dur_sec
        self._update_timer_label()
        self.exam_timer.start()

        # Build Exam Questions
        while self.exam_questions_layout.count():
            item = self.exam_questions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        questions = exam_dict.get("questions", [])
        total_pts = exam_dict.get("total_points", len(questions) * 5)
        self.lbl_exam_points_stat.setText(f"Gesamtpunkte: {total_pts}")

        for i, q in enumerate(questions):
            q_card = QFrame()
            q_card.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                        stop:0 #141E34, stop:1 #0F1628);
                    border: 1px solid #2A3A5C;
                    border-radius: 12px;
                    padding: 18px;
                }
                QFrame:hover {
                    border: 1px solid #3D5A8A;
                }
            """)
            qc_lay = QVBoxLayout(q_card)
            qc_lay.setSpacing(12)

            # Header strip
            hdr = QHBoxLayout()
            hdr.setSpacing(8)

            num_pill = QLabel(f"  {i + 1}  ")
            num_pill.setFont(QFont("Segoe UI", 11, QFont.Bold))
            num_pill.setStyleSheet("""
                background: #1F6FEB;
                color: #FFFFFF;
                border-radius: 6px;
                padding: 3px 10px;
            """)
            hdr.addWidget(num_pill)

            pts = q.get("points", 5)
            badge_pts = QLabel(f"  {pts} Punkte  ")
            badge_pts.setFont(QFont("Segoe UI", 9, QFont.Bold))
            badge_pts.setStyleSheet("""
                background: #1A1E2E;
                color: #E3B341;
                border: 1px solid #3A3000;
                border-radius: 5px;
                padding: 3px 8px;
            """)
            hdr.addWidget(badge_pts)

            diff = q.get("difficulty", "")
            if diff:
                diff_clean = clean_umlauts(str(diff)).strip()
                if "AFB III" in diff_clean or "Problemlösung" in diff_clean or "Fallstrick" in diff_clean or "Reflexion" in diff_clean:
                    diff_label = "🔥 AFB III • Problemlösung" if "AFB" not in diff_clean else diff_clean
                    diff_col = "#D2A8FF"
                    diff_bg = "#25143A"
                    diff_border = "#5A2F82"
                elif "AFB II" in diff_clean or "Anwendung" in diff_clean or "Transfer" in diff_clean or "Klausurniveau" in diff_clean or "Verständnis" in diff_clean:
                    diff_label = "⚡ AFB II • Transfer & Anwendung" if "AFB" not in diff_clean else diff_clean
                    diff_col = "#58A6FF"
                    diff_bg = "#112240"
                    diff_border = "#1F6FEB"
                else:
                    diff_label = "🎯 AFB I • Reproduktion & Basis" if "AFB" not in diff_clean else diff_clean
                    diff_col = "#3FB950"
                    diff_bg = "#10261E"
                    diff_border = "#238636"

                diff_pill = QLabel(f"  {diff_label}  ")
                diff_pill.setFont(QFont("Segoe UI", 9, QFont.Bold))
                diff_pill.setStyleSheet(f"""
                    background: {diff_bg};
                    color: {diff_col};
                    border: 1px solid {diff_border};
                    border-radius: 6px;
                    padding: 3px 10px;
                """)
                hdr.addWidget(diff_pill)

            hdr.addStretch()
            qc_lay.addLayout(hdr)

            # Separator
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("background-color: #1E2D4A; border: none; max-height: 1px;")
            qc_lay.addWidget(sep)

            # Question text
            q_html = format_latex_html(q.get("question", ""), text_color="#F0F6FC", math_color="#F0F6FC", font_size=12)
            lbl_q_text = QLabel(q_html)
            lbl_q_text.setTextFormat(Qt.RichText)
            lbl_q_text.setFont(QFont("Segoe UI", 12))
            lbl_q_text.setWordWrap(True)
            lbl_q_text.setStyleSheet("color: #F0F6FC; border: none; line-height: 1.45;")
            qc_lay.addWidget(lbl_q_text)

            # Answer option cards (not plain radio buttons)
            btn_grp = QButtonGroup(q_card)
            opts = q.get("options", [])
            option_btns = []
            for opt_idx, opt_text in enumerate(opts):
                opt_letter = chr(65 + opt_idx)
                r_btn = QRadioButton()
                r_btn.setVisible(False)  # hidden, we use card clicks

                opt_card = QFrame()
                opt_card.setObjectName(f"opt_card_{i}_{opt_idx}")
                opt_card.setCursor(Qt.PointingHandCursor)
                opt_card.setStyleSheet("""
                    QFrame {
                        background-color: #0C1220;
                        border: 1px solid #243050;
                        border-radius: 8px;
                        padding: 2px;
                    }
                    QFrame:hover {
                        background-color: #121E38;
                        border: 1px solid #1F6FEB;
                    }
                """)
                opt_lay = QHBoxLayout(opt_card)
                opt_lay.setContentsMargins(12, 8, 12, 8)
                opt_lay.setSpacing(10)

                lbl_letter = QLabel(opt_letter)
                lbl_letter.setFixedWidth(22)
                lbl_letter.setFixedHeight(22)
                lbl_letter.setAlignment(Qt.AlignCenter)
                lbl_letter.setFont(QFont("Segoe UI", 10, QFont.Bold))
                lbl_letter.setStyleSheet("""
                    background: #1A2540;
                    color: #58A6FF;
                    border-radius: 4px;
                """)
                opt_lay.addWidget(lbl_letter)

                opt_html = format_latex_html(opt_text, text_color="#E0E8F5", math_color="#E0E8F5", font_size=11)
                lbl_opt_text = QLabel(opt_html)
                lbl_opt_text.setTextFormat(Qt.RichText)
                lbl_opt_text.setWordWrap(True)
                lbl_opt_text.setStyleSheet("color: #C9D1D9; font-size: 12px; border: none;")
                opt_lay.addWidget(lbl_opt_text, stretch=1)

                # Make card clickable via mouse press event
                def make_click_handler(qi, oi, card, grp, r):
                    def mousePressEvent(ev):
                        grp.setExclusive(False)
                        r.setChecked(True)
                        grp.setExclusive(True)
                        self._on_exam_option_picked(qi, oi)
                        # Highlight selected card
                        for sibling in card.parent().findChildren(QFrame):
                            nm = sibling.objectName()
                            if nm.startswith(f"opt_card_{qi}_"):
                                sibling.setStyleSheet("""
                                    QFrame {
                                        background-color: #0C1220;
                                        border: 1px solid #243050;
                                        border-radius: 8px;
                                        padding: 2px;
                                    }
                                    QFrame:hover {
                                        background-color: #121E38;
                                        border: 1px solid #1F6FEB;
                                    }
                                """)
                        card.setStyleSheet("""
                            QFrame {
                                background-color: #12203A;
                                border: 2px solid #1F6FEB;
                                border-radius: 8px;
                                padding: 2px;
                            }
                        """)
                    return mousePressEvent

                opt_card.mousePressEvent = make_click_handler(i, opt_idx, opt_card, btn_grp, r_btn)
                btn_grp.addButton(r_btn, opt_idx)
                qc_lay.addWidget(opt_card)
                option_btns.append(opt_card)

            self.exam_questions_layout.addWidget(q_card)

        self.exam_questions_layout.addStretch()
        self.exam_stack.setCurrentIndex(1)

    def _on_exam_option_picked(self, q_idx: int, opt_idx: int) -> None:
        self.exam_user_answers[q_idx] = opt_idx

    def _on_exam_timer_tick(self) -> None:
        self.exam_seconds_left -= 1
        self._update_timer_label()
        if self.exam_seconds_left <= 0:
            self.exam_timer.stop()
            self._submit_exam(forced_time_up=True)

    def _update_timer_label(self) -> None:
        mins = max(0, self.exam_seconds_left // 60)
        secs = max(0, self.exam_seconds_left % 60)
        time_str = f"⏱️ Verbleibend: {mins:02d}:{secs:02d}"
        self.lbl_live_timer.setText(time_str)

        if self.exam_seconds_left <= 180:
            self.lbl_live_timer.setStyleSheet("color: #F85149; font-weight: bold; border: none;")
        elif self.exam_seconds_left <= 300:
            self.lbl_live_timer.setStyleSheet("color: #E3B341; font-weight: bold; border: none;")
        else:
            self.lbl_live_timer.setStyleSheet("color: #D2A8FF; font-weight: bold; border: none;")

    def _submit_exam(self, forced_time_up: bool = False) -> None:
        self.exam_timer.stop()
        questions = self.exam_data.get("questions", [])
        total_questions = len(questions)
        earned_points = 0
        total_max_points = 0
        details = []

        for i, q in enumerate(questions):
            pts = q.get("points", 5)
            total_max_points += pts
            c_idx = q.get("correct_index", 0)
            u_idx = self.exam_user_answers.get(i, -1)
            is_correct = (u_idx == c_idx)
            if is_correct:
                earned_points += pts

            opts = q.get("options", [])
            u_str = opts[u_idx] if 0 <= u_idx < len(opts) else "Keine Antwort gegeben"
            c_str = opts[c_idx] if 0 <= c_idx < len(opts) else ""

            details.append({
                "question": q.get("question", ""),
                "correct": is_correct,
                "user_answer": u_str,
                "correct_answer": c_str,
                "explanation": q.get("explanation", ""),
            })

        pct = int((earned_points / total_max_points) * 100) if total_max_points > 0 else 0

        # German Grading Scale
        if pct >= 95:
            grade_str = "1.0 (Sehr gut)"
            passed = True
        elif pct >= 90:
            grade_str = "1.3 (Sehr gut)"
            passed = True
        elif pct >= 85:
            grade_str = "1.7 (Gut)"
            passed = True
        elif pct >= 80:
            grade_str = "2.0 (Gut)"
            passed = True
        elif pct >= 75:
            grade_str = "2.3 (Gut)"
            passed = True
        elif pct >= 70:
            grade_str = "2.7 (Befriedigend)"
            passed = True
        elif pct >= 65:
            grade_str = "3.0 (Befriedigend)"
            passed = True
        elif pct >= 60:
            grade_str = "3.3 (Befriedigend)"
            passed = True
        elif pct >= 55:
            grade_str = "3.7 (Ausreichend)"
            passed = True
        elif pct >= 50:
            grade_str = "4.0 (Ausreichend)"
            passed = True
        else:
            grade_str = "5.0 (Nicht bestanden)"
            passed = False

        xp_gain = max(30, earned_points * 4) if passed else max(15, earned_points * 2)
        add_user_xp(xp_gain)

        # Save to database
        bid = self.selected_item.get("id", "") if self.selected_item else ""
        save_quiz_result(
            bid,
            self.current_chapter_title or "Klausursimulation",
            "klausur_simulation",
            pct,
            grade_str,
            json.dumps({"earned": earned_points, "total": total_max_points, "details": details})
        )

        self._update_gamification_hud()

        # Build Results Page
        while self.rb_layout.count():
            item = self.rb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        res_bg = "#0D1826"
        res_border = "#238636" if passed else "#DA3633"
        self.card_result_banner.setStyleSheet(f"""
            QFrame {{
                background-color: {res_bg};
                border: 2px solid {res_border};
                border-radius: 10px;
                padding: 6px;
            }}
        """)

        banner_inner = QVBoxLayout()
        banner_inner.setSpacing(12)

        # Top row: Left (Title + Subtitle) / Right (Grade badge)
        top_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        lbl_hdr = QLabel(f"🎓 Klausur-Gutachten • {'Bestanden' if passed else 'Nicht bestanden'}")
        lbl_hdr.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_hdr.setStyleSheet(f"color: {'#3FB950' if passed else '#F85149'}; border: none;")
        title_box.addWidget(lbl_hdr)

        lbl_desc = QLabel(f"Prüfungsstoff: {self.current_chapter_title or 'Fachmodul'} • {total_questions} Aufgaben absolviert")
        lbl_desc.setStyleSheet("color: #8B949E; font-size: 11px; border: none;")
        title_box.addWidget(lbl_desc)
        top_row.addLayout(title_box)

        top_row.addStretch()

        # Big Grade pill
        grade_badge = QLabel(f"  Note {grade_str}  ")
        grade_badge.setFont(QFont("Segoe UI", 13, QFont.Bold))
        grade_badge.setStyleSheet(f"""
            background-color: {'#11261B' if passed else '#2A1217'};
            color: {'#3FB950' if passed else '#F85149'};
            border: 2px solid {res_border};
            border-radius: 8px;
            padding: 6px 14px;
        """)
        top_row.addWidget(grade_badge)
        banner_inner.addLayout(top_row)

        # Stat cards strip in result banner
        stat_strip = QHBoxLayout()
        stat_strip.setSpacing(12)

        def make_stat_chip(title: str, val: str, val_col: str):
            f = QFrame()
            f.setStyleSheet("background: #141C2E; border: 1px solid #232F48; border-radius: 6px; padding: 6px 12px;")
            l = QVBoxLayout(f)
            l.setContentsMargins(6, 4, 6, 4)
            l.setSpacing(2)
            t_lbl = QLabel(title)
            t_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
            t_lbl.setStyleSheet("color: #8B949E; border: none;")
            l.addWidget(t_lbl)
            v_lbl = QLabel(val)
            v_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
            v_lbl.setStyleSheet(f"color: {val_col}; border: none;")
            l.addWidget(v_lbl)
            return f

        stat_strip.addWidget(make_stat_chip("ERREICHTE PUNKTE", f"{earned_points} / {total_max_points}", "#58A6FF"))
        stat_strip.addWidget(make_stat_chip("ERFOLGSQUOTE", f"{pct} %", "#3FB950" if passed else "#F85149"))
        stat_strip.addWidget(make_stat_chip("STATUS", "Bestanden ✓" if passed else "Nicht bestanden ✕", "#3FB950" if passed else "#F85149"))
        stat_strip.addWidget(make_stat_chip("BELOHNUNG", f"+{xp_gain} XP", "#E3B341"))
        banner_inner.addLayout(stat_strip)

        # Score progress bar
        pbar = QProgressBar()
        pbar.setRange(0, 100)
        pbar.setValue(pct)
        pbar.setTextVisible(False)
        pbar.setFixedHeight(8)
        pbar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #161F33;
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {'#238636' if passed else '#DA3633'};
                border-radius: 4px;
            }}
        """)
        banner_inner.addWidget(pbar)

        self.rb_layout.addLayout(banner_inner)

        # Build Review Items – premium cards with full LaTeX math rendering
        for idx, d in enumerate(details):
            is_ok = d["correct"]
            border_col = "#238636" if is_ok else "#DA3633"
            bg_col = "#0D1826"
            accent_pill_bg = "rgba(35, 134, 54, 0.15)" if is_ok else "rgba(218, 54, 51, 0.15)"
            stat_col = "#3FB950" if is_ok else "#F85149"
            stat_icon = "✓ Richtig" if is_ok else "✕ Nicht korrekt"
            pts_str = "+5 Punkte" if is_ok else "0 von 5 Punkten"

            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg_col};
                    border: 1px solid #1E2D4A;
                    border-left: 4px solid {border_col};
                    border-radius: 8px;
                    padding: 4px;
                }}
            """)
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(16, 12, 16, 14)
            c_lay.setSpacing(10)

            # Header row: [AUFGABE N]  [Status Pill]  ... [Points badge]
            hdr_row = QHBoxLayout()
            hdr_row.setSpacing(8)

            lbl_num = QLabel(f"AUFGABE {idx + 1}")
            lbl_num.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_num.setStyleSheet("color: #8B949E; border: none; letter-spacing: 0.5px;")
            hdr_row.addWidget(lbl_num)

            stat_pill = QLabel(f" {stat_icon} ")
            stat_pill.setFont(QFont("Segoe UI", 9, QFont.Bold))
            stat_pill.setStyleSheet(f"""
                background-color: {accent_pill_bg};
                color: {stat_col};
                border: 1px solid {border_col};
                border-radius: 4px;
                padding: 2px 8px;
            """)
            hdr_row.addWidget(stat_pill)

            hdr_row.addStretch()

            pts_pill = QLabel(pts_str)
            pts_pill.setFont(QFont("Segoe UI", 9, QFont.Bold))
            pts_pill.setStyleSheet(f"color: {'#3FB950' if is_ok else '#8B949E'}; border: none;")
            hdr_row.addWidget(pts_pill)
            c_lay.addLayout(hdr_row)

            # Question text with LaTeX rendering
            q_html = format_latex_html(d["question"], text_color="#F0F6FC", math_color="#F0F6FC", font_size=12)
            lbl_q = QLabel(q_html)
            lbl_q.setTextFormat(Qt.RichText)
            lbl_q.setWordWrap(True)
            lbl_q.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
            lbl_q.setStyleSheet("color: #F0F6FC; border: none; line-height: 1.4;")
            c_lay.addWidget(lbl_q)

            # Answers container
            ans_box = QFrame()
            ans_box.setStyleSheet(f"""
                QFrame {{
                    background: {'rgba(35, 134, 54, 0.08)' if is_ok else 'rgba(218, 54, 51, 0.08)'};
                    border: 1px solid {'rgba(35, 134, 54, 0.3)' if is_ok else 'rgba(218, 54, 51, 0.3)'};
                    border-radius: 6px;
                }}
            """)
            ans_lay = QVBoxLayout(ans_box)
            ans_lay.setContentsMargins(10, 8, 10, 8)
            ans_lay.setSpacing(6)

            u_html = format_latex_html(d['user_answer'], text_color=stat_col, math_color=stat_col, font_size=11)
            lbl_ans = QLabel(f"<b>Ihre Antwort:</b> {u_html}")
            lbl_ans.setTextFormat(Qt.RichText)
            lbl_ans.setWordWrap(True)
            lbl_ans.setStyleSheet(f"color: {stat_col}; border: none; font-size: 11px;")
            ans_lay.addWidget(lbl_ans)

            if not is_ok:
                c_html = format_latex_html(d['correct_answer'], text_color="#3FB950", math_color="#3FB950", font_size=11)
                lbl_sol = QLabel(f"<b>Musterlösung:</b> {c_html}")
                lbl_sol.setTextFormat(Qt.RichText)
                lbl_sol.setWordWrap(True)
                lbl_sol.setStyleSheet("color: #3FB950; border: none; font-size: 11px;")
                ans_lay.addWidget(lbl_sol)

            c_lay.addWidget(ans_box)

            # Explanation / Herleitung with LaTeX
            if d.get("explanation"):
                expl_box = QFrame()
                expl_box.setStyleSheet("""
                    QFrame {
                        background: rgba(31, 111, 235, 0.07);
                        border: 1px solid rgba(88, 166, 255, 0.22);
                        border-radius: 6px;
                    }
                """)
                expl_lay = QVBoxLayout(expl_box)
                expl_lay.setContentsMargins(10, 8, 10, 8)
                expl_lay.setSpacing(4)

                lbl_expl_hdr = QLabel("💡 Fachliche Herleitung & Begründung:")
                lbl_expl_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
                lbl_expl_hdr.setStyleSheet("color: #58A6FF; border: none;")
                expl_lay.addWidget(lbl_expl_hdr)

                e_html = format_latex_html(d["explanation"], text_color="#C9D1D9", math_color="#C9D1D9", font_size=10)
                lbl_exp = QLabel(e_html)
                lbl_exp.setTextFormat(Qt.RichText)
                lbl_exp.setWordWrap(True)
                lbl_exp.setStyleSheet("color: #C9D1D9; font-size: 11px; border: none; line-height: 1.4;")
                expl_lay.addWidget(lbl_exp)

                c_lay.addWidget(expl_box)

            self.res_items_layout.addWidget(card)

        self.res_items_layout.addStretch()
        self.exam_stack.setCurrentIndex(2)


    # =================================================================
    # PAGE 2: ⚡ ACTIVE RECALL SPEED SPRINT
    # =================================================================
    def _build_active_recall_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        # Header status bar
        top_bar = QFrame()
        top_bar.setStyleSheet("""
            QFrame {
                background: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 10px 14px;
            }
        """)
        tb_lay = QHBoxLayout(top_bar)
        tb_lay.setContentsMargins(6, 2, 6, 2)

        self.lbl_quiz_prog = QLabel("Frage 1 von 5")
        self.lbl_quiz_prog.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_quiz_prog.setStyleSheet("color: #58A6FF; border: none;")
        tb_lay.addWidget(self.lbl_quiz_prog)

        tb_lay.addStretch()

        self.lbl_quiz_score_badge = QLabel("Punkte: 0 / 5 • Streak: 🔥 0")
        self.lbl_quiz_score_badge.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_quiz_score_badge.setStyleSheet("color: #E3B341; border: none;")
        tb_lay.addWidget(self.lbl_quiz_score_badge)

        layout.addWidget(top_bar)

        # Question Presentation Card
        self.card_quiz_q = QFrame()
        self.card_quiz_q.setStyleSheet("""
            QFrame {
                background: #141C2E;
                border: 1px solid #324468;
                border-radius: 10px;
                padding: 18px;
            }
        """)
        qq_lay = QVBoxLayout(self.card_quiz_q)
        qq_lay.setSpacing(12)

        self.lbl_quiz_question_text = QLabel("Klicken Sie auf 'Neues Quiz starten', um 5 Multiple-Choice Fragen zum aktuellen Kapitel zu generieren.")
        self.lbl_quiz_question_text.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_quiz_question_text.setWordWrap(True)
        self.lbl_quiz_question_text.setStyleSheet("color: #F0F6FC; border: none;")
        qq_lay.addWidget(self.lbl_quiz_question_text)

        # 4 Option Buttons – premium card style
        self.quiz_opt_buttons = []
        for i in range(4):
            opt_letter = chr(65 + i)
            opt_frame = QFrame()
            opt_frame.setObjectName(f"quiz_opt_{i}")
            opt_frame.setCursor(Qt.PointingHandCursor)
            opt_frame.setMinimumHeight(52)
            opt_frame.setStyleSheet("""
                QFrame {
                    background-color: #0C1220;
                    border: 1px solid #1E2D4A;
                    border-radius: 10px;
                }
                QFrame:hover {
                    background-color: #111E38;
                    border: 1px solid #1F6FEB;
                }
            """)
            opt_inner = QHBoxLayout(opt_frame)
            opt_inner.setContentsMargins(14, 10, 14, 10)
            opt_inner.setSpacing(12)

            lbl_letter_badge = QLabel(opt_letter)
            lbl_letter_badge.setObjectName(f"quiz_letter_{i}")
            lbl_letter_badge.setFixedSize(28, 28)
            lbl_letter_badge.setAlignment(Qt.AlignCenter)
            lbl_letter_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_letter_badge.setStyleSheet("""
                background: #1A2540;
                color: #58A6FF;
                border-radius: 6px;
            """)
            opt_inner.addWidget(lbl_letter_badge)

            lbl_opt = QLabel(f"Option {opt_letter}")
            lbl_opt.setObjectName(f"quiz_opt_lbl_{i}")
            lbl_opt.setWordWrap(True)
            lbl_opt.setStyleSheet("color: #C9D1D9; font-size: 12px; border: none;")
            opt_inner.addWidget(lbl_opt, stretch=1)

            btn = QPushButton()  # invisible click target
            btn.setObjectName(f"quiz_btn_{i}")
            btn.setFlat(True)
            btn.setStyleSheet("background: transparent; border: none;")
            btn.clicked.connect(lambda checked, idx=i: self._on_quiz_option_clicked(idx))
            btn.setVisible(False)

            opt_frame.setVisible(False)
            qq_lay.addWidget(opt_frame)
            self.quiz_opt_buttons.append(opt_frame)

        # Explanation Box
        self.box_quiz_expl = QFrame()
        self.box_quiz_expl.setStyleSheet("""
            QFrame {
                background-color: #0E1A2D;
                border-left: 4px solid #58A6FF;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        qexp_lay = QVBoxLayout(self.box_quiz_expl)
        self.lbl_quiz_result_tag = QLabel("")
        self.lbl_quiz_result_tag.setFont(QFont("Segoe UI", 11, QFont.Bold))
        qexp_lay.addWidget(self.lbl_quiz_result_tag)
        self.lbl_quiz_explanation = QLabel("")
        self.lbl_quiz_explanation.setWordWrap(True)
        self.lbl_quiz_explanation.setStyleSheet("color: #C9D1D9; font-size: 11px;")
        qexp_lay.addWidget(self.lbl_quiz_explanation)
        self.box_quiz_expl.setVisible(False)
        qq_lay.addWidget(self.box_quiz_expl)

        layout.addWidget(self.card_quiz_q, stretch=1)

        # Bottom Bar: Next / Generate
        b_bar = QHBoxLayout()
        self.btn_gen_quiz = QPushButton("  ⚡ Neues Active-Recall Quiz generieren")
        self.btn_gen_quiz.setIcon(create_vector_icon("sync", "#FFFFFF", 14))
        self.btn_gen_quiz.setCursor(Qt.PointingHandCursor)
        self.btn_gen_quiz.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        self.btn_gen_quiz.clicked.connect(self._generate_active_recall_quiz)
        b_bar.addWidget(self.btn_gen_quiz)

        self.btn_next_quiz_q = QPushButton("Nächste Frage  →")
        self.btn_next_quiz_q.setCursor(Qt.PointingHandCursor)
        self.btn_next_quiz_q.setVisible(False)
        self.btn_next_quiz_q.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)
        self.btn_next_quiz_q.clicked.connect(self._next_quiz_question)
        b_bar.addWidget(self.btn_next_quiz_q)

        b_bar.addStretch()
        layout.addLayout(b_bar)

        return container

    def _generate_active_recall_quiz(self) -> None:
        text = self._extract_active_text()
        if not text:
            QMessageBox.warning(self, "Kein Textinhalt", "Bitte wählen Sie ein Werk mit verfügbarem Text aus.")
            return

        title = self.selected_item.get("title", "Fachwerk") if self.selected_item else "Fachwerk"
        chapter = self.current_chapter_title or "Klausurstoff"
        model_id = self.combo_ai_model.currentData() or ""

        self.lbl_quiz_question_text.setText("⏳ Generiere 5 Active-Recall Fragen aus dem Buchtext...")
        self.btn_gen_quiz.setEnabled(False)

        self.exam_worker = ExamAiWorkerThread("quiz", title, chapter, text, model_id=model_id, parent=self)
        self.exam_worker.finished_quiz.connect(self._on_quiz_generated)
        self.exam_worker.error_occurred.connect(lambda err: self.lbl_quiz_question_text.setText(f"Fehler: {err}"))
        self.exam_worker.start()

    def _on_quiz_generated(self, quiz_data: Dict[str, Any]) -> None:
        self.btn_gen_quiz.setEnabled(True)
        self.quiz_data = quiz_data
        self.quiz_questions = quiz_data.get("questions", [])
        self.quiz_current_idx = 0
        self.quiz_score = 0
        self.quiz_streak = 0
        self._display_quiz_question(0)

    def _display_quiz_question(self, idx: int) -> None:
        if idx >= len(self.quiz_questions):
            self._show_quiz_finished()
            return

        self.quiz_current_idx = idx
        q = self.quiz_questions[idx]
        self.lbl_quiz_prog.setText(f"Frage {idx + 1} von {len(self.quiz_questions)}")
        self.lbl_quiz_score_badge.setText(f"Punkte: {self.quiz_score} / {len(self.quiz_questions)} • Streak: 🔥 {self.quiz_streak}")
        self.lbl_quiz_question_text.setTextFormat(Qt.RichText)
        self.lbl_quiz_question_text.setText(format_latex_html(f"Frage {idx + 1}: {q.get('question', '')}", font_size=12))

        opts = q.get("options", [])
        for i, frm in enumerate(self.quiz_opt_buttons):
            lbl = frm.findChild(QLabel, f"quiz_opt_lbl_{i}")
            if i < len(opts):
                if lbl:
                    lbl.setTextFormat(Qt.RichText)
                    lbl.setText(format_latex_html(opts[i], font_size=11))
                # Reset to neutral style
                frm.setStyleSheet("""
                    QFrame {
                        background-color: #0C1220;
                        border: 1px solid #1E2D4A;
                        border-radius: 10px;
                    }
                    QFrame:hover {
                        background-color: #111E38;
                        border: 1px solid #1F6FEB;
                    }
                """)
                # Reset letter badge color
                letter_lbl = frm.findChild(QLabel, f"quiz_letter_{i}")
                if letter_lbl:
                    letter_lbl.setStyleSheet("""
                        background: #1A2540;
                        color: #58A6FF;
                        border-radius: 6px;
                    """)
                if lbl:
                    lbl.setStyleSheet("color: #C9D1D9; font-size: 12px; border: none;")
                frm.setVisible(True)

                # Connect click
                def make_handler(idx):
                    def mousePressEvent(ev):
                        self._on_quiz_option_clicked(idx)
                    return mousePressEvent
                frm.mousePressEvent = make_handler(i)
            else:
                frm.setVisible(False)

        self.box_quiz_expl.setVisible(False)
        self.btn_next_quiz_q.setVisible(False)

    def _on_quiz_option_clicked(self, selected_idx: int) -> None:
        if self.quiz_current_idx >= len(self.quiz_questions):
            return

        q = self.quiz_questions[self.quiz_current_idx]
        correct_idx = q.get("correct_index", 0)

        # Disable all further clicks
        for frm in self.quiz_opt_buttons:
            frm.mousePressEvent = lambda ev: None

        # Highlight correct answer GREEN
        if 0 <= correct_idx < len(self.quiz_opt_buttons):
            frm_c = self.quiz_opt_buttons[correct_idx]
            frm_c.setStyleSheet("""
                QFrame {
                    background-color: #0D1F14;
                    border: 2px solid #238636;
                    border-radius: 10px;
                }
            """)
            lc = frm_c.findChild(QLabel, f"quiz_letter_{correct_idx}")
            if lc:
                lc.setStyleSheet("background: #238636; color: #FFFFFF; border-radius: 6px;")
            ll = frm_c.findChild(QLabel, f"quiz_opt_lbl_{correct_idx}")
            if ll:
                ll.setStyleSheet("color: #3FB950; font-size: 12px; font-weight: bold; border: none;")

        is_correct = (selected_idx == correct_idx)
        if is_correct:
            self.quiz_score += 1
            self.quiz_streak += 1
            self.lbl_quiz_result_tag.setText("Richtig! Hervorragend.")
            self.lbl_quiz_result_tag.setStyleSheet("color: #3FB950; font-weight: bold; font-size: 13px; border: none;")
            add_user_xp(20)
        else:
            self.quiz_streak = 0
            if 0 <= selected_idx < len(self.quiz_opt_buttons):
                frm_w = self.quiz_opt_buttons[selected_idx]
                frm_w.setStyleSheet("""
                    QFrame {
                        background-color: #200C0C;
                        border: 2px solid #DA3633;
                        border-radius: 10px;
                    }
                """)
                lw = frm_w.findChild(QLabel, f"quiz_letter_{selected_idx}")
                if lw:
                    lw.setStyleSheet("background: #DA3633; color: #FFFFFF; border-radius: 6px;")
                ll_w = frm_w.findChild(QLabel, f"quiz_opt_lbl_{selected_idx}")
                if ll_w:
                    ll_w.setStyleSheet("color: #F85149; font-size: 12px; font-weight: bold; border: none;")
            opts = q.get("options", [])
            c_str = opts[correct_idx] if 0 <= correct_idx < len(opts) else ""
            self.lbl_quiz_result_tag.setText(f"Falsch. Richtig war: {chr(65+correct_idx)}) {c_str[:60]}")
            self.lbl_quiz_result_tag.setStyleSheet("color: #F85149; font-weight: bold; font-size: 12px; border: none;")

        self.lbl_quiz_explanation.setTextFormat(Qt.RichText)
        self.lbl_quiz_explanation.setText(format_latex_html(q.get("explanation", ""), font_size=11))
        self.box_quiz_expl.setVisible(True)
        self.btn_next_quiz_q.setVisible(True)
        self.lbl_quiz_score_badge.setText(f"Punkte: {self.quiz_score} / {len(self.quiz_questions)} \u2022 Streak: {self.quiz_streak}")
        self._update_gamification_hud()

    def _next_quiz_question(self) -> None:
        self._display_quiz_question(self.quiz_current_idx + 1)

    def _show_quiz_finished(self) -> None:
        total = len(self.quiz_questions) if self.quiz_questions else 5
        pct = int((self.quiz_score / total) * 100) if total > 0 else 0
        self.lbl_quiz_question_text.setText(
            f"Quiz abgeschlossen!\nErgebnis: {self.quiz_score} von {total} richtig ({pct}%)."
        )
        for frm in self.quiz_opt_buttons:
            frm.setVisible(False)
        self.box_quiz_expl.setVisible(False)
        self.btn_next_quiz_q.setVisible(False)

        grade = "1.0 (Sehr gut)" if pct >= 90 else ("2.0 (Gut)" if pct >= 70 else ("3.0 (Befriedigend)" if pct >= 50 else "5.0 (Wiederholen)"))
        bid = self.selected_item.get("id", "") if self.selected_item else ""
        save_quiz_result(bid, self.current_chapter_title or "Active Recall", "active_recall", pct, grade, json.dumps(self.quiz_questions))
        self._update_gamification_hud()

    # =================================================================
    # PAGE 3: 🎙️ SOKRATISCHE MÜNDLICHE PRÜFUNG
    # =================================================================
    def _build_socratic_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # Dialog History View
        self.soc_scroll = QScrollArea()
        self.soc_scroll.setWidgetResizable(True)
        self.soc_scroll.setStyleSheet("background: #0B0F19; border: 1px solid #232F48; border-radius: 8px;")
        self.soc_content = QWidget()
        self.soc_layout = QVBoxLayout(self.soc_content)
        self.soc_layout.setContentsMargins(12, 12, 12, 12)
        self.soc_layout.setSpacing(12)
        self.soc_layout.addStretch()
        self.soc_scroll.setWidget(self.soc_content)
        layout.addWidget(self.soc_scroll, stretch=1)

        # Bottom Input Area
        input_bar = QFrame()
        input_bar.setStyleSheet("""
            QFrame {
                background: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        ib_lay = QHBoxLayout(input_bar)
        ib_lay.setSpacing(10)

        self.txt_socratic_input = QPlainTextEdit()
        self.txt_socratic_input.setFixedHeight(50)
        self.txt_socratic_input.setPlaceholderText("Formulieren Sie Ihre Antwort an den Professor (Strg+Enter zum Senden)...")
        self.txt_socratic_input.setStyleSheet("""
            QPlainTextEdit {
                background: #0B0F19;
                color: #F0F6FC;
                border: 1px solid #324468;
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
            }
        """)
        ib_lay.addWidget(self.txt_socratic_input, stretch=1)

        b_vbox = QVBoxLayout()
        b_vbox.setSpacing(4)

        self.btn_send_socratic = QPushButton("  Antworten")
        self.btn_send_socratic.setCursor(Qt.PointingHandCursor)
        self.btn_send_socratic.setFixedHeight(28)
        self.btn_send_socratic.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 5px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        self.btn_send_socratic.clicked.connect(self._send_socratic_answer)
        b_vbox.addWidget(self.btn_send_socratic)

        self.btn_start_socratic = QPushButton("Prüfung starten")
        self.btn_start_socratic.setCursor(Qt.PointingHandCursor)
        self.btn_start_socratic.setFixedHeight(24)
        self.btn_start_socratic.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #58A6FF;
                border: 1px solid #324468;
                border-radius: 5px;
                padding: 2px 8px;
                font-size: 11px;
            }
        """)
        self.btn_start_socratic.clicked.connect(self._start_socratic_exam)
        b_vbox.addWidget(self.btn_start_socratic)

        ib_lay.addLayout(b_vbox)
        layout.addWidget(input_bar)

        return container

    def _start_socratic_exam(self) -> None:
        text = self._extract_active_text()
        if not text:
            QMessageBox.warning(self, "Kein Textinhalt", "Bitte wählen Sie ein Werk mit verfügbarem Text aus.")
            return

        title = self.selected_item.get("title", "Fachwerk") if self.selected_item else "Fachwerk"
        chapter = self.current_chapter_title or "Klausurstoff"
        model_id = self.combo_ai_model.currentData() or ""

        # Clear chat
        while self.soc_layout.count() > 1:
            item = self.soc_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.socratic_history.clear()
        self.socratic_turn_count = 0

        self._add_socratic_bubble("assistant", f"Guten Tag! Lassen Sie uns heute über das Kapitel '{chapter}' aus dem Werk '{title}' sprechen. Erläutern Sie mir bitte zu Beginn die zentrale Grundidee oder Fragestellung dieses Abschnitts in eigenen Worten.")

    def _send_socratic_answer(self) -> None:
        user_msg = self.txt_socratic_input.toPlainText().strip()
        if not user_msg:
            return

        self._add_socratic_bubble("user", user_msg)
        self.txt_socratic_input.clear()
        self.btn_send_socratic.setEnabled(False)

        text = self._extract_active_text()
        title = self.selected_item.get("title", "Fachwerk") if self.selected_item else "Fachwerk"
        chapter = self.current_chapter_title or "Klausurstoff"
        model_id = self.combo_ai_model.currentData() or ""

        self.socratic_worker = SocraticWorkerThread(title, chapter, text, self.socratic_history, model_id=model_id, parent=self)
        self.socratic_worker.finished_turn.connect(self._on_socratic_response)
        self.socratic_worker.error_occurred.connect(lambda err: self._add_socratic_bubble("assistant", f"⚠️ Fehler: {err}"))
        self.socratic_worker.start()

    def _on_socratic_response(self, resp_dict: Dict[str, Any]) -> None:
        self.btn_send_socratic.setEnabled(True)
        msg = resp_dict.get("professor_message", "")
        self._add_socratic_bubble("assistant", msg)
        self.socratic_turn_count += 1

        if resp_dict.get("is_exam_finished") or self.socratic_turn_count >= 4:
            grade = resp_dict.get("final_grade") or "2.0 (Gut)"
            feedback = resp_dict.get("feedback_summary") or "Mündliche Prüfung erfolgreich beendet."
            self._add_socratic_bubble("assistant", f"🎓 **Prüfungsergebnis:** Note {grade}\n\n*Gutachten:* {feedback}")
            add_user_xp(50)
            bid = self.selected_item.get("id", "") if self.selected_item else ""
            save_quiz_result(bid, self.current_chapter_title or "Mündliche Prüfung", "oral_exam", 80, str(grade), json.dumps(self.socratic_history))
            self._update_gamification_hud()

    def _add_socratic_bubble(self, role: str, text: str) -> None:
        self.socratic_history.append({"role": role, "content": text})

        bubble = QFrame()
        is_user = (role == "user")
        bg_col = "#142542" if is_user else "#121A28"
        border_col = "#1F6FEB" if is_user else "#324468"

        bubble.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_col};
                border: 1px solid {border_col};
                border-radius: 8px;
                padding: 10px 14px;
            }}
        """)
        b_lay = QVBoxLayout(bubble)
        b_lay.setSpacing(4)

        sender_label = "Sie (Prüfling):" if is_user else "Herr Prof. Dr. KI (Prüfer):"
        sender_col = "#58A6FF" if is_user else "#E3B341"
        lbl_s = QLabel(sender_label)
        lbl_s.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_s.setStyleSheet(f"color: {sender_col}; border: none;")
        b_lay.addWidget(lbl_s)

        lbl_t = QLabel(text)
        lbl_t.setFont(QFont("Segoe UI", 11))
        lbl_t.setWordWrap(True)
        lbl_t.setStyleSheet("color: #F0F6FC; border: none; line-height: 1.3;")
        b_lay.addWidget(lbl_t)

        self.soc_layout.insertWidget(self.soc_layout.count() - 1, bubble)
        QTimer.singleShot(50, lambda: self.soc_scroll.verticalScrollBar().setValue(self.soc_scroll.verticalScrollBar().maximum()))

    # =================================================================
    # PAGE 4: 📑 1-PAGE SPICKZETTEL / FORMELSAMMLUNG
    # =================================================================
    def _build_cheat_sheet_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        # Action bar
        top_bar = QHBoxLayout()
        self.btn_gen_cheat = QPushButton("  📑 Spickzettel / Formelsammlung generieren")
        self.btn_gen_cheat.setIcon(create_vector_icon("notes", "#FFFFFF", 14))
        self.btn_gen_cheat.setCursor(Qt.PointingHandCursor)
        self.btn_gen_cheat.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        self.btn_gen_cheat.clicked.connect(self._generate_cheat_sheet)
        top_bar.addWidget(self.btn_gen_cheat)

        btn_copy = QPushButton("  In Zwischenablage kopieren")
        btn_copy.setIcon(create_vector_icon("copy", "#58A6FF", 14))
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #F0F6FC;
                border: 1px solid #324468;
                border-radius: 6px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background: #1F2A42;
            }
        """)
        btn_copy.clicked.connect(self._copy_cheat_sheet)
        top_bar.addWidget(btn_copy)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        self.txt_cheat_sheet = QPlainTextEdit()
        self.txt_cheat_sheet.setReadOnly(True)
        self.txt_cheat_sheet.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0E1422;
                color: #F0F6FC;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 16px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        self.txt_cheat_sheet.setPlainText("# 📑 1-Page Klausur-Spickzettel\n\nWählen Sie ein Kapitel aus und klicken Sie auf 'Spickzettel generieren'.")
        layout.addWidget(self.txt_cheat_sheet, stretch=1)

        return container

    def _generate_cheat_sheet(self) -> None:
        text = self._extract_active_text()
        if not text:
            QMessageBox.warning(self, "Kein Textinhalt", "Bitte wählen Sie ein Werk mit verfügbarem Text aus.")
            return

        title = self.selected_item.get("title", "Fachwerk") if self.selected_item else "Fachwerk"
        chapter = self.current_chapter_title or "Klausurstoff"
        model_id = self.combo_ai_model.currentData() or ""

        self.txt_cheat_sheet.setPlainText("⏳ Extrahiere Formeln, Theoreme, Klausurfallen und Definitionen...")
        self.btn_gen_cheat.setEnabled(False)

        self.exam_worker = ExamAiWorkerThread("cheat_sheet", title, chapter, text, model_id=model_id, parent=self)
        self.exam_worker.finished_cheat_sheet.connect(self._on_cheat_sheet_generated)
        self.exam_worker.error_occurred.connect(lambda err: self.txt_cheat_sheet.setPlainText(f"Fehler: {err}"))
        self.exam_worker.start()

    def _on_cheat_sheet_generated(self, markdown_text: str) -> None:
        self.btn_gen_cheat.setEnabled(True)
        self.txt_cheat_sheet.setPlainText(markdown_text)
        add_user_xp(15)
        self._update_gamification_hud()

    def _copy_cheat_sheet(self) -> None:
        text = self.txt_cheat_sheet.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Kopiert", "Spickzettel erfolgreich in die Zwischenablage kopiert!")

    # =================================================================
    # PAGE 5: 📊 KLAUSUR-ARCHIV & NOTENSPIEGEL (ANALYTICS & REVIEW)
    # =================================================================
    def _build_archive_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        # Analytics KPI Dashboard Strip
        kpi_strip = QFrame()
        kpi_strip.setStyleSheet("background: transparent; border: none;")
        ks_lay = QHBoxLayout(kpi_strip)
        ks_lay.setContentsMargins(0, 0, 0, 0)
        ks_lay.setSpacing(14)

        def make_kpi_card(title: str, sub: str, accent: str, lbl_obj: QLabel) -> QFrame:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background: #111726;
                    border: 1px solid #232F48;
                    border-top: 3px solid {accent};
                    border-radius: 8px;
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(4)
            lbl_t = QLabel(title)
            lbl_t.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_t.setStyleSheet("color: #8B949E; border: none; letter-spacing: 0.5px;")
            cl.addWidget(lbl_t)
            lbl_obj.setFont(QFont("Segoe UI", 18, QFont.Bold))
            lbl_obj.setStyleSheet(f"color: {accent}; border: none;")
            cl.addWidget(lbl_obj)
            lbl_s = QLabel(sub)
            lbl_s.setStyleSheet("color: #6E7681; font-size: 10px; border: none;")
            cl.addWidget(lbl_s)
            return card

        self.lbl_arch_total = QLabel("0")
        self.lbl_arch_pass = QLabel("0.0 %")
        self.lbl_arch_gpa = QLabel("—")
        self.lbl_arch_avg_score = QLabel("0 %")

        ks_lay.addWidget(make_kpi_card("ABSOLVIERTE KLAUSUREN", "Gesamtprüfungen im Archiv", "#58A6FF", self.lbl_arch_total))
        ks_lay.addWidget(make_kpi_card("BESTEHENSQUOTE", "Erfolgreich abgeschlossen (>= 50 %)", "#3FB950", self.lbl_arch_pass))
        ks_lay.addWidget(make_kpi_card("Ø NOTENSPIEGEL (GPA)", "Deutscher Notendurchschnitt", "#E3B341", self.lbl_arch_gpa))
        ks_lay.addWidget(make_kpi_card("DURCHSCHN. ERGEBNIS", "Mittlerer Punktewert", "#D2A8FF", self.lbl_arch_avg_score))

        layout.addWidget(kpi_strip)

        # Filter bar
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)

        lbl_f = QLabel("Filter:")
        lbl_f.setStyleSheet("color: #8B949E; font-weight: bold;")
        filter_bar.addWidget(lbl_f)

        self.combo_hist_filter = QComboBox()
        self.combo_hist_filter.addItem("Alle Prüfungsarten", None)
        self.combo_hist_filter.addItem("Klausursimulationen", "klausur_simulation")
        self.combo_hist_filter.addItem("Active Recall Quizzes", "active_recall")
        self.combo_hist_filter.addItem("Mündliche Prüfungen", "oral_exam")
        self.combo_hist_filter.setStyleSheet("""
            QComboBox {
                background: #0B0F19;
                border: 1px solid #324468;
                border-radius: 6px;
                color: #F0F6FC;
                padding: 4px 10px;
                font-size: 12px;
            }
        """)
        self.combo_hist_filter.currentIndexChanged.connect(self._load_archive_data)
        filter_bar.addWidget(self.combo_hist_filter)

        filter_bar.addStretch()

        btn_refresh = QPushButton("  Aktualisieren")
        btn_refresh.setIcon(create_vector_icon("sync", "#58A6FF", 12))
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background: #141C2E;
                color: #F0F6FC;
                border: 1px solid #324468;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #1F2A42;
            }
        """)
        btn_refresh.clicked.connect(self._load_archive_data)
        filter_bar.addWidget(btn_refresh)

        layout.addLayout(filter_bar)

        # Table of history
        self.table_history = QTableWidget()
        self.table_history.setColumnCount(7)
        self.table_history.setHorizontalHeaderLabels([
            "Datum", "Prüfungsstoff (Werk & Thema)", "Modus", "Ergebnis", "Note", "Aktionen", "ID"
        ])
        self.table_history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_history.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table_history.setColumnWidth(2, 145)
        self.table_history.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table_history.setColumnWidth(3, 105)
        self.table_history.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table_history.setColumnWidth(4, 140)
        self.table_history.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.table_history.setColumnWidth(5, 175)
        self.table_history.setColumnHidden(6, True)
        self.table_history.verticalHeader().setDefaultSectionSize(48)
        self.table_history.verticalHeader().setVisible(False)
        self.table_history.setItemDelegate(NoFocusItemDelegate(self.table_history))
        self.table_history.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_history.setAlternatingRowColors(True)
        self.table_history.setStyleSheet("""
            QTableWidget {
                background-color: #0E1422;
                alternate-background-color: #121826;
                color: #F0F6FC;
                border: 1px solid #232F48;
                border-radius: 8px;
                gridline-color: #1A243B;
            }
            QHeaderView::section {
                background-color: #141C2E;
                color: #8B949E;
                border: none;
                border-bottom: 2px solid #232F48;
                padding: 8px 10px;
                font-weight: bold;
                font-size: 11px;
                letter-spacing: 0.5px;
            }
        """)
        self.table_history.doubleClicked.connect(self._on_archive_row_double_click)
        layout.addWidget(self.table_history, stretch=1)

        return container

    def _load_archive_data(self) -> None:
        filt = self.combo_hist_filter.currentData()
        records = get_quiz_history(limit=150, mode_filter=filt)
        stats = get_exam_statistics()

        # Update KPI Cards
        self.lbl_arch_total.setText(str(stats.get("total_exams", 0)))
        self.lbl_arch_pass.setText(f"{stats.get('pass_rate', 0.0):.1f} %")
        gpa = stats.get("gpa", 0.0)
        self.lbl_arch_gpa.setText(f"{gpa:.2f}" if gpa > 0 else "—")
        self.lbl_arch_avg_score.setText(f"{stats.get('avg_percent', 0.0):.1f} %")

        self.table_history.setRowCount(0)
        for r_idx, r in enumerate(records):
            self.table_history.insertRow(r_idx)
            dt_str = time.strftime("%d.%m.%Y %H:%M", time.localtime(r.get("created_at", time.time())))
            title_text = f"{r.get('source_title', 'Werk')} • {r.get('chapter_title', '')}"
            mode_raw = r.get("mode", "")
            mode_display = "Klausursimulation" if mode_raw == "klausur_simulation" else ("Active Recall" if mode_raw == "active_recall" else "Mündliche Prüfung")
            score_text = f"{r.get('score_percent', 0)} %"
            grade_text = r.get("grade", "—")

            item_dt = QTableWidgetItem(dt_str)
            item_dt.setTextAlignment(Qt.AlignCenter)
            self.table_history.setItem(r_idx, 0, item_dt)

            item_tit = QTableWidgetItem(title_text)
            self.table_history.setItem(r_idx, 1, item_tit)

            # Modus Pill Badge
            mod_widget = QWidget()
            mod_lay = QHBoxLayout(mod_widget)
            mod_lay.setContentsMargins(4, 4, 4, 4)
            mod_lay.setAlignment(Qt.AlignCenter)
            lbl_mod_pill = QLabel(mode_display)
            lbl_mod_pill.setFont(QFont("Segoe UI", 9, QFont.Bold))
            if mode_raw == "klausur_simulation":
                m_bg = "rgba(31, 111, 235, 0.15)"
                m_border = "rgba(88, 166, 255, 0.35)"
                m_col = "#58A6FF"
            elif mode_raw == "active_recall":
                m_bg = "rgba(217, 119, 6, 0.15)"
                m_border = "rgba(245, 158, 11, 0.35)"
                m_col = "#F59E0B"
            else:
                m_bg = "rgba(168, 85, 247, 0.15)"
                m_border = "rgba(192, 132, 252, 0.35)"
                m_col = "#C084FC"
            lbl_mod_pill.setStyleSheet(f"""
                background: {m_bg};
                color: {m_col};
                border: 1px solid {m_border};
                border-radius: 10px;
                padding: 3px 10px;
            """)
            mod_lay.addWidget(lbl_mod_pill)
            self.table_history.setCellWidget(r_idx, 2, mod_widget)

            # Score Pill Badge
            sc_widget = QWidget()
            sc_lay = QHBoxLayout(sc_widget)
            sc_lay.setContentsMargins(4, 4, 4, 4)
            sc_lay.setAlignment(Qt.AlignCenter)
            lbl_sc_pill = QLabel(score_text)
            lbl_sc_pill.setFont(QFont("Segoe UI", 10, QFont.Bold))
            pct_val = r.get('score_percent', 0)
            if pct_val >= 80:
                s_col = "#3FB950"
                s_bg = "rgba(63, 185, 80, 0.15)"
                s_border = "rgba(63, 185, 80, 0.35)"
            elif pct_val >= 50:
                s_col = "#E3B341"
                s_bg = "rgba(227, 179, 65, 0.15)"
                s_border = "rgba(227, 179, 65, 0.35)"
            else:
                s_col = "#F85149"
                s_bg = "rgba(248, 81, 73, 0.15)"
                s_border = "rgba(248, 81, 73, 0.35)"
            lbl_sc_pill.setStyleSheet(f"""
                background: {s_bg};
                color: {s_col};
                border: 1px solid {s_border};
                border-radius: 10px;
                padding: 3px 10px;
            """)
            sc_lay.addWidget(lbl_sc_pill)
            self.table_history.setCellWidget(r_idx, 3, sc_widget)

            # Grade Pill Badge
            gr_widget = QWidget()
            gr_lay = QHBoxLayout(gr_widget)
            gr_lay.setContentsMargins(4, 4, 4, 4)
            gr_lay.setAlignment(Qt.AlignCenter)
            lbl_gr_pill = QLabel(f" {grade_text} ")
            lbl_gr_pill.setFont(QFont("Segoe UI", 9, QFont.Bold))
            if "1." in grade_text or "2." in grade_text:
                g_col = "#3FB950"
                g_bg = "rgba(63, 185, 80, 0.15)"
                g_border = "rgba(63, 185, 80, 0.35)"
            elif "3." in grade_text or "4." in grade_text:
                g_col = "#E3B341"
                g_bg = "rgba(227, 179, 65, 0.15)"
                g_border = "rgba(227, 179, 65, 0.35)"
            else:
                g_col = "#F85149"
                g_bg = "rgba(248, 81, 73, 0.15)"
                g_border = "rgba(248, 81, 73, 0.35)"
            lbl_gr_pill.setStyleSheet(f"""
                background: {g_bg};
                color: {g_col};
                border: 1px solid {g_border};
                border-radius: 10px;
                padding: 3px 10px;
            """)
            gr_lay.addWidget(lbl_gr_pill)
            self.table_history.setCellWidget(r_idx, 4, gr_widget)

            # Action button widget (Gutachten & Löschen)
            act_widget = QWidget()
            act_lay = QHBoxLayout(act_widget)
            act_lay.setContentsMargins(6, 4, 6, 4)
            act_lay.setSpacing(8)

            btn_view = QPushButton(" Gutachten")
            btn_view.setIcon(create_vector_icon("book", "#FFFFFF", 12))
            btn_view.setCursor(Qt.PointingHandCursor)
            btn_view.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #238636);
                    color: #FFFFFF;
                    font-weight: bold;
                    font-size: 11px;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388BFD, stop:1 #2EA043);
                }
                QPushButton:pressed {
                    background: #1A56B5;
                }
            """)
            btn_view.clicked.connect(lambda ch, item=r: self._open_archive_detail(item))
            act_lay.addWidget(btn_view)

            btn_del = QPushButton("✕")
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setToolTip("Diesen Eintrag dauerhaft aus dem Archiv löschen")
            btn_del.setStyleSheet("""
                QPushButton {
                    background: rgba(248, 81, 73, 0.12);
                    color: #F85149;
                    border: 1px solid rgba(248, 81, 73, 0.3);
                    border-radius: 6px;
                    padding: 5px 9px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #DA3633;
                    color: #FFFFFF;
                    border-color: #DA3633;
                }
            """)
            btn_del.clicked.connect(lambda ch, hid=r.get("id"): self._delete_archive_entry(hid))
            act_lay.addWidget(btn_del)

            self.table_history.setCellWidget(r_idx, 5, act_widget)

            # Hidden ID
            self.table_history.setItem(r_idx, 6, QTableWidgetItem(str(r.get("id", ""))))

    def _on_archive_row_double_click(self, index) -> None:
        r_idx = index.row()
        id_item = self.table_history.item(r_idx, 6)
        if not id_item:
            return
        hid = int(id_item.text())
        records = get_quiz_history(limit=150)
        found = next((r for r in records if r.get("id") == hid), None)
        if found:
            self._open_archive_detail(found)

    def _open_archive_detail(self, item: Dict[str, Any]) -> None:
        dlg = ExamArchiveDetailDialog(item, self)
        dlg.exec()

    def _delete_archive_entry(self, history_id: int) -> None:
        confirm = QMessageBox.question(
            self, "Eintrag löschen", "Möchten Sie diesen Prüfungseintrag unwiderruflich aus dem Archiv löschen?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            delete_quiz_history_item(history_id)
            self._load_archive_data()
            self._update_gamification_hud()
