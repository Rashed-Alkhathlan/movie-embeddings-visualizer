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

/* Suggestion chips */
suggestionsEl.addEventListener('click', (e) => {
    const chip = e.target.closest('.suggestion-chip');
    if (!chip) return;
    inputEl.value = chip.textContent.replace(/^[^\w]+/, '').trim();
    inputEl.dispatchEvent(new Event('input'));
    suggestionsEl.remove();
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
                    activeStatuses.push(event.data);    // ← push to queue
                    renderStatuses();

                } else if (event.type === 'status_clear') {
                    activeStatuses.shift();             // ← remove oldest
                    renderStatuses();

                } else if (event.type === 'token') {
                    activeStatuses = [];                // ← clear when answer starts
                    if (!streamingRow) {
                        typingRow.remove();
                        streamingRow = document.createElement('div');
                        streamingRow.className = 'msg-row bot';
                        streamingRow.innerHTML = `
                            <div class="msg-avatar">AI</div>
                            <div class="msg-col">
                                <div class="msg-bubble streaming"></div>
                            </div>`;
                        messagesEl.appendChild(streamingRow);
                    }
                    for (const char of event.data) charQueue.push(char);
                    if (!draining) drainQueue();

                } else if (event.type === 'tokens_reset') {
                    if (streamingRow) {
                        streamingRow.remove();
                        streamingRow = null;
                    }
                    rawTokens = '';
                    charQueue = [];
                    draining = false;
                    // Restore typing indicator
                    typingRow.id = 'typing-row';
                    messagesEl.appendChild(typingRow);
                    scrollToBottom(messagesEl, 200);

                } else if (event.type === 'reply_done') {
                    // Poll until the queue is empty, then finalize
                    function finalize() {
                        if (charQueue.length > 0 || draining) {
                            setTimeout(finalize, 20);
                            return;
                        }
                        if (streamingRow) {
                            const bubble = streamingRow.querySelector('.msg-bubble');
                            bubble.classList.remove('streaming');
                            bubble.innerHTML = marked.parse(rawTokens);

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
        selectModel(active, false);

    } catch {
        modelList.innerHTML = '<div class="model-loading">Failed to load</div>';
    }
}

function selectModel(model, notify = true) {
    currentModel = model.id;
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
        const res = await fetch('/api/chat/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: model.id }),
        });
        if (res.status === 429) {
            appendBotMsg('⏳ Cannot switch model while a response is processing.');
            return;
        }
        appendDateSep(`Switched to ${model.label}`);
        scrollToBottom(messagesEl);
        msgCount = 0;
        updateMsgCount();
    } catch {
        appendBotMsg('⚠ Failed to switch model.');
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
    if (model && model.id !== currentModel) selectModel(model);
    else closeDropdown();
});

document.addEventListener('click', (e) => {
    if (!modelDropdown.contains(e.target) && e.target !== modelBtn) {
        closeDropdown();
    }
});

loadModels();