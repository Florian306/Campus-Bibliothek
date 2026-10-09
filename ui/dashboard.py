"""Campus Library AI - Modern Dark-Theme Dashboard.
Features:
- Sidebar Navigation: 🏛️ Bibliothek, 📖 Mein Schreibtisch, ⚠️ Auflagen-Radar, ⚡ Scan & Sync
- Data-Lake Approach: PDFs stay untouched on Google Drive / Local
- Real-time instant search (<2ms) and multi-category faceted chips
- Virtual Reading Desk with progress slider, notes, and instant PDF launcher
- Edition Sentinel tracking newer textbook releases
"""

import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.library_db import (
    get_all_books,
    get_desk_books,
    toggle_desk_item,
    update_reading_progress,
    get_book_notes,
    add_book_note,
    delete_book_note,
    get_category_counts,
    get_edition_alerts,
    dismiss_edition_alert,
    open_pdf_in_system_viewer,
    open_pdf_in_edge,
)
from core.config import get_app_dir, load_config, save_config
from core.cover_manager import (
    get_cached_cover,
    generate_fallback_cover,
    extract_and_cache_cover,
    FACULTY_COLORS,
)
from PIL import ImageTk


# Modern Obsidian & Indigo Palette
COLOR_BG = "#0D1117"
COLOR_SIDEBAR = "#161B22"
COLOR_CARD = "#1C2128"
COLOR_BORDER = "#30363D"
COLOR_PRIMARY = "#58A6FF"
COLOR_ACCENT = "#238636"
COLOR_WARNING = "#D29922"
COLOR_TEXT_MAIN = "#F0F6FC"
COLOR_TEXT_MUTED = "#8B949E"
COLOR_SELECTED = "#1F2937"
COLOR_HOVER = "#21262D"


class CampusLibraryDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Campus-Bibliothek AI – Virtueller Lehrbuch-Workspace")
        self.geometry("1300x820")
        self.minsize(1050, 650)
        self.configure(bg=COLOR_BG)

        # Set taskbar icon if exists
        icon_path = os.path.join(get_app_dir(), "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Thread dispatch queue
        self.ui_queue = queue.Queue()
        self.after(30, self._process_ui_queue)

        # Global Spacebar shortcut for Quick-Look preview
        self.bind("<space>", self._on_space_key)

        # Scanning State
        self.is_scanning = False
        self.stop_event = threading.Event()
        cfg = load_config()
        self.source_dir = cfg.get("last_directory") or r"G:\Meine Ablage\Bücher"
        if not os.path.exists(self.source_dir):
            self.source_dir = os.path.expanduser("~")

        # Active View State
        self.active_tab = ""
        self.current_category_filter = "Alle"
        self.search_term = ""
        self._search_after_id = None

        # Data cache & state flags for zero-latency instant tab switching
        self._library_loaded = False
        self._library_dirty = False
        self._desk_loaded = False
        self._desk_dirty = False
        self._radar_loaded = False
        self._radar_dirty = False
        self._rendered_chips_data = None

        # Catalog View Mode: 'shelf' (Regal) vs 'table' (Tabelle)
        self.catalog_view_mode = "shelf"
        self._photo_cache: Dict[str, Any] = {}
        self.selected_book_id: Optional[str] = None
        self._shelf_cards: Dict[str, tk.Frame] = {}
        self._shelf_cover_labels: Dict[str, tk.Label] = {}
        self._master_books: List[Dict[str, Any]] = []
        self._all_current_books: List[Dict[str, Any]] = []
        self._visible_shelf_card_ids: set = set()
        self._chip_buttons: Dict[str, tk.Button] = {}
        self._btn_more_menu: Optional[tk.Menubutton] = None
        self._shelf_empty_label: Optional[tk.Label] = None
        self._table_dirty: bool = True
        self._shelf_batch_job: Optional[str] = None
        self._shelf_render_index: int = 0

        # Background worker queue for async cover extraction
        self._cover_queue: queue.Queue = queue.Queue()
        self._queued_cover_ids: set = set()
        self._is_shutting_down = False
        self._start_cover_worker()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_styles()
        self._build_layout()

    def _dispatch(self, func: Callable, *args, **kwargs) -> None:
        self.ui_queue.put((func, args, kwargs))

    def _process_ui_queue(self) -> None:
        processed = 0
        while processed < 25 and not self.ui_queue.empty():
            try:
                func, args, kwargs = self.ui_queue.get_nowait()
                func(*args, **kwargs)
            except Exception as e:
                print(f"[UI Queue Error] {e}")
            processed += 1
        self.after(20, self._process_ui_queue)

    def _setup_styles(self) -> None:
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT_MAIN, font=("Segoe UI", 10))
        self.style.configure("Treeview",
            background=COLOR_CARD,
            foreground=COLOR_TEXT_MAIN,
            fieldbackground=COLOR_CARD,
            rowheight=38,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        self.style.configure("Treeview.Heading",
            background="#161B22",
            foreground="#8B949E",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padding=(10, 8),
        )
        self.style.map("Treeview",
            background=[("selected", "#1F3B64")],
            foreground=[("selected", "#FFFFFF")],
        )
        self.style.map("Treeview.Heading",
            background=[("active", "#21262D")],
            foreground=[("active", "#58A6FF")],
        )

        self.style.configure("Horizontal.TProgressbar",
            background=COLOR_PRIMARY,
            troughcolor=COLOR_BORDER,
            thickness=10,
            borderwidth=0,
        )

        self.style.layout("Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {
                "sticky": "ns",
                "children": [
                    ("Vertical.Scrollbar.thumb", {"sticky": "nswe"})
                ]
            })
        ])
        self.style.configure("Vertical.TScrollbar",
            background="#30363D",
            troughcolor="#0D1117",
            bordercolor="#0D1117",
            lightcolor="#30363D",
            darkcolor="#30363D",
            arrowsize=0,
            gripcount=0,
            relief="flat"
        )
        self.style.map("Vertical.TScrollbar",
            background=[("pressed", "#58A6FF"), ("active", "#484F58")]
        )

    def _build_layout(self) -> None:
        # Container
        self.main_container = tk.Frame(self, bg=COLOR_BG)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # -------------------------------------------------------------
        # Left Sidebar (230px wide)
        # -------------------------------------------------------------
        self.sidebar = tk.Frame(self.main_container, bg=COLOR_SIDEBAR, width=240)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        # App Brand Header
        brand_frame = tk.Frame(self.sidebar, bg=COLOR_SIDEBAR)
        brand_frame.pack(fill=tk.X, padx=16, pady=(20, 24))

        tk.Label(brand_frame, text="📚 Campus AI", font=("Segoe UI", 15, "bold"), bg=COLOR_SIDEBAR, fg=COLOR_TEXT_MAIN).pack(anchor="w")
        tk.Label(brand_frame, text="Virtuelle Fachbibliothek", font=("Segoe UI", 9), bg=COLOR_SIDEBAR, fg=COLOR_TEXT_MUTED).pack(anchor="w")

        # Nav Buttons
        self.nav_buttons = {}
        nav_items = [
            ("library", "🏛️  Bibliothek & Katalog", self._switch_to_library),
            ("desk", "📖  Mein Schreibtisch", self._switch_to_desk),
            ("radar", "⚠️  Auflagen-Radar", self._switch_to_radar),
            ("sync", "⚡  Scan & Sync", self._switch_to_sync),
        ]

        for key, label, cmd in nav_items:
            btn = tk.Button(
                self.sidebar,
                text=label,
                font=("Segoe UI", 10, "bold"),
                bg=COLOR_SIDEBAR,
                fg=COLOR_TEXT_MUTED,
                activebackground=COLOR_HOVER,
                activeforeground=COLOR_TEXT_MAIN,
                bd=0,
                padx=16,
                pady=11,
                anchor="w",
                cursor="hand2",
                command=cmd,
            )
            btn.pack(fill=tk.X, padx=8, pady=3)
            self.nav_buttons[key] = btn

        # Sidebar Footer: Total Stats
        sidebar_bottom = tk.Frame(self.sidebar, bg=COLOR_SIDEBAR)
        sidebar_bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=20)

        self.lbl_stats = tk.Label(
            sidebar_bottom,
            text="Lade Daten...",
            font=("Segoe UI", 9),
            bg=COLOR_SIDEBAR,
            fg=COLOR_TEXT_MUTED,
            justify=tk.LEFT,
        )
        self.lbl_stats.pack(anchor="w")

        # -------------------------------------------------------------
        # Main Content Area
        # -------------------------------------------------------------
        self.content_frame = tk.Frame(self.main_container, bg=COLOR_BG)
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=20)
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        # Build pages
        self._build_library_view()
        self._build_desk_view()
        self._build_radar_view()
        self._build_sync_view()

        # Grid all pages into identical cell for instant zero-latency raising
        for frame in (self.frame_library, self.frame_desk, self.frame_radar, self.frame_sync):
            frame.grid(row=0, column=0, sticky="nsew")

        # Show initial tab
        self._switch_to_library()

    def _highlight_nav(self, active_key: str) -> None:
        self.active_tab = active_key
        for key, btn in self.nav_buttons.items():
            if key == active_key:
                btn.configure(bg=COLOR_CARD, fg=COLOR_PRIMARY)
            else:
                btn.configure(bg=COLOR_SIDEBAR, fg=COLOR_TEXT_MUTED)

    # -----------------------------------------------------------------
    # -----------------------------------------------------------------
    # VIEW 1: BIBLIOTHEK & KATALOG
    # -----------------------------------------------------------------
    def _build_library_view(self) -> None:
        self.frame_library = tk.Frame(self.content_frame, bg=COLOR_BG)

        # Header Bar: Title, Subtitle, Total Badge, View Switcher & Search
        top_bar = tk.Frame(self.frame_library, bg=COLOR_BG)
        top_bar.pack(fill=tk.X, pady=(0, 14))

        title_box = tk.Frame(top_bar, bg=COLOR_BG)
        title_box.pack(side=tk.LEFT, anchor="w")

        title_row = tk.Frame(title_box, bg=COLOR_BG)
        title_row.pack(anchor="w")

        tk.Label(
            title_row,
            text="🏛️  Katalog & Literaturverzeichnis",
            font=("Segoe UI", 16, "bold"),
            bg=COLOR_BG,
            fg=COLOR_TEXT_MAIN,
        ).pack(side=tk.LEFT)

        self.lbl_badge_total = tk.Label(
            title_row,
            text="320 Bücher",
            font=("Segoe UI", 9, "bold"),
            bg="#1F2937",
            fg=COLOR_PRIMARY,
            padx=10,
            pady=2,
            bd=1,
            relief="solid",
        )
        self.lbl_badge_total.pack(side=tk.LEFT, padx=(12, 0))

        tk.Label(
            title_box,
            text="Zentrales Register aller archivierten Fach- und Lehrbücher mit Volltext-Index",
            font=("Segoe UI", 9),
            bg=COLOR_BG,
            fg=COLOR_TEXT_MUTED,
        ).pack(anchor="w", pady=(3, 0))

        # View Mode Switcher (Bücherregal vs. Tabelle)
        switch_frame = tk.Frame(top_bar, bg=COLOR_SIDEBAR, bd=1, relief="solid", highlightthickness=1, highlightbackground=COLOR_BORDER)
        switch_frame.pack(side=tk.RIGHT, padx=(12, 0), pady=4)

        self.btn_view_shelf = tk.Button(
            switch_frame,
            text="🗂️ Bücherregal",
            font=("Segoe UI", 9, "bold"),
            bg="#1F6FEB",
            fg="#FFFFFF",
            activebackground=COLOR_HOVER,
            activeforeground="#FFFFFF",
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: self._set_catalog_view_mode("shelf"),
        )
        self.btn_view_shelf.pack(side=tk.LEFT)

        self.btn_view_table = tk.Button(
            switch_frame,
            text="📋 Katalogliste",
            font=("Segoe UI", 9),
            bg=COLOR_SIDEBAR,
            fg=COLOR_TEXT_MUTED,
            activebackground=COLOR_HOVER,
            activeforeground=COLOR_TEXT_MAIN,
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: self._set_catalog_view_mode("table"),
        )
        self.btn_view_table.pack(side=tk.LEFT)

        # Modern Search Input with integrated icon and clear button
        search_box = tk.Frame(top_bar, bg=COLOR_SIDEBAR, bd=1, relief="solid", highlightthickness=1, highlightbackground=COLOR_BORDER)
        search_box.pack(side=tk.RIGHT, pady=4)

        tk.Label(search_box, text=" 🔍 ", bg=COLOR_SIDEBAR, fg=COLOR_PRIMARY, font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.ent_search = tk.Entry(
            search_box,
            font=("Segoe UI", 10),
            bg=COLOR_SIDEBAR,
            fg=COLOR_TEXT_MAIN,
            insertbackground=COLOR_PRIMARY,
            bd=0,
            width=28,
        )
        self.ent_search.pack(side=tk.LEFT, ipady=6, padx=(0, 4))
        self.ent_search.bind("<KeyRelease>", self._on_search_change)

        self.btn_clear_search = tk.Button(
            search_box,
            text="✖",
            font=("Segoe UI", 8),
            bg=COLOR_SIDEBAR,
            fg=COLOR_TEXT_MUTED,
            activebackground=COLOR_HOVER,
            activeforeground=COLOR_TEXT_MAIN,
            bd=0,
            padx=6,
            pady=2,
            cursor="hand2",
            command=self._clear_search,
        )
        self.btn_clear_search.pack(side=tk.LEFT, padx=(0, 4))

        # Category Filter Chips Bar
        self.chips_frame = tk.Frame(self.frame_library, bg=COLOR_BG)
        self.chips_frame.pack(fill=tk.X, pady=(0, 14))

        # -------------------------------------------------------------
        # Action Bar pinned to bottom
        # -------------------------------------------------------------
        action_bar = tk.Frame(self.frame_library, bg=COLOR_BG)
        action_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))

        # Center View Container (Holds Shelf Grid & Table)
        self.center_view_container = tk.Frame(self.frame_library, bg=COLOR_BG)
        self.center_view_container.pack(fill=tk.BOTH, expand=True)

        # -------------------------------------------------------------
        # 1. SHELF VIEW (Virtuelles Bücherregal)
        # -------------------------------------------------------------
        self.shelf_frame = tk.Frame(self.center_view_container, bg=COLOR_BG)

        self.shelf_canvas = tk.Canvas(self.shelf_frame, bg=COLOR_BG, highlightthickness=0)
        self.shelf_sb = ttk.Scrollbar(self.shelf_frame, orient="vertical", command=self.shelf_canvas.yview)
        self.shelf_canvas.configure(yscrollcommand=self.shelf_sb.set)

        self.shelf_content = tk.Frame(self.shelf_canvas, bg=COLOR_BG)
        self.shelf_window = self.shelf_canvas.create_window((0, 0), window=self.shelf_content, anchor="nw")

        self._shelf_empty_label = tk.Label(
            self.shelf_content,
            text="Keine Bücher für die aktuellen Filterkriterien gefunden.",
            font=("Segoe UI", 12),
            bg=COLOR_BG,
            fg=COLOR_TEXT_MUTED,
            pady=60,
        )

        self.shelf_canvas.bind("<Configure>", self._on_shelf_canvas_configure)
        self.shelf_content.bind("<Configure>", self._on_shelf_content_configure)
        self.shelf_canvas.bind_all("<MouseWheel>", self._on_shelf_mousewheel)

        self.shelf_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.shelf_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # -------------------------------------------------------------
        # 2. TABLE VIEW (Katalogliste)
        # -------------------------------------------------------------
        self.table_frame = tk.Frame(self.center_view_container, bg=COLOR_CARD, bd=1, relief="solid", highlightthickness=1, highlightbackground=COLOR_BORDER)

        columns = ("desk", "title", "author", "category", "edition", "pages")
        self.tree_books = ttk.Treeview(self.table_frame, columns=columns, show="headings", selectmode="browse")

        self.tree_books.heading("desk", text="Pult", anchor="center")
        self.tree_books.heading("title", text="📖 Buchtitel", anchor="w", command=lambda: self._sort_tree_column("title", False))
        self.tree_books.heading("author", text="✍️ Autor(en)", anchor="w", command=lambda: self._sort_tree_column("author", False))
        self.tree_books.heading("category", text="🏷️ Fachbereich", anchor="w", command=lambda: self._sort_tree_column("category", False))
        self.tree_books.heading("edition", text="🔢 Auflage", anchor="center", command=lambda: self._sort_tree_column("edition", False))
        self.tree_books.heading("pages", text="📄 Seiten", anchor="center", command=lambda: self._sort_tree_column("pages", False))

        self.tree_books.column("desk", width=45, anchor="center")
        self.tree_books.column("title", width=420, anchor="w")
        self.tree_books.column("author", width=200, anchor="w")
        self.tree_books.column("category", width=220, anchor="w")
        self.tree_books.column("edition", width=85, anchor="center")
        self.tree_books.column("pages", width=75, anchor="center")

        # Alternating Row Tags (High-End Dark Mode Zebra)
        self.tree_books.tag_configure("even", background="#12171F", foreground=COLOR_TEXT_MAIN)
        self.tree_books.tag_configure("odd", background="#19202A", foreground=COLOR_TEXT_MAIN)

        sb = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree_books.yview)
        self.tree_books.configure(yscrollcommand=sb.set)

        self.tree_books.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree_books.bind("<Double-1>", self._on_book_double_click)
        self.tree_books.bind("<Button-3>", self._on_tree_context_menu)
        self.tree_books.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Show Shelf View by default
        self.shelf_frame.pack(fill=tk.BOTH, expand=True)

        btn_open = tk.Button(
            action_bar,
            text="📂  PDF direkt öffnen",
            font=("Segoe UI", 10, "bold"),
            bg="#238636",
            fg="#FFFFFF",
            activebackground="#2EA043",
            activeforeground="#FFFFFF",
            bd=0,
            padx=16,
            pady=7,
            cursor="hand2",
            command=self._open_selected_book,
        )
        btn_open.pack(side=tk.LEFT, padx=(0, 10))

        btn_quick_look = tk.Button(
            action_bar,
            text="🔍  Quick-Look (Leertaste)",
            font=("Segoe UI", 10),
            bg=COLOR_CARD,
            fg=COLOR_TEXT_MAIN,
            activebackground=COLOR_HOVER,
            activeforeground=COLOR_TEXT_MAIN,
            bd=1,
            relief="solid",
            padx=14,
            pady=7,
            cursor="hand2",
            command=self._open_quick_look,
        )
        btn_quick_look.pack(side=tk.LEFT, padx=(0, 10))

        btn_toggle_desk = tk.Button(
            action_bar,
            text="📖  Auf Schreibtisch / entfernen",
            font=("Segoe UI", 10),
            bg=COLOR_CARD,
            fg=COLOR_TEXT_MAIN,
            activebackground=COLOR_HOVER,
            activeforeground=COLOR_TEXT_MAIN,
            bd=1,
            relief="solid",
            padx=14,
            pady=7,
            cursor="hand2",
            command=self._toggle_selected_desk,
        )
        btn_toggle_desk.pack(side=tk.LEFT, padx=(0, 10))

        btn_reclassify = tk.Button(
            action_bar,
            text="✨  Katalog & Titel optimieren",
            font=("Segoe UI", 10, "bold"),
            bg=COLOR_CARD,
            fg="#F0883E",
            activebackground=COLOR_HOVER,
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            padx=14,
            pady=7,
            cursor="hand2",
            command=self._trigger_auto_reclassify,
        )
        btn_reclassify.pack(side=tk.LEFT)

        btn_export = tk.Button(
            action_bar,
            text="📚  Exportieren",
            font=("Segoe UI", 10),
            bg=COLOR_CARD,
            fg="#58A6FF",
            activebackground=COLOR_HOVER,
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            padx=14,
            pady=7,
            cursor="hand2",
            command=self._open_export_dialog,
        )
        btn_export.pack(side=tk.LEFT, padx=(10, 0))

        # Right side info & counter pill
        info_frame = tk.Frame(action_bar, bg=COLOR_BG)
        info_frame.pack(side=tk.RIGHT)

        self.lbl_table_count = tk.Label(
            info_frame,
            text="320 Bücher",
            font=("Segoe UI", 9, "bold"),
            bg="#1F2937",
            fg=COLOR_PRIMARY,
            padx=10,
            pady=4,
            bd=1,
            relief="solid"
        )
        self.lbl_table_count.pack(side=tk.RIGHT, padx=(12, 0))

        tk.Label(
            info_frame,
            text="💡 Tipp: Leertaste für Quick-Look • Doppelklick öffnet PDF • Rechtsklick für Zitate & Editor",
            font=("Segoe UI", 9),
            bg=COLOR_BG,
            fg=COLOR_TEXT_MUTED,
        ).pack(side=tk.RIGHT)

    # -----------------------------------------------------------------
    # VIEW 2: MEIN SCHREIBTISCH (LESEPULT)
    # -----------------------------------------------------------------
    def _build_desk_view(self) -> None:
        self.frame_desk = tk.Frame(self.content_frame, bg=COLOR_BG)

        # Header
        top_bar = tk.Frame(self.frame_desk, bg=COLOR_BG)
        top_bar.pack(fill=tk.X, pady=(0, 14))

        tk.Label(top_bar, text="📖 Mein Schreibtisch (Aktive Lektüre)", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT_MAIN).pack(side=tk.LEFT)

        # Desk Container with Split (List Left, Notes Right)
        split_frame = tk.Frame(self.frame_desk, bg=COLOR_BG)
        split_frame.pack(fill=tk.BOTH, expand=True)

        # Left: Desk Book Items
        self.desk_list_frame = tk.Frame(split_frame, bg=COLOR_CARD, bd=1, relief="solid")
        self.desk_list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 14))

        columns = ("title", "author", "progress", "pages", "notes")
        self.tree_desk = ttk.Treeview(self.desk_list_frame, columns=columns, show="headings", selectmode="browse")

        self.tree_desk.heading("title", text="Buchtitel", anchor="w")
        self.tree_desk.heading("author", text="Autor", anchor="w")
        self.tree_desk.heading("progress", text="Fortschritt", anchor="center")
        self.tree_desk.heading("pages", text="Aktuelle Seite", anchor="center")
        self.tree_desk.heading("notes", text="Notizen", anchor="center")

        self.tree_desk.column("title", width=300, anchor="w")
        self.tree_desk.column("author", width=150, anchor="w")
        self.tree_desk.column("progress", width=90, anchor="center")
        self.tree_desk.column("pages", width=110, anchor="center")
        self.tree_desk.column("notes", width=70, anchor="center")

        self.tree_desk.pack(fill=tk.BOTH, expand=True)
        self.tree_desk.bind("<<TreeviewSelect>>", self._on_desk_select)
        self.tree_desk.bind("<Double-1>", self._on_desk_double_click)

        # Right: Quick Notes Panel
        self.notes_panel = tk.Frame(split_frame, bg=COLOR_CARD, bd=1, relief="solid", width=340)
        self.notes_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.notes_panel.pack_propagate(False)

        tk.Label(self.notes_panel, text="📝 Notizen & Exzerpte", font=("Segoe UI", 12, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MAIN).pack(anchor="w", padx=14, pady=12)

        self.lbl_active_book_title = tk.Label(self.notes_panel, text="Wähle ein Buch aus...", font=("Segoe UI", 9), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, wraplength=310, justify=tk.LEFT)
        self.lbl_active_book_title.pack(anchor="w", padx=14, pady=(0, 10))

        # Progress update controls
        p_frame = tk.Frame(self.notes_panel, bg=COLOR_CARD)
        p_frame.pack(fill=tk.X, padx=14, pady=(0, 10))
        tk.Label(p_frame, text="Seite:", font=("Segoe UI", 10), bg=COLOR_CARD, fg=COLOR_TEXT_MAIN).pack(side=tk.LEFT)
        self.ent_current_page = tk.Entry(p_frame, width=6, bg=COLOR_BG, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN)
        self.ent_current_page.pack(side=tk.LEFT, padx=6)
        self.ent_current_page.bind("<Return>", lambda e: self._save_page_progress())
        btn_save_p = tk.Button(p_frame, text="Speichern", font=("Segoe UI", 9, "bold"), bg=COLOR_SIDEBAR, fg=COLOR_PRIMARY, bd=0, padx=8, pady=2, command=self._save_page_progress, cursor="hand2")
        btn_save_p.pack(side=tk.LEFT)
        self.lbl_desk_page_feedback = tk.Label(p_frame, text="", font=("Segoe UI", 8), bg=COLOR_CARD, fg="#3FB950")
        self.lbl_desk_page_feedback.pack(side=tk.LEFT, padx=(8, 0))

        # Notes text box
        self.txt_note = tk.Text(self.notes_panel, bg=COLOR_BG, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=0, font=("Segoe UI", 10), padx=8, pady=8)
        self.txt_note.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))

        btn_add_note = tk.Button(self.notes_panel, text="➕ Notiz sichern", font=("Segoe UI", 10, "bold"), bg=COLOR_PRIMARY, fg="#FFFFFF", bd=0, pady=6, command=self._add_current_note)
        btn_add_note.pack(fill=tk.X, padx=14, pady=(0, 14))

        # Bottom Desk Controls
        desk_ctrl = tk.Frame(self.frame_desk, bg=COLOR_BG)
        desk_ctrl.pack(fill=tk.X, pady=(12, 0))

        btn_open_desk = tk.Button(desk_ctrl, text="📖 In Edge öffnen (gespeicherte Seite)", font=("Segoe UI", 10, "bold"), bg=COLOR_ACCENT, fg="#FFFFFF", bd=0, padx=14, pady=6, cursor="hand2", command=self._open_selected_desk_pdf)
        btn_open_desk.pack(side=tk.LEFT, padx=(0, 10))

        btn_remove_desk = tk.Button(desk_ctrl, text="❌ Vom Schreibtisch entfernen", font=("Segoe UI", 10), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, bd=1, relief="solid", padx=14, pady=6, cursor="hand2", command=self._remove_from_desk)
        btn_remove_desk.pack(side=tk.LEFT)

    # -----------------------------------------------------------------
    # VIEW 3: AUFLAGEN-RADAR
    # -----------------------------------------------------------------
    def _build_radar_view(self) -> None:
        self.frame_radar = tk.Frame(self.content_frame, bg=COLOR_BG)
        self.radar_mode = "editions"

        top_bar = tk.Frame(self.frame_radar, bg=COLOR_BG)
        top_bar.pack(fill=tk.X, pady=(0, 14))

        self.lbl_radar_title = tk.Label(top_bar, text="⚠️ Auflagen-Radar (Literatur-Aktualität)", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT_MAIN)
        self.lbl_radar_title.pack(side=tk.LEFT)

        # Mode switcher buttons (Editions vs Duplicates)
        mode_box = tk.Frame(top_bar, bg=COLOR_BG)
        mode_box.pack(side=tk.LEFT, padx=(20, 0))

        self.btn_mode_editions = tk.Button(
            mode_box,
            text="⚠️  Auflagen-Radar",
            font=("Segoe UI", 9, "bold"),
            bg="#1F6FEB",
            fg="#FFFFFF",
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: self._set_radar_mode("editions"),
        )
        self.btn_mode_editions.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_mode_duplicates = tk.Button(
            mode_box,
            text="👯  Dubletten-Finder",
            font=("Segoe UI", 9),
            bg=COLOR_CARD,
            fg=COLOR_TEXT_MUTED,
            bd=1,
            relief="solid",
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: self._set_radar_mode("duplicates"),
        )
        self.btn_mode_duplicates.pack(side=tk.LEFT)

        self.btn_radar_action = tk.Button(
            top_bar,
            text="🔄 Auflagen online abgleichen",
            font=("Segoe UI", 10, "bold"),
            bg=COLOR_CARD,
            fg=COLOR_WARNING,
            bd=1,
            relief="solid",
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._on_radar_action_clicked,
        )
        self.btn_radar_action.pack(side=tk.RIGHT)

        table_frame = tk.Frame(self.frame_radar, bg=COLOR_CARD, bd=1, relief="solid")
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("title", "author", "current_ed", "latest_ed", "diff", "action")
        self.tree_radar = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        self._configure_radar_tree_columns()

        self.tree_radar.pack(fill=tk.BOTH, expand=True)
        self.tree_radar.bind("<Double-1>", self._on_radar_double_click)

    # -----------------------------------------------------------------
    # VIEW 4: SCAN & SYNC CENTER
    # -----------------------------------------------------------------
    def _build_sync_view(self) -> None:
        self.frame_sync = tk.Frame(self.content_frame, bg=COLOR_BG)

        tk.Label(self.frame_sync, text="⚡ Scan & Sync Center (Data-Lake)", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0, 14))

        # Panel: Source Folder
        card_dir = tk.Frame(self.frame_sync, bg=COLOR_CARD, bd=1, relief="solid", padx=16, pady=16)
        card_dir.pack(fill=tk.X, pady=(0, 14))

        tk.Label(card_dir, text="Quellverzeichnis (Google Drive oder lokaler Ordner):", font=("Segoe UI", 10, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0, 6))

        dir_box = tk.Frame(card_dir, bg=COLOR_CARD)
        dir_box.pack(fill=tk.X)

        self.lbl_source_dir = tk.Label(dir_box, text=self.source_dir, font=("Segoe UI", 10), bg=COLOR_BG, fg=COLOR_TEXT_MAIN, anchor="w", padx=10, pady=6)
        self.lbl_source_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        btn_choose = tk.Button(dir_box, text="Ordner wählen...", font=("Segoe UI", 10), bg=COLOR_SIDEBAR, fg=COLOR_TEXT_MAIN, bd=1, relief="solid", padx=12, pady=5, cursor="hand2", command=self._choose_source_dir)
        btn_choose.pack(side=tk.RIGHT)

        # Panel: Trigger Delta-Scan
        card_scan = tk.Frame(self.frame_sync, bg=COLOR_CARD, bd=1, relief="solid", padx=16, pady=16)
        card_scan.pack(fill=tk.X, pady=(0, 14))

        tk.Label(card_scan, text="Inkrementeller Delta-Scan:", font=("Segoe UI", 11, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MAIN).pack(anchor="w")
        tk.Label(card_scan, text="Bereits bekannte PDFs werden in Millisekunden übersprungen. Nur neue oder geänderte Bücher werden analysiert.", font=("Segoe UI", 9), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED).pack(anchor="w", pady=(2, 12))

        self.progress_bar = ttk.Progressbar(card_scan, style="Horizontal.TProgressbar", mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))

        btn_row = tk.Frame(card_scan, bg=COLOR_CARD)
        btn_row.pack(fill=tk.X)

        self.btn_run_scan = tk.Button(
            btn_row,
            text="⚡ Delta-Scan starten",
            font=("Segoe UI", 11, "bold"),
            bg=COLOR_PRIMARY,
            fg="#FFFFFF",
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._start_delta_scan,
        )
        self.btn_run_scan.pack(side=tk.LEFT)

        self.lbl_scan_status = tk.Label(btn_row, text="Bereit für Delta-Scan", font=("Segoe UI", 10), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED)
        self.lbl_scan_status.pack(side=tk.LEFT, padx=16)

        # Log Terminal
        log_frame = tk.Frame(self.frame_sync, bg=COLOR_CARD, bd=1, relief="solid", padx=12, pady=12)
        log_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(log_frame, text="Ereignis-Protokoll:", font=("Segoe UI", 10, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0, 6))

        self.txt_log = tk.Text(log_frame, bg=COLOR_BG, fg=COLOR_TEXT_MAIN, font=("Consolas", 9), bd=0, padx=8, pady=8)
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    # -----------------------------------------------------------------
    # NAVIGATION SWITCHES (Instant 0ms Stacking via tkraise)
    # -----------------------------------------------------------------
    def _switch_to_library(self) -> None:
        if self.active_tab == "library" and getattr(self, "_library_loaded", False):
            return
        self._highlight_nav("library")
        self.frame_library.tkraise()
        if not getattr(self, "_library_loaded", False) or getattr(self, "_library_dirty", False):
            self._load_library_data()
            self._library_loaded = True
            self._library_dirty = False

    def _switch_to_desk(self) -> None:
        if self.active_tab == "desk" and getattr(self, "_desk_loaded", False):
            return
        self._highlight_nav("desk")
        self.frame_desk.tkraise()
        if not getattr(self, "_desk_loaded", False) or getattr(self, "_desk_dirty", False):
            self._load_desk_data()
            self._desk_loaded = True
            self._desk_dirty = False

    def _switch_to_radar(self) -> None:
        if self.active_tab == "radar" and getattr(self, "_radar_loaded", False):
            return
        self._highlight_nav("radar")
        self.frame_radar.tkraise()
        if not getattr(self, "_radar_loaded", False) or getattr(self, "_radar_dirty", False):
            self._load_radar_data()
            self._radar_loaded = True
            self._radar_dirty = False

    def _switch_to_sync(self) -> None:
        if self.active_tab == "sync":
            return
        self._highlight_nav("sync")
        self.frame_sync.tkraise()

    # -----------------------------------------------------------------
    # DATA LOADING & FILTERING
    # -----------------------------------------------------------------
    def _clear_search(self) -> None:
        self.ent_search.delete(0, tk.END)
        self.search_term = ""
        self._apply_catalog_filter()

    def _sort_tree_column(self, col: str, reverse: bool) -> None:
        l = [(self.tree_books.set(k, col), k) for k in self.tree_books.get_children('')]
        # try numeric sort for pages or edition
        try:
            l.sort(key=lambda t: int(re.sub(r'\D', '', t[0]) or 0), reverse=reverse)
        except Exception:
            l.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (val, k) in enumerate(l):
            self.tree_books.move(k, '', index)
            row_tag = "even" if index % 2 == 0 else "odd"
            self.tree_books.item(k, tags=(row_tag,))

        # toggle sort direction for next click
        self.tree_books.heading(col, command=lambda: self._sort_tree_column(col, not reverse))

    def _set_catalog_view_mode(self, mode: str) -> None:
        if self.catalog_view_mode == mode:
            return
        self.catalog_view_mode = mode
        if mode == "shelf":
            self.table_frame.pack_forget()
            self.shelf_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_view_shelf.configure(bg="#1F6FEB", fg="#FFFFFF")
            self.btn_view_table.configure(bg=COLOR_SIDEBAR, fg=COLOR_TEXT_MUTED)
            self._render_shelf_grid()
        else:
            self.shelf_frame.pack_forget()
            self.table_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_view_table.configure(bg="#1F6FEB", fg="#FFFFFF")
            self.btn_view_shelf.configure(bg=COLOR_SIDEBAR, fg=COLOR_TEXT_MUTED)
            if getattr(self, "_table_dirty", True):
                self._populate_table_view()
            if self.selected_book_id and self.tree_books.exists(self.selected_book_id):
                self.tree_books.selection_set(self.selected_book_id)
                self.tree_books.see(self.selected_book_id)

    def _on_shelf_canvas_configure(self, event) -> None:
        if event.widget != self.shelf_canvas:
            return
        canvas_width = event.width
        if canvas_width <= 200:
            return

        self.shelf_canvas.coords(self.shelf_window, 0, 0)
        self.shelf_canvas.itemconfig(self.shelf_window, width=canvas_width)

        card_slot_width = 184
        new_cols = max(1, min(8, canvas_width // card_slot_width))
        spare = canvas_width - (new_cols * card_slot_width)
        left_pad = max(8, spare // 2)

        # Instant zero-latency layout adaptation: immediate on window open, maximize, and restore
        if getattr(self, "_current_shelf_cols", 0) != new_cols and self._all_current_books:
            self._current_shelf_cols = new_cols
            self._reposition_shelf_cards(new_cols, left_pad)
        else:
            self._update_shelf_horizontal_padding(left_pad)

    def _update_shelf_horizontal_padding(self, left_pad: int) -> None:
        if getattr(self, "_current_left_pad", None) == left_pad:
            return
        self._current_left_pad = left_pad
        cols = getattr(self, "_current_shelf_cols", 4)
        rendered_count = getattr(self, "_shelf_render_index", len(self._all_current_books))
        for idx in range(min(rendered_count, len(self._all_current_books))):
            b_id = self._all_current_books[idx]["id"]
            if b_id in self._shelf_cards:
                r, c = divmod(idx, cols)
                if c == 0:
                    try:
                        self._shelf_cards[b_id].grid_configure(padx=(left_pad, 8))
                    except Exception:
                        pass

    def _on_shelf_content_configure(self, event=None) -> None:
        if event and event.widget != self.shelf_content:
            return
        self.shelf_canvas.configure(scrollregion=self.shelf_canvas.bbox("all"))

    def _on_shelf_mousewheel(self, event) -> None:
        if getattr(self, "catalog_view_mode", "") != "shelf":
            return
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
            if not widget:
                return
            w = widget
            is_over_shelf = False
            while w is not None:
                if w == self.shelf_canvas or w == self.shelf_content:
                    is_over_shelf = True
                    break
                w = getattr(w, "master", None)
            if not is_over_shelf:
                return
            self.shelf_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            yv = self.shelf_canvas.yview()
            if yv and yv[1] > 0.65 and getattr(self, "_shelf_render_index", 0) < len(self._all_current_books):
                self._render_next_shelf_batch()
        except Exception:
            pass

    def _reposition_shelf_cards(self, cols: int, left_pad: int = 8) -> None:
        if not self._all_current_books:
            return
        self._current_left_pad = left_pad

        try:
            yview = self.shelf_canvas.yview()
            old_ratio = yview[0] if yview else 0.0
        except Exception:
            old_ratio = 0.0

        rendered_count = getattr(self, "_shelf_render_index", len(self._all_current_books))
        active_count = min(rendered_count, len(self._all_current_books))

        for idx in range(active_count):
            b_id = self._all_current_books[idx]["id"]
            if b_id in self._shelf_cards:
                r, c = divmod(idx, cols)
                pad_x = (left_pad, 8) if c == 0 else 8
                self._shelf_cards[b_id].grid(row=r, column=c, padx=pad_x, pady=9, sticky="n")

        total_rows = (len(self._all_current_books) + cols - 1) // cols
        est_height = max(600, total_rows * 326 + 30)
        self.shelf_canvas.configure(scrollregion=(0, 0, self.shelf_canvas.winfo_width(), est_height))

        if old_ratio > 0.0:
            try:
                self.shelf_canvas.yview_moveto(old_ratio)
            except Exception:
                pass

    @staticmethod
    def _format_card_title(title: str, max_chars: int = 44) -> str:
        t = (title or "Ohne Titel").strip()
        if len(t) <= max_chars:
            return t
        truncated = t[:max_chars].rsplit(" ", 1)[0]
        return (truncated if truncated else t[:max_chars]) + "…"

    @staticmethod
    def _format_card_author(author: str, max_chars: int = 24) -> str:
        a = (author or "Unbekannter Autor").strip()
        if len(a) <= max_chars:
            return a
        return a[:max_chars - 1] + "…"

    def _create_shelf_card_widget(self, b: Dict[str, Any]) -> tk.Frame:
        b_id = b["id"]
        is_sel = (self.selected_book_id == b_id)
        card_bg = "#1C2738" if is_sel else "#161B22"
        card_border = "#58A6FF" if is_sel else "#30363D"

        card = tk.Frame(
            self.shelf_content,
            bg=card_bg,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=card_border,
            width=168,
            height=308,
            cursor="hand2",
        )
        card.pack_propagate(False)
        card.grid_propagate(False)
        self._shelf_cards[b_id] = card

        # Top Badge Bar (Faculty Color Accent & Desk Icon)
        cat_str = b.get("categories_str") or "Sonstiges"
        cats = [c.strip() for c in cat_str.split("|") if c.strip()]
        first_cat = b.get("primary_category") or (cats[0] if cats else "Sonstiges")
        _, accent_col = FACULTY_COLORS.get(first_cat, ("#161B22", "#58A6FF"))
        if len(cats) > 1:
            display_cat = f"{first_cat[:11]} +{len(cats)-1}"
        else:
            display_cat = (first_cat[:15] + "…") if len(first_cat) > 16 else first_cat

        top_pill = tk.Frame(card, bg=card_bg, height=22)
        top_pill.pack_propagate(False)
        top_pill.pack(fill=tk.X, padx=8, pady=(6, 2))

        dot = tk.Label(top_pill, text="●", font=("Segoe UI", 7), bg=card_bg, fg=accent_col)
        dot.pack(side=tk.LEFT)
        lbl_cat = tk.Label(top_pill, text=display_cat, font=("Segoe UI", 8, "bold"), bg=card_bg, fg=accent_col)
        lbl_cat.pack(side=tk.LEFT, padx=(3, 0))

        pct = b.get("reading_progress") or 0
        is_desk = bool(b.get("is_on_desk"))
        desk_text = f"📖 {pct}%" if (is_desk and pct > 0) else ("📖" if is_desk else "")
        lbl_desk = tk.Label(top_pill, text=desk_text, font=("Segoe UI", 8), bg=card_bg, fg="#58A6FF" if pct > 0 else COLOR_TEXT_MUTED)
        lbl_desk.pack(side=tk.RIGHT)

        # Fixed Cover Frame Container (Uniform 135x190)
        cover_frame = tk.Frame(
            card,
            bg="#12171F",
            width=135,
            height=190,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#30363D",
            cursor="hand2",
        )
        cover_frame.pack_propagate(False)
        cover_frame.pack(pady=(2, 6))

        # Cover Thumbnail Image (Instant cached/fallback + async thread hydration)
        cached_img = get_cached_cover(b_id)
        if cached_img:
            photo = ImageTk.PhotoImage(cached_img)
        else:
            photo = ImageTk.PhotoImage(generate_fallback_cover(b.get("title", ""), b.get("author", ""), first_cat))
            self._queue_async_cover_generation(b_id, b.get("file_path", ""), b.get("title", ""), b.get("author", ""), first_cat)

        self._photo_cache[b_id] = photo

        lbl_cover = tk.Label(cover_frame, image=photo, bg="#12171F", bd=0, cursor="hand2")
        lbl_cover.pack(fill=tk.BOTH, expand=True)
        self._shelf_cover_labels[b_id] = lbl_cover

        # Title Label (Fixed 2 lines allocated height)
        lbl_t = tk.Label(
            card,
            text=self._format_card_title(b.get("title", "")),
            font=("Segoe UI", 9, "bold"),
            bg=card_bg,
            fg=COLOR_TEXT_MAIN,
            height=2,
            wraplength=148,
            justify=tk.CENTER,
            cursor="hand2",
        )
        lbl_t.pack(fill=tk.X, padx=6)

        # Author Label (Fixed 1 line allocated height)
        lbl_a = tk.Label(
            card,
            text=self._format_card_author(b.get("author", "")),
            font=("Segoe UI", 8),
            bg=card_bg,
            fg=COLOR_TEXT_MUTED,
            height=1,
            wraplength=148,
            justify=tk.CENTER,
            cursor="hand2",
        )
        lbl_a.pack(fill=tk.X, padx=6, pady=(1, 4))

        # Reading Progress Indicator (3px bottom strip if active on desk)
        prog_bar_frame = tk.Frame(card, bg="#21262D", height=3)
        prog_bar_frame.pack_propagate(False)
        prog_bar_fill = tk.Frame(prog_bar_frame, bg="#3FB950" if pct >= 100 else "#1F6FEB", height=3)
        if is_desk and pct > 0:
            fill_w = max(4, int(168 * (pct / 100.0)))
            prog_bar_fill.place(x=0, y=0, width=fill_w, height=3)
            prog_bar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        card._prog_bar_frame = prog_bar_frame
        card._prog_bar_fill = prog_bar_fill

        # Store widget references for synchronous theming & content refresh
        card._themed_widgets = [card, top_pill, dot, lbl_cat, lbl_desk, lbl_t, lbl_a]
        card._lbl_t = lbl_t
        card._lbl_a = lbl_a
        card._lbl_cat = lbl_cat
        card._dot = dot
        card._lbl_desk = lbl_desk

        # Bind interactive events
        widgets_to_bind = [card, top_pill, dot, lbl_cat, lbl_desk, cover_frame, lbl_cover, lbl_t, lbl_a]
        for w in widgets_to_bind:
            w.bind("<Enter>", lambda e, bid=b_id: self._on_shelf_card_enter(bid))
            w.bind("<Leave>", lambda e, bid=b_id: self._on_shelf_card_leave(bid))
            w.bind("<Button-1>", lambda e, bid=b_id: self._on_shelf_card_click(bid))
            w.bind("<Double-Button-1>", lambda e, bid=b_id: self._on_shelf_card_double_click(bid))
            w.bind("<Button-3>", lambda e, bid=b_id: self._on_shelf_card_context_menu(e, bid))
            w.bind("<MouseWheel>", self._on_shelf_mousewheel)

        return card

    def _refresh_shelf_card_widget(self, card: tk.Frame, b: Dict[str, Any]) -> None:
        cat_str = b.get("categories_str") or "Sonstiges"
        cats = [c.strip() for c in cat_str.split("|") if c.strip()]
        first_cat = b.get("primary_category") or (cats[0] if cats else "Sonstiges")
        _, accent_col = FACULTY_COLORS.get(first_cat, ("#161B22", "#58A6FF"))
        if len(cats) > 1:
            display_cat = f"{first_cat[:11]} +{len(cats)-1}"
        else:
            display_cat = (first_cat[:15] + "…") if len(first_cat) > 16 else first_cat

        pct = b.get("reading_progress") or 0
        is_desk = bool(b.get("is_on_desk"))
        desk_text = f"📖 {pct}%" if (is_desk and pct > 0) else ("📖" if is_desk else "")

        if hasattr(card, "_lbl_cat"):
            card._lbl_cat.configure(text=display_cat, fg=accent_col)
        if hasattr(card, "_dot"):
            card._dot.configure(fg=accent_col)
        if hasattr(card, "_lbl_desk"):
            card._lbl_desk.configure(text=desk_text, fg="#58A6FF" if pct > 0 else COLOR_TEXT_MUTED)
        if hasattr(card, "_lbl_t"):
            card._lbl_t.configure(text=self._format_card_title(b.get("title", "")))
        if hasattr(card, "_lbl_a"):
            card._lbl_a.configure(text=self._format_card_author(b.get("author", "")))

        if hasattr(card, "_prog_bar_frame") and hasattr(card, "_prog_bar_fill"):
            if is_desk and pct > 0:
                fill_w = max(4, int(168 * (pct / 100.0)))
                card._prog_bar_fill.configure(bg="#3FB950" if pct >= 100 else "#1F6FEB")
                card._prog_bar_fill.place(x=0, y=0, width=fill_w, height=3)
                if not card._prog_bar_frame.winfo_ismapped():
                    card._prog_bar_frame.pack(side=tk.BOTTOM, fill=tk.X)
            else:
                card._prog_bar_frame.pack_forget()

    def _cancel_shelf_batch(self) -> None:
        if getattr(self, "_shelf_batch_job", None) is not None:
            try:
                self.after_cancel(self._shelf_batch_job)
            except Exception:
                pass
            self._shelf_batch_job = None

    def _render_shelf_grid(self) -> None:
        self._cancel_shelf_batch()

        c_width = self.shelf_canvas.winfo_width()
        if c_width <= 200:
            c_width = 1020
        card_slot_width = 184
        cols = max(1, min(8, c_width // card_slot_width))
        self._current_shelf_cols = cols
        spare = c_width - (cols * card_slot_width)
        left_pad = max(8, spare // 2)
        self._current_left_pad = left_pad

        self.shelf_canvas.coords(self.shelf_window, 0, 0)
        self.shelf_canvas.itemconfig(self.shelf_window, width=c_width)

        if not self._all_current_books:
            for cid in list(self._visible_shelf_card_ids):
                if cid in self._shelf_cards:
                    self._shelf_cards[cid].grid_remove()
            self._visible_shelf_card_ids.clear()
            self._shelf_render_index = 0
            if hasattr(self, "_shelf_empty_label") and self._shelf_empty_label:
                self._shelf_empty_label.pack(expand=True, pady=60)
            self.shelf_canvas.configure(scrollregion=(0, 0, 0, 0))
            return

        if hasattr(self, "_shelf_empty_label") and self._shelf_empty_label:
            self._shelf_empty_label.pack_forget()

        # Hide cards that are no longer part of the filtered book set
        valid_ids = {b["id"] for b in self._all_current_books}
        to_hide = self._visible_shelf_card_ids - valid_ids
        for cid in to_hide:
            if cid in self._shelf_cards:
                self._shelf_cards[cid].grid_remove()
        self._visible_shelf_card_ids -= to_hide

        # Set realistic scroll height instantly so scrollbar is immediately correct
        total_rows = (len(self._all_current_books) + cols - 1) // cols
        est_height = max(600, total_rows * 326 + 30)
        self.shelf_canvas.configure(scrollregion=(0, 0, c_width, est_height))
        self.shelf_canvas.yview_moveto(0)

        # Render first visible batch immediately (24 cards = instant startup)
        self._shelf_render_index = 0
        self._render_next_shelf_batch(batch_size=24)

    def _render_next_shelf_batch(self, batch_size: int = 24) -> None:
        self._cancel_shelf_batch()
        if getattr(self, "catalog_view_mode", "") != "shelf" or not self._all_current_books:
            return

        cols = getattr(self, "_current_shelf_cols", 4)
        left_pad = getattr(self, "_current_left_pad", 8)
        start_idx = getattr(self, "_shelf_render_index", 0)
        total_books = len(self._all_current_books)

        if start_idx >= total_books:
            self.shelf_canvas.configure(scrollregion=self.shelf_canvas.bbox("all"))
            return

        end_idx = min(start_idx + batch_size, total_books)
        for idx in range(start_idx, end_idx):
            b = self._all_current_books[idx]
            b_id = b["id"]
            self._visible_shelf_card_ids.add(b_id)
            r, c = divmod(idx, cols)

            if b_id not in self._shelf_cards:
                self._create_shelf_card_widget(b)
            else:
                self._refresh_shelf_card_widget(self._shelf_cards[b_id], b)

            pad_x = (left_pad, 8) if c == 0 else 8
            self._shelf_cards[b_id].grid(row=r, column=c, padx=pad_x, pady=9, sticky="n")

        self._shelf_render_index = end_idx

        # Smooth progressive background hydration for remaining cards
        if self._shelf_render_index < total_books:
            self._shelf_batch_job = self.after(15, lambda: self._render_next_shelf_batch(batch_size=28))
        else:
            self.shelf_canvas.configure(scrollregion=self.shelf_canvas.bbox("all"))

    def _queue_async_cover_generation(self, book_id: str, file_path: str, title: str, author: str, category: str) -> None:
        if book_id not in self._queued_cover_ids:
            self._queued_cover_ids.add(book_id)
            self._cover_queue.put((book_id, file_path, title, author, category))

    def _start_cover_worker(self) -> None:
        def worker():
            while not getattr(self, "_is_shutting_down", False):
                try:
                    item = self._cover_queue.get(timeout=0.4)
                except queue.Empty:
                    continue
                if item is None:
                    break
                book_id, file_path, title, author, category = item
                try:
                    img = extract_and_cache_cover(book_id, file_path, title, author, category)
                    if img:
                        def update(bid=book_id, im=img):
                            if bid in self._shelf_cover_labels:
                                lbl = self._shelf_cover_labels[bid]
                                try:
                                    if lbl.winfo_exists():
                                        new_photo = ImageTk.PhotoImage(im)
                                        self._photo_cache[bid] = new_photo
                                        lbl.configure(image=new_photo)
                                except Exception:
                                    pass
                        self._dispatch(update)
                except Exception:
                    pass
                finally:
                    self._cover_queue.task_done()

        threading.Thread(target=worker, daemon=True).start()

    def _on_close(self) -> None:
        try:
            self.withdraw()
        except Exception:
            pass
        self._cancel_shelf_batch()
        self._is_shutting_down = True
        self.stop_event.set()
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)



    def _update_shelf_card_colors(self, book_id: str, is_hover: bool = False) -> None:
        if book_id not in self._shelf_cards:
            return
        card = self._shelf_cards[book_id]
        is_sel = (self.selected_book_id == book_id)

        if is_sel:
            bg_col = "#1C2738"
            border_col = "#58A6FF"
        elif is_hover:
            bg_col = "#21262D"
            border_col = "#58A6FF"
        else:
            bg_col = "#161B22"
            border_col = "#30363D"

        card.configure(bg=bg_col, highlightbackground=border_col)
        if hasattr(card, "_themed_widgets"):
            for w in card._themed_widgets:
                try:
                    if w.winfo_exists():
                        w.configure(bg=bg_col)
                except Exception:
                    pass

    def _on_shelf_card_enter(self, book_id: str) -> None:
        if self.selected_book_id != book_id:
            self._update_shelf_card_colors(book_id, is_hover=True)

    def _on_shelf_card_leave(self, book_id: str) -> None:
        if self.selected_book_id != book_id:
            self._update_shelf_card_colors(book_id, is_hover=False)

    def _on_shelf_card_click(self, book_id: str) -> None:
        old_id = self.selected_book_id
        self.selected_book_id = book_id
        if old_id and old_id in self._shelf_cards:
            self._update_shelf_card_colors(old_id, is_hover=False)
        if book_id in self._shelf_cards:
            self._update_shelf_card_colors(book_id, is_hover=False)
        if self.tree_books.exists(book_id):
            self.tree_books.selection_set(book_id)

    def _on_shelf_card_double_click(self, book_id: str) -> None:
        self._launch_book_by_id(book_id)

    def _build_book_context_menu(self, book_id: str) -> tk.Menu:
        menu = tk.Menu(self, tearoff=0, bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, activebackground=COLOR_PRIMARY, activeforeground="#FFFFFF")
        menu.add_command(label="🔍 Quick-Look & Details (Leertaste)", command=self._open_quick_look)
        menu.add_command(label="📂 PDF direkt öffnen", command=self._open_selected_book)
        menu.add_command(label="📁 Im Explorer anzeigen", command=self._show_selected_in_explorer)
        menu.add_command(label="📖 Auf Schreibtisch / entfernen", command=self._toggle_selected_desk)
        menu.add_separator()

        # Zitationen Submenu
        cite_sub = tk.Menu(menu, tearoff=0, bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, activebackground=COLOR_PRIMARY, activeforeground="#FFFFFF")
        cite_sub.add_command(label="📋 Als BibTeX kopieren (LaTeX)", command=lambda: self._copy_selected_citation("bibtex"))
        cite_sub.add_command(label="📋 Als APA 7 kopieren", command=lambda: self._copy_selected_citation("apa"))
        cite_sub.add_command(label="📋 Als Markdown-Link kopieren", command=lambda: self._copy_selected_citation("md"))
        menu.add_cascade(label="🎓 Zitat kopieren", menu=cite_sub)

        # Lesefortschritt Submenu
        prog_sub = tk.Menu(menu, tearoff=0, bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, activebackground=COLOR_PRIMARY, activeforeground="#FFFFFF")
        for p in (25, 50, 75, 100):
            prog_sub.add_command(label=f"{p}% ({'Abgeschlossen' if p == 100 else 'Fortschritt'})", command=lambda target_p=p: self._set_selected_progress_pct(target_p))
        menu.add_cascade(label="📊 Lesefortschritt setzen", menu=prog_sub)

        # Fachbereich Submenu (Multi-Zuordnung & Hauptfach)
        cat_sub = tk.Menu(menu, tearoff=0, bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, activebackground=COLOR_PRIMARY, activeforeground="#FFFFFF")
        from ai.categories import STANDARD_CATEGORIES
        from core.library_db import get_book_categories

        assigned_cat_list = get_book_categories(book_id)
        assigned_dict = {c["category"]: bool(c.get("is_primary")) for c in assigned_cat_list}
        primary_cat = next((c["category"] for c in assigned_cat_list if c.get("is_primary")), None)

        for cat in STANDARD_CATEGORIES:
            if cat in assigned_dict:
                is_p = assigned_dict[cat]
                prefix = "✓ ⭐ " if is_p else "✓ "
                suffix = " (Hauptfach)" if is_p else ""
                lbl = f"{prefix}{cat}{suffix}"
            else:
                lbl = f"    {cat}"
            cat_sub.add_command(
                label=lbl,
                command=lambda c=cat, b_id=book_id: self._toggle_category(b_id, c)
            )

        if assigned_cat_list:
            cat_sub.add_separator()
            prim_sub = tk.Menu(cat_sub, tearoff=0, bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, activebackground=COLOR_PRIMARY, activeforeground="#FFFFFF")
            for c_info in assigned_cat_list:
                c_name = c_info["category"]
                is_p = bool(c_info.get("is_primary"))
                p_lbl = f"⭐ {c_name} (Aktiv)" if is_p else f"    {c_name}"
                prim_sub.add_command(
                    label=p_lbl,
                    command=lambda c=c_name, b_id=book_id: self._set_primary_cat(b_id, c)
                )
            cat_sub.add_cascade(label="⭐ Hauptfach festlegen", menu=prim_sub)

        menu.add_cascade(label="🏷️ Fachbereiche (Multi-Auswahl)", menu=cat_sub)
        menu.add_separator()
        menu.add_command(label="✏️ Titel, Autor & Fächer bearbeiten...", command=self._edit_selected_book)
        return menu

    def _on_shelf_card_context_menu(self, event, book_id: str) -> None:
        self._on_shelf_card_click(book_id)
        menu = self._build_book_context_menu(book_id)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_tree_select(self, event=None) -> None:
        sel = self.tree_books.selection()
        if sel:
            self.selected_book_id = sel[0]

    def _load_library_data(self) -> None:
        self._master_books = get_all_books()
        if not self.selected_book_id and self._master_books:
            self.selected_book_id = self._master_books[0]["id"]

        cat_counts = get_category_counts()
        total_b = sum(c[1] for c in cat_counts)
        self.lbl_stats.configure(text=f"● {total_b} Fachbücher\n● SQLite Data-Lake aktiv")
        if hasattr(self, "lbl_badge_total"):
            self.lbl_badge_total.configure(text=f"{total_b} Fachbücher")

        self._render_category_chips(cat_counts)
        self._apply_catalog_filter()

    def _get_filtered_books(self) -> List[Dict[str, Any]]:
        books = self._master_books
        if self.current_category_filter != "Alle":
            target = self.current_category_filter
            books = [b for b in books if target in (b.get("categories_str") or "")]
        if self.search_term:
            q = self.search_term.lower()
            books = [
                b for b in books
                if q in b["title"].lower()
                or q in b["author"].lower()
                or q in (b.get("categories_str") or "").lower()
            ]
        return books

    def _apply_catalog_filter(self) -> None:
        books = self._get_filtered_books()
        self._all_current_books = books

        total_b = len(self._master_books)
        if hasattr(self, "lbl_table_count"):
            if self.search_term or self.current_category_filter != "Alle":
                self.lbl_table_count.configure(text=f"{len(books)} von {total_b} Büchern")
            else:
                self.lbl_table_count.configure(text=f"{len(books)} Bücher")

        if self.catalog_view_mode == "shelf":
            self._render_shelf_grid()
            self._table_dirty = True
        else:
            self._populate_table_view()

    def _populate_table_view(self) -> None:
        children = self.tree_books.get_children()
        if children:
            self.tree_books.delete(*children)

        for idx, b in enumerate(self._all_current_books):
            desk_icon = "📖" if b.get("is_on_desk") else "—"
            ed_str = f"{b.get('edition', 1)}. Aufl."
            pages_str = f"{b.get('page_count')} S." if b.get("page_count") else "?"
            cats = b.get("categories_str") or "Sonstiges"
            row_tag = "even" if idx % 2 == 0 else "odd"

            self.tree_books.insert(
                "",
                "end",
                iid=b["id"],
                values=(desk_icon, b["title"], b["author"], cats, ed_str, pages_str),
                tags=(row_tag,)
            )
        self._table_dirty = False

    def _render_category_chips(self, cat_counts: List[Tuple[str, int]]) -> None:
        for widget in self.chips_frame.winfo_children():
            widget.destroy()
        self._chip_buttons.clear()

        # All Chip
        total_cnt = sum(c[1] for c in cat_counts)
        self._create_chip("Alle", total_cnt, is_active=(self.current_category_filter == "Alle"))

        # Top 6 Categories
        top_cats = cat_counts[:6]
        for cat, cnt in top_cats:
            self._create_chip(cat, cnt, is_active=(self.current_category_filter == cat))

        # Dropdown button for remaining categories
        if len(cat_counts) > 6:
            is_dropdown_active = self.current_category_filter not in ["Alle"] + [c[0] for c in top_cats]
            btn_more = tk.Menubutton(
                self.chips_frame,
                text="➕ Weitere Fachbereiche ▾",
                font=("Segoe UI", 9, "bold" if is_dropdown_active else "normal"),
                bg="#1F6FEB" if is_dropdown_active else COLOR_CARD,
                fg="#FFFFFF" if is_dropdown_active else COLOR_TEXT_MUTED,
                activebackground=COLOR_HOVER,
                activeforeground=COLOR_TEXT_MAIN,
                bd=1,
                relief="solid",
                padx=10,
                pady=4,
                cursor="hand2",
            )
            more_menu = tk.Menu(btn_more, tearoff=0, bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, activebackground=COLOR_PRIMARY, activeforeground="#FFFFFF")
            for cat, cnt in cat_counts[6:]:
                more_menu.add_command(
                    label=f"{cat} ({cnt})",
                    command=lambda c=cat: self._set_category_filter(c)
                )
            btn_more["menu"] = more_menu
            btn_more.pack(side=tk.LEFT, padx=(0, 6))
            self._btn_more_menu = btn_more
        else:
            self._btn_more_menu = None

    def _create_chip(self, category: str, count: int, is_active: bool) -> None:
        bg = "#1F6FEB" if is_active else COLOR_CARD
        fg = "#FFFFFF" if is_active else COLOR_TEXT_MAIN
        txt = f"{category}  •  {count}" if count > 0 else category

        btn = tk.Button(
            self.chips_frame,
            text=txt,
            font=("Segoe UI", 9, "bold" if is_active else "normal"),
            bg=bg,
            fg=fg,
            activebackground=COLOR_HOVER,
            activeforeground=COLOR_TEXT_MAIN,
            bd=1,
            relief="solid",
            padx=12,
            pady=4,
            cursor="hand2",
            command=lambda c=category: self._set_category_filter(c),
        )
        btn.pack(side=tk.LEFT, padx=(0, 6))
        self._chip_buttons[category] = btn

    def _update_chip_styles(self) -> None:
        for cat, btn in self._chip_buttons.items():
            is_active = (self.current_category_filter == cat)
            btn.configure(
                bg="#1F6FEB" if is_active else COLOR_CARD,
                fg="#FFFFFF" if is_active else COLOR_TEXT_MAIN,
                font=("Segoe UI", 9, "bold" if is_active else "normal")
            )
        if self._btn_more_menu:
            top_cat_names = list(self._chip_buttons.keys())
            is_dropdown_active = self.current_category_filter not in top_cat_names
            self._btn_more_menu.configure(
                bg="#1F6FEB" if is_dropdown_active else COLOR_CARD,
                fg="#FFFFFF" if is_dropdown_active else COLOR_TEXT_MUTED,
                font=("Segoe UI", 9, "bold" if is_dropdown_active else "normal")
            )

    def _set_category_filter(self, category: str) -> None:
        if self.current_category_filter == category:
            return
        self.current_category_filter = category
        self._update_chip_styles()
        self._apply_catalog_filter()

    def _on_search_change(self, event=None) -> None:
        if getattr(self, "_search_after_id", None):
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(80, self._perform_search)

    def _perform_search(self) -> None:
        self._search_after_id = None
        new_term = self.ent_search.get().strip()
        if new_term != self.search_term:
            self.search_term = new_term
            self._apply_catalog_filter()

    # -----------------------------------------------------------------
    # DESK ACTIONS
    # -----------------------------------------------------------------
    def _load_desk_data(self) -> None:
        children = self.tree_desk.get_children()
        if children:
            self.tree_desk.delete(*children)

        items = get_desk_books()
        for d in items:
            prog = f"{d.get('progress_pct', 0)}%"
            p_curr = d.get('current_page', 0)
            p_tot = d.get('total_pages', 0)
            pages = f"S. {p_curr} / {p_tot}" if p_tot else f"S. {p_curr}"
            n_count = f"📝 {d.get('notes_count', 0)}"

            self.tree_desk.insert(
                "",
                "end",
                iid=d["id"],
                values=(d["title"], d["author"], prog, pages, n_count)
            )

    def _on_desk_select(self, event=None) -> None:
        sel = self.tree_desk.selection()
        if not sel:
            return
        book_id = sel[0]
        # Fetch book details
        conn = self._get_db()
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if row:
            self.active_desk_book_id = book_id
            self.lbl_active_book_title.configure(text=f"{row['title']}\n({row['author']})")

            cur_p = conn.execute("SELECT current_page FROM desk_items WHERE book_id = ?", (book_id,)).fetchone()
            self.ent_current_page.delete(0, tk.END)
            if cur_p:
                self.ent_current_page.insert(0, str(cur_p["current_page"]))

            # Load notes
            notes = get_book_notes(book_id)
            self.txt_note.delete("1.0", tk.END)
            if notes:
                compiled = "\n\n---\n\n".join(f"[{time.strftime('%d.%m.%Y', time.localtime(n['created_at']))}] {n['note_text']}" for n in notes)
                self.txt_note.insert("1.0", compiled)

    def _save_page_progress(self) -> None:
        if not hasattr(self, "active_desk_book_id") or not self.active_desk_book_id:
            return
        try:
            p = int(self.ent_current_page.get().strip())
            if p < 1:
                p = 1
            update_reading_progress(self.active_desk_book_id, p)
            self._load_desk_data()
            if hasattr(self, "lbl_desk_page_feedback"):
                self.lbl_desk_page_feedback.configure(text=f"✓ Seite {p} gespeichert!", fg="#3FB950")
                self.after(3000, lambda: self.lbl_desk_page_feedback.configure(text=""))
            self._log(f"[Pult] Gespeicherte Leseseite auf {p} gesetzt (öffnet in Edge)")
        except ValueError:
            pass

    def _add_current_note(self) -> None:
        if not hasattr(self, "active_desk_book_id") or not self.active_desk_book_id:
            return
        txt = self.txt_note.get("1.0", tk.END).strip()
        if txt:
            try:
                p = int(self.ent_current_page.get().strip())
            except ValueError:
                p = None
            add_book_note(self.active_desk_book_id, txt, p)
            self._load_desk_data()
            messagebox.showinfo("Gespeichert", "Notiz wurde erfolgreich am Buch hinterlegt.")

    def _open_selected_desk_pdf(self) -> None:
        sel = self.tree_desk.selection()
        if not sel:
            return
        self._launch_book_by_id(sel[0])

    def _remove_from_desk(self) -> None:
        sel = self.tree_desk.selection()
        if not sel:
            return
        book_id = sel[0]
        toggle_desk_item(book_id)
        self.tree_desk.delete(book_id)
        self._library_dirty = True
        if getattr(self, "active_desk_book_id", None) == book_id:
            self.active_desk_book_id = None
            self.lbl_active_book_title.configure(text="Wähle ein Buch aus...")
            self.ent_current_page.delete(0, tk.END)
            self.txt_note.delete("1.0", tk.END)

    def _on_desk_double_click(self, event=None) -> None:
        sel = self.tree_desk.selection()
        if sel:
            self._launch_book_by_id(sel[0])

    # -----------------------------------------------------------------
    # RADAR ACTIONS
    # -----------------------------------------------------------------
    # RADAR ACTIONS (EDITION SENTINEL & DUPLICATE FINDER)
    # -----------------------------------------------------------------
    def _set_radar_mode(self, mode: str) -> None:
        self.radar_mode = mode
        if mode == "editions":
            self.lbl_radar_title.configure(text="⚠️ Auflagen-Radar (Literatur-Aktualität)")
            self.btn_mode_editions.configure(bg="#1F6FEB", fg="#FFFFFF", bd=0)
            self.btn_mode_duplicates.configure(bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, bd=1)
            self.btn_radar_action.configure(text="🔄 Auflagen online abgleichen", fg=COLOR_WARNING)
        else:
            self.lbl_radar_title.configure(text="👯 Dubletten-Finder (Redundanzen bereinigen)")
            self.btn_mode_duplicates.configure(bg="#1F6FEB", fg="#FFFFFF", bd=0)
            self.btn_mode_editions.configure(bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, bd=1)
            self.btn_radar_action.configure(text="🔍 Dubletten jetzt suchen", fg="#58A6FF")

        self._configure_radar_tree_columns()
        self._load_radar_data()

    def _configure_radar_tree_columns(self) -> None:
        if getattr(self, "radar_mode", "editions") == "editions":
            self.tree_radar.heading("title", text="Buchtitel", anchor="w")
            self.tree_radar.heading("author", text="Autor", anchor="w")
            self.tree_radar.heading("current_ed", text="Deine Auflage", anchor="center")
            self.tree_radar.heading("latest_ed", text="Verfügbare Neuauflage", anchor="center")
            self.tree_radar.heading("diff", text="Status", anchor="center")
            self.tree_radar.heading("action", text="Quelle", anchor="center")

            self.tree_radar.column("title", width=380, anchor="w")
            self.tree_radar.column("author", width=200, anchor="w")
            self.tree_radar.column("current_ed", width=120, anchor="center")
            self.tree_radar.column("latest_ed", width=180, anchor="center")
            self.tree_radar.column("diff", width=120, anchor="center")
            self.tree_radar.column("action", width=140, anchor="center")
        else:
            self.tree_radar.heading("title", text="Buchtitel / Dublette", anchor="w")
            self.tree_radar.heading("author", text="Autor", anchor="w")
            self.tree_radar.heading("current_ed", text="Auflage / Seiten", anchor="center")
            self.tree_radar.heading("latest_ed", text="Dubletten-Erkennung", anchor="center")
            self.tree_radar.heading("diff", text="Dateigröße", anchor="center")
            self.tree_radar.heading("action", text="Speicherort / Pfad", anchor="w")

            self.tree_radar.column("title", width=340, anchor="w")
            self.tree_radar.column("author", width=170, anchor="w")
            self.tree_radar.column("current_ed", width=120, anchor="center")
            self.tree_radar.column("latest_ed", width=200, anchor="center")
            self.tree_radar.column("diff", width=100, anchor="center")
            self.tree_radar.column("action", width=250, anchor="w")

    def _load_radar_data(self) -> None:
        children = self.tree_radar.get_children()
        if children:
            self.tree_radar.delete(*children)

        if getattr(self, "radar_mode", "editions") == "editions":
            alerts = get_edition_alerts()
            for a in alerts:
                c_ed = f"{a['current_edition']}. Auflage"
                l_ed = f"{a['latest_edition']}. Auflage ({a.get('latest_year') or 'Neu'})"
                diff = f"⚠️ +{a['latest_edition'] - a['current_edition']} Auflagen"

                self.tree_radar.insert(
                    "",
                    "end",
                    iid=a["book_id"],
                    values=(a["title"], a["author"], c_ed, l_ed, diff, a.get("source", "DNB")),
                )
        else:
            from core.duplicate_finder import find_library_duplicates
            dupes = find_library_duplicates()
            idx = 0
            for group in dupes:
                reason = group["reason"]
                for b in group["books"]:
                    size_mb = f"{b.get('file_size', 0) / (1024*1024):.1f} MB"
                    ed_str = f"{b.get('edition', 1)}. Aufl. ({b.get('page_count', '?')} S.)"
                    item_id = f"dupe_{idx}_{b['id']}"
                    idx += 1
                    self.tree_radar.insert(
                        "",
                        "end",
                        iid=item_id,
                        values=(b["title"], b["author"], ed_str, reason, size_mb, b.get("file_path", "")),
                    )

    def _on_radar_action_clicked(self) -> None:
        if getattr(self, "radar_mode", "editions") == "editions":
            self._run_online_edition_check()
        else:
            self._load_radar_data()
            self._log("[Dubletten] Dubletten-Scan abgeschlossen.")

    def _on_radar_double_click(self, event=None) -> None:
        sel = self.tree_radar.selection()
        if not sel:
            return
        item_id = sel[0]
        actual_id = item_id.split("_", 2)[-1] if item_id.startswith("dupe_") else item_id
        self._launch_book_by_id(actual_id)

    def _run_online_edition_check(self) -> None:
        def worker():
            from ai.edition_checker import check_for_newer_edition
            self._log("[Radar] Starte Online-Auflagen-Check gegen Google Books & DNB...")
            books = get_all_books()
            found_cnt = 0
            for b in books[:30]:
                res = check_for_newer_edition(b)
                if res:
                    found_cnt += 1
                    self._log(f"[Radar ⚠️] Neuere Auflage für '{b['title'][:30]}': {res['latest_edition']}. Aufl.!")
            self._log(f"[Radar] Prüfung abgeschlossen: {found_cnt} neuere Auflagen entdeckt.")
            self._radar_dirty = True
            if self.active_tab == "radar":
                self._dispatch(self._load_radar_data)

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------
    # ACTIONS: OPEN & QUICK-LOOK & CITATIONS
    # -----------------------------------------------------------------
    def _on_space_key(self, event=None) -> None:
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text)):
            return
        self._open_quick_look()

    def _open_quick_look(self, event=None) -> None:
        b_id = self._get_active_selection_id()
        if not b_id:
            return
        book = next((b for b in self._master_books if b["id"] == b_id), None)
        if not book:
            conn = self._get_db()
            row = conn.execute("SELECT * FROM books WHERE id = ?", (b_id,)).fetchone()
            if row:
                book = dict(row)
        if book:
            # Query fresh desk status & current_page from DB
            conn = self._get_db()
            desk_r = conn.execute("SELECT current_page, progress_pct FROM desk_items WHERE book_id = ?", (b_id,)).fetchone()
            if desk_r:
                book["is_on_desk"] = 1
                book["current_page"] = desk_r["current_page"]
                book["reading_progress"] = desk_r["progress_pct"]
            else:
                book["is_on_desk"] = 0

            prev_ql = getattr(self, "_active_quick_look", None)
            from ui.quick_look import QuickLookDialog
            new_ql = QuickLookDialog(self, book, on_change=self._load_library_data)
            self._active_quick_look = new_ql
            if prev_ql and prev_ql != new_ql and prev_ql.winfo_exists():
                try:
                    prev_ql.destroy()
                except Exception:
                    pass


    def _show_selected_in_explorer(self) -> None:
        b_id = self._get_active_selection_id()
        if not b_id:
            return
        book = next((b for b in self._master_books if b["id"] == b_id), None)
        if book and book.get("file_path") and os.path.exists(book["file_path"]):
            subprocess.run(["explorer", "/select,", os.path.normpath(book["file_path"])])
        else:
            messagebox.showwarning("Hinweis", "Datei nicht im Dateisystem gefunden.")

    def _copy_selected_citation(self, fmt: str) -> None:
        b_id = self._get_active_selection_id()
        if not b_id:
            return
        book = next((b for b in self._master_books if b["id"] == b_id), None)
        if not book:
            return
        from core.citations import generate_bibtex, generate_apa, generate_markdown_link
        if fmt == "bibtex":
            text = generate_bibtex(book)
            name = "BibTeX"
        elif fmt == "apa":
            text = generate_apa(book)
            name = "APA 7"
        else:
            text = generate_markdown_link(book)
            name = "Markdown-Link"
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._log(f"[Zitat] {name} in Zwischenablage kopiert für '{book.get('title', '')}'")

    def _set_selected_progress_pct(self, target_pct: int) -> None:
        b_id = self._get_active_selection_id()
        if not b_id:
            return
        book = next((b for b in self._master_books if b["id"] == b_id), None)
        if not book:
            return
        tot_pages = book.get("page_count") or 100
        page_num = int(tot_pages * (target_pct / 100.0))
        if not book.get("is_on_desk"):
            toggle_desk_item(b_id)
        update_reading_progress(b_id, page_num)
        self._load_library_data()
        self._log(f"[Pult] Lesefortschritt auf {target_pct}% gesetzt ({page_num}/{tot_pages} S.)")

    def _on_book_double_click(self, event=None) -> None:
        sel = self.tree_books.selection()
        if sel:
            self._launch_book_by_id(sel[0])

    def _on_tree_context_menu(self, event) -> None:
        iid = self.tree_books.identify_row(event.y)
        if not iid:
            return
        self.tree_books.selection_set(iid)
        self.selected_book_id = iid
        menu = self._build_book_context_menu(iid)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _toggle_category(self, book_id: str, category: str) -> None:
        from core.library_db import toggle_book_category
        from core.memory import learn_user_correction

        is_now_assigned = toggle_book_category(book_id, category)
        book = next((b for b in self._master_books if b["id"] == book_id), None)
        if book and is_now_assigned and book.get("filename"):
            learn_user_correction(book["filename"], category)

        self._load_library_data()
        status = "hinzugefügt zu" if is_now_assigned else "entfernt aus"
        self._log(f"[Katalog] Fachbereich '{category}' {status} '{book['title'] if book else book_id}'.")

    def _set_primary_cat(self, book_id: str, category: str) -> None:
        from core.library_db import set_primary_category
        set_primary_category(book_id, category)
        self._load_library_data()
        book = next((b for b in self._master_books if b["id"] == book_id), None)
        self._log(f"[Katalog] Hauptfach für '{book['title'] if book else book_id}' ist nun '{category}'.")

    def _edit_selected_book(self) -> None:
        book_id = self._get_active_selection_id()
        if not book_id:
            return
        conn = self._get_db()
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            return

        from ai.categories import STANDARD_CATEGORIES
        from core.library_db import get_book_categories, update_book_metadata
        from core.memory import learn_user_correction

        assigned_cats_list = get_book_categories(book_id)
        assigned_names = {c["category"] for c in assigned_cats_list}
        primary_cat = next((c["category"] for c in assigned_cats_list if c.get("is_primary")), (row["categories_str"] or "Sonstiges"))

        dialog = tk.Toplevel(self)
        dialog.title("Metadaten & Fachbereiche bearbeiten")
        dialog.geometry("580x530")
        dialog.minsize(500, 480)
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self)
        dialog.grab_set()

        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 290
        y = self.winfo_y() + (self.winfo_height() // 2) - 265
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")

        pad_f = tk.Frame(dialog, bg=COLOR_CARD, padx=22, pady=18)
        pad_f.pack(fill=tk.BOTH, expand=True)

        tk.Label(pad_f, text="Buch-Metadaten & Zuordnung bearbeiten", font=("Segoe UI", 13, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0, 12))

        # Title Field
        tk.Label(pad_f, text="Titel:", font=("Segoe UI", 9, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED).pack(anchor="w")
        ent_title = tk.Entry(pad_f, font=("Segoe UI", 10), bg=COLOR_BG, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief="solid")
        ent_title.pack(fill=tk.X, pady=(2, 10), ipady=3)
        ent_title.insert(0, row["title"] or "")

        # Author Field
        tk.Label(pad_f, text="Autor(en):", font=("Segoe UI", 9, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED).pack(anchor="w")
        ent_author = tk.Entry(pad_f, font=("Segoe UI", 10), bg=COLOR_BG, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief="solid")
        ent_author.pack(fill=tk.X, pady=(2, 12), ipady=3)
        ent_author.insert(0, row["author"] or "")

        # Multi-Faculty Checkbox Grid
        tk.Label(pad_f, text="Fachbereiche (Mehrfachauswahl für interdisziplinäre Bücher):", font=("Segoe UI", 9, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        chk_frame = tk.Frame(pad_f, bg="#161B22", bd=1, relief="solid", padx=10, pady=8)
        chk_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        cat_vars = {}
        def on_cat_toggled():
            selected = [cat for cat, var in cat_vars.items() if var.get()]
            valid_vals = selected if selected else STANDARD_CATEGORIES
            cbo_primary["values"] = valid_vals
            if cbo_primary.get() not in valid_vals:
                cbo_primary.set(valid_vals[0])

        cols_per_row = 2
        for idx, cat in enumerate(STANDARD_CATEGORIES):
            is_active = (cat in assigned_names)
            var = tk.BooleanVar(value=is_active)
            cat_vars[cat] = var
            r, c = divmod(idx, cols_per_row)
            cb = tk.Checkbutton(
                chk_frame,
                text=cat,
                variable=var,
                bg="#161B22",
                fg=COLOR_TEXT_MAIN,
                selectcolor="#0D1117",
                activebackground="#161B22",
                activeforeground=COLOR_PRIMARY,
                font=("Segoe UI", 9),
                command=on_cat_toggled,
                cursor="hand2"
            )
            cb.grid(row=r, column=c, sticky="w", padx=10, pady=2)

        # Primary Faculty Selection
        tk.Label(pad_f, text="Primäres Hauptfach (Farbakzent & Regal-Einordnung):", font=("Segoe UI", 9, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED).pack(anchor="w", pady=(0, 3))
        init_primary_vals = [c for c in STANDARD_CATEGORIES if c in assigned_names] or STANDARD_CATEGORIES
        cbo_primary = ttk.Combobox(pad_f, values=init_primary_vals, state="readonly", font=("Segoe UI", 10))
        cbo_primary.pack(fill=tk.X, pady=(0, 16))
        if primary_cat in init_primary_vals:
            cbo_primary.set(primary_cat)
        else:
            cbo_primary.set(init_primary_vals[0])

        # Buttons
        btn_box = tk.Frame(pad_f, bg=COLOR_CARD)
        btn_box.pack(fill=tk.X)

        def close_dialog():
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

        def save():
            new_title = ent_title.get().strip()
            new_author = ent_author.get().strip()
            if not new_title:
                messagebox.showwarning("Hinweis", "Der Titel darf nicht leer sein.", parent=dialog)
                return

            selected_cats = [cat for cat, v in cat_vars.items() if v.get()]
            if not selected_cats:
                selected_cats = ["Sonstiges"]

            selected_primary = cbo_primary.get().strip()
            if selected_primary not in selected_cats:
                selected_primary = selected_cats[0]

            update_book_metadata(
                book_id,
                new_title,
                new_author,
                categories=selected_cats,
                primary_category=selected_primary
            )

            if row["filename"]:
                learn_user_correction(row["filename"], selected_primary)

            close_dialog()
            self._load_library_data()
            self._log(f"[Katalog] Metadaten & Fächer aktualisiert: '{new_title}' ({', '.join(selected_cats)})")

        btn_save = tk.Button(btn_box, text="💾 Speichern", font=("Segoe UI", 10, "bold"), bg=COLOR_PRIMARY, fg="#FFFFFF", bd=0, padx=16, pady=6, cursor="hand2", command=save)
        btn_save.pack(side=tk.RIGHT, padx=(8, 0))

        btn_cancel = tk.Button(btn_box, text="Abbrechen", font=("Segoe UI", 10), bg=COLOR_HOVER, fg=COLOR_TEXT_MUTED, bd=0, padx=14, pady=6, cursor="hand2", command=close_dialog)
        btn_cancel.pack(side=tk.RIGHT)

    def _change_book_category(self, book_id: str, new_category: str) -> None:
        from core.library_db import update_book_category, get_all_books
        from core.memory import learn_user_correction

        books = get_all_books()
        book = next((b for b in books if b["id"] == book_id), None)
        if book and book.get("filename"):
            learn_user_correction(book["filename"], new_category)

        update_book_category(book_id, new_category)
        self._load_library_data()
        self._log(f"[Katalog] Fachbereich für '{book['title'] if book else book_id}' auf '{new_category}' gesetzt.")

    def _trigger_auto_reclassify(self) -> None:
        from core.library_db import optimize_library_catalog

        # Non-blocking progress modal window
        dlg = tk.Toplevel(self)
        dlg.title("Katalog & Titel-Optimierung")
        dlg.geometry("520x220")
        dlg.resizable(False, False)
        dlg.configure(bg=COLOR_BG)
        dlg.transient(self)
        dlg.lift()
        dlg.focus_force()

        # Center on parent
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 260
        y = self.winfo_y() + (self.winfo_height() // 2) - 110
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

        lbl_header = tk.Label(
            dlg,
            text="⚡ Katalog & Metadaten werden optimiert...",
            font=("Segoe UI", 12, "bold"),
            bg=COLOR_BG,
            fg="#F0F6FC",
        )
        lbl_header.pack(pady=(18, 8), padx=20, anchor="w")

        lbl_status = tk.Label(
            dlg,
            text="Initialisiere Prüfung...",
            font=("Segoe UI", 9),
            bg=COLOR_BG,
            fg="#8B949E",
        )
        lbl_status.pack(pady=(0, 12), padx=20, anchor="w")

        prog_bar = ttk.Progressbar(dlg, mode="determinate", maximum=100)
        prog_bar.pack(fill=tk.X, padx=20, pady=(0, 16))

        stop_evt = threading.Event()

        def on_cancel():
            stop_evt.set()
            lbl_status.configure(text="Abbruch wird durchgeführt...", fg="#F85149")
            btn_cancel.configure(state=tk.DISABLED)

        dlg.protocol("WM_DELETE_WINDOW", on_cancel)

        btn_cancel = tk.Button(
            dlg,
            text="Abbrechen",
            font=("Segoe UI", 9),
            bg="#21262D",
            fg="#C9D1D9",
            activebackground="#30363D",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            padx=14,
            pady=5,
            cursor="hand2",
            command=on_cancel,
        )
        btn_cancel.pack(side=tk.RIGHT, padx=20, pady=(0, 16))

        def _bg_task():
            def _progress_cb(pct: int, total: int, text: str):
                self.after(0, lambda: _update_ui(pct, text))

            try:
                stats = optimize_library_catalog(progress_callback=_progress_cb, stop_event=stop_evt)
            except Exception as e:
                stats = {"error": str(e)}

            self.after(0, lambda: _on_complete(stats))

        def _update_ui(pct: int, text: str):
            if dlg.winfo_exists():
                prog_bar["value"] = pct
                lbl_status.configure(text=text)

        def _on_complete(stats: dict):
            if dlg.winfo_exists():
                try:
                    dlg.grab_release()
                except Exception:
                    pass
                dlg.destroy()

            try:
                self.lift()
                self.focus_force()
            except Exception:
                pass

            self._load_library_data()

            if "error" in stats:
                messagebox.showerror("Fehler", f"Fehler bei der Optimierung:\n{stats['error']}", parent=self)
                return

            if stop_evt.is_set():
                messagebox.showinfo("Abgebrochen", "Die Katalog-Optimierung wurde vorzeitig beendet.", parent=self)
                return

            parts = []
            if stats.get("titles", 0) > 0:
                parts.append(f"• {stats['titles']} Titel & Autoren bereinigt.")
            if stats.get("categories", 0) > 0:
                parts.append(f"• {stats['categories']} Fachbereiche präzisiert.")
            if stats.get("isbns", 0) > 0:
                parts.append(f"• {stats['isbns']} offizielle ISBNs extrahiert.")
            if stats.get("years", 0) > 0:
                parts.append(f"• {stats['years']} Erscheinungsjahre ermittelt.")

            if parts:
                msg = "Erfolgreich optimiert:\n\n" + "\n".join(parts)
            else:
                msg = "Katalog ist bereits optimal: Alle Titel, Fachbereiche, ISBNs und Erscheinungsjahre sind vollständig erfasst."
            messagebox.showinfo("Katalog & Titel-Optimierung", msg, parent=self)

        threading.Thread(target=_bg_task, daemon=True).start()


    def _open_export_dialog(self) -> None:
        """Modal dialog to export library citations and lists in BibTeX, RIS, or CSV format."""
        dlg = tk.Toplevel(self)
        dlg.title("Bibliothek exportieren")
        dlg.geometry("500x380")
        dlg.resizable(False, False)
        dlg.configure(bg=COLOR_CARD)
        dlg.transient(self)
        dlg.lift()
        dlg.focus_force()

        # Center on parent
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 250
        y = self.winfo_y() + (self.winfo_height() // 2) - 190
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

        pad = tk.Frame(dlg, bg=COLOR_CARD, padx=22, pady=18)
        pad.pack(fill=tk.BOTH, expand=True)

        tk.Label(pad, text="📚 Literatur & Bibliothek exportieren", font=("Segoe UI", 13, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0, 14))

        # Scope Selection
        tk.Label(pad, text="Umfang:", font=("Segoe UI", 9, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        scope_var = tk.StringVar(value="all")

        total_cnt = len(self._master_books)
        curr_cnt = len(self._all_current_books)

        rb_all = tk.Radiobutton(pad, text=f"Gesamte Bibliothek ({total_cnt} Bücher)", variable=scope_var, value="all", bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, selectcolor="#0D1117", activebackground=COLOR_CARD, activeforeground=COLOR_PRIMARY, font=("Segoe UI", 9))
        rb_all.pack(anchor="w", padx=6, pady=2)

        rb_filter = tk.Radiobutton(pad, text=f"Aktuelle Ansicht / Filterung ({curr_cnt} Bücher)", variable=scope_var, value="filtered", bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, selectcolor="#0D1117", activebackground=COLOR_CARD, activeforeground=COLOR_PRIMARY, font=("Segoe UI", 9))
        rb_filter.pack(anchor="w", padx=6, pady=(2, 14))

        # Format Selection
        tk.Label(pad, text="Zielformat:", font=("Segoe UI", 9, "bold"), bg=COLOR_CARD, fg=COLOR_TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        fmt_var = tk.StringVar(value="bib")

        rb_bib = tk.Radiobutton(pad, text="BibTeX (.bib) — Für LaTeX & Overleaf", variable=fmt_var, value="bib", bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, selectcolor="#0D1117", activebackground=COLOR_CARD, activeforeground=COLOR_PRIMARY, font=("Segoe UI", 9))
        rb_bib.pack(anchor="w", padx=6, pady=2)

        rb_ris = tk.Radiobutton(pad, text="RIS (.ris) — Für Zotero, Citavi, Mendeley", variable=fmt_var, value="ris", bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, selectcolor="#0D1117", activebackground=COLOR_CARD, activeforeground=COLOR_PRIMARY, font=("Segoe UI", 9))
        rb_ris.pack(anchor="w", padx=6, pady=2)

        rb_csv = tk.Radiobutton(pad, text="CSV (.csv) — Für Excel / Tabellenkalkulation", variable=fmt_var, value="csv", bg=COLOR_CARD, fg=COLOR_TEXT_MAIN, selectcolor="#0D1117", activebackground=COLOR_CARD, activeforeground=COLOR_PRIMARY, font=("Segoe UI", 9))
        rb_csv.pack(anchor="w", padx=6, pady=(2, 18))

        def do_export():
            target_books = self._master_books if scope_var.get() == "all" else self._all_current_books
            fmt = fmt_var.get()

            ext_map = {
                "bib": ("BibTeX-Datei", "*.bib"),
                "ris": ("RIS-Literaturdatei", "*.ris"),
                "csv": ("CSV-Tabelle", "*.csv"),
            }
            desc, ext = ext_map.get(fmt, ("Datei", "*.*"))

            save_path = filedialog.asksaveasfilename(
                parent=dlg,
                title="Bibliothek exportieren als...",
                defaultextension=f".{fmt}",
                filetypes=[(desc, ext), ("Alle Dateien", "*.*")],
                initialfile=f"Campus_Bibliothek_{fmt.upper()}",
            )
            if not save_path:
                return

            try:
                from core.citations import export_library_to_file
                written = export_library_to_file(target_books, fmt, save_path)
                dlg.destroy()
                messagebox.showinfo("Export erfolgreich", f"Erfolgreich {written} Bücher als {fmt.upper()} exportiert:\n\n{save_path}", parent=self)
                self._log(f"[Export] {written} Bücher nach {save_path} exportiert.")
            except Exception as e:
                messagebox.showerror("Fehler beim Export", f"Die Datei konnte nicht gespeichert werden:\n{str(e)}", parent=dlg)

        btn_box = tk.Frame(pad, bg=COLOR_CARD)
        btn_box.pack(fill=tk.X, pady=(10, 0))

        tk.Button(btn_box, text="💾 Export-Datei speichern...", font=("Segoe UI", 10, "bold"), bg=COLOR_PRIMARY, fg="#FFFFFF", bd=0, padx=16, pady=6, cursor="hand2", command=do_export).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(btn_box, text="Abbrechen", font=("Segoe UI", 10), bg=COLOR_HOVER, fg=COLOR_TEXT_MUTED, bd=0, padx=14, pady=6, cursor="hand2", command=dlg.destroy).pack(side=tk.RIGHT)



    def _get_active_selection_id(self) -> Optional[str]:
        if self.catalog_view_mode == "shelf":
            if self.selected_book_id:
                return self.selected_book_id
            if self._all_current_books:
                return self._all_current_books[0]["id"]
            return None
        sel = self.tree_books.selection()
        return sel[0] if sel else None

    def _open_selected_book(self) -> None:
        b_id = self._get_active_selection_id()
        if b_id:
            self._launch_book_by_id(b_id)

    def _toggle_selected_desk(self) -> None:
        b_id = self._get_active_selection_id()
        if not b_id:
            return

        conn = self._get_db()
        cur_desk = conn.execute("SELECT current_page FROM desk_items WHERE book_id = ?", (b_id,)).fetchone()

        if not cur_desk:
            curr_b = next((b for b in self._master_books if b["id"] == b_id), None)
            tot_p = curr_b.get("page_count", 0) if curr_b else 0
            cur_p = curr_b.get("current_page", 1) if curr_b else 1

            page_input = simpledialog.askinteger(
                "Lesepult – Seite speichern",
                "Buch aufs Lesepult legen:\n\nAuf welcher Seite möchtest du starten / weiterlesen?",
                initialvalue=cur_p if cur_p and cur_p > 0 else 1,
                minvalue=1,
                maxvalue=tot_p if tot_p and tot_p > 0 else 99999,
                parent=self,
            )
            if page_input is None:
                return
            start_p = page_input
            new_state = toggle_desk_item(b_id, start_page=start_p)
            msg = f"Auf das Lesepult gelegt (Seite {start_p} gespeichert, öffnet in Edge)!"
        else:
            new_state = toggle_desk_item(b_id)
            start_p = 1
            msg = "Vom Lesepult entfernt."

        if self.tree_books.exists(b_id):
            current_vals = list(self.tree_books.item(b_id, "values"))
            if current_vals:
                current_vals[0] = "📖" if new_state else "—"
                self.tree_books.item(b_id, values=current_vals)
        for b in self._all_current_books:
            if b["id"] == b_id:
                b["is_on_desk"] = 1 if new_state else 0
                if new_state:
                    b["current_page"] = start_p
                break
        for b in self._master_books:
            if b["id"] == b_id:
                b["is_on_desk"] = 1 if new_state else 0
                if new_state:
                    b["current_page"] = start_p
                break
        if self.catalog_view_mode == "shelf":
            self._render_shelf_grid()
        self._desk_dirty = True
        self._log(f"[Pult] {msg}")

    def _launch_book_by_id(self, book_id: str) -> None:
        conn = self._get_db()
        row = conn.execute("SELECT file_path, title FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row or not row["file_path"]:
            messagebox.showerror("Fehler", "PDF-Datei nicht gefunden.")
            return

        desk_row = conn.execute("SELECT current_page FROM desk_items WHERE book_id = ?", (book_id,)).fetchone()
        saved_page = desk_row["current_page"] if desk_row and desk_row["current_page"] else 1

        success = open_pdf_in_edge(row["file_path"], page=saved_page)
        if success:
            if desk_row and desk_row["current_page"]:
                self._log(f"[Edge] Öffne '{row['title']}' auf gespeicherter Seite {saved_page}...")
            else:
                self._log(f"[Edge] Öffne '{row['title']}'...")
        else:
            success = open_pdf_in_system_viewer(row["file_path"])
            if not success:
                messagebox.showerror("Fehler", f"Datei konnte nicht geöffnet werden:\n{row['file_path']}")

    def _get_db(self):
        from core.library_db import get_db_connection
        return get_db_connection()

    # -----------------------------------------------------------------
    # DELTA-SCAN WORKER
    # -----------------------------------------------------------------
    def _choose_source_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.source_dir, title="Quellordner für PDFs wählen")
        if chosen:
            self.source_dir = chosen
            self.lbl_source_dir.configure(text=chosen)
            cfg = load_config()
            cfg["last_directory"] = chosen
            save_config(cfg)

    def _live_add_book_to_catalog(self, b: Dict[str, Any]) -> None:
        desk_icon = "📖" if b.get("is_on_desk") else "—"
        ed_str = f"{b.get('edition', 1)}. Aufl."
        pages_str = str(b.get("page_count")) if b.get("page_count") else "?"
        cats = b.get("categories_str") or "Sonstiges"

        if self.tree_books.exists(b["id"]):
            self.tree_books.item(
                b["id"],
                values=(desk_icon, b["title"], b["author"], cats, ed_str, pages_str)
            )
        else:
            self.tree_books.insert(
                "",
                0,
                iid=b["id"],
                values=(desk_icon, b["title"], b["author"], cats, ed_str, pages_str),
            )
        self._library_loaded = True

        ts = time.strftime("%H:%M:%S")
        self.txt_log.insert(tk.END, f"[{ts}] [Katalog ✨] Neu erfasst: {b['title'][:40]}\n")
        line_count = int(self.txt_log.index("end-1c").split(".")[0])
        if line_count > 400:
            self.txt_log.delete("1.0", "50.0")
        self.txt_log.see(tk.END)

    def _start_delta_scan(self) -> None:
        if self.is_scanning:
            return
        self.is_scanning = True
        self.btn_run_scan.configure(state="disabled", text="⏳ Scanne...")
        self.lbl_scan_status.configure(text="Initialisiere Delta-Scan...")
        self.progress_bar["value"] = 0

        def scan_worker():
            self._log(f"[Delta-Scan] Starte Prüfung in: {self.source_dir}")
            last_ui_update = 0.0
            prog_lock = threading.Lock()

            def on_progress(curr, total, fname, is_delta, book_data=None):
                nonlocal last_ui_update

                # Stream new books live into catalog table
                if is_delta and book_data:
                    self._dispatch(self._live_add_book_to_catalog, book_data)

                # Throttle UI progress-bar updates (max 20Hz, or delta, or 100%)
                with prog_lock:
                    now = time.time()
                    if is_delta or (now - last_ui_update >= 0.05) or curr == total:
                        last_ui_update = now
                        pct = int((curr / max(1, total)) * 100)
                        tag = "⚡ NEU" if is_delta else "✔ Bekannt"
                        msg = f"{curr}/{total} ({pct}%) | {tag}: {fname[:35]}"
                        self._dispatch(self._update_scan_progress, pct, msg)

            from core.delta_scanner import run_delta_scan
            stats = run_delta_scan(
                source_dir=self.source_dir,
                progress_callback=on_progress,
                stop_event=self.stop_event,
            )

            self._dispatch(self._finish_delta_scan, stats)

        threading.Thread(target=scan_worker, daemon=True).start()

    def _update_scan_progress(self, pct: int, msg: str) -> None:
        self.progress_bar["value"] = pct
        self.lbl_scan_status.configure(text=msg)

    def _finish_delta_scan(self, stats: Dict[str, int]) -> None:
        self.is_scanning = False
        self.btn_run_scan.configure(state="normal", text="⚡ Delta-Scan starten")
        self.progress_bar["value"] = 100
        summary = f"Scan fertig! {stats['total']} PDFs geprüft ({stats['new_or_updated']} analysiert, {stats['unchanged']} unverändert)."
        self.lbl_scan_status.configure(text=summary)
        self._log(f"[Delta-Scan] {summary}")
        self._desk_dirty = True
        self._radar_dirty = True

        # Quick stats & chips update without freezing the treeview
        cat_counts = get_category_counts()
        total_b = sum(c[1] for c in cat_counts)
        self.lbl_stats.configure(text=f"● {total_b} Fachbücher\n● SQLite Data-Lake aktiv")
        self._render_category_chips(cat_counts)

        messagebox.showinfo("Scan abgeschlossen", summary)

    def _log(self, text: str) -> None:
        def append():
            ts = time.strftime("%H:%M:%S")
            self.txt_log.insert(tk.END, f"[{ts}] {text}\n")
            # Bound log to last 400 lines to guarantee smooth rendering
            line_count = int(self.txt_log.index("end-1c").split(".")[0])
            if line_count > 400:
                self.txt_log.delete("1.0", "50.0")
            self.txt_log.see(tk.END)
        self._dispatch(append)


def main():
    app = CampusLibraryDashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
