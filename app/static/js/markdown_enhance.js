/**
 * Markdown Enhance — שיפורים לבלוקי קוד במסמכי Markdown מרונדרים.
 *
 * שני פיצ'רים עיקריים:
 *   1. RTL אוטומטי לבלוקי קוד שתוכנם רוב עברית.
 *   2. כפתור "העתק" קטן (אייקון בלבד) לכל בלוק קוד.
 *
 * הפעלה: אוטומטית ב-DOMContentLoaded על כל .markdown-body בעמוד,
 * ובנוסף MutationObserver שמזהה עדכונים של x-html (Alpine) ומפעיל
 * את השיפורים מחדש על התוכן החדש.
 *
 * חשיפה: window.MarkdownEnhance.enhance(container)  — לקריאה ידנית.
 */
(function () {
    'use strict';

    var HEBREW_THRESHOLD = 0.3;
    var COPY_FEEDBACK_MS = 1500;

    // ============ RTL detection ============

    function isHebrewMajority(text) {
        if (!text) return false;
        var cleaned = text.replace(/\s+/g, '');
        if (cleaned.length === 0) return false;
        var hebrewCount = 0;
        var letterCount = 0;
        for (var i = 0; i < cleaned.length; i++) {
            var c = cleaned.charCodeAt(i);
            if (c >= 0x0590 && c <= 0x05FF) {
                hebrewCount++;
                letterCount++;
            } else if ((c >= 0x0041 && c <= 0x005A) || (c >= 0x0061 && c <= 0x007A)) {
                letterCount++;
            }
            // מספרים, פיסוק וסימנים – לא נספרים, כדי שלא ידללו את היחס
        }
        if (letterCount === 0) return false;
        return hebrewCount / letterCount > HEBREW_THRESHOLD;
    }

    function hasExplicitLanguage(codeEl) {
        var cls = codeEl.className || '';
        // plaintext/text/none נחשבים "ללא שפה" – ולכן כן מותר להחיל RTL
        return /\blanguage-(?!plaintext\b|text\b|nohighlight\b|none\b|txt\b)\S+/.test(cls);
    }

    function applyRtlIfHebrew(codeEl) {
        var pre = codeEl.closest('pre');
        if (!pre) return false;

        // ההחלטה ננעלת בהפעלה הראשונה. רן חוזר (MutationObserver אחרי
        // ש-hljs הוסיף language-X) לא יהפוך את הכיוון - אחרת hasExplicitLanguage
        // היה מחזיר true בריצה השנייה ומסיר את rtl-code מבלוקים עבריים.
        if (codeEl.dataset.rtlDecided === '1') {
            return pre.classList.contains('rtl-code');
        }

        var isHebrew = !hasExplicitLanguage(codeEl) && isHebrewMajority(codeEl.textContent);
        if (isHebrew) {
            pre.classList.add('rtl-code');
        }
        codeEl.dataset.rtlDecided = '1';
        return isHebrew;
    }

    // ============ Copy button ============

    var ICON_COPY =
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>' +
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>' +
        '</svg>';

    var ICON_CHECK =
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<polyline points="20 6 9 17 4 12"></polyline>' +
        '</svg>';

    function getCodeText(pre) {
        // לקיחת הטקסט מתוך ה-code, לא כולל מספרי שורות אם יש
        var code = pre.querySelector('code');
        return (code ? code.textContent : pre.textContent) || '';
    }

    function copyToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        // fallback ל-execCommand (דפדפנים ישנים / contexts לא מאובטחים)
        return new Promise(function (resolve, reject) {
            try {
                var ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                resolve();
            } catch (e) {
                reject(e);
            }
        });
    }

    function addCopyButton(pre) {
        if (pre.dataset.copyBtnAdded === '1') return;
        pre.dataset.copyBtnAdded = '1';

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'md-copy-btn';
        btn.setAttribute('aria-label', 'העתק קוד');
        btn.title = 'העתק';
        btn.innerHTML = ICON_COPY;

        btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var text = getCodeText(pre);
            copyToClipboard(text).then(
                function () {
                    btn.classList.add('copied');
                    btn.innerHTML = ICON_CHECK;
                    btn.title = 'הועתק!';
                    setTimeout(function () {
                        btn.classList.remove('copied');
                        btn.innerHTML = ICON_COPY;
                        btn.title = 'העתק';
                    }, COPY_FEEDBACK_MS);
                },
                function () {
                    btn.title = 'העתקה נכשלה';
                }
            );
        });

        pre.appendChild(btn);
    }

    // ============ Main entry ============

    function runHljs(codeEl) {
        // חייב לרוץ *אחרי* applyRtlIfHebrew: applyRtlIfHebrew מסתמך על
        // ה-class המקורי (לפני ש-hljs מוסיף language-X משלו).
        // idempotent: hljs מסמן data-highlighted='yes' ולא יריץ פעמיים.
        if (!window.hljs || typeof window.hljs.highlightElement !== 'function') return;
        if (codeEl.dataset.highlighted === 'yes') return;
        try {
            window.hljs.highlightElement(codeEl);
        } catch (e) {
            // לא מפיל את ה-page בגלל בלוק בעייתי
            console.warn('hljs failed on block:', e);
        }
    }

    function enhanceBlock(codeEl) {
        applyRtlIfHebrew(codeEl);
        runHljs(codeEl);
        var pre = codeEl.closest('pre');
        if (pre) addCopyButton(pre);
    }

    function enhance(container) {
        var root = container || document;
        // codehilite של Pygments עוטף ב-div.highlight, אך גם ללא wrapper – pre>code תקף
        var blocks = root.querySelectorAll('.markdown-body pre > code');
        blocks.forEach(enhanceBlock);
    }

    // ============ Auto-init + MutationObserver ============

    function init() {
        enhance(document);

        // מעקב אחר עדכוני x-html של Alpine: כל שינוי ב-childList של
        // .markdown-body מפעיל enhance מחדש. debounce ל-rAF כדי לא להריץ
        // פעמים רבות ברצף. enhance הוא idempotent (כפתור לא מתווסף פעמיים).
        var pending = false;
        function schedule() {
            if (pending) return;
            pending = true;
            requestAnimationFrame(function () {
                pending = false;
                enhance(document);
            });
        }

        var observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var m = mutations[i];
                if (m.type !== 'childList' || m.addedNodes.length === 0) continue;
                var t = m.target;
                if (t.classList && t.classList.contains('markdown-body')) {
                    schedule();
                    return;
                }
                if (t.querySelector && t.querySelector('.markdown-body pre > code')) {
                    schedule();
                    return;
                }
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // חשיפה
    window.MarkdownEnhance = {
        enhance: enhance,
        isHebrewMajority: isHebrewMajority,
        hasExplicitLanguage: hasExplicitLanguage,
        applyRtlIfHebrew: applyRtlIfHebrew,
    };
})();
