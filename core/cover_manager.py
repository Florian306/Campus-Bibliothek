"""High-performance cover thumbnail generator and SQLite BLOB persistence.
Extracts page 0 of PDFs via PyMuPDF or generates stylish academic book jackets.
Zero disk clutter: All covers are stored directly inside SQLite database with in-memory LRU cache.
"""

import os
import re
import io
import hashlib
from typing import Any, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from core.config import get_app_dir
from core.library_db import save_book_cover_blob, get_book_cover_blob, delete_book_cover_blob

THUMB_WIDTH = 135
THUMB_HEIGHT = 190

# In-memory fast cache to keep shelf scrolling 60+ FPS without repeated DB reads
_MEMORY_CACHE: Dict[str, Image.Image] = {}
_MAX_MEMORY_ITEMS = 600

# Faculty color palette for styled fallback jackets
FACULTY_COLORS = {
    "Informatik & Programmierung": ("#0D2847", "#58A6FF"),
    "Geschichte & Politik": ("#3B2A0A", "#D29922"),
    "Biologie & Lebenswissenschaften": ("#0E331E", "#3FB950"),
    "Geowissenschaften & Geologie": ("#123624", "#7EE787"),
    "Mathematik": ("#2B1B47", "#BC8CFF"),
    "Chemie": ("#3E200C", "#F0883E"),
    "Physik & Astronomie": ("#0F2D4A", "#79C0FF"),
    "Psychologie & Soziologie": ("#3D142B", "#F778BA"),
    "Medizin & Pharmazie": ("#3D1418", "#FF7B72"),
    "Rechtswissenschaften & Jura": ("#36220E", "#FFA657"),
    "Wirtschaftswissenschaften": ("#382E0B", "#E3B341"),
    "Sprach- & Literaturwissenschaft": ("#132B45", "#A5D6FF"),
    "Pädagogik & Schule": ("#16361C", "#56D364"),
    "Philosophie & Religion": ("#36152F", "#DB61A2"),
    "Ingenieurwissenschaften & Technik": ("#1F242C", "#8B949E"),
    "Sonstiges": ("#161B22", "#6E7681"),
}


def get_cover_path(book_id: str) -> str:
    """Legacy helper: returns empty path as covers are stored as BLOBs in SQLite."""
    return ""


def generate_fallback_cover(title: str, author: str, category: str = "Sonstiges") -> Image.Image:
    """Creates a sleek, modern academic book jacket image when no PDF cover exists."""
    bg_hex, accent_hex = FACULTY_COLORS.get(category, ("#161B22", "#58A6FF"))
    
    img = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), color=bg_hex)
    draw = ImageDraw.Draw(img)

    # Book spine line on the left
    draw.line([(6, 0), (6, THUMB_HEIGHT)], fill=accent_hex, width=3)
    # Subtle inner border
    draw.rectangle([0, 0, THUMB_WIDTH - 1, THUMB_HEIGHT - 1], outline="#30363D", width=1)
    # Accent top banner
    draw.rectangle([8, 10, THUMB_WIDTH - 8, 14], fill=accent_hex)

    # Clean typography
    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 11)
        font_author = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 10)
        font_cat = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 9)
    except Exception:
        font_title = font_author = font_cat = ImageFont.load_default()

    # Truncate and wrap title
    words = (title or "Ohne Titel").split()
    lines = []
    curr = ""
    for w in words:
        if len(curr) + len(w) + 1 <= 15:
            curr = f"{curr} {w}".strip()
        else:
            if curr:
                lines.append(curr)
            curr = w
        if len(lines) >= 4:
            break
    if curr and len(lines) < 4:
        lines.append(curr)

    y = 26
    for line in lines[:4]:
        draw.text((12, y), line[:18], font=font_title, fill="#F0F6FC")
        y += 16

    # Author line at bottom
    if author and author != "Unbekannt":
        draw.text((12, THUMB_HEIGHT - 34), author[:17], font=font_author, fill="#8B949E")
        
    # Faculty tag at very bottom
    draw.text((12, THUMB_HEIGHT - 18), category[:17], font=font_cat, fill=accent_hex)

    return img


def get_cached_cover(book_id: str) -> Optional[Image.Image]:
    """Returns PIL Image from memory cache or SQLite database."""
    if book_id in _MEMORY_CACHE:
        return _MEMORY_CACHE[book_id]

    blob = get_book_cover_blob(book_id)
    if blob:
        try:
            img = Image.open(io.BytesIO(blob)).copy()
            if img.size != (THUMB_WIDTH, THUMB_HEIGHT):
                canvas = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), "#12171F")
                img.thumbnail((THUMB_WIDTH, THUMB_HEIGHT), Image.Resampling.LANCZOS)
                canvas.paste(img, ((THUMB_WIDTH - img.width) // 2, (THUMB_HEIGHT - img.height) // 2))
                img = canvas

            if len(_MEMORY_CACHE) >= _MAX_MEMORY_ITEMS:
                _MEMORY_CACHE.pop(next(iter(_MEMORY_CACHE)))
            _MEMORY_CACHE[book_id] = img
            return img
        except Exception:
            return None
    return None


def find_best_cover_page(doc: Any) -> int:
    """Intelligently detects true front cover, bypassing disclaimers or blank pages."""
    num_pages = min(len(doc), 4)
    if num_pages == 1:
        return 0

    best_idx = 0
    best_score = -999.0
    for idx in range(num_pages):
        page = doc[idx]
        text = page.get_text().lower()
        imgs = page.get_images()

        score = float(len(imgs) * 35 + (25 - idx * 6))
        for dw in [
            "downloaded from", "downloaded by", "springerlink", "springer nature",
            "taylor & francis", "licensed to", "terms of use", "open access",
            "this page intentionally left blank", "inhaltsverzeichnis", "table of contents",
            "vorwort", "preface", "disclaimer", "all rights reserved"
        ]:
            if dw in text:
                score -= 90.0

        if len(text.strip()) > 1200:
            score -= 40.0

        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx


def trim_whitespace(img: Image.Image) -> Image.Image:
    """Crops excess white or uniform borders around book cover graphics."""
    try:
        from PIL import ImageOps
        bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
        diff = ImageOps.difference(img, bg)
        bbox = diff.getbbox()
        if bbox:
            w_crop = bbox[2] - bbox[0]
            h_crop = bbox[3] - bbox[1]
            if w_crop > img.width * 0.65 and h_crop > img.height * 0.65:
                return img.crop(bbox)
    except Exception:
        pass
    return img


def extract_and_cache_cover(
    book_id: str,
    file_path: str,
    title: str,
    author: str,
    category: str = "Sonstiges",
    isbn: Optional[str] = None
) -> Image.Image:
    """Extracts best cover page from PDF, trims margins, and caches as BLOB in SQLite."""
    cached = get_cached_cover(book_id)
    if cached:
        return cached

    # Extract from PDF
    if file_path and os.path.exists(file_path):
        try:
            import pymupdf
            doc = pymupdf.open(file_path)
            if len(doc) > 0:
                best_page_idx = find_best_cover_page(doc)
                page = doc[best_page_idx]
                pix = page.get_pixmap(dpi=84)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                doc.close()

                img = trim_whitespace(img)
                img.thumbnail((THUMB_WIDTH, THUMB_HEIGHT), Image.Resampling.LANCZOS)

                canvas = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), "#12171F")
                offset_x = (THUMB_WIDTH - img.width) // 2
                offset_y = (THUMB_HEIGHT - img.height) // 2
                canvas.paste(img, (offset_x, offset_y))

                draw = ImageDraw.Draw(canvas)
                draw.rectangle([0, 0, THUMB_WIDTH - 1, THUMB_HEIGHT - 1], outline="#30363D", width=1)

                # Persist in SQLite
                buf = io.BytesIO()
                canvas.save(buf, format="PNG", optimize=True)
                save_book_cover_blob(book_id, buf.getvalue())

                _MEMORY_CACHE[book_id] = canvas
                return canvas
            doc.close()
        except Exception:
            pass

    # Fallback to OpenLibrary if ISBN is present
    if isbn:
        clean_isbn = re.sub(r"\D", "", isbn)
        if len(clean_isbn) in (10, 13):
            try:
                import urllib.request
                url = f"https://covers.openlibrary.org/b/isbn/{clean_isbn}-M.jpg"
                req = urllib.request.Request(url, headers={"User-Agent": "Buchsortierer/1.0"})
                with urllib.request.urlopen(req, timeout=1.8) as resp:
                    if resp.status == 200:
                        data = resp.read()
                        if len(data) > 1500:  # Valid non-1x1 pixel image
                            ol_img = Image.open(io.BytesIO(data)).convert("RGB")
                            ol_img.thumbnail((THUMB_WIDTH, THUMB_HEIGHT), Image.Resampling.LANCZOS)
                            canvas = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), "#12171F")
                            canvas.paste(ol_img, ((THUMB_WIDTH - ol_img.width) // 2, (THUMB_HEIGHT - ol_img.height) // 2))
                            draw = ImageDraw.Draw(canvas)
                            draw.rectangle([0, 0, THUMB_WIDTH - 1, THUMB_HEIGHT - 1], outline="#30363D", width=1)

                            buf = io.BytesIO()
                            canvas.save(buf, format="PNG", optimize=True)
                            save_book_cover_blob(book_id, buf.getvalue())

                            _MEMORY_CACHE[book_id] = canvas
                            return canvas
            except Exception:
                pass

    # Return styled fallback without writing a permanent dummy file to disk
    return generate_fallback_cover(title, author, category)


def get_or_create_cover_image(book_id: str, file_path: str, title: str, author: str, category: str = "Sonstiges") -> Image.Image:
    """Legacy helper: gets cached cover or extracts immediately."""
    cached = get_cached_cover(book_id)
    if cached:
        return cached
    return extract_and_cache_cover(book_id, file_path, title, author, category)


def migrate_disk_covers_to_db() -> None:
    """Migrates existing PNG covers from disk folder into SQLite DB and removes the folder."""
    covers_dir = os.path.join(get_app_dir(), "covers")
    if not os.path.isdir(covers_dir):
        return
    try:
        files = [f for f in os.listdir(covers_dir) if f.endswith(".png")]
        if not files:
            import shutil
            shutil.rmtree(covers_dir, ignore_errors=True)
            return

        for fname in files:
            book_id = fname[:-4]
            fpath = os.path.join(covers_dir, fname)
            try:
                with open(fpath, "rb") as f:
                    blob = f.read()
                if blob and len(blob) > 200:
                    save_book_cover_blob(book_id, blob)
                os.remove(fpath)
            except Exception:
                pass

        try:
            os.rmdir(covers_dir)
        except Exception:
            import shutil
            shutil.rmtree(covers_dir, ignore_errors=True)
    except Exception:
        pass


# Run transparent migration on startup to eliminate the covers/ folder from disk
migrate_disk_covers_to_db()
