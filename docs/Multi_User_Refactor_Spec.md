# אפיון מעבר ל-Multi-User

> מסמך עבודה לרפקטור המעביר את TaskFlow מאפליקציית משתמש-יחיד (single-tenant)
> למוצר שמשרת מספר משתמשים, כל אחד עם מרחב עבודה פרטי משלו.

---

## 1. רקע ומטרות

### 1.1 מצב נוכחי

- **אימות**: סיסמה אחת ב-`APP_PASSWORD` (env). cookie חתום ב-`itsdangerous`
  שנושא רק `{"authenticated": true}`. אין מושג של "מי המשתמש".
- **דאטה**: כל ה-collections (`projects`, `clients`, `tasks`, `tags`,
  `task_comments`, `project_documents`) ללא שדה בעלות. כל מי שמתחבר רואה הכל.
- **הגדרות**: `telegram_*`, `r2_*`, `backup_*`, `user_display_name` הם גלובליים
  ב-env. נכון לעכשיו `telegram_bot_token`, `telegram_chat_id`, ו-`r2_*` מוגדרים
  ב-`Settings` אבל לא בשימוש בפועל בקוד.
- **גיבויים**: scheduler יומי שמייצא את כל ה-DB לקובץ zip מקומי.
- **Deploy**: instance בודד ב-Render עם MongoDB משלו.

### 1.2 יעדים (v1)

1. כל משתמש נרשם עם email + סיסמה משלו ורואה רק את הדאטה שלו.
2. אפס דליפת מידע בין משתמשים — כל שאילתה מסוננת ב-`user_id`.
3. הגדרות פר-משתמש שהיום גלובליות (display name, theme, וכו').
4. מיגרציה חלקה של הדאטה הקיים — לא לאבד שום פרויקט/משימה.
5. API תואם-לאחור ככל האפשר (שינוי מינימלי בצד-לקוח).

### 1.3 מה לא בתחום (out of scope ל-v1)

- **שיתוף בין משתמשים / Teams / Organizations** — workspace הוא פרטי, נקודה.
- **תפקידים והרשאות (RBAC)** — אין admin/viewer/editor; כל יוזר שולט במרחב שלו.
- **קישור פרויקטים בין משתמשים** — אין ייצוא/ייבוא ביניהם בגרסה הראשונה.
- **OAuth / SSO** (Google, GitHub) — רק email+סיסמה ב-v1.
- **Email verification חובה** — נשלח לינק verify אבל לא חוסם שימוש (אופציונלי).
- **Billing / Plans** — חינמי לכולם, ללא מגבלות בשלב זה.
- **API tokens / Public API** — אין endpoints ל-third-party clients.
- **Multi-region / Sharding** — instance בודד מספיק.

---

## 2. ארכיטקטורת היעד

### 2.1 מודל יוזרים

collection חדש: **`users`**.

| שדה | סוג | הערות |
|---|---|---|
| `_id` | ObjectId | PK |
| `email` | string | unique, normalized lowercase |
| `password_hash` | string | argon2 (preferred) או bcrypt |
| `display_name` | string | מחליף את `user_display_name` הגלובלי |
| `email_verified` | bool | default false |
| `email_verify_token` | string \| null | חד-פעמי, expires |
| `password_reset_token` | string \| null | חד-פעמי, expires |
| `password_reset_expires` | datetime \| null | |
| `created_at` | datetime | |
| `updated_at` | datetime | |
| `last_login_at` | datetime \| null | למעקב/אבטחה |
| `settings` | dict | preferences פר-משתמש (ראה 2.4) |
| `disabled` | bool | מצב חסום (אדמין) |

**Indexes**:
- `email` unique.
- `email_verify_token` sparse.
- `password_reset_token` sparse.

### 2.2 Auth flow

#### הרשמה (`POST /api/auth/register`)
- input: `email`, `password`, `display_name`.
- validation: email תקין, סיסמה ≥ 10 תווים עם complexity מינימלי, captcha (ראה §5.3).
- בודק שאין משתמש קיים → יוצר doc ב-`users` עם hash → מייצר session → שולח אימייל verify.

#### התחברות (`POST /api/auth/login`)
- input: `email`, `password`.
- מאתר user → מאמת hash → מייצר session token חתום נושא `user_id` →
  cookie `taskflow_session` (HttpOnly, Secure, SameSite=Lax, 30d) → מעדכן
  `last_login_at`.

#### יציאה (`POST /api/auth/logout`)
- מוחק את ה-cookie. (sessionless: ה-token הוא JWT-like, אין server-side store.)

#### איפוס סיסמה
- `POST /api/auth/forgot-password` (email בלבד) — תמיד מחזיר 200 כדי לא לחשוף
  קיום משתמשים. מייצר `password_reset_token` עם תוקף שעה, שולח אימייל.
- `POST /api/auth/reset-password` (token, new_password) — מאמת token, hash סיסמה
  חדשה, מבטל את ה-token.

#### אימות email (אופציונלי)
- `GET /api/auth/verify-email?token=...` — מסמן `email_verified=true`.
- Banner בממשק עבור משתמשים לא-מאומתים, ללא חסימה.

### 2.3 Session

ה-token יישא:
```json
{ "uid": "<user_id_hex>", "v": 1 }
```

- `uid` — string ObjectId של היוזר. השאילתה תקרא אותו לכל request.
- `v` — token schema version, מאפשר ביטול גורף בעתיד (bump → טוקנים ישנים
  ייכשלו).

**Migration consideration**: טוקנים קיימים (`{authenticated: true}`) ייפסלו
אוטומטית כי חסר להם `uid`. כל המשתמשים יצטרכו להתחבר מחדש פעם אחת.

### 2.4 הגדרות פר-משתמש

מתחת ל-`users.settings`:

| מפתח | ברירת מחדל | מקור היום |
|---|---|---|
| `theme` | `"system"` | `localStorage` בצד-לקוח |
| `notifications.telegram_bot_token` | `""` | `TELEGRAM_BOT_TOKEN` env (לא בשימוש) |
| `notifications.telegram_chat_id` | `""` | `TELEGRAM_CHAT_ID` env (לא בשימוש) |
| `backup.enabled` | `true` | `BACKUP_ENABLED` env |
| `backup.retention_days` | `7` | env |
| `backup.hour` / `minute` | `3:00` UTC | env |

**הערה**: `r2_*` נשארים גלובליים — שירות אחסון משותף עם prefix פר-יוזר.
ראה §3.3.

### 2.5 בידוד דאטה

עיקרון: **שדה `user_id` (string ObjectId) על כל מסמך, ב-`$match` בכל שאילתה**.

אין trust ב-frontend. כל endpoint דורש `current_user = get_current_user(request)`
וכל find/insert/update/delete מוסיף `user_id=current_user.id`.

---

## 3. שינויים בדאטה

### 3.1 schema-level

| collection | שדה חדש | indexes חדשים |
|---|---|---|
| `users` | (חדש לגמרי) | `email` unique, `email_verify_token` sparse, `password_reset_token` sparse |
| `clients` | `user_id` | `(user_id, name)` |
| `projects` | `user_id` | `(user_id, status, name)`, `(user_id, client_id, status)` |
| `tasks` | `user_id` | `(user_id, project_id, status, archived)`, `(user_id, client_id, status, archived)`, `(user_id, tags)` |
| `tags` | `user_id` | `(user_id, name)` unique |
| `task_comments` | `user_id` | `(user_id, task_id, created_at)` |
| `project_documents` | `user_id` | `(user_id, project_id)` |

**הערה**: כל אינדקס קיים שמתחיל ב-field כמו `project_id` או `client_id` הופך
לאינדקס מרוכב עם `user_id` כקידומת. אחרת ה-DB יוכל בתיאוריה לסרוק רוחבית בין
מסמכים של משתמשים שונים, ובאופן מעשי יאט.

**`tags` ייחודיות**: כיום `db.tags.find_one({"name": ...})` בעת יצירה.
חייב להפוך ל-`{"user_id": uid, "name": ...}` — שני משתמשים יכולים שניהם להחזיק
תגית "urgent", הם פשוט מסמכים שונים.

### 3.2 שינויים במודלים (`app/models/*`)

- `MongoBaseModel` (או מחלקה נגזרת חדשה `OwnedMongoBaseModel`): מוסיף שדה
  `user_id: PyObjectId`.
- כל המודלים (פרט ל-`User` עצמו): יורשים מ-`OwnedMongoBaseModel`.
- DTOs של create (`ProjectCreate`, `ClientCreate`, וכו'): **אין** `user_id`
  כקלט מהלקוח — מוזרק בשרת מה-session.

### 3.3 קבצים מצורפים (R2)

אם/כש-R2 ייכנס לשימוש בפועל:
- bucket אחד משותף.
- מפתח (key) מקבל prefix: `users/{user_id}/projects/{project_id}/...`.
- בקשות download/upload מוודאות שה-prefix מתחיל ב-`users/{current_user.id}/`.

---

## 4. שינויים ב-API

### 4.1 endpoints חדשים

```
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me
POST   /api/auth/forgot-password
POST   /api/auth/reset-password
GET    /api/auth/verify-email
POST   /api/auth/change-password   (משתמש מחובר)
GET    /api/users/me/settings
PUT    /api/users/me/settings
DELETE /api/users/me                (מחיקת חשבון + כל הדאטה)
```

### 4.2 endpoints קיימים

**אין שינוי בחתימה החיצונית**, אבל:

- כל קריאה ל-`require_api_auth(request)` תוחלף ב-dependency חדש שמחזיר
  `User` object: `current_user: User = Depends(get_current_user)`.
- כל query: תוסף `"user_id": current_user.id`.
- כל insert: תוסף `doc["user_id"] = current_user.id`.
- כל aggregation pipeline: `$match` הראשון יכלול `user_id`.

דוגמה מ-`list_projects`:
```python
# היה:
query = {}
if not include_inactive:
    query["status"] = {"$in": ["active", "pending"]}

# יהיה:
query = {"user_id": current_user.id}
if not include_inactive:
    query["status"] = {"$in": ["active", "pending"]}
```

ב-aggregation של `list_clients` (ספירת projects+tasks לפי client_id):
ה-`$match` הראשון חייב לכלול גם `user_id`, אחרת נספור גם נכסים של משתמשים אחרים.

### 4.3 ולידציות צולבות

מצב נפוץ: יצירת project עם `client_id` → היום בודק שהלקוח קיים.
**צריך לבדוק שהלקוח שייך לאותו user_id**, אחרת יוזר A יוכל ליצור project
שמצביע על client של יוזר B.

אותו דבר ל:
- task → project, client, tags (כולם).
- project_document → project.
- task_comment → task.

יוטמע כ-helper: `verify_owned(db, collection, doc_id, user_id) -> doc | 404`.

---

## 5. אבטחה

### 5.1 סיסמאות

- אלגוריתם: **argon2id** (preferred) או **bcrypt** (cost ≥ 12).
- ספריה: `argon2-cffi` או `passlib[bcrypt]`.
- אורך מינימלי: 10 תווים. אסור password שמופיע ב-Have I Been Pwned (אופציונלי
  ב-v1).
- אחסון: רק ה-hash. אין log של הסיסמה הגולמית בשום מקום.

### 5.2 CSRF

היום אין הגנה. סיסמה אחת ו-cookie על דומיין יחיד → סיכון מוגבל.
ב-multi-user public app זה מסוכן יותר.

אופציות:
1. **Double-submit cookie**: שני cookies, AJAX שולח header `X-CSRF-Token` שתואם
   ל-cookie. מימוש פשוט.
2. **SameSite=Strict** במקום `Lax` — חזק אבל שובר external links.

המלצה: SameSite=Lax (כיום) + Double-submit על כל POST/PUT/DELETE/PATCH.

### 5.3 Rate limiting

נחוץ על endpoints ציבוריים (לא דורשים auth):
- `register`: 5/min/IP, 20/day/IP.
- `login`: 10/min/IP, 30/min/email (להאט brute-force).
- `forgot-password`: 3/min/email.

ספריה: `slowapi` (FastAPI middleware על Redis או memory).

**הערה**: memory-based limiter עובד רק עם instance אחד. ל-multi-instance נצטרך
Redis. כיום instance בודד → memory מספיק.

### 5.4 Captcha (אופציונלי)

על register: hCaptcha / Turnstile. ל-v1 אפשר לדחות; ה-rate limiting נותן חלק
מההגנה.

### 5.5 Authorization בודק את הקיים

audit pass: לעבור על כל endpoint ולוודא ש-`user_id` נבדק *תמיד*. הסיכון
העיקרי הוא endpoint שמקבל `project_id` ב-URL ומחזיר את הפרויקט בלי לבדוק
בעלות. כללי-אצבע:
- find_one של מסמך שמזהה דרך URL: חייב `{"_id": id, "user_id": current_user.id}`.
- חזרת 404 (לא 403) גם כשהמסמך קיים אך לא שייך — לא לחשוף קיום.

---

## 6. שינויים ב-Frontend

### 6.1 דפים חדשים

- `/register` — טופס הרשמה.
- `/forgot-password`, `/reset-password?token=...`.
- `/account` — עריכת display_name, שינוי סיסמה, הגדרות התראות, מחיקת חשבון.

### 6.2 שינויים בקיים

- `/login` (קיים): שדה email נוסף.
- `base.html`: ה-navbar מציג את ה-display_name (מ-`/api/auth/me`) במקום
  `user_display_name` מ-context.
- כל הטמפלייטים שמשתמשים ב-`user_display_name` מ-`get_settings()` (אם יש):
  להעביר ל-user object.

### 6.3 ניהול מצב

`/api/auth/me` נקרא פעם בטעינת הדף (Alpine `init`), מאחסן את ה-user בזיכרון.
Logout מנקה ומפנה ל-`/login`.

---

## 7. גיבויים בעולם רב-משתמשים

האסטרטגיה הנוכחית (dump של ה-DB כולו פעם ביום) לא מתאימה אחד-לאחד:

**אופציה A (מומלצת ל-v1)**: גיבוי גלובלי של ה-DB נשאר כמו שהוא, מנהל המערכת
(אתה) הוא היחיד שיש לו גישה לקבצים. משתמשים לא יראו את עמוד הגיבויים.
- `/admin/backups` מוסתר ממשתמשים רגילים (דורש `is_admin=true` ב-user doc, שאין
  לאף אחד כברירת מחדל).

**אופציה B (v2)**: כל יוזר מקבל "Export my data" → zip עם כל הפרויקטים/משימות
שלו ב-JSON. וגם "Delete my account" שמוחק את כל הדאטה שלו.

ב-v1 ניישם רק "Delete my account" (GDPR-friendly), Export יידחה.

---

## 8. תוכנית מיגרציה

### 8.1 מצב התחלתי

ה-DB הקיים מכיל פרויקטים/משימות/לקוחות **של משתמש אחד** (אתה).

### 8.2 שלבי המיגרציה

סקריפט חד-פעמי `scripts/migrate_to_multi_user.py`:

1. קלט: `--email`, `--password`, `--display-name` (היוזר הראשון).
2. יוצר doc ב-`users` עם הפרטים האלה.
3. רץ על כל המסמכים ב-`clients`, `projects`, `tasks`, `tags`, `task_comments`,
   `project_documents` ומוסיף `user_id` של היוזר החדש.
4. יוצר את האינדקסים החדשים (`_ensure_indexes` יעודכן ויטופל אוטומטית בעלייה
   הבאה).
5. מאמת: ספירות מסמכים לפני ואחרי זהות; כל מסמך יש לו `user_id`.

הסקריפט **idempotent**: ריצה חוזרת לא תכפיל. בדיקה: אם יש כבר doc ב-`users`
עם אותו email → skip יצירה, רק משלימה user_id חסרים (אם נשארו).

### 8.3 שלב הפריסה

1. Deploy גרסה חדשה במצב "maintenance" — read-only או הודעה למשתמשים.
2. הרצת מיגרציה.
3. אימות בקצרה (לוגין → לראות שכל הדאטה שם).
4. הסרת maintenance, החלפת ה-flag להפעיל registration ציבורי (אם רוצים).

---

## 9. שלבי מימוש (milestones)

### Milestone 1 — תשתית auth
- מודל `User`, ראוטר `auth.py` חדש עם register/login/me/logout.
- `get_current_user` dependency.
- מיגרציה של הסיסמה הגלובלית הקיימת (בלי data isolation עדיין).
- דפים: `/register`, עדכון `/login`.
- **Definition of done**: יוזר יכול להירשם, להתחבר, ולראות את ה-(אחד) הקיים.

### Milestone 2 — בידוד דאטה
- הוספת `user_id` לכל המודלים.
- עדכון כל ה-routers (כל endpoint).
- אינדקסים חדשים ב-`_ensure_indexes`.
- ולידציות בעלות צולבות (verify_owned).
- סקריפט מיגרציה.
- **Definition of done**: שני יוזרים שונים רואים datasets נפרדים. בדיקת נסיון
  גישה ל-`/api/projects/<id_של_יוזר_אחר>` מחזירה 404.

### Milestone 3 — הגדרות פר-משתמש + עמוד חשבון
- collection settings ב-`users.settings`.
- `/account` UI.
- שינוי סיסמה, מחיקת חשבון.

### Milestone 4 — שכבת אבטחה
- CSRF (double-submit).
- Rate limiting (slowapi).
- forgot/reset password (דורש שליחת מייל — ראה §11).
- email verify (אופציונלי).

### Milestone 5 — תיעוד + cleanup
- README עם הוראות deploy חדשות.
- הסרת ה-env vars שעברו ל-user settings.
- מסך admin בסיסי (אופציונלי).

---

## 10. שאלות פתוחות / החלטות נדרשות

1. **שירות מייל**: לאיפוס סיסמה ו-verify נצטרך SMTP/SendGrid/Resend.
   - האם להוסיף תלות בשירות צד-שלישי, או לדחות את password-reset ל-v2?
   - אם דוחים: יוזר ששוכח סיסמה → פנייה ידנית לאדמין.
2. **רישום פתוח לכולם, או invite-only?**
   - public: צריך captcha + rate limiting אגרסיבי.
   - invite-only: אדמין יוצר tokens, פשוט יותר.
3. **מחיקת חשבון = מחיקה רכה או קשה?**
   - hard delete: כל הדאטה נמחק, לא ניתן לשחזר.
   - soft delete: `disabled=true`, דאטה נשמר 30 יום ואז cron מוחק.
4. **תאימות לאחור עם המודל הישן**:
   - האם להשאיר `APP_PASSWORD` עובד כ-fallback admin עד שגרסה תתייצב?
   - לדעתי לא — clean cut, פחות bugs.
5. **Theme — server-side או client-only?**
   - היום `localStorage`. להשאיר ככה? או להעביר ל-`users.settings.theme` כדי
     שיהיה sync בין מכשירים?

---

## 11. סיכוני מימוש

- **דליפת מידע בין משתמשים** עקב query שנשכח: הסיכון העיקרי. מקלימייץ:
  - audit פר-route.
  - tests אוטומטיים שמנסים cross-tenant access ומצפים ל-404.
  - linter custom (אופציונלי) שזורק אם find/insert/update בלי `user_id`.
- **מיגרציה תקועה**: שגיאה בריצה משאירה DB במצב מעורב.
  - הרצה בסביבת staging תחילה.
  - `idempotent` + dry-run mode.
- **שבירת clients קיימים** (Alpine ב-frontend): טוקן ישן יחזיר 401 → redirect
  ל-`/login`. צריך הודעה ידידותית למשתמש בכניסה הראשונה.
- **ביצועים**: aggregations שלא יקבלו את האינדקס המרוכב הנכון יהפכו לסריקות
  מלאות. בדיקה: `explain()` על השאילתות העיקריות אחרי המיגרציה.

---

## 12. הערכת היקף

הערכה גסה (לא מחייבת):

| Milestone | מאמץ משוער |
|---|---|
| M1 — auth | 1-2 ימי עבודה |
| M2 — בידוד דאטה | 3-4 ימי עבודה (זהירות, audit, tests) |
| M3 — settings & account | 1-2 ימי עבודה |
| M4 — security hardening | 2-3 ימי עבודה (תלוי בשירות מייל) |
| M5 — תיעוד | 0.5 יום |

**סה"כ**: שבוע וחצי עד שבועיים של עבודה ממוקדת, כולל בדיקות.

---

## 13. נספח — קבצים שיושפעו

```
NEW:
  app/models/user.py
  app/routers/users.py
  app/core/passwords.py
  scripts/migrate_to_multi_user.py
  app/templates/register.html
  app/templates/account.html
  app/templates/forgot_password.html
  app/templates/reset_password.html

MODIFIED:
  app/core/auth.py              -- session schema, get_current_user
  app/core/config.py            -- הסרת settings שעוברים ל-user
  app/core/database.py          -- אינדקסים חדשים
  app/main.py                   -- include_router של users
  app/models/base.py            -- OwnedMongoBaseModel
  app/models/{client,project,task,tag,comment,project_document}.py
                                -- user_id field
  app/routers/auth.py           -- register/login/logout/me/...
  app/routers/{clients,projects,tasks,tags,comments,documents,dashboard,
               backups}.py      -- user_id scoping בכל endpoint
  app/templates/base.html       -- display_name מ-/api/auth/me
  app/templates/login.html      -- שדה email
```
