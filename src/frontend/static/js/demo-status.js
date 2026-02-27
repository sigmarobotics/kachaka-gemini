// demo-status.js — Robot status and mini-map for demo page
import state from './state.js';

let mapImage = null;
let mapDarkCanvas = null; // offscreen canvas with inverted map
let mapCanvas = null;
let mapCtx = null;
let animFrameId = null;

export function initDemoStatus() {
    mapCanvas = document.getElementById('demo-map-canvas');
    if (!mapCanvas) return;
    mapCtx = mapCanvas.getContext('2d');

    // Load map image
    loadMap();

    // Start render loop
    renderLoop();

    // Poll connection status
    setInterval(pollConnectionStatus, 3000);
    pollConnectionStatus();
}

function loadMap() {
    const img = new Image();
    img.onload = () => {
        mapImage = img;
        // Pre-render inverted (dark theme) map into offscreen canvas
        mapDarkCanvas = document.createElement('canvas');
        mapDarkCanvas.width = img.width;
        mapDarkCanvas.height = img.height;
        const ctx = mapDarkCanvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        const imageData = ctx.getImageData(0, 0, img.width, img.height);
        const d = imageData.data;
        for (let i = 0; i < d.length; i += 4) {
            d[i]     = 255 - d[i];     // R
            d[i + 1] = 255 - d[i + 1]; // G
            d[i + 2] = 255 - d[i + 2]; // B
        }
        ctx.putImageData(imageData, 0, 0);

        if (mapCanvas) {
            mapCanvas.width = mapCanvas.parentElement?.clientWidth || 300;
            mapCanvas.height = mapCanvas.parentElement?.clientHeight || 200;
        }
    };
    img.onerror = () => {
        console.warn('Map load failed, retrying in 3s...');
        setTimeout(loadMap, 3000);
    };
    img.src = '/api/map?t=' + Date.now();
}

function renderLoop() {
    renderMap();
    animFrameId = requestAnimationFrame(renderLoop);
}

function renderMap() {
    if (!mapCtx || !mapCanvas) return;
    const w = mapCanvas.width;
    const h = mapCanvas.height;

    // Dark background
    mapCtx.fillStyle = '#1a1a2e';
    mapCtx.fillRect(0, 0, w, h);

    if (!mapDarkCanvas) {
        mapCtx.fillStyle = '#888';
        mapCtx.font = '14px system-ui';
        mapCtx.textAlign = 'center';
        mapCtx.fillText('地圖載入中...', w / 2, h / 2);
        return;
    }

    // Draw inverted map from offscreen canvas
    const srcW = mapDarkCanvas.width;
    const srcH = mapDarkCanvas.height;
    const scale = Math.min(w / srcW, h / srcH);
    const mw = srcW * scale;
    const mh = srcH * scale;
    const mx = (w - mw) / 2;
    const my = (h - mh) / 2;
    mapCtx.drawImage(mapDarkCanvas, mx, my, mw, mh);

    // Draw robot position
    const info = state.mapInfo;
    const pose = state.robotPose;
    if (info && pose && info.resolution > 0) {
        const px = mx + ((pose.x - info.origin_x) / info.resolution) * scale;
        const py = my + (mh - ((pose.y - info.origin_y) / info.resolution) * scale);

        // Robot dot
        mapCtx.beginPath();
        mapCtx.arc(px, py, 6, 0, Math.PI * 2);
        mapCtx.fillStyle = '#FF7043';
        mapCtx.fill();
        mapCtx.strokeStyle = '#fff';
        mapCtx.lineWidth = 2;
        mapCtx.stroke();

        // Direction indicator
        const dirLen = 12;
        const dirX = px + Math.cos(-pose.theta) * dirLen;
        const dirY = py + Math.sin(-pose.theta) * dirLen;
        mapCtx.beginPath();
        mapCtx.moveTo(px, py);
        mapCtx.lineTo(dirX, dirY);
        mapCtx.strokeStyle = '#FF7043';
        mapCtx.lineWidth = 2;
        mapCtx.stroke();
    }
}

async function pollConnectionStatus() {
    try {
        const res = await fetch('/api/robot/status');
        if (res.ok) {
            const data = await res.json();
            const indicator = document.getElementById('demo-connection-status');
            if (indicator) {
                indicator.classList.toggle('connected', data.connected);
                indicator.title = data.connected ? `Connected: ${data.ip}` : 'Disconnected';
            }
        }
    } catch (e) {
        // Silent fail
    }
}

export function cleanup() {
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }
}
