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

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // Init modules
    initMap();
    startPolling();
    initChat();
    initSettings();

    // Default tab is Chat
    switchTab('chat');
});
