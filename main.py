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

from ui.qt_app import run_qt_app as main

if __name__ == "__main__":
    if not enforce_single_instance():
        sys.exit(0)
    main()
