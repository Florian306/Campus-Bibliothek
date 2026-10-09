"""Persistent, flicker-free filter tab bar.
"""

from typing import Callable, List
import customtkinter as ctk
from core.models import BookItem
from ui.theme import ACCENT_BLUE, ACCENT_BLUE_HOVER


class FilterTabBar(ctk.CTkFrame):
    """Modern persistent segment buttons for filtering all books, review-needed, and safe books."""

    def __init__(self, parent, on_tab_changed: Callable[[str], None]):
        super().__init__(parent, fg_color="transparent")
        self.on_tab_changed = on_tab_changed
        self.current_tab = "all"

        self.tab_container = ctk.CTkFrame(self, fg_color="#222226", corner_radius=8, height=36)
        self.tab_container.pack(side="left")

        self.btn_all = ctk.CTkButton(
            self.tab_container,
            text="📋 Alle Bücher (0)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_BLUE_HOVER,
            text_color="#ffffff",
            height=30,
            corner_radius=6,
            command=lambda: self.switch_to("all"),
        )
        self.btn_all.pack(side="left", padx=3, pady=3)

        self.btn_review = ctk.CTkButton(
            self.tab_container,
            text="⚠️ Zu überprüfen (0)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent",
            hover_color="#2e2e33",
            text_color="#a1a1aa",
            height=30,
            corner_radius=6,
            command=lambda: self.switch_to("review"),
        )
        self.btn_review.pack(side="left", padx=3, pady=3)

        self.btn_safe = ctk.CTkButton(
            self.tab_container,
            text="✅ Sicher (0)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent",
            hover_color="#2e2e33",
            text_color="#a1a1aa",
            height=30,
            corner_radius=6,
            command=lambda: self.switch_to("safe"),
        )
        self.btn_safe.pack(side="left", padx=3, pady=3)

    def switch_to(self, tab_id: str):
        """Switches active tab and updates button visuals instantly."""
        if self.current_tab == tab_id:
            return
        self.current_tab = tab_id

        self._refresh_styles()
        self.on_tab_changed(tab_id)

    def _refresh_styles(self, needs_rev_count: int = 0):
        tabs = [
            ("all", self.btn_all, ACCENT_BLUE, "#a1a1aa"),
            ("review", self.btn_review, "#dc2626" if needs_rev_count > 0 else ACCENT_BLUE, "#f87171" if needs_rev_count > 0 else "#a1a1aa"),
            ("safe", self.btn_safe, "#059669", "#a1a1aa"),
        ]
        for t_id, btn, active_bg, inact_fg in tabs:
            if t_id == self.current_tab:
                btn.configure(fg_color=active_bg, hover_color=active_bg, text_color="#ffffff")
            else:
                btn.configure(fg_color="transparent", hover_color="#2e2e33", text_color=inact_fg)

    def update_badges(self, items: List[BookItem]):
        """Updates tab badge count labels with zero latency and no widget destruction."""
        total = len(items)
        needs_rev_count = sum(1 for it in items if it.needs_review)
        safe_count = sum(1 for it in items if (not it.needs_review and it.status != "Wartend"))

        self.btn_all.configure(text=f"📋 Alle Bücher ({total})")

        rev_color = "#ffffff" if self.current_tab == "review" else ("#f87171" if needs_rev_count > 0 else "#a1a1aa")
        self.btn_review.configure(
            text=f"⚠️ Zu überprüfen ({needs_rev_count})",
            text_color=rev_color,
        )
        self.btn_safe.configure(text=f"✅ Sicher ({safe_count})")
