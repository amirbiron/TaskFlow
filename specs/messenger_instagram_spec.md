# InboxFlow – הוספת ערוצי Messenger ו-Instagram

**גרסה:** 1.0
**תאריך:** 2026-05-15
**הקשר:** הרחבה ל-WhatsAppLeadFlow (InboxFlow) – הוספת שני ערוצי תקשורת חדשים מבוססי Meta Graph API.
**ארכיטקטורה:** SaaS עם Facebook App מרכזי אחד שמשרת את כל לקוחות הקצה.

---

## תוכן עניינים

1. [סקירה ומטרה](#1-סקירה-ומטרה)
2. [תמונה טכנית של Meta Graph API](#2-תמונה-טכנית-של-meta-graph-api)
3. [ארכיטקטורת App מרכזי – השלכות](#3-ארכיטקטורת-app-מרכזי--השלכות)
4. [שינויים במודל הנתונים](#4-שינויים-במודל-הנתונים)
5. [Provider חדש: meta_graph](#5-provider-חדש-meta_graph)
6. [Webhook גלובלי וניתוב](#6-webhook-גלובלי-וניתוב)
7. [זרימת OAuth ל-onboarding לקוח](#7-זרימת-oauth-ל-onboarding-לקוח)
8. [שליחת הודעות וחלון 24 שעות](#8-שליחת-הודעות-וחלון-24-שעות)
9. [התאמות בסיווג ובניסוח טיוטות](#9-התאמות-בסיווג-ובניסוח-טיוטות)
10. [שינויים ב-UI](#10-שינויים-ב-ui)
11. [Tokens – ניהול ורענון](#11-tokens--ניהול-ורענון)
12. [Privacy, Compliance ו-App Review](#12-privacy-compliance-ו-app-review)
13. [שלבי פיתוח](#13-שלבי-פיתוח)
14. [גוצ'ות ופוטנציאל לבאגים](#14-גוצות-ופוטנציאל-לבאגים)
15. [Checklist לפני השקה](#15-checklist-לפני-השקה)
16. [נספח א – דוגמאות JSON של webhooks](#נספח-א--דוגמאות-json-של-webhooks)
17. [נספח ב – ENV vars נדרשים](#נספח-ב--env-vars-נדרשים)

---

## 1. סקירה ומטרה

הוספת תמיכה ב-**Facebook Messenger** ו-**Instagram Direct** ל-InboxFlow, תוך שימוש מקסימלי בתשתית הקיימת מ-WhatsApp:
- אותו classifier
- אותו draft writer
- אותו מנגנון התראות (טלגרם)
- אותו מנגנון follow-up

הערוצים החדשים נכנסים כ-providers נוספים מתחת לאותה אבסטרקציה (`BaseChannelProvider`), כך שהליבה לא צריכה להכיר את ה-API של פייסבוק ישירות.

**יתרון מרכזי:** Messenger ו-Instagram חולקים provider אחד (Meta Graph API). מימוש Messenger נותן את Instagram כמעט בחינם.

---

## 2. תמונה טכנית של Meta Graph API

### 2.1 נקודות מפתח

- **Endpoint שליחה:** `POST https://graph.facebook.com/v21.0/me/messages`
- **Webhook יחיד:** מטא שולחים אירועים מ-Messenger ומ-Instagram לאותו URL שאתה רושם ב-App
- **הבדל זיהוי:** שדה `object` ב-payload (`page` ל-Messenger, `instagram` ל-IG)
- **אימות חתימה:** `X-Hub-Signature-256` עם HMAC-SHA256 על raw body, מפתח = `app_secret`

### 2.2 חלון 24 שעות (Standard Messaging Window)

- אפשר לשלוח חופשי תוך 24 שעות מההודעה האחרונה של הלקוח
- מחוץ לחלון – רק `MESSAGE_TAG` מאושר (לא תבניות כמו ב-WhatsApp)
- Tags מותרים: `CONFIRMED_EVENT_UPDATE`, `POST_PURCHASE_UPDATE`, `ACCOUNT_UPDATE`, `HUMAN_AGENT` (דורש הרשאה מיוחדת)

### 2.3 הרשאות נדרשות (Permissions)

| הרשאה | תפקיד | App Review? |
|--------|--------|-------------|
| `pages_show_list` | רשימת Pages של המשתמש | כן |
| `pages_messaging` | קריאה/שליחה ב-Messenger | כן |
| `pages_manage_metadata` | רישום webhook subscriptions | כן |
| `instagram_basic` | מידע בסיסי על IG account | כן |
| `instagram_manage_messages` | DM באינסטגרם | כן |
| `business_management` | (אופציונלי) Insights | כן |

### 2.4 דרישות קדם ללקוח קצה

- **עמוד פייסבוק עסקי** (לא פרופיל אישי)
- **עבור Instagram:** חשבון Professional (Business / Creator) **מחובר** לעמוד הפייסבוק
- **המשתמש שמתחבר חייב להיות אדמין/Editor של העמוד**

---

## 3. ארכיטקטורת App מרכזי – השלכות

ב-SaaS שלך יש **Facebook App אחד** שמשרת את כל לקוחות הקצה. זו הבחירה הנכונה (חיכוך נמוך לכל לקוח), אבל יש כמה השלכות חשובות:

### 3.1 `app_secret` הוא גלובלי

- שייך לאותו App, לא ללקוח
- יושב ב-`ENV` (לא ב-DB)
- משמש לאימות **כל** ה-webhooks

### 3.2 Webhook URL אחד

```
POST https://api.inboxflow.com/webhooks/meta
```

נרשם פעם אחת ב-App Dashboard של Meta. אין `tenant_id` ב-URL.

### 3.3 זיהוי Tenant מתוך payload

לכל אירוע יש `entry[].id` שהוא `page_id` (או IG account id). מחפשים בטבלת אינדקס מהירה:

```python
{ "page_id": "12345...", "tenant_id": ObjectId, "channel_type": "messenger" }
{ "ig_account_id": "17841...", "tenant_id": ObjectId, "channel_type": "instagram" }
```

### 3.4 App Review פעם אחת

ה-App עובר Review **פעם אחת** ואז כל לקוח חדש מקבל את ההרשאות אוטומטית. תידרש:
- סרטון הדגמה מלא של ה-flow
- תיאור use-case מפורט
- מדיניות פרטיות + Terms + Data Deletion endpoint פעילים

---

## 4. שינויים במודל הנתונים

### 4.1 `tenants` – הוספת ערוצים חדשים

```python
{
  "_id": ObjectId,
  "business_name": "צילום אירועים אבי",
  "telegram_chat_id": "12345",
  "business_context": "צלם אירועים, מתמחה בחתונות...",
  "channels": [
    {
      "type": "whatsapp",
      "provider": "green_api",
      "credentials": { "instance_id": "...", "token": "<encrypted>" },
      "active": True
    },
    {
      "type": "messenger",
      "provider": "meta_graph",
      "credentials": {
        "page_id": "12345...",
        "page_name": "Avi Photography",
        "page_access_token": "<encrypted>"
      },
      "active": True,
      "connected_at": datetime,
      "connected_by_user_id": "fb_user_id"
    },
    {
      "type": "instagram",
      "provider": "meta_graph",
      "credentials": {
        "ig_business_account_id": "17841...",
        "ig_username": "avi_photography",
        "page_id": "12345...",
        "page_access_token": "<encrypted>"
      },
      "active": True
    }
  ]
}
```

> שים לב: `app_secret` **לא** נמצא כאן – הוא ב-ENV הגלובלי.

### 4.2 `meta_page_index` (collection חדש – לזיהוי מהיר)

```python
{
  "_id": ObjectId,
  "platform_account_id": "12345...",  # page_id או ig_account_id
  "tenant_id": ObjectId,
  "channel_type": "messenger",  # או "instagram"
  "active": True
}
```

**אינדקס:** `{ platform_account_id: 1 }` unique.

### 4.3 `conversations` – הוספת שדות channel

```python
{
  "_id": ObjectId,
  "tenant_id": ObjectId,
  "channel_type": "messenger",  # חדש
  "channel_contact_id": "PSID_or_phone",  # חדש (החליף את contact_phone)
  "contact_name": "יוסי כהן",
  "contact_avatar_url": "https://...",  # חדש
  "status": "lead_hot",
  "last_message_at": datetime,
  "last_incoming_at": datetime,  # חשוב לחישוב חלון 24h
  "needs_human_reply": True,
  "tags": ["wedding", "august"]
}
```

**אינדקס ייחודי חדש:** `{ tenant_id: 1, channel_type: 1, channel_contact_id: 1 }`.

### 4.4 `messages` – הוספת שדות platform

```python
{
  "_id": ObjectId,
  "conversation_id": ObjectId,
  "direction": "incoming",
  "body": "יש לכם זמין?",
  "media": [{"type": "image", "url": "...", "mime_type": "image/jpeg"}],
  "platform_message_id": "mid.123abc",  # חדש - ל-deduplication
  "reply_to_message_id": "mid.456def",  # חדש - לתגובות
  "reactions": [],  # חדש
  "ai_classification": {...},
  "draft_reply": "...",
  "sent": False,
  "sent_with_tag": None,  # אם נשלח עם MESSAGE_TAG
  "timestamp": datetime
}
```

**אינדקס ייחודי:** `{ platform_message_id: 1 }` sparse unique – למניעת כפילויות מ-webhooks חוזרים.

---

## 5. Provider חדש: meta_graph

### 5.1 מבנה הקלאס

```python
# app/services/whatsapp/providers/meta_graph.py

from .base import BaseChannelProvider, ParsedMessage, ContactProfile

class MetaGraphProvider(BaseChannelProvider):
    GRAPH_VERSION = "v21.0"
    BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

    def __init__(self, credentials: dict, platform: str, app_secret: str):
        # platform: "messenger" | "instagram"
        self.platform = platform
        self.page_token = decrypt(credentials["page_access_token"])
        self.page_id = credentials["page_id"]
        self.app_secret = app_secret  # מ-ENV הגלובלי

    async def send_message(
        self,
        recipient_id: str,
        body: str,
        message_tag: str | None = None,
        reply_to: str | None = None,
    ) -> str:
        """שולח הודעה. message_tag נדרש מחוץ לחלון 24h."""
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": body},
            "messaging_type": "MESSAGE_TAG" if message_tag else "RESPONSE",
        }
        if message_tag:
            payload["tag"] = message_tag
        if reply_to:
            payload["message"]["reply_to"] = {"mid": reply_to}

        url = f"{self.BASE_URL}/me/messages?access_token={self.page_token}"
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, timeout=15.0)
            r.raise_for_status()
            return r.json()["message_id"]

    @staticmethod
    def verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
        """אימות X-Hub-Signature-256 בזמן קבוע."""
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = hmac.new(
            app_secret.encode(),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        provided = signature_header.removeprefix("sha256=")
        return hmac.compare_digest(expected, provided)

    @classmethod
    def parse_incoming(cls, payload: dict) -> list[ParsedMessage]:
        """מפרק webhook גולמי לרשימת הודעות סטנדרטיות.
        מטפל ב: messages, postbacks, reactions, read receipts.
        """
        platform = "instagram" if payload.get("object") == "instagram" else "messenger"
        results = []

        for entry in payload.get("entry", []):
            page_id = entry["id"]
            for event in entry.get("messaging", []):
                if "message" in event:
                    results.append(cls._parse_message_event(event, platform, page_id))
                elif "postback" in event:
                    results.append(cls._parse_postback_event(event, platform, page_id))
                elif "reaction" in event:
                    results.append(cls._parse_reaction_event(event, platform, page_id))
                # read / delivery נתעלם בשלב הזה

        return [r for r in results if r is not None]

    async def fetch_contact_profile(self, contact_id: str) -> ContactProfile:
        """משיג שם + תמונת פרופיל. נדרש בפעם הראשונה שמתקבלת הודעה."""
        # ב-Messenger:
        # GET /{PSID}?fields=name,profile_pic
        # ב-Instagram:
        # GET /{IGSID}?fields=name,profile_pic,username
        fields = "name,profile_pic" if self.platform == "messenger" else "name,profile_pic,username"
        url = f"{self.BASE_URL}/{contact_id}?fields={fields}&access_token={self.page_token}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=10.0)
            r.raise_for_status()
            return ContactProfile(**r.json())
```

### 5.2 ממשק `BaseChannelProvider` (אם עוד אין)

```python
class BaseChannelProvider(ABC):
    @abstractmethod
    async def send_message(self, recipient_id: str, body: str, **kwargs) -> str: ...

    @abstractmethod
    async def fetch_contact_profile(self, contact_id: str) -> ContactProfile: ...

    @staticmethod
    @abstractmethod
    def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool: ...

    @classmethod
    @abstractmethod
    def parse_incoming(cls, payload: dict) -> list[ParsedMessage]: ...
```

---

## 6. Webhook גלובלי וניתוב

### 6.1 שני endpoints

```python
# אימות חד-פעמי של פייסבוק (verify token challenge)
@router.get("/webhooks/meta")
async def meta_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403)


# קבלת אירועים (Messenger + Instagram יחד)
@router.post("/webhooks/meta")
async def meta_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # 1. אימות חתימה - חובה!
    if not MetaGraphProvider.verify_signature(raw_body, signature, settings.META_APP_SECRET):
        raise HTTPException(403, "Invalid signature")

    payload = json.loads(raw_body)
    platform = "instagram" if payload.get("object") == "instagram" else "messenger"

    # 2. עיבוד ברקע - חובה להחזיר 200 תוך 20s!
    background_tasks.add_task(_process_meta_payload, payload, platform)

    return {"ok": True}


async def _process_meta_payload(payload: dict, platform: str):
    """מנתב כל אירוע ל-tenant הנכון."""
    for entry in payload.get("entry", []):
        platform_account_id = entry["id"]

        # 3. מציאת tenant לפי page_id / ig_account_id
        index_doc = await db.meta_page_index.find_one({
            "platform_account_id": platform_account_id,
            "active": True,
        })
        if not index_doc:
            logger.warning(f"Received event for unknown account: {platform_account_id}")
            continue

        tenant = await db.tenants.find_one({"_id": index_doc["tenant_id"]})
        channel = next(
            (c for c in tenant["channels"]
             if c["type"] == index_doc["channel_type"] and c["active"]),
            None
        )
        if not channel:
            continue

        provider = MetaGraphProvider(channel["credentials"], platform, settings.META_APP_SECRET)
        parsed = provider.parse_incoming({"object": payload["object"], "entry": [entry]})

        for msg in parsed:
            await process_incoming_message(tenant["_id"], platform, msg, provider)
```

### 6.2 דרישות חובה

- **תשובת 200 תוך 20 שניות** – אחרת מטא ינסו שוב ויגרמו לכפילויות
- **כל העיבוד הכבד ברקע** (BackgroundTasks או queue)
- **Deduplication לפי `platform_message_id`** – לפני כל insert
- **Logging של webhooks שהגיעו ל-page לא מוכר** – יעזור לדבג onboarding שבור

---

## 7. זרימת OAuth ל-onboarding לקוח

זה החלק המורכב ביותר. כל לקוח חדש עובר:

### 7.1 השלבים

```
1. בעל העסק לוחץ "חבר את עמוד הפייסבוק/אינסטגרם" בהגדרות
   → POST /settings/meta/connect → מחזיר redirect URL

2. מועבר ל-Facebook Login dialog:
   https://www.facebook.com/v21.0/dialog/oauth?
     client_id={APP_ID}
     &redirect_uri={CALLBACK_URL}
     &state={CSRF_TOKEN}
     &scope=pages_show_list,pages_messaging,pages_manage_metadata,
            instagram_basic,instagram_manage_messages

3. אחרי אישור, חוזר ל-{CALLBACK_URL}?code={SHORT_LIVED_CODE}&state=...
   → GET /settings/meta/callback

4. השרת מחליף code ל-short-lived user token:
   GET /v21.0/oauth/access_token?
     client_id=...&client_secret=...&redirect_uri=...&code=...

5. השרת מחליף ל-long-lived user token (60 ימים):
   GET /v21.0/oauth/access_token?
     grant_type=fb_exchange_token&client_id=...&client_secret=...
     &fb_exchange_token={SHORT_LIVED}

6. השרת מבקש את רשימת ה-Pages:
   GET /me/accounts?access_token={LONG_LIVED_USER_TOKEN}
   → מחזיר רשימה: [{ id, name, access_token, instagram_business_account: {id} }]

7. הצגת רשימת Pages למשתמש → הוא בוחר אחד
   → POST /settings/meta/select_page  { page_id: "..." }

8. השרת:
   - שומר page_access_token (זה ה-token הקבוע!) מוצפן
   - יוצר רשומה ב-meta_page_index
   - אם יש instagram_business_account → גם רושם אותו
   - מבצע subscribe ל-webhooks של ה-Page:
     POST /{page_id}/subscribed_apps?
       subscribed_fields=messages,messaging_postbacks,messaging_reactions
       &access_token={PAGE_TOKEN}
   - עבור IG: גם
     POST /{page_id}/subscribed_apps עם השדות של IG
```

### 7.2 Endpoints חדשים

| Method | Path | תיאור |
|--------|------|-------|
| `POST` | `/settings/meta/connect` | מתחיל OAuth, מחזיר redirect URL + state |
| `GET` | `/settings/meta/callback` | מקבל code, מחליף לטוקנים, שומר משתמש |
| `GET` | `/settings/meta/pages` | רשימת ה-Pages הזמינות (אחרי קולבק) |
| `POST` | `/settings/meta/select_page` | בחירת עמוד + רישום webhook |
| `DELETE` | `/settings/meta/disconnect` | ניתוק (גם מ-Meta וגם מ-DB) |

### 7.3 Disconnect – מה לעשות?

```python
async def disconnect_meta(tenant_id, channel_type):
    # 1. ביטול הרשמה ל-webhooks ב-Meta
    DELETE /{page_id}/subscribed_apps?access_token={page_token}

    # 2. (אופציונלי) ביטול הטוקן עצמו
    DELETE /{page_id}/permissions?access_token={page_token}

    # 3. סימון ה-channel כ-inactive ב-tenant
    # 4. סימון ה-meta_page_index כ-inactive (לא למחוק - להיסטוריה)
    # 5. השארת השיחות וההיסטוריה ב-DB
```

---

## 8. שליחת הודעות וחלון 24 שעות

### 8.1 לוגיקת השליחה

```python
async def send_outgoing_message(conversation_id: ObjectId, body: str,
                                 message_tag: str | None = None) -> str:
    conv = await get_conversation(conversation_id)
    tenant = await get_tenant(conv["tenant_id"])
    channel = get_channel(tenant, conv["channel_type"])

    # בדיקת חלון 24h ב-Meta
    if conv["channel_type"] in ("messenger", "instagram"):
        last_incoming = conv.get("last_incoming_at")
        if last_incoming:
            hours_since = (datetime.utcnow() - last_incoming).total_seconds() / 3600
            if hours_since > 24 and not message_tag:
                raise OutsideMessagingWindow(
                    f"Last incoming was {hours_since:.1f}h ago. "
                    "MESSAGE_TAG required."
                )

    provider = build_provider(channel)
    platform_msg_id = await provider.send_message(
        recipient_id=conv["channel_contact_id"],
        body=body,
        message_tag=message_tag,
    )

    # שמירה ב-DB
    await db.messages.insert_one({
        "conversation_id": conversation_id,
        "direction": "outgoing",
        "body": body,
        "platform_message_id": platform_msg_id,
        "sent": True,
        "sent_with_tag": message_tag,
        "timestamp": datetime.utcnow(),
    })

    return platform_msg_id
```

### 8.2 התנהגות ב-UI

- **בתוך החלון:** כפתור "שלח" רגיל
- **מחוץ לחלון:**
  - באנר צהוב: "החלון של 24 שעות הסתיים. ניתן לשלוח רק עם MESSAGE_TAG."
  - הכפתור "שלח" משבת
  - ליד הכפתור: dropdown "בחר Tag" + הסבר על כל tag
  - אם בעל העסק בוחר tag → הכפתור מתאפשר

### 8.3 MESSAGE_TAG – מתי כל אחד

| Tag | מתי להשתמש |
|-----|------------|
| `CONFIRMED_EVENT_UPDATE` | תזכורת לפגישה/אירוע מאושר |
| `POST_PURCHASE_UPDATE` | עדכון על הזמנה (משלוח, סטטוס) |
| `ACCOUNT_UPDATE` | שינוי בחשבון/בהזמנה של המשתמש |
| `HUMAN_AGENT` | (24/7) מצריך הרשאת `human_agent` נפרדת |

> **חשוב:** שימוש לא נכון ב-tag = איסור מצד מטא. לא להציע "סתם" ללקוח.

---

## 9. התאמות בסיווג ובניסוח טיוטות

### 9.1 העברת `channel_type` ל-classifier

עדכון חתימה:

```python
async def classify_message(
    business_context: str,
    history: list[dict],
    new_message: str,
    channel_type: str,  # חדש
) -> ClassificationResult: ...
```

ב-prompt להוסיף הקשר:

> "ההודעה הגיעה דרך {channel_type}. הקח בחשבון: {channel_hint}"

`channel_hint` לפי הערוץ:
- `whatsapp`: "טון של שיחה אישית, לרוב ישיר וקצר"
- `messenger`: "דומה לוואטסאפ, אבל יותר נוטה לשאלות 'מתעניין' מאשר 'מוכן לקנות'"
- `instagram`: "לרוב מגיע מסקרנות אחרי תוכן/סטורי, איכות ליד נמוכה יותר ממוצעת"

### 9.2 התאמת draft_writer

| ערוץ | אורך מומלץ | סגנון | אמוג'ים |
|------|------------|-------|---------|
| WhatsApp | 2-4 שורות | חברי-מקצועי | מינימליים |
| Messenger | 2-4 שורות | חברי | מתון |
| Instagram | 1-3 שורות | קליל ויזואלי | מותרים |

הוסף `channel_type` לפרמטרים, והכל בפרומפט.

---

## 10. שינויים ב-UI

### 10.1 עמוד Inbox

- **Filter chips** למעלה: כל הערוצים | WhatsApp | Messenger | Instagram (עם counter)
- **בכל שורה ברשימה:** אייקון קטן של הערוץ (ירוק WA, כחול FB, גרדיאנט IG)
- **חיווי "מחוץ לחלון"** – נקודה אדומה קטנה ליד שיחות Meta שעברו 24h

### 10.2 עמוד שיחה

- **כותרת:** שם + תמונת פרופיל + שם הערוץ
- **באנר 24h** – בולט אם רלוונטי
- **תיבת תשובה:** dropdown של MESSAGE_TAG מופיע רק אם מחוץ לחלון
- **תמיכה בתמונות** (Meta שולחים תמונות הרבה – חובה להציג)

### 10.3 עמוד Settings

- כרטיס "Meta (Facebook + Instagram)":
  - אם לא מחובר: כפתור "Connect Facebook Page"
  - אם מחובר: שם העמוד + תמונה + Toggle נפרד ל-Messenger ול-Instagram + כפתור "Disconnect"
- הסבר קצר על דרישות (עמוד עסקי, IG Business מחובר)

---

## 11. Tokens – ניהול ורענון

### 11.1 סוגי טוקנים

| טוקן | תוקף | שימוש |
|------|-------|-------|
| Short-lived user token | שעה | רק להחלפה ל-long-lived |
| Long-lived user token | 60 ימים | רק להשגת page tokens |
| **Page access token** | **קבוע** (אם הוצא נכון) | **השליחה והקריאה השוטפות** |

> רק אם הוצאת page token דרך long-lived user token, הוא לא פג. אחרת הוא יפוג עם ה-user token.

### 11.2 בדיקה תקופתית

Background job שרץ פעם ביום:

```python
async def check_meta_tokens_health():
    """בודק שכל ה-page tokens עדיין תקפים."""
    async for tenant in db.tenants.find({"channels.type": {"$in": ["messenger", "instagram"]}}):
        for channel in tenant["channels"]:
            if channel["provider"] != "meta_graph" or not channel["active"]:
                continue
            try:
                token = decrypt(channel["credentials"]["page_access_token"])
                async with httpx.AsyncClient() as c:
                    r = await c.get(
                        f"https://graph.facebook.com/v21.0/me?access_token={token}",
                        timeout=10.0,
                    )
                if r.status_code != 200:
                    raise TokenInvalid(r.text)
            except TokenInvalid:
                await mark_channel_disconnected(tenant["_id"], channel["type"])
                await notify_tenant_telegram(
                    tenant["telegram_chat_id"],
                    f"⚠️ החיבור ל-{channel['type']} נותק. נא להתחבר מחדש."
                )
```

### 11.3 הצפנה

כל הטוקנים מוצפנים ב-Fernet (אותה תשתית כמו WhatsApp). מפתח ה-Fernet ב-ENV.

---

## 12. Privacy, Compliance ו-App Review

### 12.1 דרישות חובה לפני App Review

- [ ] **Privacy Policy URL** ציבורי, מתאר במפורש איסוף הודעות
- [ ] **Terms of Service URL**
- [ ] **Data Deletion Callback URL** – endpoint שמטפל בבקשות מחיקה:
  ```python
  @router.post("/webhooks/meta/data-deletion")
  async def handle_data_deletion(request: Request):
      # 1. אמת signed_request
      # 2. החזר { url, confirmation_code }
      # 3. תזמן מחיקת כל ההודעות של ה-user_id
  ```
- [ ] **Use Case מסביר** – "אני בונה כלי שמסייע לעסקים קטנים לנהל לידים מ-Messenger/Instagram, מסווג הודעות לפי דחיפות ושולח התראות לבעל העסק."
- [ ] **סרטון Demo** – 2-3 דקות, שלב-אחר-שלב של ה-flow
- [ ] **משתמשי בדיקה (Test Users)** – הוסף לפחות 2

### 12.2 Use Case לכל הרשאה

צריך להסביר במלל **למה** אתה צריך כל הרשאה. דוגמה:

> `pages_messaging`: We use this to receive incoming Messenger messages on behalf of the business owner who installed our app, classify them as leads or not, and allow the owner to reply through our dashboard.

### 12.3 GDPR / חוק הגנת הפרטיות הישראלי

- בעל העסק אחראי להסכמת לקוחותיו (תזכיר לו לעדכן את מדיניות הפרטיות שלו)
- אתה כ-DPO צריך לאפשר ייצוא ומחיקת נתונים לכל לקוח קצה לפי בקשה
- שמור log של כל פעולת מחיקה

---

## 13. שלבי פיתוח

### שלב 0 – תהליך מטא (במקביל לפיתוח, מתחילים מיד)

- [ ] יצירת Facebook App (Type: Business)
- [ ] הגשת Business Verification – **1-2 שבועות**
- [ ] כתיבת Privacy Policy + ToS + Data Deletion endpoint
- [ ] הקלטת סרטון Demo
- [ ] הגשה ל-App Review – **שבוע נוסף**

### שלב 1 – Provider בסיסי (3-4 ימים)

- [ ] `services/whatsapp/providers/meta_graph.py` עם `parse_incoming` + `send_message` + `verify_signature` + `fetch_contact_profile`
- [ ] בדיקות יחידה לפרסור webhooks (לפחות 5 סוגי אירועים)
- [ ] יצירת `meta_page_index` collection + מודל

### שלב 2 – Webhook גלובלי (2 ימים)

- [ ] `GET /webhooks/meta` (verify token)
- [ ] `POST /webhooks/meta` עם signature verification + ניתוב ברקע
- [ ] בדיקה ב-localhost עם ngrok + Webhook Tester של מטא

### שלב 3 – שליחה וחלון 24h (2 ימים)

- [ ] `send_outgoing_message` כולל בדיקת חלון
- [ ] תמיכה ב-MESSAGE_TAG
- [ ] תמיכה ב-`reply_to`
- [ ] טיפול בשגיאות מטא (rate limit, expired token)

### שלב 4 – OAuth onboarding (4 ימים)

- [ ] 5 ה-endpoints של ההגדרות
- [ ] CSRF state + שמירת user במהלך OAuth
- [ ] דף בחירת Page יפה ב-UI
- [ ] רישום אוטומטי ל-webhook subscriptions
- [ ] טיפול בכפילות (לקוח מתחבר שוב לאותו page)

### שלב 5 – התאמות classifier/draft (1-2 ימים)

- [ ] העברת `channel_type` בכל ה-pipeline
- [ ] עדכון פרומפטים
- [ ] בדיקת רגרסיה על דוגמאות WhatsApp הקיימות

### שלב 6 – Inbox UI multi-channel (3 ימים)

- [ ] Filter chips
- [ ] אייקונים בכל שורה
- [ ] באנר 24h
- [ ] תמיכה בהצגת תמונות/מדיה

### שלב 7 – Instagram-specific (2 ימים)

- [ ] טיפול ב-Story Mentions
- [ ] טיפול ב-Story Replies (פורמט שונה)
- [ ] טיפול ב-`is_echo` (הודעות שאתה שלחת חוזרות בwebhook)

### שלב 8 – Token health + monitoring (1 יום)

- [ ] Background job בדיקת tokens
- [ ] התראות ניתוק לטלגרם
- [ ] דשבורד אדמין למצב חיבורים

**סה"כ:** ~3 שבועות פיתוח טהור + 2-3 שבועות תהליך מטא במקביל.

---

## 14. גוצ'ות ופוטנציאל לבאגים

### 14.1 כפילויות webhooks
מטא שולחים אותו אירוע 2-3 פעמים אם תשובת השרת מאחרת. **חובה** dedup לפי `platform_message_id`.

### 14.2 Echo messages
כשאתה שולח הודעה דרך ה-API, מטא שולחים אותה בחזרה ב-webhook עם `is_echo: true`. אם לא תסנן את זה – תישמר הודעה כפולה. סינון:
```python
if event.get("message", {}).get("is_echo"):
    return None
```

### 14.3 Story Mentions באינסטגרם
פורמט שונה לגמרי – `attachments[].type == "story_mention"`. אם לא תטפל – תאבד לידים שמתייגים את הלקוח שלך בסטורי.

### 14.4 Instagram Professional חובה
לקוחות עם חשבון IG אישי לא יוכלו להתחבר. צריך לזהות את זה ב-onboarding ולתת הוראות איך להמיר לחשבון מקצועי.

### 14.5 Page חייב להיות מ-Page Inbox מצב Production
אם המשתמש משתמש ב-"Page Inbox" של Meta – הודעות מסומנות כ-"handled" ולא תמיד יגיעו ל-API. צריך להמליץ לכבות את זה.

### 14.6 Rate limits
- **Per token:** 200 קריאות/שעה (App Mode = Live)
- **Per user-app pair:** מוגבל
- כשתגיע ל-50+ לקוחות – לעבור ל-batch ב-`/me/messages` או להשתמש ב-Background queue

### 14.7 24h window לא מתאפס בזכות הודעה אוטומטית שלך
החלון מתאפס רק כשהלקוח שולח הודעה. תזכורת/follow-up שאתה שולח – לא מאפסת.

### 14.8 Webhook signing על raw body
חייב לחשב חתימה על ה-bytes המקוריים, **לא** על JSON שעבר parse ושוב serialize. ב-FastAPI: `await request.body()` ולשמור.

### 14.9 Data Deletion – חובה
אם פייסבוק מקבל בקשה למחיקה ולא תגיב תוך 30 יום – ה-App יושעה.

### 14.10 IG DM פתוח רק למי שעוקב אחריך
משתמשים שלא עוקבים יכולים לשלוח DM רק ב"בקשת הודעה" – חלק מהאירועים מגיעים בערוץ נפרד עם מבנה שונה.

---

## 15. Checklist לפני השקה

### טכני

- [ ] Webhook מקבל אירועים מ-Messenger ומ-Instagram ושומר ב-DB
- [ ] Signature verification עובד (בדיקה: שלח request מזויף, ודא 403)
- [ ] Deduplication עובד (שלח אותו payload פעמיים, ודא הודעה אחת ב-DB)
- [ ] OAuth flow עובד מקצה לקצה עם משתמש בדיקה
- [ ] שליחה בתוך חלון 24h עובדת
- [ ] שליחה מחוץ לחלון עם MESSAGE_TAG עובדת ובלי – נכשלת בצורה ברורה
- [ ] Token health job רץ ב-scheduler
- [ ] Privacy Policy URL פעיל ב-production
- [ ] Data Deletion endpoint פעיל ובדוק
- [ ] Logging מקיף לכל webhook נכנס

### Compliance

- [ ] Business Verification אושר
- [ ] App Review אושר עם כל ההרשאות הנדרשות
- [ ] App במצב Live (לא Development)
- [ ] Privacy Policy מעודכן ומאושר על ידי עו"ד (אם יש)

### UX

- [ ] Onboarding ברור עם תמונות/הסברים
- [ ] שגיאות OAuth מציגות הודעה ידידותית
- [ ] באנר 24h מובן וברור
- [ ] Disconnect עובד נקי בלי להשאיר זבל

### תפעול

- [ ] Sentry/error tracking על כל endpoints
- [ ] Alert על page disconnections מצטברות
- [ ] Backup לטבלת `meta_page_index` (קריטית ל-recovery)
- [ ] Runbook למה לעשות אם token נחסם

---

## נספח א – דוגמאות JSON של webhooks

### א.1 Messenger – הודעת טקסט נכנסת

```json
{
  "object": "page",
  "entry": [{
    "id": "PAGE_ID",
    "time": 1734000000000,
    "messaging": [{
      "sender": { "id": "PSID_OF_USER" },
      "recipient": { "id": "PAGE_ID" },
      "timestamp": 1734000000000,
      "message": {
        "mid": "mid.HKL_abc123",
        "text": "יש לכם זמין ל-15.8?"
      }
    }]
  }]
}
```

### א.2 Messenger – הודעה עם תמונה

```json
{
  "object": "page",
  "entry": [{
    "id": "PAGE_ID",
    "messaging": [{
      "sender": { "id": "PSID" },
      "recipient": { "id": "PAGE_ID" },
      "timestamp": 1734000000000,
      "message": {
        "mid": "mid.xyz",
        "attachments": [{
          "type": "image",
          "payload": { "url": "https://scontent.xx.fbcdn.net/..." }
        }]
      }
    }]
  }]
}
```

### א.3 Instagram – הודעה נכנסת

```json
{
  "object": "instagram",
  "entry": [{
    "id": "IG_BUSINESS_ACCOUNT_ID",
    "time": 1734000000000,
    "messaging": [{
      "sender": { "id": "IGSID_OF_USER" },
      "recipient": { "id": "IG_BUSINESS_ACCOUNT_ID" },
      "timestamp": 1734000000000,
      "message": {
        "mid": "aWdfZAG...",
        "text": "ראיתי את הסטורי שלכם!"
      }
    }]
  }]
}
```

### א.4 Instagram – Story Mention

```json
{
  "object": "instagram",
  "entry": [{
    "id": "IG_BUSINESS_ACCOUNT_ID",
    "messaging": [{
      "sender": { "id": "IGSID" },
      "recipient": { "id": "IG_BUSINESS_ACCOUNT_ID" },
      "message": {
        "mid": "...",
        "attachments": [{
          "type": "story_mention",
          "payload": { "url": "https://lookaside.fbsbx.com/..." }
        }]
      }
    }]
  }]
}
```

### א.5 Echo (הודעה שאתה שלחת)

```json
{
  "object": "page",
  "entry": [{
    "id": "PAGE_ID",
    "messaging": [{
      "sender": { "id": "PAGE_ID" },
      "recipient": { "id": "PSID" },
      "message": {
        "mid": "...",
        "text": "תודה על פנייתך",
        "is_echo": true,
        "app_id": "YOUR_APP_ID"
      }
    }]
  }]
}
```

⚠️ חובה לסנן `is_echo: true`.

### א.6 Reaction

```json
{
  "object": "page",
  "entry": [{
    "id": "PAGE_ID",
    "messaging": [{
      "sender": { "id": "PSID" },
      "recipient": { "id": "PAGE_ID" },
      "reaction": {
        "mid": "mid.HKL_abc123",
        "action": "react",
        "reaction": "love",
        "emoji": "❤️"
      }
    }]
  }]
}
```

---

## נספח ב – ENV vars נדרשים

```bash
# Meta Graph API - גלובלי לכל הלקוחות
META_APP_ID=123456789012345
META_APP_SECRET=abc123...                    # סודי - רק ב-ENV!
META_VERIFY_TOKEN=random-string-you-define   # לאימות webhook setup
META_GRAPH_VERSION=v21.0
META_REDIRECT_URI=https://api.inboxflow.com/settings/meta/callback

# הצפנת page tokens
FERNET_KEY=...                               # 32 bytes base64
```

---

## שאלות פתוחות שטוב להחליט עליהן לפני שמתחילים

1. **Story Mentions** – מטפלים בהם כליד נפרד או כסוג הודעה רגילה?
2. **DM Requests** (לא-עוקבים באינסטגרם) – אוטומטית מאשרים את הבקשה (ע"י קריאה ל-API)? או רק מתריעים לבעל העסק?
3. **Reactions** – שומרים בצד ההודעה בלבד או גם משנים סטטוס שיחה (למשל: "סומן כנקרא")?
4. **תמיכה במשרדי Office hours** – האם המערכת תשלח אוטומטית הודעת "נחזור אליך מחר" אם הלקוח כותב מחוץ לשעות עבודה?
5. **Multi-page onboarding** – האם לאפשר ללקוח לחבר מספר Pages באותו tenant? (למשל, רשת חנויות עם דף לכל סניף)

---

**בהצלחה! כשתסיים לממש – ה-spec תקף גם לתמיכה עתידית ב-WhatsApp Cloud API הרשמי, כי הארכיטקטורה אותה דבר.**
