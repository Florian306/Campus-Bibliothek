"""LaTeX Math Renderer for PySide6 Desktop UI.
Renders LaTeX math formulas into base64-encoded PNG images using matplotlib mathtext,
and formats mixed text containing LaTeX into inline HTML supported by Qt QLabel/QTextBrowser.
"""

import html
import io
import re
import base64
from typing import Dict, Tuple

# Lazy-loaded matplotlib handles to prevent any import crash during app bootstrap
_MPL_AVAILABLE = None
_Figure = None
_FigureCanvasAgg = None


def _ensure_matplotlib():
    global _MPL_AVAILABLE, _Figure, _FigureCanvasAgg
    if _MPL_AVAILABLE is None:
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            _Figure = Figure
            _FigureCanvasAgg = FigureCanvasAgg
            _MPL_AVAILABLE = True
        except Exception:
            _MPL_AVAILABLE = False
    return _MPL_AVAILABLE


# In-memory LRU-like cache for rendered formulas to ensure 0-overhead instant lookups
_MATH_IMG_CACHE: Dict[Tuple[str, str, int], str] = {}

# Regex for explicit math delimiters: $$...$$, $...$, \(...\), \[...\]
MATH_SPLIT_REGEX = re.compile(r'(\$\$[\s\S]+?\$\$|\$[^\$\n]+?\$|\\\(.+?\\\)|\\\[[\s\S]+?\\\])')


def clean_umlauts(text: str) -> str:
    """Restores German umlauts from ASCII or TeX escaped forms."""
    if not text:
        return ""
    replacements = [
        (r'\\\"a|"a', 'ä'),
        (r'\\\"o|"o', 'ö'),
        (r'\\\"u|"u', 'ü'),
        (r'\\\"A|"A', 'Ä'),
        (r'\\\"O|"O', 'Ö'),
        (r'\\\"U|"U', 'Ü'),
        (r'\\\"s|"s|\\ss\b', 'ß'),
    ]
    for pattern, rep in replacements:
        text = re.sub(pattern, rep, text)
    return text


def wrap_academic_math(text: str) -> str:
    """Cleans up text, quotes around formulas, TeX umlauts, and wraps raw math expressions."""
    if not text:
        return ""

    # 1. Clean TeX/ASCII umlauts (e.g. f"ur -> für, Verst"andnis -> Verständnis)
    text = clean_umlauts(text)

    # 2. Fix awkward quotes around formulas: ' X + 5 = 8 ' -> $X + 5 = 8$
    text = re.sub(r"['\"`]\s*(\$?[A-Za-z0-9\s\+\-\*\/\=\<\>\(\)\:\^\_\\\|!]+\$?)\s*['\"`]", r" $\1$ ", text)

    # 3. Clean consecutive dollar signs like $$ at end or middle of inline math: $A(x) : x + 5 = 8$$ -> $A(x) : x + 5 = 8$
    text = re.sub(r'\${2,}', '$', text)

    # 4. If odd number of $, fix trailing or opening $
    if text.count('$') % 2 != 0:
        if text.endswith('$'):
            text = text[:-1]
        elif text.startswith('$'):
            text = text[1:]

    # 5. If no explicit $ delimiters present:
    if "$" not in text and r"\(" not in text and r"\[" not in text:
        s = text.strip()
        # Full mathematical statement (e.g. A(x) : x + 5 = 8 or A(x) : x + 5 \ne 8)
        if re.match(r'^[A-Za-z]\([a-z]\)\s*:\s*[0-9a-zA-Z\s\+\-\*\/\=\<\>\^\_\\\|!]+$', s):
            text = f"${s}$"
        else:
            # Formula preceding German qualifier (e.g. A(x) : x^2 \ge 0 für alle...)
            m = re.match(r'^([A-Za-z]\([a-z]\)\s*:\s*[-0-9a-zA-Z\s\+\*\/\=\<\>\^\_\\\|!]+?)(?=\s+(?:für|mit|wobei|wenn|falls|da|und|oder|gilt|\.|$))(.*)$', s)
            if m:
                text = f"${m.group(1).strip()}$ {m.group(2).strip()}"
            else:
                # Standalone equations and relations
                text = re.sub(r'(\b[a-zA-Z]\s*[\+\-\*\/]\s*[0-9a-zA-Z]+\s*(?:=|<|>|!=|<=|>=|\\ne|\\neq|\\ge|\\geq|\\le|\\leq)\s*[0-9a-zA-Z]+)', r'$\1$', text)
                # Standalone powers/inequalities: x^2 >= 0
                text = re.sub(r'(\b[a-zA-Z]\^[0-9a-zA-Z]+(?:\s*(?:>=|<=|>|<|=|!=|\\ge|\\le|\\geq|\\leq)\s*[-0-9a-zA-Z]+)?)', r'$\1$', text)

    # Clean double spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def render_math_to_base64(formula: str, color: str = "#E0E8F5", fontsize: int = 12, dpi: int = 135) -> str:
    """Renders a LaTeX math expression into a base64 encoded PNG data URI."""
    formula = formula.strip().strip("$").strip()
    if formula.startswith(r"\(") and formula.endswith(r"\)"):
        formula = formula[2:-2].strip()
    elif formula.startswith(r"\[") and formula.endswith(r"\]"):
        formula = formula[2:-2].strip()

    if not formula:
        return ""

    # Normalize common text symbols to Matplotlib mathtext equivalents
    formula = formula.replace(">=", r"\geq ").replace("<=", r"\leq ").replace("!=", r"\neq ")
    formula = re.sub(r'\\ge\b', r'\\geq', formula)
    formula = re.sub(r'\\le\b', r'\\leq', formula)
    formula = re.sub(r'\\ne\b', r'\\neq', formula)
    formula = re.sub(r'\\implies\b', r'\\Rightarrow', formula)
    formula = re.sub(r'\\iff\b', r'\\Leftrightarrow', formula)
    formula = re.sub(r'\\land\b', r'\\wedge', formula)
    formula = re.sub(r'\\lor\b', r'\\vee', formula)

    cache_key = (formula, color, fontsize)
    if cache_key in _MATH_IMG_CACHE:
        return _MATH_IMG_CACHE[cache_key]

    if not _ensure_matplotlib():
        return ""

    try:
        fig = _Figure(facecolor="none")
        canvas = _FigureCanvasAgg(fig)
        fig.text(0.5, 0.5, f"${formula}$", color=color, fontsize=fontsize, ha="center", va="center")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.03, dpi=dpi)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        uri = f"data:image/png;base64,{b64}"
        _MATH_IMG_CACHE[cache_key] = uri
        return uri
    except Exception:
        # Fallback to empty string on fatal parse error
        return ""


def format_latex_html(
    text: str,
    text_color: str = "#E0E8F5",
    math_color: str = "#E0E8F5",
    font_size: int = 11,
    detect_implicit: bool = True
) -> str:
    """Converts a string with mixed text and LaTeX into rich HTML with embedded base64 math images."""
    if not text:
        return ""

    if detect_implicit:
        text = wrap_academic_math(text)
    else:
        text = clean_umlauts(text)

    parts = MATH_SPLIT_REGEX.split(text)
    html_out = []

    for part in parts:
        if not part:
            continue
        is_math = (
            (part.startswith("$") and part.endswith("$")) or
            (part.startswith(r"\(") and part.endswith(r"\)")) or
            (part.startswith(r"\[") and part.endswith(r"\]"))
        )
        if is_math:
            img_uri = render_math_to_base64(part, color=math_color, fontsize=font_size)
            if img_uri:
                html_out.append(f'<img src="{img_uri}" align="middle" style="vertical-align: -2px; margin: 0 1px;" />')
            else:
                clean_raw = part.strip("$")
                html_out.append(f'<span style="color: {math_color}; font-family: monospace;">{html.escape(clean_raw)}</span>')
        else:
            escaped = html.escape(part).replace("\n", "<br>")
            html_out.append(escaped)

    return "".join(html_out)
