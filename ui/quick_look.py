"""High-fidelity Quick-Look preview modal dialog (Spacebar/Click inspector).
Shows full bibliographic metadata, large cover, reading progress, and 1-click citation export.
"""

import os
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Any, Callable, Dict, Optional
from PIL import Image, ImageTk

from core.citations import generate_apa, generate_bibtex, generate_markdown_link, generate_ris
from core.cover_manager import get_cached_cover, generate_fallback_cover, FACULTY_COLORS
from core.library_db import (
    open_pdf_in_system_viewer,
    open_pdf_at_page,
    open_pdf_in_edge,
    toggle_desk_item,
    update_reading_progress,
    resolve_or_extract_book_year,
    update_book_year,
    get_book_summary,
)
from ai.pdf_extractor import extract_pdf_toc
from ai.summary_generator import generate_book_summary



class QuickLookDialog(tk.Toplevel):
    """Modern dark-themed Quick-Look inspection window."""

    def __init__(self, parent: tk.Tk, book: Dict[str, Any], on_change: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        # Immediately withdraw to prevent white flash during initial rendering
        self.withdraw()

        self.parent = parent
        self.book = dict(book)
        self.on_change = on_change

        self.title(f"Quick-Look: {self.book.get('title', 'Buch-Vorschau')}")
        self.minsize(700, 480)
        self.configure(bg="#0D1117")
        self.transient(parent)

        # Center window relative to parent while still hidden
        w_w, w_h = 780, 520
        try:
            p_x = parent.winfo_rootx() if parent.winfo_rootx() > 0 else parent.winfo_x()
            p_y = parent.winfo_rooty() if parent.winfo_rooty() > 0 else parent.winfo_y()
            p_w = parent.winfo_width() if parent.winfo_width() > 100 else 1300
            p_h = parent.winfo_height() if parent.winfo_height() > 100 else 820
            pos_x = max(20, p_x + (p_w - w_w) // 2)
            pos_y = max(20, p_y + (p_h - w_h) // 2)
            self.geometry(f"{w_w}x{w_h}+{pos_x}+{pos_y}")
        except Exception:
            self.geometry(f"{w_w}x{w_h}")

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<space>", lambda e: self.destroy())

        # Construct UI elements while window is hidden
        self._build_ui()

        # Set Windows 10/11 dark title bar
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            for attr in (20, 19):
                v = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:
            pass

        # Update geometry and reveal without flicker
        self.update_idletasks()
        self.deiconify()
        self.lift()
        self.focus_force()

        # Auto-extract publication year asynchronously so window launch is instant
        if not self.book.get("year"):
            def _async_year():
                auto_year = resolve_or_extract_book_year(self.book)
                if auto_year:
                    def _apply():
                        if self.winfo_exists():
                            self.book["year"] = auto_year
                            if hasattr(self, "lbl_ed_year"):
                                ed_str = f"{self.book.get('edition', 1)}. Auflage"
                                self.lbl_ed_year.configure(text=f"{ed_str} • {auto_year}")
                            if self.on_change:
                                try:
                                    self.on_change()
                                except Exception:
                                    pass
                    self.after(0, _apply)
            import threading
            threading.Thread(target=_async_year, daemon=True).start()

    def _build_ui(self) -> None:
        main_frame = tk.Frame(self, bg="#0D1117", padx=20, pady=18)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Left Column: Big Cover Artwork
        left_col = tk.Frame(main_frame, bg="#0D1117", width=210)
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
        left_col.pack_propagate(False)

        cat = self.book.get("categories_str") or "Sonstiges"
        first_cat = cat.split(",")[0].strip()
        _, accent_col = FACULTY_COLORS.get(first_cat, ("#161B22", "#58A6FF"))

        # Cover Frame
        cov_frame = tk.Frame(
            left_col,
            bg="#12171F",
            width=200,
            height=280,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#30363D",
        )
        cov_frame.pack_propagate(False)
        cov_frame.pack(pady=(0, 14))

        # Get high-res cover
        b_id = self.book["id"]
        cached_img = get_cached_cover(b_id)
        if not cached_img:
            cached_img = generate_fallback_cover(self.book.get("title", ""), self.book.get("author", ""), first_cat)

        # Scale nicely to 200x280
        large_img = cached_img.resize((196, 276), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(large_img)

        lbl_img = tk.Label(cov_frame, image=self._photo, bg="#12171F", bd=0)
        lbl_img.pack(fill=tk.BOTH, expand=True)

        # Fast action buttons under cover
        curr_p = self.book.get("current_page", 1) or 1
        open_label = f"🌐 In Edge öffnen (S. {curr_p})" if curr_p > 1 else "🌐 In Edge öffnen"
        self.btn_open = tk.Button(
            left_col,
            text=open_label,
            font=("Segoe UI", 10, "bold"),
            bg="#238636",
            fg="#FFFFFF",
            activebackground="#2EA043",
            activeforeground="#FFFFFF",
            bd=0,
            pady=7,
            cursor="hand2",
            command=self._open_pdf,
        )
        self.btn_open.pack(fill=tk.X, pady=(0, 6))

        btn_explorer = tk.Button(
            left_col,
            text="📁 Im Explorer zeigen",
            font=("Segoe UI", 9),
            bg="#21262D",
            fg="#C9D1D9",
            activebackground="#30363D",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            pady=5,
            cursor="hand2",
            command=self._show_in_explorer,
        )
        btn_explorer.pack(fill=tk.X)

        # Right Column: Bibliographic Details & Citations
        right_col = tk.Frame(main_frame, bg="#0D1117")
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Top Badge Row (Multi-Categories + Desk indicator)
        badge_row = tk.Frame(right_col, bg="#0D1117")
        badge_row.pack(fill=tk.X, pady=(0, 6))

        cat_str = self.book.get("categories_str") or "Sonstiges"
        cats = [c.strip() for c in cat_str.split("|") if c.strip()]
        primary_cat = self.book.get("primary_category") or (cats[0] if cats else "Sonstiges")

        for c in cats:
            is_prim = (c == primary_cat)
            _, c_col = FACULTY_COLORS.get(c, ("#161B22", "#58A6FF"))
            b_text = f"● {c}" + (" (Hauptfach)" if is_prim and len(cats) > 1 else "")
            badge = tk.Label(
                badge_row,
                text=b_text,
                font=("Segoe UI", 8, "bold" if is_prim else "normal"),
                bg="#1F2937" if is_prim else "#161B22",
                fg=c_col,
                padx=7,
                pady=2,
                bd=1,
                relief="solid",
            )
            badge.pack(side=tk.LEFT, padx=(0, 6))

        if self.book.get("is_on_desk"):
            lbl_desk = tk.Label(badge_row, text="📖 Auf Schreibtisch", font=("Segoe UI", 9, "bold"), bg="#1F2937", fg="#58A6FF", padx=8, pady=2)
            lbl_desk.pack(side=tk.RIGHT)

        # Big Title
        lbl_t = tk.Label(
            right_col,
            text=self.book.get("title", "Ohne Titel"),
            font=("Segoe UI", 14, "bold"),
            bg="#0D1117",
            fg="#F0F6FC",
            wraplength=510,
            justify=tk.LEFT,
        )
        lbl_t.pack(anchor="w", pady=(0, 4))

        # Author
        lbl_a = tk.Label(
            right_col,
            text=f"von {self.book.get('author', 'Unbekannt')}",
            font=("Segoe UI", 11),
            bg="#0D1117",
            fg="#8B949E",
            wraplength=510,
            justify=tk.LEFT,
        )
        lbl_a.pack(anchor="w", pady=(0, 14))

        # Metadata Card Grid
        meta_card = tk.Frame(right_col, bg="#161B22", bd=1, relief="solid", highlightthickness=1, highlightbackground="#30363D", padx=14, pady=12)
        meta_card.pack(fill=tk.X, pady=(0, 14))

        raw_isbn = self.book.get("isbn")
        if raw_isbn:
            import re
            digits = re.sub(r'\D', '', str(raw_isbn))
            if len(digits) == 13 and "-" not in str(raw_isbn):
                display_isbn = f"{digits[:3]}-{digits[3]}-{digits[4:7]}-{digits[7:12]}-{digits[12:]}"
            else:
                display_isbn = str(raw_isbn)
        else:
            display_isbn = "Keine Angabe"
        self._add_meta_row(meta_card, 0, "ISBN / Identifikator:", display_isbn)
        year_str = str(self.book.get("year")) if self.book.get("year") else "Unbekannt"
        ed_str = f"{self.book.get('edition', 1)}. Auflage"

        # Auflage & Jahr with quick edit button
        row_ey = tk.Frame(meta_card, bg="#161B22")
        row_ey.pack(fill=tk.X, pady=2)
        tk.Label(row_ey, text="Auflage & Jahr:", font=("Segoe UI", 8, "bold"), bg="#161B22", fg="#8B949E", width=18, anchor="w").pack(side=tk.LEFT)
        self.lbl_ed_year = tk.Label(row_ey, text=f"{ed_str} • {year_str}", font=("Segoe UI", 8), bg="#161B22", fg="#C9D1D9", anchor="w")
        self.lbl_ed_year.pack(side=tk.LEFT)

        btn_edit_yr = tk.Button(
            row_ey,
            text="✏️",
            font=("Segoe UI", 8),
            bg="#21262D",
            fg="#58A6FF",
            activebackground="#30363D",
            activeforeground="#FFFFFF",
            bd=0,
            padx=4,
            pady=0,
            cursor="hand2",
            command=self._edit_year,
        )
        btn_edit_yr.pack(side=tk.LEFT, padx=(6, 0))

        pages = self.book.get("page_count")
        pages_str = f"{pages} Seiten" if pages else "Nicht ermittelt"
        size_bytes = self.book.get("file_size") or 0
        size_str = f"{size_bytes / (1024*1024):.1f} MB" if size_bytes else "?"
        self._add_meta_row(meta_card, 2, "Umfang & Größe:", f"{pages_str} • {size_str}")

        file_path = self.book.get("file_path") or ""
        short_path = file_path if len(file_path) < 55 else "..." + file_path[-52:]
        self._add_meta_row(meta_card, 3, "Speicherort:", short_path)

        # Reading Progress Section
        progress_card = tk.Frame(right_col, bg="#161B22", bd=1, relief="solid", highlightthickness=1, highlightbackground="#30363D", padx=14, pady=10)
        progress_card.pack(fill=tk.X, pady=(0, 14))

        p_row = tk.Frame(progress_card, bg="#161B22")
        p_row.pack(fill=tk.X)

        tk.Label(p_row, text="📊 Lesefortschritt:", font=("Segoe UI", 9, "bold"), bg="#161B22", fg="#F0F6FC").pack(side=tk.LEFT)

        tot_pages = self.book.get("page_count") or 1
        curr_page = self.book.get("current_page") or 0
        pct = self.book.get("reading_progress") or 0

        self.lbl_progress_val = tk.Label(
            p_row,
            text=f"Seite {curr_page} von {tot_pages} ({pct}%)",
            font=("Segoe UI", 9),
            bg="#161B22",
            fg="#58A6FF" if pct > 0 else "#8B949E",
        )
        self.lbl_progress_val.pack(side=tk.RIGHT)

        # Quick set page buttons
        btn_prog_box = tk.Frame(progress_card, bg="#161B22")
        btn_prog_box.pack(fill=tk.X, pady=(6, 0))

        tk.Label(btn_prog_box, text="Schnell setzen:", font=("Segoe UI", 8), bg="#161B22", fg="#8B949E").pack(side=tk.LEFT, padx=(0, 6))

        for target_pct in (25, 50, 75, 100):
            calc_p = int(tot_pages * (target_pct / 100.0))
            b = tk.Button(
                btn_prog_box,
                text=f"{target_pct}%",
                font=("Segoe UI", 8),
                bg="#21262D",
                fg="#C9D1D9",
                bd=1,
                relief="solid",
                padx=6,
                pady=1,
                cursor="hand2",
                command=lambda p=calc_p: self._set_progress(p),
            )
            b.pack(side=tk.LEFT, padx=3)

        # Exact page input & save for Edge bookmarking
        page_input_frame = tk.Frame(progress_card, bg="#161B22")
        page_input_frame.pack(fill=tk.X, pady=(8, 0))
        tk.Label(page_input_frame, text="Seite auf Pult merken:", font=("Segoe UI", 8), bg="#161B22", fg="#8B949E").pack(side=tk.LEFT, padx=(0, 6))

        self.ent_quick_page = tk.Entry(page_input_frame, width=6, bg="#0D1117", fg="#F0F6FC", insertbackground="#58A6FF", bd=1, relief="solid")
        self.ent_quick_page.pack(side=tk.LEFT, padx=(0, 6))
        if curr_page:
            self.ent_quick_page.insert(0, str(curr_page))

        def _save_exact_page():
            try:
                val = int(self.ent_quick_page.get().strip())
                self._set_progress(val)
            except ValueError:
                pass

        btn_save_exact = tk.Button(
            page_input_frame,
            text="Speichern",
            font=("Segoe UI", 8, "bold"),
            bg="#21262D",
            fg="#58A6FF",
            activebackground="#30363D",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            padx=8,
            pady=1,
            cursor="hand2",
            command=_save_exact_page,
        )
        btn_save_exact.pack(side=tk.LEFT)
        self.ent_quick_page.bind("<Return>", lambda e: _save_exact_page())

        lbl_edge_hint = tk.Label(page_input_frame, text="🌐 Öffnet in Edge", font=("Segoe UI", 8), bg="#161B22", fg="#3FB950")
        lbl_edge_hint.pack(side=tk.LEFT, padx=(8, 0))

        # 1-Click Citation Export Bar
        cite_frame = tk.Frame(right_col, bg="#0D1117")
        cite_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(cite_frame, text="🎓 Zitat exportieren:", font=("Segoe UI", 9, "bold"), bg="#0D1117", fg="#F0F6FC").pack(side=tk.LEFT, padx=(0, 10))

        btn_bibtex = tk.Button(
            cite_frame,
            text="BibTeX",
            font=("Segoe UI", 8, "bold"),
            bg="#21262D",
            fg="#58A6FF",
            bd=1,
            relief="solid",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._copy_bibtex,
        )
        btn_bibtex.pack(side=tk.LEFT, padx=(0, 6))

        btn_apa = tk.Button(
            cite_frame,
            text="APA 7",
            font=("Segoe UI", 8, "bold"),
            bg="#21262D",
            fg="#58A6FF",
            bd=1,
            relief="solid",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._copy_apa,
        )
        btn_apa.pack(side=tk.LEFT, padx=(0, 6))

        btn_ris = tk.Button(
            cite_frame,
            text="RIS (Zotero)",
            font=("Segoe UI", 8, "bold"),
            bg="#21262D",
            fg="#58A6FF",
            bd=1,
            relief="solid",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._copy_ris,
        )
        btn_ris.pack(side=tk.LEFT, padx=(0, 6))

        btn_md = tk.Button(
            cite_frame,
            text="Markdown",
            font=("Segoe UI", 8),
            bg="#21262D",
            fg="#C9D1D9",
            bd=1,
            relief="solid",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._copy_markdown,
        )
        btn_md.pack(side=tk.LEFT, padx=(0, 8))

        self.lbl_copy_toast = tk.Label(cite_frame, text="", font=("Segoe UI", 9, "bold"), bg="#0D1117", fg="#3FB950")
        self.lbl_copy_toast.pack(side=tk.LEFT)

        # Exploration Actions Bar: TOC & AI Abstract
        action_card = tk.Frame(right_col, bg="#0D1117")
        action_card.pack(fill=tk.X, pady=(0, 10))

        btn_toc = tk.Button(
            action_card,
            text="📑 Inhaltsverzeichnis (TOC)",
            font=("Segoe UI", 9, "bold"),
            bg="#1F2937",
            fg="#38BDF8",
            activebackground="#374151",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            padx=12,
            pady=5,
            cursor="hand2",
            command=self._show_toc_dialog,
        )
        btn_toc.pack(side=tk.LEFT, padx=(0, 8))

        btn_summary = tk.Button(
            action_card,
            text="✨ KI-Zusammenfassung",
            font=("Segoe UI", 9, "bold"),
            bg="#1F2937",
            fg="#A78BFA",
            activebackground="#374151",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            padx=12,
            pady=5,
            cursor="hand2",
            command=self._show_summary_dialog,
        )
        btn_summary.pack(side=tk.LEFT)

        # Bottom Bar: Desk Toggle & Close
        bot_bar = tk.Frame(right_col, bg="#0D1117")
        bot_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        self.btn_desk = tk.Button(
            bot_bar,
            text="📖 Auf Schreibtisch" if not self.book.get("is_on_desk") else "❌ Vom Schreibtisch entfernen",
            font=("Segoe UI", 9),
            bg="#21262D",
            fg="#F0F6FC",
            bd=1,
            relief="solid",
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._toggle_desk,
        )
        self.btn_desk.pack(side=tk.LEFT)

        btn_close = tk.Button(
            bot_bar,
            text="Schließen (Esc)",
            font=("Segoe UI", 9),
            bg="#21262D",
            fg="#8B949E",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.destroy,
        )
        btn_close.pack(side=tk.RIGHT)

    def _add_meta_row(self, parent: tk.Frame, row_idx: int, label: str, val: str) -> None:
        f = tk.Frame(parent, bg="#161B22")
        f.pack(fill=tk.X, pady=2)
        tk.Label(f, text=label, font=("Segoe UI", 8, "bold"), bg="#161B22", fg="#8B949E", width=18, anchor="w").pack(side=tk.LEFT)
        tk.Label(f, text=val, font=("Segoe UI", 8), bg="#161B22", fg="#C9D1D9", anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _edit_year(self) -> None:
        """Allows instant inline modification of publication year."""
        curr_y = self.book.get("year") or 2020
        new_y = simpledialog.askinteger(
            "Erscheinungsjahr anpassen",
            "Erscheinungsjahr für dieses Buch eingeben (z. B. 2021):",
            parent=self,
            initialvalue=curr_y,
            minvalue=1800,
            maxvalue=2050,
        )
        if new_y:
            update_book_year(self.book["id"], new_y)
            self.book["year"] = new_y
            ed_str = f"{self.book.get('edition', 1)}. Auflage"
            self.lbl_ed_year.configure(text=f"{ed_str} • {new_y}")
            self._flash_toast(f"Jahr auf {new_y} gesetzt!")
            if self.on_change:
                try:
                    self.on_change()
                except Exception:
                    pass


    def _flash_toast(self, text: str) -> None:
        self.lbl_copy_toast.configure(text=f"✓ {text}")
        self.after(2200, lambda: self.lbl_copy_toast.configure(text=""))

    def _copy_bibtex(self) -> None:
        text = generate_bibtex(self.book)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._flash_toast("BibTeX in Zwischenablage!")

    def _copy_apa(self) -> None:
        text = generate_apa(self.book)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._flash_toast("APA 7 Zitat kopiert!")

    def _copy_markdown(self) -> None:
        text = generate_markdown_link(self.book)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._flash_toast("Markdown-Link kopiert!")

    def _copy_ris(self) -> None:
        text = generate_ris(self.book)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._flash_toast("RIS (Zotero) Zitat kopiert!")

    def _show_toc_dialog(self) -> None:
        """Displays modern interactive Table of Contents with 1-click page jump navigation."""
        fp = self.book.get("file_path")
        if not fp or not os.path.exists(fp):
            messagebox.showerror("Fehler", "PDF-Datei nicht gefunden.", parent=self)
            return

        toc_items = extract_pdf_toc(fp)
        if not toc_items:
            messagebox.showinfo("Inhaltsverzeichnis", "Für dieses PDF sind keine digitalen Kapitel/Bookmarks hinterlegt.", parent=self)
            return

        w = tk.Toplevel(self)
        w.withdraw()
        book_title = self.book.get('title', 'Kapitel')
        book_author = self.book.get('author', 'Unbekannter Autor')
        w.title(f"Inhaltsverzeichnis • {book_title}")
        w.configure(bg="#0D1117")
        w.minsize(680, 480)

        # Center dialog nicely over parent
        try:
            pw_x = self.winfo_rootx() if self.winfo_rootx() > 0 else self.winfo_x()
            pw_y = self.winfo_rooty() if self.winfo_rooty() > 0 else self.winfo_y()
            pw_w = self.winfo_width()
            pw_h = self.winfo_height()
            dw_w, dw_h = 760, 580
            pos_x = max(40, pw_x + (pw_w - dw_w) // 2)
            pos_y = max(40, pw_y + (pw_h - dw_h) // 2)
            w.geometry(f"{dw_w}x{dw_h}+{pos_x}+{pos_y}")
        except Exception:
            w.geometry("760x580")

        w.transient(self)

        # Modern Dark Scrollbar style
        style = ttk.Style(w)
        try:
            style.theme_use("clam")
            style.layout("Vertical.TScrollbar", [
                ("Vertical.Scrollbar.trough", {
                    "sticky": "ns",
                    "children": [
                        ("Vertical.Scrollbar.thumb", {"sticky": "nswe"})
                    ]
                })
            ])
            style.configure("Vertical.TScrollbar",
                background="#30363D",
                troughcolor="#0D1117",
                bordercolor="#0D1117",
                lightcolor="#30363D",
                darkcolor="#30363D",
                arrowsize=0,
                gripcount=0,
                relief="flat"
            )
            style.map("Vertical.TScrollbar",
                background=[("pressed", "#58A6FF"), ("active", "#484F58")]
            )
        except Exception:
            pass

        # ---------------- Top Header ----------------
        hdr = tk.Frame(w, bg="#0D1117", padx=20, pady=14)
        hdr.pack(fill=tk.X)

        top_line = tk.Frame(hdr, bg="#0D1117")
        top_line.pack(fill=tk.X)

        title_box = tk.Frame(top_line, bg="#0D1117")
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(title_box, text="📑", font=("Segoe UI Emoji", 14), bg="#0D1117", fg="#58A6FF").pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(title_box, text="Inhaltsverzeichnis", font=("Segoe UI", 13, "bold"), bg="#0D1117", fg="#F0F6FC").pack(side=tk.LEFT)

        count_badge = tk.Label(
            title_box,
            text=f"{len(toc_items)} Kapitel",
            font=("Segoe UI", 8, "bold"),
            bg="#21262D",
            fg="#58A6FF",
            padx=8,
            pady=2,
            bd=0
        )
        count_badge.pack(side=tk.LEFT, padx=10)

        # Search / Filter Bar
        search_box = tk.Frame(top_line, bg="#161B22", bd=1, relief="solid", highlightthickness=1, highlightbackground="#30363D")
        search_box.pack(side=tk.RIGHT, pady=2)

        tk.Label(search_box, text=" 🔍 ", font=("Segoe UI", 9), bg="#161B22", fg="#8B949E").pack(side=tk.LEFT)
        search_var = tk.StringVar()
        search_entry = tk.Entry(
            search_box,
            textvariable=search_var,
            font=("Segoe UI", 9),
            bg="#161B22",
            fg="#F0F6FC",
            insertbackground="#58A6FF",
            bd=0,
            width=22
        )
        search_entry.pack(side=tk.LEFT, padx=(0, 6), pady=4)

        btn_clear = tk.Label(search_box, text="✕ ", font=("Segoe UI", 8, "bold"), bg="#161B22", fg="#6E7681", cursor="hand2")
        btn_clear.pack(side=tk.RIGHT)
        btn_clear.bind("<Button-1>", lambda e: search_var.set(""))

        sub_line = tk.Frame(hdr, bg="#0D1117")
        sub_line.pack(fill=tk.X, pady=(6, 0))

        tk.Label(sub_line, text=f"📖 {book_title}  •  {book_author}", font=("Segoe UI", 8), bg="#0D1117", fg="#8B949E", anchor="w").pack(side=tk.LEFT, fill=tk.X)
        tk.Label(sub_line, text="💡 Klick auf Seite oder Doppelklick öffnet PDF", font=("Segoe UI", 8), bg="#0D1117", fg="#58A6FF", anchor="e").pack(side=tk.RIGHT)

        # ---------------- List Container ----------------
        list_container = tk.Frame(w, bg="#161B22", bd=1, relief="solid", highlightthickness=1, highlightbackground="#30363D")
        list_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        canvas = tk.Canvas(list_container, bg="#0D1117", highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner_frame = tk.Frame(canvas, bg="#0D1117")
        win_id = canvas.create_window((0, 0), window=inner_frame, anchor="nw")

        def _on_canvas_resize(event):
            canvas.itemconfig(win_id, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_inner_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner_frame.bind("<Configure>", _on_inner_resize)

        # CRITICAL: Local mouse wheel handling with "break" to isolate scroll from background shelf!
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        w.bind("<MouseWheel>", _on_wheel)
        canvas.bind("<MouseWheel>", _on_wheel)
        inner_frame.bind("<MouseWheel>", _on_wheel)

        selected_item = {"page": None, "title": "", "frame": None}

        # ---------------- Status & Action Bar ----------------
        bottom_bar = tk.Frame(w, bg="#0D1117", padx=20, pady=12)
        bottom_bar.pack(fill=tk.X)

        status_lbl = tk.Label(bottom_bar, text="Kein Kapitel ausgewählt (Klick zum Auswählen)", font=("Segoe UI", 9), bg="#0D1117", fg="#8B949E", anchor="w")
        status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def jump_to_page(page_num: int, title: str = ""):
            try:
                open_pdf_at_page(fp, page_num)
                self._flash_toast(f"Zu Seite {page_num} gesprungen!")
            except Exception:
                open_pdf_in_system_viewer(fp)

        def on_jump_action():
            if selected_item["page"] is not None:
                jump_to_page(selected_item["page"], selected_item["title"])
            else:
                messagebox.showinfo("Inhaltsverzeichnis", "Bitte wähle zuerst ein Kapitel aus.", parent=w)

        btn_jump = tk.Button(
            bottom_bar,
            text="📖 Zu Seite springen",
            font=("Segoe UI", 9, "bold"),
            bg="#238636",
            activebackground="#2EA043",
            fg="#FFFFFF",
            activeforeground="#FFFFFF",
            bd=0,
            padx=16,
            pady=6,
            cursor="hand2",
            command=on_jump_action
        )
        btn_jump.pack(side=tk.RIGHT, padx=(8, 0))

        btn_close = tk.Button(
            bottom_bar,
            text="Schließen",
            font=("Segoe UI", 9),
            bg="#21262D",
            activebackground="#30363D",
            fg="#8B949E",
            activeforeground="#F0F6FC",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=w.destroy
        )
        btn_close.pack(side=tk.RIGHT)

        # Build chapter item rows
        row_widgets = []

        def select_row(row_f, page_num, ch_title):
            if selected_item["frame"] and selected_item["frame"].winfo_exists():
                prev_lvl = getattr(selected_item["frame"], "_lvl", 1)
                default_bg = "#161B22" if prev_lvl == 1 else ("#12161D" if prev_lvl == 2 else "#0F1318")
                default_border = "#21262D" if prev_lvl == 1 else "#1B2028"
                selected_item["frame"].configure(bg=default_bg, highlightbackground=default_border)
                for child in selected_item["frame"].winfo_children():
                    if getattr(child, "_is_badge", False):
                        continue
                    child.configure(bg=default_bg)

            selected_item["page"] = page_num
            selected_item["title"] = ch_title
            selected_item["frame"] = row_f

            row_f.configure(bg="#1C2B3F", highlightbackground="#58A6FF")
            for child in row_f.winfo_children():
                if getattr(child, "_is_badge", False):
                    continue
                child.configure(bg="#1C2B3F")

            status_lbl.configure(text=f"📌 Ausgewählt: \"{ch_title[:55]}{'…' if len(ch_title)>55 else ''}\"  (Seite {page_num})", fg="#F0F6FC")

        for idx, item_data in enumerate(toc_items):
            lvl = item_data[0]
            title = item_data[1]
            target_page = item_data[2]
            printed_page = item_data[3] if len(item_data) > 3 else target_page

            is_l1 = (lvl == 1)
            is_l2 = (lvl == 2)
            bg_color = "#161B22" if is_l1 else ("#12161D" if is_l2 else "#0F1318")
            border_color = "#21262D" if is_l1 else "#1B2028"
            indent_pad = 12 if is_l1 else (32 if is_l2 else 52)

            rf = tk.Frame(
                inner_frame,
                bg=bg_color,
                bd=0,
                highlightthickness=1,
                highlightbackground=border_color,
                padx=8,
                pady=6,
                cursor="hand2"
            )
            rf._lvl = lvl
            rf._title = title.lower()
            rf._page_str = str(printed_page)
            rf.pack(fill=tk.X, padx=10, pady=2)

            # Left prefix / icon
            if is_l1:
                prefix_lbl = tk.Label(rf, text="📑 ", font=("Segoe UI", 9, "bold"), bg=bg_color, fg="#58A6FF")
                prefix_lbl.pack(side=tk.LEFT, padx=(indent_pad, 4))
                title_font = ("Segoe UI", 10, "bold")
                title_color = "#F0F6FC"
            elif is_l2:
                prefix_lbl = tk.Label(rf, text="↳ ", font=("Segoe UI", 9), bg=bg_color, fg="#58A6FF")
                prefix_lbl.pack(side=tk.LEFT, padx=(indent_pad, 4))
                title_font = ("Segoe UI", 9)
                title_color = "#C9D1D9"
            else:
                prefix_lbl = tk.Label(rf, text="• ", font=("Segoe UI", 8), bg=bg_color, fg="#6E7681")
                prefix_lbl.pack(side=tk.LEFT, padx=(indent_pad, 4))
                title_font = ("Segoe UI", 9)
                title_color = "#8B949E"

            title_lbl = tk.Label(rf, text=title, font=title_font, bg=bg_color, fg=title_color, anchor="w")
            title_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Page jump pill button (displays printed page, jumps to actual PDF page)
            page_btn = tk.Button(
                rf,
                text=f"S. {printed_page} ↗",
                font=("Segoe UI", 9, "bold"),
                bg="#21262D",
                activebackground="#238636",
                fg="#58A6FF",
                activeforeground="#FFFFFF",
                bd=0,
                padx=10,
                pady=2,
                cursor="hand2",
                command=lambda p=target_page, t=title: jump_to_page(p, t)
            )
            page_btn._is_badge = True
            page_btn.pack(side=tk.RIGHT, padx=4)

            # Bindings for hover and click
            def make_bindings(f, p, t, l):
                def _enter(e):
                    if selected_item["frame"] != f:
                        f.configure(bg="#1F2937", highlightbackground="#388BFD")
                        for c in f.winfo_children():
                            if getattr(c, "_is_badge", False):
                                continue
                            c.configure(bg="#1F2937")

                def _leave(e):
                    if selected_item["frame"] != f:
                        orig_bg = "#161B22" if l == 1 else ("#12161D" if l == 2 else "#0F1318")
                        orig_bdr = "#21262D" if l == 1 else "#1B2028"
                        f.configure(bg=orig_bg, highlightbackground=orig_bdr)
                        for c in f.winfo_children():
                            if getattr(c, "_is_badge", False):
                                continue
                            c.configure(bg=orig_bg)

                def _click(e):
                    select_row(f, p, t)

                def _dbl_click(e):
                    select_row(f, p, t)
                    jump_to_page(p, t)

                for wgt in (f, prefix_lbl, title_lbl):
                    wgt.bind("<Enter>", _enter)
                    wgt.bind("<Leave>", _leave)
                    wgt.bind("<Button-1>", _click)
                    wgt.bind("<Double-1>", _dbl_click)
                    wgt.bind("<MouseWheel>", _on_wheel)

                page_btn.bind("<MouseWheel>", _on_wheel)

            make_bindings(rf, page, title, lvl)
            row_widgets.append(rf)

        # Real-time search filter
        empty_lbl = tk.Label(
            inner_frame,
            text="Keine passenden Kapitel gefunden.",
            font=("Segoe UI", 10),
            bg="#0D1117",
            fg="#8B949E",
            pady=30
        )

        def apply_filter(*args):
            query = search_var.get().strip().lower()
            visible_count = 0
            for rf in row_widgets:
                if not query or (query in rf._title) or (query in rf._page_str):
                    rf.pack(fill=tk.X, padx=10, pady=2)
                    visible_count += 1
                else:
                    rf.pack_forget()

            if visible_count == 0:
                empty_lbl.pack(fill=tk.X, padx=10, pady=20)
                count_badge.configure(text=f"0 / {len(toc_items)} Treffer", fg="#F85149")
            else:
                empty_lbl.pack_forget()
                if query:
                    count_badge.configure(text=f"{visible_count} / {len(toc_items)} Treffer", fg="#58A6FF")
                else:
                    count_badge.configure(text=f"{len(toc_items)} Kapitel", fg="#58A6FF")

            canvas.configure(scrollregion=canvas.bbox("all"))

        search_var.trace_add("write", apply_filter)

        # Key bindings
        w.bind("<Escape>", lambda e: w.destroy())
        w.bind("<Return>", lambda e: on_jump_action())

        # Reveal TOC without flicker
        w.update_idletasks()
        w.deiconify()
        w.lift()
        w.focus_force()

    def _show_summary_dialog(self) -> None:
        """Displays or generates AI abstract and audience analysis."""
        fp = self.book.get("file_path") or ""
        b_id = self.book.get("id") or ""
        title = self.book.get("title") or "Buch"
        author = self.book.get("author") or "Unbekannt"

        w = tk.Toplevel(self)
        w.withdraw()
        w.title(f"✨ KI-Abstract: {title}")
        w.geometry("640x380")
        w.configure(bg="#0D1117")
        w.transient(self)

        hdr = tk.Frame(w, bg="#0D1117", padx=16, pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"✨ KI-Analyse & Abstract: {title}", font=("Segoe UI", 11, "bold"), bg="#0D1117", fg="#F0F6FC", anchor="w").pack(fill=tk.X)
        lbl_sub = tk.Label(hdr, text=f"von {author}", font=("Segoe UI", 8), bg="#0D1117", fg="#8B949E", anchor="w")
        lbl_sub.pack(fill=tk.X)

        txt_frame = tk.Frame(w, bg="#161B22", bd=1, relief="solid", highlightthickness=1, highlightbackground="#30363D")
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        txt_box = tk.Text(txt_frame, font=("Segoe UI", 10), bg="#161B22", fg="#F0F6FC", bd=0, wrap=tk.WORD, padx=12, pady=10)
        txt_sb = ttk.Scrollbar(txt_frame, orient="vertical", command=txt_box.yview, style="Vertical.TScrollbar")
        txt_box.configure(yscrollcommand=txt_sb.set)

        txt_sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _on_txt_wheel(e):
            txt_box.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"
        txt_box.bind("<MouseWheel>", _on_txt_wheel)
        w.bind("<MouseWheel>", _on_txt_wheel)

        # Check existing summary
        cached_summary = self.book.get("summary") or get_book_summary(b_id)
        if cached_summary:
            txt_box.insert("1.0", cached_summary)
            txt_box.configure(state=tk.DISABLED)
        else:
            txt_box.insert("1.0", "⏳ KI-Analyse wird durchgeführt (Ollama / Gemini)...\nBitte einen kurzen Moment Geduld.")
            txt_box.configure(state=tk.DISABLED)

            import threading
            def _fetch():
                res = generate_book_summary(b_id, title, author, fp)
                def _update():
                    if w.winfo_exists():
                        txt_box.configure(state=tk.NORMAL)
                        txt_box.delete("1.0", tk.END)
                        txt_box.insert("1.0", res)
                        txt_box.configure(state=tk.DISABLED)
                        self.book["summary"] = res
                w.after(0, _update)

            threading.Thread(target=_fetch, daemon=True).start()

        btn_bar = tk.Frame(w, bg="#0D1117", padx=16, pady=8)
        btn_bar.pack(fill=tk.X)

        def _refresh():
            txt_box.configure(state=tk.NORMAL)
            txt_box.delete("1.0", tk.END)
            txt_box.insert("1.0", "🔄 Aktualisiere KI-Analyse...\nBitte warten...")
            txt_box.configure(state=tk.DISABLED)

            import threading
            def _fetch_forced():
                res = generate_book_summary(b_id, title, author, fp, force_refresh=True)
                def _update():
                    if w.winfo_exists():
                        txt_box.configure(state=tk.NORMAL)
                        txt_box.delete("1.0", tk.END)
                        txt_box.insert("1.0", res)
                        txt_box.configure(state=tk.DISABLED)
                        self.book["summary"] = res
                        self._flash_toast("KI-Abstract aktualisiert!")
                w.after(0, _update)

            threading.Thread(target=_fetch_forced, daemon=True).start()

        tk.Button(btn_bar, text="🔄 Neu generieren", font=("Segoe UI", 9), bg="#21262D", fg="#C9D1D9", bd=1, relief="solid", padx=12, pady=5, cursor="hand2", command=_refresh).pack(side=tk.LEFT)
        tk.Button(btn_bar, text="Schließen", font=("Segoe UI", 9), bg="#21262D", fg="#8B949E", bd=0, padx=12, pady=5, cursor="hand2", command=w.destroy).pack(side=tk.RIGHT)

        w.update_idletasks()
        w.deiconify()
        w.lift()
        w.focus_force()


    def _open_pdf(self) -> None:
        fp = self.book.get("file_path")
        if fp and os.path.exists(fp):
            p = self.book.get("current_page", 1) or 1
            open_pdf_in_edge(fp, page=p)
        else:
            messagebox.showerror("Fehler", "PDF-Datei nicht gefunden.", parent=self)

    def _show_in_explorer(self) -> None:
        fp = self.book.get("file_path")
        if fp and os.path.exists(fp):
            subprocess.run(["explorer", "/select,", os.path.normpath(fp)])
        else:
            messagebox.showerror("Fehler", "Datei nicht gefunden.", parent=self)

    def _set_progress(self, page_num: int) -> None:
        b_id = self.book["id"]
        # Ensure book is on desk first
        if not self.book.get("is_on_desk"):
            toggle_desk_item(b_id, start_page=page_num)
            self.book["is_on_desk"] = 1
        else:
            update_reading_progress(b_id, page_num)

        tot_pages = self.book.get("page_count") or 1
        pct = min(100, int((page_num / tot_pages) * 100))
        self.book["current_page"] = page_num
        self.book["reading_progress"] = pct
        self.lbl_progress_val.configure(text=f"Seite {page_num} von {tot_pages} ({pct}%)", fg="#3FB950")
        if hasattr(self, "ent_quick_page"):
            self.ent_quick_page.delete(0, tk.END)
            self.ent_quick_page.insert(0, str(page_num))
        if hasattr(self, "btn_open"):
            self.btn_open.configure(text=f"🌐 In Edge öffnen (S. {page_num})")
        if hasattr(self, "btn_desk"):
            self.btn_desk.configure(text="❌ Vom Schreibtisch entfernen")
        self._flash_toast(f"✓ Seite {page_num} gespeichert! Öffnet sich in Edge.")
        if self.on_change:
            self.on_change()

    def _toggle_desk(self) -> None:
        b_id = self.book["id"]
        if not self.book.get("is_on_desk"):
            tot_p = self.book.get("page_count") or 99999
            cur_p = self.book.get("current_page") or 1
            page_input = simpledialog.askinteger(
                "Lesepult – Seite speichern",
                "Buch aufs Lesepult legen:\n\nAuf welcher Seite möchtest du starten / weiterlesen?",
                initialvalue=cur_p if cur_p > 0 else 1,
                minvalue=1,
                maxvalue=tot_p,
                parent=self,
            )
            if page_input is None:
                return
            start_p = page_input
            toggle_desk_item(b_id, start_page=start_p)
            self.book["is_on_desk"] = 1
            self.book["current_page"] = start_p
            tot_pages = self.book.get("page_count") or 1
            pct = min(100, int((start_p / tot_pages) * 100))
            self.book["reading_progress"] = pct
            if hasattr(self, "lbl_progress_val"):
                self.lbl_progress_val.configure(text=f"Seite {start_p} von {tot_pages} ({pct}%)", fg="#3FB950")
            if hasattr(self, "ent_quick_page"):
                self.ent_quick_page.delete(0, tk.END)
                self.ent_quick_page.insert(0, str(start_p))
            if hasattr(self, "btn_open"):
                self.btn_open.configure(text=f"🌐 In Edge öffnen (S. {start_p})")
            if hasattr(self, "btn_desk"):
                self.btn_desk.configure(text="❌ Vom Schreibtisch entfernen")
            self._flash_toast(f"✓ Aufs Lesepult gelegt (Seite {start_p} gespeichert)!")
        else:
            toggle_desk_item(b_id)
            self.book["is_on_desk"] = 0
            if hasattr(self, "btn_desk"):
                self.btn_desk.configure(text="📖 Auf Schreibtisch")
            self._flash_toast("Vom Schreibtisch entfernt.")
        if self.on_change:
            self.on_change()

    def destroy(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()

