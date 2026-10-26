import math
import time
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, Property, QPointF
from PySide6.QtGui import (
    QFont,
    QColor,
    QPainter,
    QLinearGradient,
    QRadialGradient,
    QConicalGradient,
    QPen,
    QBrush,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGraphicsDropShadowEffect,
    QFrame,
    QApplication,
)
from ui.qt.icons import create_vector_pixmap


class SmoothLinearProgressBar(QWidget):
    """Futuristic, Ultra-Smooth Neon Progress Bar with Glowing Head & Shimmer."""

    def __init__(self, height: int = 8, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._target_value: float = 0.0
        self._display_value: float = 0.0
        self._shimmer_offset: float = 0.0

        # Animation timer for ultra-smooth 60fps interpolation
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60 fps
        self._anim_timer.timeout.connect(self._on_tick)
        self._anim_timer.start()

    def set_target_value(self, value: float) -> None:
        self._target_value = max(0.0, min(100.0, float(value)))

    def _on_tick(self) -> None:
        # Smooth asymptotic approach towards target (lerp)
        diff = self._target_value - self._display_value
        if abs(diff) > 0.15:
            self._display_value += diff * 0.18
        else:
            self._display_value = self._target_value

        self._shimmer_offset += 0.02
        if self._shimmer_offset > 2.0:
            self._shimmer_offset = -1.0

        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        r = h / 2.0

        # 1. Background Groove
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        painter.fillPath(bg_path, QColor(15, 23, 42, 220))

        bg_border = QPen(QColor(37, 51, 78, 140), 1.0)
        painter.setPen(bg_border)
        painter.drawPath(bg_path)

        # 2. Active Progress Fill
        fill_pct = max(0.0, min(1.0, self._display_value / 100.0))
        fill_w = w * fill_pct

        if fill_w > 1.0:
            fill_path = QPainterPath()
            fill_path.addRoundedRect(QRectF(0, 0, fill_w, h), r, r)

            # Gradient from deep cyan-blue to glowing bright azure
            grad = QLinearGradient(0, 0, max(fill_w, 1.0), 0)
            grad.setColorAt(0.0, QColor("#1D4ED8"))  # Deep Blue
            grad.setColorAt(0.5, QColor("#388BFD"))  # Electric Blue
            grad.setColorAt(1.0, QColor("#79C0FF"))  # Bright Cyan

            painter.fillPath(fill_path, grad)

            # 3. Glowing Leading Tip (Head)
            if fill_w > r:
                glow_grad = QRadialGradient(QPointF(fill_w - r, r), r * 1.5)
                glow_grad.setColorAt(0.0, QColor(255, 255, 255, 220))
                glow_grad.setColorAt(0.6, QColor(88, 166, 255, 180))
                glow_grad.setColorAt(1.0, QColor(56, 139, 253, 0))
                painter.setPen(Qt.NoPen)
                painter.setBrush(glow_grad)
                painter.drawEllipse(QRectF(fill_w - r * 2.0, 0, r * 2.0, h))


class CircularProgressRing(QWidget):
    """Custom High-Tech Circular Progress Ring with Gradient Arc & Glowing Track."""

    def __init__(self, size: int = 56, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._target_progress: float = 0.0
        self._display_progress: float = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_tick)
        self._anim_timer.start()

    def set_value(self, value: float) -> None:
        self._target_progress = max(0.0, min(100.0, float(value)))

    def _on_tick(self) -> None:
        diff = self._target_progress - self._display_progress
        if abs(diff) > 0.15:
            self._display_progress += diff * 0.18
        else:
            self._display_progress = self._target_progress
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        width = self.width()
        height = self.height()
        stroke_width = 4.5
        padding = stroke_width / 2.0 + 2.0
        rect = QRectF(padding, padding, width - padding * 2.0, height - padding * 2.0)

        # 1. Background Track Ring (Dark Blue / Slate)
        bg_pen = QPen(QColor(30, 41, 59, 180), stroke_width)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

        # 2. Glowing Progress Arc (Neon Cyan-Blue Conical Gradient)
        if self._display_progress > 0.5:
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

            span_angle = -int((self._display_progress / 100.0) * 360 * 16)
            painter.drawArc(rect, 90 * 16, span_angle)

        # 3. Inner Center Text (Current percentage)
        painter.setPen(QColor("#F0F6FC"))
        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, f"{int(round(self._display_progress))}%")


class ModernSplashCard(QFrame):
    """Deep Cyber-Glass Card with subtle border glow and linear gradient background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0B1120, 
                    stop:0.4 #0F172A, 
                    stop:0.8 #0D1527, 
                    stop:1 #080D1A);
                border: 1px solid #1E293B;
                border-top: 1px solid #388BFD;
                border-radius: 16px;
            }
        """)


class CampusSplashScreen(QWidget):
    """Non-blocking, Luxury Dark Splash Screen with dynamic fluid loader."""

    def __init__(self):
        super().__init__()
        # Normal top-level splash without WindowStaysOnTopHint so it doesn't hijack other applications
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(540, 316)

        # Root layout with padding for the ambient drop shadow
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
        card_layout.setContentsMargins(32, 24, 32, 24)
        card_layout.setSpacing(0)

        # -------------------------------------------------------------
        # TOP ROW: System Status Pill & Version
        # -------------------------------------------------------------
        top_h = QHBoxLayout()
        top_h.setContentsMargins(0, 0, 0, 12)

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
        sp_lay.setContentsMargins(6, 2, 8, 2)
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
        brand_h.setSpacing(16)
        brand_h.setContentsMargins(0, 4, 0, 14)

        # Hexagon/Square Icon Emblem with Gradient Border
        icon_box = QFrame()
        icon_box.setFixedSize(54, 54)
        icon_box.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1E293B, stop:1 #0F172A);
                border: 1.5px solid #388BFD;
                border-radius: 12px;
            }
        """)
        ib_lay = QVBoxLayout(icon_box)
        ib_lay.setContentsMargins(0, 0, 0, 0)
        ib_lay.setAlignment(Qt.AlignCenter)

        lbl_logo = QLabel()
        lbl_logo.setAlignment(Qt.AlignCenter)
        lbl_logo.setPixmap(create_vector_pixmap("book", "#58A6FF", 30))
        lbl_logo.setStyleSheet("border: none; background: transparent;")
        ib_lay.addWidget(lbl_logo)
        brand_h.addWidget(icon_box)

        # Typography stack
        text_v = QVBoxLayout()
        text_v.setContentsMargins(0, 0, 0, 0)
        text_v.setSpacing(2)

        lbl_title = QLabel("Campus-Bibliothek AI")
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
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
        # LOADER & STATUS SECTION
        # -------------------------------------------------------------
        loader_box = QFrame()
        loader_box.setStyleSheet("""
            QFrame {
                background-color: rgba(15, 23, 42, 0.7);
                border: 1px solid #1E293B;
                border-radius: 12px;
            }
        """)
        loader_v = QVBoxLayout(loader_box)
        loader_v.setContentsMargins(16, 12, 16, 12)
        loader_v.setSpacing(10)

        # Top line in box: Status text + percentage ring
        box_top_h = QHBoxLayout()
        box_top_h.setContentsMargins(0, 0, 0, 0)
        box_top_h.setSpacing(12)

        # Circular Progress Ring
        self.ring = CircularProgressRing(size=46)
        box_top_h.addWidget(self.ring)

        # Status text column
        status_v = QVBoxLayout()
        status_v.setContentsMargins(0, 0, 0, 0)
        status_v.setSpacing(2)

        lbl_prep = QLabel("SYSTEM-START & SYNCHRONISATION")
        lbl_prep.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_prep.setStyleSheet("color: #64748B; border: none; background: transparent; letter-spacing: 0.8px;")
        status_v.addWidget(lbl_prep)

        self.lbl_status = QLabel("Initialisiere Kernmodule...")
        self.lbl_status.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self.lbl_status.setStyleSheet("color: #58A6FF; border: none; background: transparent;")
        status_v.addWidget(self.lbl_status)

        box_top_h.addLayout(status_v)
        box_top_h.addStretch()
        loader_v.addLayout(box_top_h)

        # High-tech linear progress bar
        self.progress_bar = SmoothLinearProgressBar(height=6)
        loader_v.addWidget(self.progress_bar)

        card_layout.addWidget(loader_box)
        root_layout.addWidget(self.card)

    def set_progress(self, percent: int, status_text: str = "") -> None:
        """Updates both circular and linear progress indicators smoothly."""
        val = max(0, min(100, percent))
        self.ring.set_value(val)
        self.progress_bar.set_target_value(val)
        if status_text:
            self.lbl_status.setText(status_text)
        QApplication.processEvents()

    def step_smooth(self, target_percent: int, status_text: str = "", duration_ms: int = 150) -> None:
        """Pumps events smoothly to render fluid animation during blocking startup steps."""
        self.set_progress(target_percent, status_text)
        steps = max(1, duration_ms // 16)
        for _ in range(steps):
            time.sleep(0.016)
            QApplication.processEvents()

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()
