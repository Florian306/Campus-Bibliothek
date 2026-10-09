"""Vector Icon generator for PySide6 using QPainter.
Generates razor-sharp, modern geometric icons with anti-aliasing, avoiding broken Windows emoji squares.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QPainterPath


def create_vector_pixmap(icon_name: str, color_hex: str = "#58A6FF", size: int = 24) -> QPixmap:
    """Renders a modern flat vector icon to QPixmap."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    col = QColor(color_hex)
    pen = QPen(col)
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    s = float(size)

    if icon_name == "library":
        # Pediment (roof)
        path = QPainterPath()
        path.moveTo(s * 0.15, s * 0.35)
        path.lineTo(s * 0.50, s * 0.15)
        path.lineTo(s * 0.85, s * 0.35)
        path.closeSubpath()
        painter.fillPath(path, QBrush(col))

        # Base
        painter.fillRect(QRectF(s * 0.12, s * 0.80, s * 0.76, s * 0.08), col)

        # 3 Columns
        painter.fillRect(QRectF(s * 0.22, s * 0.40, s * 0.09, s * 0.38), col)
        painter.fillRect(QRectF(s * 0.455, s * 0.40, s * 0.09, s * 0.38), col)
        painter.fillRect(QRectF(s * 0.69, s * 0.40, s * 0.09, s * 0.38), col)

    elif icon_name in ("desk", "book"):
        # Open book
        p1 = QPainterPath()
        p1.moveTo(s * 0.5, s * 0.28)
        p1.cubicTo(s * 0.35, s * 0.20, s * 0.2, s * 0.23, s * 0.14, s * 0.28)
        p1.lineTo(s * 0.14, s * 0.75)
        p1.cubicTo(s * 0.2, s * 0.70, s * 0.35, s * 0.67, s * 0.5, s * 0.75)
        p1.closeSubpath()
        painter.drawPath(p1)

        p2 = QPainterPath()
        p2.moveTo(s * 0.5, s * 0.28)
        p2.cubicTo(s * 0.65, s * 0.20, s * 0.8, s * 0.23, s * 0.86, s * 0.28)
        p2.lineTo(s * 0.86, s * 0.75)
        p2.cubicTo(s * 0.8, s * 0.70, s * 0.65, s * 0.67, s * 0.5, s * 0.75)
        p2.closeSubpath()
        painter.drawPath(p2)

        painter.drawLine(QPointF(s * 0.5, s * 0.28), QPointF(s * 0.5, s * 0.75))

    elif icon_name == "radar":
        # Concentric radar arches & beacon
        painter.drawArc(QRectF(s * 0.15, s * 0.15, s * 0.7, s * 0.7), 45 * 16, 90 * 16)
        painter.drawArc(QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44), 45 * 16, 90 * 16)
        painter.setBrush(QBrush(col))
        painter.drawEllipse(QRectF(s * 0.42, s * 0.60, s * 0.16, s * 0.16))

    elif icon_name == "sync":
        # Lightning / Zap
        path = QPainterPath()
        path.moveTo(s * 0.55, s * 0.15)
        path.lineTo(s * 0.28, s * 0.52)
        path.lineTo(s * 0.50, s * 0.52)
        path.lineTo(s * 0.45, s * 0.85)
        path.lineTo(s * 0.72, s * 0.48)
        path.lineTo(s * 0.50, s * 0.48)
        path.closeSubpath()
        painter.setBrush(QBrush(col))
        painter.drawPath(path)

    elif icon_name == "search":
        painter.drawEllipse(QRectF(s * 0.2, s * 0.2, s * 0.45, s * 0.45))
        painter.drawLine(QPointF(s * 0.55, s * 0.55), QPointF(s * 0.82, s * 0.82))

    elif icon_name == "notes":
        painter.drawRoundedRect(QRectF(s * 0.2, s * 0.15, s * 0.6, s * 0.7), 2, 2)
        painter.drawLine(QPointF(s * 0.32, s * 0.35), QPointF(s * 0.68, s * 0.35))
        painter.drawLine(QPointF(s * 0.32, s * 0.50), QPointF(s * 0.68, s * 0.50))
        painter.drawLine(QPointF(s * 0.32, s * 0.65), QPointF(s * 0.55, s * 0.65))

    elif icon_name == "clock":
        painter.drawEllipse(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64))
        painter.drawLine(QPointF(s * 0.5, s * 0.32), QPointF(s * 0.5, s * 0.5))
        painter.drawLine(QPointF(s * 0.5, s * 0.5), QPointF(s * 0.66, s * 0.5))

    elif icon_name == "bookmark":
        path = QPainterPath()
        path.moveTo(s * 0.26, s * 0.16)
        path.lineTo(s * 0.74, s * 0.16)
        path.lineTo(s * 0.74, s * 0.84)
        path.lineTo(s * 0.50, s * 0.66)
        path.lineTo(s * 0.26, s * 0.84)
        path.closeSubpath()
        painter.drawPath(path)

    elif icon_name == "copy":
        # Back sheet
        painter.drawRoundedRect(QRectF(s * 0.32, s * 0.15, s * 0.50, s * 0.60), 2, 2)
        # Front sheet
        painter.setBrush(QBrush(QColor(18, 24, 38, 230)))
        painter.drawRoundedRect(QRectF(s * 0.18, s * 0.28, s * 0.50, s * 0.60), 2, 2)

    elif icon_name == "trash":
        # Lid
        painter.drawLine(QPointF(s * 0.20, s * 0.28), QPointF(s * 0.80, s * 0.28))
        painter.drawLine(QPointF(s * 0.40, s * 0.20), QPointF(s * 0.60, s * 0.20))
        # Body
        path = QPainterPath()
        path.moveTo(s * 0.28, s * 0.34)
        path.lineTo(s * 0.32, s * 0.82)
        path.lineTo(s * 0.68, s * 0.82)
        path.lineTo(s * 0.72, s * 0.34)
        painter.drawPath(path)
        # Ribs
        painter.drawLine(QPointF(s * 0.44, s * 0.42), QPointF(s * 0.44, s * 0.72))
        painter.drawLine(QPointF(s * 0.56, s * 0.42), QPointF(s * 0.56, s * 0.72))

    elif icon_name == "plus":
        painter.drawLine(QPointF(s * 0.50, s * 0.24), QPointF(s * 0.50, s * 0.76))
        painter.drawLine(QPointF(s * 0.24, s * 0.50), QPointF(s * 0.76, s * 0.50))

    elif icon_name == "export":
        # Box with arrow pointing out top-right
        painter.drawPolyline([
            QPointF(s * 0.45, s * 0.25),
            QPointF(s * 0.20, s * 0.25),
            QPointF(s * 0.20, s * 0.80),
            QPointF(s * 0.75, s * 0.80),
            QPointF(s * 0.75, s * 0.55),
        ])
        painter.drawLine(QPointF(s * 0.45, s * 0.55), QPointF(s * 0.80, s * 0.20))
        painter.drawLine(QPointF(s * 0.58, s * 0.20), QPointF(s * 0.80, s * 0.20))
        painter.drawLine(QPointF(s * 0.80, s * 0.20), QPointF(s * 0.80, s * 0.42))

    elif icon_name == "research":
        # Atom / Science Orbitals
        painter.drawEllipse(QRectF(s * 0.40, s * 0.40, s * 0.20, s * 0.20))
        painter.drawEllipse(QPointF(s * 0.50, s * 0.50), s * 0.38, s * 0.16)
        # Tilted ellipse
        painter.save()
        painter.translate(s * 0.50, s * 0.50)
        painter.rotate(60)
        painter.drawEllipse(QPointF(0, 0), s * 0.38, s * 0.16)
        painter.restore()

    elif icon_name == "institution":
        # Academic columns and pediment
        path = QPainterPath()
        path.moveTo(s * 0.16, s * 0.34)
        path.lineTo(s * 0.50, s * 0.16)
        path.lineTo(s * 0.84, s * 0.34)
        path.closeSubpath()
        painter.fillPath(path, QBrush(col))
        painter.fillRect(QRectF(s * 0.14, s * 0.80, s * 0.72, s * 0.08), col)
        painter.fillRect(QRectF(s * 0.22, s * 0.38, s * 0.08, s * 0.38), col)
        painter.fillRect(QRectF(s * 0.46, s * 0.38, s * 0.08, s * 0.38), col)
        painter.fillRect(QRectF(s * 0.70, s * 0.38, s * 0.08, s * 0.38), col)

    elif icon_name == "download":
        # Downward arrow into tray
        painter.drawLine(QPointF(s * 0.50, s * 0.18), QPointF(s * 0.50, s * 0.62))
        painter.drawLine(QPointF(s * 0.32, s * 0.46), QPointF(s * 0.50, s * 0.64))
        painter.drawLine(QPointF(s * 0.68, s * 0.46), QPointF(s * 0.50, s * 0.64))
        painter.drawPolyline([
            QPointF(s * 0.20, s * 0.60),
            QPointF(s * 0.20, s * 0.80),
            QPointF(s * 0.80, s * 0.80),
            QPointF(s * 0.80, s * 0.60),
        ])

    elif icon_name == "external":
        painter.drawPolyline([
            QPointF(s * 0.45, s * 0.25),
            QPointF(s * 0.20, s * 0.25),
            QPointF(s * 0.20, s * 0.80),
            QPointF(s * 0.75, s * 0.80),
            QPointF(s * 0.75, s * 0.55),
        ])
        painter.drawLine(QPointF(s * 0.45, s * 0.55), QPointF(s * 0.80, s * 0.20))
        painter.drawLine(QPointF(s * 0.58, s * 0.20), QPointF(s * 0.80, s * 0.20))
        painter.drawLine(QPointF(s * 0.80, s * 0.20), QPointF(s * 0.80, s * 0.42))

    elif icon_name == "bulb":
        # Lightbulb head
        painter.drawArc(QRectF(s * 0.26, s * 0.16, s * 0.48, s * 0.48), 300 * 16, 300 * 16)
        painter.drawLine(QPointF(s * 0.36, s * 0.72), QPointF(s * 0.64, s * 0.72))
        painter.drawLine(QPointF(s * 0.42, s * 0.82), QPointF(s * 0.58, s * 0.82))

    elif icon_name in ("globe", "web", "internet"):
        # Outer circle
        painter.drawEllipse(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68))
        # Equator
        painter.drawLine(QPointF(s * 0.16, s * 0.50), QPointF(s * 0.84, s * 0.50))
        # Prime meridian ellipse
        painter.drawEllipse(QRectF(s * 0.33, s * 0.16, s * 0.34, s * 0.68))

    elif icon_name == "check":
        path = QPainterPath()
        path.moveTo(s * 0.2, s * 0.5)
        path.lineTo(s * 0.42, s * 0.72)
        path.lineTo(s * 0.82, s * 0.28)
        painter.drawPath(path)

    elif icon_name == "chevron_left":
        pen_thick = QPen(col)
        pen_thick.setWidthF(2.4)
        pen_thick.setCapStyle(Qt.RoundCap)
        pen_thick.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen_thick)
        path = QPainterPath()
        path.moveTo(s * 0.62, s * 0.26)
        path.lineTo(s * 0.36, s * 0.50)
        path.lineTo(s * 0.62, s * 0.74)
        painter.drawPath(path)

    elif icon_name == "chevron_right":
        pen_thick = QPen(col)
        pen_thick.setWidthF(2.4)
        pen_thick.setCapStyle(Qt.RoundCap)
        pen_thick.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen_thick)
        path = QPainterPath()
        path.moveTo(s * 0.38, s * 0.26)
        path.lineTo(s * 0.64, s * 0.50)
        path.lineTo(s * 0.38, s * 0.74)
        painter.drawPath(path)

    elif icon_name in ("exam", "quiz", "graduation"):
        # Graduation Cap (Mortarboard)
        # Rhombus cap top
        path = QPainterPath()
        path.moveTo(s * 0.50, s * 0.18)
        path.lineTo(s * 0.88, s * 0.35)
        path.lineTo(s * 0.50, s * 0.52)
        path.lineTo(s * 0.12, s * 0.35)
        path.closeSubpath()
        painter.fillPath(path, QBrush(col))

        # Skull cap underneath
        cap_path = QPainterPath()
        cap_path.moveTo(s * 0.28, s * 0.43)
        cap_path.lineTo(s * 0.28, s * 0.65)
        cap_path.cubicTo(s * 0.35, s * 0.78, s * 0.65, s * 0.78, s * 0.72, s * 0.65)
        cap_path.lineTo(s * 0.72, s * 0.43)
        painter.drawPath(cap_path)

        # Tassel hanging on the right
        painter.drawLine(QPointF(s * 0.82, s * 0.38), QPointF(s * 0.82, s * 0.68))
        painter.drawEllipse(QRectF(s * 0.79, s * 0.68, s * 0.07, s * 0.07))

    elif icon_name == "trophy":
        # Cup body
        cup = QPainterPath()
        cup.moveTo(s * 0.25, s * 0.22)
        cup.lineTo(s * 0.75, s * 0.22)
        cup.lineTo(s * 0.70, s * 0.52)
        cup.cubicTo(s * 0.65, s * 0.68, s * 0.35, s * 0.68, s * 0.30, s * 0.52)
        cup.closeSubpath()
        painter.drawPath(cup)
        # Stem and base
        painter.drawLine(QPointF(s * 0.50, s * 0.64), QPointF(s * 0.50, s * 0.80))
        painter.fillRect(QRectF(s * 0.30, s * 0.80, s * 0.40, s * 0.08), col)
        # Handles
        painter.drawArc(QRectF(s * 0.14, s * 0.26, s * 0.24, s * 0.26), 90 * 16, 180 * 16)
        painter.drawArc(QRectF(s * 0.62, s * 0.26, s * 0.24, s * 0.26), 270 * 16, 180 * 16)

    elif icon_name == "history":
        painter.drawArc(QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.60), 45 * 16, 270 * 16)
        painter.drawLine(QPointF(s * 0.50, s * 0.32), QPointF(s * 0.50, s * 0.50))
        painter.drawLine(QPointF(s * 0.50, s * 0.50), QPointF(s * 0.65, s * 0.50))
        # Arrowhead on arc
        painter.drawLine(QPointF(s * 0.62, s * 0.18), QPointF(s * 0.76, s * 0.25))
        painter.drawLine(QPointF(s * 0.76, s * 0.25), QPointF(s * 0.74, s * 0.40))

    elif icon_name in ("jarvis", "ai_core", "bot", "assistant"):
        # Arc Reactor / Futuristic Hex-Core
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(s * 0.15, s * 0.15, s * 0.70, s * 0.70))
        painter.drawEllipse(QRectF(s * 0.32, s * 0.32, s * 0.36, s * 0.36))
        painter.setBrush(QBrush(col))
        painter.drawEllipse(QRectF(s * 0.42, s * 0.42, s * 0.16, s * 0.16))
        # 4 Quantum node rays
        painter.drawLine(QPointF(s * 0.50, s * 0.15), QPointF(s * 0.50, s * 0.32))
        painter.drawLine(QPointF(s * 0.50, s * 0.68), QPointF(s * 0.50, s * 0.85))
        painter.drawLine(QPointF(s * 0.15, s * 0.50), QPointF(s * 0.32, s * 0.50))
        painter.drawLine(QPointF(s * 0.68, s * 0.50), QPointF(s * 0.85, s * 0.50))

    elif icon_name in ("mail", "inbox"):
        # Envelope with flap
        painter.drawRoundedRect(QRectF(s * 0.16, s * 0.26, s * 0.68, s * 0.50), 2, 2)
        path = QPainterPath()
        path.moveTo(s * 0.16, s * 0.28)
        path.lineTo(s * 0.50, s * 0.54)
        path.lineTo(s * 0.84, s * 0.28)
        painter.drawPath(path)

    elif icon_name in ("calendar", "schedule"):
        # Calendar binder
        painter.drawRoundedRect(QRectF(s * 0.18, s * 0.24, s * 0.64, s * 0.58), 2, 2)
        painter.drawLine(QPointF(s * 0.18, s * 0.40), QPointF(s * 0.82, s * 0.40))
        # Binder rings
        painter.drawLine(QPointF(s * 0.34, s * 0.16), QPointF(s * 0.34, s * 0.28))
        painter.drawLine(QPointF(s * 0.66, s * 0.16), QPointF(s * 0.66, s * 0.28))
        # Day dot
        painter.setBrush(QBrush(col))
        painter.drawEllipse(QRectF(s * 0.44, s * 0.52, s * 0.12, s * 0.12))

    elif icon_name in ("news", "newspaper"):
        # Newspaper fold
        painter.drawRoundedRect(QRectF(s * 0.18, s * 0.20, s * 0.64, s * 0.62), 2, 2)
        # Headline image block
        painter.fillRect(QRectF(s * 0.26, s * 0.28, s * 0.20, s * 0.18), col)
        # Text lines
        painter.drawLine(QPointF(s * 0.52, s * 0.30), QPointF(s * 0.74, s * 0.30))
        painter.drawLine(QPointF(s * 0.52, s * 0.40), QPointF(s * 0.74, s * 0.40))
        painter.drawLine(QPointF(s * 0.26, s * 0.56), QPointF(s * 0.74, s * 0.56))
        painter.drawLine(QPointF(s * 0.26, s * 0.68), QPointF(s * 0.64, s * 0.68))

    else:
        # Default dot
        painter.setBrush(QBrush(col))
        painter.drawEllipse(QRectF(s * 0.35, s * 0.35, s * 0.3, s * 0.3))

    painter.end()
    return pixmap


def create_vector_icon(icon_name: str, color_hex: str = "#58A6FF", size: int = 24) -> QIcon:
    """Renders a modern flat vector icon to QIcon."""
    return QIcon(create_vector_pixmap(icon_name, color_hex, size))
