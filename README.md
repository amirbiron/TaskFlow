# TaskFlow

> מערכת אישית לניהול פרויקטים, משימות ולקוחות

## סטאק

- **Backend:** FastAPI (Python 3.11) + Motor (MongoDB)
- **Frontend:** HTML + Tailwind + Alpine.js + SortableJS
- **Hosting:** Render

## מצב נוכחי - שלב 5 ✅

- ✅ הזדהות + cookie
- ✅ ניווט רספונסיבי (5 פריטים)
- ✅ ניהול לקוחות עם צבעים
- ✅ ניהול פרויקטים עם סטטוסים
- ✅ ניהול משימות עם Kanban
- ✅ **חדש**: תיקון גרירה במגע (delay 250ms - לחיצה ארוכה)
- ✅ **חדש**: תת-משימות בתוך מודאל המשימה (checkbox + טקסט)
- ✅ **חדש**: עמוד ניהול תגיות (`/tags`)
- ✅ **חדש**: תגיות למשימות עם autocomplete ויצירה מהירה
- ✅ **חדש**: תגיות לפרויקטים
- ✅ **חדש**: הצגת תגיות בכרטיסי Kanban (עד 3 + "+N")
- ✅ **חדש**: הצגת תגיות בכרטיסי פרויקטים
- ✅ **חדש**: תצוגה של ספירת תת-משימות בכרטיס משימה (3/5 וכד')
- ✅ **חדש**: מחיקת תגית מסירה אותה אוטומטית מכל המשימות והפרויקטים

## API Endpoints חדשים

### תגיות
- `GET /api/tags` - רשימת תגיות עם usage
- `POST /api/tags` - יצירת תגית
- `GET /api/tags/{id}` - תגית בודדת
- `PUT /api/tags/{id}` - עדכון
- `DELETE /api/tags/{id}` - מחיקה (מסירה גם משימות/פרויקטים)

### משימות (משדרגים)
- שדה `subtasks` חדש: `[{ id, title, completed }]`
- שדה `tags` כעת מקושר לתגיות במערכת
- enrichment של `tag_details` ב-GET של משימה

### פרויקטים (משדרגים)
- שדה `tags` כעת מקושר
- enrichment של `tag_details`

## תיקון גרירה במגע

ב-Sortable הוספנו:
- `delay: 250` - חייב לחיצה של רבע שנייה לפני שהגרירה מתחילה
- `delayOnTouchOnly: true` - העיכוב חל רק במגע, לא בעכבר
- `forceFallback: true` - שימוש ב-fallback של Sortable שעובד טוב יותר במגע

תוצאה: בנייד/טאבלט - לחיצה ארוכה ואז גרירה. סקרול רגיל פועל בלחיצה רגילה.

## הוראות שדרוג

ב-Render: דחוף את הקוד החדש לריפו → rebuild אוטומטי.
אין שינויים ב-env variables.

## גיבויים אוטומטיים

המערכת מבצעת גיבוי יומי אוטומטי של MongoDB באמצעות `mongodump`,
שומרת את הקבצים על דיסק מתמיד של Render (`/var/data/backups`),
ומסובבת אותם אוטומטית לפי `BACKUP_RETENTION_DAYS`.

### הגדרה ראשונית ב-Render

1. **שדרג ל-Starter ($7/חודש)** - חינמי לא תומך ב-Persistent Disk.
2. **Disk** - מוגדר ב-`render.yaml`. בפעם הראשונה ייתכן שתצטרך אישור ידני
   בלוח Render (Settings → Disks → Add Disk: name=`taskflow-backups`,
   mountPath=`/var/data`, size=1GB).
3. **mongodb-database-tools** - מותקנים אוטומטית ב-build script
   (ראה `render.yaml`).
4. אין חובה לשנות env vars - יש ברירות מחדל סבירות.

### דף ניהול

זמין ב-`/admin/backups` (מאחורי auth):
- רשימת גיבויים זמינים
- כפתור "גיבוי עכשיו" לטריגר ידני
- הורדה / מחיקה ידנית
- תצוגת ריצה אחרונה + ריצה הבאה

### שחזור גיבוי

הורד את קובץ הגיבוי ולאחר מכן הרץ במחשב מקומי:

```bash
mongorestore --gzip --archive=backup_YYYY-MM-DD_HH-MM.archive.gz \
  --uri "$MONGODB_URL"
```

### משתני סביבה

| משתנה | ברירת מחדל | תיאור |
|---|---|---|
| `BACKUP_ENABLED` | `true` | האם להפעיל את ה-scheduler |
| `BACKUP_DIR` | `/var/data/backups` | תיקיית יעד |
| `BACKUP_RETENTION_DAYS` | `7` | כמה ימים לשמור |
| `BACKUP_HOUR` | `3` | שעת ריצה (UTC) |
| `BACKUP_MINUTE` | `0` | דקה |
| `MONGODUMP_PATH` | `mongodump` | נתיב לכלי |

### API חדש

- `GET /admin/backups` - דף ניהול
- `GET /api/admin/backups` - רשימת גיבויים + מטא
- `POST /api/admin/backups/run` - גיבוי ידני
- `GET /api/admin/backups/{filename}/download` - הורדה
- `DELETE /api/admin/backups/{filename}` - מחיקה

## השלבים הבאים

- שלב 6: העלאת קבצים (Cloudflare R2)
- שלב 7: תזכורות בטלגרם
- שלב 8: דשבורד מלא עם נתונים אמיתיים
- שלב 9: ליטוש סופי
