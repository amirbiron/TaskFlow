# EmailFlow — מסמך אפיון מפורט (Spec)

> מערכת לסיווג ומענה אוטומטי לתיבת מייל עסקית, מבוססת AI.
> גרסה: 1.0 | תאריך: 2026-05-10

---

## 1. סקירה כללית

### 1.1 מטרה
פתרון שורשי לעסקים שמוצפים במיילים חוזרים — סיווג חכם, תיוג, ניתוב, וטיוטות מענה אוטומטיות בסגנון העסק. בעל העסק מאשר ושולח בקליק, או רק עוקב אחרי מה שהמערכת עושה.

### 1.2 קהל יעד
עורכי דין, רואי חשבון, סוכנויות נדל"ן, קליניקות, סטודיו עיצוב, נותני שירות — כל מי שמקבל 30+ מיילים ביום עם דפוסים חוזרים.

### 1.3 ערך מרכזי
- חיסכון של 1–3 שעות ביום על מיילים
- אף מייל לא נופל בין הכיסאות
- מענה מהיר ומקצועי גם כשבעל העסק עסוק
- ניתוב חכם לעובדים הנכונים בארגון

### 1.4 גישת מוצר
**Multi-tenant היברידי**: ליבה אחת לכל הלקוחות, התאמה לכל לקוח דרך config, prompts, וידע (FAQ) — לא דרך פיצול קוד.

---

## 2. דרישות פונקציונליות

### 2.1 חיבור מקור (Source)
- **Gmail OAuth 2.0** (Phase 1 — בלבד)
- תמיכה ב-Gmail פרטי וב-Google Workspace
- חידוש refresh token אוטומטי
- ניטור תיבה דרך Gmail Push Notifications (Pub/Sub) — לא polling
- אופציה ל-fallback polling כל X דקות אם Push לא זמין

### 2.2 סיווג מיילים
- כל מייל נכנס מסווג ל-**קטגוריה אחת** מתוך רשימה מותאמת לעסק
- קטגוריות ברירת מחדל:
  - `faq` — שאלה שיש לה תשובה במאגר
  - `lead` — פנייה של לקוח פוטנציאלי חדש
  - `support` — בקשת תמיכה / תלונה מלקוח קיים
  - `scheduling` — בקשה לקביעת/שינוי פגישה
  - `invoice` — חשבונית / תשלום / חיוב
  - `personal` — אישי / לא קשור לעסק
  - `spam` — ספאם או שיווק לא רלוונטי
  - `other` — לא הצלחנו לסווג בביטחון
- לכל מייל מצורפים: **קטגוריה, ביטחון (0–1), סנטימנט, דחיפות (low/normal/high)**
- בעל העסק יכול להוסיף/לערוך/למחוק קטגוריות

### 2.3 מאגר ידע (FAQ Knowledge Base)
- בעל העסק מזין שאלות ותשובות (Q&A pairs)
- אפשרות לטעון מאתר/PDF/מסמך Word
- כל פריט נשמר עם **embedding** לחיפוש סמנטי
- חיפוש hybrid: vector similarity + keyword match
- סף ביטחון: רק תשובה מעל 0.75 similarity מוגשת כטיוטה

### 2.4 יצירת טיוטות מענה
- לכל מייל שמתאים למענה — נוצרת **טיוטה ב-Gmail Drafts**
- הטיוטה נכתבת בסגנון העסק:
  - שפה (עברית/אנגלית — אוטומטית לפי שפת המייל)
  - טון (רשמי/חברי/מקצועי) — מוגדר ב-config של הלקוח
  - חתימה אוטומטית
  - שמירה על thread ו-quoted text
- **שום מייל לא נשלח אוטומטית בגרסה הראשונה** — רק טיוטה לאישור

### 2.5 תיוג ב-Gmail
- כל מייל מקבל לייבל בפורמט: `EmailFlow/<קטגוריה>`
- מיילים דחופים מקבלים גם `EmailFlow/Urgent`
- מיילים שיש להם טיוטה: `EmailFlow/HasDraft`
- אופציה להעביר לתיקייה (ארכוב מ-Inbox) לפי קטגוריה

### 2.6 ניתוב פנימי
- בעל העסק מגדיר חוקי ניתוב: `קטגוריה X → אדם Y`
- ניתוב = העברה / הוספת CC / שליחת התראה
- דוגמה: `lead → manager@biz.com + WhatsApp לבעלים`

### 2.7 התרעות
- ערוצים נתמכים: WhatsApp (Twilio/Green API), Slack, Telegram, SMS
- טריגרים מותאמים: דחיפות גבוהה / קטגוריה ספציפית / VIP sender
- תוכן ההתראה: שם שולח, נושא, סיכום של 2 שורות, לינק ישיר ל-Gmail

### 2.8 דשבורד ניהולי
- **דף ראשי**: כמה מיילים נכנסו היום, כמה טיוטות מוכנות, כמה דחופים
- **רשימת מיילים**: סינון לפי קטגוריה/דחיפות/סטטוס + צפייה בטיוטה + עריכה
- **ניהול FAQ**: CRUD + טעינת מסמכים
- **ניהול קטגוריות וחוקים**
- **סטטיסטיקות**: חיסכון בזמן משוער, % מענה אוטומטי, דיוק סיווג
- **אונבורדינג מודרך**: חיבור Gmail → אימון על מיילים אחרונים → הגדרת FAQ → סיום

### 2.9 למידה והשתפרות
- בעל העסק יכול לערוך טיוטה לפני שליחה — העריכה נשמרת
- אם מסווג בטעות — בעל העסק מתקן ידנית
- תיקונים מצטברים → fine-tune של פרומפט הסיווג / הוספה ל-FAQ

---

## 3. דרישות לא-פונקציונליות

### 3.1 ביצועים
- מייל חדש מטופל תוך **30 שניות** מקבלתו
- דשבורד נטען תוך < 2 שניות
- תמיכה ב-100+ מיילים ביום פר לקוח ב-MVP

### 3.2 אבטחה ופרטיות
- **תוכן המיילים לא נשמר ב-DB אלא אם הלקוח אישר** — רק metadata
- Encryption at rest (Postgres) + in transit (TLS)
- OAuth tokens מוצפנים (KMS / Vault)
- מחיקת נתונים מלאה תוך 24 שעות לפי בקשת הלקוח
- עמידה ב-Google API Services User Data Policy
- Audit log לכל פעולה רגישה

### 3.3 זמינות
- 99.5% uptime ב-MVP
- Retry mechanism למיילים שלא טופלו
- Dead letter queue לבעיות

### 3.4 עלויות AI
- שימוש ב-`gpt-4o-mini` / `claude-haiku` לסיווג (זול)
- שימוש ב-`gpt-4o` / `claude-sonnet` לטיוטות (איכות)
- prompt caching מקסימלי
- מעקב עלויות פר לקוח לחיוב נכון

---

## 4. ארכיטקטורה

### 4.1 רכיבים מרכזיים

```
┌──────────────────────────────────────────────────────────────┐
│                        Gmail (per tenant)                    │
└──────────┬─────────────────────────────────────▲─────────────┘
           │ Push Notification                   │ Create Draft
           │ (Pub/Sub)                           │ Apply Label
           ▼                                     │
┌─────────────────────┐    ┌──────────────────────────────────┐
│  Webhook Receiver   │───▶│         Job Queue (Redis)        │
│   (FastAPI)         │    └──────────┬───────────────────────┘
└─────────────────────┘               │
                                       ▼
                          ┌────────────────────────────┐
                          │   Email Processing Worker  │
                          │  (Celery / RQ / BullMQ)    │
                          └────┬──────────┬────────────┘
                               │          │
                ┌──────────────▼──┐    ┌──▼──────────────────┐
                │  AI Classifier  │    │  AI Draft Generator │
                │  (Claude/GPT)   │    │   (Claude/GPT)      │
                └──────────────┬──┘    └──┬──────────────────┘
                               │          │
                               ▼          ▼
                  ┌──────────────────────────────┐
                  │   FAQ Vector Search (pgvector)│
                  └──────────────────────────────┘
                               │
                               ▼
                  ┌──────────────────────────────┐
                  │   PostgreSQL (multi-tenant)  │
                  └──────────────────────────────┘
                               │
                               ▼
                  ┌──────────────────────────────┐
                  │   Notification Dispatcher    │
                  │  (WhatsApp/Slack/Telegram)   │
                  └──────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│           Frontend Dashboard (Next.js + React)             │
│        ◄──── REST API ────► Backend (FastAPI)              │
└────────────────────────────────────────────────────────────┘
```

### 4.2 תהליך עיבוד מייל (End-to-End)

1. Gmail Push Notification מגיע ל-webhook
2. ה-webhook מאמת את החתימה ושומר job בתור Redis
3. Worker מושך את ה-job, קורא את המייל ב-Gmail API
4. שולף את ה-tenant config (קטגוריות, סגנון, FAQ)
5. סיווג AI → קטגוריה + דחיפות + סנטימנט
6. אם קטגוריה = `faq` → חיפוש vector ב-FAQ → אם נמצאה תשובה מעל סף → יצירת טיוטה
7. אם קטגוריה ≠ `faq` אבל ברת-מענה (lead/scheduling) → AI כותב טיוטה לפי תבנית
8. תיוג המייל ב-Gmail
9. ניתוב לפי החוקים (העברה/CC)
10. שליחת התראה אם דחוף
11. עדכון DB ל-dashboard

---

## 5. סטאק טכנולוגי

### 5.1 Backend
- **Python 3.12** + **FastAPI**
- **Celery** + **Redis** ל-job queue
- **SQLAlchemy** + **Alembic** ל-ORM ומיגרציות
- **Pydantic v2** ל-validation

### 5.2 AI / LLM
- **Anthropic Claude** (Sonnet 4.6 לטיוטות, Haiku 4.5 לסיווג)
- **OpenAI** כ-fallback
- **OpenAI text-embedding-3-small** ל-embeddings (זול ויעיל)
- **prompt caching** ב-Anthropic לחיסכון 90% בעלויות הסיווג

### 5.3 Database
- **PostgreSQL 16** + **pgvector**
- **Redis** ל-cache ול-queue

### 5.4 Frontend
- **Next.js 15** (App Router) + **React 19**
- **TailwindCSS** + **shadcn/ui**
- **TanStack Query** ל-state ו-API
- **NextAuth** ל-auth של בעל העסק לדשבורד

### 5.5 Infrastructure
- **Docker** + **docker-compose** לפיתוח
- **Render / Railway / Fly.io** ל-deployment ראשוני
- **Cloudflare** ל-CDN ו-DDoS
- **Sentry** ל-error tracking
- **PostHog** ל-product analytics

### 5.6 אינטגרציות חיצוניות
- **Gmail API** (read/modify/labels/drafts)
- **Google Cloud Pub/Sub** ל-push notifications
- **Twilio / Green API** ל-WhatsApp
- **Slack API** / **Telegram Bot API**

---

## 6. מבנה Database

### 6.1 טבלאות ליבה

```sql
-- ארגונים (multi-tenancy)
tenants (
  id UUID PK,
  name TEXT,
  business_type TEXT,         -- עו"ד, רו"ח וכו'
  language TEXT DEFAULT 'he',
  tone TEXT DEFAULT 'professional',
  signature TEXT,
  status TEXT,                -- active/suspended/trial
  created_at, updated_at
)

-- משתמשי הדשבורד
users (
  id UUID PK,
  tenant_id FK,
  email, password_hash,
  role TEXT,                  -- owner/admin/viewer
  created_at
)

-- חשבונות Gmail מחוברים
gmail_accounts (
  id UUID PK,
  tenant_id FK,
  email TEXT,
  refresh_token_encrypted TEXT,
  watch_expiration TIMESTAMP,
  history_id BIGINT,
  status TEXT,
  created_at
)

-- קטגוריות מותאמות
categories (
  id UUID PK,
  tenant_id FK,
  key TEXT,                   -- faq/lead/support...
  name TEXT,
  description TEXT,           -- הסבר ל-AI
  color TEXT,
  auto_reply BOOLEAN,
  routing_rules JSONB,
  created_at
)

-- מאגר FAQ
faq_items (
  id UUID PK,
  tenant_id FK,
  question TEXT,
  answer TEXT,
  embedding vector(1536),
  source TEXT,                -- manual/website/pdf
  active BOOLEAN,
  hit_count INT,
  created_at, updated_at
)

-- מיילים שטופלו
emails (
  id UUID PK,
  tenant_id FK,
  gmail_message_id TEXT UNIQUE,
  thread_id TEXT,
  from_email, from_name,
  subject TEXT,
  received_at TIMESTAMP,
  category TEXT,
  category_confidence FLOAT,
  urgency TEXT,
  sentiment TEXT,
  status TEXT,                -- processed/draft_ready/replied/ignored
  draft_id TEXT,              -- Gmail draft ID
  draft_text TEXT,            -- שמירה מקומית רק אם הלקוח הסכים
  ai_cost_usd DECIMAL,
  processing_ms INT,
  created_at, updated_at
)

-- חוקי ניתוב
routing_rules (
  id UUID PK,
  tenant_id FK,
  category_id FK,
  condition JSONB,            -- {sender_domain, urgency, keywords}
  action JSONB,               -- {forward_to, cc, notify_channel}
  priority INT,
  active BOOLEAN
)

-- ערוצי התראה
notification_channels (
  id UUID PK,
  tenant_id FK,
  type TEXT,                  -- whatsapp/slack/telegram
  config_encrypted JSONB,
  active BOOLEAN
)

-- אודיט
audit_log (
  id BIGSERIAL,
  tenant_id FK,
  user_id FK NULL,
  action TEXT,
  resource_type, resource_id,
  metadata JSONB,
  created_at TIMESTAMP
)

-- סטטיסטיקות יומיות (חישוב מראש)
daily_stats (
  tenant_id FK,
  date DATE,
  emails_received INT,
  drafts_created INT,
  auto_categorized INT,
  manually_corrected INT,
  ai_cost_usd DECIMAL,
  PRIMARY KEY (tenant_id, date)
)
```

### 6.2 אינדקסים חשובים
- `emails(tenant_id, received_at DESC)`
- `emails(tenant_id, category, status)`
- `faq_items` — IVFFlat / HNSW על `embedding`
- כל ה-FK עם `tenant_id` יחד

---

## 7. API Endpoints (Backend)

### 7.1 Auth
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

### 7.2 Gmail Connection
- `GET /gmail/oauth-url` — מחזיר URL להפניה
- `GET /gmail/callback` — סיום OAuth
- `POST /gmail/webhook` — Pub/Sub notifications
- `DELETE /gmail/disconnect`

### 7.3 Emails
- `GET /emails?category=&urgency=&status=&page=` — רשימה
- `GET /emails/:id` — פירוט + טיוטה
- `PATCH /emails/:id/category` — תיקון סיווג
- `POST /emails/:id/draft/regenerate`
- `POST /emails/:id/send` — שליחת הטיוטה

### 7.4 FAQ
- `GET /faq`
- `POST /faq`
- `PATCH /faq/:id`
- `DELETE /faq/:id`
- `POST /faq/import` — מקובץ/URL

### 7.5 Categories & Rules
- `GET/POST/PATCH/DELETE /categories`
- `GET/POST/PATCH/DELETE /routing-rules`

### 7.6 Settings
- `GET/PATCH /settings/tenant` — סגנון/חתימה/שפה
- `GET/POST/DELETE /notification-channels`

### 7.7 Stats
- `GET /stats/dashboard` — KPIs
- `GET /stats/timeline?from=&to=`

---

## 8. פרומפטים (Prompts)

### 8.1 פרומפט סיווג (System)
```
אתה מסווג מיילים עבור עסק מסוג: {business_type}.
שם העסק: {business_name}.

הקטגוריות הזמינות:
{categories_with_descriptions}

החזר JSON בלבד במבנה:
{
  "category": "<key>",
  "confidence": 0.0-1.0,
  "urgency": "low" | "normal" | "high",
  "sentiment": "positive" | "neutral" | "negative",
  "language": "he" | "en" | "other",
  "summary": "<משפט אחד בעברית>",
  "suggested_actions": ["..."]
}

חוקים:
- "high" urgency רק כשיש דחיפות אמיתית (לקוח כועס, deadline היום)
- אם לא בטוח, השתמש ב-"other" עם confidence נמוך
- summary חייב להיות בעברית גם אם המייל באנגלית
```
> נשלח עם **prompt caching** — רק תוכן המייל משתנה בכל קריאה.

### 8.2 פרומפט יצירת טיוטה (FAQ)
```
אתה כותב תשובות מייל בשם {business_name}.

סגנון: {tone}
שפת המייל המקורי: {language} — תענה באותה שפה.
חתימה: {signature}

הלקוח שאל:
"{email_body}"

נמצאה במאגר תשובה מתאימה:
"{faq_answer}"

כתוב תשובת מייל מנומסת ומקצועית שמתבססת על התשובה למעלה.
- פנייה אישית בתחילה (אם יש שם)
- אל תמציא מידע שלא נמצא בתשובה
- שמור על אורך סביר (לא יותר מ-150 מילים)
- סיים בחתימה
```

### 8.3 פרומפט יצירת טיוטה (Lead)
```
אתה כותב תשובה ראשונית ללקוח פוטנציאלי שפנה ל-{business_name} ({business_type}).

המייל שהתקבל:
"{email_body}"

כתוב תשובה שמטרותיה:
1. תודה על הפנייה
2. אישור קבלה
3. הזמנה לשיחת היכרות / שאלה ממקדת לקבלת מידע נוסף
4. ציפייה לזמן תגובה ({response_time})

סגנון: {tone}. שפה: {language}. חתימה: {signature}.
```

---

## 9. הגדרות לקוח (Tenant Config)

קובץ `tenant_config.yaml` שניתן לערוך גם דרך הדשבורד:

```yaml
business:
  name: "משרד עו״ד כהן ושות׳"
  type: "law_firm"
  language: he
  tone: formal_professional
  response_time: "תוך 24 שעות"
  signature: |
    בברכה,
    עו"ד יוסי כהן
    משרד עו"ד כהן ושות'
    טל: 03-1234567

categories:
  - key: faq
    auto_reply: true
  - key: new_case
    auto_reply: true
    routing:
      forward_to: "intake@cohen-law.co.il"
      notify: ["whatsapp:owner"]
  - key: court_deadline
    auto_reply: false
    urgency_override: high
    notify: ["whatsapp:owner", "sms:owner"]

ai:
  classifier_model: "claude-haiku-4-5-20251001"
  drafter_model: "claude-sonnet-4-6"
  faq_similarity_threshold: 0.78
  draft_max_words: 150

privacy:
  store_email_body: false
  retention_days: 90
```

---

## 10. אבטחה ופרטיות

### 10.1 OAuth
- Scopes מינימליים: `gmail.modify` (כדי להוסיף לייבל וטיוטה) — לא `gmail.send`
- מצב "draft only" → אין יכולת שליחה אוטומטית בכלל

### 10.2 הצפנה
- Refresh tokens מוצפנים ב-AES-256-GCM
- מפתח ראשי ב-KMS/Vault, לא ב-env
- כל המסד מוצפן at rest

### 10.3 פרטיות מיילים
- ברירת מחדל: לא שומרים body של מיילים — רק metadata
- ניתן להפעיל שמירה לטובת UI (הצגת תוכן בדשבורד) — בהסכמת לקוח
- מחיקה אוטומטית אחרי X ימים (config)

### 10.4 ציות
- עמידה ב-Google API Services User Data Policy
- מסך הסכמה ברור ב-OAuth
- מדיניות פרטיות ותנאי שימוש
- DPA לכל לקוח עסקי

---

## 11. שלבי פיתוח

### Phase 1 — Core MVP (שבועיים)
- [ ] Setup repo + docker-compose + CI
- [ ] DB schema + migrations
- [ ] Gmail OAuth flow
- [ ] Webhook receiver + worker
- [ ] AI classifier בסיסי
- [ ] FAQ vector search
- [ ] יצירת טיוטה ב-Gmail
- [ ] תיוג בסיסי
- [ ] Dashboard מינימלי (login, רשימת מיילים, FAQ CRUD)

### Phase 2 — Production Ready (שבועיים נוספים)
- [ ] חוקי ניתוב
- [ ] התראות WhatsApp + Slack
- [ ] אונבורדינג מודרך
- [ ] סטטיסטיקות
- [ ] ניהול קטגוריות מותאמות
- [ ] Prompt caching ואופטימיזציות עלות
- [ ] טסטים (unit + integration)
- [ ] Sentry + לוגים מובנים

### Phase 3 — Scale & Polish (שבוע)
- [ ] Multi-tenant מלא + bilbil
- [ ] טעינת FAQ ממסמכים/אתר
- [ ] עריכת טיוטה ב-dashboard
- [ ] Admin panel (לבעלי המוצר)
- [ ] תיעוד למשתמש
- [ ] Landing page

### Phase 4 — Future
- [ ] Outlook/IMAP
- [ ] שליחה אוטומטית לקטגוריות בטוחות (אחרי תקופת אמון)
- [ ] Fine-tuning על תיקונים של הלקוח
- [ ] אינטגרציה עם CRMs (HubSpot, מונדיי, Pipedrive)

---

## 12. מבנה תיקיות מוצע

```
emailflow/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routes
│   │   │   ├── auth.py
│   │   │   ├── emails.py
│   │   │   ├── faq.py
│   │   │   ├── gmail.py
│   │   │   └── stats.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   └── encryption.py
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   ├── services/
│   │   │   ├── gmail_client.py
│   │   │   ├── classifier.py
│   │   │   ├── drafter.py
│   │   │   ├── faq_search.py
│   │   │   ├── router.py
│   │   │   └── notifier.py
│   │   ├── workers/
│   │   │   ├── celery_app.py
│   │   │   └── tasks.py
│   │   ├── prompts/
│   │   │   ├── classifier.py
│   │   │   └── drafter.py
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── app/
│   │   ├── (dashboard)/
│   │   │   ├── emails/
│   │   │   ├── faq/
│   │   │   ├── settings/
│   │   │   └── stats/
│   │   ├── (auth)/
│   │   └── layout.tsx
│   ├── components/
│   ├── lib/
│   ├── package.json
│   └── Dockerfile
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   └── render.yaml
├── docs/
│   ├── SPEC.md               # המסמך הזה
│   ├── ONBOARDING.md
│   └── API.md
├── .env.example
├── .gitignore
├── CLAUDE.md
└── README.md
```

---

## 13. בדיקות (Testing)

### 13.1 Unit
- כל service (classifier, drafter, faq_search) עם mocks ל-LLM
- prompts: snapshot tests
- אבטחה: encryption/decryption

### 13.2 Integration
- Gmail API mock (responses)
- DB עם testcontainers
- E2E של עיבוד מייל (webhook → DB → draft)

### 13.3 Eval (איכות AI)
- dataset של 200 מיילים מסומנים ידנית פר תחום
- מדידת accuracy/precision/recall של הסיווג
- evaluation אוטומטי לטיוטות (LLM-as-judge על relevance, tone, accuracy)
- threshold לעדכון מודל / פרומפט

### 13.4 Load
- 1000 מיילים בו-זמנית — האם כל ה-jobs מטופלים תוך 5 דקות?

---

## 14. עלויות ותמחור

### 14.1 עלויות תפעול ללקוח (חודשי, ב-100 מיילים/יום)
- Anthropic API: ~$8 (Haiku לסיווג, Sonnet לטיוטות, עם prompt caching)
- OpenAI embeddings: ~$1
- Hosting (משותף): ~$5
- WhatsApp (Twilio): ~$3
- **סה"כ עלות**: ~$17/חודש

### 14.2 תמחור ללקוח (מוצע)
- **התקנה**: 2,500–4,000 ₪ (אונבורדינג, FAQ, אימון סגנון)
- **חודשי Basic**: 350 ₪ (עד 1,500 מיילים/חודש)
- **חודשי Pro**: 700 ₪ (עד 5,000 + ניתוב מתקדם + WhatsApp)
- **חודשי Enterprise**: 1,500 ₪+ (ללא הגבלה + תמיכה מועדפת)

---

## 15. KPIs להצלחה

- **דיוק סיווג**: ≥ 92% אחרי שבועיים של אימון על מיילים אמיתיים
- **טיוטות שאושרו ללא עריכה**: ≥ 60%
- **חיסכון בזמן מדווח**: ≥ 60 דק' ביום
- **NPS לקוחות**: ≥ 50
- **Churn חודשי**: ≤ 5%

---

## 16. סיכונים וטיפול

| סיכון | חומרה | טיפול |
|-------|--------|-------|
| Google דוחה את האפליקציה ב-OAuth verification | גבוהה | להגיש מוקדם, לעמוד בכל הדרישות, להכין מסמכים |
| AI ממציא תשובות (hallucination) | גבוהה | טיוטה בלבד + similarity threshold קשיח + אזהרה |
| דליפת תוכן מיילים | קריטית | לא לשמור body, encryption, audit log |
| עלות AI גבוהה ממה שצפינו | בינונית | prompt caching, מודל זול לסיווג, monitoring יומי |
| Push notifications של Gmail עוצרים (watch expires) | בינונית | renewal יומי + fallback polling |
| לקוח מבקש מותאם בקוד | בינונית | לדחות. הכל דרך config |

---

## 17. הצעדים הבאים

1. ✅ אישור ה-spec
2. יצירת repo חדש
3. העתקת המסמך ל-`docs/SPEC.md`
4. יצירת `CLAUDE.md` עם סגנון העבודה
5. התחלת Phase 1
