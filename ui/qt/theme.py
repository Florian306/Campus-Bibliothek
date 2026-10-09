"""High-End Cyber-Obsidian & Indigo Theme for Campus Library AI (PySide6).
Delivers rich depth, gradient highlights, polished controls, and smooth hover states.
"""

from PySide6.QtWidgets import QProxyStyle, QStyle, QStyledItemDelegate, QStyleOptionViewItem

class NoFocusProxyStyle(QProxyStyle):
    """Suppresses the native Windows white/dotted focus outline rectangle across all controls."""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


class NoFocusItemDelegate(QStyledItemDelegate):
    """Suppresses cell focus rectangles in QTableWidget and item views."""
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        if opt.state & QStyle.State_HasFocus:
            opt.state &= ~QStyle.State_HasFocus
        super().paint(painter, opt, index)

# Color Palette Tokens
COLOR_BG = "#0B0F19"
COLOR_BG_ALT = "#080C14"
COLOR_SIDEBAR = "#0F1422"
COLOR_CARD = "#141C2E"
COLOR_CARD_HOVER = "#1B253D"
COLOR_CARD_SELECTED = "#20304E"
COLOR_BORDER = "#232F48"
COLOR_BORDER_LIGHT = "#324468"
COLOR_PRIMARY = "#58A6FF"
COLOR_PRIMARY_HOVER = "#79B8FF"
COLOR_ACCENT = "#238636"
COLOR_ACCENT_HOVER = "#2EA043"
COLOR_PURPLE = "#A371F7"
COLOR_CYAN = "#39C5BB"
COLOR_WARNING = "#E3B341"
COLOR_DANGER = "#F85149"
COLOR_TEXT_MAIN = "#F0F6FC"
COLOR_TEXT_MUTED = "#8B949E"

# Modern QSS with Deep Dark Palette & Gradients
DARK_STYLESHEET = """
QMainWindow {
    background-color: #0B0F19;
}

QWidget {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    color: #F0F6FC;
    font-size: 13px;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #232F48;
    min-height: 28px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: #58A6FF;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: transparent;
    height: 6px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #232F48;
    min-width: 28px;
    border-radius: 3px;
}

QScrollBar::handle:horizontal:hover {
    background: #58A6FF;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Buttons */
QPushButton {
    background-color: #141C2E;
    color: #F0F6FC;
    border: 1px solid #232F48;
    border-radius: 7px;
    padding: 7px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1B253D;
    border-color: #58A6FF;
    color: #FFFFFF;
}

QPushButton:pressed {
    background-color: #0F1422;
}

QPushButton:disabled {
    background-color: #0D121D;
    color: #48546A;
    border-color: #161F32;
}

QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
    color: #FFFFFF;
    border: 1px solid #58A6FF;
    font-weight: 700;
}

QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388BFD, stop:1 #58A6FF);
    border-color: #79B8FF;
}

QPushButton#accentButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2EA043);
    color: #FFFFFF;
    border: 1px solid #3FB950;
    font-weight: 700;
}

QPushButton#accentButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2EA043, stop:1 #3FB950);
}

QPushButton#dangerButton {
    background-color: #211317;
    color: #FF7B72;
    border: 1px solid #6E2229;
    font-weight: 600;
}

QPushButton#dangerButton:hover {
    background-color: #381A20;
    border-color: #F85149;
    color: #FFFFFF;
}

/* Inputs & Forms */
QLineEdit {
    background-color: #0F1524;
    color: #F0F6FC;
    border: 1px solid #232F48;
    border-radius: 7px;
    padding: 7px 12px;
    selection-background-color: #1F6FEB;
}

QLineEdit:focus {
    border: 1px solid #58A6FF;
    background-color: #131A2D;
}

QPlainTextEdit, QTextEdit {
    background-color: #0F1524;
    color: #F0F6FC;
    border: 1px solid #232F48;
    border-radius: 7px;
    padding: 10px;
    selection-background-color: #1F6FEB;
}

QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid #58A6FF;
    background-color: #131A2D;
}

/* Tables & Item Views */
QTableWidget, QTableView, QListView, QTreeView, QAbstractItemView {
    background-color: #0F1524;
    color: #F0F6FC;
    border: 1px solid #232F48;
    border-radius: 8px;
    gridline-color: #182236;
    selection-background-color: #1F365A;
    selection-color: #FFFFFF;
    outline: 0;
    outline: none;
}

QTableWidget:focus, QTableView:focus, QListView:focus, QTreeView:focus, QAbstractItemView:focus {
    outline: 0;
    outline: none;
    border: 1px solid #232F48;
}

QTableWidget::item, QTableView::item, QListView::item, QTreeView::item {
    padding: 8px 10px;
    border-bottom: 1px solid #182236;
    outline: 0;
    outline: none;
    border-top: none;
    border-left: none;
    border-right: none;
}

QTableWidget::item:hover, QTableView::item:hover {
    background-color: #182236;
    outline: 0;
    outline: none;
}

QTableWidget::item:selected, QTableView::item:selected {
    background-color: #1F365A;
    color: #FFFFFF;
    outline: 0;
    outline: none;
}

QTableWidget::item:focus, QTableView::item:focus,
QTableWidget::item:selected:focus, QTableView::item:selected:focus {
    outline: 0;
    outline: none;
    border-top: none;
    border-left: none;
    border-right: none;
}

QHeaderView::section {
    background-color: #0B0F19;
    color: #8B949E;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border: none;
    border-bottom: 2px solid #232F48;
    padding: 10px 8px;
}

/* Progress Bar */
QProgressBar {
    background-color: #182236;
    border: 1px solid #232F48;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #58A6FF);
    border-radius: 3px;
}

/* Context Menu */
QMenu {
    background-color: #141C2E;
    color: #F0F6FC;
    border: 1px solid #324468;
    border-radius: 8px;
    padding: 6px 0px;
}

QMenu::item {
    padding: 8px 24px;
    font-size: 13px;
}

QMenu::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F6FEB, stop:1 #388BFD);
    color: #FFFFFF;
}

QMenu::separator {
    height: 1px;
    background: #232F48;
    margin: 5px 10px;
}

/* Tooltip */
QToolTip {
    background-color: #141C2E;
    color: #F0F6FC;
    border: 1px solid #58A6FF;
    border-radius: 5px;
    padding: 6px 10px;
}
"""
