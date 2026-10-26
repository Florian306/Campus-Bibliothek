"""Buchsortierer AI - Intelligente Fachbuch-Katalogisierung & Sortierung.
Haupt-Einstiegspunkt der Desktop-Anwendung.
"""

import sys
import ctypes

# Set Windows Taskbar AppUserModelID immediately before any UI or COM initializations
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("de.campusbibliothek.buchsortierer.1.0")
except Exception:
    pass

def enforce_single_instance() -> bool:
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    mutex_name = "CampusBibliothekAI_SingleInstance_Mutex"
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = user32.FindWindowW(None, "Campus-Bibliothek AI – Virtueller Lehrbuch-Workspace")
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return False
    return True

def _handle_fatal_startup(err_text: str):
    try:
        from core.update_checker import CURRENT_VERSION
        from core.recovery_dialog import show_recovery_dialog
        show_recovery_dialog(err_text, CURRENT_VERSION)
    except Exception:
        pass
    sys.exit(1)


if __name__ == "__main__":
    if not enforce_single_instance():
        sys.exit(0)

    try:
        from core.update_checker import CURRENT_VERSION
        from core.crash_guard import mark_boot_started
        mark_boot_started(CURRENT_VERSION)
    except Exception:
        pass

    try:
        # Deliberate test crash to verify crash recovery and rollback behavior
        raise RuntimeError("SIMULIERTER TEST-CRASH: Initialisierungsfehler beim Booten der Anwendung!")
        from ui.qt_app import run_qt_app as main
        main()
    except Exception:
        import traceback
        _handle_fatal_startup(traceback.format_exc())
