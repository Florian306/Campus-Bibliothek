"""Interactive AI Tutor, Exam Simulation & Quiz Studio Dialog for PySide6.
Features Active Recall Multiple-Choice Quizzes, Timed Exam Simulators with Real Evaluation & Grading,
Socratic Oral Examinations, and Intelligent Substantive Topic Selection.
"""

import json
import time
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, QTimer, QSize, Signal, QThread
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QStackedWidget,
    QPlainTextEdit,
    QLineEdit,
    QWidget,
    QFrame,
    QScrollArea,
    QApplication,
    QComboBox,
    QButtonGroup,
)

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from ui.qt.theme import NoFocusItemDelegate
from core.library_db import (
    open_pdf_in_edge,
    get_book_pair,
    save_quiz_result,
    add_user_xp,
    get_gamification_profile,
)
from core.config import load_config, save_config
from ai.book_pairing import is_exercise_book
from ai.tutor_engine import (
    extract_chapter_text,
    get_book_substantive_chapters,
    get_available_ai_models,
    generate_active_recall_quiz,
    generate_exam_simulation,
    generate_socratic_turn,
    generate_cheat_sheet,
)


class TutorWorkerThread(QThread):
    finished_quiz = Signal(dict)
    finished_exam = Signal(dict)
    finished_cheat_sheet = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, mode: str, book_title: str, chapter_title: str, text: str, model_id: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.book_title = book_title
        self.chapter_title = chapter_title
        self.text = text
        self.model_id = model_id

    def run(self):
        try:
            if self.mode == "quiz":
                res = generate_active_recall_quiz(
                    self.book_title, self.chapter_title, self.text, num_questions=5, model_id=self.model_id
                )
                self.finished_quiz.emit(res)
            elif self.mode == "exam":
                res = generate_exam_simulation(
                    self.book_title, self.chapter_title, self.text, duration_minutes=20, model_id=self.model_id
                )
                self.finished_exam.emit(res)
            elif self.mode == "cheat_sheet":
                res = generate_cheat_sheet(
                    self.book_title, self.chapter_title, self.text, model_id=self.model_id
                )
                self.finished_cheat_sheet.emit(res)
        except Exception as e:
            self.error_occurred.emit(str(e))


class TutorStudioDialog(QDialog):
    """Flagship AI Tutor Studio modal for textbook mastery and exam readiness."""

    xp_gained = Signal(int)

    def __init__(self, book: Dict[str, Any], initial_mode: str = "quiz", parent=None):
        super().__init__(parent)
        self.book = book
        self.book_id = str(book.get("id", ""))
        self.book_title = book.get("title", "Fachbuch")
        self.file_path = book.get("file_path", "")
        self.initial_mode = initial_mode

        self.setWindowTitle(f"KI-Tutor & Prüfungs-Studio • {self.book_title}")
        self.resize(920, 680)
        self.setStyleSheet("""
            QDialog {
                background-color: #0E1422;
                border: 1px solid #232F48;
            }
        """)

        # State
        self.curr_chapter = "Kapitel & Kernaussagen"
        curr_p = max(1, int(book.get("current_page") or 1))
        self.start_page = curr_p
        page_cnt = max(1, int(book.get("page_count") or (self.start_page + 20)))
        self.end_page = min(page_cnt, self.start_page + 20)
        self.chapter_text = ""
        self.available_chapters: List[Dict[str, Any]] = []

        # Quiz State
        self.quiz_data = {}
        self.quiz_questions = []
        self.current_q_idx = 0
        self.score = 0
        self.selected_option = -1
        self.is_answered = False

        # Exam State
        self.exam_timer = QTimer(self)
        self.exam_timer.setInterval(1000)
        self.exam_timer.timeout.connect(self._on_exam_tick)
        self.exam_seconds_left = 1200
        self.exam_question_widgets: List[Dict[str, Any]] = []

        # Socratic State
        self.socratic_history: List[Dict[str, str]] = []
        self.active_worker: Optional[TutorWorkerThread] = None

        self._build_ui()
        self._populate_chapters()
        self._populate_ai_models()
        self._set_active_mode(self.initial_mode)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(22, 18, 22, 18)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # 1. Header Bar: Title & Gamification Mini-Banner
        # -------------------------------------------------------------
        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header_row.setAlignment(Qt.AlignVCenter)

        icon_tutor = QLabel()
        icon_tutor.setPixmap(create_vector_pixmap("notes", "#58A6FF", 22))
        icon_tutor.setStyleSheet("border: none; background: transparent;")
        header_row.addWidget(icon_tutor)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_h = QLabel(self.book_title)
        lbl_h.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_h.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
        title_box.addWidget(lbl_h)

        self.lbl_sub = QLabel(f"Seiten {self.start_page} bis {self.end_page} • Interaktives Prüfungs-Studio")
        self.lbl_sub.setFont(QFont("Segoe UI", 10))
        self.lbl_sub.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        title_box.addWidget(self.lbl_sub)
        header_row.addLayout(title_box, stretch=1)

        # Gamification Pill
        prof = get_gamification_profile()
        self.lbl_gamification = QLabel(f"🔥 {prof.get('current_streak', 0)} Tage Streak  •  {prof.get('title', 'Ersti')} ({prof.get('total_xp', 0)} XP)")
        self.lbl_gamification.setStyleSheet("""
            QLabel {
                background-color: #162035;
                color: #58A6FF;
                border: 1px solid #2B3D66;
                border-radius: 12px;
                padding: 5px 12px;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        header_row.addWidget(self.lbl_gamification)

        main_layout.addLayout(header_row)

        # -------------------------------------------------------------
        # 1.1 Topic / Chapter & AI Model Selector Bar
        # -------------------------------------------------------------
        ch_selector_box = QFrame()
        ch_selector_box.setStyleSheet("""
            QFrame {
                background-color: #121929;
                border: 1px solid #202D47;
                border-radius: 8px;
            }
        """)
        ch_layout = QHBoxLayout(ch_selector_box)
        ch_layout.setContentsMargins(12, 6, 12, 6)
        ch_layout.setSpacing(10)
        ch_layout.setAlignment(Qt.AlignVCenter)

        lbl_ch_title = QLabel("📖 Thema / Kapitel:")
        lbl_ch_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_ch_title.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        ch_layout.addWidget(lbl_ch_title)

        self.combo_chapter = QComboBox()
        self.combo_chapter.setCursor(Qt.PointingHandCursor)
        self.combo_chapter.setStyleSheet("""
            QComboBox {
                background-color: #0E1422;
                color: #F0F6FC;
                border: 1px solid #2B3D66;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 600;
                min-height: 28px;
            }
            QComboBox:hover {
                border-color: #58A6FF;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #0E1422;
                color: #F0F6FC;
                border: 1px solid #2B3D66;
                selection-background-color: #1F365A;
                selection-color: #58A6FF;
                padding: 4px;
            }
        """)
        self.combo_chapter.currentIndexChanged.connect(self._on_chapter_changed)
        ch_layout.addWidget(self.combo_chapter, stretch=1)

        # AI Model Dropdown
        lbl_ai = QLabel("🤖 KI-Modell:")
        lbl_ai.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_ai.setStyleSheet("color: #79C0FF; border: none; background: transparent;")
        ch_layout.addWidget(lbl_ai)

        self.combo_ai_model = QComboBox()
        self.combo_ai_model.setCursor(Qt.PointingHandCursor)
        self.combo_ai_model.setStyleSheet("""
            QComboBox {
                background-color: #0E1422;
                color: #58A6FF;
                border: 1px solid #2B3D66;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 600;
                min-height: 28px;
            }
            QComboBox:hover {
                border-color: #58A6FF;
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QComboBox QAbstractItemView {
                background-color: #0E1422;
                color: #F0F6FC;
                border: 1px solid #2B3D66;
                selection-background-color: #1F365A;
                selection-color: #58A6FF;
                padding: 4px;
            }
        """)
        self.combo_ai_model.currentIndexChanged.connect(self._on_model_changed)
        ch_layout.addWidget(self.combo_ai_model)

        btn_reload_ch = QPushButton("  Neu analysieren")
        btn_reload_ch.setIcon(create_vector_icon("sync", "#C9D1D9", 12))
        btn_reload_ch.setCursor(Qt.PointingHandCursor)
        btn_reload_ch.setStyleSheet("""
            QPushButton {
                background-color: #1A2438;
                color: #C9D1D9;
                border: 1px solid #28395A;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #253552;
                border-color: #58A6FF;
                color: #FFFFFF;
            }
        """)
        btn_reload_ch.clicked.connect(lambda: self._on_chapter_changed(self.combo_chapter.currentIndex()))
        ch_layout.addWidget(btn_reload_ch)

        main_layout.addWidget(ch_selector_box)

        # -------------------------------------------------------------
        # 2. Companion Workbook Auto-Pairing Banner (If Available)
        # -------------------------------------------------------------
        pair_info = get_book_pair(self.book_id)
        is_wb, wb_label = is_exercise_book(self.book_title, self.book.get("author", ""))

        if is_wb:
            wb_banner = QFrame()
            wb_banner.setStyleSheet("""
                QFrame {
                    background-color: #141E33;
                    border: 1px solid #233866;
                    border-radius: 8px;
                    padding: 6px 12px;
                }
            """)
            wb_layout = QHBoxLayout(wb_banner)
            wb_layout.setContentsMargins(10, 4, 10, 4)
            wb_layout.setSpacing(8)

            lbl_badge = QLabel("📚 Dieses Buch ist bereits ein Arbeitsbuch mit originalen Aufgaben & Lösungen.")
            lbl_badge.setStyleSheet("color: #79B8FF; font-weight: 600; font-size: 12px; border: none;")
            wb_layout.addWidget(lbl_badge, stretch=1)

            btn_open_ex = QPushButton("Direkt zu Aufgaben im PDF")
            btn_open_ex.setCursor(Qt.PointingHandCursor)
            btn_open_ex.setStyleSheet("""
                QPushButton {
                    background-color: #1F6FEB;
                    color: #FFFFFF;
                    font-weight: bold;
                    border: none;
                    border-radius: 5px;
                    padding: 4px 12px;
                }
                QPushButton:hover { background-color: #388BFD; }
            """)
            btn_open_ex.clicked.connect(lambda: open_pdf_in_edge(self.file_path, self.start_page))
            wb_layout.addWidget(btn_open_ex)
            main_layout.addWidget(wb_banner)

        elif pair_info:
            pair_banner = QFrame()
            pair_banner.setStyleSheet("""
                QFrame {
                    background-color: #11261B;
                    border: 1px solid #1C5432;
                    border-radius: 8px;
                    padding: 6px 12px;
                }
            """)
            pair_layout = QHBoxLayout(pair_banner)
            pair_layout.setContentsMargins(10, 4, 10, 4)
            pair_layout.setSpacing(8)

            pair_title = pair_info.get("title", "Passendes Arbeitsbuch")
            pair_path = pair_info.get("file_path", "")
            lbl_pair_icon = QLabel("⚔️")
            lbl_pair_icon.setStyleSheet("font-size: 14px; border: none; background: transparent;")
            pair_layout.addWidget(lbl_pair_icon)

            lbl_pair = QLabel(f"Gekoppeltes Arbeitsbuch gefunden: <b>{pair_title}</b>")
            lbl_pair.setStyleSheet("color: #56D364; font-size: 12px; border: none;")
            pair_layout.addWidget(lbl_pair, stretch=1)

            btn_open_pair = QPushButton("Arbeitsbuch aufschlagen")
            btn_open_pair.setCursor(Qt.PointingHandCursor)
            btn_open_pair.setStyleSheet("""
                QPushButton {
                    background-color: #238636;
                    color: #FFFFFF;
                    font-weight: bold;
                    border: none;
                    border-radius: 5px;
                    padding: 4px 12px;
                }
                QPushButton:hover { background-color: #2EA043; }
            """)
            btn_open_pair.clicked.connect(lambda p=pair_path: open_pdf_in_edge(p, 1))
            pair_layout.addWidget(btn_open_pair)
            main_layout.addWidget(pair_banner)

        # -------------------------------------------------------------
        # 3. Mode Switcher Bar (Tabs)
        # -------------------------------------------------------------
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(8)

        self.btn_mode_quiz = self._create_mode_button("🎯 Active Recall Quiz", "quiz")
        self.btn_mode_exam = self._create_mode_button("⏱️ Klausur-Simulator", "exam")
        self.btn_mode_socratic = self._create_mode_button("🎓 Mündliche Prüfung", "socratic")
        self.btn_mode_cheat = self._create_mode_button("📄 Spickzettel", "cheat")

        nav_bar.addWidget(self.btn_mode_quiz)
        nav_bar.addWidget(self.btn_mode_exam)
        nav_bar.addWidget(self.btn_mode_socratic)
        nav_bar.addWidget(self.btn_mode_cheat)
        nav_bar.addStretch()
        main_layout.addLayout(nav_bar)

        # -------------------------------------------------------------
        # 4. Central Stacked Content Area
        # -------------------------------------------------------------
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")

        # Page 0: Quiz Page
        self.page_quiz = self._build_quiz_page()
        self.stack.addWidget(self.page_quiz)

        # Page 1: Exam Page
        self.page_exam = self._build_exam_page()
        self.stack.addWidget(self.page_exam)

        # Page 2: Socratic Oral Exam Page
        self.page_socratic = self._build_socratic_page()
        self.stack.addWidget(self.page_socratic)

        # Page 3: Cheat Sheet Page
        self.page_cheat = self._build_cheat_page()
        self.stack.addWidget(self.page_cheat)

        main_layout.addWidget(self.stack, stretch=1)

        # -------------------------------------------------------------
        # 5. Bottom Status / Close Bar
        # -------------------------------------------------------------
        bottom_bar = QHBoxLayout()
        self.lbl_status = QLabel("Bereit zum Lernen")
        self.lbl_status.setStyleSheet("color: #8B949E; font-size: 11px;")
        bottom_bar.addWidget(self.lbl_status, stretch=1)

        btn_close = QPushButton("Schließen (Esc)")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)

        main_layout.addLayout(bottom_bar)

    def _create_mode_button(self, label: str, mode: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._set_active_mode(mode))
        return btn

    def _set_active_mode(self, mode: str) -> None:
        self.active_mode = mode
        buttons = [
            (self.btn_mode_quiz, "quiz", 0),
            (self.btn_mode_exam, "exam", 1),
            (self.btn_mode_socratic, "socratic", 2),
            (self.btn_mode_cheat, "cheat", 3),
        ]
        for btn, m_name, idx in buttons:
            if m_name == mode:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1F6FEB;
                        color: #FFFFFF;
                        border: 1px solid #388BFD;
                        border-radius: 6px;
                        padding: 6px 14px;
                        font-weight: bold;
                    }
                """)
                self.stack.setCurrentIndex(idx)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #141C2E;
                        color: #8B949E;
                        border: 1px solid #232F48;
                        border-radius: 6px;
                        padding: 6px 14px;
                    }
                    QPushButton:hover {
                        color: #F0F6FC;
                        border-color: #58A6FF;
                        background-color: #1B253D;
                    }
                """)

        if mode == "quiz" and not self.quiz_questions:
            self._generate_quiz()
        elif mode == "exam" and not self.exam_question_widgets:
            self._start_exam()
        elif mode == "socratic" and not self.socratic_history:
            self._start_socratic()
        elif mode == "cheat" and not self.txt_cheat.toPlainText().strip():
            self._generate_cheat()

    def _populate_chapters(self) -> None:
        """Extracts substantive chapters from TOC and selects the appropriate topic."""
        self.combo_chapter.blockSignals(True)
        self.combo_chapter.clear()

        chapters = get_book_substantive_chapters(self.file_path)
        self.available_chapters = chapters

        curr_p = max(1, int(self.book.get("current_page") or 1))
        total_p = max(1, int(self.book.get("page_count") or 100))

        # Item 0: Current Reading Position
        pos_end = min(total_p, curr_p + 15)
        self.combo_chapter.addItem(f"📍 Aktuelle Leseposition (S. {curr_p} - {pos_end})", {
            "title": f"Abschnitt ab S. {curr_p}",
            "start_page": curr_p,
            "end_page": pos_end,
        })

        selected_idx = 0
        matched_chapter = False

        for idx, ch in enumerate(chapters):
            self.combo_chapter.addItem(f"📖 {ch['display']}", ch)
            # Check if current reading page falls into this chapter
            if ch["start_page"] <= curr_p <= ch["end_page"]:
                selected_idx = idx + 1
                matched_chapter = True

        # If current page was 1 or front-matter and not matching a chapter, but real chapters exist:
        if not matched_chapter and len(chapters) > 0 and curr_p <= 5:
            # Default directly to the FIRST real substantive chapter!
            selected_idx = 1

        self.combo_chapter.setCurrentIndex(selected_idx)
        self.combo_chapter.blockSignals(False)
        self._on_chapter_changed(selected_idx)

    def _populate_ai_models(self) -> None:
        """Discovers available LLM models from Ollama daemon or Gemini configuration."""
        self.combo_ai_model.blockSignals(True)
        self.combo_ai_model.clear()
        models = get_available_ai_models()
        cfg = load_config()
        cfg_model = cfg.get("ollama_model", "")

        selected_idx = 0
        for idx, m in enumerate(models):
            self.combo_ai_model.addItem(f"🟢 {m['name']}", m["id"])
            if cfg_model and m.get("model") == cfg_model:
                selected_idx = idx

        if self.combo_ai_model.count() == 0:
            self.combo_ai_model.addItem("🟡 Kein lokales Modell gefunden", "fallback")

        self.combo_ai_model.setCurrentIndex(selected_idx)
        self.combo_ai_model.blockSignals(False)

    def _get_current_model_id(self) -> str:
        return str(self.combo_ai_model.currentData() or "")

    def _on_model_changed(self, idx: int) -> None:
        model_id = self._get_current_model_id()
        if model_id.startswith("ollama:"):
            real_name = model_id.split(":", 1)[1]
            cfg = load_config()
            cfg["ollama_model"] = real_name
            cfg["provider"] = "ollama"
            save_config(cfg)
        elif model_id.startswith("gemini:"):
            cfg = load_config()
            cfg["provider"] = "gemini"
            save_config(cfg)

    def _on_worker_error(self, task_name: str, err: str) -> None:
        self.lbl_status.setText(f"Hinweis: KI-Fallback für {task_name} aktiviert.")

    def _on_chapter_changed(self, index: int) -> None:
        """Triggered when student picks another chapter from the dropdown."""
        data = self.combo_chapter.currentData()
        if not data:
            return

        self.curr_chapter = data.get("title", "Thema")
        self.start_page = data.get("start_page", 1)
        self.end_page = data.get("end_page", self.start_page + 20)
        self.lbl_sub.setText(f"Thema: {self.curr_chapter} • Seiten {self.start_page} bis {self.end_page}")

        # Extract real text for this chapter
        self.chapter_text = extract_chapter_text(self.file_path, self.start_page, self.end_page)

        # Reset states so each tab regenerates with the new topic
        self.quiz_questions = []
        self.exam_timer.stop()
        self.exam_question_widgets = []
        self.socratic_history = []
        self.txt_cheat.clear()

        # Trigger generation for active tab
        if hasattr(self, "active_mode"):
            self._set_active_mode(self.active_mode)

    # -----------------------------------------------------------------
    # PAGE 0: ACTIVE RECALL QUIZ
    # -----------------------------------------------------------------
    def _build_quiz_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # Progress bar
        self.quiz_prog = QProgressBar()
        self.quiz_prog.setRange(0, 100)
        self.quiz_prog.setValue(0)
        self.quiz_prog.setFixedHeight(6)
        self.quiz_prog.setTextVisible(False)
        self.quiz_prog.setStyleSheet("""
            QProgressBar {
                background-color: #141C2E;
                border: 1px solid #232F48;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #58A6FF);
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.quiz_prog)

        # Question Card Box
        self.card_q = QFrame()
        self.card_q.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        q_layout = QVBoxLayout(self.card_q)
        q_layout.setSpacing(10)

        q_meta_row = QHBoxLayout()
        self.lbl_q_num = QLabel("Frage 1 von 5")
        self.lbl_q_num.setStyleSheet("color: #58A6FF; font-weight: bold; font-size: 11px;")
        q_meta_row.addWidget(self.lbl_q_num)
        q_meta_row.addStretch()

        self.lbl_score_badge = QLabel("Punkte: 0 / 5")
        self.lbl_score_badge.setStyleSheet("color: #E3B341; font-weight: bold; font-size: 11px;")
        q_meta_row.addWidget(self.lbl_score_badge)
        q_layout.addLayout(q_meta_row)

        self.lbl_question_text = QLabel("Frage wird geladen...")
        self.lbl_question_text.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_question_text.setStyleSheet("color: #F0F6FC; border: none;")
        self.lbl_question_text.setWordWrap(True)
        q_layout.addWidget(self.lbl_question_text)

        layout.addWidget(self.card_q)

        # 4 Options Buttons
        self.opt_buttons = []
        for i in range(4):
            btn = QPushButton(f"Option {chr(65+i)}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(42)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #141C2E;
                    color: #F0F6FC;
                    border: 1px solid #232F48;
                    border-radius: 7px;
                    padding: 6px 16px;
                    font-size: 12px;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: #1B253D;
                    border-color: #58A6FF;
                }
            """)
            btn.clicked.connect(lambda checked=False, opt_idx=i: self._on_option_selected(opt_idx))
            layout.addWidget(btn)
            self.opt_buttons.append(btn)

        # Explanation Box (hidden initially)
        self.box_expl = QFrame()
        self.box_expl.setVisible(False)
        self.box_expl.setStyleSheet("""
            QFrame {
                background-color: #162035;
                border: 1px solid #2B3D66;
                border-radius: 7px;
                padding: 10px;
            }
        """)
        expl_layout = QVBoxLayout(self.box_expl)
        expl_layout.setSpacing(4)

        self.lbl_result_tag = QLabel("Richtig!")
        self.lbl_result_tag.setFont(QFont("Segoe UI", 10, QFont.Bold))
        expl_layout.addWidget(self.lbl_result_tag)

        self.lbl_explanation = QLabel("")
        self.lbl_explanation.setWordWrap(True)
        self.lbl_explanation.setStyleSheet("color: #C9D1D9; font-size: 11px;")
        expl_layout.addWidget(self.lbl_explanation)

        layout.addWidget(self.box_expl)

        # Bottom Next Button
        quiz_bottom = QHBoxLayout()
        quiz_bottom.addStretch()

        self.btn_next_q = QPushButton("Nächste Frage ➔")
        self.btn_next_q.setCursor(Qt.PointingHandCursor)
        self.btn_next_q.setVisible(False)
        self.btn_next_q.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #388BFD; }
        """)
        self.btn_next_q.clicked.connect(self._next_question)
        quiz_bottom.addWidget(self.btn_next_q)

        layout.addLayout(quiz_bottom)
        layout.addStretch()
        return page

    def _generate_quiz(self) -> None:
        self.lbl_question_text.setText("🧠 KI liest den Buchtext & generiert Multiple-Choice-Fragen...")
        for btn in self.opt_buttons:
            btn.setVisible(False)
        self.box_expl.setVisible(False)
        self.btn_next_q.setVisible(False)
        self.quiz_prog.setValue(0)
        self.lbl_q_num.setText("Generiere Fragen...")
        self.lbl_status.setText(f"🤖 KI ({self.combo_ai_model.currentText()}) analysiert Kapitel...")

        if self.active_worker and self.active_worker.isRunning():
            self.active_worker.terminate()
            self.active_worker.wait(400)

        self.active_worker = TutorWorkerThread(
            mode="quiz",
            book_title=self.book_title,
            chapter_title=self.curr_chapter,
            text=self.chapter_text,
            model_id=self._get_current_model_id(),
            parent=self
        )
        self.active_worker.finished_quiz.connect(self._on_quiz_loaded)
        self.active_worker.error_occurred.connect(lambda err: self._on_worker_error("Quiz", err))
        self.active_worker.start()

    def _on_quiz_loaded(self, data: Dict[str, Any]) -> None:
        self.quiz_data = data
        self.quiz_questions = self.quiz_data.get("questions", [])
        self.current_q_idx = 0
        self.score = 0
        self.lbl_status.setText("Quiz bereit • Wähle deine Antwort")
        self._display_question(0)

    def _display_question(self, idx: int) -> None:
        if not self.quiz_questions or idx >= len(self.quiz_questions):
            self._show_quiz_finished()
            return

        self.current_q_idx = idx
        self.is_answered = False
        q = self.quiz_questions[idx]

        total = len(self.quiz_questions)
        pct = int((idx / total) * 100)
        self.quiz_prog.setValue(pct)
        self.lbl_q_num.setText(f"Frage {idx + 1} von {total} • {q.get('difficulty', 'Verständnis')}")
        self.lbl_score_badge.setText(f"Punkte: {self.score} / {total}")
        self.lbl_question_text.setText(q.get("question", "Keine Frage"))

        options = q.get("options", ["A", "B", "C", "D"])
        for i, btn in enumerate(self.opt_buttons):
            if i < len(options):
                btn.setText(f"  {chr(65+i)}   {options[i]}")
                btn.setEnabled(True)
                btn.setVisible(True)
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #141C2E;
                        color: #F0F6FC;
                        border: 1px solid #232F48;
                        border-radius: 7px;
                        padding: 6px 16px;
                        font-size: 12px;
                        text-align: left;
                    }
                    QPushButton:hover {
                        background-color: #1B253D;
                        border-color: #58A6FF;
                    }
                """)
            else:
                btn.setVisible(False)

        self.box_expl.setVisible(False)
        self.btn_next_q.setVisible(False)

    def _on_option_selected(self, chosen_idx: int) -> None:
        if self.is_answered:
            return
        self.is_answered = True
        self.selected_option = chosen_idx

        q = self.quiz_questions[self.current_q_idx]
        correct_idx = q.get("correct_index", 0)

        # Highlight right and wrong
        for i, btn in enumerate(self.opt_buttons):
            btn.setEnabled(False)
            if i == correct_idx:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #163622;
                        color: #3FB950;
                        border: 2px solid #2EA043;
                        border-radius: 7px;
                        padding: 6px 16px;
                        font-weight: bold;
                        text-align: left;
                    }
                """)
            elif i == chosen_idx and chosen_idx != correct_idx:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #36171B;
                        color: #FF7B72;
                        border: 2px solid #DA3633;
                        border-radius: 7px;
                        padding: 6px 16px;
                        font-weight: bold;
                        text-align: left;
                    }
                """)

        if chosen_idx == correct_idx:
            self.score += 1
            self.lbl_result_tag.setText("✓ Richtig beantwortet! (+20 XP)")
            self.lbl_result_tag.setStyleSheet("color: #3FB950; font-weight: bold; border: none;")
            add_user_xp(20)
            self.xp_gained.emit(20)
        else:
            self.lbl_result_tag.setText(f"✗ Leider falsch. Richtige Antwort: {chr(65+correct_idx)}")
            self.lbl_result_tag.setStyleSheet("color: #FF7B72; font-weight: bold; border: none;")

        self.lbl_explanation.setText(q.get("explanation", ""))
        self.box_expl.setVisible(True)
        self.btn_next_q.setVisible(True)

        total = len(self.quiz_questions)
        self.lbl_score_badge.setText(f"Punkte: {self.score} / {total}")

    def _next_question(self) -> None:
        if self.current_q_idx + 1 < len(self.quiz_questions):
            self._display_question(self.current_q_idx + 1)
        else:
            self._show_quiz_finished()

    def _show_quiz_finished(self) -> None:
        self.quiz_prog.setValue(100)
        total = len(self.quiz_questions) if self.quiz_questions else 5
        pct = int((self.score / total) * 100) if total > 0 else 0

        self.lbl_question_text.setText(f"🎉 Wissens-Check abgeschlossen!\nDu hast {self.score} von {total} Fragen richtig beantwortet ({pct}%).")
        for btn in self.opt_buttons:
            btn.setVisible(False)
        self.box_expl.setVisible(False)

        grade = "1.0 (Ausgezeichnet)" if pct >= 90 else ("2.0 (Gut)" if pct >= 70 else ("3.0 (Befriedigend)" if pct >= 50 else "5.0 (Wiederholen)"))
        save_quiz_result(self.book_id, self.curr_chapter, "active_recall", pct, grade, json.dumps(self.quiz_questions))

        self.btn_next_q.setText("🔄 Quiz wiederholen")
        self.btn_next_q.clicked.disconnect()
        self.btn_next_q.clicked.connect(self._generate_quiz)
        self.btn_next_q.setVisible(True)

    # -----------------------------------------------------------------
    # PAGE 1: TIMED EXAM SIMULATION WITH REAL EVALUATION
    # -----------------------------------------------------------------
    def _build_exam_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        # Top Timer Banner
        timer_banner = QFrame()
        timer_banner.setStyleSheet("""
            QFrame {
                background-color: #131A2B;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        tb_layout = QHBoxLayout(timer_banner)
        self.lbl_exam_timer = QLabel("⏱️ Verbleibende Prüfungszeit: 20:00")
        self.lbl_exam_timer.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_exam_timer.setStyleSheet("color: #D2A8FF; border: none;")
        tb_layout.addWidget(self.lbl_exam_timer)
        tb_layout.addStretch()

        self.btn_submit_exam = QPushButton("Klausur abgeben & auswerten")
        self.btn_submit_exam.setCursor(Qt.PointingHandCursor)
        self.btn_submit_exam.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 5px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #2EA043; }
        """)
        self.btn_submit_exam.clicked.connect(self._finish_exam)
        tb_layout.addWidget(self.btn_submit_exam)

        layout.addWidget(timer_banner)

        # Result Scoreboard Banner (Hidden until submission)
        self.card_exam_result = QFrame()
        self.card_exam_result.setVisible(False)
        self.result_layout = QVBoxLayout(self.card_exam_result)
        self.result_layout.setContentsMargins(14, 12, 14, 12)
        self.result_layout.setSpacing(4)
        layout.addWidget(self.card_exam_result)

        # Scroll area for questions
        self.scroll_exam = QScrollArea()
        self.scroll_exam.setWidgetResizable(True)
        self.scroll_exam.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.exam_container = QWidget()
        self.exam_layout = QVBoxLayout(self.exam_container)
        self.exam_layout.setSpacing(12)
        self.scroll_exam.setWidget(self.exam_container)
        layout.addWidget(self.scroll_exam, stretch=1)

        return page

    def _start_exam(self) -> None:
        self.card_exam_result.setVisible(False)
        self.exam_seconds_left = 1200
        mins = self.exam_seconds_left // 60
        secs = self.exam_seconds_left % 60
        self.lbl_exam_timer.setText(f"⏱️ Verbleibende Prüfungszeit: {mins:02d}:{secs:02d}")
        self.btn_submit_exam.setText("Klausur abgeben & auswerten")
        self.btn_submit_exam.setEnabled(False)

        # Clear existing layout and show loading placeholder
        while self.exam_layout.count():
            item = self.exam_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        lbl_loading = QLabel("🧠 KI konzipiert 6 Prüfungsaufgaben aus dem Fachbuchinhalt...\nBitte einen Moment Geduld.")
        lbl_loading.setStyleSheet("color: #79C0FF; font-size: 13px; font-weight: bold; padding: 40px;")
        lbl_loading.setAlignment(Qt.AlignCenter)
        self.exam_layout.addWidget(lbl_loading)

        self.lbl_status.setText(f"🤖 KI ({self.combo_ai_model.currentText()}) erstellt Klausursimulation...")

        if self.active_worker and self.active_worker.isRunning():
            self.active_worker.terminate()
            self.active_worker.wait(400)

        self.active_worker = TutorWorkerThread(
            mode="exam",
            book_title=self.book_title,
            chapter_title=self.curr_chapter,
            text=self.chapter_text,
            model_id=self._get_current_model_id(),
            parent=self
        )
        self.active_worker.finished_exam.connect(self._on_exam_loaded)
        self.active_worker.error_occurred.connect(lambda err: self._on_worker_error("Klausur", err))
        self.active_worker.start()

    def _on_exam_loaded(self, exam_data: Dict[str, Any]) -> None:
        # Clear loading placeholder
        while self.exam_layout.count():
            item = self.exam_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self.btn_submit_exam.setEnabled(True)
        try:
            self.btn_submit_exam.clicked.disconnect()
        except Exception:
            pass
        self.btn_submit_exam.clicked.connect(self._finish_exam)

        self.exam_timer.start()
        self.lbl_status.setText("Klausur aktiv • Aufgaben geladen • Bearbeitungszeit läuft")

        questions = exam_data.get("questions", [])
        self.exam_question_widgets = []
        for i, q in enumerate(questions):
            q_box = QFrame()
            q_box.setStyleSheet("""
                QFrame {
                    background-color: #121826;
                    border: 1px solid #232F48;
                    border-radius: 8px;
                    padding: 12px;
                }
            """)
            q_b_layout = QVBoxLayout(q_box)
            q_b_layout.setSpacing(8)

            q_pts = q.get("points", 10)
            lbl_t = QLabel(f"<b>Aufgabe {i+1} ({q_pts} Punkte)</b>: {q.get('question')}")
            lbl_t.setStyleSheet("color: #F0F6FC; font-size: 13px; border: none; font-weight: 500;")
            lbl_t.setWordWrap(True)
            q_b_layout.addWidget(lbl_t)

            btn_group = QButtonGroup(q_box)
            btn_group.setExclusive(True)
            opt_buttons = []

            options = q.get("options", [])
            for opt_idx, opt_text in enumerate(options):
                btn_opt = QPushButton(f"  {chr(65+opt_idx)})  {opt_text}")
                btn_opt.setCheckable(True)
                btn_opt.setCursor(Qt.PointingHandCursor)
                btn_opt.setStyleSheet("""
                    QPushButton {
                        background-color: #161F33;
                        color: #C9D1D9;
                        border: 1px solid #253350;
                        border-radius: 5px;
                        padding: 7px 12px;
                        text-align: left;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        border-color: #388BFD;
                        color: #F0F6FC;
                    }
                    QPushButton:checked {
                        background-color: #1F365A;
                        color: #58A6FF;
                        border: 1.5px solid #388BFD;
                        font-weight: bold;
                    }
                """)
                btn_group.addButton(btn_opt, opt_idx)
                opt_buttons.append(btn_opt)
                q_b_layout.addWidget(btn_opt)

            self.exam_layout.addWidget(q_box)
            self.exam_question_widgets.append({
                "question": q,
                "box": q_box,
                "group": btn_group,
                "option_buttons": opt_buttons,
                "points": q_pts,
                "correct_index": q.get("correct_index", 0),
                "explanation": q.get("explanation", ""),
            })

        self.exam_layout.addStretch()
        self.exam_timer.start()
        self.lbl_status.setText(f"Klausur aktiv • {len(questions)} Aufgaben • Bearbeitungszeit läuft")

    def _on_exam_tick(self) -> None:
        self.exam_seconds_left = max(0, self.exam_seconds_left - 1)
        mins = self.exam_seconds_left // 60
        secs = self.exam_seconds_left % 60
        self.lbl_exam_timer.setText(f"⏱️ Verbleibende Prüfungszeit: {mins:02d}:{secs:02d}")
        if self.exam_seconds_left == 0:
            self.exam_timer.stop()
            self._finish_exam()

    def _finish_exam(self) -> None:
        """Evaluates student answers against answer keys, computes real grades, reveals explanations and awards XP."""
        self.exam_timer.stop()
        if not self.exam_question_widgets:
            return

        total_max_points = 0
        earned_points = 0
        details = []

        for item in self.exam_question_widgets:
            q = item["question"]
            group = item["group"]
            btn_opts = item["option_buttons"]
            box = item["box"]
            q_pts = item["points"]
            correct_idx = item["correct_index"]

            total_max_points += q_pts
            chosen_id = group.checkedId()
            is_correct = (chosen_id == correct_idx)

            if is_correct:
                earned_points += q_pts

            details.append({
                "question": q.get("question"),
                "chosen_index": chosen_id,
                "correct_index": correct_idx,
                "is_correct": is_correct,
                "points": q_pts if is_correct else 0,
            })

            # Style card frame
            if is_correct:
                box.setStyleSheet("""
                    QFrame {
                        background-color: #0E1E17;
                        border: 1.5px solid #238636;
                        border-radius: 8px;
                        padding: 12px;
                    }
                """)
            else:
                box.setStyleSheet("""
                    QFrame {
                        background-color: #201116;
                        border: 1.5px solid #DA3633;
                        border-radius: 8px;
                        padding: 12px;
                    }
                """)

            # Update each option button style & lock
            for opt_idx, btn in enumerate(btn_opts):
                btn.setEnabled(False)
                if opt_idx == correct_idx:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #1A3E26;
                            color: #3FB950;
                            border: 1.5px solid #238636;
                            border-radius: 5px;
                            padding: 6px 12px;
                            text-align: left;
                            font-weight: bold;
                        }
                    """)
                elif opt_idx == chosen_id and not is_correct:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #3B161B;
                            color: #F85149;
                            border: 1.5px solid #DA3633;
                            border-radius: 5px;
                            padding: 6px 12px;
                            text-align: left;
                        }
                    """)
                else:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #121826;
                            color: #6E7681;
                            border: 1px solid #1E283D;
                            border-radius: 5px;
                            padding: 6px 12px;
                            text-align: left;
                        }
                    """)

            # Add Musterlösung & Begründung label
            expl_text = q.get("explanation") or "Fachliche Begründung im Buchtext verankert."
            badge = f"✓ Richtige Antwort (+{q_pts} Pkt)" if is_correct else f"✗ Nicht korrekt (0/{q_pts} Pkt)"
            badge_color = "#3FB950" if is_correct else "#F85149"
            lbl_res = QLabel(
                f"<span style='color:{badge_color}; font-weight:bold;'>{badge}</span><br>"
                f"<span style='color:#C9D1D9;'>💡 <b>Musterlösung:</b> {expl_text}</span>"
            )
            lbl_res.setStyleSheet("background-color: #0B101B; border: 1px solid #1C273C; border-radius: 6px; padding: 8px;")
            lbl_res.setWordWrap(True)
            box.layout().addWidget(lbl_res)

        # Compute percentage and authentic German academic grade
        pct = int((earned_points / total_max_points) * 100) if total_max_points > 0 else 0
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
            grade_str = "4.0 (Ausreichend - Bestanden)"
            passed = True
        else:
            grade_str = "5.0 (Nicht bestanden)"
            passed = False

        xp_award = max(25, earned_points * 4) if passed else max(10, earned_points * 2)
        add_user_xp(xp_award)
        self.xp_gained.emit(xp_award)

        save_quiz_result(
            self.book_id,
            self.curr_chapter,
            "klausur_simulation",
            pct,
            grade_str,
            json.dumps({"earned": earned_points, "total": total_max_points, "details": details})
        )

        # Render top result scoreboard
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        res_bg = "#11261B" if passed else "#2A1217"
        res_border = "#238636" if passed else "#DA3633"
        self.card_exam_result.setStyleSheet(f"""
            QFrame {{
                background-color: {res_bg};
                border: 2px solid {res_border};
                border-radius: 8px;
            }}
        """)

        lbl_score_header = QLabel(f"🎓 Klausur-Ergebnis: Note {grade_str}")
        lbl_score_header.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_score_header.setStyleSheet(f"color: {'#3FB950' if passed else '#F85149'}; border: none;")
        self.result_layout.addWidget(lbl_score_header)

        lbl_score_sub = QLabel(
            f"Erreichte Punkte: <b>{earned_points} von {total_max_points}</b> ({pct} %) • "
            f"Status: <b>{'Bestanden' if passed else 'Nicht bestanden'}</b> • "
            f"Belohnung: <b>+{xp_award} XP</b> gutgeschrieben"
        )
        lbl_score_sub.setStyleSheet("color: #F0F6FC; font-size: 12px; border: none;")
        self.result_layout.addWidget(lbl_score_sub)

        self.card_exam_result.setVisible(True)

        self.lbl_exam_timer.setText(f"✅ Klausur ausgewertet: Note {grade_str} ({earned_points}/{total_max_points} Pkt)")
        self.btn_submit_exam.setText("🔄 Neue Klausur generieren")
        self.btn_submit_exam.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 5px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #388BFD; }
        """)
        try:
            self.btn_submit_exam.clicked.disconnect()
        except Exception:
            pass
        self.btn_submit_exam.clicked.connect(self._start_exam)

    # -----------------------------------------------------------------
    # PAGE 2: SOCRATIC ORAL EXAM
    # -----------------------------------------------------------------
    def _build_socratic_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Dialog Box
        self.txt_socratic_log = QPlainTextEdit()
        self.txt_socratic_log.setReadOnly(True)
        self.txt_socratic_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0E1422;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 12px;
                color: #F0F6FC;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        layout.addWidget(self.txt_socratic_log, stretch=1)

        input_row = QHBoxLayout()
        self.ent_student_answer = QLineEdit()
        self.ent_student_answer.setPlaceholderText("Deine mündliche Antwort an den Prüfer formulieren...")
        self.ent_student_answer.setStyleSheet("""
            QLineEdit {
                background-color: #141C2E;
                color: #F0F6FC;
                border: 1px solid #232F48;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus { border-color: #58A6FF; }
        """)
        self.ent_student_answer.returnPressed.connect(self._submit_socratic_answer)
        input_row.addWidget(self.ent_student_answer, stretch=1)

        btn_send = QPushButton("Antworten")
        btn_send.setCursor(Qt.PointingHandCursor)
        btn_send.setStyleSheet("""
            QPushButton {
                background-color: #1F6FEB;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
            }
            QPushButton:hover { background-color: #388BFD; }
        """)
        btn_send.clicked.connect(self._submit_socratic_answer)
        input_row.addWidget(btn_send)

        layout.addLayout(input_row)
        return page

    def _start_socratic(self) -> None:
        self.socratic_history = []
        turn = generate_socratic_turn(
            self.book_title, self.curr_chapter, self.chapter_text, self.socratic_history, model_id=self._get_current_model_id()
        )
        msg = turn.get("professor_message", "Guten Tag! Lassen Sie uns über den Stoff sprechen.")
        self.socratic_history.append({"role": "assistant", "content": msg})
        self.txt_socratic_log.appendPlainText(f"🎓 Herr Professor:\n{msg}\n\n" + "—"*50 + "\n")

    def _submit_socratic_answer(self) -> None:
        text = self.ent_student_answer.text().strip()
        if not text:
            return
        self.ent_student_answer.clear()

        self.txt_socratic_log.appendPlainText(f"🗣️ Du:\n{text}\n\n")
        self.socratic_history.append({"role": "user", "content": text})
        QApplication.processEvents()

        turn = generate_socratic_turn(
            self.book_title, self.curr_chapter, self.chapter_text, self.socratic_history, model_id=self._get_current_model_id()
        )
        msg = turn.get("professor_message", "Vielen Dank. Lassen Sie uns zum nächsten Aspekt übergehen.")
        self.socratic_history.append({"role": "assistant", "content": msg})
        self.txt_socratic_log.appendPlainText(f"🎓 Herr Professor:\n{msg}\n\n" + "—"*50 + "\n")

        add_user_xp(15)
        self.xp_gained.emit(15)

    # -----------------------------------------------------------------
    # PAGE 3: ONE-PAGE CHEAT SHEET
    # -----------------------------------------------------------------
    def _build_cheat_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        lbl_info = QLabel("Automatisch generierte Formelsammlung und Kernaussagen:")
        lbl_info.setStyleSheet("color: #8B949E; font-size: 11px;")
        top_row.addWidget(lbl_info)
        top_row.addStretch()

        btn_copy = QPushButton("In Zwischenablage kopieren")
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #1F293D;
                color: #C9D1D9;
                border: 1px solid #232F48;
                border-radius: 5px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #263550; color: #FFFFFF; }
        """)
        btn_copy.clicked.connect(self._copy_cheat)
        top_row.addWidget(btn_copy)
        layout.addLayout(top_row)

        self.txt_cheat = QPlainTextEdit()
        self.txt_cheat.setReadOnly(True)
        self.txt_cheat.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0B0F19;
                color: #F0F6FC;
                border: 1px solid #232F48;
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', 'Segoe UI', monospace;
                font-size: 12px;
                line-height: 1.6;
            }
        """)
        layout.addWidget(self.txt_cheat, stretch=1)
        return page

    def _generate_cheat(self) -> None:
        self.txt_cheat.setPlainText("🧠 KI analysiert das Fachbuchkapitel und formuliert den 1-Page Spickzettel & Formelsammlung...")
        self.lbl_status.setText(f"🤖 KI ({self.combo_ai_model.currentText()}) generiert Spickzettel...")

        if self.active_worker and self.active_worker.isRunning():
            self.active_worker.terminate()
            self.active_worker.wait(400)

        self.active_worker = TutorWorkerThread(
            mode="cheat_sheet",
            book_title=self.book_title,
            chapter_title=self.curr_chapter,
            text=self.chapter_text,
            model_id=self._get_current_model_id(),
            parent=self
        )
        self.active_worker.finished_cheat_sheet.connect(self._on_cheat_loaded)
        self.active_worker.error_occurred.connect(lambda err: self._on_worker_error("Spickzettel", err))
        self.active_worker.start()

    def _on_cheat_loaded(self, cheat_md: str) -> None:
        self.txt_cheat.setPlainText(cheat_md)
        self.lbl_status.setText("Spickzettel erfolgreich generiert.")

    def _copy_cheat(self) -> None:
        text = self.txt_cheat.toPlainText()
        if text:
            clip = QApplication.clipboard()
            if clip:
                clip.setText(text)
                self.lbl_status.setText("✓ Spickzettel in Zwischenablage kopiert!")
                QTimer.singleShot(2500, lambda: self.lbl_status.setText(""))
