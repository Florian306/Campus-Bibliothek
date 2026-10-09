"""Modal dialogs for user confirmations.
"""

import customtkinter as ctk


class ConfirmationDialog(ctk.CTkToplevel):
    """Modern modal confirmation dialog matching the Windows 11 dark aesthetic."""

    def __init__(self, parent, title: str, message: str, details: str = "", warn: bool = False):
        super().__init__(parent)
        self.parent = parent
        self.result = False

        self.title(title)
        self.geometry("560x310")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        try:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - 280
            y = parent.winfo_y() + (parent.winfo_height() // 2) - 155
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        self.configure(fg_color="#18181b")

        header_frame = ctk.CTkFrame(self, fg_color="#27272a" if not warn else "#451a03", height=50, corner_radius=0)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        icon_text = "⚠️ Bestätigung erforderlich" if warn else "📁 Sortierung anwenden"
        title_lbl = ctk.CTkLabel(
            header_frame,
            text=icon_text,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#fef08a" if warn else "#fafafa",
            anchor="w",
        )
        title_lbl.pack(side="left", padx=20, pady=12)

        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=24, pady=16)

        msg_lbl = ctk.CTkLabel(
            content_frame,
            text=message,
            font=ctk.CTkFont(size=13),
            text_color="#e4e4e7",
            justify="left",
            anchor="w",
        )
        msg_lbl.pack(fill="x", pady=(0, 10))

        if details:
            details_box = ctk.CTkFrame(
                content_frame,
                fg_color="#222226" if not warn else "#291307",
                corner_radius=6,
                border_width=1,
                border_color="#3f3f46" if not warn else "#b45309",
            )
            details_box.pack(fill="x", pady=(0, 10))

            det_lbl = ctk.CTkLabel(
                details_box,
                text=details,
                font=ctk.CTkFont(size=12),
                text_color="#fde047" if warn else "#a1a1aa",
                justify="left",
                anchor="w",
                wraplength=480,
            )
            det_lbl.pack(fill="x", padx=12, pady=10)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent", height=45)
        btn_frame.pack(fill="x", padx=24, pady=(0, 20))

        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Abbrechen",
            width=110,
            height=34,
            corner_radius=6,
            fg_color="#3f3f46",
            hover_color="#52525b",
            text_color="#fafafa",
            command=self._on_cancel,
        )
        cancel_btn.pack(side="right", padx=(10, 0))

        confirm_btn = ctk.CTkButton(
            btn_frame,
            text="Vorgang ausführen",
            width=150,
            height=34,
            corner_radius=6,
            fg_color="#059669" if not warn else "#d97706",
            hover_color="#047857" if not warn else "#b45309",
            text_color="#ffffff",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_confirm,
        )
        confirm_btn.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window()

    def _on_confirm(self):
        self.result = True
        self.destroy()

    def _on_cancel(self):
        self.result = False
        self.destroy()

    def destroy(self):
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()

