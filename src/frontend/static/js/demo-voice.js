// demo-voice.js — Full-screen waveform overlay for demo page

let canvas = null;
let ctx = null;
let overlay = null;
let statusEl = null;
let animFrameId = null;
let isActive = false;
let currentState = 'hidden'; // hidden, listening, speaking
let currentAmplitude = 0;
let targetAmplitude = 0;
let wavePhase = 0;
let fadeOpacity = 0;

// Waveform history for smooth animation
const amplitudeHistory = new Array(64).fill(0);
let historyIndex = 0;

export function initDemoVoice() {
    overlay = document.getElementById('waveform-overlay');
    canvas = document.getElementById('waveform-canvas');
    statusEl = document.getElementById('waveform-status');

    if (!canvas || !overlay) return;
    ctx = canvas.getContext('2d');

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    // Stop button
    const stopBtn = overlay.querySelector('.stop-btn');
    if (stopBtn) {
        stopBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            hide();
            window.dispatchEvent(new CustomEvent('voice-stop'));
        });
    }
}

function resizeCanvas() {
    if (!canvas) return;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}

// ─── Public API ──────────────────────────────────────

export function showListening() {
    currentState = 'listening';
    isActive = true;
    fadeOpacity = 1;
    if (overlay) overlay.classList.add('active');
    if (statusEl) statusEl.textContent = '聆聽中...';
    startAnimation();
}

export function showSpeaking() {
    currentState = 'speaking';
    isActive = true;
    fadeOpacity = 1;
    if (overlay) overlay.classList.add('active');
    if (statusEl) statusEl.textContent = '回覆中...';
    startAnimation();
}

export function hide() {
    currentState = 'hidden';
    isActive = false;
    const fadeOut = () => {
        fadeOpacity -= 0.05;
        if (fadeOpacity <= 0) {
            fadeOpacity = 0;
            if (overlay) overlay.classList.remove('active');
            stopAnimation();
            return;
        }
        requestAnimationFrame(fadeOut);
    };
    fadeOut();
}

export function onMicAmplitude(amplitude) {
    if (currentState === 'listening') {
        targetAmplitude = Math.min(1, amplitude * 8);
    }
}

export function onPlaybackAmplitude(amplitude) {
    if (currentState === 'speaking') {
        targetAmplitude = Math.min(1, amplitude * 8);
    }
}

// ─── Animation ───────────────────────────────────────

function startAnimation() {
    if (animFrameId) return;
    animFrameId = requestAnimationFrame(animate);
}

function stopAnimation() {
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }
}

function animate() {
    if (!ctx || !canvas) return;

    // Smooth amplitude interpolation
    currentAmplitude += (targetAmplitude - currentAmplitude) * 0.15;
    targetAmplitude *= 0.95; // Decay

    // Store in history
    amplitudeHistory[historyIndex] = currentAmplitude;
    historyIndex = (historyIndex + 1) % amplitudeHistory.length;

    wavePhase += 0.03;

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    drawWaveform(w, h);

    if (isActive || fadeOpacity > 0) {
        animFrameId = requestAnimationFrame(animate);
    } else {
        animFrameId = null;
    }
}

function drawWaveform(w, h) {
    const centerY = h / 2;
    const maxAmplitude = h * 0.3;

    const layers = [
        { color: 'rgba(255, 120, 60, 0.6)', amplitude: 1.0, frequency: 1.0, speed: 1.0, lineWidth: 3 },
        { color: 'rgba(255, 160, 80, 0.4)', amplitude: 0.7, frequency: 1.5, speed: 0.8, lineWidth: 2 },
        { color: 'rgba(255, 200, 120, 0.3)', amplitude: 0.5, frequency: 2.0, speed: 1.2, lineWidth: 1.5 },
    ];

    for (const layer of layers) {
        const points = [];
        const segments = 100;
        for (let i = 0; i <= segments; i++) {
            const x = (i / segments) * w;
            const t = (i / segments) * Math.PI * 4 * layer.frequency;
            const histIdx = Math.floor((i / segments) * amplitudeHistory.length);
            const histAmp = amplitudeHistory[(historyIndex + histIdx) % amplitudeHistory.length];
            const amp = (currentAmplitude * 0.6 + histAmp * 0.4) * layer.amplitude;
            const y = centerY + Math.sin(t + wavePhase * layer.speed) * amp * maxAmplitude;
            points.push({ x, y });
        }

        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 0; i < points.length - 1; i++) {
            const xc = (points[i].x + points[i + 1].x) / 2;
            const yc = (points[i].y + points[i + 1].y) / 2;
            ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
        }

        ctx.strokeStyle = layer.color;
        ctx.lineWidth = layer.lineWidth;
        ctx.stroke();
    }
}

export function cleanup() {
    stopAnimation();
}
