/**
 * רכיב Kanban משותף.
 * מקבל את המשימות ומעדכן את השרת בעת גרירה.
 *
 * שימוש:
 *   kanbanComponent({
 *       projectId: '...',  // אופציונלי - אם null, תצוגה גלובלית
 *       showProjectName: true/false,  // האם להציג את שם הפרויקט בכרטיסים
 *   })
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

        // מודאל משימה
        modalOpen: false,
        modalMode: 'create', // 'create' או 'edit'
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
            links: [],
        },
        newLink: '',

        // מודאל מחיקה
        deleteConfirmOpen: false,

        // עמודות
        statusColumns: [
            { id: 'open', label: 'פתוח', color: 'border-slate-300' },
            { id: 'in_progress', label: 'בתהליך', color: 'border-blue-400' },
            { id: 'completed', label: 'הושלם', color: 'border-green-400' },
        ],

        async init() {
            await Promise.all([
                this.loadTasks(),
                this.loadClients(),
                this.loadProjects(),
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
                    this.projectOptions = data.map(p => ({
                        _id: p._id,
                        name: p.name,
                    }));
                }
            } catch (e) { console.error(e); }
        },

        tasksByStatus(statusId) {
            return this.tasks
                .filter(t => t.status === statusId)
                .sort((a, b) => (a.column_order || 0) - (b.column_order || 0));
        },

        priorityLabel(p) {
            return {
                low: 'נמוכה',
                normal: 'רגילה',
                high: 'גבוהה',
                urgent: 'דחוף',
            }[p] || p;
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

        isOverdue(dateStr, status) {
            if (!dateStr || status === 'completed') return false;
            const d = new Date(dateStr);
            return d < new Date();
        },

        // אתחול גרירה
        initSortable() {
            this.statusColumns.forEach(col => {
                const el = document.getElementById(`column-${col.id}`);
                if (!el) return;

                new Sortable(el, {
                    group: 'kanban-tasks',
                    animation: 150,
                    ghostClass: 'task-ghost',
                    chosenClass: 'task-chosen',
                    dragClass: 'task-drag',
                    onEnd: (evt) => this.handleDragEnd(evt, col.id),
                });
            });
        },

        async handleDragEnd(evt, newStatus) {
            const taskId = evt.item.dataset.taskId;
            const targetColumn = evt.to.dataset.status;

            // נאסוף את כל ה-IDs בעמודת היעד בסדר החדש
            const updates = [];
            const targetTasks = Array.from(evt.to.children).filter(c => c.dataset && c.dataset.taskId);

            targetTasks.forEach((el, index) => {
                updates.push({
                    id: el.dataset.taskId,
                    status: targetColumn,
                    column_order: index,
                });
            });

            // אם העמודה השתנתה, נעדכן גם את עמודת המקור (סדר התעדכן)
            if (evt.from !== evt.to) {
                const sourceTasks = Array.from(evt.from.children).filter(c => c.dataset && c.dataset.taskId);
                const sourceColumn = evt.from.dataset.status;
                sourceTasks.forEach((el, index) => {
                    updates.push({
                        id: el.dataset.taskId,
                        status: sourceColumn,
                        column_order: index,
                    });
                });
            }

            try {
                await fetch('/api/tasks/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tasks: updates }),
                });
                // נטען מחדש לקבל completed_at ושאר נתונים
                await this.loadTasks();
            } catch (e) {
                console.error('שגיאה בעדכון סדר:', e);
                // נחזיר את המצב הקודם בטעינה מחדש
                await this.loadTasks();
            }
        },

        // === ניהול מודאל משימה ===
        resetForm() {
            this.formData = {
                title: '',
                description: '',
                project_id: this.projectId || '',
                client_id: '',
                priority: 'normal',
                status: 'open',
                due_date: '',
                links: [],
            };
            this.newLink = '';
            this.error = null;
            this.currentTaskId = null;
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
                links: [...(task.links || [])],
            };
            this.newLink = '';
            this.modalMode = 'edit';
            this.error = null;
            this.modalOpen = true;
        },

        closeModal() {
            this.modalOpen = false;
            this.error = null;
            setTimeout(() => this.resetForm(), 200);
        },

        addLink() {
            const link = this.newLink.trim();
            if (!link) return;
            this.formData.links.push(link);
            this.newLink = '';
        },

        removeLink(index) {
            this.formData.links.splice(index, 1);
        },

        async saveTask() {
            this.saving = true;
            this.error = null;

            try {
                const payload = { ...this.formData };

                // ניקוי שדות ריקים
                if (!payload.client_id) payload.client_id = null;
                if (!payload.description || !payload.description.trim()) payload.description = null;
                if (!payload.due_date) payload.due_date = null;
                else payload.due_date = new Date(payload.due_date).toISOString();

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
                // נחזיר את ה-Sortable על הרשימות החדשות
                this.$nextTick(() => this.initSortable());
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
                const res = await fetch(`/api/tasks/${this.currentTaskId}`, {
                    method: 'DELETE',
                });
                if (!res.ok && res.status !== 204) {
                    const err = await res.json().catch(() => ({}));
                    alert(err.detail || 'שגיאה במחיקה');
                    return;
                }
                this.deleteConfirmOpen = false;
                await this.loadTasks();
                this.resetForm();
                this.$nextTick(() => this.initSortable());
            } catch (e) {
                alert('שגיאת רשת');
            } finally {
                this.saving = false;
            }
        },
    };
}
