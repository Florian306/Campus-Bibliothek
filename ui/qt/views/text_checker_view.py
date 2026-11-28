"""Interactive Text Proofreading, Grammar, Punctuation & Style Checker View (No AI).
Combines offline German rules + optional LanguageTool API with inline underlines
and 1-click quick fixes.
"""

from typing import List, Optional
import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.text_checker import TextIssue, TextStats, analyze_text


class _TextCheckWorker(QThread):
    finished_check = Signal(list, object)  # (List[TextIssue], TextStats)

    def __init__(self, text: str, use_lt: bool, parent=None):
        super().__init__(parent)
        self.text = text
        self.use_lt = use_lt

    def run(self) -> None:
        issues, stats = analyze_text(self.text, use_languagetool=self.use_lt)
        self.finished_check.emit(issues, stats)


class TextCheckerView(QWidget):
    """Proofreading & academic style editor view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._issues: List[TextIssue] = []
        self._active_filter = "all"  # "all" | "spelling" | "grammar" | "style"
        self._worker: Optional[_TextCheckWorker] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Header Bar
        hdr = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        lbl_title = QLabel("Lektorat & Textprüfung")
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC;")
        lbl_sub = QLabel("Grammatik, Kommasetzung, Zeichensetzung, Rechtschreibung & wissenschaftlicher Stil (ohne KI)")
        lbl_sub.setFont(QFont("Segoe UI", 9.5))
        lbl_sub.setStyleSheet("color: #8B949E;")
        title_col.addWidget(lbl_title)
        title_col.addWidget(lbl_sub)
        hdr.addLayout(title_col)
        hdr.addStretch()

        self.chk_languagetool = QCheckBox("LanguageTool Online-Prüfung (de-DE)")
        self.chk_languagetool.setChecked(True)
        self.chk_languagetool.setStyleSheet("color: #C9D1D9; font-size: 12px;")
        hdr.addWidget(self.chk_languagetool)

        btn_style = """
            QPushButton {
                background-color: #161B22; color: #C9D1D9;
                border: 1px solid #30363D; border-radius: 6px;
                padding: 6px 12px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background-color: #21262D; color: #FFFFFF; border-color: #58A6FF; }
        """

        self.btn_import = QPushButton("📄 Datei laden (.txt/.docx)")
        self.btn_import.setCursor(Qt.PointingHandCursor)
        self.btn_import.setStyleSheet(btn_style)
        self.btn_import.clicked.connect(self._import_file)
        hdr.addWidget(self.btn_import)

        self.btn_copy = QPushButton("📋 Text kopieren")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setStyleSheet(btn_style)
        self.btn_copy.clicked.connect(self._copy_text)
        hdr.addWidget(self.btn_copy)

        self.btn_check = QPushButton("🔍 Text prüfen")
        self.btn_check.setCursor(Qt.PointingHandCursor)
        self.btn_check.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
                color: #FFFFFF; border: none; border-radius: 6px;
                padding: 7px 16px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: #58A6FF; }
        """)
        self.btn_check.clicked.connect(self._run_check)
        hdr.addWidget(self.btn_check)

        root.addLayout(hdr)

        # Splitter: Left Editor, Right Issues Inspector
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #1A2436; width: 2px; }")

        # Left Editor
        editor_frame = QFrame()
        editor_frame.setStyleSheet("QFrame { background-color: #0D1117; border: 1px solid #1E2B42; border-radius: 10px; }")
        ed_lay = QVBoxLayout(editor_frame)
        ed_lay.setContentsMargins(10, 10, 10, 10)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Füge hier deinen Text ein (z. B. Hausarbeit, Zusammenfassung, E-Mail) "
            "und klicke oben auf „Text prüfen“..."
        )
        self.editor.setFont(QFont("Segoe UI", 11))
        self.editor.setStyleSheet("""
            QTextEdit {
                background-color: #0D1117; color: #E6EDF3;
                border: none; selection-background-color: #1F6FEB;
            }
        """)
        ed_lay.addWidget(self.editor)
        splitter.addWidget(editor_frame)

        # Right Inspector
        insp_frame = QFrame()
        insp_frame.setMinimumWidth(360)
        insp_frame.setStyleSheet("QFrame { background-color: #0A0F1A; border: 1px solid #1E2B42; border-radius: 10px; }")
        insp_lay = QVBoxLayout(insp_frame)
        insp_lay.setContentsMargins(12, 12, 12, 12)
        insp_lay.setSpacing(10)

        # Stats Bar
        self.lbl_stats = QLabel("Wörter: 0  ·  Sätze: 0  ·  Ø Satzlänge: 0  ·  Flesch: –")
        self.lbl_stats.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_stats.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        insp_lay.addWidget(self.lbl_stats)

        # Filter Pills
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self._filter_btns = {}
        for key, label in [
            ("all", "Alle"),
            ("spelling", "Rechtschreibung"),
            ("grammar", "Komma & Grammatik"),
            ("style", "Stil"),
        ]:
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(26)
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._filter_btns[key] = b
            filter_row.addWidget(b)
        filter_row.addStretch()
        insp_lay.addLayout(filter_row)
        self._update_filter_styles()

        # Issues Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.issues_container = QWidget()
        self.issues_container.setStyleSheet("background: transparent;")
        self.issues_layout = QVBoxLayout(self.issues_container)
        self.issues_layout.setContentsMargins(0, 2, 4, 8)
        self.issues_layout.setSpacing(8)
        self.issues_layout.addStretch()

        self.scroll.setWidget(self.issues_container)
        insp_lay.addWidget(self.scroll, stretch=1)

        splitter.addWidget(insp_frame)
        splitter.setSizes([640, 440])
        root.addWidget(splitter, stretch=1)

    def _set_filter(self, key: str) -> None:
        self._active_filter = key
        self._update_filter_styles()
        self._render_issues()

    def _update_filter_styles(self) -> None:
        for k, btn in self._filter_btns.items():
            if k == self._active_filter:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1F6FEB; color: #FFFFFF;
                        border: none; border-radius: 13px; padding: 0 10px;
                        font-size: 11px; font-weight: bold;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #121A2B; color: #8B949E;
                        border: 1px solid #23314A; border-radius: 13px; padding: 0 10px;
                        font-size: 11px; font-weight: 600;
                    }
                    QPushButton:hover { color: #FFFFFF; border-color: #388BFD; }
                """)

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Text oder Word-Dokument laden",
            "",
            "Dokumente (*.txt *.md *.docx);;Alle Dateien (*.*)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".docx"):
                import docx
                doc = docx.Document(path)
                content = "\n".join(p.text for p in doc.paragraphs)
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            self.editor.setPlainText(content)
            self._run_check()
        except Exception as e:
            self.lbl_stats.setText(f"Fehler beim Laden: {e}")

    def _copy_text(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.btn_copy.setText("✅ Kopiert")

    def _run_check(self) -> None:
        text = self.editor.toPlainText()
        self.btn_check.setEnabled(False)
        self.btn_check.setText("⏳ Prüfe...")
        self._worker = _TextCheckWorker(text, self.chk_languagetool.isChecked(), self)
        self._worker.finished_check.connect(self._on_check_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_check_finished(self, issues: list, stats: TextStats) -> None:
        self.btn_check.setEnabled(True)
        self.btn_check.setText("🔍 Text prüfen")
        self._issues = issues
        self.lbl_stats.setText(
            f"Wörter: {stats.words}  ·  Sätze: {stats.sentences}  ·  "
            f"Ø Satzlänge: {stats.avg_sentence_len}  ·  Flesch: {stats.flesch_de}"
        )
        self._apply_editor_underlines()
        self._render_issues()

    def _apply_editor_underlines(self) -> None:
        selections = []
        color_map = {
            "spelling": QColor("#F85149"),
            "grammar": QColor("#58A6FF"),
            "style": QColor("#D29922"),
        }
        doc_len = len(self.editor.toPlainText())
        for issue in self._issues:
            if issue.offset < 0 or issue.offset + issue.length > doc_len:
                continue
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            fmt.setUnderlineColor(color_map.get(issue.category, QColor("#58A6FF")))
            sel.format = fmt
            cur = self.editor.textCursor()
            cur.setPosition(issue.offset)
            cur.setPosition(issue.offset + issue.length, QTextCursor.KeepAnchor)
            sel.cursor = cur
            selections.append(sel)
        self.editor.setExtraSelections(selections)

    def _render_issues(self) -> None:
        while self.issues_layout.count():
            item = self.issues_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        filtered = [
            i for i in self._issues
            if self._active_filter == "all" or i.category == self._active_filter
        ]

        if not filtered:
            lbl = QLabel("Keine Hinweise in dieser Kategorie gefunden." if self._issues else "Noch keine Prüfung durchgeführt oder keine Fehler gefunden.")
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #8B949E; padding: 24px; border: none; background: transparent;")
            self.issues_layout.addWidget(lbl)
            self.issues_layout.addStretch()
            return

        badge_colors = {
            "spelling": ("Rechtschreibung", "#F85149"),
            "grammar": ("Komma & Grammatik", "#58A6FF"),
            "style": ("Stil", "#D29922"),
        }

        for issue in filtered[:120]:
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: #111827; border: 1px solid #1E2B42; border-radius: 8px;
                }
                QFrame:hover { border-color: #388BFD; }
            """)
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(10, 8, 10, 8)
            c_lay.setSpacing(6)

            top = QHBoxLayout()
            cat_label, cat_col = badge_colors.get(issue.category, ("Hinweis", "#58A6FF"))
            badge = QLabel(cat_label)
            badge.setStyleSheet(f"color: {cat_col}; font-size: 10px; font-weight: bold; border: none; background: transparent;")
            top.addWidget(badge)
            top.addStretch()

            btn_jump = QPushButton("Zur Stelle")
            btn_jump.setCursor(Qt.PointingHandCursor)
            btn_jump.setStyleSheet("QPushButton { color: #8B949E; border: none; background: transparent; font-size: 10px; } QPushButton:hover { color: #FFFFFF; }")
            btn_jump.clicked.connect(lambda _=False, iss=issue: self._jump_to_issue(iss))
            top.addWidget(btn_jump)
            c_lay.addLayout(top)

            msg = QLabel(issue.message)
            msg.setWordWrap(True)
            msg.setStyleSheet("color: #E6EDF3; font-size: 12px; border: none; background: transparent;")
            c_lay.addWidget(msg)

            if issue.replacements:
                rep_row = QHBoxLayout()
                rep_row.setSpacing(6)
                for rep in issue.replacements[:3]:
                    btn_rep = QPushButton(f"✓ {rep}")
                    btn_rep.setCursor(Qt.PointingHandCursor)
                    btn_rep.setStyleSheet("""
                        QPushButton {
                            background-color: #16243D; color: #58A6FF;
                            border: 1px solid #264270; border-radius: 5px;
                            padding: 3px 8px; font-size: 11px; font-weight: 600;
                        }
                        QPushButton:hover { background-color: #1F6FEB; color: #FFFFFF; }
                    """)
                    btn_rep.clicked.connect(lambda _=False, iss=issue, r=rep: self._apply_replacement(iss, r))
                    rep_row.addWidget(btn_rep)
                rep_row.addStretch()
                c_lay.addLayout(rep_row)

            self.issues_layout.addWidget(card)

        self.issues_layout.addStretch()

    def _jump_to_issue(self, issue: TextIssue) -> None:
        cur = self.editor.textCursor()
        cur.setPosition(issue.offset)
        cur.setPosition(issue.offset + issue.length, QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cur)
        self.editor.setFocus()

    def _apply_replacement(self, issue: TextIssue, replacement: str) -> None:
        cur = self.editor.textCursor()
        cur.setPosition(issue.offset)
        cur.setPosition(issue.offset + issue.length, QTextCursor.KeepAnchor)
        cur.insertText(replacement)
        self._run_check()
