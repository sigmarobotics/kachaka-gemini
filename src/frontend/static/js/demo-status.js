// demo-status.js — Robot status and mini-map for demo page
import state from './state.js';

let mapImage = null;
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

async function loadMap() {
    try {
        const img = new Image();
        img.onload = () => {
            mapImage = img;
            if (mapCanvas) {
                mapCanvas.width = mapCanvas.parentElement?.clientWidth || 300;
                mapCanvas.height = mapCanvas.parentElement?.clientHeight || 200;
            }
        };
        img.src = '/api/map';
    } catch (e) {
        console.error('Failed to load map:', e);
    }
}

function renderLoop() {
    renderMap();
    animFrameId = requestAnimationFrame(renderLoop);
}

function renderMap() {
    if (!mapCtx || !mapCanvas) return;
    const w = mapCanvas.width;
    const h = mapCanvas.height;

    mapCtx.clearRect(0, 0, w, h);

    if (!mapImage) {
        mapCtx.fillStyle = '#f0f0f0';
        mapCtx.fillRect(0, 0, w, h);
        mapCtx.fillStyle = '#999';
        mapCtx.font = '14px system-ui';
        mapCtx.textAlign = 'center';
        mapCtx.fillText('地圖載入中...', w / 2, h / 2);
        return;
    }

    // Draw map scaled to fit
    const scale = Math.min(w / mapImage.width, h / mapImage.height);
    const mw = mapImage.width * scale;
    const mh = mapImage.height * scale;
    const mx = (w - mw) / 2;
    const my = (h - mh) / 2;
    mapCtx.drawImage(mapImage, mx, my, mw, mh);

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
            const indicator = document.getElementById('connection-status');
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
