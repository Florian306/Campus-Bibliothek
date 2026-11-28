"""Rule-based + LanguageTool German text, grammar, punctuation & academic style checker.
Works 100% without AI: combines fast local rules (commas, typography, academic style, readability)
with optional LanguageTool public API checks for deep spelling & grammar accuracy.
"""

from dataclasses import dataclass, field
import json
import re
import ssl
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple


@dataclass
class TextIssue:
    offset: int
    length: int
    category: str  # "spelling" | "grammar" | "style"
    rule_id: str
    message: str
    replacements: List[str] = field(default_factory=list)
    snippet: str = ""


@dataclass
class TextStats:
    words: int = 0
    sentences: int = 0
    chars: int = 0
    avg_sentence_len: float = 0.0
    flesch_de: float = 0.0


_FILLER_WORDS = {
    "eigentlich", "irgendwie", "quasi", "sozusagen", "halt", "eben",
    "vielleicht", "gewissermaßen", "bekanntlich", "natürlich", "einfach",
    "praktisch", "faktisch", "sozusagen", "irgendwann", "total", "ziemlich",
}

_SUBORDINATING_CONJUNCTIONS = (
    "dass", "weil", "obwohl", "obgleich", "während", "damit", "sodass",
    "sofern", "falls", "sobald", "seitdem", "nachdem", "bevor", "ehe",
    "indem", "weshalb", "warum", "wodurch", "wobei",
)

_COORDINATING_COMMA_CONJUNCTIONS = ("aber", "sondern", "denn", "jedoch")


def _count_syllables_de(word: str) -> int:
    w = re.sub(r"[^a-zäöüß]", "", word.lower())
    if not w:
        return 1
    groups = re.findall(r"[aeiouyäöü]+", w)
    return max(1, len(groups))


def compute_stats(text: str) -> TextStats:
    words_list = re.findall(r"\b[\wäöüÄÖÜß-]+\b", text)
    sentences_list = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    w_count = len(words_list)
    s_count = max(1, len(sentences_list)) if w_count > 0 else 0
    avg_len = round(w_count / s_count, 1) if s_count > 0 else 0.0

    if w_count > 0 and s_count > 0:
        syllables = sum(_count_syllables_de(w) for w in words_list)
        asl = w_count / s_count
        asw = syllables / w_count
        # Amstad formula for German Flesch Reading Ease
        flesch = round(max(0.0, min(100.0, 180.0 - asl - (58.5 * asw))), 1)
    else:
        flesch = 0.0

    return TextStats(
        words=w_count,
        sentences=len(sentences_list),
        chars=len(text),
        avg_sentence_len=avg_len,
        flesch_de=flesch,
    )


def _run_offline_rules(text: str) -> List[TextIssue]:
    issues: List[TextIssue] = []

    # 1. Double spaces
    for m in re.finditer(r" {2,}", text):
        issues.append(TextIssue(
            offset=m.start(),
            length=m.end() - m.start(),
            category="grammar",
            rule_id="DOUBLE_SPACE",
            message="Mehrfache Leerzeichen gefunden.",
            replacements=[" "],
            snippet=text[max(0, m.start() - 12):min(len(text), m.end() + 12)],
        ))

    # 2. Space before punctuation
    for m in re.finditer(r" +([,.;:!?])", text):
        issues.append(TextIssue(
            offset=m.start(),
            length=m.end() - m.start(),
            category="grammar",
            rule_id="SPACE_BEFORE_PUNCT",
            message=f"Kein Leerzeichen vor „{m.group(1)}“ setzen.",
            replacements=[m.group(1)],
            snippet=text[max(0, m.start() - 12):min(len(text), m.end() + 12)],
        ))

    # 3. Missing space after comma/semicolon/colon (excluding decimals like 3,5 or times 12:30)
    for m in re.finditer(r"([,;:])([A-Za-zÄÖÜäöüß])", text):
        issues.append(TextIssue(
            offset=m.start(),
            length=2,
            category="grammar",
            rule_id="MISSING_SPACE_AFTER_PUNCT",
            message=f"Nach „{m.group(1)}“ fehlt ein Leerzeichen.",
            replacements=[f"{m.group(1)} {m.group(2)}"],
            snippet=text[max(0, m.start() - 10):min(len(text), m.end() + 12)],
        ))

    # 4. Lowercase letter at start of sentence
    for m in re.finditer(r"(?:^|[.!?]\s+)([a-zäöü])", text):
        ch = m.group(1)
        pos = m.start(1)
        issues.append(TextIssue(
            offset=pos,
            length=1,
            category="spelling",
            rule_id="SENTENCE_START_UPPER",
            message="Satzanfang sollte großgeschrieben werden.",
            replacements=[ch.upper()],
            snippet=text[max(0, pos - 6):min(len(text), pos + 18)],
        ))

    # 5. Missing comma before subordinating / coordinating conjunctions
    conj_pattern = "|".join(_SUBORDINATING_CONJUNCTIONS + _COORDINATING_COMMA_CONJUNCTIONS)
    for m in re.finditer(rf"(\b[\wäöüÄÖÜß]+)\s+({conj_pattern})\b", text, re.IGNORECASE):
        prev_word = m.group(1).lower()
        conj = m.group(2)
        if prev_word in {"und", "oder", "sowie", "als", "wie", "so", "auch", "noch", "nur", "um"}:
            continue
        # Check if comma or punctuation is already right before
        before = text[max(0, m.start() - 2):m.start(2)].strip()
        if before.endswith((",", ";", ":", ".", "!", "?", "–", "-", "(")):
            continue
        issues.append(TextIssue(
            offset=m.start(1),
            length=m.end(2) - m.start(1),
            category="grammar",
            rule_id="COMMA_BEFORE_CONJUNCTION",
            message=f"Vor der Konjunktion „{conj}“ steht in der Regel ein Komma.",
            replacements=[f"{m.group(1)}, {conj}"],
            snippet=text[max(0, m.start() - 10):min(len(text), m.end() + 15)],
        ))

    # 6. Academic style: long sentences (> 28 words)
    for m in re.finditer(r"[^.!?\n]+[.!?]?", text):
        sent = m.group(0).strip()
        words = re.findall(r"\b[\wäöüÄÖÜß-]+\b", sent)
        if len(words) > 28:
            issues.append(TextIssue(
                offset=m.start(),
                length=min(len(sent), 45),
                category="style",
                rule_id="LONG_SENTENCE",
                message=f"Sehr langer Schachtelsatz ({len(words)} Wörter). Prüfe, ob sich der Satz teilen lässt.",
                replacements=[],
                snippet=sent[:60] + ("..." if len(sent) > 60 else ""),
            ))

    # 7. Academic style: filler words
    for m in re.finditer(r"\b([A-Za-zÄÖÜäöüß]+)\b", text):
        w = m.group(1)
        if w.lower() in _FILLER_WORDS:
            issues.append(TextIssue(
                offset=m.start(),
                length=len(w),
                category="style",
                rule_id="FILLER_WORD",
                message=f"Füllwort „{w}“ – in wissenschaftlichen Texten möglichst präzisieren oder streichen.",
                replacements=[],
                snippet=text[max(0, m.start() - 12):min(len(text), m.end() + 12)],
            ))

    # 8. Academic style: passive voice clusters
    for m in re.finditer(r"\b(wird|wurde|werden|wurden|worden)\b", text, re.IGNORECASE):
        issues.append(TextIssue(
            offset=m.start(),
            length=len(m.group(1)),
            category="style",
            rule_id="PASSIVE_VOICE",
            message="Passiv-Konstruktion – aktive Formulierungen wirken oft klarer und direkter.",
            replacements=[],
            snippet=text[max(0, m.start() - 15):min(len(text), m.end() + 15)],
        ))

    return issues


def _query_languagetool(text: str) -> List[TextIssue]:
    """Queries public LanguageTool API (de-DE) with strict timeout; returns [] on offline/error."""
    if not text.strip():
        return []
    # LanguageTool public API accepts up to ~20k chars comfortably per request
    payload_text = text[:18000]
    data = urllib.parse.urlencode({
        "text": payload_text,
        "language": "de-DE",
        "enabledOnly": "false",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.languagetool.org/v2/check",
        data=data,
        headers={
            "User-Agent": "CampusBibliothek-TextChecker/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=6.0, context=ctx) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    lt_issues: List[TextIssue] = []
    for m in res.get("matches", []):
        offset = int(m.get("offset", 0))
        length = int(m.get("length", 0))
        rule = m.get("rule", {})
        issue_type = (rule.get("issueType") or "").lower()
        cat_id = (rule.get("category", {}).get("id") or "").upper()

        if issue_type in ("misspelling", "typographical") or "TYPO" in cat_id or "SPELL" in cat_id:
            category = "spelling"
        elif issue_type in ("style", "locale-violation") or "STYLE" in cat_id:
            category = "style"
        else:
            category = "grammar"

        repls = [r.get("value", "") for r in m.get("replacements", [])[:5] if r.get("value") is not None]
        lt_issues.append(TextIssue(
            offset=offset,
            length=length,
            category=category,
            rule_id=rule.get("id", "LT_RULE"),
            message=m.get("message", "Prüfhinweis"),
            replacements=repls,
            snippet=payload_text[max(0, offset - 12):min(len(payload_text), offset + length + 12)],
        ))
    return lt_issues


def analyze_text(text: str, use_languagetool: bool = True) -> Tuple[List[TextIssue], TextStats]:
    """Runs offline rules + optional LanguageTool API and returns sorted, deduplicated issues + stats."""
    stats = compute_stats(text)
    if not text.strip():
        return [], stats

    issues = _run_offline_rules(text)

    if use_languagetool:
        try:
            lt_issues = _query_languagetool(text)
            # Deduplicate overlapping spans (prefer LanguageTool for spelling/grammar)
            occupied = {(i.offset, i.offset + i.length) for i in lt_issues}
            filtered_offline = []
            for off in issues:
                o_start, o_end = off.offset, off.offset + off.length
                overlaps = any(not (o_end <= s or o_start >= e) for s, e in occupied)
                if not overlaps or off.category == "style":
                    filtered_offline.append(off)
            issues = lt_issues + filtered_offline
        except Exception:
            pass

    issues.sort(key=lambda x: x.offset)
    return issues, stats
