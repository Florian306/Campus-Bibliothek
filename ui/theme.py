"""Design system tokens, color palettes, and helpers for Buchsortierer AI.
Follows a sleek Windows 11 / Linear dark mode aesthetic.
"""

# Palette
BG_ROOT = "#09090b"
BG_CARD = "#18181b"
BG_CARD_ALT = "#202025"
BG_HOVER = "#2c2c36"
BG_CONTAINER = "#18181b"
BG_TABLE = "#141417"

# Borders & Accents
BORDER_MUTED = "#27272a"
BORDER_ACCENT = "#3f3f46"
ACCENT_BLUE = "#2563eb"
ACCENT_BLUE_HOVER = "#1d4ed8"
ACCENT_GREEN = "#059669"
ACCENT_GREEN_HOVER = "#047857"
ACCENT_RED = "#dc2626"
ACCENT_RED_HOVER = "#b91c1c"

# Text Colors
TEXT_PRIMARY = "#fafafa"
TEXT_SECONDARY = "#e4e4e7"
TEXT_MUTED = "#a1a1aa"
TEXT_DIM = "#71717a"
TEXT_BLUE = "#60a5fa"
TEXT_GREEN = "#34d399"
TEXT_YELLOW = "#fbbf24"
TEXT_RED = "#f87171"


def get_status_color(status: str) -> str:
    """Returns color hex string for an item status."""
    if "Sortiert" in status or "Erledigt" in status:
        return "#4ade80"
    if "Analysiert" in status:
        return "#38bdf8"
    if "Analysiere" in status:
        return "#fbbf24"
    if "Fehler" in status:
        return "#f87171"
    if "Trockenlauf" in status or "Vorschau" in status:
        return "#c084fc"
    return "#a1a1aa"


def get_confidence_badge_info(confidence: int, needs_review: bool, status: str) -> tuple:
    """Returns (text, text_color) tuple for confidence display."""
    if status == "Wartend":
        return ("-", "#71717a")
    if needs_review or confidence < 70:
        return (f"⚠️ {confidence}%", "#f87171")
    elif confidence < 85:
        return (f"🟡 {confidence}%", "#fbbf24")
    return (f"🟢 {confidence}%", "#34d399")
