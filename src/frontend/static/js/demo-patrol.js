// demo-patrol.js — Patrol history and results for demo page
import { escapeHtml } from './state.js';

let isPatrolActive = false;
let pollInterval = null;

export function initDemoPatrol() {
    // Load initial history
    loadPatrolHistory();

    // Set up patrol panel toggle
    const toggleBtn = document.getElementById('patrol-toggle-btn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            const panel = document.getElementById('demo-patrol-panel');
            if (panel) panel.classList.toggle('expanded');
        });
    }

    // Poll patrol status periodically
    pollInterval = setInterval(checkPatrolStatus, 5000);
}

async function loadPatrolHistory() {
    const listEl = document.getElementById('demo-patrol-list');
    if (!listEl) return;

    try {
        const res = await fetch('/api/patrol/runs?limit=10');
        if (!res.ok) return;
        const data = await res.json();
        const runs = data.runs || [];

        if (runs.length === 0) {
            listEl.innerHTML = '<div class="patrol-empty">尚無巡檢紀錄</div>';
            return;
        }

        listEl.innerHTML = runs.map(run => renderRunCard(run)).join('');

        // Bind detail buttons
        listEl.querySelectorAll('.patrol-detail-btn').forEach(btn => {
            btn.addEventListener('click', () => loadRunDetail(btn.dataset.runId));
        });

        // Bind PDF buttons
        listEl.querySelectorAll('.patrol-pdf-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                window.open(`/api/patrol/runs/${btn.dataset.runId}/pdf`, '_blank');
            });
        });

    } catch (e) {
        console.error('Failed to load patrol history:', e);
        listEl.innerHTML = '<div class="patrol-empty">載入失敗</div>';
    }
}

function renderRunCard(run) {
    const time = run.start_time ? new Date(run.start_time).toLocaleString('zh-TW') : '';
    const statusClass = run.status === 'Completed' ? 'badge-ok' :
                        run.status === 'Running' ? 'badge-running' : 'badge-ng';
    const statusText = run.status === 'Completed' ? '完成' :
                       run.status === 'Running' ? '執行中' :
                       run.status === 'Error' ? '錯誤' : run.status;
    const summary = run.report_content ? escapeHtml(run.report_content.substring(0, 100)) + '...' : '無摘要';

    return `
        <div class="patrol-card" data-run-id="${run.id}">
            <div class="patrol-card-header">
                <span class="patrol-time">${escapeHtml(time)}</span>
                <span class="${statusClass}">${escapeHtml(statusText)}</span>
            </div>
            <div class="patrol-card-body">
                <p class="patrol-summary">${summary}</p>
            </div>
            <div class="patrol-card-actions">
                <button class="patrol-detail-btn" data-run-id="${run.id}">詳細</button>
                <button class="patrol-pdf-btn" data-run-id="${run.id}">PDF 報告</button>
            </div>
            <div class="patrol-detail" id="patrol-detail-${run.id}" style="display:none;"></div>
        </div>
    `;
}

async function loadRunDetail(runId) {
    const detailEl = document.getElementById(`patrol-detail-${runId}`);
    if (!detailEl) return;

    // Toggle visibility
    if (detailEl.style.display !== 'none') {
        detailEl.style.display = 'none';
        return;
    }

    try {
        const res = await fetch(`/api/patrol/runs/${runId}`);
        if (!res.ok) return;
        const data = await res.json();
        const inspections = data.inspections || [];

        detailEl.innerHTML = inspections.map(insp => {
            const badge = insp.is_ng ? '<span class="badge-ng">NG</span>' : '<span class="badge-ok">OK</span>';
            const imgHtml = insp.image_path
                ? `<img src="/api/patrol/report/image/${encodeURI(insp.image_path)}" class="patrol-thumb" alt="inspection">`
                : '';
            return `
                <div class="inspection-card">
                    <div class="inspection-header">
                        <strong>${escapeHtml(insp.point_name)}</strong>
                        ${badge}
                    </div>
                    ${imgHtml}
                    <p class="inspection-desc">${escapeHtml(insp.ai_description || insp.ai_response || '無描述')}</p>
                </div>
            `;
        }).join('');

        // Show video analysis if available
        if (data.run && data.run.video_analysis) {
            detailEl.innerHTML += `
                <div class="video-analysis-card">
                    <h4>影片分析</h4>
                    <p>${escapeHtml(data.run.video_analysis)}</p>
                </div>
            `;
        }

        detailEl.style.display = 'block';
    } catch (e) {
        console.error('Failed to load run detail:', e);
    }
}

async function checkPatrolStatus() {
    try {
        const res = await fetch('/api/patrol/status');
        if (!res.ok) return;
        const data = await res.json();
        const wasActive = isPatrolActive;
        isPatrolActive = data.status !== 'idle' && data.status !== 'completed' && data.status !== 'error';

        // Refresh history when patrol just completed
        if (wasActive && !isPatrolActive) {
            loadPatrolHistory();
        }

        // Update status indicator if patrol is running
        const statusEl = document.getElementById('patrol-active-status');
        if (statusEl) {
            if (isPatrolActive) {
                statusEl.textContent = `巡檢中: ${data.status_text || data.status}`;
                statusEl.style.display = '';
            } else {
                statusEl.style.display = 'none';
            }
        }
    } catch (e) {
        // Silent fail
    }
}

export function refreshHistory() {
    loadPatrolHistory();
}
