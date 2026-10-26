import sys
import os
import time
import ctypes

# Set Windows Taskbar AppUserModelID immediately
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("de.campusbibliothek.buchsortierer.1.0")
except Exception:
    pass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui.qt.splash import CampusSplashScreen
from ui.qt.main_window import CampusMainWindow
from ui.qt.theme import NoFocusProxyStyle
from core.library_db import init_library_schema


def get_app_icon_file() -> str:
    """Finds the absolute path to app_icon.ico across PyInstaller bundle and developer environments."""
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "app_icon.ico"))
        candidates.append(os.path.join(sys._MEIPASS, "app_icon.png"))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "app_icon.ico"))
        candidates.append(os.path.join(exe_dir, "app_icon.png"))
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates.append(os.path.join(root_dir, "app_icon.ico"))
    candidates.append(os.path.join(root_dir, "app_icon.png"))
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return ""


def force_windows_icon(hwnd: int, icon_file: str) -> None:
    """Forces the Windows shell / taskbar to assign the application icon via Win32 messages."""
    if not icon_file or not os.path.exists(icon_file):
        return
    try:
        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        h_icon = user32.LoadImageW(None, icon_file, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if h_icon:
            user32.SendMessageW(hwnd, WM_SETICON, 0, h_icon)  # ICON_SMALL
            user32.SendMessageW(hwnd, WM_SETICON, 1, h_icon)  # ICON_BIG
    except Exception:
        pass


def run_qt_app() -> None:
    """Initializes and runs the PySide6 desktop application with smooth splash transition."""
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setStyle(NoFocusProxyStyle(app.style()))
    app.setApplicationName("Campus-Bibliothek AI")

    # Load App Icon for Windows Taskbar & System Titlebars
    icon_file = get_app_icon_file()
    app_icon = QIcon(icon_file) if icon_file else None
    if app_icon and not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # Disable Windows "Not Responding" Ghosting mechanism completely
    try:
        ctypes.windll.user32.DisableProcessWindowsGhosting()
    except Exception:
        pass

    # 1. Display stylish Splash Screen
    splash = CampusSplashScreen()
    if app_icon:
        splash.setWindowIcon(app_icon)

    # Center splash screen on the active monitor
    try:
        screen_geo = app.primaryScreen().availableGeometry()
        splash.move(
            screen_geo.center().x() - splash.width() // 2,
            screen_geo.center().y() - splash.height() // 2,
        )
    except Exception:
        pass

    splash.show()
    app.processEvents()

    # Determine Warmstart (database file already exists and was previously opened)
    from core.config import get_database_path
    db_file = get_database_path()
    is_warmstart = os.path.isfile(db_file) and os.path.getsize(db_file) > 1024

    # Step 1: Fast SQLite Data-Lake check
    if not is_warmstart:
        splash.step_smooth(25, "Initialisiere SQLite Data-Lake...", duration_ms=80)
        init_library_schema()
        app.processEvents()
    else:
        splash.set_progress(35, "Lade System-Komponenten...")

    # Step 2: Build Main Window UI (with Lazy View architecture)
    if not is_warmstart:
        splash.step_smooth(65, "Baue Benutzeroberfläche & Views...", duration_ms=90)
    window = CampusMainWindow()
    if app_icon:
        window.setWindowIcon(app_icon)
    app.processEvents()

    # Step 3: Sidebar Stats
    if not is_warmstart:
        splash.step_smooth(85, "Lade Fachbuch-Register...", duration_ms=80)
    window.update_sidebar_stats()
    app.processEvents()

    # Step 4: Finalize & Reveal Main Window
    splash.set_progress(100, "Bereit!")
    app.processEvents()

    def launch_main():
        splash.close()
        window.showMaximized()
        if icon_file:
            force_windows_icon(int(window.winId()), icon_file)
        try:
            from core.crash_guard import mark_boot_success
            mark_boot_success()
        except Exception:
            pass

    # Instant transition: 60ms for warmstart, 180ms for cold start
    delay_ms = 60 if is_warmstart else 180
    QTimer.singleShot(delay_ms, launch_main)

    sys.exit(app.exec())


if __name__ == "__main__":
    run_qt_app()
