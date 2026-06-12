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
    r"^:::[ \t]*"
    r"(?P<kind>note|info|tip|success|warning|important|danger|"
    r"question|example|quote|experimental|deprecated|todo|abstract)\b"
    r"(?P<title>[^\n]*)\n"
    r"(?P<body>.*?)\n:::[ \t]*$",
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

# לכל סוג בלוק: (מחלקת CSS, כותרת ברירת-מחדל בעברית, אייקון).
# הכותרת והאייקון מוצגים בראש הבלוק; אפשר לדרוס את הכותרת ע"י טקסט
# אחרי שם הסוג בשורת ה-::: (כמו ב-details).
_ADMONITION_TYPES = {
    "note":         ("note",         "הערה",          "📝"),
    "info":         ("info",         "מידע",          "ℹ️"),
    "tip":          ("tip",          "טיפ",           "💡"),
    "success":      ("success",      "הצלחה",         "✅"),
    "warning":      ("warning",      "אזהרה",         "⚠️"),
    "important":    ("important",    "חשוב",          "❗"),
    "danger":       ("danger",       "סכנה",          "🚨"),
    "question":     ("question",     "שאלה",          "❓"),
    "example":      ("example",      "דוגמה",         "🧩"),
    "quote":        ("quote",        "ציטוט",         "❝"),
    "experimental": ("experimental", "ניסוי",         "🧪"),
    "deprecated":   ("deprecated",   "לא מומלץ",      "🚫"),
    "todo":         ("todo",         "משימות לביצוע", "📋"),
    "abstract":     ("abstract",     "תקציר",         "📄"),
}


# ---------- Preprocess: רווח-שורה אוטומטי לפני טבלאות ----------
# מנוע ה-Markdown מזהה טבלה רק כשהיא בלוק נפרד (עם שורה ריקה לפניה). בלי זה
# הטבלה "נדבקת" לפסקה שמעליה ומרונדרת כטקסט רגיל. כאן מוסיפים אוטומטית שורה
# ריקה לפני טבלה שצמודה לטקסט, כדי שתמיד תרונדר כטבלה.

_TABLE_DELIM_CELL_RE = re.compile(r":?-+:?")


def _table_cell_count(line: str) -> int:
    """מספר העמודות בשורת טבלה (אחרי הסרת pipe מוביל/סוגר)."""
    return len(line.strip().strip("|").split("|"))


def _is_table_delimiter_row(line: str) -> bool:
    """האם השורה היא שורת המפריד של טבלה (למשל '| --- | :--: |').

    דורש '|' אחד לפחות ו'-' אחד לפחות, וכל תא תואם ל-:?-+:? — כדי לא
    לבלבל עם קו אופקי (---) או כותרת setext.
    """
    s = line.strip()
    if "|" not in s or "-" not in s:
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return bool(cells) and all(bool(c) and _TABLE_DELIM_CELL_RE.fullmatch(c) for c in cells)


def _ensure_table_blank_lines(text: str) -> str:
    """מוסיף שורה ריקה לפני טבלה שצמודה לטקסט שמעליה.

    מזהה זוג שורות 'כותרת + מפריד' (header ואז |---|---|). אם הכותרת
    מודבקת לשורת טקסט לא-ריקה מעליה - מוסיפים שורה ריקה ביניהן.
    מריצים על טקסט שבו בלוקי קוד כבר הוצאו (placeholders) כדי לא לגעת בהם.
    """
    lines = text.split("\n")
    out: list[str] = []
    for idx, line in enumerate(lines):
        if idx >= 1 and _is_table_delimiter_row(line):
            header = out[-1] if out else ""
            # כותרת חוקית: לא ריקה, מכילה '|', ובאותו מספר עמודות כמו המפריד.
            # ואם השורה שלפני הכותרת לא-ריקה - מפרידים בשורה ריקה.
            if (
                header.strip()
                and "|" in header
                and _table_cell_count(line) >= 2
                and _table_cell_count(header) == _table_cell_count(line)
                and len(out) >= 2
                and out[-2].strip() != ""
            ):
                out.insert(len(out) - 1, "")
        out.append(line)
    return "\n".join(out)


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

    # שלב 1.5: רווח-שורה אוטומטי לפני טבלאות (מחוץ לבלוקי הקוד שכבר הוצאו).
    stashed = _ensure_table_blank_lines(stashed)

    # שלב 2: עיבוד admonitions על הטקסט הנקי מבלוקי קוד.
    def _replace(match: re.Match) -> str:
        kind = match.group("kind").lower()
        custom_title = (match.group("title") or "").strip()
        body = match.group("body").strip()
        # אם בגוף ה-admonition יש בלוקי קוד שנשמרו - מחזירים אותם
        # לפני הרינדור הפנימי, כדי שמנוע ה-Markdown יוכל לעבד אותם.
        body = placeholder_re.sub(_restore_placeholder, body)
        css_class, default_title, icon = _ADMONITION_TYPES.get(
            kind, ("info", "מידע", "ℹ️")
        )
        # כותרת מותאמת אם סופקה בשורת ה-:::, אחרת ברירת-המחדל לסוג.
        title = custom_title or default_title
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
        # escape לכותרת כדי למנוע XSS דרך טקסט הכותרת שבשורת ה-:::.
        safe_title = (title.replace("&", "&amp;").replace("<", "&lt;")
                           .replace(">", "&gt;").replace('"', "&quot;"))
        # עוטפים בשורות ריקות מסביב כדי ש-Python-Markdown יזהה את ה-div
        # כבלוק-HTML עצמאי ולא יבלע פסקאות שמופיעות אחריו ללא שורה ריקה.
        # הכותרת מופיעה ראשונה (מימין ב-RTL) ואחריה האייקון, כמו בעיצוב.
        return (
            f'\n\n<div class="alert alert-{css_class}">'
            f'<div class="alert-header">'
            f'<span class="alert-title">{safe_title}</span>'
            f'<span class="alert-icon">{icon}</span>'
            f'</div>'
            f'<div class="alert-content">{clean_inner}</div>'
            f'</div>\n\n'
        )

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
                # הסינטקס-הילייטינג נעשה בצד-לקוח ב-highlight.js (hljs).
                # השרת מחזיר <pre><code class="language-X">raw</code></pre>
                # בלי spans של Pygments. זה נדרש כדי ש-hljs יוכל לרוץ
                # *אחרי* applyRtlIfHebrew ו-bidi יקבל tokens לעבוד איתם
                # (אחרת בלוקים מעורבים עברית+אנגלית מתרנדרים מבולגן).
                "guess_lang": False,
                "use_pygments": False,
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
