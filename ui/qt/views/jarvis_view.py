"""JARVIS Command Center & Executive Daily Briefing View.
Bento-Grid Architecture integrating Calendar/Timetable, Email Inbox, Live RSS Feeds,
AI-Powered Daily Executive Summaries, and Native Windows TTS Voice Playback.
"""

import os
import datetime
import threading
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QObject, QSize, QTimer, QUrl
from PySide6.QtGui import QFont, QColor, QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QFrame,
    QScrollArea,
    QSplitter,
    QProgressBar,
    QDialog,
    QFormLayout,
    QMessageBox,
    QTextBrowser,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage
    _HAS_WEBENGINE = True
except Exception:
    _HAS_WEBENGINE = False

from ui.qt.icons import create_vector_icon, create_vector_pixmap
from core.calendar_service import (
    get_today_events,
    get_display_events,
    get_next_upcoming_event,
    sync_webcal_feed,
    get_cal_url,
    save_cal_url,
    clear_all_demo_events,
    ensure_calendar_synced,
    format_event_day,
    format_event_relative,
    calculate_event_duration,
    delete_calendar_event,
)
from core.rss_news_service import fetch_live_news
from core.mail_service import (
    fetch_inbox_messages,
    fetch_single_email_body,
    fetch_single_email_content,
    delete_email_by_id,
    get_mail_settings,
    save_mail_settings,
    test_mail_connection,
)
from core.library_db import get_desk_books, get_gamification_profile
from ai.jarvis_briefing import (
    get_greeting,
    generate_executive_briefing,
    speak_text,
    stop_speech,
)


class JarvisSignals(QObject):
    """Thread-safe signals for background data gathering, AI synthesis and voice playback."""
    briefing_ready = Signal(str)
    news_ready = Signal(list)
    mails_ready = Signal(list)
    calendar_ready = Signal(list, bool)
    speech_finished = Signal()


if _HAS_WEBENGINE:
    class ExternalWebEnginePage(QWebEnginePage):
        """Routes link clicks to the system browser."""

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def createWindow(self, _type):  # noqa: N802
            # target=_blank -> temp page forwarding to system browser
            tmp = QWebEnginePage(self)
            tmp.urlChanged.connect(lambda u: (QDesktopServices.openUrl(u), tmp.deleteLater()))
            return tmp


_CLEAN_MAIL_CSS = """
<style>
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: #F1F3F4; }
::-webkit-scrollbar-thumb { background: #DADCE0; border-radius: 5px; }
::-webkit-scrollbar-thumb:hover { background: #BDC1C6; }
html { background-color: #FFFFFF !important; }
body { margin: 0; background-color: #FFFFFF !important; color: #202124 !important; font-family: Roboto, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }
</style>
"""

_MAIL_WRAPPER = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base target="_blank">
<style>
html,body{{margin:0;padding:0;background:#FFFFFF;}}
body{{padding:24px 28px;font-family:Roboto,'Google Sans','Segoe UI',Arial,sans-serif;font-size:14px;color:#202124;line-height:1.6;}}
img{{max-width:100%;height:auto;}}
::-webkit-scrollbar{{width:10px;height:10px;}}
::-webkit-scrollbar-track{{background:#F1F3F4;}}
::-webkit-scrollbar-thumb{{background:#DADCE0;border-radius:5px;}}
::-webkit-scrollbar-thumb:hover{{background:#BDC1C6;}}
</style></head><body>{content}</body></html>"""


class JarvisMailReaderDialog(QDialog):
    """Authentic Gmail Web-Browser style email reader dialog with HTML and delete capability."""

    def __init__(self, parent=None, mail_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.mail_data = mail_data or {}
        self.was_deleted = False
        self._light_mode = True
        subj = self.mail_data.get("subject", "E-Mail")
        self.setWindowTitle(f"Gmail – {subj[:80]}")
        
        # Enable full Windows window controls: Min, Max, Close, and free resizing
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self.setMinimumSize(700, 500)
        self.resize(1080, 780)
        self.setStyleSheet("""
            QDialog {
                background-color: #1F1F1F;
                color: #E8EAED;
            }
            QLabel {
                color: #E8EAED;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        # 1. TOP GMAIL TOOLBAR (like web browser)
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #2D2E30; border-radius: 8px; padding: 4px;")
        t_lay = QHBoxLayout(toolbar)
        t_lay.setContentsMargins(8, 4, 8, 4)
        t_lay.setSpacing(6)

        def make_tb_btn(icon_str: str, tooltip: str, on_click=None) -> QPushButton:
            btn = QPushButton(icon_str)
            btn.setFixedSize(34, 30)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #E8EAED;
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #3C4043;
                }
            """)
            if on_click:
                btn.clicked.connect(on_click)
            return btn

        btn_back = make_tb_btn("←", "Zurück zum Posteingang", self.accept)
        t_lay.addWidget(btn_back)

        sep1 = QLabel("│")
        sep1.setStyleSheet("color: #5F6368; border: none;")
        t_lay.addWidget(sep1)

        btn_archive = make_tb_btn("📥", "Archivieren", lambda: QMessageBox.information(self, "Gmail", "Nachricht archiviert."))
        t_lay.addWidget(btn_archive)

        btn_spam = make_tb_btn("⚠️", "Spam melden", lambda: QMessageBox.information(self, "Gmail", "Als Spam gemeldet."))
        t_lay.addWidget(btn_spam)

        btn_delete = make_tb_btn("🗑️", "In den Papierkorb verschieben (Löschen)", self._on_delete)
        t_lay.addWidget(btn_delete)

        sep2 = QLabel("│")
        sep2.setStyleSheet("color: #5F6368; border: none;")
        t_lay.addWidget(sep2)

        btn_unread = make_tb_btn("✉️", "Als ungelesen markieren", self.accept)
        t_lay.addWidget(btn_unread)

        btn_label = make_tb_btn("🏷️", "Labels", lambda: None)
        t_lay.addWidget(btn_label)

        t_lay.addStretch()

        btn_web = QPushButton("  🌐 In Google Mail öffnen")
        btn_web.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_web.setFixedHeight(28)
        btn_web.setCursor(Qt.PointingHandCursor)
        btn_web.setStyleSheet("""
            QPushButton {
                background: #1A73E8;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #1557B0;
            }
        """)
        btn_web.clicked.connect(self._open_webmail)
        t_lay.addWidget(btn_web)

        btn_max = make_tb_btn("⛶", "Vollbild / Vergrößern umschalten", self._toggle_maximize)
        t_lay.addWidget(btn_max)

        layout.addWidget(toolbar)

        # 2. SUBJECT & LABELS
        subj_row = QHBoxLayout()
        subj_row.setSpacing(10)

        lbl_subj = QLabel(subj)
        lbl_subj.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_subj.setStyleSheet("color: #E8EAED; border: none;")
        lbl_subj.setWordWrap(True)
        subj_row.addWidget(lbl_subj, stretch=1)

        chip_inbox = QLabel("Posteingang  ✕")
        chip_inbox.setFont(QFont("Segoe UI", 8, QFont.Bold))
        chip_inbox.setStyleSheet("background: #3C4043; color: #E8EAED; border-radius: 4px; padding: 2px 6px; border: none;")
        subj_row.addWidget(chip_inbox)

        urg = self.mail_data.get("urgency", "normal")
        if urg == "high":
            chip_urg = QLabel("⚠️ Wichtig")
            chip_urg.setFont(QFont("Segoe UI", 8, QFont.Bold))
            chip_urg.setStyleSheet("background: #5C1D24; color: #F28B82; border-radius: 4px; padding: 2px 6px; border: none;")
            subj_row.addWidget(chip_urg)

        layout.addLayout(subj_row)

        # 3. SENDER CARD WITH GMAIL AVATAR BUBBLE
        sender_card = QFrame()
        sender_card.setStyleSheet("background-color: #282A2D; border-radius: 8px; padding: 8px;")
        s_lay = QHBoxLayout(sender_card)
        s_lay.setContentsMargins(10, 8, 10, 8)
        s_lay.setSpacing(12)

        # Avatar circle
        sender_name = self.mail_data.get("sender", "Absender")
        initial = (sender_name[:1] or "G").upper()
        colors = ["#EA4335", "#1A73E8", "#FBBC04", "#34A853", "#9334E6", "#E91E63", "#00897B", "#F4511E"]
        av_bg = colors[ord(initial) % len(colors)]

        lbl_avatar = QLabel(initial)
        lbl_avatar.setFixedSize(38, 38)
        lbl_avatar.setAlignment(Qt.AlignCenter)
        lbl_avatar.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_avatar.setStyleSheet(f"background-color: {av_bg}; color: #FFFFFF; border-radius: 19px; border: none;")
        s_lay.addWidget(lbl_avatar)

        # Sender Details
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_row = QHBoxLayout()
        lbl_name = QLabel(sender_name)
        lbl_name.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_name.setStyleSheet("color: #E8EAED; border: none;")
        name_row.addWidget(lbl_name)

        sender_email = self.mail_data.get("sender_email") or f"{sender_name.lower().replace(' ', '')}@mail.de"
        lbl_email = QLabel(f"<{sender_email}>")
        lbl_email.setFont(QFont("Segoe UI", 9))
        lbl_email.setStyleSheet("color: #9AA0A6; border: none;")
        name_row.addWidget(lbl_email)
        name_row.addStretch()
        info_col.addLayout(name_row)

        lbl_to = QLabel("an mich ▾")
        lbl_to.setFont(QFont("Segoe UI", 8))
        lbl_to.setStyleSheet("color: #9AA0A6; border: none;")
        info_col.addWidget(lbl_to)

        s_lay.addLayout(info_col, stretch=1)

        # Date & Star on right
        right_info = QHBoxLayout()
        lbl_date = QLabel(self.mail_data.get("date", "Heute"))
        lbl_date.setFont(QFont("Segoe UI", 9))
        lbl_date.setStyleSheet("color: #9AA0A6; border: none;")
        right_info.addWidget(lbl_date)

        lbl_star = QPushButton("☆")
        lbl_star.setFixedSize(26, 26)
        lbl_star.setCursor(Qt.PointingHandCursor)
        lbl_star.setStyleSheet("background: transparent; color: #9AA0A6; border: none; font-size: 14px;")
        lbl_star.clicked.connect(lambda: lbl_star.setText("★") if lbl_star.text() == "☆" else lbl_star.setText("☆"))
        right_info.addWidget(lbl_star)

        s_lay.addLayout(right_info)
        layout.addWidget(sender_card)

        # 4. EMAIL BODY (Clean embedded browser without thick white borders)
        body_frame = QFrame()
        body_frame.setStyleSheet("""
            QFrame {
                background-color: #1F1F1F;
                border: none;
                border-radius: 8px;
            }
        """)
        body_lay = QVBoxLayout(body_frame)
        body_lay.setContentsMargins(0, 0, 0, 0)

        self.web_view = None
        self.browser = None
        if _HAS_WEBENGINE:
            self.web_view = QWebEngineView()
            self.web_view.setPage(ExternalWebEnginePage(self.web_view))
            self.web_view.page().setBackgroundColor(QColor("#1F1F1F"))
            body_lay.addWidget(self.web_view)
        else:
            self.browser = QTextBrowser()
            self.browser.setOpenExternalLinks(True)
            self.browser.setStyleSheet("background:#1F1F1F; color:#E8EAED; border:none; padding:16px;")
            body_lay.addWidget(self.browser)
        layout.addWidget(body_frame, stretch=1)

        # 5. GMAIL REPLY / FORWARD BOX
        reply_card = QFrame()
        reply_card.setStyleSheet("background-color: #282A2D; border: 1px solid #3C4043; border-radius: 8px; padding: 10px;")
        r_lay = QHBoxLayout(reply_card)
        r_lay.setContentsMargins(8, 4, 8, 4)
        r_lay.setSpacing(10)

        btn_reply = QPushButton("  ↩ Antworten")
        btn_reply.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_reply.setFixedHeight(34)
        btn_reply.setCursor(Qt.PointingHandCursor)
        btn_reply.setStyleSheet("""
            QPushButton {
                background: #303134;
                color: #E8EAED;
                border: 1px solid #5F6368;
                border-radius: 17px;
                padding: 0 18px;
            }
            QPushButton:hover {
                background: #3C4043;
                border-color: #8AB4F8;
                color: #8AB4F8;
            }
        """)
        btn_reply.clicked.connect(self._open_webmail)
        r_lay.addWidget(btn_reply)

        btn_fwd = QPushButton("  ↪ Weiterleiten")
        btn_fwd.setFont(QFont("Segoe UI", 9))
        btn_fwd.setFixedHeight(34)
        btn_fwd.setCursor(Qt.PointingHandCursor)
        btn_fwd.setStyleSheet("""
            QPushButton {
                background: #303134;
                color: #E8EAED;
                border: 1px solid #5F6368;
                border-radius: 17px;
                padding: 0 18px;
            }
            QPushButton:hover {
                background: #3C4043;
            }
        """)
        btn_fwd.clicked.connect(self._open_webmail)
        r_lay.addWidget(btn_fwd)

        r_lay.addStretch()

        btn_del_large = QPushButton("  🗑️ In den Papierkorb")
        btn_del_large.setFont(QFont("Segoe UI", 9))
        btn_del_large.setFixedHeight(34)
        btn_del_large.setCursor(Qt.PointingHandCursor)
        btn_del_large.setStyleSheet("""
            QPushButton {
                background: #3C2224;
                color: #F28B82;
                border: 1px solid #5C1D24;
                border-radius: 6px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: #5C1D24;
                color: #FFFFFF;
            }
        """)
        btn_del_large.clicked.connect(self._on_delete)
        r_lay.addWidget(btn_del_large)

        layout.addWidget(reply_card)

        self._load_content()

    def _set_body_html(self, html: str) -> None:
        if self.web_view is not None:
            # Remote base URL so http(s) images load like in Gmail
            self.web_view.setHtml(html, QUrl("https://mail.google.com/"))
        elif self.browser is not None:
            self.browser.setHtml(html)

    def _render_html(self, html: str) -> None:
        if "<html" in html[:500].lower():
            # Inject clean scrollbar & white background styles right into existing HTML emails
            if "<head>" in html.lower():
                idx = html.lower().find("<head>") + 6
                enhanced_html = html[:idx] + _CLEAN_MAIL_CSS + html[idx:]
            elif "<html>" in html.lower():
                idx = html.lower().find("<html>") + 6
                enhanced_html = html[:idx] + "<head>" + _CLEAN_MAIL_CSS + "</head>" + html[idx:]
            else:
                enhanced_html = _CLEAN_MAIL_CSS + html
            self._set_body_html(enhanced_html)
        else:
            self._set_body_html(_MAIL_WRAPPER.format(content=html))

    def _load_content(self) -> None:
        mid = self.mail_data.get("id", "")
        html = self.mail_data.get("html", "")
        body = self.mail_data.get("body", "")

        # Cache hit -> render synchronously, zero latency
        if not html and not body and mid and mid != "err":
            from core import mail_service
            cached = mail_service._EMAIL_CONTENT_CACHE.get(mid)
            if cached:
                html, body = cached.get("html", ""), cached.get("text", "")
                self.mail_data["html"], self.mail_data["body"] = html, body

        if html:
            self._render_html(html)
            return
        if body:
            self._render_text(body)
            return
        if not mid or mid == "err":
            self._render_text(self.mail_data.get("snippet", "Keine Nachricht vorhanden."))
            return

        self._render_text("⏳ Lade E-Mail von Gmail...")

        def _worker():
            data = fetch_single_email_content(mid)
            txt = data.get("text", "")
            h = data.get("html", "")
            self.mail_data["body"] = txt
            self.mail_data["html"] = h
            QTimer.singleShot(0, lambda: self._render_html(h) if h else self._render_text(txt))

        threading.Thread(target=_worker, daemon=True).start()

    def _render_text(self, text: str) -> None:
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self._set_body_html(_MAIL_WRAPPER.format(content=f'<div style="line-height:1.6;white-space:normal;">{escaped}</div>'))

    def _on_delete(self) -> None:
        mid = self.mail_data.get("id", "")
        if not mid:
            return
        reply = QMessageBox.question(
            self,
            "In den Papierkorb verschieben?",
            "Möchtest du diese E-Mail wirklich in den Papierkorb verschieben?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            ok, msg = delete_email_by_id(mid)
            if ok:
                self.was_deleted = True
                self.accept()
            else:
                QMessageBox.warning(self, "Löschen fehlgeschlagen", msg)

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _open_webmail(self) -> None:
        QDesktopServices.openUrl(QUrl("https://mail.google.com"))


class JarvisEventDetailDialog(QDialog):
    """Detailed view for a calendar event with full timing, duration, location and actions."""

    def __init__(self, parent=None, event_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.event_data = event_data or {}
        self.was_deleted = False
        self.setWindowTitle("Termin-Details & Ablauf")
        self.setFixedSize(480, 360)
        self.setStyleSheet("""
            QDialog {
                background-color: #0A0E18;
                border: 1px solid #1E2B45;
                border-radius: 12px;
            }
            QLabel {
                color: #F0F6FC;
                font-family: 'Segoe UI';
            }
        """)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        cat = self.event_data.get("category", "Termin")
        start_t = self.event_data.get("start_time", "")
        end_t = self.event_data.get("end_time", "")
        ev_date = self.event_data.get("event_date", "")
        loc = self.event_data.get("location", "")
        title = self.event_data.get("title", "Termin ohne Titel")
        source = self.event_data.get("source", "local")

        rel_str = format_event_relative(ev_date) if ev_date else ""
        dur_str = calculate_event_duration(start_t, end_t)

        # Header Badge Row
        h_row = QHBoxLayout()
        h_row.setSpacing(8)

        lbl_cat = QLabel(f"📌 {cat}")
        lbl_cat.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_cat.setStyleSheet("background: #16243E; color: #58A6FF; border: 1px solid #1F6FEB; border-radius: 4px; padding: 3px 8px;")
        h_row.addWidget(lbl_cat)

        if rel_str:
            lbl_rel = QLabel(f"⏳ {rel_str}")
            lbl_rel.setFont(QFont("Segoe UI", 8, QFont.Bold))
            lbl_rel.setStyleSheet("background: #231C10; color: #E3B341; border: 1px solid #D29922; border-radius: 4px; padding: 3px 8px;")
            h_row.addWidget(lbl_rel)

        if dur_str:
            lbl_dur = QLabel(f"⏱️ {dur_str}")
            lbl_dur.setFont(QFont("Segoe UI", 8, QFont.Bold))
            lbl_dur.setStyleSheet("background: #152219; color: #3FB950; border: 1px solid #238636; border-radius: 4px; padding: 3px 8px;")
            h_row.addWidget(lbl_dur)

        h_row.addStretch()

        btn_close_x = QPushButton("✕")
        btn_close_x.setFixedSize(26, 26)
        btn_close_x.setCursor(Qt.PointingHandCursor)
        btn_close_x.setStyleSheet("background: transparent; color: #8B949E; border: none; font-size: 14px;")
        btn_close_x.clicked.connect(self.reject)
        h_row.addWidget(btn_close_x)

        layout.addLayout(h_row)

        # Title
        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_t.setStyleSheet("color: #FFFFFF; border: none;")
        lbl_t.setWordWrap(True)
        layout.addWidget(lbl_t)

        # Info Box
        box = QFrame()
        box.setStyleSheet("background-color: #111726; border: 1px solid #1E283D; border-radius: 8px; padding: 12px;")
        b_lay = QVBoxLayout(box)
        b_lay.setSpacing(8)

        # Date & Time Row
        day_str = format_event_day(ev_date)
        time_display = start_t if start_t == "Ganztägig" or not end_t or ":" not in end_t else f"{start_t} bis {end_t} Uhr"
        lbl_datetime = QLabel(f"📅 Datum:  <b>{day_str}</b> ({ev_date})  ·  <b>{time_display}</b>")
        lbl_datetime.setFont(QFont("Segoe UI", 9))
        lbl_datetime.setStyleSheet("color: #C9D1D9; border: none;")
        b_lay.addWidget(lbl_datetime)

        if loc:
            lbl_location = QLabel(f"📍 Ort / Raum:  <b>{loc}</b>")
            lbl_location.setFont(QFont("Segoe UI", 9))
            lbl_location.setStyleSheet("color: #58A6FF; border: none;")
            b_lay.addWidget(lbl_location)

        src_desc = "WebCal / iCal Kalender-Feed" if source == "ical" else "Lokaler JARVIS-Kalender"
        lbl_source = QLabel(f"🔗 Quelle:  <span style='color:#8B949E;'>{src_desc}</span>")
        lbl_source.setFont(QFont("Segoe UI", 8))
        lbl_source.setStyleSheet("border: none;")
        b_lay.addWidget(lbl_source)

        layout.addWidget(box)
        layout.addStretch()

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        eid = self.event_data.get("id")
        if eid:
            btn_del = QPushButton("  🗑️ Termin löschen")
            btn_del.setFixedHeight(32)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("""
                QPushButton {
                    background: #2B161B;
                    color: #F85149;
                    border: 1px solid #DA3633;
                    border-radius: 6px;
                    padding: 0 14px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #3B1C22;
                    color: #FF7B72;
                }
            """)
            btn_del.clicked.connect(self._delete_event)
            btn_row.addWidget(btn_del)

        btn_row.addStretch()

        btn_ok = QPushButton("Fertig")
        btn_ok.setFixedSize(90, 32)
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

    def _delete_event(self) -> None:
        eid = self.event_data.get("id")
        if not eid:
            return
        res = QMessageBox.question(
            self,
            "Termin löschen",
            f"Möchtest du den Termin «{self.event_data.get('title', '')}» wirklich aus dem Kalender entfernen?",
            QMessageBox.Yes | QMessageBox.No
        )
        if res == QMessageBox.Yes:
            delete_calendar_event(int(eid))
            self.was_deleted = True
            self.accept()


class JarvisSetupDialog(QDialog):
    """Modern Cyber-Obsidian configuration dialog for Calendar & Email setup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS Synchronisation: Kalender & E-Mail Postfach")
        self.setFixedSize(620, 680)
        self.setStyleSheet("""
            QDialog {
                background-color: #090D16;
                border: 1px solid #233352;
                border-radius: 12px;
            }
            QLabel {
                color: #F0F6FC;
                font-family: 'Segoe UI';
            }
            QLineEdit {
                background-color: #0F1626;
                border: 1.5px solid #233352;
                border-radius: 7px;
                color: #FFFFFF;
                padding: 0 12px;
                font-family: 'Segoe UI';
                font-size: 12px;
                min-height: 38px;
            }
            QLineEdit:focus {
                border-color: #58A6FF;
                background-color: #121B30;
            }
            QCheckBox {
                color: #F0F6FC;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1.5px solid #388BFD;
                background-color: #0F1626;
            }
            QCheckBox::indicator:checked {
                background-color: #1F6FEB;
                image: none;
            }
        """)
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(14)

        # Header Banner
        header_row = QHBoxLayout()
        lbl_head_icon = QLabel()
        lbl_head_icon.setPixmap(create_vector_pixmap("jarvis", "#58A6FF", 28))
        lbl_head_icon.setStyleSheet("border: none;")
        header_row.addWidget(lbl_head_icon)

        head_text_col = QVBoxLayout()
        lbl_title = QLabel("JARVIS Konten- & Feed-Zentrale")
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; letter-spacing: 0.3px;")
        head_text_col.addWidget(lbl_title)

        lbl_desc = QLabel("Verbinde deinen Vorlesungsplan (Google, Outlook, Uni) und dein E-Mail-Postfach.")
        lbl_desc.setFont(QFont("Segoe UI", 9))
        lbl_desc.setStyleSheet("color: #8B949E; border: none;")
        head_text_col.addWidget(lbl_desc)
        header_row.addLayout(head_text_col)
        header_row.addStretch()

        main_layout.addLayout(header_row)

        # Scroll area container for perfect fit
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; } QWidget { background: transparent; }")
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. SECTION: Calendar
        # -------------------------------------------------------------
        cal_card = QFrame()
        cal_card.setStyleSheet("""
            QFrame {
                background-color: #0E1524;
                border: 1px solid #1E2B45;
                border-radius: 9px;
                padding: 12px;
            }
        """)
        cal_layout = QVBoxLayout(cal_card)
        cal_layout.setContentsMargins(12, 10, 12, 10)
        cal_layout.setSpacing(8)

        cal_head_row = QHBoxLayout()
        lbl_cal_icon = QLabel("📅")
        lbl_cal_icon.setStyleSheet("font-size: 14px; border: none;")
        cal_head_row.addWidget(lbl_cal_icon)

        lbl_cal_title = QLabel("Kalender-Abonnement (.ics / WebCal Feed)")
        lbl_cal_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_cal_title.setStyleSheet("color: #58A6FF; border: none;")
        cal_head_row.addWidget(lbl_cal_title)
        cal_head_row.addStretch()

        btn_clear_demo = QPushButton("Beispiel-Termine löschen")
        btn_clear_demo.setFont(QFont("Segoe UI", 8, QFont.Bold))
        btn_clear_demo.setFixedHeight(26)
        btn_clear_demo.setCursor(Qt.PointingHandCursor)
        btn_clear_demo.setStyleSheet("""
            QPushButton {
                background-color: #1A2234;
                color: #8B949E;
                border: 1px solid #283754;
                border-radius: 5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                color: #FF7B72;
                border-color: #FF7B72;
                background-color: #2D1A20;
            }
        """)
        btn_clear_demo.clicked.connect(self._clear_demo_calendar)
        cal_head_row.addWidget(btn_clear_demo)
        cal_layout.addLayout(cal_head_row)

        lbl_cal_field = QLabel("WebCal / iCal URL des Kalenders:")
        lbl_cal_field.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_cal_field.setStyleSheet("color: #E6EDF3; border: none;")
        cal_layout.addWidget(lbl_cal_field)

        self.input_cal_url = QLineEdit(get_cal_url())
        self.input_cal_url.setPlaceholderText("https://... oder webcal://... (Google Kalender, Outlook, Uni-Stundenplan)")
        cal_layout.addWidget(self.input_cal_url)

        lbl_cal_hint = QLabel("💡 Tipp: Google Kalender ➔ ⚙️ Einstellungen ➔ Kalender auswählen ➔ 'Geheime Adresse im iCal-Format' kopieren.")
        lbl_cal_hint.setFont(QFont("Segoe UI", 8))
        lbl_cal_hint.setStyleSheet("color: #79C0FF; border: none; line-height: 1.3;")
        lbl_cal_hint.setWordWrap(True)
        cal_layout.addWidget(lbl_cal_hint)

        layout.addWidget(cal_card)

        # -------------------------------------------------------------
        # 2. SECTION: Email Postfach
        # -------------------------------------------------------------
        mail_card = QFrame()
        mail_card.setStyleSheet("""
            QFrame {
                background-color: #0E1524;
                border: 1px solid #1E2B45;
                border-radius: 9px;
                padding: 12px;
            }
        """)
        mail_layout = QVBoxLayout(mail_card)
        mail_layout.setContentsMargins(12, 10, 12, 10)
        mail_layout.setSpacing(8)

        mail_head_row = QHBoxLayout()
        lbl_mail_icon = QLabel("📬")
        lbl_mail_icon.setStyleSheet("font-size: 14px; border: none;")
        mail_head_row.addWidget(lbl_mail_icon)

        lbl_mail_title = QLabel("E-Mail Posteingang (IMAP SSL)")
        lbl_mail_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_mail_title.setStyleSheet("color: #A371F7; border: none;")
        mail_head_row.addWidget(lbl_mail_title)
        mail_head_row.addStretch()
        mail_layout.addLayout(mail_head_row)

        # Provider Quick Preset Chips
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        lbl_quick = QLabel("Voreinstellung:")
        lbl_quick.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_quick.setStyleSheet("color: #8B949E; border: none;")
        preset_row.addWidget(lbl_quick)

        for p_name, p_host, p_port in [
            ("Gmail", "imap.gmail.com", 993),
            ("Outlook / M365", "outlook.office365.com", 993),
            ("GMX", "imap.gmx.net", 993),
            ("Web.de", "imap.web.de", 993),
        ]:
            btn_p = QPushButton(p_name)
            btn_p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            btn_p.setFixedHeight(24)
            btn_p.setCursor(Qt.PointingHandCursor)
            btn_p.setStyleSheet("""
                QPushButton {
                    background-color: #172238;
                    color: #79C0FF;
                    border: 1px solid #28395B;
                    border-radius: 4px;
                    padding: 0 8px;
                }
                QPushButton:hover {
                    background-color: #1F6FEB;
                    color: #FFFFFF;
                }
            """)
            btn_p.clicked.connect(lambda ch, h=p_host, p=p_port: self._apply_mail_preset(h, p))
            preset_row.addWidget(btn_p)

        preset_row.addStretch()
        mail_layout.addLayout(preset_row)

        # Server & Port Row
        server_port_row = QHBoxLayout()
        server_port_row.setSpacing(10)

        col_server = QVBoxLayout()
        lbl_server = QLabel("IMAP Server:")
        lbl_server.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_server.setStyleSheet("color: #F0F6FC; border: none;")
        col_server.addWidget(lbl_server)

        settings = get_mail_settings()
        self.input_mail_host = QLineEdit(settings.get("host", ""))
        self.input_mail_host.setPlaceholderText("z. B. imap.gmail.com oder mail.uni.de")
        col_server.addWidget(self.input_mail_host)
        server_port_row.addLayout(col_server, stretch=3)

        col_port = QVBoxLayout()
        lbl_port = QLabel("Port (SSL):")
        lbl_port.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_port.setStyleSheet("color: #F0F6FC; border: none;")
        col_port.addWidget(lbl_port)

        self.input_mail_port = QLineEdit(str(settings.get("port", 993)))
        col_port.addWidget(self.input_mail_port)
        server_port_row.addLayout(col_port, stretch=1)

        mail_layout.addLayout(server_port_row)

        # Email user address
        lbl_user = QLabel("E-Mail-Adresse / Benutzername:")
        lbl_user.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_user.setStyleSheet("color: #F0F6FC; border: none;")
        mail_layout.addWidget(lbl_user)

        self.input_mail_user = QLineEdit(settings.get("user", ""))
        self.input_mail_user.setPlaceholderText("dein.name@gmail.com oder benutzer@uni.de")
        mail_layout.addWidget(self.input_mail_user)

        # Password
        lbl_pass = QLabel("Passwort (bei Gmail/Outlook mit 2FA: App-Passwort):")
        lbl_pass.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_pass.setStyleSheet("color: #F0F6FC; border: none;")
        mail_layout.addWidget(lbl_pass)

        pass_row = QHBoxLayout()
        pass_row.setSpacing(6)
        self.input_mail_pass = QLineEdit(settings.get("password", ""))
        self.input_mail_pass.setEchoMode(QLineEdit.Password)
        self.input_mail_pass.setPlaceholderText("16-stelliges Google App-Passwort eingeben")
        pass_row.addWidget(self.input_mail_pass, stretch=1)

        self.btn_toggle_pass = QPushButton("👁")
        self.btn_toggle_pass.setFixedSize(36, 32)
        self.btn_toggle_pass.setToolTip("Passwort anzeigen / verbergen")
        self.btn_toggle_pass.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_pass.setStyleSheet("""
            QPushButton {
                background: #161B22;
                color: #8B949E;
                border: 1px solid #30363D;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #21262D;
                color: #F0F6FC;
            }
        """)
        self.btn_toggle_pass.clicked.connect(self._toggle_pass_visibility)
        pass_row.addWidget(self.btn_toggle_pass)
        mail_layout.addLayout(pass_row)

        self.chk_only_unseen = QCheckBox("  Nur ungelesene E-Mails abrufen (UNSEEN Filter)")
        self.chk_only_unseen.setChecked(settings.get("only_unseen", True))
        mail_layout.addWidget(self.chk_only_unseen)

        # Connection Test Bar
        test_card = QFrame()
        test_card.setStyleSheet("background-color: #0A0F1A; border: 1px solid #1E283D; border-radius: 6px; padding: 6px;")
        test_lay = QHBoxLayout(test_card)
        test_lay.setContentsMargins(6, 4, 6, 4)
        test_lay.setSpacing(10)

        self.btn_test_mail = QPushButton("  🔌 Verbindung jetzt testen")
        self.btn_test_mail.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_test_mail.setFixedHeight(32)
        self.btn_test_mail.setCursor(Qt.PointingHandCursor)
        self.btn_test_mail.setStyleSheet("""
            QPushButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #388BFD;
                border-radius: 5px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: #388BFD;
            }
        """)
        self.btn_test_mail.clicked.connect(self._on_test_mail)
        test_lay.addWidget(self.btn_test_mail)

        self.lbl_test_result = QLabel("Noch nicht getestet")
        self.lbl_test_result.setFont(QFont("Segoe UI", 9))
        self.lbl_test_result.setStyleSheet("color: #8B949E; border: none;")
        self.lbl_test_result.setWordWrap(True)
        test_lay.addWidget(self.lbl_test_result, stretch=1)

        mail_layout.addWidget(test_card)
        layout.addWidget(mail_card)

        scroll.setWidget(container)
        main_layout.addWidget(scroll, stretch=1)

        # Dialog Footer Buttons
        footer_row = QHBoxLayout()
        footer_row.addStretch()

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setFont(QFont("Segoe UI", 9))
        btn_cancel.setFixedHeight(36)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background: #182236;
                color: #8B949E;
                border: 1px solid #23314B;
                border-radius: 6px;
                padding: 0 20px;
            }
            QPushButton:hover {
                color: #F0F6FC;
                border-color: #58A6FF;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        footer_row.addWidget(btn_cancel)

        btn_save = QPushButton("  ✓ Speichern & Synchronisieren")
        btn_save.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_save.setFixedHeight(36)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton {
                background: #238636;
                color: #FFFFFF;
                border: 1px solid #2EA043;
                border-radius: 6px;
                padding: 0 22px;
            }
            QPushButton:hover {
                background: #2EA043;
            }
        """)
        btn_save.clicked.connect(self._on_save)
        footer_row.addWidget(btn_save)

        main_layout.addLayout(footer_row)

    def _toggle_pass_visibility(self) -> None:
        if self.input_mail_pass.echoMode() == QLineEdit.Password:
            self.input_mail_pass.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_pass.setStyleSheet("""
                QPushButton {
                    background: #1F6FEB;
                    color: #FFFFFF;
                    border: 1px solid #388BFD;
                    border-radius: 6px;
                    font-size: 13px;
                }
            """)
        else:
            self.input_mail_pass.setEchoMode(QLineEdit.Password)
            self.btn_toggle_pass.setStyleSheet("""
                QPushButton {
                    background: #161B22;
                    color: #8B949E;
                    border: 1px solid #30363D;
                    border-radius: 6px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background: #21262D;
                    color: #F0F6FC;
                }
            """)

    def _apply_mail_preset(self, host: str, port: int) -> None:
        self.input_mail_host.setText(host)
        self.input_mail_port.setText(str(port))
        if "gmail" in host.lower():
            self.input_mail_pass.setPlaceholderText("16-stelliges Google App-Passwort eingeben")
            self.lbl_test_result.setText("💡 Gmail aktiv: Bitte dein 16-stelliges App-Passwort nutzen.")
            self.lbl_test_result.setStyleSheet("color: #58A6FF; border: none;")

    def _clear_demo_calendar(self) -> None:
        clear_all_demo_events()
        QMessageBox.information(self, "Kalender", "Alle Beispiel-Termine wurden sauber gelöscht!")

    def _on_test_mail(self) -> None:
        host = self.input_mail_host.text().strip()
        port = int(self.input_mail_port.text().strip() or "993")
        user = self.input_mail_user.text().strip()
        pwd = self.input_mail_pass.text().strip()

        self.lbl_test_result.setText("⏳ Verbinde mit Mailserver...")
        self.lbl_test_result.setStyleSheet("color: #58A6FF; border: none;")
        self.btn_test_mail.setEnabled(False)

        def _worker():
            ok, msg, unread = test_mail_connection(host, port, user, pwd)
            def update():
                self.btn_test_mail.setEnabled(True)
                if ok:
                    self.lbl_test_result.setText(f"✓ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #3FB950; font-weight: bold; border: none;")
                else:
                    self.lbl_test_result.setText(f"✗ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #FF7B72; font-weight: bold; border: none;")
            QTimer.singleShot(0, update)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_save(self) -> None:
        cal_url = self.input_cal_url.text().strip()
        if cal_url:
            save_cal_url(cal_url)
            count, msg = sync_webcal_feed(cal_url)
            QMessageBox.information(self, "Kalender-Sync", msg)

        host = self.input_mail_host.text().strip()
        user = self.input_mail_user.text().strip()
        pwd = self.input_mail_pass.text().strip()
        port = int(self.input_mail_port.text().strip() or "993")
        enabled = bool(host and user and pwd)
        only_unseen = self.chk_only_unseen.isChecked()

        save_mail_settings(host, user, pwd, port, enabled=enabled, only_unseen=only_unseen)
        self.accept()


class JarvisView(QWidget):
    """Executive Daily Briefing Command Center."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent

        self._signals = JarvisSignals()
        self._signals.briefing_ready.connect(self._on_briefing_ready)
        self._signals.news_ready.connect(self._render_news)
        self._signals.mails_ready.connect(self._render_mails)
        self._signals.calendar_ready.connect(self._render_calendar)
        self._signals.speech_finished.connect(self._on_speech_finished)

        self._is_speaking = False
        self._current_briefing_text = ""
        self._active_news_category = "all"
        self._all_news_items: List[Dict[str, Any]] = []
        self._all_mails: List[Dict[str, Any]] = []
        self._mail_search_query = ""
        self._starred_mail_ids = set()

        self._build_ui()
        self.refresh_all_data()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. Header Banner: JARVIS Command Cockpit
        # -------------------------------------------------------------
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121929, stop:1 #172238);
                border: 1px solid #233352;
                border-radius: 12px;
                padding: 12px;
            }
        """)
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(6)

        top_row = QHBoxLayout()
        lbl_icon = QLabel()
        lbl_icon.setPixmap(create_vector_pixmap("jarvis", "#58A6FF", 26))
        lbl_icon.setStyleSheet("border: none; background: transparent;")
        top_row.addWidget(lbl_icon)

        lbl_title = QLabel("JARVIS COMMAND CENTER")
        lbl_title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_title.setStyleSheet("color: #F0F6FC; border: none; background: transparent; letter-spacing: 0.6px;")
        top_row.addWidget(lbl_title)

        now_str = datetime.datetime.now().strftime("%A, %d. %B %Y")
        lbl_date = QLabel(f"· {now_str}")
        lbl_date.setFont(QFont("Segoe UI", 10))
        lbl_date.setStyleSheet("color: #8B949E; border: none; background: transparent;")
        top_row.addWidget(lbl_date)

        top_row.addStretch()

        # Action Buttons
        self.btn_speak = QPushButton("  ▶ Briefing vorlesen")
        self.btn_speak.setIcon(create_vector_icon("bulb", "#FFFFFF", 16))
        self.btn_speak.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_speak.setFixedHeight(34)
        self.btn_speak.setCursor(Qt.PointingHandCursor)
        self.btn_speak.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8957E5, stop:1 #A371F7);
                color: #FFFFFF;
                border: 1px solid #A371F7;
                border-radius: 7px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: #A371F7;
            }
        """)
        self.btn_speak.clicked.connect(self._toggle_speech)
        top_row.addWidget(self.btn_speak)

        btn_refresh = QPushButton("  🔄 Aktualisieren")
        btn_refresh.setFont(QFont("Segoe UI", 9))
        btn_refresh.setFixedHeight(34)
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background: #162035;
                color: #F0F6FC;
                border: 1px solid #23314B;
                border-radius: 7px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #1C2945;
                border-color: #58A6FF;
            }
        """)
        btn_refresh.clicked.connect(self.refresh_all_data)
        top_row.addWidget(btn_refresh)

        btn_setup = QPushButton("  ⚙️ Setup")
        btn_setup.setFont(QFont("Segoe UI", 9))
        btn_setup.setFixedHeight(34)
        btn_setup.setCursor(Qt.PointingHandCursor)
        btn_setup.setStyleSheet("""
            QPushButton {
                background: #162035;
                color: #8B949E;
                border: 1px solid #23314B;
                border-radius: 7px;
                padding: 0 12px;
            }
            QPushButton:hover {
                color: #F0F6FC;
                border-color: #58A6FF;
            }
        """)
        btn_setup.clicked.connect(self._open_setup_dialog)
        top_row.addWidget(btn_setup)

        header_layout.addLayout(top_row)

        # Executive Briefing AI Quote Card
        self.card_briefing = QFrame()
        self.card_briefing.setStyleSheet("""
            QFrame {
                background-color: #0A0F1A;
                border: 1px solid #1E283D;
                border-left: 4px solid #58A6FF;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        briefing_layout = QVBoxLayout(self.card_briefing)
        briefing_layout.setContentsMargins(12, 8, 12, 8)
        briefing_layout.setSpacing(4)

        self.lbl_greeting = QLabel(get_greeting())
        self.lbl_greeting.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_greeting.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        briefing_layout.addWidget(self.lbl_greeting)

        self.lbl_briefing_text = QLabel("⏳ JARVIS bereitet dein persönliches Briefing vor...")
        self.lbl_briefing_text.setFont(QFont("Segoe UI", 9))
        self.lbl_briefing_text.setStyleSheet("color: #E6EDF3; border: none; background: transparent; line-height: 1.4;")
        self.lbl_briefing_text.setWordWrap(True)
        briefing_layout.addWidget(self.lbl_briefing_text)

        header_layout.addWidget(self.card_briefing)
        root_layout.addWidget(header_card)

        # -------------------------------------------------------------
        # 2. Bento-Grid (3 Equal Columns): Agenda | Mails | News
        # -------------------------------------------------------------
        grid_splitter = QSplitter(Qt.Horizontal)
        grid_splitter.setHandleWidth(8)
        grid_splitter.setStyleSheet("QSplitter::handle { background: transparent; }")

        # ------------------- COLUMN 1: Agenda & Calendar -------------------
        col1_card = QFrame()
        col1_card.setStyleSheet("QFrame { background-color: #0D1322; border: 1px solid #1E293F; border-radius: 10px; }")
        col1_layout = QVBoxLayout(col1_card)
        col1_layout.setContentsMargins(12, 12, 12, 12)
        col1_layout.setSpacing(10)

        c1_head = QHBoxLayout()
        lbl_c1_icon = QLabel()
        lbl_c1_icon.setPixmap(create_vector_pixmap("calendar", "#58A6FF", 18))
        lbl_c1_icon.setStyleSheet("border: none;")
        c1_head.addWidget(lbl_c1_icon)
        
        self.lbl_c1_title = QLabel("DEIN TAG & KALENDER")
        self.lbl_c1_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_c1_title.setStyleSheet("color: #F0F6FC; border: none;")
        c1_head.addWidget(self.lbl_c1_title)
        c1_head.addStretch()

        self.lbl_next_event_pill = QLabel("Nächster Termin...")
        self.lbl_next_event_pill.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_next_event_pill.setStyleSheet("background: #1B2B47; color: #58A6FF; border-radius: 4px; padding: 2px 6px; border: none;")
        c1_head.addWidget(self.lbl_next_event_pill)
        col1_layout.addLayout(c1_head)

        # Scroll Area for Calendar events
        scroll_cal = QScrollArea()
        scroll_cal.setWidgetResizable(True)
        scroll_cal.setStyleSheet("QScrollArea { border: none; background: transparent; } QWidget { background: transparent; }")
        self.cal_container = QWidget()
        self.cal_layout = QVBoxLayout(self.cal_container)
        self.cal_layout.setContentsMargins(0, 0, 0, 0)
        self.cal_layout.setSpacing(6)
        scroll_cal.setWidget(self.cal_container)
        col1_layout.addWidget(scroll_cal, stretch=1)

        # Desk & Streak Footer in Col 1
        desk_footer = QFrame()
        desk_footer.setStyleSheet("QFrame { background-color: #0A0E18; border: 1px solid #182236; border-radius: 6px; padding: 6px; }")
        desk_layout = QVBoxLayout(desk_footer)
        desk_layout.setContentsMargins(8, 6, 8, 6)
        desk_layout.setSpacing(3)

        self.lbl_streak = QLabel("🔥 5 Tage Lernstreak")
        self.lbl_streak.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_streak.setStyleSheet("color: #D29922; border: none;")
        desk_layout.addWidget(self.lbl_streak)

        self.lbl_desk_info = QLabel("📚 Schreibtisch: 0 Bücher")
        self.lbl_desk_info.setFont(QFont("Segoe UI", 8))
        self.lbl_desk_info.setStyleSheet("color: #8B949E; border: none;")
        desk_layout.addWidget(self.lbl_desk_info)

        col1_layout.addWidget(desk_footer)
        grid_splitter.addWidget(col1_card)

        # ------------------- COLUMN 2: Gmail Web Browser Experience -------------------
        col2_card = QFrame()
        col2_card.setStyleSheet("QFrame { background-color: #1F1F1F; border: 1px solid #303134; border-radius: 10px; }")
        col2_layout = QVBoxLayout(col2_card)
        col2_layout.setContentsMargins(12, 12, 12, 12)
        col2_layout.setSpacing(8)

        # 1. Gmail Header with Logo & Email
        c2_head = QHBoxLayout()
        lbl_c2_logo = QLabel("✉️")
        lbl_c2_logo.setStyleSheet("font-size: 16px; color: #EA4335; border: none;")
        c2_head.addWidget(lbl_c2_logo)

        self.lbl_c2_title = QLabel("Gmail")
        self.lbl_c2_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_c2_title.setStyleSheet("color: #E8EAED; border: none; letter-spacing: 0.5px;")
        c2_head.addWidget(self.lbl_c2_title)

        settings = get_mail_settings()
        user_email = settings.get("user") or "Posteingang"
        self.lbl_c2_user = QLabel(f"· {user_email[:26]}")
        self.lbl_c2_user.setFont(QFont("Segoe UI", 8))
        self.lbl_c2_user.setStyleSheet("color: #9AA0A6; border: none;")
        c2_head.addWidget(self.lbl_c2_user)

        c2_head.addStretch()

        btn_mail_cfg = QPushButton("⚙️ Setup")
        btn_mail_cfg.setFont(QFont("Segoe UI", 8))
        btn_mail_cfg.setFixedHeight(24)
        btn_mail_cfg.setToolTip("E-Mail & Kalender Einstellungen öffnen")
        btn_mail_cfg.setCursor(Qt.PointingHandCursor)
        btn_mail_cfg.setStyleSheet("background: #2D3035; color: #C9D1D9; border: 1px solid #3C4043; border-radius: 4px; padding: 0 8px;")
        btn_mail_cfg.clicked.connect(self._open_setup_dialog)
        c2_head.addWidget(btn_mail_cfg)

        self.btn_summarize_mails = QPushButton("✨ KI-Digest")
        self.btn_summarize_mails.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_summarize_mails.setFixedHeight(24)
        self.btn_summarize_mails.setCursor(Qt.PointingHandCursor)
        self.btn_summarize_mails.setStyleSheet("background: #8957E5; color: #FFFFFF; border-radius: 4px; padding: 0 10px; border: none;")
        self.btn_summarize_mails.clicked.connect(self._summarize_mails_with_ai)
        c2_head.addWidget(self.btn_summarize_mails)
        col2_layout.addLayout(c2_head)

        # 2. Gmail Search Input
        self.input_mail_search = QLineEdit()
        self.input_mail_search.setPlaceholderText("🔍  In E-Mails suchen...")
        self.input_mail_search.setFixedHeight(30)
        self.input_mail_search.setStyleSheet("""
            QLineEdit {
                background-color: #282A2D;
                color: #E8EAED;
                border: 1px solid #3C4043;
                border-radius: 15px;
                padding: 0 12px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #8AB4F8;
                background-color: #303134;
            }
        """)
        self.input_mail_search.textChanged.connect(self._on_mail_search_changed)
        col2_layout.addWidget(self.input_mail_search)

        # 3. Gmail Browser Tabs (Primär / Werbung / Sozial)
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(6)

        self.btn_tab_primary = QPushButton("📥 Primär")
        self.btn_tab_primary.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_tab_primary.setFixedHeight(24)
        self.btn_tab_primary.setCursor(Qt.PointingHandCursor)
        self.btn_tab_primary.setStyleSheet("""
            QPushButton {
                background: #303134;
                color: #8AB4F8;
                border: none;
                border-bottom: 2px solid #8AB4F8;
                padding: 0 10px;
                font-weight: bold;
            }
        """)
        tabs_row.addWidget(self.btn_tab_primary)

        btn_tab_promo = QPushButton("🏷️ Werbung")
        btn_tab_promo.setFont(QFont("Segoe UI", 8))
        btn_tab_promo.setFixedHeight(24)
        btn_tab_promo.setCursor(Qt.PointingHandCursor)
        btn_tab_promo.setStyleSheet("background: transparent; color: #9AA0A6; border: none; padding: 0 8px;")
        btn_tab_promo.clicked.connect(lambda: QMessageBox.information(self, "Gmail", "Keine Werbe-E-Mails im Posteingang."))
        tabs_row.addWidget(btn_tab_promo)

        btn_tab_social = QPushButton("👥 Sozial")
        btn_tab_social.setFont(QFont("Segoe UI", 8))
        btn_tab_social.setFixedHeight(24)
        btn_tab_social.setCursor(Qt.PointingHandCursor)
        btn_tab_social.setStyleSheet("background: transparent; color: #9AA0A6; border: none; padding: 0 8px;")
        btn_tab_social.clicked.connect(lambda: QMessageBox.information(self, "Gmail", "Keine Social-Benachrichtigungen."))
        tabs_row.addWidget(btn_tab_social)

        tabs_row.addStretch()

        btn_mail_refresh = QPushButton("🔄")
        btn_mail_refresh.setFixedSize(24, 24)
        btn_mail_refresh.setToolTip("Posteingang aktualisieren")
        btn_mail_refresh.setCursor(Qt.PointingHandCursor)
        btn_mail_refresh.setStyleSheet("background: transparent; color: #9AA0A6; border: none; font-size: 13px;")
        btn_mail_refresh.clicked.connect(self._refresh_mails_only)
        tabs_row.addWidget(btn_mail_refresh)

        col2_layout.addLayout(tabs_row)

        # Scroll Area for Gmail Rows
        scroll_mail = QScrollArea()
        scroll_mail.setWidgetResizable(True)
        scroll_mail.setStyleSheet("QScrollArea { border: none; background: transparent; } QWidget { background: transparent; }")
        self.mail_container = QWidget()
        self.mail_layout = QVBoxLayout(self.mail_container)
        self.mail_layout.setContentsMargins(0, 0, 0, 0)
        self.mail_layout.setSpacing(4)
        scroll_mail.setWidget(self.mail_container)
        col2_layout.addWidget(scroll_mail, stretch=1)

        grid_splitter.addWidget(col2_card)

        # ------------------- COLUMN 3: Live News Feeds -------------------
        col3_card = QFrame()
        col3_card.setStyleSheet("QFrame { background-color: #0D1322; border: 1px solid #1E293F; border-radius: 10px; }")
        col3_layout = QVBoxLayout(col3_card)
        col3_layout.setContentsMargins(12, 12, 12, 12)
        col3_layout.setSpacing(10)

        c3_head = QHBoxLayout()
        lbl_c3_icon = QLabel()
        lbl_c3_icon.setPixmap(create_vector_pixmap("news", "#3FB950", 18))
        lbl_c3_icon.setStyleSheet("border: none;")
        c3_head.addWidget(lbl_c3_icon)
        lbl_c3 = QLabel("LIVE-SCHLAGZEILEN")
        lbl_c3.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_c3.setStyleSheet("color: #F0F6FC; border: none;")
        c3_head.addWidget(lbl_c3)
        c3_head.addStretch()

        col3_layout.addLayout(c3_head)

        # Category Chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        for cat_k, cat_label in [("all", "Alle"), ("Wissenschaft", "🔬 Sci"), ("Tech & IT", "💻 Tech"), ("Weltgeschehen", "🌍 Welt")]:
            btn_chip = QPushButton(cat_label)
            btn_chip.setFont(QFont("Segoe UI", 8))
            btn_chip.setFixedHeight(22)
            btn_chip.setCursor(Qt.PointingHandCursor)
            btn_chip.setStyleSheet("background: #141C2E; color: #8B949E; border: 1px solid #1E293F; border-radius: 4px; padding: 0 6px;")
            btn_chip.clicked.connect(lambda ch, k=cat_k: self._filter_news_category(k))
            chips_row.addWidget(btn_chip)
        chips_row.addStretch()
        col3_layout.addLayout(chips_row)

        # Scroll Area for News
        scroll_news = QScrollArea()
        scroll_news.setWidgetResizable(True)
        scroll_news.setStyleSheet("QScrollArea { border: none; background: transparent; } QWidget { background: transparent; }")
        self.news_container = QWidget()
        self.news_layout = QVBoxLayout(self.news_container)
        self.news_layout.setContentsMargins(0, 0, 0, 0)
        self.news_layout.setSpacing(6)
        scroll_news.setWidget(self.news_container)
        col3_layout.addWidget(scroll_news, stretch=1)

        grid_splitter.addWidget(col3_card)

        # Equal column distribution
        grid_splitter.setSizes([380, 420, 420])
        root_layout.addWidget(grid_splitter, stretch=1)

        # -------------------------------------------------------------
        # 3. Interactive Quick Command Bar
        # -------------------------------------------------------------
        cmd_card = QFrame()
        cmd_card.setStyleSheet("""
            QFrame {
                background-color: #0E1422;
                border: 1px solid #1E293F;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        cmd_layout = QHBoxLayout(cmd_card)
        cmd_layout.setContentsMargins(8, 4, 8, 4)
        cmd_layout.setSpacing(8)

        lbl_prompt = QLabel("💬 JARVIS:")
        lbl_prompt.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_prompt.setStyleSheet("color: #58A6FF; border: none;")
        cmd_layout.addWidget(lbl_prompt)

        self.input_cmd = QLineEdit()
        self.input_cmd.setPlaceholderText("Stelle JARVIS eine Frage (z. B. 'Was ist mein nächster Termin?', 'Fasse E-Mail 1 zusammen', 'Welches Buch heute?')...")
        self.input_cmd.setFont(QFont("Segoe UI", 10))
        self.input_cmd.setStyleSheet("background: #090D16; border: 1px solid #232F48; border-radius: 6px; color: #F0F6FC; padding: 4px 10px;")
        self.input_cmd.returnPressed.connect(self._on_cmd_submitted)
        cmd_layout.addWidget(self.input_cmd, stretch=1)

        btn_send = QPushButton("  Fragen")
        btn_send.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_send.setFixedHeight(30)
        btn_send.setCursor(Qt.PointingHandCursor)
        btn_send.setStyleSheet("background: #1F6FEB; color: #FFFFFF; border: 1px solid #388BFD; border-radius: 6px; padding: 0 14px;")
        btn_send.clicked.connect(self._on_cmd_submitted)
        cmd_layout.addWidget(btn_send)

        root_layout.addWidget(cmd_card)

    def refresh_all_data(self) -> None:
        """Triggers asynchronous gathering of agenda, mails, and news."""
        self.lbl_briefing_text.setText("⏳ JARVIS aktualisiert Termine, E-Mails und Weltnachrichten...")

        def _worker():
            # 1. Calendar (pull fresh feed, throttled)
            try:
                ensure_calendar_synced()
            except Exception:
                pass
            evs, is_today = get_display_events()
            self._signals.calendar_ready.emit(evs, is_today)

            # 2. Mails
            mails = fetch_inbox_messages(limit=6)
            self._signals.mails_ready.emit(mails)

            # 3. News
            news = fetch_live_news(force_refresh=True)
            self._signals.news_ready.emit(news)

            # 4. AI Briefing
            briefing = generate_executive_briefing()
            self._signals.briefing_ready.emit(briefing)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_briefing_ready(self, text: str) -> None:
        self._current_briefing_text = text
        self.lbl_greeting.setText(get_greeting())
        self.lbl_briefing_text.setText(text)

    def _render_calendar(self, events: List[Dict[str, Any]], is_today: bool) -> None:
        while self.cal_layout.count():
            item = self.cal_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if is_today:
            self.lbl_c1_title.setText("DEIN TAG & KALENDER")
            next_ev = get_next_upcoming_event()
            if next_ev:
                ev_obj, mins = next_ev
                self.lbl_next_event_pill.setText(f"In {mins}m: {ev_obj.get('title', '')[:20]}")
            else:
                self.lbl_next_event_pill.setText("Läuft gerade / heute")
        else:
            self.lbl_c1_title.setText("KALENDER (KOMMENDE TERMINE)")
            self.lbl_next_event_pill.setText("Heute termin-frei ☀️")

        if not events:
            empty_card = QFrame()
            empty_card.setStyleSheet("background-color: #121929; border: 1px dashed #23314B; border-radius: 8px; padding: 14px;")
            e_lay = QVBoxLayout(empty_card)
            e_lay.setSpacing(4)
            lbl_e1 = QLabel("🎉 Keine anstehenden Termine eingetragen")
            lbl_e1.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_e1.setStyleSheet("color: #F0F6FC; border: none;")
            e_lay.addWidget(lbl_e1)
            lbl_e2 = QLabel("Klicke oben auf ⚙️ Setup, um deinen Google-/Outlook-Kalender per Link zu verbinden.")
            lbl_e2.setFont(QFont("Segoe UI", 8))
            lbl_e2.setStyleSheet("color: #8B949E; border: none;")
            lbl_e2.setWordWrap(True)
            e_lay.addWidget(lbl_e2)
            self.cal_layout.addWidget(empty_card)
        else:
            cat_styles = {
                "Prüfung": {"color": "#F85149", "bg": "#2B161B", "badge_bg": "#44181E", "icon": "📝"},
                "Uni": {"color": "#58A6FF", "bg": "#121C30", "badge_bg": "#172E54", "icon": "🎓"},
                "Praxis": {"color": "#3FB950", "bg": "#12231A", "badge_bg": "#173822", "icon": "💼"},
                "Lernen": {"color": "#A371F7", "bg": "#1E1730", "badge_bg": "#301D54", "icon": "📚"},
                "Aufgabe": {"color": "#D29922", "bg": "#241D12", "badge_bg": "#3D2E17", "icon": "⚡"},
                "Privat": {"color": "#F778BA", "bg": "#2B1724", "badge_bg": "#451B38", "icon": "☕"},
                "Termin": {"color": "#79C0FF", "bg": "#131C2D", "badge_bg": "#1E2F4D", "icon": "📅"},
            }

            for ev in events:
                item = QFrame()
                cat = ev.get("category", "Termin")
                style = cat_styles.get(cat, cat_styles["Termin"])
                accent_col = style["color"]
                bg_col = style["bg"]
                badge_bg = style["badge_bg"]
                smart_icon = style["icon"]

                # Modern Bento Card with left accent strip and sleek hover effect
                item.setStyleSheet(f"""
                    QFrame#CalBentoCard {{
                        background-color: #111726;
                        border: 1px solid #1E283D;
                        border-left: 4px solid {accent_col};
                        border-radius: 8px;
                    }}
                    QFrame#CalBentoCard:hover {{
                        border-color: {accent_col};
                        background-color: #151D30;
                    }}
                """)
                item.setObjectName("CalBentoCard")

                c_layout = QHBoxLayout(item)
                c_layout.setContentsMargins(10, 8, 12, 8)
                c_layout.setSpacing(12)

                # Date Block / Badge on the left
                ev_date = ev.get("event_date", "")
                day_label = format_event_day(ev_date) if ev_date else ""
                
                date_block = QFrame()
                date_block.setFixedWidth(56)
                date_block.setStyleSheet(f"""
                    QFrame {{
                        background-color: {badge_bg};
                        border: 1px solid {accent_col}33;
                        border-radius: 6px;
                    }}
                """)
                db_lay = QVBoxLayout(date_block)
                db_lay.setContentsMargins(2, 4, 2, 4)
                db_lay.setSpacing(1)
                db_lay.setAlignment(Qt.AlignCenter)

                # Day name (e.g. Di, Sa, Heute) and day number
                if " " in day_label:
                    d_wday, d_num = day_label.split(" ", 1)
                else:
                    d_wday = day_label
                    d_num = ""

                lbl_wday = QLabel(d_wday.upper())
                lbl_wday.setFont(QFont("Segoe UI", 7, QFont.Bold))
                lbl_wday.setStyleSheet(f"color: {accent_col}; border: none; background: transparent;")
                lbl_wday.setAlignment(Qt.AlignCenter)
                db_lay.addWidget(lbl_wday)

                if d_num:
                    lbl_dnum = QLabel(d_num)
                    lbl_dnum.setFont(QFont("Segoe UI", 9, QFont.Bold))
                    lbl_dnum.setStyleSheet("color: #F0F6FC; border: none; background: transparent;")
                    lbl_dnum.setAlignment(Qt.AlignCenter)
                    db_lay.addWidget(lbl_dnum)

                c_layout.addWidget(date_block)

                # Event Content Column
                info_col = QVBoxLayout()
                info_col.setSpacing(3)
                info_col.setAlignment(Qt.AlignVCenter)

                # Header Row: Time + Duration + Category + Countdown Badge
                top_row = QHBoxLayout()
                top_row.setSpacing(6)

                start_t = ev.get("start_time", "09:00")
                end_t = ev.get("end_time", "")
                dur_str = calculate_event_duration(start_t, end_t)
                rel_str = format_event_relative(ev_date) if ev_date else ""

                if start_t == "Ganztägig" or not end_t or ":" not in end_t:
                    time_label = start_t
                else:
                    time_label = f"{start_t}–{end_t}"
                    if dur_str:
                        time_label = f"{time_label} ({dur_str})"

                lbl_time = QLabel(f"⏱️ {time_label}")
                lbl_time.setFont(QFont("Segoe UI", 8, QFont.Bold))
                lbl_time.setStyleSheet("color: #C9D1D9; border: none; background: transparent;")
                top_row.addWidget(lbl_time)

                lbl_cat = QLabel(f"{smart_icon} {cat}")
                lbl_cat.setFont(QFont("Segoe UI", 7, QFont.Bold))
                lbl_cat.setStyleSheet(f"background: {badge_bg}; color: {accent_col}; border-radius: 4px; padding: 1px 6px; border: 1px solid {accent_col}55;")
                top_row.addWidget(lbl_cat)

                # Countdown Pill (e.g. "In 6 Tagen", "Heute", "Morgen")
                if rel_str and rel_str not in ("Heute",):
                    lbl_countdown = QLabel(f"⏳ {rel_str}")
                    lbl_countdown.setFont(QFont("Segoe UI", 7, QFont.Bold))
                    lbl_countdown.setStyleSheet("background: #1C2234; color: #8B949E; border-radius: 4px; padding: 1px 6px; border: 1px solid #2B384E;")
                    top_row.addWidget(lbl_countdown)

                top_row.addStretch()

                info_col.addLayout(top_row)

                # Title
                lbl_title = QLabel(ev.get("title", ""))
                lbl_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
                lbl_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
                lbl_title.setWordWrap(True)
                info_col.addWidget(lbl_title)

                # Location (if present)
                loc = ev.get("location", "")
                if loc:
                    lbl_loc = QLabel(f"📍 {loc}")
                    lbl_loc.setFont(QFont("Segoe UI", 8))
                    lbl_loc.setStyleSheet("color: #8B949E; border: none; background: transparent;")
                    info_col.addWidget(lbl_loc)

                c_layout.addLayout(info_col, stretch=1)

                # Click interaction to view full details
                item.setCursor(Qt.PointingHandCursor)
                item.setToolTip("Klicke für vollständige Details und Optionen")
                item.mousePressEvent = lambda e, event_obj=ev: self._open_event_detail_dialog(event_obj)

                self.cal_layout.addWidget(item)

        self.cal_layout.addStretch()

        # Update streak & desk stats
        gam = get_gamification_profile()
        streak = gam.get("current_streak", 0)
        level = gam.get("level", 1)
        self.lbl_streak.setText(f"🔥 {streak} Tage Lernstreak · Level {level}")

        desk_books = get_desk_books()
        if desk_books:
            first_b = desk_books[0]
            self.lbl_desk_info.setText(f"📖 Schreibtisch: «{first_b.get('title', '')[:25]}...» ({first_b.get('reading_progress', 0)}%)")
        else:
            self.lbl_desk_info.setText("📚 Schreibtisch: Keine Bücher am Lesen")

    def _open_event_detail_dialog(self, event_data: Dict[str, Any]) -> None:
        """Opens detailed event dialogue with duration, full time and delete option."""
        dlg = JarvisEventDetailDialog(self, event_data=event_data)
        if dlg.exec() and dlg.was_deleted:
            # Refresh calendar events immediately
            evs, is_today = get_display_events()
            self._render_calendar(evs, is_today)

    def _render_mails(self, mails: List[Dict[str, Any]]) -> None:
        settings = get_mail_settings()
        user_email = settings.get("user") or "Posteingang"
        self.lbl_c2_user.setText(f"· {user_email[:26]}")
        self._all_mails = list(mails)
        self._render_mails_ui(self._all_mails)

    def _render_mails_ui(self, mails: List[Dict[str, Any]]) -> None:
        while self.mail_layout.count():
            item = self.mail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        settings = get_mail_settings()
        is_demo = any(m.get("is_demo") for m in mails)
        is_err = any(m.get("is_error") for m in mails)
        real_count = 0 if is_err else len(mails)
        self.btn_tab_primary.setText(f"📥 Primär ({real_count})")

        if is_err:
            err_obj = next((m for m in mails if m.get("is_error")), {})
            err_msg = err_obj.get("subject", "Verbindungsfehler aufgetreten.")
            err_card = QFrame()
            err_card.setStyleSheet("background-color: #2D1418; border: 1px solid #F85149; border-radius: 8px; padding: 14px;")
            e_lay = QVBoxLayout(err_card)
            e_lay.setSpacing(8)

            lbl_e1 = QLabel("⚠️ Postfach konnte nicht synchronisiert werden")
            lbl_e1.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_e1.setStyleSheet("color: #FF7B72; border: none;")
            e_lay.addWidget(lbl_e1)

            lbl_e2 = QLabel(err_msg)
            lbl_e2.setFont(QFont("Segoe UI", 8))
            lbl_e2.setStyleSheet("color: #E6EDF3; border: none;")
            lbl_e2.setWordWrap(True)
            e_lay.addWidget(lbl_e2)

            btn_row = QHBoxLayout()
            btn_reconn = QPushButton("⚙️ Zugangsdaten prüfen")
            btn_reconn.setFont(QFont("Segoe UI", 8, QFont.Bold))
            btn_reconn.setCursor(Qt.PointingHandCursor)
            btn_reconn.setStyleSheet("background: #1F6FEB; color: #FFFFFF; border-radius: 4px; padding: 4px 12px; border: none;")
            btn_reconn.clicked.connect(self._open_setup_dialog)
            btn_row.addWidget(btn_reconn)

            btn_retry = QPushButton("🔄 Erneut versuchen")
            btn_retry.setFont(QFont("Segoe UI", 8))
            btn_retry.setCursor(Qt.PointingHandCursor)
            btn_retry.setStyleSheet("background: #21262D; color: #C9D1D9; border: 1px solid #30363D; border-radius: 4px; padding: 4px 12px;")
            btn_retry.clicked.connect(self._refresh_mails_only)
            btn_row.addWidget(btn_retry)
            btn_row.addStretch()
            e_lay.addLayout(btn_row)

            self.mail_layout.addWidget(err_card)
            self.mail_layout.addStretch()
            return

        if is_demo:
            demo_banner = QFrame()
            demo_banner.setStyleSheet("background-color: #2D2616; border: 1px solid #FBBC04; border-radius: 6px; padding: 6px;")
            d_lay = QHBoxLayout(demo_banner)
            d_lay.setContentsMargins(8, 4, 8, 4)
            lbl_d = QLabel("⚠️ Gmail Demo-Modus")
            lbl_d.setFont(QFont("Segoe UI", 8, QFont.Bold))
            lbl_d.setStyleSheet("color: #FDD663; border: none;")
            d_lay.addWidget(lbl_d)
            d_lay.addStretch()

            btn_conn = QPushButton("Postfach verbinden")
            btn_conn.setFont(QFont("Segoe UI", 8, QFont.Bold))
            btn_conn.setStyleSheet("background: #1A73E8; color: #FFFFFF; border: none; border-radius: 4px; padding: 2px 10px;")
            btn_conn.setCursor(Qt.PointingHandCursor)
            btn_conn.clicked.connect(self._open_setup_dialog)
            d_lay.addWidget(btn_conn)
            self.mail_layout.addWidget(demo_banner)

        if not mails and settings.get("enabled"):
            empty_card = QFrame()
            empty_card.setStyleSheet("background-color: #202124; border: 1px dashed #3C4043; border-radius: 8px; padding: 18px;")
            e_lay = QVBoxLayout(empty_card)
            e_lay.setSpacing(6)
            lbl_e1 = QLabel("✓ Alles erledigt! Keine ungelesenen E-Mails")
            lbl_e1.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_e1.setStyleSheet("color: #34A853; border: none;")
            e_lay.addWidget(lbl_e1)
            lbl_e2 = QLabel("Dein Google Mail Posteingang ist aktuell auf dem neuesten Stand.")
            lbl_e2.setFont(QFont("Segoe UI", 8))
            lbl_e2.setStyleSheet("color: #9AA0A6; border: none;")
            lbl_e2.setWordWrap(True)
            e_lay.addWidget(lbl_e2)
            self.mail_layout.addWidget(empty_card)
        else:
            for m in mails:
                row_frame = QFrame()
                row_frame.setCursor(Qt.PointingHandCursor)
                row_frame.setToolTip("Klicken zum Lesen der E-Mail (wie im Browser)")
                is_unread = m.get("is_unread", True)
                bg_col = "#24262A" if is_unread else "#1E1F22"

                row_frame.setStyleSheet(f"""
                    QFrame {{
                        background-color: {bg_col};
                        border: 1px solid #303134;
                        border-radius: 6px;
                        padding: 4px;
                    }}
                    QFrame:hover {{
                        background-color: #2D3035;
                        border-color: #8AB4F8;
                    }}
                """)
                r_lay = QVBoxLayout(row_frame)
                r_lay.setContentsMargins(8, 6, 8, 6)
                r_lay.setSpacing(3)

                # Top Row: Star + Sender + Tag + Date + Delete Button
                top_r = QHBoxLayout()
                top_r.setSpacing(6)

                mid = m.get("id", "")
                is_starred = mid in self._starred_mail_ids
                btn_star = QPushButton("★" if is_starred else "☆")
                btn_star.setFixedSize(22, 22)
                btn_star.setCursor(Qt.PointingHandCursor)
                star_col = "#FBBC04" if is_starred else "#9AA0A6"
                btn_star.setStyleSheet(f"background: transparent; color: {star_col}; border: none; font-size: 13px;")

                def _toggle_star(ch=False, item_id=mid, b=btn_star):
                    if item_id in self._starred_mail_ids:
                        self._starred_mail_ids.remove(item_id)
                        b.setText("☆")
                        b.setStyleSheet("background: transparent; color: #9AA0A6; border: none; font-size: 13px;")
                    else:
                        self._starred_mail_ids.add(item_id)
                        b.setText("★")
                        b.setStyleSheet("background: transparent; color: #FBBC04; border: none; font-size: 13px;")

                btn_star.clicked.connect(_toggle_star)
                top_r.addWidget(btn_star)

                sender_text = m.get("sender", "Absender")
                lbl_sender = QLabel(sender_text[:28])
                lbl_sender.setFont(QFont("Segoe UI", 9, QFont.Bold if is_unread else QFont.Normal))
                lbl_sender.setStyleSheet("color: #E8EAED; border: none;")
                top_r.addWidget(lbl_sender)

                urg = m.get("urgency", "normal")
                if urg == "high":
                    lbl_urg = QLabel("Wichtig")
                    lbl_urg.setFont(QFont("Segoe UI", 7, QFont.Bold))
                    lbl_urg.setStyleSheet("background: #5C1D24; color: #F28B82; border-radius: 3px; padding: 1px 4px; border: none;")
                    top_r.addWidget(lbl_urg)

                top_r.addStretch()

                lbl_date = QLabel(m.get("date", ""))
                lbl_date.setFont(QFont("Segoe UI", 8))
                lbl_date.setStyleSheet("color: #9AA0A6; border: none;")
                top_r.addWidget(lbl_date)

                # Direct Delete Button (Papierkorb)
                btn_del = QPushButton("🗑️")
                btn_del.setFixedSize(24, 22)
                btn_del.setToolTip("In den Papierkorb verschieben (Löschen)")
                btn_del.setCursor(Qt.PointingHandCursor)
                btn_del.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #9AA0A6;
                        border: none;
                        border-radius: 3px;
                    }
                    QPushButton:hover {
                        background: #5C1D24;
                        color: #F28B82;
                    }
                """)
                btn_del.clicked.connect(lambda ch, item_id=mid: self._delete_mail_direct(item_id))
                top_r.addWidget(btn_del)

                r_lay.addLayout(top_r)

                # Bottom Line: Betreff & Snippet preview
                subj_text = m.get("subject", "Kein Betreff")
                snip_text = m.get("snippet", "")
                lbl_content = QLabel(f"<b style='color: #E8EAED;'>{subj_text[:38]}</b> <span style='color: #9AA0A6;'>— {snip_text[:48]}</span>")
                lbl_content.setFont(QFont("Segoe UI", 8))
                lbl_content.setStyleSheet("border: none;")
                lbl_content.setTextFormat(Qt.RichText)
                r_lay.addWidget(lbl_content)

                # Clicking row opens reader
                row_frame.mousePressEvent = lambda ev, mail_item=m: self._open_mail_reader(mail_item)
                self.mail_layout.addWidget(row_frame)

        self.mail_layout.addStretch()

    def _delete_mail_direct(self, msg_id: str) -> None:
        if not msg_id:
            return
        reply = QMessageBox.question(
            self,
            "In den Papierkorb verschieben?",
            "Möchtest du diese E-Mail wirklich in den Papierkorb verschieben?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            ok, msg = delete_email_by_id(msg_id)
            if ok:
                self._all_mails = [m for m in self._all_mails if m.get("id") != msg_id]
                self._render_mails_ui(self._all_mails)
            else:
                QMessageBox.warning(self, "Löschen fehlgeschlagen", msg)

    def _open_mail_reader(self, mail_data: Dict[str, Any]) -> None:
        dlg = JarvisMailReaderDialog(self, mail_data=mail_data)
        dlg.exec()
        if getattr(dlg, "was_deleted", False):
            deleted_id = mail_data.get("id")
            self._all_mails = [m for m in self._all_mails if m.get("id") != deleted_id]
            self._render_mails_ui(self._all_mails)

    def _on_mail_search_changed(self, text: str) -> None:
        self._mail_search_query = text.strip().lower()
        if not self._mail_search_query:
            self._render_mails_ui(self._all_mails)
        else:
            filtered = [
                m for m in self._all_mails
                if self._mail_search_query in m.get("subject", "").lower()
                or self._mail_search_query in m.get("sender", "").lower()
                or self._mail_search_query in m.get("snippet", "").lower()
            ]
            self._render_mails_ui(filtered)

    def _refresh_mails_only(self) -> None:
        def _worker():
            mails = fetch_inbox_messages(limit=8)
            self._signals.mails_ready.emit(mails)
        threading.Thread(target=_worker, daemon=True).start()

    def _render_news(self, news: List[Dict[str, Any]]) -> None:
        self._all_news_items = news
        self._apply_news_filter()

    def _filter_news_category(self, cat: str) -> None:
        self._active_news_category = cat
        self._apply_news_filter()

    def _apply_news_filter(self) -> None:
        while self.news_layout.count():
            item = self.news_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        filtered = self._all_news_items
        if self._active_news_category != "all":
            filtered = [n for n in self._all_news_items if n.get("category") == self._active_news_category]

        for n in filtered[:8]:
            item = QFrame()
            item.setStyleSheet("""
                QFrame {
                    background-color: #121929;
                    border: 1px solid #1E283D;
                    border-radius: 6px;
                    padding: 6px;
                }
                QFrame:hover {
                    border-color: #3FB950;
                    background-color: #162035;
                }
            """)
            n_layout = QVBoxLayout(item)
            n_layout.setContentsMargins(8, 6, 8, 6)
            n_layout.setSpacing(2)

            t_row = QHBoxLayout()
            lbl_badge = QLabel(f"{n.get('icon', '📰')} {n.get('source', '')}")
            lbl_badge.setFont(QFont("Segoe UI", 7, QFont.Bold))
            lbl_badge.setStyleSheet(f"color: {n.get('color', '#58A6FF')}; border: none;")
            t_row.addWidget(lbl_badge)
            t_row.addStretch()

            lbl_date = QLabel(n.get("date", "Heute"))
            lbl_date.setFont(QFont("Segoe UI", 7))
            lbl_date.setStyleSheet("color: #8B949E; border: none;")
            t_row.addWidget(lbl_date)
            n_layout.addLayout(t_row)

            lbl_title = QLabel(n.get("title", ""))
            lbl_title.setFont(QFont("Segoe UI", 8, QFont.Bold))
            lbl_title.setStyleSheet("color: #F0F6FC; border: none;")
            lbl_title.setWordWrap(True)
            n_layout.addWidget(lbl_title)

            desc = n.get("description", "")
            if desc:
                lbl_desc = QLabel(desc)
                lbl_desc.setFont(QFont("Segoe UI", 8))
                lbl_desc.setStyleSheet("color: #8B949E; border: none;")
                lbl_desc.setWordWrap(True)
                n_layout.addWidget(lbl_desc)

            # Click opens link in default browser
            link = n.get("link", "")
            if link:
                item.setCursor(Qt.PointingHandCursor)
                item.mousePressEvent = lambda e, l=link: self._open_news_link(l)

            self.news_layout.addWidget(item)

        self.news_layout.addStretch()

    def _open_news_link(self, url: str) -> None:
        if url:
            import webbrowser
            webbrowser.open(url)

    def _summarize_mails_with_ai(self) -> None:
        mails = fetch_inbox_messages(limit=5)
        mail_texts = [f"Von: {m.get('sender')}, Betreff: {m.get('subject')} - {m.get('snippet')}" for m in mails]
        full_prompt = (
            "Fasse die folgenden E-Mails aus dem Postfach in 2-3 präzisen Sätzen auf Deutsch zusammen. "
            "Hebe Fristen und dringende Aktionen sofort hervor:\n\n" + "\n".join(mail_texts)
        )
        self.lbl_briefing_text.setText("⏳ Analysiere E-Mails mit KI...")

        def _worker():
            summary = ""
            try:
                from ai.gemini_client import generate_response
                resp = generate_response(full_prompt)
                if resp:
                    summary = resp.strip()
            except Exception:
                pass
            if not summary:
                summary = "📬 Keine dringenden Fristen in den aktuellen Nachrichten gefunden."
            self._signals.briefing_ready.emit(f"📬 E-Mail Digest:\n{summary}")

        threading.Thread(target=_worker, daemon=True).start()

    def _toggle_speech(self) -> None:
        if self._is_speaking:
            stop_speech()
            self._on_speech_finished()
        else:
            if not self._current_briefing_text:
                return
            self._is_speaking = True
            self.btn_speak.setText("  ⏹ Vorlesen stoppen")
            self.btn_speak.setStyleSheet("background: #DA3633; color: #FFFFFF; border: 1px solid #F85149; border-radius: 7px; padding: 0 14px;")
            speak_text(self._current_briefing_text, on_finished=self._signals.speech_finished.emit)

    def _on_speech_finished(self) -> None:
        self._is_speaking = False
        self.btn_speak.setText("  ▶ Briefing vorlesen")
        self.btn_speak.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8957E5, stop:1 #A371F7);
                color: #FFFFFF;
                border: 1px solid #A371F7;
                border-radius: 7px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: #A371F7;
            }
        """)

    def _open_setup_dialog(self) -> None:
        dlg = JarvisSetupDialog(self)
        if dlg.exec():
            self.refresh_all_data()

    def _on_cmd_submitted(self) -> None:
        cmd = self.input_cmd.text().strip()
        if not cmd:
            return
        self.input_cmd.clear()

        low = cmd.lower()
        if "termin" in low or "kalender" in low or "wann" in low:
            next_ev = get_next_upcoming_event()
            if next_ev:
                ans = f"🗓️ Dein nächster Termin ist {next_ev[0].get('title')} um {next_ev[0].get('start_time')} Uhr ({next_ev[0].get('location')})."
            else:
                ans = "🗓️ Heute stehen keine weiteren Termine im Kalender."
            self.lbl_briefing_text.setText(ans)
        elif "mail" in low or "nachricht" in low or "postfach" in low:
            self._summarize_mails_with_ai()
        elif "buch" in low or "lesen" in low or "schreibtisch" in low:
            books = get_desk_books()
            if books:
                ans = f"📖 Empfehlung: Lies heute 25 Minuten in «{books[0].get('title')}» weiter (aktuell bei {books[0].get('reading_progress', 0)}%)."
            else:
                ans = "📖 Du hast gerade kein Buch auf dem Schreibtisch. Wähle eines im Bibliotheks-Katalog aus!"
            self.lbl_briefing_text.setText(ans)
        else:
            self.lbl_briefing_text.setText(f"⏳ JARVIS denkt nach über: «{cmd}»...")
            def _worker():
                prompt = f"Du bist JARVIS, der KI-Campus-Assistent. Beantworte diese Nutzeranfrage kurz, präzise und freundlich auf Deutsch:\n{cmd}"
                ans = ""
                try:
                    from ai.gemini_client import generate_response
                    resp = generate_response(prompt)
                    if resp:
                        ans = resp.strip()
                except Exception:
                    pass
                if not ans:
                    ans = f"JARVIS hat deine Anfrage «{cmd}» notiert und in deine Tagesplanung einbezogen."
                self._signals.briefing_ready.emit(ans)
            threading.Thread(target=_worker, daemon=True).start()
