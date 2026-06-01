import { escHtml, scrollToBottom } from '../utils.js';

// ----------------- Starry background -----------------

const canvas = document.getElementById('stars');
const ctx = canvas.getContext('2d');
let stars = [];

function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    stars = Array.from({ length: 200 }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        s: Math.random() * 1.6 + 0.2,
        a: Math.random() * 0.7 + 0.1,
        speed: Math.random() * 0.015 + 0.003,
        phase: Math.random() * Math.PI * 2,
    }));
}

function draw(t) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const star of stars) {
        const alpha = star.a * (0.6 + 0.4 * Math.sin(t * star.speed + star.phase));
        ctx.fillStyle = `rgba(200,220,255,${alpha})`;
        ctx.fillRect(star.x, star.y, star.s, star.s);
    }
    requestAnimationFrame(draw);
}

window.addEventListener('resize', resize);
resize();
requestAnimationFrame(draw);


// ---------------------- Chat logic -----------------------

const messagesEl = document.getElementById('messages');
const inputEl    = document.getElementById('chat-input');
const sendBtn    = document.getElementById('send-btn');
const charCount  = document.getElementById('char-count');
const msgCountEl = document.getElementById('msg-count');
const clearBtn   = document.getElementById('clear-btn');
const suggestionsEl = document.getElementById('suggestions');

let msgCount = 0;

/* Set welcome timestamp */
document.getElementById('welcome-time').textContent = formatTime(new Date());

function formatTime(d) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/* Auto-resize textarea */
inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
    const remaining = 800 - inputEl.value.length;
    charCount.textContent = remaining;
    charCount.classList.toggle('warn', remaining < 80);
    sendBtn.disabled = !inputEl.value.trim();
});

/* Suggestion chips — kept in place so they can be reused */
suggestionsEl.addEventListener('click', (e) => {
    const chip = e.target.closest('.suggestion-chip');
    if (!chip) return;
    inputEl.value = chip.textContent.replace(/^[^\w]+/, '').trim();
    inputEl.dispatchEvent(new Event('input'));
    sendMessage();
});

/* Keyboard shortcuts */
inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) sendMessage();
    }
});
sendBtn.addEventListener('click', sendMessage);

/* Clear */
clearBtn.addEventListener('click', clear_history);

async function clear_history() {
    try {
        await fetch('/api/chat/history', { method: 'DELETE' });
        messagesEl.innerHTML = '';
        msgCount = 0;
        updateMsgCount();
        appendDateSep('Cleared');
        appendBotMsg('History cleared. Ask me anything about movies!');
    } catch (err) {
        console.error('Failed to clear history:', err);
    }
}

function updateMsgCount() {
    if (!msgCountEl) return;
    msgCountEl.textContent = msgCount === 0
        ? '0 messages'
        : `${msgCount} message${msgCount !== 1 ? 's' : ''}`;
}

function appendDateSep(label) {
    const div = document.createElement('div');
    div.className = 'date-sep';
    div.textContent = label;
    messagesEl.appendChild(div);
}

function appendUserMsg(text) {
    const now = new Date();
    const row = document.createElement('div');
    row.className = 'msg-row user';
    row.innerHTML = `
        <div class="msg-avatar">You</div>
        <div class="msg-col">
            <div class="msg-bubble">${escHtml(text)}</div>
            <div class="msg-time">${formatTime(now)}</div>
        </div>`;
    messagesEl.appendChild(row);
    scrollToBottom(messagesEl);
    msgCount++;
    updateMsgCount();
}

function appendBotMsg(text) {
    const now = new Date();
    const row = document.createElement('div');
    row.className = 'msg-row bot';

    // Convert Markdown to HTML
    const html = marked.parse(
        typeof text === "string" ? text : ""
    );

    row.innerHTML = `
        <div class="msg-avatar">AI</div>
        <div class="msg-col">
            <div class="msg-bubble">${html}</div>
            <div class="msg-time">${formatTime(now)}</div>
        </div>`;
    messagesEl.appendChild(row);
    scrollToBottom(messagesEl);
    msgCount++;
    updateMsgCount();
}

function showTyping() {
    const row = document.createElement('div');
    row.className = 'msg-row bot';
    row.id = 'typing-row';
    row.innerHTML = `
        <div class="msg-avatar">AI</div>
        <div class="typing-bubble">
            <span></span><span></span><span></span>
        </div>`;
    messagesEl.appendChild(row);
    scrollToBottom(messagesEl, 200);
    return row;
}

function setInputLocked(locked) {
    inputEl.disabled = locked;
    sendBtn.disabled = locked;
    inputEl.style.opacity = locked ? '0.4' : '1';
    inputEl.placeholder = locked 
        ? 'Waiting for response…' 
        : 'Ask me anything about movies…';
}

async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    inputEl.value = '';
    inputEl.style.height = 'auto';
    charCount.textContent = '800';
    charCount.classList.remove('warn');
    sendBtn.disabled = true;

    appendUserMsg(text);
    const typingRow = showTyping();
    setInputLocked(true);

    let streamingRow = null;
    let rawTokens = '';
    let charQueue = [];
    let draining = false;
    let activeStatuses = [];        // ← queue of active status messages

    // Reasoning ("thinking") panel — lazily created on the first thinking event.
    let rawThinking = '';
    let thinkPanel = null;
    let thinkBody = null;
    let firstTokenSeen = false;

    function hideTyping() {
        if (typingRow.parentNode) typingRow.remove();
    }

    function ensureStreamingRow() {
        if (streamingRow) return streamingRow;
        hideTyping();
        streamingRow = document.createElement('div');
        streamingRow.className = 'msg-row bot';
        // .bot-response sizes to the wider of the reasoning panel / answer bubble (capped),
        // and both children fill it — so the panel and bubble are always the same width.
        streamingRow.innerHTML = `
            <div class="msg-avatar">AI</div>
            <div class="msg-col">
                <div class="bot-response">
                    <div class="msg-bubble streaming pending"></div>
                </div>
            </div>`;
        messagesEl.appendChild(streamingRow);
        return streamingRow;
    }

    function ensureThinkPanel() {
        ensureStreamingRow();
        if (thinkPanel) return thinkPanel;
        const wrap = streamingRow.querySelector('.bot-response');
        thinkPanel = document.createElement('div');
        thinkPanel.className = 'think-panel streaming expanded';
        thinkPanel.innerHTML = `
            <button class="think-toggle" type="button" aria-expanded="true">
                <span class="think-spinner"></span>
                <span class="think-label">Thinking…</span>
                <svg class="think-chevron" viewBox="0 0 24 24"><path d="M7 10l5 5 5-5z"/></svg>
            </button>
            <div class="think-body"></div>`;
        wrap.insertBefore(thinkPanel, wrap.firstChild);
        thinkBody = thinkPanel.querySelector('.think-body');
        const toggle = thinkPanel.querySelector('.think-toggle');
        toggle.addEventListener('click', () => {
            const open = thinkPanel.classList.toggle('expanded');
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        return thinkPanel;
    }

    function renderStatuses() {
        if (activeStatuses.length === 0) {
            typingRow.innerHTML = `
                <div class="msg-avatar">AI</div>
                <div class="typing-bubble">
                    <span></span><span></span><span></span>
                </div>`;
        } else {
            const items = activeStatuses.map(s =>
                `<div class="status-item">
                    <div class="status-spinner"></div>
                    <span class="status-text">${marked.parse(s)}</span>
                </div>`
            ).join('');
            typingRow.innerHTML = `
                <div class="msg-avatar">AI</div>
                <div class="status-bubble">${items}</div>`;
            // A status may arrive after reasoning removed the typing row — re-attach it.
            if (!typingRow.parentNode) messagesEl.appendChild(typingRow);
        }
        scrollToBottom(messagesEl, 200);
    }

    const CHARS_PER_TICK = 4;

    function drainQueue() {
        if (charQueue.length === 0) {
            draining = false;
            return;
        }
        draining = true;

        // Drain multiple chars per tick
        for (let i = 0; i < CHARS_PER_TICK && charQueue.length > 0; i++) {
            rawTokens += charQueue.shift();
        }

        const bubble = streamingRow.querySelector('.msg-bubble');
        bubble.innerHTML = marked.parse(rawTokens);
        scrollToBottom(messagesEl, 50);

        setTimeout(drainQueue, 4); // ms per character — tune this
    }

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text }),
        });

        if (res.status === 429) {
            typingRow.remove();
            appendBotMsg('⏳ The assistant is busy. Please wait a moment and try again.');
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;

                let event;
                try { event = JSON.parse(line.slice(6)); }
                catch { continue; }

                if (event.type === 'status') {
                    if (thinkPanel && !firstTokenSeen) {
                        // Tool used mid-reasoning — record it inline in the reasoning panel
                        // (as a blockquote) and flag the panel so the marker shows a spinner
                        // while the tool is still running.
                        rawThinking += `\n\n> ${event.data}\n\n`;
                        thinkBody.innerHTML = marked.parse(rawThinking);
                        thinkPanel.classList.add('tool-running');
                        scrollToBottom(messagesEl, 50);
                    } else {
                        activeStatuses.push(event.data);
                        renderStatuses();
                    }

                } else if (event.type === 'status_clear') {
                    if (thinkPanel && thinkPanel.classList.contains('tool-running')) {
                        thinkPanel.classList.remove('tool-running');   // tool finished; freeze the marker
                    } else if (activeStatuses.length) {
                        activeStatuses.shift();
                        renderStatuses();
                    }

                } else if (event.type === 'thinking') {
                    activeStatuses = [];
                    hideTyping();
                    ensureThinkPanel();
                    rawThinking += event.data;
                    thinkBody.innerHTML = marked.parse(rawThinking);
                    scrollToBottom(messagesEl, 200);

                } else if (event.type === 'token') {
                    activeStatuses = [];                // ← clear when answer starts
                    hideTyping();
                    ensureStreamingRow();
                    streamingRow.querySelector('.msg-bubble').classList.remove('pending');
                    if (!firstTokenSeen) {
                        firstTokenSeen = true;
                        if (thinkPanel) {               // collapse reasoning once the answer begins
                            thinkPanel.classList.remove('streaming', 'expanded', 'tool-running');
                            const toggle = thinkPanel.querySelector('.think-toggle');
                            toggle.setAttribute('aria-expanded', 'false');
                            thinkPanel.querySelector('.think-label').textContent = 'Reasoning';
                        }
                    }
                    for (const char of event.data) charQueue.push(char);
                    if (!draining) drainQueue();

                } else if (event.type === 'tokens_reset') {
                    rawTokens = '';
                    charQueue = [];
                    draining = false;
                    if (streamingRow && thinkPanel) {
                        // Keep the reasoning panel; only discard the partial answer.
                        // The blinking cursor on the empty bubble signals more is coming.
                        const bubble = streamingRow.querySelector('.msg-bubble');
                        if (bubble) bubble.innerHTML = '';
                    } else {
                        if (streamingRow) {
                            streamingRow.remove();
                            streamingRow = null;
                        }
                        // Restore typing indicator
                        typingRow.id = 'typing-row';
                        messagesEl.appendChild(typingRow);
                    }
                    scrollToBottom(messagesEl, 200);

                } else if (event.type === 'reply_done') {
                    // Poll until the queue is empty, then finalize
                    function finalize() {
                        if (charQueue.length > 0 || draining) {
                            setTimeout(finalize, 20);
                            return;
                        }
                        hideTyping();
                        if (thinkPanel) {               // settle the reasoning panel
                            thinkPanel.classList.remove('streaming', 'tool-running');
                            thinkPanel.querySelector('.think-label').textContent = 'Reasoning';
                        }
                        if (streamingRow) {
                            const bubble = streamingRow.querySelector('.msg-bubble');
                            bubble.classList.remove('streaming');
                            if (rawTokens) {
                                bubble.innerHTML = marked.parse(rawTokens);
                            } else if (thinkPanel) {
                                bubble.remove();        // reasoning only, no answer text
                            }

                            const col = streamingRow.querySelector('.msg-col');
                            const time = document.createElement('div');
                            time.className = 'msg-time';
                            time.textContent = formatTime(new Date());
                            col.appendChild(time);
                            msgCount++;
                            updateMsgCount();
                        }
                        scrollToBottom(messagesEl, 200);
                    }
                    finalize();

                } else if (event.type === 'error') {
                    typingRow.remove();
                    streamingRow?.remove();
                    streamingRow = null;
                    charQueue = [];
                    draining = false;
                    appendBotMsg('⚠ ' + event.data);
                }
            }
        }
    } catch (_err) {
        console.log(_err.message);
        typingRow.remove();
        streamingRow?.remove();
        appendBotMsg('⚠ Could not reach the server. Please check your connection.');
    } finally {
        setInputLocked(false);
    }
}

// ---------------------- Model selector -----------------------

const modelBtn      = document.getElementById('model-btn');
const modelLabel    = document.getElementById('model-label');
const modelDropdown = document.getElementById('model-dropdown');
const modelList     = document.getElementById('model-list');

let currentModel = null;
let allModels    = [];

async function loadModels() {
    try {
        const [modelsRes, currentRes] = await Promise.all([
            fetch('/api/chat/models'),
            fetch('/api/chat/model'),
        ]);
        const { models } = await modelsRes.json();
        const { model: activeId } = await currentRes.json();
        allModels = models;

        const groups = {};
        for (const m of models) {
            if (!groups[m.provider]) groups[m.provider] = [];
            groups[m.provider].push(m);
        }

        modelList.innerHTML = Object.entries(groups).map(([provider, items]) => `
            <div class="model-group-label">${provider}</div>
            ${items.map(m => `
                <div class="model-option" data-id="${m.id}">${m.label}</div>
            `).join('')}
        `).join('');

        // Select the currently active model without triggering a switch
        const active = models.find(m => m.id === activeId) || models[0];
        currentModel = active;
        selectModel(active, false);

    } catch {
        modelList.innerHTML = '<div class="model-loading">Failed to load</div>';
    }
}

function selectModel(model, notify = true) {
    modelLabel.textContent = model.label;

    // Update active state
    modelList.querySelectorAll('.model-option').forEach(el => {
        el.classList.toggle('active', el.dataset.id === model.id);
    });

    closeDropdown();
    if (notify) switchModel(model);
}

async function switchModel(model) {
    try {
        setInputLocked(true);
        const res = await fetch('/api/chat/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: model.id }),
        });
        if (res.status === 429) {
            appendDateSep('⏳ Cannot switch model while a response is processing.');
            return;
        }
        if (res.status !== 200) {
            appendDateSep('⚠ Failed to switch model.');
            if (model !== currentModel) {
                selectModel(currentModel, false);
            }
            return;
        }
        currentModel = model;
        selectModel(currentModel, false);
        appendDateSep(`Switched to ${model.label}`);
        scrollToBottom(messagesEl);
        msgCount = 0;
        updateMsgCount();
    } catch {
        appendBotMsg('⚠ Failed to switch model.');
    } finally {
        setInputLocked(false);
    }
}

function closeDropdown() {
    modelDropdown.classList.remove('open');
    modelBtn.classList.remove('open');
}

modelBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = modelDropdown.classList.toggle('open');
    modelBtn.classList.toggle('open', isOpen);
});

modelList.addEventListener('click', (e) => {
    const option = e.target.closest('.model-option');
    if (!option) return;
    const model = allModels.find(m => m.id === option.dataset.id);
    if (model && model.id !== currentModel.id) selectModel(model);
    else closeDropdown();
});

document.addEventListener('click', (e) => {
    if (!modelDropdown.contains(e.target) && e.target !== modelBtn) {
        closeDropdown();
    }
});

loadModels();

// ---------------------- Widenable chat column -----------------------

const pageEl       = document.querySelector('.page');
const resizeHandle = document.getElementById('resize-handle');
const DEFAULT_WIDTH = 850;
const MIN_WIDTH     = 520;

function clampWidth(w) {
    return Math.max(MIN_WIDTH, Math.min(w, Math.round(window.innerWidth * 0.96)));
}

function setChatWidth(w, persist = true) {
    const width = clampWidth(w);
    pageEl.style.width = width + 'px';
    if (persist) localStorage.setItem('chatWidth', width);
}

// Restore a saved width on load.
const savedWidth = parseInt(localStorage.getItem('chatWidth'), 10);
if (savedWidth) setChatWidth(savedWidth, false);

if (resizeHandle) {
    let dragging = false;

    const onMove = (e) => {
        if (!dragging) return;
        const x = e.clientX ?? e.touches?.[0]?.clientX;
        if (x == null) return;
        // The column is centered, so half its width is the distance from center to cursor.
        setChatWidth(Math.round(2 * (x - window.innerWidth / 2)));
    };

    const stop = () => {
        if (!dragging) return;
        dragging = false;
        document.body.classList.remove('resizing');
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', stop);
    };

    resizeHandle.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        dragging = true;
        document.body.classList.add('resizing');
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', stop);
    });

    // Double-click resets to the default width.
    resizeHandle.addEventListener('dblclick', () => setChatWidth(DEFAULT_WIDTH));
}

// Keep the column within bounds if the window shrinks.
window.addEventListener('resize', () => {
    if (pageEl.style.width) setChatWidth(parseInt(pageEl.style.width, 10) || DEFAULT_WIDTH, false);
});