"""Native Windows GUI dialog for fatal boot crash recovery and rollback.
Displays error details, options to roll back to the previous stable release, or start in safe mode.
Uses Tkinter or standard Win32 MessageBox as fallback if PySide6 fails to boot.
"""

import os
import subprocess
import sys
import threading
import traceback
from typing import Optional

from core.crash_guard import (
    execute_rollback,
    fetch_previous_stable_release,
    load_boot_state,
    save_boot_state,
)


def show_recovery_dialog(error_details: str, current_version: str) -> None:
    """Displays recovery window offering instant one-click rollback."""
    state = load_boot_state()
    state["last_error"] = error_details
    save_boot_state(state)

    prev_info = fetch_previous_stable_release(current_version)
    prev_version = prev_info[0] if prev_info else state.get("previous_version") or "Vorgängerversion"
    download_url = prev_info[1] if prev_info else None

    # Attempt to open Tkinter dialog (Tkinter is built into Python/Windows, lightweight and immune to Qt DLL issues)
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.title("Campus-Bibliothek – Startfehler & Wiederherstellung")
        root.geometry("640x480")
        root.minsize(580, 420)
        root.configure(bg="#0D1117")

        # Center on screen
        root.update_idletasks()
        w = root.winfo_width()
        h = root.winfo_height()
        x = (root.winfo_screenwidth() // 2) - (w // 2)
        y = (root.winfo_screenheight() // 2) - (h // 2)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.attributes("-topmost", True)

        header_frame = tk.Frame(root, bg="#161B22", padx=20, pady=16)
        header_frame.pack(fill="x")

        title_lbl = tk.Label(
            header_frame,
            text=f"⚠️ Unerwarteter Startfehler in Version {current_version}",
            font=("Segoe UI", 13, "bold"),
            fg="#F85149",
            bg="#161B22",
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            header_frame,
            text="Die Anwendung konnte beim Starten nicht initialisiert werden.",
            font=("Segoe UI", 9),
            fg="#8B949E",
            bg="#161B22",
        )
        sub_lbl.pack(anchor="w", pady=(4, 0))

        content_frame = tk.Frame(root, bg="#0D1117", padx=20, pady=12)
        content_frame.pack(fill="both", expand=True)

        err_label = tk.Label(
            content_frame,
            text="Fehlerdiagnose:",
            font=("Segoe UI", 9, "bold"),
            fg="#C9D1D9",
            bg="#0D1117",
        )
        err_label.pack(anchor="w")

        text_box = tk.Text(
            content_frame,
            bg="#161B22",
            fg="#E6EDF3",
            insertbackground="#58A6FF",
            font=("Consolas", 8),
            wrap="word",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#30363D",
        )
        text_box.insert("1.0", error_details)
        text_box.config(state="disabled")
        text_box.pack(fill="both", expand=True, pady=6)

        status_lbl = tk.Label(
            content_frame,
            text=f"Empfehlung: Automatisch auf stabile Version ({prev_version}) zurücksetzen.",
            font=("Segoe UI", 9),
            fg="#7EE787",
            bg="#0D1117",
        )
        status_lbl.pack(anchor="w", pady=(4, 8))

        btn_frame = tk.Frame(root, bg="#161B22", padx=16, pady=12)
        btn_frame.pack(fill="x", side="bottom")

        def on_rollback():
            if not download_url:
                messagebox.showerror(
                    "Download nicht verfügbar",
                    f"Konnte das Installationspaket für Version {prev_version} nicht online abrufen.\n"
                    "Bitte lade die Vorgängerversion manuell von GitHub herunter.",
                )
                return

            status_lbl.config(text=f"Lade Version {prev_version} herunter und installiere...", fg="#E3B341")
            rollback_btn.config(state="disabled")
            close_btn.config(state="disabled")
            root.update()

            def _worker():
                success = execute_rollback(download_url, prev_version)
                if success:
                    root.after(0, lambda: root.destroy())
                    sys.exit(0)
                else:
                    root.after(0, lambda: messagebox.showerror("Fehler", "Rollback fehlgeschlagen."))
                    root.after(0, lambda: rollback_btn.config(state="normal"))
                    root.after(0, lambda: close_btn.config(state="normal"))

            threading.Thread(target=_worker, daemon=True).start()

        def copy_log():
            root.clipboard_clear()
            root.clipboard_append(error_details)
            messagebox.showinfo("Kopiert", "Fehlermeldung wurde in die Zwischenablage kopiert.")

        rollback_btn = tk.Button(
            btn_frame,
            text=f"🔄 Auf Version {prev_version} zurücksetzen (Rollback)",
            command=on_rollback,
            bg="#238636",
            fg="#FFFFFF",
            activebackground="#2EA043",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        )
        rollback_btn.pack(side="left")

        copy_btn = tk.Button(
            btn_frame,
            text="📋 Fehler kopieren",
            command=copy_log,
            bg="#21262D",
            fg="#C9D1D9",
            activebackground="#30363D",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9),
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )
        copy_btn.pack(side="left", padx=8)

        close_btn = tk.Button(
            btn_frame,
            text="Schließen",
            command=root.destroy,
            bg="#21262D",
            fg="#C9D1D9",
            activebackground="#30363D",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9),
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )
        close_btn.pack(side="right")

        root.mainloop()

    except Exception:
        # Ultimate fallback: Win32 message box
        import ctypes
        MB_YESNO = 0x00000004
        MB_ICONERROR = 0x00000010
        IDYES = 6
        msg = (
            f"Beim Starten von Campus-Bibliothek v{current_version} ist ein Fehler aufgetreten:\n\n"
            f"{error_details[:300]}...\n\n"
            f"Möchtest du automatisch auf die vorherige Version ({prev_version}) zurücksetzen?"
        )
        res = ctypes.windll.user32.MessageBoxW(0, msg, "Campus-Bibliothek – Startfehler", MB_YESNO | MB_ICONERROR)
        if res == IDYES and download_url:
            execute_rollback(download_url, prev_version)
            sys.exit(0)
