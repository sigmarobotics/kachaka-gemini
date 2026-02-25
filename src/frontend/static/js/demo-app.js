// demo-app.js — Exhibition demo page entry point
import state, { escapeHtml } from './state.js';

// Sub-modules will be imported as they are created
// import { initDemoChat, sendText, connectChat, disconnectChat } from './demo-chat.js';
// import { initDemoStatus } from './demo-status.js';
// import { initDemoPatrol } from './demo-patrol.js';
// import { initDemoVoice } from './demo-voice.js';

let ws = null;
let isConnected = false;
let currentMode = 'text'; // 'text' or 'live'
let statusPollInterval = null;
let settings = {};

// ─── Initialize ──────────────────────────────────────
async function init() {
    // Load settings
    try {
        const res = await fetch('/api/settings');
        if (res.ok) {
            settings = await res.json();
            currentMode = settings.api_mode || 'text';
        }
    } catch (e) {
        console.error('Failed to load settings:', e);
    }

    // Set exhibition title
    const titleEl = document.getElementById('demo-title');
    if (titleEl && settings.exhibition_title) {
        titleEl.textContent = settings.exhibition_title;
    }

    // Set up mode toggle
    const modeToggle = document.getElementById('mode-toggle');
    if (modeToggle) {
        modeToggle.checked = currentMode === 'live';
        modeToggle.addEventListener('change', handleModeToggle);
        updateModeLabel();
    }

    // Set up quick actions
    setupQuickActions();

    // Set up input handlers
    const sendBtn = document.getElementById('btn-demo-send');
    const chatInput = document.getElementById('demo-chat-input');
    if (sendBtn) sendBtn.addEventListener('click', handleSend);
    if (chatInput) {
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        });
    }

    // Start status polling
    statusPollInterval = setInterval(pollStatus, 2000);
    pollStatus(); // immediate first poll

    // Auto-connect WebSocket
    connectWebSocket();
}

// ─── WebSocket ───────────────────────────────────────
function connectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);

    ws.onopen = () => {
        addSystemMessage('正在連接 Gemini...');
        ws.send(JSON.stringify({ type: 'connect' }));
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleMessage(msg);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
    };

    ws.onclose = () => {
        isConnected = false;
        updateConnectionUI(false);
        // Auto-reconnect after 3s
        setTimeout(() => {
            if (!isConnected) connectWebSocket();
        }, 3000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };
}

function disconnectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'disconnect' }));
    }
    if (ws) {
        ws.close();
        ws = null;
    }
    isConnected = false;
    updateConnectionUI(false);
}

// ─── Message handling ────────────────────────────────
function handleMessage(msg) {
    switch (msg.type) {
        case 'status':
            if (msg.message && msg.message.includes('Connected to Gemini')) {
                isConnected = true;
                if (msg.api_mode) currentMode = msg.api_mode;
                updateConnectionUI(true);
                addSystemMessage('已連接 Gemini ✓');
            } else {
                addSystemMessage(msg.message || '');
            }
            break;

        case 'text':
            addBotMessage(msg.content || '');
            break;

        case 'audio':
            // Forward to demo-voice module for playback + waveform
            if (window._demoVoiceOnAudio) {
                window._demoVoiceOnAudio(msg.data);
            }
            break;

        case 'function_call':
            addSystemMessage(`執行中: ${msg.name || ''}...`);
            break;

        case 'function_result':
            // Gemini will summarize; no direct display needed
            break;

        case 'turn_complete':
            // Typing indicator off
            hideTypingIndicator();
            break;

        case 'error':
            addSystemMessage(`錯誤: ${msg.message || ''}`);
            break;

        case 'token_usage':
            // Optionally display
            break;

        case 'patrol_started':
            addSystemMessage('巡檢已啟動');
            break;

        default:
            console.log('Unknown message type:', msg.type);
    }
}

// ─── Chat UI ─────────────────────────────────────────
function addBotMessage(text) {
    const container = document.getElementById('demo-chat-messages');
    if (!container) return;
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble robot';
    bubble.innerHTML = `<div class="bubble-content">${escapeHtml(text)}</div>`;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
    hideTypingIndicator();
}

function addUserMessage(text) {
    const container = document.getElementById('demo-chat-messages');
    if (!container) return;
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble user';
    bubble.innerHTML = `<div class="bubble-content">${escapeHtml(text)}</div>`;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
}

function addSystemMessage(text) {
    const container = document.getElementById('demo-chat-messages');
    if (!container) return;
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble system';
    bubble.innerHTML = `<div class="bubble-content">${escapeHtml(text)}</div>`;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
}

function showTypingIndicator() {
    let indicator = document.getElementById('typing-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'typing-indicator';
        indicator.className = 'chat-bubble robot typing';
        indicator.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
        document.getElementById('demo-chat-messages')?.appendChild(indicator);
    }
    indicator.style.display = '';
    const container = document.getElementById('demo-chat-messages');
    if (container) container.scrollTop = container.scrollHeight;
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) indicator.style.display = 'none';
}

function handleSend() {
    const input = document.getElementById('demo-chat-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

    ws.send(JSON.stringify({ type: 'text', content: text }));
    addUserMessage(text);
    input.value = '';
    showTypingIndicator();
}

// ─── Mode Toggle ─────────────────────────────────────
async function handleModeToggle() {
    const modeToggle = document.getElementById('mode-toggle');
    const newMode = modeToggle.checked ? 'live' : 'text';

    // Disconnect current session
    disconnectWebSocket();

    // Update mode setting on server
    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_mode: newMode }),
        });
    } catch (e) {
        console.error('Failed to update mode:', e);
    }

    currentMode = newMode;
    updateModeLabel();
    updateModeUI();

    // Reconnect with new mode
    setTimeout(connectWebSocket, 500);
}

function updateModeLabel() {
    const label = document.getElementById('mode-label');
    if (label) {
        label.textContent = currentMode === 'live' ? 'Live' : 'Text';
    }
}

function updateModeUI() {
    const micBtn = document.getElementById('btn-demo-mic');
    if (micBtn) {
        micBtn.style.display = currentMode === 'live' ? '' : 'none';
    }
}

// ─── Quick Actions ───────────────────────────────────
function setupQuickActions() {
    const container = document.getElementById('demo-quick-actions');
    if (!container) return;

    const actions = settings.exhibition_quick_actions || [
        { label: '導覽', command: '帶我去參觀' },
        { label: '送飲料', command: '幫我送飲料' },
        { label: '開始巡檢', command: '開始巡檢' },
        { label: '查看報告', action: 'show_history' },
    ];

    container.innerHTML = '';
    for (const action of actions) {
        const btn = document.createElement('button');
        btn.className = 'quick-action-btn';
        btn.textContent = action.label;
        btn.addEventListener('click', () => {
            if (action.action === 'show_history') {
                // Toggle patrol panel
                const panel = document.getElementById('demo-patrol-panel');
                if (panel) panel.classList.toggle('expanded');
            } else if (action.command) {
                // Send as chat message
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'text', content: action.command }));
                    addUserMessage(action.command);
                    showTypingIndicator();
                }
            }
        });
        container.appendChild(btn);
    }
}

// ─── Status Polling ──────────────────────────────────
async function pollStatus() {
    try {
        const res = await fetch('/api/state');
        if (res.ok) {
            const data = await res.json();
            // Update battery
            const batteryEl = document.getElementById('demo-battery');
            if (batteryEl) {
                batteryEl.textContent = `${data.battery || 0}%`;
            }
            // Update state for map
            state.robotPose = data.pose || { x: 0, y: 0, theta: 0 };
            if (data.map_info) state.mapInfo = data.map_info;
        }
    } catch (e) {
        // Silent fail for polling
    }
}

function updateConnectionUI(connected) {
    const indicator = document.getElementById('demo-connection-status');
    if (indicator) {
        indicator.classList.toggle('connected', connected);
    }
    const input = document.getElementById('demo-chat-input');
    if (input) input.disabled = !connected;
    const sendBtn = document.getElementById('btn-demo-send');
    if (sendBtn) sendBtn.disabled = !connected;

    updateModeUI();
}

// ─── Exports for sub-modules ─────────────────────────
export function getWebSocket() { return ws; }
export function getMode() { return currentMode; }
export function getSettings() { return settings; }
export { addBotMessage, addUserMessage, addSystemMessage, showTypingIndicator, hideTypingIndicator };

// ─── Start ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
