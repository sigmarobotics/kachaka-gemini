// chat.js — WebSocket chat + audio handling for Gemini Live API
import { escapeHtml } from './state.js';

let ws = null;
let isConnected = false;
let isMicActive = false;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let currentModelText = '';
let currentResponseMode = 'audio';
let sessionTokenTotal = 0;

// Audio playback: single AudioContext, schedule chunks on timeline
let playbackCtx = null;
let nextPlayTime = 0;

const SAMPLE_RATE_INPUT = 16000;
const SAMPLE_RATE_OUTPUT = 24000;

export function initChat() {
    const connectBtn = document.getElementById('btn-connect');
    const sendBtn = document.getElementById('btn-send');
    const micBtn = document.getElementById('btn-mic');
    const chatInput = document.getElementById('chat-input');

    connectBtn.addEventListener('click', toggleConnection);
    sendBtn.addEventListener('click', sendTextMessage);
    micBtn.addEventListener('click', toggleMic);

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendTextMessage();
        }
    });
}

function toggleConnection() {
    if (isConnected) {
        disconnect();
    } else {
        connect();
    }
}

async function connect() {
    // Load interim response audio before connecting
    try {
        const res = await fetch('/api/interim_audio');
        if (res.ok) {
            const data = await res.json();
            updateInterimSettings(data);
        }
    } catch (e) {
        console.error('Failed to load interim settings:', e);
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);

    ws.onopen = () => {
        appendSystemMessage('Connecting to Gemini...');
        ws.send(JSON.stringify({ type: 'connect' }));
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            // Mark as connected when Gemini session is ready
            if (msg.type === 'status' && msg.message && msg.message.includes('Connected to Gemini')) {
                if (msg.response_mode) {
                    currentResponseMode = msg.response_mode;
                }
                sessionTokenTotal = 0;
                updateSessionTokenDisplay();
                updateConnectionUI(true);
            }
            handleServerMessage(msg);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
    };

    ws.onclose = () => {
        updateConnectionUI(false);
        stopMic();
    };

    ws.onerror = () => {
        appendSystemMessage('WebSocket connection error — is the server running?');
    };
}

function disconnect() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'disconnect' }));
    }
    stopMic();
    if (ws) {
        ws.close();
        ws = null;
    }
    updateConnectionUI(false);
}

function updateConnectionUI(connected) {
    isConnected = connected;
    const connectBtn = document.getElementById('btn-connect');
    const micBtn = document.getElementById('btn-mic');
    const sendBtn = document.getElementById('btn-send');
    const chatInput = document.getElementById('chat-input');
    const statusDot = document.getElementById('gemini-status');

    if (connected) {
        connectBtn.textContent = 'Disconnect';
        connectBtn.classList.add('connected');
        if (statusDot) statusDot.classList.add('connected');
    } else {
        connectBtn.textContent = 'Connect';
        connectBtn.classList.remove('connected');
        if (statusDot) statusDot.classList.remove('connected');
    }

    // In text mode, hide the mic button
    const isTextMode = currentResponseMode === 'text';
    micBtn.disabled = !connected || isTextMode;
    micBtn.style.display = isTextMode ? 'none' : '';
    sendBtn.disabled = !connected;
    chatInput.disabled = !connected;
}

function sendTextMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

    ws.send(JSON.stringify({ type: 'text', content: text }));
    appendMessage('user', text);
    input.value = '';
}

// ─── Mic / Audio Input ───────────────────────────────────────────────────────

async function toggleMic() {
    if (isMicActive) {
        stopMic();
    } else {
        await startMic();
    }
}

async function startMic() {
    try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: SAMPLE_RATE_INPUT,
        });

        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: SAMPLE_RATE_INPUT,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
            },
        });

        const source = audioContext.createMediaStreamSource(mediaStream);

        // Use ScriptProcessorNode for PCM capture
        // Buffer size 4096 gives ~256ms at 16kHz
        scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
        scriptProcessor.onaudioprocess = (e) => {
            if (!isMicActive || !ws || ws.readyState !== WebSocket.OPEN) return;
            const float32 = e.inputBuffer.getChannelData(0);
            const pcm16 = float32ToPcm16(float32);
            const b64 = arrayBufferToBase64(pcm16.buffer);
            ws.send(JSON.stringify({ type: 'audio', data: b64 }));
        };

        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);

        isMicActive = true;
        updateMicUI(true);
    } catch (e) {
        console.error('Failed to start mic:', e);
        appendSystemMessage('Microphone access denied or unavailable');
    }
}

function stopMic() {
    isMicActive = false;
    updateMicUI(false);

    if (scriptProcessor) {
        scriptProcessor.disconnect();
        scriptProcessor = null;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
        mediaStream = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
}

function updateMicUI(active) {
    const micBtn = document.getElementById('btn-mic');
    if (active) {
        micBtn.classList.add('active');
        micBtn.textContent = 'Mic ON';
    } else {
        micBtn.classList.remove('active');
        micBtn.textContent = 'Mic';
    }
}

// ─── Audio Playback ──────────────────────────────────────────────────────────
// Uses a single AudioContext and schedules chunks on the audio timeline
// so they play gaplessly back-to-back.

function ensurePlaybackCtx() {
    if (!playbackCtx || playbackCtx.state === 'closed') {
        playbackCtx = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: SAMPLE_RATE_OUTPUT,
        });
        nextPlayTime = 0;
    }
    if (playbackCtx.state === 'suspended') {
        playbackCtx.resume();
    }
    return playbackCtx;
}

function scheduleAudioChunk(base64Data) {
    try {
        const ctx = ensurePlaybackCtx();
        const pcmBytes = base64ToArrayBuffer(base64Data);
        const pcm16 = new Int16Array(pcmBytes);
        const float32 = pcm16ToFloat32(pcm16);

        const buffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE_OUTPUT);
        buffer.getChannelData(0).set(float32);

        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);

        // Schedule this chunk right after the previous one ends
        const now = ctx.currentTime;
        const startAt = Math.max(now, nextPlayTime);
        source.start(startAt);
        nextPlayTime = startAt + buffer.duration;
    } catch (e) {
        console.error('Audio playback error:', e);
    }
}

function resetPlayback() {
    // Reset scheduling so next turn starts fresh
    if (playbackCtx) {
        nextPlayTime = 0;
    }
}

// ─── Interim Response (過渡性回覆) ───────────────────────────────────────────
// 當 Function Call 執行時，先播放預先生成的語音讓使用者知道系統在處理

let interimSettings = {
    enabled: false,
    audio: {},       // { function_name: base64_pcm_data }
    phrases: {},     // { function_name: text } (fallback)
};

export function updateInterimSettings(data) {
    interimSettings.enabled = data.enabled || false;
    interimSettings.audio = data.audio || {};
    interimSettings.phrases = data.phrases || {};
}

function playInterimResponse(functionName) {
    if (!interimSettings.enabled) return;

    // Try pre-generated audio first (same voice as Gemini)
    const audioData = interimSettings.audio[functionName];
    if (audioData) {
        playInterimAudioChunk(audioData);
        return;
    }

    // Fallback: Web Speech API
    const text = interimSettings.phrases[functionName]
        || interimSettings.phrases.default
        || '好的，請稍候';

    if ('speechSynthesis' in window) {
        speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'zh-TW';
        utterance.rate = 1.1;
        utterance.pitch = 1.0;

        const voices = speechSynthesis.getVoices();
        const zhVoice = voices.find(v => v.lang.startsWith('zh'));
        if (zhVoice) utterance.voice = zhVoice;

        speechSynthesis.speak(utterance);
    }
}

function playInterimAudioChunk(base64Data) {
    try {
        const ctx = ensurePlaybackCtx();
        const pcmBytes = base64ToArrayBuffer(base64Data);
        const pcm16 = new Int16Array(pcmBytes);
        const float32 = pcm16ToFloat32(pcm16);

        const buffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE_OUTPUT);
        buffer.getChannelData(0).set(float32);

        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);

        // Play immediately (overrides any scheduled playback)
        const now = ctx.currentTime;
        source.start(now);
        // Update nextPlayTime so Gemini's subsequent audio starts after this
        nextPlayTime = now + buffer.duration;
    } catch (e) {
        console.error('Interim audio playback error:', e);
    }
}

// Preload voices for fallback (needed for some browsers)
if ('speechSynthesis' in window) {
    speechSynthesis.getVoices();
    speechSynthesis.onvoiceschanged = () => speechSynthesis.getVoices();
}

// ─── Handle server messages ──────────────────────────────────────────────────

function handleServerMessage(msg) {
    switch (msg.type) {
        case 'text':
            currentModelText += msg.content;
            updateModelMessage(currentModelText);
            break;

        case 'audio':
            scheduleAudioChunk(msg.data);
            break;

        case 'function_call':
            // Play interim response while function executes
            playInterimResponse(msg.name);
            appendSystemMessage(
                `Calling: ${escapeHtml(msg.name)}(${escapeHtml(JSON.stringify(msg.args))})`
            );
            break;

        case 'function_result': {
            const resultStr = typeof msg.result === 'object' ? JSON.stringify(msg.result) : String(msg.result);
            const success = msg.result && msg.result.success !== false;
            appendSystemMessage(
                `${escapeHtml(msg.name)}: ${success ? 'OK' : 'Failed'} — ${escapeHtml(resultStr)}`
            );
            break;
        }

        case 'turn_complete': {
            // Finalize any streaming model message
            const streamingMsg = document.querySelector('.chat-message.model.streaming');
            if (streamingMsg) {
                streamingMsg.classList.remove('streaming');
            }
            currentModelText = '';
            resetPlayback();
            break;
        }

        case 'gemini_disconnected':
            appendSystemMessage(
                `Gemini disconnected (code: ${msg.code}). Reconnecting...`
            );
            stopMic();
            resetPlayback();
            // Auto-reconnect via existing WebSocket
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'connect' }));
            }
            break;

        case 'status':
            appendSystemMessage(msg.message);
            break;

        case 'token_usage':
            sessionTokenTotal += msg.total || 0;
            updateSessionTokenDisplay();
            break;

        case 'error':
            appendSystemMessage(`Error: ${escapeHtml(msg.message)}`, true);
            break;
    }
}

function updateSessionTokenDisplay() {
    const el = document.getElementById('session-tokens');
    if (el) el.textContent = `Tokens: ${sessionTokenTotal.toLocaleString()}`;
}

// ─── Chat UI helpers ─────────────────────────────────────────────────────────

function appendMessage(role, text) {
    const messagesDiv = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `chat-message ${role}`;

    const label = document.createElement('span');
    label.className = 'msg-role';
    label.textContent = role === 'user' ? 'You' : 'AI';

    const content = document.createElement('span');
    content.className = 'msg-content';
    content.textContent = text;

    div.appendChild(label);
    div.appendChild(content);
    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function updateModelMessage(text) {
    const messagesDiv = document.getElementById('chat-messages');
    let existing = messagesDiv.querySelector('.chat-message.model.streaming');

    if (!existing) {
        existing = document.createElement('div');
        existing.className = 'chat-message model streaming';

        const label = document.createElement('span');
        label.className = 'msg-role';
        label.textContent = 'AI';

        const content = document.createElement('span');
        content.className = 'msg-content';

        existing.appendChild(label);
        existing.appendChild(content);
        messagesDiv.appendChild(existing);
    }

    existing.querySelector('.msg-content').textContent = text;
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    // If turn is complete, remove streaming class
    if (!currentModelText) {
        existing.classList.remove('streaming');
    }
}

function appendSystemMessage(text, isError = false) {
    const messagesDiv = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `chat-message system${isError ? ' error' : ''}`;
    div.textContent = text;
    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// ─── Audio conversion utilities ──────────────────────────────────────────────

function float32ToPcm16(float32Array) {
    const pcm16 = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return pcm16;
}

function pcm16ToFloat32(pcm16Array) {
    const float32 = new Float32Array(pcm16Array.length);
    for (let i = 0; i < pcm16Array.length; i++) {
        float32[i] = pcm16Array[i] / 0x8000;
    }
    return float32;
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}

function base64ToArrayBuffer(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}
