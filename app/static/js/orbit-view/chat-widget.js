// chat-widget.js  —  Movie Orbit chatbot widget

import { scrollToBottom } from '../utils.js';

/* ── Build DOM ─────────────────────────────────────────────────── */
const toggle = document.createElement('button');
toggle.id = 'chat-toggle';
toggle.className = 'chat-toggle';
toggle.setAttribute('aria-label', 'Open movie assistant');
toggle.innerHTML = `
    <svg class="icon-chat" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M20 2H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h3l3 3 3-3h7a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zm-2 9H6V9h12v2zm0-4H6V5h12v2z"/>
    </svg>
    <svg class="icon-close" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
    </svg>`;

const panel = document.createElement('div');
panel.id = 'chat-panel';
panel.className = 'chat-panel';
panel.setAttribute('aria-live', 'polite');
panel.innerHTML = `
    <div class="chat-header">
        <div class="chat-resize-handle" id="chat-resize"></div>
        <div class="chat-header-dot"></div>
        <span class="chat-header-title">Movie Assistant</span>
        <span class="chat-header-sub">AI · online</span>
        <button class="chat-expand-btn" id="chat-expand-btn" title="Expand">
            <!-- expand icon, swaps to collapse when expanded -->
            <svg id="expand-icon" viewBox="0 0 24 24"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>
            <svg id="collapse-icon" viewBox="0 0 24 24" style="display:none"><path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/></svg>
        </button>
    </div>
    <div class="chat-messages" id="chat-messages">
        <div class="chat-msg bot">
            Hey! Ask me anything about movies — genres, recommendations, cast, plot comparisons, and more. 🎬
        </div>
    </div>
    <div class="chat-input-row">
        <input
            id="chat-input"
            class="chat-input"
            type="text"
            placeholder="Ask about a movie…"
            autocomplete="off"
            maxlength="400"
        />
        <button id="chat-send" class="chat-send" aria-label="Send">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
        </button>
    </div>`;

document.body.appendChild(toggle);
document.body.appendChild(panel);

function openPanel() {
    panel.classList.add('open');
    toggle.classList.add('open');
    chatInput.focus();
}

function closePanel() {
    panel.classList.remove('open');
    toggle.classList.remove('open');
}

/* ── Refs ──────────────────────────────────────────────────────── */
const messages   = document.getElementById('chat-messages');
const chatInput  = document.getElementById('chat-input');
const sendBtn    = document.getElementById('chat-send');

/* ── Toggle open/close ─────────────────────────────────────────── */
toggle.addEventListener('click', () => {
    panel.classList.contains('open') ? closePanel() : openPanel();
    if (isOpen) {
        chatInput.focus();
    }
});

// Close panel when clicking outside
document.addEventListener('click', (e) => {
    if (didResize) { didResize = false; return; }  // ignore post-resize clicks
    if (!panel.contains(e.target) && e.target !== toggle) {
        closePanel();
    }
});

/* ── Helpers ───────────────────────────────────────────────────── */
function appendMsg(text, role) {
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
}

function showTyping() {
    const div = document.createElement('div');
    div.className = 'chat-msg bot typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
}

/* ── Send ──────────────────────────────────────────────────────── */
function setTypingStatus(typingDiv, statusText) {
    const html = marked.parse(
        typeof statusText === "string" ? statusText : ""
    );
    if (html) {
        typingDiv.className = 'chat-msg bot status';
        typingDiv.innerHTML = `<div class="chat-status-spinner"></div><span>${html}</span>`;
    } else {
        typingDiv.className = 'chat-msg bot typing';
        typingDiv.innerHTML = '<span></span><span></span><span></span>';
    }
    scrollToBottom(messages);
}

function setInputLocked(locked) {
    chatInput.disabled = locked;
    sendBtn.disabled = locked;
    chatInput.style.opacity = locked ? '0.4' : '1';
    chatInput.placeholder = locked
        ? 'Waiting for response…'
        : 'Ask about a movie…';
}

async function send() {
    const text = chatInput.value.trim();
    if (!text) return;

    chatInput.value = '';
    sendBtn.disabled = true;

    appendMsg(text, 'user');
    const typingDiv = showTyping();
    setInputLocked(true);

    let streamingDiv = null;
    let rawTokens = '';
    let charQueue = [];
    let draining = false;

    function drainQueue() {
        if (charQueue.length === 0) {
            draining = false;
            return;
        }
        draining = true;
        const char = charQueue.shift();
        rawTokens += char;

        if (streamingDiv) {
            streamingDiv.innerHTML = marked.parse(rawTokens);
            scrollToBottom(messages);
        }

        setTimeout(drainQueue, 4);
    }

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text }),
        });

        if (res.status === 429) {
            typingDiv.remove();
            appendMsg('⏳ The assistant is busy. Please wait a moment and try again.', 'bot');
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
                    setTypingStatus(typingDiv, event.data);

                } else if (event.type === 'status_clear') {
                    setTypingStatus(typingDiv, null);

                } else if (event.type === 'token') {
                    if (!streamingDiv) {
                        typingDiv.remove();
                        streamingDiv = document.createElement('div');
                        streamingDiv.className = 'chat-msg bot streaming';
                        messages.appendChild(streamingDiv);
                    }
                    for (const char of event.data) charQueue.push(char);
                    if (!draining) drainQueue();

               } else if (event.type === 'tokens_reset') {
                    if (streamingDiv) {
                        streamingDiv.remove();
                        streamingDiv = null;
                    }
                    rawTokens = '';
                    charQueue = [];
                    draining = false;
                    // Restore typing indicator
                    typingDiv.id = 'typing-row';
                    messages.appendChild(typingDiv);
                    scrollToBottom(messages);
                    
                } else if (event.type === 'reply_done') {
                    function finalize() {
                        if (charQueue.length > 0 || draining) {
                            setTimeout(finalize, 20);
                            return;
                        }
                        if (streamingDiv) {
                            streamingDiv.classList.remove('streaming');
                            streamingDiv.innerHTML = marked.parse(rawTokens);
                        }
                        scrollToBottom(messages);
                    }
                    finalize();

                } else if (event.type === 'error') {
                    typingDiv.remove();
                    streamingDiv?.remove();        // remove the cursored bubble if it exists
                    streamingDiv = null;
                    charQueue = [];                // stop draining
                    draining = false;
                    appendMsg('⚠ ' + event.data, 'bot');
                }
            }
        }
    } catch (_err) {
        console.log(_err.message);
        typingDiv.remove();
        streamingDiv?.remove();        // same cleanup
        streamingDiv = null;
        charQueue = [];
        draining = false;
        appendMsg('⚠ Could not reach the server.', 'bot');
    } finally {
        setInputLocked(false);
    }
}

sendBtn.addEventListener('click', send);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
    }
});

/* ── Expand / collapse ─────────────────────────────────────── */
const expandBtn     = document.getElementById('chat-expand-btn');
const expandIcon    = document.getElementById('expand-icon');
const collapseIcon  = document.getElementById('collapse-icon');

let sizeBeforeExpand = null;

expandBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isExpanded = panel.classList.toggle('expanded');

    if (isExpanded) {
        // Save current size before expanding
        sizeBeforeExpand = { w: panel.offsetWidth, h: panel.offsetHeight };
        // Clear inline styles so the CSS class takes over
        panel.style.transition = '';
        panel.style.width  = '600px';
        panel.style.height = '800px';
    } else {
        // Restore previous size
        panel.style.transition = '';
        panel.style.width  = (sizeBeforeExpand?.w ?? 320) + 'px';
        panel.style.height = (sizeBeforeExpand?.h ?? 480) + 'px';
        panel.classList.remove('expanded');
    }

    expandIcon.style.display   = isExpanded ? 'none' : '';
    collapseIcon.style.display = isExpanded ? '' : 'none';
    setTimeout(() => messages.scrollTop = messages.scrollHeight, 260);
});

/* ── Resize handle ─────────────────────────────────────────── */
const resizeHandle = document.getElementById('chat-resize');

let isResizing = false;
let startX, startY, startW, startH;

let didResize = false;

resizeHandle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    e.stopPropagation();
    isResizing = true;
    didResize = false;

    startX = e.clientX;
    startY = e.clientY;
    startW = panel.offsetWidth;
    startH = panel.offsetHeight;

    document.addEventListener('mousemove', onResize);
    document.addEventListener('mouseup', stopResize);
});

function onResize(e) {
    if (!isResizing) return;
    didResize = true;
    const dw = startX - e.clientX;   // dragging left = wider
    const dh = startY - e.clientY;   // dragging up   = taller

    const newW = Math.min(Math.max(startW + dw, 280), 700);
    const newH = Math.min(Math.max(startH + dh, 300), 800);

    panel.style.width  = newW + 'px';
    panel.style.height = newH + 'px';
}

function stopResize() {
    isResizing = false;
    panel.style.transition = '';
    document.removeEventListener('mousemove', onResize);
    document.removeEventListener('mouseup', stopResize);
}