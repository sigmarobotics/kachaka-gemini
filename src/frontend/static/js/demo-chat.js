// demo-chat.js — Audio handling for demo page
import { getWebSocket, getMode } from './app.js';

const SAMPLE_RATE_INPUT = 16000;
const SAMPLE_RATE_OUTPUT = 24000;

let audioContext = null;
let mediaStream = null;
let workletNode = null;
let workletBuffer = [];
let workletBufferLength = 0;
let isMicActive = false;
let micMuted = false; // exhibition mode: mute mic while AI is speaking

// Audio playback
let playbackCtx = null;
let nextPlayTime = 0;

// Amplitude callback for waveform overlay
let onPlaybackAmplitude = null;
let onMicAmplitude = null;

export function initDemoChat() {
    const micBtn = document.getElementById('btn-demo-mic');
    if (micBtn) {
        micBtn.addEventListener('click', toggleMic);
    }
}

// ─── Mic Controls ────────────────────────────────────
export async function startMic() {
    if (isMicActive) return;
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

        if (audioContext.audioWorklet) {
            await audioContext.audioWorklet.addModule('/static/js/pcm-processor.js');
            workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');
            workletBuffer = [];
            workletBufferLength = 0;

            workletNode.port.onmessage = (e) => {
                const ws = getWebSocket();
                if (!isMicActive || !ws || ws.readyState !== WebSocket.OPEN) return;
                const float32Chunk = e.data;

                // Forward amplitude for waveform (even when muted)
                if (onMicAmplitude) {
                    let sum = 0;
                    for (let i = 0; i < float32Chunk.length; i++) {
                        sum += Math.abs(float32Chunk[i]);
                    }
                    onMicAmplitude(sum / float32Chunk.length);
                }

                // Exhibition mode: skip sending audio while AI is speaking
                if (micMuted) return;

                workletBuffer.push(float32Chunk);
                workletBufferLength += float32Chunk.length;

                if (workletBufferLength >= 4096) {
                    const merged = new Float32Array(workletBufferLength);
                    let offset = 0;
                    for (const chunk of workletBuffer) {
                        merged.set(chunk, offset);
                        offset += chunk.length;
                    }
                    workletBuffer = [];
                    workletBufferLength = 0;

                    const pcm16 = float32ToPcm16(merged);
                    const b64 = arrayBufferToBase64(pcm16.buffer);
                    ws.send(JSON.stringify({ type: 'audio', data: b64 }));
                }
            };

            source.connect(workletNode);
            workletNode.connect(audioContext.destination);
        }

        isMicActive = true;
        updateMicUI(true);
    } catch (e) {
        console.error('Failed to start mic:', e);
    }
}

export function stopMic() {
    isMicActive = false;
    updateMicUI(false);

    if (workletNode) {
        workletNode.disconnect();
        workletNode = null;
    }
    workletBuffer = [];
    workletBufferLength = 0;
    if (mediaStream) {
        mediaStream.getTracks().forEach(t => t.stop());
        mediaStream = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
}

function toggleMic() {
    if (isMicActive) {
        stopMic();
    } else {
        startMic();
    }
}

function updateMicUI(active) {
    const micBtn = document.getElementById('btn-demo-mic');
    if (micBtn) {
        micBtn.classList.toggle('active', active);
    }
}

// ─── Audio Playback ──────────────────────────────────
export function playAudioChunk(base64Data) {
    if (!playbackCtx) {
        playbackCtx = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: SAMPLE_RATE_OUTPUT,
        });
        nextPlayTime = 0;
    }

    const raw = atob(base64Data);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) {
        bytes[i] = raw.charCodeAt(i);
    }

    // Decode PCM16 LE to Float32
    const pcm16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
        float32[i] = pcm16[i] / 32768.0;
    }

    // Calculate amplitude for waveform
    if (onPlaybackAmplitude) {
        let sum = 0;
        for (let i = 0; i < float32.length; i++) {
            sum += Math.abs(float32[i]);
        }
        onPlaybackAmplitude(sum / float32.length);
    }

    // Schedule playback
    const buffer = playbackCtx.createBuffer(1, float32.length, SAMPLE_RATE_OUTPUT);
    buffer.copyToChannel(float32, 0);

    const source = playbackCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(playbackCtx.destination);

    const now = playbackCtx.currentTime;
    if (nextPlayTime < now) {
        nextPlayTime = now;
    }
    source.start(nextPlayTime);
    nextPlayTime += buffer.duration;
}

export function stopPlayback() {
    if (playbackCtx) {
        playbackCtx.close();
        playbackCtx = null;
    }
    nextPlayTime = 0;
}

/** Returns milliseconds until all scheduled audio finishes playing. */
export function getPlaybackRemainingMs() {
    if (!playbackCtx) return 0;
    return Math.max(0, (nextPlayTime - playbackCtx.currentTime) * 1000);
}

// ─── Amplitude callbacks ─────────────────────────────
export function setOnPlaybackAmplitude(cb) {
    onPlaybackAmplitude = cb;
}

export function setOnMicAmplitude(cb) {
    onMicAmplitude = cb;
}

export function isMicRecording() {
    return isMicActive;
}

export function muteMic() {
    micMuted = true;
    workletBuffer = [];
    workletBufferLength = 0;
}

export function unmuteMic() {
    micMuted = false;
}

// ─── PCM Utils ───────────────────────────────────────
function float32ToPcm16(float32) {
    const pcm16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
        let s = Math.max(-1, Math.min(1, float32[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return pcm16;
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}
