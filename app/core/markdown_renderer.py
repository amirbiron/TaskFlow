"""רינדור Markdown ל-HTML עם סניטציה והדגשת קוד.

מבוסס על המסלול היציב של CodeBot: Python-Markdown -> bleach -> Pygments.
"""
from __future__ import annotations
import re
from functools import lru_cache
from typing import Tuple

import bleach
import markdown
from pygments.formatters import HtmlFormatter
from pygments.styles import get_style_by_name


# ---------- Allowlist לסניטציה ----------

ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "div", "span", "p", "br",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "code", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "blockquote", "ul", "ol", "li", "hr", "a",
    "b", "i", "strong", "em", "del", "ins",
    "sup", "sub", "mark", "nav",
]

ALLOWED_ATTRS = {
    "*": ["class", "id"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "code": ["class"],
    "span": ["class"],
    "pre": ["class"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


# ---------- Preprocess: ::: note / warning / ... ----------

_ADMONITION_RE = re.compile(
    r"^:::\s*(note|info|warning|important|danger|success|tip)\b[^\n]*\n(.*?)\n:::$",
    flags=re.DOTALL | re.MULTILINE,
)

# בלוקי קוד עטופים בגדר (``` או ~~~). תופסים אותם כדי לא לעבד admonitions בתוכם.
_FENCED_CODE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)\s*$",
    flags=re.DOTALL | re.MULTILINE,
)

_TYPE_MAP = {
    "note": "info", "info": "info", "tip": "success", "success": "success",
    "warning": "warning", "important": "warning", "danger": "danger",
}


def _preprocess_markdown(text: str) -> str:
    """ממיר בלוקי `::: type ... :::` ל-<div class='alert alert-*'>.

    מדלג על תוכן שבתוך בלוקי קוד עטופים (```/~~~) כדי לא לפגוע בהם.
    """
    if not text:
        return ""

    # שלב 1: שמור בלוקי קוד מחוץ למקום ובמקומם הנח placeholder ייחודי.
    fences: list[str] = []

    def _stash(match: re.Match) -> str:
        idx = len(fences)
        fences.append(match.group(0))
        # מחרוזת פלייסהולדר בלי ::: שלא תיתפס ע"י ה-regex של ה-admonitions.
        return f"\x00FENCE{idx}\x00"

    stashed = _FENCED_CODE_RE.sub(_stash, text)

    # שלב 2: עיבוד ה-admonitions על הטקסט "הנקי" מבלוקי הקוד.
    def _replace(match: re.Match) -> str:
        kind = match.group(1).lower()
        body = match.group(2).strip()
        css_class = _TYPE_MAP.get(kind, "info")
        inner = markdown.markdown(body, extensions=["nl2br"])
        clean_inner = bleach.clean(
            inner,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )
        return f'<div class="alert alert-{css_class}">{clean_inner}</div>'

    processed = _ADMONITION_RE.sub(_replace, stashed)

    # שלב 3: החזרת בלוקי הקוד המקוריים למקומם.
    def _restore(match: re.Match) -> str:
        return fences[int(match.group(1))]

    return re.sub(r"\x00FENCE(\d+)\x00", _restore, processed)


# ---------- אבטחה: rel="noopener noreferrer" על target="_blank" ----------

def _force_noopener(html: str) -> str:
    def _fix(m: re.Match) -> str:
        tag = m.group(0)
        if re.search(r'\srel\s*=\s*(["\'])', tag):
            return re.sub(
                r'\srel\s*=\s*(["\']).*?\1',
                ' rel="noopener noreferrer"',
                tag,
                count=1,
                flags=re.IGNORECASE,
            )
        return tag.replace('target="_blank"', 'target="_blank" rel="noopener noreferrer"')

    return re.sub(r'<a\s[^>]*target="_blank"[^>]*>', _fix, html)


# ---------- Main API ----------

def markdown_to_html(text: str, include_toc: bool = False) -> Tuple[str, str]:
    """ממיר Markdown ל-HTML נקי. מחזיר (html, toc_html)."""
    if not text:
        return "", ""

    processed = _preprocess_markdown(text)

    md = markdown.Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "nl2br",
            "toc",
            "codehilite",
            "attr_list",
        ],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "linenums": False,
                "guess_lang": False,
            },
            "toc": {
                "title": "תוכן עניינים",
                "toc_depth": 3,
            },
        },
    )

    raw = md.convert(processed)

    # רשת ביטחון: הסרת בלוקי script/style גם אם נשתחלו דרך הסניטציה
    raw = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    clean = bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )

    clean = _force_noopener(clean)

    toc_html = ""
    if include_toc and getattr(md, "toc", ""):
        toc_html = bleach.clean(
            md.toc,
            tags=["div", "nav", "ul", "li", "a"],
            attributes={"a": ["href", "title"], "*": ["class", "id"]},
            protocols=["http", "https"],
            strip=True,
        )

    return clean, toc_html


@lru_cache(maxsize=1)
def pygments_css(style_name: str = "default", css_class: str = ".highlight") -> str:
    """מחזיר את ה-CSS של ערכת הצבעים. ממוטמן כי הוא קבוע לאורך חיי התהליך."""
    try:
        style = get_style_by_name(style_name)
    except Exception:
        style = get_style_by_name("default")
    formatter = HtmlFormatter(style=style, cssclass=css_class.lstrip("."))
    return formatter.get_style_defs(css_class)
