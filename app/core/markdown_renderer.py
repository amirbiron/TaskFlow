"""רינדור Markdown ל-HTML עם סניטציה והדגשת קוד.

מבוסס על המסלול היציב של CodeBot: Python-Markdown -> bleach -> Pygments.
"""
from __future__ import annotations
import re
import secrets
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
    "b", "i", "strong", "em", "del", "ins", "s",
    "sup", "sub", "mark", "nav",
    "input",  # checkboxes של task lists
    "details", "summary",  # ::: details ... ::: (קיפול)
]

def _input_attr_filter(tag: str, name: str, value: str) -> bool:
    """מתיר רק <input type="checkbox" disabled checked? class?> - לא input אחר."""
    if name == "type":
        return value == "checkbox"
    if name in ("checked", "disabled", "class"):
        return True
    return False


ALLOWED_ATTRS = {
    "*": ["class", "id"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "code": ["class"],
    "span": ["class"],
    "pre": ["class"],
    # task lists - רק checkbox (האכיפה ב-_input_attr_filter)
    "input": _input_attr_filter,
    # ::: details ... :::
    "details": ["open", "class"],
    "summary": ["class"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


# ---------- Preprocess: ::: note / warning / ... ----------

_ADMONITION_RE = re.compile(
    r"^:::\s*(note|info|warning|important|danger|success|tip)\b[^\n]*\n(.*?)\n:::$",
    flags=re.DOTALL | re.MULTILINE,
)

# ::: details כותרת ... :::  →  <details><summary>כותרת</summary>...</details>
_DETAILS_RE = re.compile(
    r"^:::\s*details\b([^\n]*)\n(.*?)\n:::$",
    flags=re.DOTALL | re.MULTILINE,
)

# בלוקי קוד עטופים בגדר (``` או ~~~). תופסים אותם כדי לא לעבד admonitions בתוכם.
# CommonMark מתיר עד 3 רווחי הזחה לפני הגדר — pymdownx.superfences מכבד את זה,
# וגם ה-regex כאן חייב להתיישר עם זה כדי שה-stashing וספירת ה-checkboxes יהיו מסונכרנים.
_FENCED_CODE_RE = re.compile(
    r"^[ ]{0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^[ ]{0,3}(?P=fence)[ \t]*\r?$",
    flags=re.DOTALL | re.MULTILINE,
)

_TYPE_MAP = {
    "note": "info", "info": "info", "tip": "success", "success": "success",
    "warning": "warning", "important": "warning", "danger": "danger",
}


def _preprocess_markdown(text: str, clickable_tasks: bool = True) -> str:
    """ממיר בלוקי `::: type ... :::` ל-<div class='alert alert-*'>.

    מדלג על תוכן שבתוך בלוקי קוד עטופים (```/~~~) כדי לא לפגוע בהם.
    הפלייסהולדרים מקבלים נונס אקראי לכל קריאה כדי שלא ניתן יהיה
    להזריק אותם דרך קלט משתמש.

    clickable_tasks משפיע על checkboxes בתוך admonitions.
    """
    if not text:
        return ""

    # נונס ייחודי לכל קריאה - מונע התנגשות עם קלט משתמש זדוני
    nonce = secrets.token_hex(8)
    placeholder_re = re.compile(rf"\x00FENCE_{nonce}_(\d+)\x00")

    fences: list[str] = []

    def _stash(match: re.Match) -> str:
        idx = len(fences)
        fences.append(match.group(0))
        return f"\x00FENCE_{nonce}_{idx}\x00"

    def _restore_placeholder(match: re.Match) -> str:
        idx = int(match.group(1))
        # אינדקס לא חוקי = להשאיר כמו שהוא (לא ליפול עם IndexError)
        return fences[idx] if 0 <= idx < len(fences) else match.group(0)

    # שלב 1: שמור בלוקי קוד עטופים מחוץ לטקסט.
    stashed = _FENCED_CODE_RE.sub(_stash, text)

    # שלב 2: עיבוד admonitions על הטקסט הנקי מבלוקי קוד.
    def _replace(match: re.Match) -> str:
        kind = match.group(1).lower()
        body = match.group(2).strip()
        # אם בגוף ה-admonition יש בלוקי קוד שנשמרו - מחזירים אותם
        # לפני הרינדור הפנימי, כדי שמנוע ה-Markdown יוכל לעבד אותם.
        body = placeholder_re.sub(_restore_placeholder, body)
        css_class = _TYPE_MAP.get(kind, "info")
        # אותן יכולות שתומכות ב-task lists גם בתוך admonitions, כדי
        # שמספר ה-checkboxes ב-HTML יתאים לסדר ההתאמות ב-_TASK_RE על המקור.
        inner = markdown.markdown(
            body,
            extensions=[
                "nl2br", "pymdownx.superfences", "tables", "pymdownx.tasklist",
                "pymdownx.tilde", "pymdownx.mark",
            ],
            extension_configs={
                "pymdownx.tasklist": {
                    "custom_checkbox": False,
                    "clickable_checkbox": clickable_tasks,
                },
                "pymdownx.tilde": {
                    "smart_delete": True,
                    "subscript": False,
                },
            },
        )
        clean_inner = bleach.clean(
            inner,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )
        # עוטפים בשורות ריקות מסביב כדי ש-Python-Markdown יזהה את ה-div
        # כבלוק-HTML עצמאי ולא יבלע פסקאות שמופיעות אחריו ללא שורה ריקה.
        return f'\n\n<div class="alert alert-{css_class}">{clean_inner}</div>\n\n'

    processed = _ADMONITION_RE.sub(_replace, stashed)

    # שלב 2.5: עיבוד `::: details כותרת ... :::` ל-<details>/<summary>.
    def _replace_details(match: re.Match) -> str:
        title = (match.group(1) or "").strip() or "לחצו להצגה"
        body = match.group(2).strip()
        # אם בגוף יש בלוקי קוד שנשמרו - מחזירים אותם לפני הרינדור הפנימי.
        body = placeholder_re.sub(_restore_placeholder, body)
        inner = markdown.markdown(
            body,
            extensions=[
                "nl2br", "pymdownx.superfences", "tables",
                "pymdownx.tasklist", "pymdownx.tilde", "pymdownx.mark",
            ],
            extension_configs={
                "pymdownx.tasklist": {
                    "custom_checkbox": False,
                    "clickable_checkbox": clickable_tasks,
                },
                "pymdownx.tilde": {
                    "smart_delete": True,
                    "subscript": False,
                },
            },
        )
        clean_inner = bleach.clean(
            inner,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )
        # escape לכותרת כדי למנוע XSS דרך התוכן בשורת ה-:::.
        safe_title = (title.replace("&", "&amp;").replace("<", "&lt;")
                            .replace(">", "&gt;").replace('"', "&quot;"))
        return (
            f'\n\n<details class="markdown-details">'
            f'<summary class="markdown-summary">{safe_title}</summary>'
            f'<div class="details-content">{clean_inner}</div>'
            f'</details>\n\n'
        )

    processed = _DETAILS_RE.sub(_replace_details, processed)

    # שלב 3: החזרת בלוקי קוד שנותרו (כאלה שלא היו בתוך admonition/details).
    return placeholder_re.sub(_restore_placeholder, processed)


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

def markdown_to_html(
    text: str,
    include_toc: bool = False,
    clickable_tasks: bool = True,
) -> Tuple[str, str]:
    """ממיר Markdown ל-HTML נקי. מחזיר (html, toc_html).

    clickable_tasks=False: ה-checkboxes יוצגו כ-disabled (תצוגה בלבד).
    מתאים למקומות שבהם אין endpoint לשמירה (למשל הערות לקוח).
    """
    if not text:
        return "", ""

    processed = _preprocess_markdown(text, clickable_tasks=clickable_tasks)

    md = markdown.Markdown(
        extensions=[
            # superfences במקום fenced_code: עוקב CommonMark, מכבד הזחה של עד
            # 3 רווחים לפני ה-fence (נדרש לבלוקי קוד בתוך פריטי רשימה).
            "pymdownx.superfences",
            "tables",
            "nl2br",
            "toc",
            # highlight הוא המחליף הרשמי של codehilite ב-pymdown-extensions,
            # והיחיד ש-superfences מתחשב בהגדרותיו עבור fenced blocks
            # (codehilite אינו נתמך עם superfences מאז גרסה 7.0).
            "pymdownx.highlight",
            "attr_list",
            "pymdownx.tasklist",
            "pymdownx.tilde",   # ~~strikethrough~~  →  <del>...</del>
            "pymdownx.mark",    # ==highlight==      →  <mark>...</mark>
        ],
        extension_configs={
            "pymdownx.highlight": {
                "css_class": "highlight",
                "linenums": False,
                # ניחוש שפה אוטומטי כש-fence ללא תווית, כדי ש-Pygments
                # יעטוף tokens ב-<span>. בלי spans, RTL על בלוק מעורב
                # (פרוזה עברית + קוד אנגלי) מבלבל את אלגוריתם ה-bidi כי
                # הכל פיסקה אחת ארוכה. "block" מגביל לבלוקים בלבד -
                # inline code (`x`) לא צריך highlighting.
                "guess_lang": "block",
                "use_pygments": True,
            },
            "toc": {
                "title": "תוכן עניינים",
                "toc_depth": 3,
            },
            "pymdownx.tasklist": {
                "custom_checkbox": False,             # input רגיל (בלי label/span עוטף)
                "clickable_checkbox": clickable_tasks,  # True=ללא disabled (לחיץ); False=disabled
            },
            "pymdownx.tilde": {
                # רק קו חוצה (~~...~~). בלי ~subscript~ — מונע התנגשות עם
                # שימושים שגרתיים של "~" בטקסט עברי/בנתיבים.
                "smart_delete": True,
                "subscript": False,
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

    # bleach מפעיל את _input_attr_filter רק כשיש attribute. <input> ללא
    # attributes חומק - וברירת המחדל ב-HTML היא type="text". לכן מסירים
    # ידנית כל <input> שאין בו type="checkbox".
    clean = re.sub(
        r'<input(?![^>]*\btype\s*=\s*["\']?checkbox["\']?)[^>]*/?>',
        "",
        clean,
        flags=re.IGNORECASE,
    )

    clean = _force_noopener(clean)

    # עטיפת טבלאות ב-div גלילה אופקית, כדי שטבלאות רחבות לא ייחתכו במובייל
    clean = re.sub(
        r"<table\b[^>]*>.*?</table>",
        lambda m: f'<div class="markdown-table-wrap">{m.group(0)}</div>',
        clean,
        flags=re.IGNORECASE | re.DOTALL,
    )

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


# ---------- Task list toggle ----------

# מתאים לתחביר של pymdownx.tasklist:
# - שורות שמתחילות בתבליט (-, *, +) או רשימה ממוספרת (1. וכו'), עם רווח/טאב,
#   ואז [ ] או [x]/[X]. תופס גם הזחה (תת-משימות) וגם blockquotes (> - [ ] foo).
# - חשוב: [ \t]+ ולא \s+ אחרי התבליט - אסור שייתפס newline (שיגרום
#   להתאמה חוצת-שורות שלא מייצרת checkbox ב-HTML).
# - תוכן בתוך fenced code blocks מסונן בנפרד למטה.
_TASK_RE = re.compile(
    r"^(?P<prefix>(?:[ \t]*>[ \t]?)*[ \t]*(?:[-*+]|\d+\.)[ \t]+)\[(?P<state>[ xX])\]",
    flags=re.MULTILINE,
)


def _task_match_positions(text: str) -> list[re.Match]:
    """כל ההתאמות של task list שייצרו checkbox ב-HTML.

    מסנן התאמות שנמצאות בתוך fenced code blocks (``` או ~~~), כי שם
    pymdownx.tasklist לא מייצר checkbox - ויש להבטיח שהאינדקס המחושב
    בצד הלקוח (לפי DOM) יתאים לזה שבצד השרת.
    """
    blocked: list[tuple[int, int]] = [
        (m.start(), m.end()) for m in _FENCED_CODE_RE.finditer(text)
    ]

    def _inside_code(pos: int) -> bool:
        return any(s <= pos < e for s, e in blocked)

    return [m for m in _TASK_RE.finditer(text) if not _inside_code(m.start())]


def toggle_task_in_markdown(text: str, index: int, checked: bool) -> str:
    """מחליף את המצב של ה-checkbox ה-N (0-based) בטקסט Markdown.

    מחזיר את הטקסט החדש. אם האינדקס מחוץ לטווח - זורק IndexError.
    """
    if not text:
        raise IndexError("no tasks in text")

    matches = _task_match_positions(text)
    if index < 0 or index >= len(matches):
        raise IndexError(f"task index {index} out of range (found {len(matches)})")

    m = matches[index]
    new_state = "x" if checked else " "
    start, end = m.start("state"), m.end("state")
    return text[:start] + new_state + text[end:]


@lru_cache(maxsize=1)
def pygments_css(style_name: str = "default", css_class: str = ".highlight") -> str:
    """מחזיר את ה-CSS של ערכת הצבעים. ממוטמן כי הוא קבוע לאורך חיי התהליך."""
    try:
        style = get_style_by_name(style_name)
    except Exception:
        style = get_style_by_name("default")
    formatter = HtmlFormatter(style=style, cssclass=css_class.lstrip("."))
    return formatter.get_style_defs(css_class)
