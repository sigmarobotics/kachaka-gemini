// app.js — Entry point, tab switching
import { initMap, startPolling } from './map.js';
import { initChat } from './chat.js';
import { initSettings } from './settings.js';

// Tab switching
window.switchTab = function (tabName) {
    document.querySelectorAll('.tab-content').forEach((el) => {
        el.style.display = 'none';
    });
    document.querySelectorAll('.tab-btn').forEach((el) => {
        el.classList.remove('active');
    });

    const view = document.getElementById(`view-${tabName}`);
    if (view) view.style.display = '';

    document.querySelectorAll('.tab-btn').forEach((el) => {
        if (el.dataset.tab === tabName) el.classList.add('active');
    });
};

// Manual control
window.manualControl = function (direction) {
    fetch('/api/manual_control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction }),
    }).catch((e) => console.error('Manual control failed:', e));
};

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // Button handlers
    const homeBtn = document.getElementById('btn-home');
    const cancelBtn = document.getElementById('btn-cancel-command');

    if (homeBtn) {
        homeBtn.addEventListener('click', () => {
            fetch('/api/return_home', { method: 'POST' }).catch(console.error);
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            fetch('/api/cancel_command', { method: 'POST' }).catch(console.error);
        });
    }

    // Init modules
    initMap();
    startPolling();
    initChat();
    initSettings();

    // Default tab is Chat
    switchTab('chat');
});
