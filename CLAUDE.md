# הנחיות עבודה

## שפה

- **הערות בקוד**: בעברית
- **תגובות בצ'אט**: בעברית
- **סיכומי PR**: בעברית

## תהליך עבודה

1. **קודם מתכננים** – לפני כל מימוש, יש להציג תוכנית עבודה ברורה.
2. **אחר כך מממשים** – המימוש מתחיל רק לאחר אישור התוכנית.

## קריאה מ-amir-bug-patterns (דרך ה-MCP של Ck)

כשמופנים לכלל ב-`amir-bug-patterns`, קוראים אותו מה-mirror ב-Ck:

```
codekeeper_docs_get_section(repo="amir-bug-patterns", path="CRITICAL-PATTERNS", section="K11")
codekeeper_get_repo_file(repo="amir-bug-patterns", path="bugbot-rules/state-record-without-state-change.md")
codekeeper_search_repo(repo="amir-bug-patterns", query="<מונח>")
codekeeper_read_batch(items=[{"kind": "section", "repo": "amir-bug-patterns", "path": "CRITICAL-PATTERNS", "section": "K11"}, {"kind": "file", "repo": "amir-bug-patterns", "path": "claude-md-snippets/universal.md"}])
```

- `codekeeper_docs_get_section` בלי `section` מחזיר את מפת הקובץ, עם גודל כל סעיף. עם `section` הוא מחזיר רק אותו, לפי מזהה (K11) או לפי שם הכותרת. ב-`path` מספיק שם הקובץ בלי `.md`.
- `codekeeper_get_repo_file` הוא לקריאת כל הקובץ, כשמופנים למשל לקובץ תחת `bugbot-rules/`. כאן `path` הוא הנתיב המלא, כולל `.md` — בלי הסיומת חוזר `not_found`.
- `codekeeper_search_repo` הוא למקרה שלא יודעים באיזה קובץ או סעיף הדפוס נמצא.
- `codekeeper_read_batch` — כשיש כמה הפניות באותו סבב (למשל כל הטריגרים של ריוויו): כל פריט הוא `{"kind": "section", ...}` או `{"kind": "file", ...}` עם אותם ארגומנטים כמו בשני הכלים, עד 20 פריטים בקריאה אחת.
- `repo="amir-bug-patterns"` בכל קריאה ובכל פריט. בפריט `file` הוא חובה, ובלעדיו `codekeeper_docs_get_section` ופריט `section` קוראים מ-CodeBot (ברירת המחדל) ומחזירים `not_found`.
- `claude-md-snippets/universal.md §5` הוא פריט ברשימה ממוספרת, לא כותרת — קוראים את הקובץ כולו (`section="5"` מחזיר `section_not_found`).
- `codekeeper_get_repo_file`, `codekeeper_search_repo` ו-`codekeeper_read_batch` מסומנים [Admin]. אם הם לא זמינים בסשן: `codekeeper_docs_get_section` זמין לכולם, והריפו ציבורי ב-GitHub (`amirbiron/amir-bug-patterns`).
