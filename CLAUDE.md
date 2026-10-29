# הנחיות עבודה

## שפה

- **הערות בקוד**: בעברית
- **תגובות בצ'אט**: בעברית
- **סיכומי PR**: בעברית

## תהליך עבודה

1. **קודם מתכננים** – לפני כל מימוש, יש להציג תוכנית עבודה ברורה.
2. **אחר כך מממשים** – המימוש מתחיל רק לאחר אישור התוכנית.

## קריאה מ-amir-bug-patterns (דרך ה-MCP של Ck)

כשמופנים לכלל ב-`amir-bug-patterns`, קוראים אותו מה-mirror ב-Ck. איך כל כלי עובד כתוב בתיאור שלו; כאן רק מה שלא כתוב שם:

```
codekeeper_docs_get_section(repo="amir-bug-patterns", path="CRITICAL-PATTERNS", section="K11")
codekeeper_get_repo_file(repo="amir-bug-patterns", path="bugbot-rules/state-record-without-state-change.md")
codekeeper_search_repo(repo="amir-bug-patterns", query="<מונח>")
codekeeper_read_batch(items=[{"kind": "section", "repo": "amir-bug-patterns", "path": "CRITICAL-PATTERNS", "section": "K11"}, {"kind": "file", "repo": "amir-bug-patterns", "path": "claude-md-snippets/universal.md"}])
```

- `repo="amir-bug-patterns"` בכל קריאה ובכל פריט: ברירת המחדל היא CodeBot, ובלעדיו חוזר `not_found`.
- ב-`codekeeper_get_repo_file` ובפריט `file` של `codekeeper_read_batch`, `path` הוא הנתיב המלא כולל `.md` — בלי הסיומת חוזר `not_found`.
- `claude-md-snippets/universal.md §5` הוא פריט ברשימה ממוספרת, לא כותרת — קוראים את הקובץ כולו.
- אם כלי ה-[Admin] לא זמינים בסשן, הריפו ציבורי ב-GitHub: `amirbiron/amir-bug-patterns`.
