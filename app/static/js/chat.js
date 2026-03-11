// chat.js  —  Movie Orbit chatbot widget

export function initChat() {
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
            <div class="chat-header-dot"></div>
            <span class="chat-header-title">Movie Assistant</span>
            <span class="chat-header-sub">AI · online</span>
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

    /* ── Refs ──────────────────────────────────────────────────────── */
    const messages   = document.getElementById('chat-messages');
    const chatInput  = document.getElementById('chat-input');
    const sendBtn    = document.getElementById('chat-send');

    /* ── Toggle open/close ─────────────────────────────────────────── */
    toggle.addEventListener('click', () => {
        const isOpen = panel.classList.toggle('open');
        toggle.classList.toggle('open', isOpen);
        if (isOpen) {
            chatInput.focus();
        }
    });

    // Close panel when clicking outside
    document.addEventListener('click', (e) => {
        if (!panel.contains(e.target) && e.target !== toggle) {
            panel.classList.remove('open');
            toggle.classList.remove('open');
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
    async function send() {
        const text = chatInput.value.trim();
        if (!text) return;

        chatInput.value = '';
        sendBtn.disabled = true;
        appendMsg(text, 'user');

        const typingEl = showTyping();

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text }),
            });
            const data = await res.json();
            typingEl.remove();
            appendMsg(data.reply || 'No response received.', 'bot');
        } catch (_err) {
            typingEl.remove();
            appendMsg('⚠ Could not reach the server. Please try again.', 'bot');
        } finally {
            sendBtn.disabled = false;
            chatInput.focus();
        }
    }

    sendBtn.addEventListener('click', send);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    });
}