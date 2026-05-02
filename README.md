# TaskFlow

> מערכת אישית לניהול פרויקטים, משימות ולקוחות

## סטאק

- **Backend:** FastAPI (Python 3.11)
- **Database:** MongoDB Atlas
- **Frontend:** HTML + Tailwind CSS + Alpine.js + SortableJS
- **Hosting:** Render

## מצב נוכחי - שלב 4 ✅

- ✅ הזדהות עם סיסמה + cookie
- ✅ ניווט רספונסיבי
- ✅ ניהול לקוחות מלא (CRUD) עם צבעים
- ✅ ניהול פרויקטים מלא (CRUD) עם סטטוסים
- ✅ **חדש**: ניהול משימות מלא (CRUD)
- ✅ **חדש**: לוח Kanban עם 3 עמודות (פתוח / בתהליך / הושלם)
- ✅ **חדש**: גרירה ושחרור בין עמודות ובתוך עמודה
- ✅ **חדש**: עדיפויות (נמוכה / רגילה / גבוהה / דחוף) עם תגי צבע
- ✅ **חדש**: תאריכי יעד עם הדגשת איחורים באדום
- ✅ **חדש**: קישורים מרובים לכל משימה
- ✅ **חדש**: תצוגת משימות גלובלית (`/tasks`) - כל המשימות מכל הפרויקטים
- ✅ **חדש**: תצוגת משימות בעמוד פרויקט בודד
- ✅ **חדש**: משימות שהושלמו מוצגות חצי-שקופות
- ✅ **חדש**: משימה ירשת לקוח מהפרויקט אם לא נבחר אחר

## API Endpoints

### לקוחות
- `GET /api/clients`
- `GET /api/clients/select-options` - רשימה לטפסים
- `POST/GET/PUT/DELETE /api/clients/{id}`

### פרויקטים
- `GET /api/projects?include_inactive=true|false`
- `POST/GET/PUT/DELETE /api/projects/{id}`
- `GET /api/projects/{id}/tasks`

### משימות (חדש)
- `GET /api/tasks?project_id=X&client_id=Y&status=Z` - פילטרים אופציונליים
- `POST /api/tasks` - יצירת משימה
- `GET /api/tasks/{id}` - פרטי משימה
- `PUT /api/tasks/{id}` - עדכון משימה
- `PATCH /api/tasks/{id}/status` - עדכון סטטוס בלבד
- `PATCH /api/tasks/{id}/order` - עדכון סדר בעמודה בלבד
- `POST /api/tasks/reorder` - עדכון bulk של סדר/סטטוס (לגרירה)
- `DELETE /api/tasks/{id}` - מחיקת משימה

### עמודים
- `/` - דשבורד
- `/clients` - לקוחות
- `/projects` - רשימת פרויקטים
- `/projects/{id}` - פרויקט בודד עם Kanban
- `/tasks` - תצוגת Kanban גלובלית

## הוראות שדרוג

ב-Render: דחוף את הקוד החדש לריפו → rebuild אוטומטי. אין שינויים ב-env variables.

## השלבים הבאים

- שלב 5: תכונות מתקדמות (תת-משימות, תגיות, סינון/חיפוש)
- שלב 6: העלאת קבצים (Cloudflare R2)
- שלב 7: תזכורות בטלגרם
- שלב 8: דשבורד מלא עם נתונים אמיתיים
- שלב 9: ליטוש סופי
