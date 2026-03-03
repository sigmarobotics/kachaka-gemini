// app.js — Unified entry point (merges demo-app.js logic + dev toolbar from chat.js)
import { initSettings } from './settings.js';
import state, { escapeHtml } from './state.js';
import { initDemoChat, startMic, stopMic, isMicRecording, playAudioChunk, stopPlayback, getPlaybackRemainingMs, setOnPlaybackAmplitude, setOnMicAmplitude, muteMic, unmuteMic } from './demo-chat.js';
import { initDemoStatus } from './demo-status.js';
import { initDemoPatrol } from './demo-patrol.js';
import { initDemoVoice, showListening, showSpeaking, hide as hideWaveform, onMicAmplitude, onPlaybackAmplitude } from './demo-voice.js';
import { initFiles } from './files.js';

let ws = null;
let isConnected = false;
let currentMode = 'text'; // 'text' or 'live'
let statusPollInterval = null;
let settings = {};
let sessionTokenTotal = 0;

// ─── Tab Switching ───────────────────────────────────
window.switchTab = function(tabName) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    const view = document.getElementById(`view-${tabName}`);
    if (view) view.style.display = '';
    document.querySelectorAll('.tab-btn').forEach(el => {
        if (el.dataset.tab === tabName) el.classList.add('active');
    });
};

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

    // Initialize sub-modules
    initDemoChat();
    initDemoVoice();
    initDemoStatus();
    initDemoPatrol();
    initSettings();
    initFiles();

    // Override mic button to orchestrate waveform overlay
    // (must be after initDemoChat which adds its own listener)
    const micBtn = document.getElementById('btn-demo-mic');
    if (micBtn) {
        const newMicBtn = micBtn.cloneNode(true);
        micBtn.parentNode.replaceChild(newMicBtn, micBtn);
        newMicBtn.addEventListener('click', handleMicToggle);
    }

    // Wire amplitude callbacks: demo-chat -> demo-voice waveform
    setOnMicAmplitude(onMicAmplitude);
    setOnPlaybackAmplitude(onPlaybackAmplitude);

    // Wire voice-stop event (from waveform overlay stop button)
    // Exits live mode entirely and switches back to text
    window.addEventListener('voice-stop', () => {
        stopMic();
        stopPlayback();
        hideWaveform();
        switchToTextMode();
    });

    // Wire interrupt button (manual interrupt for noisy environments)
    const interruptBtn = document.getElementById('btn-waveform-interrupt');
    if (interruptBtn) {
        interruptBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'interrupt' }));
            }
            stopPlayback();
            showListening();
        });
    }

    // Wire dev toolbar buttons
    document.getElementById('btn-clear-chat')?.addEventListener('click', clearChat);
    document.getElementById('btn-export-chat')?.addEventListener('click', exportChat);

    // Start status polling
    statusPollInterval = setInterval(pollStatus, 2000);
    pollStatus(); // immediate first poll

    // Auto-connect WebSocket
    connectWebSocket();

    // Default to Demo tab
    switchTab('demo');
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

// ─── Message Handling ────────────────────────────────
function handleMessage(msg) {
    switch (msg.type) {
        case 'status':
            if (msg.message && msg.message.includes('Connected to Gemini')) {
                isConnected = true;
                if (msg.api_mode) currentMode = msg.api_mode;
                updateConnectionUI(true);
                addSystemMessage('已連接 Gemini ✓');
                // Auto-start mic when connected in live mode
                if (currentMode === 'live' && !isMicRecording()) {
                    startMic();
                    showListening();
                }
            } else {
                addSystemMessage(msg.message || '');
            }
            break;

        case 'text':
            addBotMessage(msg.content || '');
            break;

        case 'audio':
            // Play audio and show speaking waveform
            showSpeaking();
            playAudioChunk(msg.data);
            updateInterruptBtn(true);
            // Exhibition mode: mute mic while AI is speaking
            if (settings.live_auto_interrupt === false) {
                muteMic();
                showExhibitionMute(true);
            }
            break;

        case 'interrupted':
            // User interrupted AI — stop playback, resume listening
            stopPlayback();
            updateInterruptBtn(false);
            if (settings.live_auto_interrupt === false) {
                unmuteMic();
                showExhibitionMute(false);
            }
            if (currentMode === 'live') showListening();
            break;

        case 'function_call':
            addSystemMessage(`執行中: ${msg.name || ''}...`);
            break;

        case 'function_result':
            // Gemini will summarize; no direct display needed
            break;

        case 'turn_complete':
            hideTypingIndicator();
            updateInterruptBtn(false);
            if (currentMode === 'live') {
                // Let queued audio finish playing naturally before unmuting mic.
                const remainMs = getPlaybackRemainingMs();
                if (settings.live_auto_interrupt === false && remainMs > 0) {
                    setTimeout(() => {
                        unmuteMic();
                        showExhibitionMute(false);
                        showListening();
                    }, remainMs + 200);  // +200ms buffer
                } else {
                    if (settings.live_auto_interrupt === false) {
                        unmuteMic();
                        showExhibitionMute(false);
                    }
                    showListening();
                }
            } else {
                hideWaveform();
            }
            break;

        case 'error':
            addSystemMessage(`錯誤: ${msg.message || ''}`);
            break;

        case 'token_usage':
            sessionTokenTotal += msg.total || 0;
            updateSessionTokenDisplay();
            break;

        case 'patrol_started':
            addSystemMessage('巡檢已啟動');
            break;

        case 'gemini_disconnected':
            isConnected = false;
            updateConnectionUI(false);
            addSystemMessage('Gemini 連線已中斷，正在重新連接...');
            stopPlayback();
            hideWaveform();
            // Auto-reconnect
            setTimeout(connectWebSocket, 2000);
            break;

        case 'history_cleared':
            // Server confirmed history clear
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

// ─── Exhibition Mode Mute Indicator ─────────────────
function showExhibitionMute(muted) {
    let el = document.getElementById('exhibition-mute-indicator');
    if (!el) {
        el = document.createElement('div');
        el.id = 'exhibition-mute-indicator';
        el.className = 'exhibition-mute-indicator';
        el.textContent = '展場模式：AI 回應中，麥克風已靜音';
        document.body.appendChild(el);
    }
    el.style.display = muted ? '' : 'none';
}

// ─── Interrupt Button ────────────────────────────────
function updateInterruptBtn(speaking) {
    const btn = document.getElementById('btn-waveform-interrupt');
    if (!btn) return;
    // Show interrupt button when AI is speaking AND auto-interrupt is off
    const autoInterrupt = settings.live_auto_interrupt !== false;
    btn.style.display = (speaking && !autoInterrupt) ? '' : 'none';
}

// ─── Mic Toggle (orchestrates audio + waveform) ─────
function handleMicToggle() {
    if (isMicRecording()) {
        stopMic();
        stopPlayback();
        hideWaveform();
    } else {
        startMic();
        showListening();
    }
}

// ─── Mode Switching ──────────────────────────────────
async function switchMode(newMode) {
    // Stop mic/playback if leaving live
    if (currentMode === 'live' && newMode !== 'live') {
        stopMic();
        stopPlayback();
        hideWaveform();
        unmuteMic();
        showExhibitionMute(false);
    }

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

    // Sync toggle checkbox
    const toggle = document.getElementById('mode-toggle');
    if (toggle) toggle.checked = newMode === 'live';

    // Reconnect with new mode
    setTimeout(connectWebSocket, 500);
    // Auto-start mic is handled in the 'status' connected handler
}

async function handleModeToggle() {
    const modeToggle = document.getElementById('mode-toggle');
    const newMode = modeToggle.checked ? 'live' : 'text';
    await switchMode(newMode);
}

function switchToTextMode() {
    switchMode('text');
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
                window.open('/demo/patrol', '_blank');
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
            // Update header battery display
            const headerBattery = document.getElementById('battery-value');
            if (headerBattery) {
                headerBattery.textContent = `${data.battery || 0}%`;
            }
            // Update state for map
            state.robotPose = data.pose || { x: 0, y: 0, theta: 0 };
            if (data.map_info) state.mapInfo = data.map_info;
        }
    } catch (e) {
        // Silent fail for polling
    }
}

// ─── Connection UI ───────────────────────────────────
function updateConnectionUI(connected) {
    // Update header Gemini status light
    const geminiStatus = document.getElementById('gemini-status');
    if (geminiStatus) {
        geminiStatus.classList.toggle('connected', connected);
    }
    const input = document.getElementById('demo-chat-input');
    if (input) input.disabled = !connected;
    const sendBtn = document.getElementById('btn-demo-send');
    if (sendBtn) sendBtn.disabled = !connected;

    updateModeUI();
}

// ─── Dev Toolbar ─────────────────────────────────────
function clearChat() {
    if (!confirm('Clear chat history? This cannot be undone.')) return;

    // Send to backend if connected (clears server-side history)
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'clear_history' }));
    }

    // Clear frontend
    const messagesDiv = document.getElementById('demo-chat-messages');
    if (messagesDiv) {
        messagesDiv.innerHTML = '';
        addSystemMessage('Chat history cleared.');
    }
    sessionTokenTotal = 0;
    updateSessionTokenDisplay();
}

function exportChat() {
    const messagesDiv = document.getElementById('demo-chat-messages');
    if (!messagesDiv) return;

    const messages = [];
    messagesDiv.querySelectorAll('.chat-bubble').forEach(el => {
        let role = 'system';
        if (el.classList.contains('user')) role = 'user';
        else if (el.classList.contains('robot')) role = 'model';

        const content = el.querySelector('.bubble-content')?.textContent || el.textContent || '';
        messages.push({ role, content, timestamp: new Date().toISOString() });
    });

    const blob = new Blob([JSON.stringify(messages, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const now = new Date();
    const ts = now.toISOString().slice(0, 16).replace('T', '-').replace(':', '');
    a.href = url;
    a.download = `chat-export-${ts}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

function updateSessionTokenDisplay() {
    const el = document.getElementById('session-tokens');
    if (el) el.textContent = `Tokens: ${sessionTokenTotal.toLocaleString()}`;
}

// ─── Exports for sub-modules ─────────────────────────
export function getWebSocket() { return ws; }
export function getMode() { return currentMode; }
export function getSettings() { return settings; }
export { addBotMessage, addUserMessage, addSystemMessage, showTypingIndicator, hideTypingIndicator };

// ─── Start ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
