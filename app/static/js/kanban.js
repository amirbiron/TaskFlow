/**
 * רכיב Kanban משותף.
 *
 * תכונות:
 * - גרירה ושחרור (תמיכה במגע)
 * - תת-משימות
 * - תגיות
 * - קישורים
 */
function kanbanComponent(config = {}) {
    return {
        // קונפיגורציה
        projectId: config.projectId || null,
        showProjectName: config.showProjectName || false,

        // מצב
        tasks: [],
        loading: true,
        clientOptions: [],
        projectOptions: [],
        // תגיות - מיובא מ-tagPicker, אבל מאתחלים פה
        allTags: [],
        tagSearchQuery: '',
        tagPickerOpen: false,
        creatingTag: false,

        // מודאל משימה
        modalOpen: false,
        modalMode: 'create',
        saving: false,
        error: null,
        currentTaskId: null,
        formData: {
            title: '',
            description: '',
            project_id: '',
            client_id: '',
            priority: 'normal',
            status: 'open',
            due_date: '',
            reminder_date: '',
            links: [],
            tags: [],
            subtasks: [],
        },
        newLink: '',
        newSubtask: '',

        // טאב כתיבה/תצוגה־מקדימה לתיאור (Markdown)
        descriptionTab: 'write',
        descriptionPreviewHtml: '',

        // העלאת תמונה לתיאור משימה (R2)
        descImageUploading: false,
        descDragOver: false,

        // מודאל מחיקה
        deleteConfirmOpen: false,

        // מצב בחירה מרובה (לארכוב משימות מעמודת "הושלם")
        selectionMode: false,
        selectedTaskIds: [],
        archiving: false,

        // עמודות
        statusColumns: [
            { id: 'open', label: 'פתוח' },
            { id: 'in_progress', label: 'בתהליך' },
            { id: 'completed', label: 'הושלם' },
        ],

        async init() {
            await Promise.all([
                this.loadTasks(),
                this.loadClients(),
                this.loadProjects(),
                this.loadAllTags(),
            ]);
            this.$nextTick(() => this.initSortable());
        },

        async loadTasks() {
            this.loading = true;
            try {
                let url = '/api/tasks';
                if (this.projectId) url += `?project_id=${this.projectId}`;
                const res = await fetch(url);
                if (res.status === 401) { window.location = '/login'; return; }
                this.tasks = await res.json();
            } catch (e) {
                console.error('שגיאה בטעינת משימות:', e);
            } finally {
                this.loading = false;
            }
        },

        async loadClients() {
            try {
                const res = await fetch('/api/clients/select-options');
                if (res.ok) this.clientOptions = await res.json();
            } catch (e) { console.error(e); }
        },

        async loadProjects() {
            try {
                const res = await fetch('/api/projects?include_inactive=true');
                if (res.ok) {
                    const data = await res.json();
                    this.projectOptions = data.map(p => ({ _id: p._id, name: p.name }));
                }
            } catch (e) { console.error(e); }
        },

        async loadAllTags() {
            try {
                const res = await fetch('/api/tags');
                if (res.ok) this.allTags = await res.json();
            } catch (e) { console.error(e); }
        },

        tasksByStatus(statusId) {
            return this.tasks
                .filter(t => t.status === statusId)
                .sort((a, b) => (a.column_order || 0) - (b.column_order || 0));
        },

        priorityLabel(p) {
            return { low: 'נמוכה', normal: 'רגילה', high: 'גבוהה', urgent: 'דחוף' }[p] || p;
        },

        priorityClass(p) {
            return {
                low: 'bg-slate-100 text-slate-600',
                normal: 'bg-blue-50 text-blue-700',
                high: 'bg-amber-50 text-amber-700',
                urgent: 'bg-red-50 text-red-700',
            }[p] || 'bg-slate-100 text-slate-600';
        },

        formatDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const dt = new Date(d);
            dt.setHours(0, 0, 0, 0);
            const diff = (dt - today) / (1000 * 60 * 60 * 24);
            if (diff === 0) return 'היום';
            if (diff === 1) return 'מחר';
            if (diff === -1) return 'אתמול';
            return d.toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit' });
        },

        // המרה של ISO datetime לפורמט שמתאים ל-<input type="datetime-local"> בזמן מקומי
        toDatetimeLocal(isoStr) {
            if (!isoStr) return '';
            const d = new Date(isoStr);
            const pad = n => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        },

        // עזרים להשוואת תאריכי דדליין מול היום (בזמן מקומי, ללא שעה)
        _dueParts(dateStr) {
            const d = new Date(dateStr);
            const today = new Date();
            const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
            const startOfDue = new Date(d.getFullYear(), d.getMonth(), d.getDate());
            return { startOfDue, startOfToday };
        },

        // הוחלט שתאריכי יעד לא יקבלו צבע מיוחד גם אם עברו - תמיד אפור רגיל.
        isOverdue(dateStr, status) {
            if (!dateStr || status === 'completed') return false;
            const { startOfDue, startOfToday } = this._dueParts(dateStr);
            return startOfDue < startOfToday;
        },

        dueDateBadgeClass() {
            return 'bg-slate-100 text-slate-600';
        },

        // === Sortable / גרירה ===
        initSortable() {
            this.statusColumns.forEach(col => {
                const el = document.getElementById(`column-${col.id}`);
                if (!el) return;

                // הסרת sortable קיים אם יש
                if (el._sortable) {
                    el._sortable.destroy();
                }

                el._sortable = new Sortable(el, {
                    group: 'kanban-tasks',
                    animation: 150,
                    // הגבלת פריטי הגרירה לכרטיסים בלבד — אחרת ברירת המחדל '>*'
                    // כוללת גם את אלמנט ה-<template> של Alpine ומבלבלת את Sortable.
                    draggable: '[data-task-id]',
                    // הגרירה מתחילה רק מתוך ידית הגרירה. כך לחיצה רגילה
                    // על גוף הכרטיס פותחת את המודאל מיד, ללא delay מבלבל.
                    handle: '.drag-handle',
                    ghostClass: 'task-ghost',
                    chosenClass: 'task-chosen',
                    dragClass: 'task-drag',
                    // forceFallback מאלץ את מנגנון הגרירה הפנימי של Sortable
                    // (מבוסס touch events) במקום HTML5 drag-and-drop, שלא
                    // נתמך באופן עקבי בנייד (במיוחד iOS Safari).
                    forceFallback: true,
                    fallbackTolerance: 5,
                    onEnd: (evt) => this.handleDragEnd(evt),
                });
            });
        },

        async handleDragEnd(evt) {
            // קודם קוראים את הסדר/סטטוס החדש מה-DOM (כפי ש-Sortable עדכן אותו)
            const updates = [];
            const collectFromColumn = (columnEl) => {
                const status = columnEl.dataset.status;
                Array.from(columnEl.children)
                    .filter(c => c.dataset && c.dataset.taskId)
                    .forEach((el, index) => {
                        updates.push({
                            id: el.dataset.taskId,
                            status,
                            column_order: index,
                        });
                    });
            };
            collectFromColumn(evt.to);
            if (evt.from !== evt.to) collectFromColumn(evt.from);

            // מחזירים את הצומת למיקום המקורי כדי ש-Alpine יבנה את ה-DOM מחדש
            // מתוך this.tasks בלי קונפליקט עם המהלך הידני של Sortable.
            if (evt.from !== evt.to || evt.oldIndex !== evt.newIndex) {
                // בגרירה בתוך אותה עמודה, אם זזנו לאחור (oldIndex > newIndex),
                // האיבר ב-oldIndex כבר זז מקום לאחר הוצאת evt.item מהעץ.
                // לכן צריך לכוון לאיבר הבא כדי להחזיר בדיוק למיקום המקורי.
                // חשוב: Sortable מחשב אינדקסים רק עבור פריטי גרירה, ולכן
                // אנחנו מסתמכים על רשימת כרטיסים (data-task-id) ולא על children.
                const isSameColumn = evt.from === evt.to;
                const movedBackwardInSameColumn = isSameColumn && evt.oldIndex > evt.newIndex;
                const referenceIndex = movedBackwardInSameColumn ? evt.oldIndex + 1 : evt.oldIndex;
                const taskElements = Array.from(evt.from.children)
                    .filter(el => el.dataset && el.dataset.taskId);
                const reference = taskElements[referenceIndex] || null;
                evt.from.insertBefore(evt.item, reference);
            }

            try {
                await fetch('/api/tasks/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tasks: updates }),
                });
            } catch (e) {
                console.error('שגיאה בעדכון סדר:', e);
            } finally {
                await this.loadTasks();
                // לחבר מחדש את SortableJS לצמתים שנבנו מחדש על-ידי Alpine
                this.$nextTick(() => this.initSortable());
            }
        },

        // === ניהול מודאל ===
        resetForm() {
            this.formData = {
                title: '',
                description: '',
                project_id: this.projectId || '',
                client_id: '',
                priority: 'normal',
                status: 'open',
                due_date: '',
                reminder_date: '',
                links: [],
                tags: [],
                subtasks: [],
            };
            this.newLink = '';
            this.newSubtask = '';
            this.tagSearchQuery = '';
            this.tagPickerOpen = false;
            this.error = null;
            this.currentTaskId = null;
            this.descriptionTab = 'write';
            this.descriptionPreviewHtml = '';
        },

        async loadDescriptionPreview() {
            this.descriptionTab = 'preview';
            const text = (this.formData.description || '').trim();
            if (!text) { this.descriptionPreviewHtml = ''; return; }
            try {
                const res = await fetch('/api/tasks/_render', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text }),
                });
                if (res.ok) {
                    const data = await res.json();
                    this.descriptionPreviewHtml = data.html || '';
                } else {
                    this.descriptionPreviewHtml = this.escapeHtmlForPreview(text);
                }
            } catch (e) {
                this.descriptionPreviewHtml = this.escapeHtmlForPreview(text);
            }
        },

        escapeHtmlForPreview(s) {
            return String(s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        },

        // === העלאת תמונה לתיאור משימה (Markdown) ===
        // escape ל-alt text של תמונת Markdown - תווים שעלולים לשבור
        // את התחביר ![alt](url) (סוגריים, סוגריים מרובעים, backslash).
        _escapeMdAlt(name) {
            return String(name || '').replace(/[\\\[\]()]/g, '\\$&');
        },

        // מעלה תמונה ל-R2 ומשבץ ![](url) במקום הסמן (או בסוף הטקסט).
        async _uploadImageAndInsert(file) {
            if (!file) return;
            if (!file.type || !file.type.startsWith('image/')) {
                alert('אפשר להעלות רק תמונות');
                return;
            }
            if (file.size > 5 * 1024 * 1024) {
                alert('התמונה גדולה מדי (עד 5MB)');
                return;
            }
            this.descImageUploading = true;
            try {
                const fd = new FormData();
                fd.append('file', file);
                const res = await fetch('/api/uploads/image', { method: 'POST', body: fd });
                if (res.status === 401) { window.location = '/login'; return; }
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    alert(err.detail || 'שגיאה בהעלאת תמונה');
                    return;
                }
                const data = await res.json();
                const alt = this._escapeMdAlt(file.name) || 'image';
                this._insertAtCursor(
                    this.$refs.descriptionTextarea,
                    'description',
                    `![${alt}](${data.file_url})`,
                );
            } catch (e) {
                alert('שגיאת רשת בהעלאה');
            } finally {
                this.descImageUploading = false;
            }
        },

        // הוספת טקסט במקום הסמן בתוך textarea של Alpine (x-model).
        // עוטף ברווחים נקיים כדי שהשיבוץ לא יידבק לטקסט קיים.
        _insertAtCursor(ta, modelField, text) {
            const target = ta && typeof ta.selectionStart === 'number' ? ta : null;
            const current = this.formData[modelField] || '';
            const start = target ? target.selectionStart : current.length;
            const end = target ? target.selectionEnd : current.length;
            const before = current.slice(0, start);
            const after = current.slice(end);

            // נדאג שיהיו שורות ריקות לפני ואחרי כדי שהתמונה תופיע כבלוק.
            const leadingNl = before.endsWith('\n\n') || before === '' ? '' :
                              before.endsWith('\n') ? '\n' : '\n\n';
            const trailingNl = after.startsWith('\n\n') || after === '' ? '' :
                               after.startsWith('\n') ? '\n' : '\n\n';

            const insert = leadingNl + text + trailingNl;
            const newValue = before + insert + after;
            this.formData[modelField] = newValue;

            if (target) {
                const newPos = start + insert.length;
                this.$nextTick(() => {
                    target.focus();
                    target.setSelectionRange(newPos, newPos);
                });
            }
        },

        onDescImageSelected(event) {
            const file = event.target.files && event.target.files[0];
            event.target.value = '';
            if (file) this._uploadImageAndInsert(file);
        },

        onDescImageDrop(event) {
            this.descDragOver = false;
            const dt = event.dataTransfer;
            if (!dt || !dt.files || !dt.files.length) return;
            const file = Array.from(dt.files).find(f => f.type.startsWith('image/'));
            if (file) this._uploadImageAndInsert(file);
        },

        onDescImagePaste(event) {
            const items = event.clipboardData && event.clipboardData.items;
            if (!items) return;
            for (const it of items) {
                if (it.kind === 'file' && it.type.startsWith('image/')) {
                    const file = it.getAsFile();
                    if (file) {
                        event.preventDefault();
                        this._uploadImageAndInsert(file);
                        return;
                    }
                }
            }
        },

        navigateToTask(taskId, task) {
            // במצב בחירה - לחיצה על כרטיס בעמודת "הושלם" מסמנת/מבטלת סימון
            // במקום לנווט לעמוד המשימה.
            if (this.selectionMode && task && task.status === 'completed') {
                this.toggleTaskSelection(taskId);
                return;
            }
            // לחיצה על הכרטיס מנווטת לדף המשימה. עריכה מהירה
            // עדיין זמינה דרך כפתור העיפרון בכרטיס (@click.stop).
            window.location = `/tasks/${taskId}`;
        },

        // === מצב בחירה מרובה ושליחה לארכיון ===
        enterSelectionMode() {
            this.selectionMode = true;
            // ברירת מחדל: כל המשימות בעמודת "הושלם" מסומנות.
            this.selectedTaskIds = this.tasksByStatus('completed').map(t => t._id);
            // ניטרול גרירה במצב בחירה
            this.$nextTick(() => this.destroySortable());
        },

        exitSelectionMode() {
            this.selectionMode = false;
            this.selectedTaskIds = [];
            // הפעלה מחדש של גרירה
            this.$nextTick(() => this.initSortable());
        },

        isTaskSelected(taskId) {
            return this.selectedTaskIds.includes(taskId);
        },

        toggleTaskSelection(taskId) {
            const idx = this.selectedTaskIds.indexOf(taskId);
            if (idx >= 0) {
                this.selectedTaskIds.splice(idx, 1);
            } else {
                this.selectedTaskIds.push(taskId);
            }
        },

        selectAllCompleted() {
            this.selectedTaskIds = this.tasksByStatus('completed').map(t => t._id);
        },

        // אחרי loadTasks, לסנן מהבחירה משימות שכבר לא בעמודת "הושלם"
        // (יכול לקרות אחרי עריכה שהחזירה משימה ל"פתוח"/"בתהליך").
        syncSelectionAfterReload() {
            if (!this.selectionMode) return;
            const completedIds = new Set(this.tasksByStatus('completed').map(t => t._id));
            this.selectedTaskIds = this.selectedTaskIds.filter(id => completedIds.has(id));
        },

        async archiveSelected() {
            if (this.archiving) return;
            const ids = [...this.selectedTaskIds];
            if (ids.length === 0) return;
            const ok = confirm(`להעביר ${ids.length} משימות לארכיון?`);
            if (!ok) return;

            this.archiving = true;
            try {
                const res = await fetch('/api/tasks/archive', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_ids: ids }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    alert(err.detail || 'שגיאה בארכוב');
                    return;
                }
                this.selectionMode = false;
                this.selectedTaskIds = [];
                await this.loadTasks();
                this.$nextTick(() => this.initSortable());
            } catch (e) {
                alert('שגיאת רשת');
            } finally {
                this.archiving = false;
            }
        },

        destroySortable() {
            this.statusColumns.forEach(col => {
                const el = document.getElementById(`column-${col.id}`);
                if (el && el._sortable) {
                    el._sortable.destroy();
                    el._sortable = null;
                }
            });
        },

        openCreateModal(initialStatus = 'open') {
            this.resetForm();
            this.formData.status = initialStatus;
            this.modalMode = 'create';
            this.modalOpen = true;
        },

        openEditModal(task) {
            this.currentTaskId = task._id;
            this.formData = {
                title: task.title || '',
                description: task.description || '',
                project_id: task.project_id || '',
                client_id: task.client_id || '',
                priority: task.priority || 'normal',
                status: task.status || 'open',
                due_date: task.due_date ? task.due_date.substring(0, 10) : '',
                reminder_date: task.reminder_date ? this.toDatetimeLocal(task.reminder_date) : '',
                links: [...(task.links || [])],
                tags: [...(task.tags || [])],
                subtasks: (task.subtasks || []).map(st => ({ ...st })),
            };
            this.newLink = '';
            this.newSubtask = '';
            this.tagSearchQuery = '';
            this.tagPickerOpen = false;
            this.modalMode = 'edit';
            this.error = null;
            this.descriptionTab = 'write';
            this.descriptionPreviewHtml = '';
            this.modalOpen = true;
        },

        closeModal() {
            this.modalOpen = false;
            this.error = null;
            setTimeout(() => this.resetForm(), 200);
        },

        // === קישורים ===
        addLink() {
            const link = this.newLink.trim();
            if (!link) return;
            this.formData.links.push(link);
            this.newLink = '';
        },

        removeLink(index) {
            this.formData.links.splice(index, 1);
        },

        // === תת-משימות ===
        generateId() {
            return 'st_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        },

        addSubtask() {
            const title = this.newSubtask.trim();
            if (!title) return;
            this.formData.subtasks.push({
                id: this.generateId(),
                title: title,
                completed: false,
            });
            this.newSubtask = '';
        },

        removeSubtask(index) {
            this.formData.subtasks.splice(index, 1);
        },

        toggleSubtask(index) {
            this.formData.subtasks[index].completed = !this.formData.subtasks[index].completed;
        },

        // === תגיות ===
        get selectedTagDetails() {
            if (!this.formData.tags || !this.allTags.length) return [];
            return this.formData.tags
                .map(tagId => this.allTags.find(t => t._id === tagId))
                .filter(Boolean);
        },

        get availableTags() {
            const selectedIds = new Set(this.formData.tags || []);
            const query = (this.tagSearchQuery || '').trim().toLowerCase();
            return this.allTags.filter(t => {
                if (selectedIds.has(t._id)) return false;
                if (!query) return true;
                return t.name.toLowerCase().includes(query);
            });
        },

        get canCreateNewTag() {
            const query = (this.tagSearchQuery || '').trim();
            if (!query) return false;
            return !this.allTags.some(t => t.name.toLowerCase() === query.toLowerCase());
        },

        addTag(tagId) {
            if (!this.formData.tags) this.formData.tags = [];
            if (!this.formData.tags.includes(tagId)) {
                this.formData.tags.push(tagId);
            }
            this.tagSearchQuery = '';
        },

        removeTag(tagId) {
            this.formData.tags = (this.formData.tags || []).filter(id => id !== tagId);
        },

        async createAndAddTag() {
            const name = (this.tagSearchQuery || '').trim();
            if (!name || this.creatingTag) return;
            this.creatingTag = true;
            try {
                const res = await fetch('/api/tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name, color: '#3B82F6' }),
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

        // עזרי תצוגה לכרטיסים
        visibleTaskTags(task, max = 3) {
            return (task.tag_details || []).slice(0, max);
        },

        hiddenTaskTagsCount(task, max = 3) {
            return Math.max(0, (task.tag_details || []).length - max);
        },

        completedSubtasksCount(task) {
            return (task.subtasks || []).filter(st => st.completed).length;
        },

        // === שמירה / מחיקה ===
        async saveTask() {
            this.saving = true;
            this.error = null;

            try {
                const payload = { ...this.formData };
                if (!payload.client_id) payload.client_id = null;
                if (!payload.description || !payload.description.trim()) payload.description = null;
                if (!payload.due_date) payload.due_date = null;
                else payload.due_date = new Date(payload.due_date).toISOString();

                // reminder_date - datetime-local: ריק => null + איפוס reminder_sent
                if (!payload.reminder_date) {
                    payload.reminder_date = null;
                } else {
                    payload.reminder_date = new Date(payload.reminder_date).toISOString();
                }
                // בכל עריכה של reminder_date - לאפס את reminder_sent כדי שתישלח שוב
                payload.reminder_sent = false;

                if (!payload.project_id) {
                    this.error = 'יש לבחור פרויקט';
                    this.saving = false;
                    return;
                }

                const url = this.modalMode === 'create'
                    ? '/api/tasks'
                    : `/api/tasks/${this.currentTaskId}`;
                const method = this.modalMode === 'create' ? 'POST' : 'PUT';

                const res = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });

                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this.error = err.detail || 'שגיאה בשמירה';
                    return;
                }

                await this.loadTasks();
                this.closeModal();
                if (this.selectionMode) {
                    this.syncSelectionAfterReload();
                    // לא להפעיל מחדש Sortable במצב בחירה
                } else {
                    this.$nextTick(() => this.initSortable());
                }
            } catch (e) {
                this.error = 'שגיאת רשת';
                console.error(e);
            } finally {
                this.saving = false;
            }
        },

        confirmDelete(task) {
            this.currentTaskId = task._id;
            this.formData.title = task.title;
            this.modalOpen = false;
            this.deleteConfirmOpen = true;
        },

        async deleteTask() {
            this.saving = true;
            try {
                const res = await fetch(`/api/tasks/${this.currentTaskId}`, { method: 'DELETE' });
                if (!res.ok && res.status !== 204) {
                    const err = await res.json().catch(() => ({}));
                    alert(err.detail || 'שגיאה במחיקה');
                    return;
                }
                this.deleteConfirmOpen = false;
                await this.loadTasks();
                this.resetForm();
                if (this.selectionMode) {
                    this.syncSelectionAfterReload();
                } else {
                    this.$nextTick(() => this.initSortable());
                }
            } catch (e) {
                alert('שגיאת רשת');
            } finally {
                this.saving = false;
            }
        },
    };
}
