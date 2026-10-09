"""Options bar component for user settings.
"""

from typing import Callable
import customtkinter as ctk
from ui.theme import ACCENT_BLUE, ACCENT_BLUE_HOVER


class OptionsBar(ctk.CTkFrame):
    """Container for application processing options."""

    def __init__(self, parent, on_change: Callable[[], None]):
        super().__init__(parent, fg_color="#18181b", corner_radius=10)
        self.on_change = on_change

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=10)

        opt_title = ctk.CTkLabel(
            inner,
            text="Optionen:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#d4d4d8",
            width=80,
            anchor="w",
        )
        opt_title.pack(side="left")

        self.var_auto_rename = ctk.BooleanVar(value=True)
        self.chk_auto_rename = ctk.CTkCheckBox(
            inner,
            text="Dateien automatisch umbenennen (Autor - Titel.pdf)",
            variable=self.var_auto_rename,
            font=ctk.CTkFont(size=13),
            text_color="#f4f4f5",
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_BLUE_HOVER,
            command=self.on_change,
        )
        self.chk_auto_rename.pack(side="left", padx=(10, 24))

        self.var_prefer_existing = ctk.BooleanVar(value=False)
        self.chk_prefer_existing = ctk.CTkCheckBox(
            inner,
            text="Bestehende Ordnerstruktur bevorzugen",
            variable=self.var_prefer_existing,
            font=ctk.CTkFont(size=13),
            text_color="#f4f4f5",
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_BLUE_HOVER,
            command=self.on_change,
        )
        self.chk_prefer_existing.pack(side="left", padx=(0, 24))

        self.var_dry_run = ctk.BooleanVar(value=False)
        self.chk_dry_run = ctk.CTkCheckBox(
            inner,
            text="Trockenlauf / Nur Vorschau anzeigen",
            variable=self.var_dry_run,
            font=ctk.CTkFont(size=13),
            text_color="#fbbf24",
            fg_color="#d97706",
            hover_color="#b45309",
            command=self.on_change,
        )
        self.chk_dry_run.pack(side="left")

    def get_settings(self) -> dict:
        return {
            "auto_rename": self.var_auto_rename.get(),
            "prefer_existing_dirs": self.var_prefer_existing.get(),
            "dry_run": self.var_dry_run.get(),
        }

    def set_settings(self, settings: dict):
        if "auto_rename" in settings:
            self.var_auto_rename.set(settings["auto_rename"])
        if "prefer_existing_dirs" in settings:
            self.var_prefer_existing.set(settings["prefer_existing_dirs"])
        if "dry_run" in settings:
            self.var_dry_run.set(settings["dry_run"])
