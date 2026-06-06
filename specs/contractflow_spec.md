# ContractFlow – Spec מימוש (Add-on ל-OfferFlow)

**גרסה:** 1.0
**תאריך:** 2026-05-16
**הקשר:** הרחבה למוצר OfferFlow – הוספת מודול חוזים אוטומטיים מבוססי הצעות מחיר שאושרו, עם חתימה דיגיטלית פשוטה.
**ארכיטקטורה:** Add-on פנימי בתוך הריפו והדומיין של OfferFlow. אותו DB, אותו codebase, אותו auth.
**עקרונות הנחיה:** SES בלבד, ללא עו"ד, תבניות גנריות, שימוש מקסימלי בתשתית קיימת.

---

## תוכן עניינים

1. [סקירה ומטרה](#1-סקירה-ומטרה)
2. [מסמכי ייחוס מחייבים](#2-מסמכי-ייחוס-מחייבים)
3. [Scope – מה כלול ומה לא](#3-scope--מה-כלול-ומה-לא)
4. [ארכיטקטורה ושילוב ב-OfferFlow](#4-ארכיטקטורה-ושילוב-ב-offerflow)
5. [מודל נתונים](#5-מודל-נתונים)
6. [Status machine של חוזה](#6-status-machine-של-חוזה)
7. [API Endpoints](#7-api-endpoints)
8. [תבניות חוזים – הגישה המינימלית](#8-תבניות-חוזים--הגישה-המינימלית)
9. [מנוע ה-AI – מילוי חוזה מהצעה](#9-מנוע-ה-ai--מילוי-חוזה-מהצעה)
10. [PDF Generation](#10-pdf-generation)
11. [עמוד חתימה ציבורי – Public View](#11-עמוד-חתימה-ציבורי--public-view)
12. [Audit Trail ו-Immutability](#12-audit-trail-ו-immutability)
13. [Notifications](#13-notifications)
14. [UI – מסכים פנימיים](#14-ui--מסכים-פנימיים)
15. [Billing ו-Quota](#15-billing-ו-quota)
16. [הגנות משפטיות ו-T&C](#16-הגנות-משפטיות-ו-tc)
17. [שלבי פיתוח](#17-שלבי-פיתוח)
18. [סיכונים והפחתה](#18-סיכונים-והפחתה)
19. [Checklist לפני release](#19-checklist-לפני-release)
20. [שאלות פתוחות להחלטה](#20-שאלות-פתוחות-להחלטה)
21. [נספח א – תבנית חוזה בסיס](#נספח-א--תבנית-חוזה-בסיס)
22. [נספח ב – ENV vars נדרשים](#נספח-ב--env-vars-נדרשים)
23. [נספח ג – טקסט הסכמה לחתימה](#נספח-ג--טקסט-הסכמה-לחתימה)

---

## 1. סקירה ומטרה

ContractFlow הוא מודול בתוך OfferFlow שמאפשר לבעל העסק להמיר הצעה שאושרה לחוזה משפטי בסיסי, לשלוח אותו ללקוח לחתימה דיגיטלית, ולשמור עותק חתום עם audit trail מלא.

**Killer flow:** הצעה אושרה → לחיצה אחת "צור חוזה" → AI ממלא את החוזה תוך 10 שניות → סקירה → שליחה ללקוח → חתימה דיגיטלית → סגירה.

**ערך לבעל העסק:**
- חיסכון של 30-60 דקות לכל חוזה (במקום העתקה מ-Word)
- חוזה אחיד וברור בכל פעם
- הוכחה משפטית שהלקוח חתם (timestamp + IP + signature image)
- סגירה מהירה יותר של עסקאות (פחות חיכוך)

**ערך ל-OfferFlow:**
- הצדקה לעדכון ל-Business tier
- הקטנת churn (לקוח עם חוזים פעילים לא עוזב)
- בידול חזק מול Quote+ ומתחרים אחרים שלא נותנים זאת

---

## 2. מסמכי ייחוס מחייבים

| מסמך | למה |
|------|-----|
| `docs/design_system.md` | כל ה-UI הפנימי של ContractFlow חייב להיות עקבי עם הפאנל הקיים של OfferFlow |
| `docs/Skills/hebrew-document-generator.md` | תבנית ה-PDF משתמשת באותו pipeline של WeasyPrint + RTL + עברית. **קרא לפני כל קוד שמייצר PDF.** |
| `OfferFlow-spec.md` (קיים) | מבנה ה-DB, ה-conventions של snapshot, immutability, share tokens, tracking |
| נספח של OfferFlow §1.3 | "snapshot הוא source of truth אחרי finalize. CRM הוא source of truth לפני." חל גם כאן |

**חריג חשוב:** עמוד החתימה הציבורי (`/c/{token}`) **לא** יורש את Dark mode של הפאנל. בדיוק כמו `/q/{token}` – Light variant ניטרלי שמייבא את `branding.primary_color` של בעל העסק.

---

## 3. Scope – מה כלול ומה לא

### ✅ כלול ב-MVP

- יצירת חוזה אוטומטית מהצעה שאושרה
- 3 תבניות בסיס (חוזה שירותים סטנדרטי / Letter of Engagement קצר / תבנית מותאמת אישית עם placeholders)
- AI שממלא את התבנית מהקשר ההצעה והעסק
- עריכה ידנית של ה-draft לפני שליחה
- שליחה ללקוח דרך לינק חתימה (`/c/{token}`)
- חתימה דיגיטלית פשוטה (SES) – canvas signature pad
- חתימה דו-צדדית: בעל עסק (פעם אחת בפרופיל) + לקוח (בכל חוזה)
- Audit trail מלא: יצירה, פתיחה, חתימה, IP, user agent, timestamp
- שמירת PDF סופי immutable + hash
- Notifications (email) על כל אירוע lifecycle
- אינטגרציה עם Mini-CRM (§1 של OfferFlow)
- אינטגרציה עם View tracking (§2 של OfferFlow)
- אינטגרציה עם Notifications system (§5 של OfferFlow)

### ❌ לא כלול ב-MVP

- ❌ AES (Advanced Electronic Signature) – אין OTP/SMS verification
- ❌ QES (Qualified Electronic Signature) – אין eIDAS/חתימה כשירה
- ❌ אינטגרציה עם DocuSign / Comda / ספקי חתימה כשירה
- ❌ חוזים מותאמים אישית עם סעיפים משפטיים מורכבים (שכ"ט עו"ד, נדל"ן, דיני עבודה)
- ❌ ניהול גרסאות (versioning) של חוזים – חוזה חתום הוא immutable, אם צריך שינוי – חוזה חדש
- ❌ חתימת מספר צדדים (3+) – רק owner + client אחד
- ❌ תרגום אוטומטי לאנגלית (V1.5)
- ❌ ניהול חוזים פעילים לאורך זמן (renewal, amendments)
- ❌ אינטגרציה עם CRM חיצוני / חתימה משפטית מקצועית

### 🎯 הפיצ'ר ההורג

**"אישור הצעה → חוזה חתום ב-3 לחיצות"**

לקוח אישר הצעה ב-OfferFlow → בעל העסק מקבל notification → לוחץ "צור חוזה" → AI ממלא תוך 10 שניות → סקירה מהירה → "שלח ללקוח" → לקוח חותם תוך דקות.

זה מה שיגרום לבעלי עסק לעבור מ-Word ידני לפלטפורמה.

---

## 4. ארכיטקטורה ושילוב ב-OfferFlow

### 4.1 איפה הקוד יושב

```
app/
├── routers/
│   ├── quotes.py              # קיים
│   ├── contracts.py           # ← חדש
│   └── public.py              # קיים – נוסיף את /c/{token}
├── models/
│   ├── quote.py               # קיים
│   ├── contract.py            # ← חדש
│   └── business_profile.py    # קיים – נרחיב
├── services/
│   ├── ai/
│   │   ├── quote_writer.py    # קיים
│   │   └── contract_writer.py # ← חדש
│   ├── pdf/
│   │   ├── quote_pdf.py       # קיים
│   │   └── contract_pdf.py    # ← חדש
│   ├── signature/
│   │   └── ses_handler.py     # ← חדש
│   ├── audit/
│   │   └── trail_builder.py   # ← חדש
│   └── reminders.py           # קיים – נרחיב
└── templates/
    ├── contracts/             # ← חדש
    │   ├── editor.html
    │   ├── preview.html
    │   └── public_sign.html
    └── pdf/
        └── contract_base.html # ← חדש
```

### 4.2 שיתוף תשתיות עם OfferFlow

| תשתית | שימוש מחדש |
|--------|------------|
| `BusinessProfile` | לוגו, ברנדינג, חתימת בעל עסק, תנאי תשלום ברירת מחדל |
| `clients` collection | אותו לקוח שאליו שלחת הצעה – אליו תשלח חוזה |
| `quotes` collection | חוזה מקושר ל-`quote_id` ויורש ממנו פריטים, סכומים, snapshot של הלקוח |
| WeasyPrint pipeline | אותו setup, אותם פונטים (Heebo/Assistant), אותו RTL |
| `hebrew-document-generator` skill | אותו playbook לטיפול ב-RTL/BiDi/פונטים |
| Public view pattern | `/q/{token}` היה המודל – `/c/{token}` בנוי באותו דפוס |
| View duration tracking | אותו מנגנון §2 – section dwell יישמר באותה צורה |
| Notifications | אותה collection `notifications`, אותו service – נוסיף סוגי events |
| Reminders pipeline | מרחיבים את `app/services/reminders.py` – לא כותבים מחדש |
| Auth, billing, quota | אותו מנגנון לחלוטין |

### 4.3 מה שונה ב-ContractFlow

- **Immutability חזקה:** הצעה ננעלת ב-`finalize`. חוזה ננעל ב-`signed` – וגם document_hash נשמר.
- **חתימה דיגיטלית:** חידוש מלא, לא היה ב-OfferFlow.
- **שתי חתימות בכל מסמך:** בעל עסק (תמונה מהפרופיל) + לקוח (canvas פעיל).
- **Audit trail מסודר:** ב-OfferFlow זה היה `tracking.opens[]`. כאן זה רשימה מסודרת של אירועי lifecycle.

---

## 5. מודל נתונים

### 5.1 `contracts` collection (חדש)

```python
{
  "_id": ObjectId,
  "user_id": ObjectId,                      # owner
  "contract_number": "CT-2026-0042",        # auto, similar to quote_number
  "quote_id": ObjectId | None,              # מקושר להצעה (אם נוצר ממנה)
  "client_id": ObjectId | None,             # reference ל-clients collection
  "client_snapshot": dict,                  # snapshot מלא של הלקוח בעת finalize

  "status": "draft",                        # ראה §6
  "title": str,                             # "חוזה התקשרות לעיצוב לוגו ואתר"

  "template_type": "standard",              # standard | letter | custom
  "template_id": ObjectId | None,           # אם custom – reference ל-contract_templates
  "sections": {                             # תוכן החוזה לאחר מילוי
    "preamble": str,                        # "הואיל ו..."
    "scope_of_work": str,
    "deliverables": list[str],
    "timeline": str,
    "payment_terms": str,
    "intellectual_property": str,
    "confidentiality": str,
    "warranty_and_liability": str,
    "termination": str,
    "general_provisions": str,
    "appendix_items": list[dict]            # מה-Quote.items
  },

  "totals": {                               # מועתק מההצעה (snapshot)
    "subtotal": float,
    "vat_rate": float,
    "vat_amount": float,
    "total_with_vat": float
  },

  "owner_signature": {
    "image_url": str,                       # מ-BusinessProfile.owner_signature_url
    "signed_at": datetime,                  # רגע ה-finalize
    "snapshot_name": str                    # שם בעל העסק בעת החתימה
  },
  "client_signature": {
    "image_url": str | None,                # canvas → image (R2)
    "signed_at": datetime | None,
    "signer_name": str | None,              # שם שהקליד הלקוח
    "signer_id": str | None,                # ת.ז./ח.פ. אם נדרש
    "ip": str | None,
    "user_agent": str | None,
    "consent_text": str | None              # הטקסט שהלקוח אישר
  },

  "share": {
    "public_token": str,                    # secrets.token_urlsafe(32)
    "shareable_url": str,
    "expires_at": datetime | None
  },

  "pdf": {
    "draft_url": str | None,                # PDF של ה-draft (regenerated on edit)
    "final_url": str | None,                # PDF סופי אחרי חתימה (immutable)
    "document_hash": str | None             # sha256 של ה-final PDF
  },

  "audit_trail": [                          # ראה §12
    {
      "event": "created",
      "at": datetime,
      "actor": "owner",                     # owner | client | system
      "actor_id": str | None,
      "ip": str | None,
      "user_agent": str | None,
      "metadata": dict
    }
  ],

  "ai_metadata": {
    "used_ai": bool,
    "tokens_in": int,
    "tokens_out": int,
    "cost_usd": float,
    "model": str
  },

  "is_immutable": bool,                     # True אחרי signed
  "created_at": datetime,
  "updated_at": datetime,
  "finalized_at": datetime | None,          # רגע השליחה ללקוח
  "signed_at": datetime | None              # רגע החתימה של הלקוח
}
```

**אינדקסים:**
- `{ user_id: 1, status: 1, created_at: -1 }` – לרשימת חוזים בדשבורד
- `{ "share.public_token": 1 }` unique sparse – ל-public view
- `{ contract_number: 1 }` unique – למניעת כפילות
- `{ quote_id: 1 }` – למצוא חוזים שיוצרו מהצעה

### 5.2 הרחבות ל-`BusinessProfile`

```python
# הוסף:
contracts_settings: {
  "default_template": "standard",          # standard | letter
  "include_appendix_items": True,           # האם לכלול נספח פירוט פריטים
  "default_terms": {
    "intellectual_property": str,           # ברירת מחדל לסעיף קניין רוחני
    "confidentiality": str,
    "warranty": str,
    "termination_notice_days": int = 30
  },
  "contract_numbering": {
    "prefix": "CT",
    "starting_number": 1000,
    "current_number": 1000,
    "locked": False
  },
  "require_client_id_number": False,        # לדרוש ת.ז./ח.פ. בחתימה?
  "include_owner_signature_in_pdf": True
}
```

### 5.3 `contract_templates` collection (חדש – למשתמש ולמערכת)

```python
{
  "_id": ObjectId,
  "owner": "system" | ObjectId,             # system templates או user templates
  "name": str,
  "description": str,
  "template_type": "standard" | "letter" | "custom",
  "industry": str | None,                   # אם מותאם לתחום
  "language": "he",                         # ברירת מחדל
  "sections_order": list[str],              # סדר הסקשנים
  "section_templates": {                    # תבניות לכל סקשן (Jinja2 syntax)
    "preamble": "הואיל ו{{owner.business_name}}...",
    "scope_of_work": "...",
    # ...
  },
  "placeholders": list[str],                # רשימת placeholders זמינים
  "is_active": bool,
  "created_at": datetime
}
```

### 5.4 הרחבת `notifications` collection

הוסף סוגי events:
- `contract_created`
- `contract_sent`
- `contract_viewed`
- `contract_signed`
- `contract_declined`
- `contract_reminder`

### 5.5 הרחבת `audit_events` (אופציונלי – או tracking בתוך contract)

המלצה: להחזיק את ה-audit trail **בתוך ה-contract document** (`audit_trail` array). יתרון: אטומיות, קל לייצוא, immutable יחד עם המסמך. חיסרון: גודל document. עבור 50 events זה זניח.

---

## 6. Status machine של חוזה

```
draft ──► review ──► sent ──► viewed ──► signed
  │                    │         │         │
  │                    │         ▼         ▼
  │                    │      declined  (immutable)
  ▼                    ▼
deleted             expired
```

| סטטוס | משמעות | פעולות מותרות |
|-------|---------|----------------|
| `draft` | חדש, AI מילא, בעל העסק עורך | edit, delete, finalize |
| `review` | בעל העסק סיים עריכה, מאשר לפני שליחה | edit, finalize, back to draft |
| `sent` | נשלח ללקוח, מחכה לפתיחה | resend, cancel, view audit |
| `viewed` | הלקוח פתח | resend, cancel, view audit |
| `signed` | הלקוח חתם – **immutable** | view, download, share |
| `declined` | הלקוח דחה | view, create new, view reason |
| `expired` | עבר תוקף בלי חתימה | duplicate, view |

**מעברים אסורים:** אחרי `signed` – כלום (חוץ מצפייה והורדה).

**Immutability gate:** כל write/edit endpoint בודק `is_immutable` לפני שמרשה לפעול.

---

## 7. API Endpoints

### 7.1 ניהול חוזים (פנימי – auth required)

| Method | Path | תיאור |
|--------|------|-------|
| `GET` | `/api/contracts` | רשימה (filters: status, client, date) |
| `POST` | `/api/contracts` | יצירה ידנית מאפס |
| `POST` | `/api/contracts/from-quote/{quote_id}` | יצירה מהצעה שאושרה (Killer flow) |
| `GET` | `/api/contracts/{id}` | שליפה |
| `PUT` | `/api/contracts/{id}` | עדכון (רק ב-draft/review) |
| `DELETE` | `/api/contracts/{id}` | מחיקה (רק ב-draft) |
| `POST` | `/api/contracts/{id}/finalize` | שליחה ללקוח – יוצר share token, מקפיא snapshot |
| `POST` | `/api/contracts/{id}/cancel` | ביטול לפני חתימה |
| `POST` | `/api/contracts/{id}/duplicate` | שכפול (יוצר draft חדש) |
| `GET` | `/api/contracts/{id}/audit` | צפייה ב-audit trail |
| `GET` | `/api/contracts/{id}/pdf` | הורדת PDF (draft או final) |

### 7.2 AI

| Method | Path | תיאור |
|--------|------|-------|
| `POST` | `/api/contracts/{id}/ai/generate` | מילוי כל החוזה מההצעה (Killer flow) |
| `POST` | `/api/contracts/{id}/ai/regenerate-section` | רגנרציה של סקשן ספציפי (`{section: "scope_of_work"}`) |
| `POST` | `/api/contracts/ai/from-text` | יצירה מתיאור חופשי (כמו Quick AI ב-OfferFlow) |

### 7.3 תבניות

| Method | Path | תיאור |
|--------|------|-------|
| `GET` | `/api/contract-templates` | רשימת תבניות זמינות (system + user) |
| `POST` | `/api/contract-templates` | יצירת תבנית מותאמת |
| `PUT` | `/api/contract-templates/{id}` | עדכון |
| `DELETE` | `/api/contract-templates/{id}` | מחיקה |
| `POST` | `/api/contract-templates/{id}/upload` | העלאת Word/PDF עם placeholders |

### 7.4 Public (ללא auth)

| Method | Path | תיאור |
|--------|------|-------|
| `GET` | `/c/{token}` | עמוד חתימה ללקוח |
| `GET` | `/c/{token}/pdf` | הורדת ה-PDF של הטיוטה לעיון |
| `POST` | `/c/{token}/track` | endpoint למעקב view duration (כמו ב-OfferFlow §2) |
| `POST` | `/c/{token}/sign` | חתימה (signature image + name + consent) |
| `POST` | `/c/{token}/decline` | דחייה (עם סיבה אופציונלית) |

### 7.5 Webhooks (פנימי – לאינטגרציה עם quotes)

`POST /api/quotes/{id}/accept` – ב-OfferFlow כבר קיים. נוסיף בו:
- אם ל-tenant יש ContractFlow פעיל ובעל העסק הפעיל auto-create – צור draft של חוזה אוטומטית
- שלח notification: "ההצעה אושרה. החוזה ממתין לאישורך."

---

## 8. תבניות חוזים – הגישה המינימלית

### 8.1 שלוש תבניות בסיס (System Templates)

#### תבנית 1: **Standard Service Agreement** (חוזה שירותים סטנדרטי)

**מתי:** רוב המקרים – פיתוח, עיצוב, ייעוץ, צילום, שירותים מקצועיים.

**סקשנים (10):**
1. **Preamble** – "הואיל ו..." זיהוי הצדדים והקונטקסט
2. **Scope of Work** – פירוט העבודה (מהצעת המחיר)
3. **Deliverables** – תוצרים ספציפיים
4. **Timeline** – לוח זמנים
5. **Payment Terms** – תנאי תשלום (מההצעה)
6. **Intellectual Property** – קניין רוחני (ברירת מחדל: עובר ללקוח עם תשלום מלא)
7. **Confidentiality** – סודיות הדדית
8. **Warranty and Liability** – אחריות והגבלות
9. **Termination** – תנאי סיום
10. **General Provisions** – שונות (סמכות שיפוט, שינויים, חתימה)

**אורך משוער:** 3-4 עמודים.

#### תבנית 2: **Letter of Engagement** (מסמך התקשרות קצר)

**מתי:** עסקאות קטנות (עד 5,000₪), לקוחות חוזרים, חיכוך נמוך.

**סקשנים (5):**
1. פתיח אישי
2. תיאור העבודה (קצר)
3. מחיר ותנאי תשלום
4. לוח זמנים
5. אישור והסכמה

**אורך משוער:** עמוד אחד.

#### תבנית 3: **Custom** (מותאמת אישית)

הלקוח מעלה Word/PDF משלו עם placeholders בפורמט Jinja2:

```
חוזה התקשרות בין:

{{owner.business_name}} ({{owner.business_id}})
לבין:
{{client.name}} ({{client.business_id_or_personal}})

נשוא ההתקשרות: {{quote.title}}

תמורה: {{quote.totals.total_with_vat}} ש"ח כולל מע"מ

לוח תשלומים:
{{payment_schedule}}

מועד אספקה: {{delivery_date}}

{{custom_clauses}}

תאריך: {{contract.signed_at | format_date}}
```

**Placeholders זמינים** (מוגדרים מראש):
- `owner.*` – business_name, business_id, address, phone, email, signature_image
- `client.*` – name, business_name, business_id, email, phone, address
- `quote.*` – title, items, totals, payment_terms
- `contract.*` – contract_number, created_at, signed_at
- `custom_clauses` – טקסט חופשי לעריכה

**עיבוד:** ה-AI מזהה את ה-placeholders, ממלא, ומחזיר HTML מוכן ל-WeasyPrint.

### 8.2 התאמה לתחום עסק

ה-AI מקבל את `business_type` מהפרופיל ומתאים ניסוחים:
- **עיצוב גרפי / פיתוח אתרים:** דגש על קניין רוחני, מקורות, תיקונים
- **צילום:** דגש על זכויות שימוש בתמונות, GDPR לאנשים בתמונה
- **ייעוץ עסקי:** דגש על סודיות, ללא ערבות תוצאה
- **קבלן שיפוצים:** דגש על אחריות לעבודה, ביטוח, גמר חשבון

**אין תבניות נפרדות לכל תחום** – זו אותה תבנית סטנדרטית, רק עם dial של AI.

---

## 9. מנוע ה-AI – מילוי חוזה מהצעה

### 9.1 הקלט

```python
{
  "quote_snapshot": {...},                  # snapshot מההצעה שאושרה
  "client_snapshot": {...},
  "business_profile": {...},
  "template_type": "standard",
  "owner_overrides": {                      # אם בעל העסק רוצה לדרוס משהו
    "delivery_date": "2026-08-15",
    "extra_clauses": "..."
  }
}
```

### 9.2 ה-Prompt

```python
SYSTEM = """
אתה עוזר ליצירת חוזים בעברית לעסק קטן.
החוזה הוא {template_type} בעברית, RTL, מקצועי אך לא מנופח.

תחום העסק: {business_type}
פרופיל העסק: {business_profile}

עקרונות חובה:
- שפה ברורה ופשוטה (לא משפטית מנופחת)
- 2-4 שורות לכל סקשן (לא יותר)
- אסור להמציא עובדות שלא בקלט
- אם חסרים פרטים – השאר placeholder ברור (למשל [תאריך אספקה לא צוין])
- תמיד כלול פסקת אזהרה: "מסמך זה אינו תחליף לייעוץ משפטי"

החזר JSON עם המבנה:
{
  "preamble": "...",
  "scope_of_work": "...",
  "deliverables": ["..."],
  "timeline": "...",
  "payment_terms": "...",
  "intellectual_property": "...",
  "confidentiality": "...",
  "warranty_and_liability": "...",
  "termination": "...",
  "general_provisions": "..."
}
"""

USER = """
הקשר ההצעה שאושרה:
{quote_snapshot_json}

לקוח:
{client_snapshot_json}

הנחיות נוספות מהבעלים:
{owner_overrides_json}

מלא את כל הסקשנים של החוזה.
"""
```

### 9.3 Prompt Caching

- **Cached:** SYSTEM prompt + business_profile + template definition – משתנים לעיתים נדירות
- **Not cached:** quote_snapshot, client_snapshot – משתנים בכל חוזה

חיסכון משוער: 60-70% בעלות לכל חוזה אחרי ה-2 הראשונים בחודש.

### 9.4 עלות יחידה

- ~3000 tokens in (כולל cached) + 1500 tokens out
- ~$0.012 לחוזה (Sonnet 4.6)
- מנוי 149₪ → רווח גולמי 99%

### 9.5 Self-critique pass (אופציונלי, מומלץ)

אחרי הטיוטה הראשונה, קריאה שנייה ל-AI:
> "סקור את החוזה הבא. בדוק: (1) חסרים פרטים מההצעה? (2) יש סתירה פנימית? (3) האם הניסוח ברור ללקוח לא משפטן? החזר רשימת תיקונים."

ואז עוד pass לתיקון. מעלה עלות פי 2 אבל איכות גבוהה משמעותית.

**המלצה:** Self-critique רק במסלול Business. ב-Pro – pass יחיד.

---

## 10. PDF Generation

### 10.1 שימוש ב-pipeline הקיים

אותו WeasyPrint, אותו `hebrew-document-generator` skill, אותם פונטים. **לא לבנות מנוע PDF חדש.**

### 10.2 תבנית `contract_base.html`

מבנה דומה ל-PDF של הצעה:

```
┌─────────────────────────────────────┐
│  [Logo]    חוזה התקשרות #CT-1042   │
│                  16 במאי 2026       │
├─────────────────────────────────────┤
│  בין:                                │
│  {{owner.business_name}} ({{ID}})   │
│                                     │
│  לבין:                               │
│  {{client.name}} ({{ID}})           │
├─────────────────────────────────────┤
│  הואיל ו... [preamble]              │
├─────────────────────────────────────┤
│  1. נשוא ההתקשרות                   │
│     [scope_of_work]                 │
│                                     │
│  2. תוצרים                          │
│     • [deliverables[0]]             │
│     • [deliverables[1]]             │
│                                     │
│  3. לוח זמנים                       │
│     [timeline]                      │
│                                     │
│  4. תמורה ותנאי תשלום               │
│     [payment_terms]                 │
│     ┌──────┬─────┬──────┐           │
│     │ פריט │ כמות│ מחיר │           │
│     └──────┴─────┴──────┘           │
│     סה"כ: {{totals.total_with_vat}} │
│                                     │
│  5. קניין רוחני [...]               │
│  6. סודיות [...]                    │
│  7. אחריות [...]                    │
│  8. תנאי סיום [...]                 │
│  9. שונות [...]                     │
├─────────────────────────────────────┤
│  ⚠️ מסמך זה אינו תחליף לייעוץ משפטי. │
│     בעת ספק יש להתייעץ עם עו"ד.    │
├─────────────────────────────────────┤
│  חתימת בעל העסק:                    │
│  [תמונת חתימה]                       │
│  {{owner.name}}                     │
│  {{owner.business_name}}            │
│  תאריך: {{contract.created_at}}     │
│                                     │
│  חתימת הלקוח:                       │
│  [תמונת חתימה / "ממתין לחתימה"]     │
│  {{client.name}}                    │
│  תאריך: {{contract.signed_at}}      │
│                                     │
│  IP: {{client_signature.ip}}        │
│  קוד אימות: {{document_hash[:8]}}   │
└─────────────────────────────────────┘
```

### 10.3 שני PDFs – draft ו-final

| גרסה | מתי נוצר | מה כולל |
|------|----------|---------|
| **Draft PDF** | בכל עדכון של הטיוטה (cache לפי hash של תוכן) | חתימת בעל עסק (אם הופעל), אזור חתימת לקוח ריק |
| **Final PDF** | רגע ה-`signed` event | שתי החתימות, audit trail summary, document_hash מודפס בתחתית |

**חשוב:** ה-final PDF הוא **immutable**. נשמר ב-R2 עם content-addressing (filename = hash). אסור לדרוס.

### 10.4 גוצ'ות

- חתימת בעל העסק = תמונה מ-`BusinessProfile.owner_signature_url`. אם אין – placeholder "(חתימה אלקטרונית)".
- חתימת לקוח = תמונה מ-canvas שהומרה ל-PNG עם רקע שקוף.
- שני העמודים האחרונים תמיד עם `page-break-before: always` כדי שהחתימה לא תיחתך.
- שורת התחתית עם hash + IP – font קטן (8pt), אבל קריא.

---

## 11. עמוד חתימה ציבורי – Public View

### 11.1 הפלואו של הלקוח

```
1. לקוח מקבל לינק במייל / WhatsApp:
   https://offerflow.app/c/aB3xY9...

2. נחיתה על העמוד:
   ▸ logged audit event: contract_viewed (IP, UA, timestamp)
   ▸ מתחיל view duration tracking (אותו מנגנון §2 של OfferFlow)

3. הלקוח רואה:
   ▸ בנר עליון: "הצעת התקשרות מ-{{business_name}}"
   ▸ תוכן החוזה (HTML responsive – לא PDF embedded)
   ▸ כפתור "הורד PDF" בצד
   ▸ section navigation (jump to: עבודה / תשלום / סיום)

4. בתחתית:
   ▸ checkbox: "קראתי והבנתי את תנאי החוזה"
   ▸ שדה: "שם מלא" (חובה)
   ▸ שדה: "ת.ז./ח.פ." (אם בעל העסק הפעיל require_client_id_number)
   ▸ Canvas signature (signature_pad.js)
   ▸ checkbox: "אני מאשר שהחתימה היא חתימתי הדיגיטלית" (consent)
   ▸ כפתור: "חתום ושלח"

5. בעת חתימה:
   ▸ Frontend: ולידציה (canvas not empty, name filled, both checkboxes)
   ▸ POST /c/{token}/sign עם:
     - signature image (PNG base64)
     - signer_name
     - signer_id (אם נדרש)
     - consent_text (הטקסט המדויק שהוצג)
     - client_timestamp
   ▸ Server:
     - ולידציה
     - העלאת signature image ל-R2
     - יצירת final PDF
     - חישוב document_hash
     - update contract: status=signed, immutable=true
     - audit_trail.append({event: "signed", at, ip, ua, ...})
     - שליחת notifications לבעל העסק (email)
     - שליחת עותק חתום למייל הלקוח

6. עמוד thank you + לינק להורדה
```

### 11.2 חוויית מובייל

- 60%+ מהלקוחות יחתמו במובייל
- canvas signature חייב לעבוד עם touch events (signature_pad.js תומך)
- כפתורים גדולים, שדות עם font-size: 16px (למניעת zoom ב-iOS)
- שמירת draft של מילוי השדות ב-localStorage (אם הלקוח עזב וחזר)

### 11.3 דחייה

אם הלקוח לוחץ "דחה":
- שדה אופציונלי: "סיבת הדחייה"
- POST /c/{token}/decline
- audit event: contract_declined
- notification לבעל העסק
- העמוד נסגר עם הודעת תודה

### 11.4 בטיחות

- ה-token (`secrets.token_urlsafe(32)`) הוא ה-authorization. לא צריך login.
- Rate limiting: max 100 requests per token per hour
- אם החוזה כבר signed/declined – העמוד מציג סטטוס בלבד, לא ניתן לחזור על הפעולה
- HTTPS חובה
- CSP headers מחמירים (להגן מ-XSS דרך הניסוח של AI)

---

## 12. Audit Trail ו-Immutability

### 12.1 מבנה האירועים

כל אירוע ב-`audit_trail` מכיל:

```python
{
  "event": str,                    # ראה רשימה למטה
  "at": datetime,                  # UTC
  "actor": "owner" | "client" | "system",
  "actor_id": str | None,          # user_id או "anonymous"
  "ip": str | None,
  "user_agent": str | None,
  "metadata": dict                 # event-specific
}
```

### 12.2 רשימת events מלאה

| event | metadata | מתי |
|-------|----------|-----|
| `created` | template_type, ai_used | יצירה ראשונה |
| `edited` | sections_changed | בכל edit |
| `ai_regenerated` | section, tokens | רגנרציה של סקשן |
| `finalized` | shareable_url | שליחה ללקוח |
| `viewed` | view_duration_sec | פתיחה ע"י לקוח |
| `section_viewed` | section, dwell_sec | מעקב per section |
| `pdf_downloaded` | by: "owner" \| "client" | הורדה |
| `signature_started` | – | לקוח התחיל לצייר |
| `signature_cleared` | – | לקוח ניקה ולא הגיש |
| `signed` | signer_name, signer_id, document_hash, consent | חתימה הסתיימה |
| `declined` | reason | דחייה |
| `reminder_sent` | type, channel | תזכורת אוטומטית |
| `expired` | – | עבר תוקף |

### 12.3 Immutability mechanism

```python
async def update_contract(contract_id, changes, user_id):
    contract = await db.contracts.find_one({"_id": contract_id, "user_id": user_id})

    if contract.get("is_immutable"):
        raise ImmutableContractError(
            "החוזה חתום ולא ניתן לעריכה. צור חוזה חדש במקום."
        )

    if contract["status"] in ("signed", "declined"):
        raise InvalidStatusError(...)

    # ... apply changes
    await log_audit_event(contract_id, "edited", ...)
```

ב-`signed` event:
```python
async def finalize_signing(contract_id, signature_data):
    # 1. צור final PDF
    pdf_bytes = await render_final_pdf(contract_id, signature_data)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_url = await upload_to_r2(pdf_bytes, f"contracts/{pdf_hash}.pdf")

    # 2. update contract atomically
    await db.contracts.update_one(
        {"_id": contract_id, "is_immutable": False},  # double-check
        {
            "$set": {
                "status": "signed",
                "signed_at": now(),
                "is_immutable": True,
                "client_signature": signature_data,
                "pdf.final_url": pdf_url,
                "pdf.document_hash": pdf_hash,
            },
            "$push": {
                "audit_trail": {
                    "event": "signed",
                    "at": now(),
                    # ...
                }
            }
        }
    )
    # 3. trigger notifications
```

### 12.4 ייצוא Audit Report

endpoint שמייצר PDF נוסף עם כל ה-audit trail – שימושי בסכסוכים. נדחה ל-V1.5 אבל המבנה תומך בזה כבר עכשיו.

---

## 13. Notifications

### 13.1 events חדשים בהגדרות הקיימות

מוסיפים ל-`notification_preferences` של ה-tenant:

```python
contract_notifications: {
  "on_contract_created": True,        # כשהצעה אושרה ונוצרה טיוטה
  "on_contract_viewed": True,         # לקוח פתח
  "on_contract_signed": True,         # לקוח חתם – חובה תמיד
  "on_contract_declined": True,
  "channels": ["email"]               # WhatsApp ב-V1.5
}
```

### 13.2 תבניות notifications

לכל event יש תבנית מייל קצרה:

**`on_contract_created`:**
> "ההצעה QT-1042 שנשלחה ל[שם לקוח] אושרה. טיוטת חוזה ממתינה לסקירה שלך."
> [כפתור: סקור חוזה]

**`on_contract_viewed`:**
> "[שם לקוח] פתח את החוזה CT-1042 כרגע."
> [כפתור: צפה בחוזה]

**`on_contract_signed`:** ← **חובה, לא ניתן לכבות**
> "🎉 [שם לקוח] חתם על החוזה CT-1042!"
> "סכום: 8,190 ש"ח | חתימה ב: 16/05/2026 14:32"
> [כפתור: הורד עותק חתום]

**עותק ללקוח (אוטומטי בעת חתימה):**
> "תודה על החתימה. מצורף עותק חתום של החוזה."
> [PDF attachment]

### 13.3 שילוב ב-pipeline הקיים

לפי החלטה §5 בנספח של OfferFlow – לא לכתוב חדש, להרחיב את `app/services/reminders.py` ו-`notifications`. אותה collection, אותו service.

### 13.4 Reminders (תזכורות)

אם החוזה `sent` ולא `viewed` תוך 3 ימים → תזכורת אוטומטית.
אם `viewed` ולא `signed` תוך 5 ימים → תזכורת.
אם `signed` לא קרה תוך 14 יום מ-`sent` → סטטוס → `expired`, notification לבעל העסק.

---

## 14. UI – מסכים פנימיים

### 14.1 דשבורד ContractFlow (חדש)

הוסף קלף ב-dashboard הקיים:
```
┌──────────────────────────────────────┐
│  📄 חוזים                             │
│                                      │
│  פעילים: 12   ממתינים לחתימה: 3     │
│  חתומים החודש: 8   שווי: 67,500 ₪   │
│                                      │
│  [צפייה בחוזים →]                    │
└──────────────────────────────────────┘
```

### 14.2 רשימת חוזים `/contracts`

טבלה עם פילטרים:
- מספר חוזה
- שם לקוח
- סטטוס (badge צבעוני)
- סכום
- תאריך יצירה
- פעולות (צפייה / הורדה / שליחה חוזרת / מחיקה)

### 14.3 מסך עריכה `/contracts/{id}/edit` – הלב

מבנה דומה לעורך הצעה ב-OfferFlow:

```
┌──────────────────────────────────────────────────────────┐
│ עריכת חוזה CT-1042         [שמור] [תצוגה] [שלח ללקוח]  │
├──────────────────────────────────────────────────────────┤
│ ┌───── שמאל: עורך ─────┐  ┌─── ימין: Live preview ───┐  │
│ │                      │  │                          │  │
│ │ 📋 הקשר              │  │  [PDF preview]           │  │
│ │  הצעה: QT-1042 ✓    │  │  Live updates            │  │
│ │  לקוח: דנה כהן       │  │                          │  │
│ │  סכום: 8,190 ₪       │  │                          │  │
│ │                      │  │                          │  │
│ │ ✨ Quick AI:         │  │                          │  │
│ │  [צור חוזה מההצעה]   │  │                          │  │
│ │                      │  │                          │  │
│ │ 📑 תבנית             │  │                          │  │
│ │  ▸ Standard ✓       │  │                          │  │
│ │  ○ Letter           │  │                          │  │
│ │  ○ Custom           │  │                          │  │
│ │                      │  │                          │  │
│ │ 📝 סקשנים            │  │                          │  │
│ │  ▸ Preamble [✨]    │  │                          │  │
│ │  ▸ Scope    [✨]    │  │                          │  │
│ │  ▸ Payment  [✨]    │  │                          │  │
│ │  ▸ IP       [✨]    │  │                          │  │
│ │  ... (10 סקשנים)    │  │                          │  │
│ │                      │  │                          │  │
│ │ ⚙️ הגדרות            │  │                          │  │
│ │  □ דרוש ת.ז./ח.פ.   │  │                          │  │
│ │  ☑ הצג חתימת בעלים  │  │                          │  │
│ │  תוקף: 14 ימים       │  │                          │  │
│ └──────────────────────┘  └──────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**כל סקשן:** כפתור [✨] = "ניסוח מחדש עם AI" → modal עם 2-3 וריאציות.

### 14.4 מסך פרטי חוזה (לחוזים חתומים) `/contracts/{id}`

- כותרת + סטטוס badge
- 4 טאבים: **מסמך** | **Audit trail** | **חתימות** | **קישורים**
- כל הפעולות שעדיין רלוונטיות (הורדה, שליחה ללקוח שוב, צפייה בלינק ציבורי)
- אזור Audit trail מציג timeline ויזואלי של כל ה-events

### 14.5 מסך תבניות `/profile/contract-templates`

- רשימת system templates (read-only)
- + רשימת custom templates של המשתמש
- כפתור "הוסף תבנית מותאמת" → wizard:
  1. העלאת קובץ Word/PDF
  2. AI מזהה placeholders ומציע מיפוי
  3. בדיקה ואישור
  4. שמירה

---

## 15. Billing ו-Quota

### 15.1 שילוב במסלולים הקיימים

עדכון לטבלת התמחור של OfferFlow:

| Plan | מחיר | חוזים | הערה |
|------|------|--------|------|
| **Free** | חינם | 0 | אין גישה ל-ContractFlow |
| **Starter** | 49₪ | – | אין גישה |
| **Pro** | 89₪ | Pay-as-you-go: 19₪/חוזה | גישה ופלוס per-contract |
| **Business** | 149₪ | 20 חוזים בחודש כלולים | מעבר – 9₪/חוזה |
| **Pro+Contracts** | 129₪ | 10 חוזים בחודש כלולים | חבילה ייעודית |

### 15.2 Pay-as-you-go

לקוחות Pro שלא רוצים לעדכן ל-Business יכולים לקנות חוזים בודדים:
- 19₪ לחוזה (חיוב בעת `finalize`)
- חיוב באמצעות אותו payment provider של המנוי

### 15.3 Quota tracking

בהמשך ל-§7 של נספח OfferFlow (counter עולה ב-`finalize`, לא ב-`create_draft`):

```python
contracts_quota: {
  "monthly_used": int = 0,
  "monthly_limit": int = 20,        # לפי plan
  "monthly_reset_at": datetime,
  "lifetime_overage_count": int = 0  # למעקב per-contract billing
}
```

### 15.4 Grandfathering

אם משדרגים מ-Pro ל-Business באמצע החודש – Quota מתאפס ומקבלים מלוא 20.

---

## 16. הגנות משפטיות ו-T&C

### 16.1 דיסקליימר חובה בכל חוזה

ב-PDF, באנר ברור:

> ⚠️ **מסמך זה אינו תחליף לייעוץ משפטי.**
> תבניות החוזה הן בסיס בלבד. בעת ספק או עסקאות מהותיות, יש להתייעץ עם עו"ד.
> ContractFlow אינה אחראית לתוקף משפטי או להתאמת התבנית למקרה ספציפי.

### 16.2 T&C של ContractFlow (להוסיף ל-OfferFlow)

סעיפים שחייבים להיכלל:
1. **השירות הוא טכנולוגי, לא משפטי.** ContractFlow מספקת כלים ליצירת מסמכים, לא ייעוץ משפטי.
2. **הסכמה לחתימה אלקטרונית** – המשתמש מאשר שחתימה אלקטרונית מחייבת אותו מבחינתו.
3. **שמירת נתונים** – חוזים חתומים נשמרים מינימום 7 שנים (תקופת התיישנות).
4. **הסרת אחריות** – אין אחריות לפרשנות משפטית, לתוקף בערכאות, או להתאמה לדין הספציפי.
5. **שימוש מותר** – אסור להשתמש לעסקאות לא חוקיות, נדל"ן, דיני משפחה, או מסמכים מוסדרים.
6. **זכויות יוצרים** – התבניות הן רכוש OfferFlow, מותר שימוש פרטי בלבד.

### 16.3 Consent text במסך חתימה

ראה נספח ג למלוא הטקסט.

### 16.4 חוק חתימה אלקטרונית, התשס"א-2001

המוצר מספק **חתימה אלקטרונית פשוטה** כהגדרתה בחוק. תקפה ב:
- ✅ עסקאות מסחריות בין עסקים (B2B)
- ✅ הזמנות ופלטפורמות שירות
- ✅ NDA ו-MoU רגילים
- ❌ עסקאות מקרקעין (דורש נוטריון)
- ❌ צוואות
- ❌ דיני משפחה
- ❌ ייפוי כוח מתמשך
- ⚠️ דיני עבודה – מומלץ אך לא חובה

יש להזכיר את זה ב-T&C ובאזור ההסכמה.

---

## 17. שלבי פיתוח

### Phase 1 – תשתית (שבוע 1)

- [ ] מודל `Contract` ו-`contract_templates`
- [ ] הרחבות ל-`BusinessProfile` (contracts_settings, owner_signature_url)
- [ ] Status machine + immutability gates
- [ ] 3 endpoints בסיסיים: `POST /contracts`, `GET /contracts/{id}`, `PUT /contracts/{id}`
- [ ] Bootstrap של 3 system templates ב-DB

### Phase 2 – AI ו-יצירה (שבוע 2)

- [ ] `services/ai/contract_writer.py` עם prompt + caching
- [ ] `POST /contracts/from-quote/{quote_id}` – Killer flow
- [ ] `POST /contracts/{id}/ai/generate` ו-`regenerate-section`
- [ ] בדיקות יחידה עם 10 הצעות אמיתיות → חוזים

### Phase 3 – PDF ו-עורך UI (שבוע 3)

- [ ] תבנית `contract_base.html` ב-WeasyPrint
- [ ] `services/pdf/contract_pdf.py` (draft + final)
- [ ] עמוד עריכה `/contracts/{id}/edit` עם split-view
- [ ] Live preview של PDF
- [ ] עריכת סקשנים + AI regenerate buttons

### Phase 4 – חתימה דיגיטלית (שבוע 3.5)

- [ ] עמוד public `/c/{token}`
- [ ] Signature pad integration (signature_pad.js)
- [ ] `POST /c/{token}/sign` עם validation
- [ ] יצירת final PDF + hash + R2 upload
- [ ] Immutability logic
- [ ] Decline flow

### Phase 5 – Audit ו-Notifications (שבוע 4)

- [ ] `services/audit/trail_builder.py`
- [ ] רישום אירועים בכל endpoint רלוונטי
- [ ] הרחבת `notifications` collection + service
- [ ] תבניות מייל (5 events)
- [ ] שליחת עותק חתום ללקוח אוטומטית

### Phase 6 – Billing ו-Reminders (שבוע 4.5)

- [ ] עדכון quota schema לחוזים
- [ ] enforcement של per-contract billing ב-Pro
- [ ] הרחבת `services/reminders.py` עם reminders של חוזים
- [ ] APScheduler job יומי

### Phase 7 – ליטוש ו-T&C (שבוע 5)

- [ ] עדכון מסמכי T&C
- [ ] דיסקליימר ב-PDF
- [ ] Consent text במסך חתימה
- [ ] בדיקות end-to-end עם 5 בטא טסטרים
- [ ] תיקון באגים

**סה"כ:** ~5 שבועות לגרסה ראשונה מוכנה ל-Beta.

---

## 18. סיכונים והפחתה

| סיכון | חומרה | פתרון |
|-------|-------|-------|
| AI יוצר חוזה עם שגיאה משפטית | גבוהה | Self-critique pass + דיסקליימר ברור + ולידציה ידנית של בעל העסק לפני שליחה |
| תקיפה משפטית "המסמך לא תקף" | בינונית | T&C מקיפים + audit trail מפורט + document hash |
| לקוח טוען "לא חתמתי" | בינונית | IP + UA + timestamp + signature image + consent text מצולמים ב-audit |
| בעל העסק טוען "לא שלחתי את זה" | נמוכה | Audit event של `finalized` עם user_id + IP |
| Signature pad לא עובד במובייל | נמוכה | בדיקות בכל המכשירים, fallback לכפתור "אני מאשר במקום ציור" (לא מומלץ) |
| WeasyPrint נופל על תבנית מותאמת | בינונית | Validation של placeholders + sandbox rendering לפני שמירה |
| Document hash mismatch בעת ולידציה | נמוכה | Logging מפורט + alert מיידי |
| חוזה גדול מדי (10MB+) | נמוכה | מגבלת 50 פריטים בנספח, sectioning של PDF |
| עורך מודל R2 עולה | נמוכה | Quota 100MB ל-account ב-Free, 1GB ב-Business |
| בעל העסק רוצה לבטל חוזה חתום | בינונית | UI מבהיר שזה immutable + מציע "צור Addendum" (V1.5) |

---

## 19. Checklist לפני release

### טכני
- [ ] כל endpoint עם immutability gate עובד
- [ ] חתימה במובייל (iOS + Android) נבדקה
- [ ] Audit trail כולל את כל ה-events הנדרשים
- [ ] Document hash מתאים לתוכן (בדיקה: שינוי בית = hash שונה)
- [ ] Final PDF לא ניתן לעריכה (בדיקה: נסה לדרוס – אמור להיכשל)
- [ ] Reminders pipeline שולח בזמן הנכון
- [ ] AI לא ממציא פרטים שלא בקלט (בדיקה עם 20 דוגמאות)
- [ ] Quota enforcement עובד ב-Pro (per-contract billing)
- [ ] R2 storage policy נכון (private, signed URLs)

### Compliance
- [ ] T&C מעודכנים וזמינים בעברית
- [ ] דיסקליימר מופיע ב-PDF
- [ ] Consent text במסך חתימה ברור
- [ ] שמירת נתונים 7 שנים מוגדר במדיניות
- [ ] Privacy Policy מעודכנת לכלול signature data

### UX
- [ ] Killer flow (הצעה → חוזה ב-3 לחיצות) עובד חלק
- [ ] עורך AI נותן תוצאות איכותיות בעברית
- [ ] Signature pad responsive במובייל
- [ ] Email טמפלייטים בעברית RTL נכון
- [ ] מסכי שגיאה ידידותיים

### תפעול
- [ ] Sentry/error tracking על endpoints
- [ ] Alert על failures של PDF generation
- [ ] גיבוי יומי של contracts collection
- [ ] Runbook למה לעשות אם R2 לא זמין
- [ ] תיעוד לתמיכה: איך מעניקים גישה לחוזה אבוד

---

## 20. שאלות פתוחות להחלטה

1. **Self-critique של AI** – להפעיל לכל חוזה (יקר אבל איכות) או רק ב-Business?
2. **Per-contract billing ב-Pro** – 19₪ ראוי? אולי 9-12₪ נדיב יותר?
3. **תזכורות** – אוטומטיות חינם או רק ב-Business?
4. **שמירת PDF סופי ללקוח** – שולחים מייל עם attachment או רק לינק להורדה?
5. **WhatsApp לחתימה** – לשלוח את הלינק גם בוואטסאפ דרך deep link? (עוד בשלב 2)
6. **Custom templates** – להגביל ל-Business בלבד או לאפשר ב-Pro?
7. **Audit report ייצוא** – V1 או V1.5?
8. **חתימה של בעל העסק** – האם להציע גם "חתימה דיגיטלית בכל חוזה" במקום תמונה סטטית? (יותר תקין משפטית)

---

## נספח א – תבנית חוזה בסיס

טקסט בסיס לתבנית "Standard Service Agreement". ה-AI ימלא placeholders ויתאים את הניסוח לתחום העסק.

```
חוזה התקשרות
מספר: {{contract_number}}
תאריך: {{created_at}}

בין:
{{owner.business_name}} ({{owner.business_id}})
מרחוב {{owner.address}}
(להלן: "נותן השירות")

לבין:
{{client.name}} ({{client.business_id_or_personal}})
{{client.business_name | default("")}}
{{client.address | default("")}}
(להלן: "הלקוח")

---

הואיל והלקוח מעוניין לקבל מנותן השירות את השירותים המתוארים להלן;
והואיל ונותן השירות מסכים לספק שירותים אלו בתנאים המפורטים;

לפיכך הוסכם בין הצדדים כדלקמן:

---

1. נשוא ההתקשרות
{{scope_of_work}}

2. תוצרים
{% for item in deliverables %}
   • {{item}}
{% endfor %}

3. לוח זמנים
{{timeline}}

4. תמורה ותנאי תשלום
התמורה הכוללת: {{totals.total_with_vat}} ש"ח (כולל מע"מ).

פירוט פריטים מצורף בנספח א'.

תנאי תשלום: {{payment_terms}}

5. קניין רוחני
{{intellectual_property}}

ברירת מחדל: כל זכויות הקניין הרוחני בעבודה יועברו ללקוח עם
תשלום מלא של התמורה. עד אז – הזכויות שמורות לנותן השירות.

6. סודיות
{{confidentiality}}

הצדדים מתחייבים לשמור על סודיות מוחלטת לגבי כל מידע
עסקי שיגיע לידיעתם במהלך ההתקשרות.

7. אחריות והגבלת אחריות
{{warranty_and_liability}}

נותן השירות אחראי לטיב העבודה לתקופה של 30 יום מסיומה.
אחריות נותן השירות מוגבלת לסכום התמורה ששולם.

8. תנאי סיום
{{termination}}

כל צד רשאי לסיים את ההתקשרות בהודעה מוקדמת של
{{termination_notice_days}} ימים. במקרה של סיום:
- הלקוח ישלם עבור עבודה שכבר בוצעה
- נותן השירות יעביר את כל החומרים שהושלמו

9. שונות
{{general_provisions}}

   9.1 כל שינוי בהסכם זה ייעשה בכתב ובהסכמת שני הצדדים.
   9.2 סמכות השיפוט הייחודית בכל מחלוקת – בית המשפט המוסמך בישראל.
   9.3 הסכם זה ממצה את ההתקשרות בין הצדדים.

---

⚠️ מסמך זה אינו תחליף לייעוץ משפטי.
   בעת ספק יש להתייעץ עם עו"ד מוסמך.

---

נחתם על ידי:

נותן השירות:                    הלקוח:
[חתימה]                         [חתימה]
{{owner.name}}                  {{client.name}}
תאריך: {{created_at}}            תאריך: {{signed_at | default("___")}}

---

נספח א' – פירוט פריטים
{% for item in items %}
{{item.name}} | כמות: {{item.qty}} | מחיר: {{item.unit_price}} ש"ח
{% endfor %}
סה"כ: {{totals.total_with_vat}} ש"ח כולל מע"מ
```

---

## נספח ב – ENV vars נדרשים

```bash
# ContractFlow
CONTRACTS_PER_CONTRACT_PRICE_ILS=19
CONTRACTS_BUSINESS_MONTHLY_LIMIT=20
CONTRACTS_REMINDER_DAYS_NOT_VIEWED=3
CONTRACTS_REMINDER_DAYS_NOT_SIGNED=5
CONTRACTS_DEFAULT_EXPIRY_DAYS=14

# Storage (משתפים עם OfferFlow)
R2_BUCKET_CONTRACTS=offerflow-contracts  # bucket נפרד או prefix
R2_SIGNATURE_RETENTION_YEARS=7

# AI
CONTRACTS_AI_MODEL=claude-sonnet-4-6
CONTRACTS_AI_TEMPERATURE=0.3              # נמוך יותר מ-quotes – פחות יצירתיות
CONTRACTS_USE_SELF_CRITIQUE_FOR_BUSINESS=true

# Audit
AUDIT_RETENTION_YEARS=7
AUDIT_HASH_ALGORITHM=sha256
```

---

## נספח ג – טקסט הסכמה לחתימה

טקסט שמופיע מעל ה-canvas signature במסך חתימה. **חובה להציג מילולית – לא להחליף.**

```
✍️ אישור חתימה דיגיטלית

על ידי חתימתי להלן, אני {{client.name}}:

1. מאשר שקראתי והבנתי את כל תנאי החוזה המפורטים מעלה.
2. מסכים להתקשרות בתנאים אלו ללא הסתייגויות.
3. מאשר שזוהי חתימתי האלקטרונית, השווה בתוקפה לחתימה ידנית
   על פי חוק חתימה אלקטרונית, התשס"א-2001.
4. מודע לכך שפעולת החתימה תירשם עם:
   - תאריך ושעה מדויקים
   - כתובת IP שלי
   - פרטי המכשיר והדפדפן
   - תמונת החתימה הדיגיטלית
5. מבין שהחוזה הופך מחייב מרגע החתימה.

[Canvas signature pad]

[שדה: שם מלא]                    [שדה: ת.ז./ח.פ. (אם נדרש)]

☐ אני מאשר את כל הנ"ל וחותם על החוזה

[כפתור: חתום ואשר]
```

---

**בהצלחה במימוש. ה-spec הזה תקף גם להוספת AES בעתיד – הארכיטקטורה תומכת בכך עם הוספת שלב OTP לפני ה-`POST /sign` בלבד.**
