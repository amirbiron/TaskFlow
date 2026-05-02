/**
 * רכיב לבחירת תגיות עם autocomplete ויצירה מהירה.
 * משתמש בו ב-merge עם x-data של רכיב אחר.
 *
 * שימוש בתבנית:
 *   <div x-data="{ ...kanbanComponent({...}), ...tagPicker() }">
 *
 * דורש:
 *   formData.tags: array של tag IDs (יוזן מבחוץ)
 *   allTags: array של { _id, name, color } (יוזן מבחוץ - נטען ב-loadAllTags)
 */
function tagPicker() {
    return {
        // נתונים
        allTags: [],
        tagSearchQuery: '',
        tagPickerOpen: false,
        creatingTag: false,

        async loadAllTags() {
            try {
                const res = await fetch('/api/tags');
                if (res.ok) {
                    this.allTags = await res.json();
                }
            } catch (e) { console.error(e); }
        },

        // תגיות שכבר נבחרו (מתוך formData.tags)
        get selectedTagDetails() {
            if (!this.formData.tags || !this.allTags.length) return [];
            return this.formData.tags
                .map(tagId => this.allTags.find(t => t._id === tagId))
                .filter(Boolean);
        },

        // תגיות זמינות לבחירה (פילטר חיפוש + לא נבחרות)
        get availableTags() {
            const selectedIds = new Set(this.formData.tags || []);
            const query = (this.tagSearchQuery || '').trim().toLowerCase();

            return this.allTags.filter(t => {
                if (selectedIds.has(t._id)) return false;
                if (!query) return true;
                return t.name.toLowerCase().includes(query);
            });
        },

        // האם להציג כפתור "צור תגית חדשה"
        get canCreateNewTag() {
            const query = (this.tagSearchQuery || '').trim();
            if (!query) return false;
            // לא ליצור אם כבר קיימת בדיוק עם השם הזה
            return !this.allTags.some(t => t.name.toLowerCase() === query.toLowerCase());
        },

        addTag(tagId) {
            if (!this.formData.tags) this.formData.tags = [];
            if (!this.formData.tags.includes(tagId)) {
                this.formData.tags.push(tagId);
            }
            this.tagSearchQuery = '';
            // השאר את ה-picker פתוח לבחירות נוספות
        },

        removeTag(tagId) {
            if (!this.formData.tags) return;
            this.formData.tags = this.formData.tags.filter(id => id !== tagId);
        },

        async createAndAddTag() {
            const name = (this.tagSearchQuery || '').trim();
            if (!name || this.creatingTag) return;

            this.creatingTag = true;
            try {
                const res = await fetch('/api/tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        color: '#3B82F6',  // צבע ברירת מחדל - אפשר לשנות בעמוד התגיות
                    }),
                });

                if (res.ok) {
                    const newTag = await res.json();
                    this.allTags.push(newTag);
                    this.addTag(newTag._id);
                } else {
                    const err = await res.json().catch(() => ({}));
                    alert(err.detail || 'שגיאה ביצירת תגית');
                }
            } catch (e) {
                alert('שגיאת רשת');
            } finally {
                this.creatingTag = false;
            }
        },

        toggleTagPicker() {
            this.tagPickerOpen = !this.tagPickerOpen;
            if (this.tagPickerOpen) {
                this.tagSearchQuery = '';
            }
        },
    };
}

/**
 * פונקציות עזר להצגת תגיות בכרטיסים
 */
function tagDisplay() {
    return {
        // עד 3 תגיות + "+N"
        visibleTags(tagDetails, max = 3) {
            if (!tagDetails || !tagDetails.length) return [];
            return tagDetails.slice(0, max);
        },

        hiddenTagsCount(tagDetails, max = 3) {
            if (!tagDetails || !tagDetails.length) return 0;
            return Math.max(0, tagDetails.length - max);
        },
    };
}
