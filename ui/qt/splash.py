import math
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QFont, QColor, QPainter, QLinearGradient, QRadialGradient, QConicalGradient, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QGraphicsDropShadowEffect,
    QFrame,
)
from ui.qt.icons import create_vector_pixmap


class CircularProgressRing(QWidget):
    """Custom High-Tech Circular Progress Ring with Gradient Arc & Glowing Track."""

    def __init__(self, size: int = 68, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._progress = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_value(self, value: int):
        self._progress = max(0, min(100, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        width = self.width()
        height = self.height()
        stroke_width = 5.0
        padding = stroke_width / 2.0 + 2.0
        rect = QRectF(padding, padding, width - padding * 2.0, height - padding * 2.0)

        # 1. Background Track Ring (Dark Blue / Slate)
        bg_pen = QPen(QColor(30, 41, 59, 180), stroke_width)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

        # 2. Glowing Progress Arc (Neon Cyan-Blue Conical Gradient)
        if self._progress > 0:
            arc_pen = QPen()
            arc_pen.setWidthF(stroke_width)
            arc_pen.setCapStyle(Qt.RoundCap)

            gradient = QConicalGradient(rect.center(), 90)
            gradient.setColorAt(0.0, QColor("#58A6FF"))
            gradient.setColorAt(0.4, QColor("#388BFD"))
            gradient.setColorAt(0.8, QColor("#1F6FEB"))
            gradient.setColorAt(1.0, QColor("#58A6FF"))

            arc_pen.setBrush(QBrush(gradient))
            painter.setPen(arc_pen)

            # Arc starts at 12 o'clock (90 * 16) and runs clockwise (-deg * 16)
            span_angle = -int((self._progress / 100.0) * 360 * 16)
            painter.drawArc(rect, 90 * 16, span_angle)

        # 3. Inner Center Text (Current percentage)
        painter.setPen(QColor("#F0F6FC"))
        font = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, f"{self._progress}%")


class ModernSplashCard(QFrame):
    """Deep Cyber-Glass Card with subtle border glow and linear gradient background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0F172A, 
                    stop:0.4 #131E36, 
                    stop:0.8 #0D1527, 
                    stop:1 #0A0F1D);
                border: 1px solid #293B61;
                border-top: 1px solid #4F82E8;
                border-radius: 16px;
            }
        """)


class CampusSplashScreen(QWidget):
    """State-of-the-Art Luxury Dark Splash Screen with Circular Ring Indicator."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(540, 310)

        # Root layout with padding for the drop shadow
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)

        # Futuristic Glass Card
        self.card = ModernSplashCard()
        
        # Deep Ambient Drop Shadow Effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 10)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(36, 26, 36, 26)
        card_layout.setSpacing(0)

        # -------------------------------------------------------------
        # TOP ROW: System Status Pill & Version
        # -------------------------------------------------------------
        top_h = QHBoxLayout()
        top_h.setContentsMargins(0, 0, 0, 14)
        
        # Live Pulse Dot & Pill
        status_pill = QFrame()
        status_pill.setStyleSheet("""
            QFrame {
                background-color: rgba(31, 111, 235, 0.15);
                border: 1px solid rgba(56, 139, 253, 0.4);
                border-radius: 10px;
                padding: 2px 10px;
            }
        """)
        sp_lay = QHBoxLayout(status_pill)
        sp_lay.setContentsMargins(4, 2, 8, 2)
        sp_lay.setSpacing(6)

        dot = QLabel("●")
        dot.setStyleSheet("color: #388BFD; font-size: 9px; border: none; background: transparent;")
        sp_lay.addWidget(dot)

        lbl_engine = QLabel("QUANTUM ENGINE 2.0")
        lbl_engine.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_engine.setStyleSheet("color: #79C0FF; border: none; background: transparent; letter-spacing: 1px;")
        sp_lay.addWidget(lbl_engine)
        top_h.addWidget(status_pill)

        top_h.addStretch()

        lbl_ver = QLabel("v2.4.0 · BUILD 2026")
        lbl_ver.setFont(QFont("Segoe UI", 8, QFont.Medium))
        lbl_ver.setStyleSheet("color: #6E7681; border: none; background: transparent;")
        top_h.addWidget(lbl_ver)
        card_layout.addLayout(top_h)

        # -------------------------------------------------------------
        # BRANDING: Glowing Icon & Title Typography
        # -------------------------------------------------------------
        brand_h = QHBoxLayout()
        brand_h.setSpacing(18)
        brand_h.setContentsMargins(0, 4, 0, 16)

        # Hexagon/Square Icon Emblem with Gradient Border
        icon_box = QFrame()
        icon_box.setFixedSize(58, 58)
        icon_box.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1E293B, stop:1 #0F172A);
                border: 1.5px solid #388BFD;
                border-radius: 14px;
            }
        """)
        ib_lay = QVBoxLayout(icon_box)
        ib_lay.setContentsMargins(0, 0, 0, 0)
        ib_lay.setAlignment(Qt.AlignCenter)

        lbl_logo = QLabel()
        lbl_logo.setAlignment(Qt.AlignCenter)
        lbl_logo.setPixmap(create_vector_pixmap("book", "#58A6FF", 32))
        lbl_logo.setStyleSheet("border: none; background: transparent;")
        ib_lay.addWidget(lbl_logo)
        brand_h.addWidget(icon_box)

        # Typography stack
        text_v = QVBoxLayout()
        text_v.setContentsMargins(0, 0, 0, 0)
        text_v.setSpacing(3)

        lbl_title = QLabel("Campus-Bibliothek AI")
        lbl_title.setFont(QFont("Segoe UI", 17, QFont.Bold))
        lbl_title.setStyleSheet("color: #F8FAFC; border: none; background: transparent; letter-spacing: 0.3px;")
        text_v.addWidget(lbl_title)

        lbl_sub = QLabel("Wissenschaftlicher Fachbuch-Workspace & Forschungs-Lake")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet("color: #94A3B8; border: none; background: transparent;")
        text_v.addWidget(lbl_sub)
        
        brand_h.addLayout(text_v)
        brand_h.addStretch()
        card_layout.addLayout(brand_h)

        card_layout.addStretch()

        # -------------------------------------------------------------
        # CIRCULAR LOADER & STATUS SECTION
        # -------------------------------------------------------------
        loader_box = QFrame()
        loader_box.setStyleSheet("""
            QFrame {
                background-color: rgba(15, 23, 42, 0.6);
                border: 1px solid #1E293B;
                border-radius: 12px;
            }
        """)
        loader_h = QHBoxLayout(loader_box)
        loader_h.setContentsMargins(16, 10, 18, 10)
        loader_h.setSpacing(16)

        # Circular Progress Ring with live percentage inside
        self.ring = CircularProgressRing(size=56)
        loader_h.addWidget(self.ring)

        # Status text column
        status_v = QVBoxLayout()
        status_v.setContentsMargins(0, 0, 0, 0)
        status_v.setSpacing(3)

        lbl_prep = QLabel("SYSTEM-START & SYNCHRONISATION")
        lbl_prep.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_prep.setStyleSheet("color: #64748B; border: none; background: transparent; letter-spacing: 0.8px;")
        status_v.addWidget(lbl_prep)

        self.lbl_status = QLabel("Initialisiere Kernmodule...")
        self.lbl_status.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        self.lbl_status.setStyleSheet("color: #388BFD; border: none; background: transparent;")
        status_v.addWidget(self.lbl_status)

        loader_h.addLayout(status_v)
        loader_h.addStretch()

        card_layout.addWidget(loader_box)

        root_layout.addWidget(self.card)

    def set_progress(self, percent: int, status_text: str = "") -> None:
        """Updates circular progress ring and status message smoothly."""
        val = max(0, min(100, percent))
        self.ring.set_value(val)
        if status_text:
            self.lbl_status.setText(status_text)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()


