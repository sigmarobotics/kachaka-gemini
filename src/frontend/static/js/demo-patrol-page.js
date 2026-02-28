// demo-patrol-page.js — Standalone patrol dashboard (History, Reports, Tokens)
// Matches visual-patrol UI: amber/cream theme, grid cards, modal detail, Chart.js

// ═══════════════════════════════════════════════════════════════════════════
// GLOBALS
// ═══════════════════════════════════════════════════════════════════════════

let tokenChart = null;
let currentReportRunId = null;

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB SWITCHING
// ═══════════════════════════════════════════════════════════════════════════

window.switchTab = function(tabName) {
    // Hide all views
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    // Deactivate all tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

    // Show selected view
    const view = document.getElementById(`view-${tabName}`);
    if (view) view.style.display = 'flex';

    // Activate the clicked tab button
    const tabs = document.querySelectorAll('.tab-btn');
    tabs.forEach(btn => {
        if (btn.textContent.toLowerCase().includes(tabName) ||
            (tabName === 'stats' && btn.textContent.toLowerCase().includes('token'))) {
            btn.classList.add('active');
        }
    });

    // Load data for the selected tab
    if (tabName === 'history') loadHistory();
    else if (tabName === 'reports') loadReports();
    else if (tabName === 'stats') loadStats();
};

// ═══════════════════════════════════════════════════════════════════════════
// HISTORY TAB
// ═══════════════════════════════════════════════════════════════════════════

async function loadHistory() {
    const listContainer = document.getElementById('history-list');
    if (!listContainer) return;

    listContainer.innerHTML = '<div style="color:#666; text-align:center; grid-column: 1/-1;">Loading history...</div>';

    try {
        const res = await fetch('/api/patrol/runs?limit=100');
        const data = await res.json();
        const runs = data.runs || [];

        listContainer.innerHTML = '';

        if (runs.length === 0) {
            listContainer.innerHTML = '<div style="color:#666; text-align:center; grid-column: 1/-1;">No patrol history found.</div>';
            return;
        }

        runs.forEach(run => {
            const card = document.createElement('div');
            card.className = 'result-card';
            card.onclick = () => viewHistoryDetail(run.id);

            const statusColor = run.status === 'Completed' ? '#28a745' : (run.status === 'Running' ? '#007bff' : '#dc3545');
            const statusText = run.status === 'Completed' ? 'Completed' :
                               run.status === 'Running' ? 'Running' :
                               run.status === 'Error' ? 'Error' : run.status;
            const videoIcon = run.video_path ? '<span title="Has video recording" style="margin-left:6px; font-size:0.85rem; opacity:0.7;">&#127909;</span>' : '';

            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-weight:bold; font-size:1.1rem; color:#1a1a1a;">Run #${run.id}${videoIcon}</span>
                    <span style="font-size:0.8rem; background:${statusColor}; color:#fff; padding:2px 8px; border-radius:4px; font-weight:bold;">${escapeHtml(statusText)}</span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.85rem; color:#555;">
                    <span>Started: ${escapeHtml(run.start_time)}</span>
                    <span>Tokens: ${run.total_tokens || 0}</span>
                </div>
                ${run.report_content ? `<div style="margin-top:10px; color:#333; font-size:0.85rem; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">${escapeHtml(run.report_content)}</div>` : ''}
            `;
            listContainer.appendChild(card);
        });

    } catch (e) {
        listContainer.innerHTML = `<div style="color:#dc3545; text-align:center; grid-column: 1/-1;">Error loading history: ${escapeHtml(String(e))}</div>`;
    }
}

async function viewHistoryDetail(runId) {
    const modal = document.getElementById('history-modal');
    const contentDiv = document.getElementById('modal-report-content');
    const listDiv = document.getElementById('modal-inspections-list');
    const title = document.getElementById('modal-title');

    if (!modal) return;

    currentReportRunId = runId;

    const videoSection = document.getElementById('modal-video-section');
    const videoContent = document.getElementById('modal-video-content');
    const videoDownload = document.getElementById('modal-video-download');

    modal.style.display = 'flex';
    contentDiv.textContent = 'Loading details...';
    listDiv.innerHTML = '';
    if (videoSection) videoSection.style.display = 'none';
    title.textContent = `Patrol Report #${runId}`;

    try {
        const res = await fetch(`/api/patrol/runs/${runId}`);
        if (!res.ok) throw new Error('Failed to load details');

        const data = await res.json();
        const { run, inspections } = data;

        if (run.report_content) {
            contentDiv.innerHTML = marked.parse(run.report_content);
        } else {
            contentDiv.textContent = 'No generated report available.';
        }

        // Video analysis section
        if (videoSection && (run.video_analysis || run.video_path)) {
            videoSection.style.display = 'block';

            if (run.video_analysis && videoContent) {
                videoContent.innerHTML = marked.parse(run.video_analysis);
            } else if (videoContent) {
                videoContent.textContent = 'No video analysis available.';
            }

            if (run.video_path && videoDownload) {
                const videoFilename = run.video_path.split('/').pop();
                videoDownload.innerHTML = `<a href="/api/patrol/report/video/${encodeURIComponent(videoFilename)}" class="btn-primary" style="display:inline-block; padding:6px 14px; font-size:12px; text-decoration:none;">⬇ Download Video</a>`;
            } else if (videoDownload) {
                videoDownload.innerHTML = '';
            }
        }

        listDiv.innerHTML = '';
        if (inspections.length === 0) {
            listDiv.innerHTML = '<div style="color:#666;">No inspections recorded for this run.</div>';
        } else {
            inspections.forEach(ins => {
                const item = document.createElement('div');
                item.style.cssText = 'background:rgba(0,0,0,0.04); padding:10px; border-radius:6px; display:flex; gap:15px; align-items:flex-start;';

                let imgHtml = '';
                if (ins.image_path) {
                    imgHtml = `<img src="/api/patrol/report/image/${encodeURI(ins.image_path)}" style="width:120px; height:auto; border-radius:4px; border:1px solid #ccc;">`;
                }

                const isNg = ins.is_ng;
                const statusClass = isNg ? 'ng' : 'ok';
                const statusLabel = isNg ? 'NG' : 'OK';
                const desc = ins.ai_description || ins.ai_response || '';

                item.innerHTML = `
                    ${imgHtml}
                    <div style="flex:1;">
                        <div style="font-weight:bold; color:#006b56; margin-bottom:4px;">${escapeHtml(ins.point_name)}</div>
                        <div style="font-size:0.8rem; color:#555; margin-bottom:6px;">${escapeHtml(ins.timestamp)}</div>
                        <div style="background:rgba(0,0,0,0.03); padding:6px; border-radius:4px; font-size:0.85rem;">
                            ${ins.prompt ? `<div style="color:#555; font-style:italic; margin-bottom:4px;">Q: ${escapeHtml(ins.prompt)}</div>` : ''}
                            <div class="ai-result-row">
                                <div class="status-indicator ${statusClass}">${statusLabel}</div>
                                <div class="status-text">${escapeHtml(desc)}</div>
                            </div>
                        </div>
                    </div>
                `;
                listDiv.appendChild(item);
            });
        }

    } catch (e) {
        contentDiv.textContent = `Error: ${String(e)}`;
    }
}

window.closeHistoryModal = function() {
    const modal = document.getElementById('history-modal');
    if (modal) modal.style.display = 'none';
};

function saveReportAsPDF() {
    if (!currentReportRunId) {
        alert('No report selected.');
        return;
    }
    window.location.href = `/api/patrol/runs/${currentReportRunId}/pdf`;
}

// ═══════════════════════════════════════════════════════════════════════════
// REPORTS TAB
// ═══════════════════════════════════════════════════════════════════════════

let generatedReports = [];

async function loadReports() {
    // Nothing to load initially — reports are generated on demand
    const list = document.getElementById('reports-list');
    if (!list) return;

    if (generatedReports.length === 0) {
        list.innerHTML = '<div style="color:#666; text-align:center; padding: 24px;">No reports generated yet. Select a date range and click Generate.</div>';
    }
}

async function generateReport() {
    const startInput = document.getElementById('report-start-date');
    const endInput = document.getElementById('report-end-date');
    const btn = document.getElementById('btn-generate-report');

    if (!startInput.value || !endInput.value) {
        alert('Please select a date range.');
        return;
    }

    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">&#x23F3;</span> Generating...';

    try {
        const res = await fetch('/api/patrol/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start_date: startInput.value,
                end_date: endInput.value
            })
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.error || 'Failed to generate report');
        }

        // Add to our local list
        const report = {
            id: Date.now(),
            start_date: startInput.value,
            end_date: endInput.value,
            timestamp: new Date().toLocaleString('zh-TW'),
            report_content: data.text || '',
            input_tokens: data.input_tokens || 0,
            output_tokens: data.output_tokens || 0,
            total_tokens: data.total_tokens || 0,
        };
        generatedReports.unshift(report);
        renderReportsList();

    } catch (e) {
        alert('Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

function renderReportsList() {
    const list = document.getElementById('reports-list');
    if (!list) return;

    list.innerHTML = '';

    if (generatedReports.length === 0) {
        list.innerHTML = '<div style="color:#666; text-align:center; padding: 24px;">No reports generated yet.</div>';
        return;
    }

    generatedReports.forEach(r => {
        const card = document.createElement('div');
        card.className = 'glass-panel';
        card.style.marginBottom = '12px';
        card.style.overflow = 'hidden';

        const header = document.createElement('div');
        header.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:14px 16px; cursor:pointer; border-bottom:1px solid var(--border-subtle);';
        header.onclick = () => toggleReportCard(r.id);

        const dateRange = `${escapeHtml(r.start_date)} ~ ${escapeHtml(r.end_date)}`;

        header.innerHTML = `
            <div>
                <span style="font-weight:bold; color:var(--teal); font-size:1rem;">${dateRange}</span>
                <span style="margin-left:12px; font-size:0.8rem; color:var(--text-muted);">${escapeHtml(r.timestamp)}</span>
            </div>
            <div style="display:flex; align-items:center; gap:12px;">
                <span style="font-size:0.75rem; color:var(--text-muted);">
                    In: ${r.input_tokens} / Out: ${r.output_tokens} / Total: <b style="color:var(--teal);">${r.total_tokens}</b>
                </span>
                <span class="toggle-icon" id="report-toggle-${r.id}">&#x25B6;</span>
            </div>
        `;

        const body = document.createElement('div');
        body.id = `report-body-${r.id}`;
        body.style.display = 'none';
        body.style.padding = '16px';

        const content = r.report_content || '';
        body.innerHTML = `
            <div class="markdown-content" style="max-height:400px; overflow-y:auto; color:var(--text-primary); margin-bottom:12px;">
                ${content ? marked.parse(content) : '<span style="color:var(--text-muted);">No content.</span>'}
            </div>
        `;

        card.appendChild(header);
        card.appendChild(body);
        list.appendChild(card);
    });
}

function toggleReportCard(id) {
    const body = document.getElementById(`report-body-${id}`);
    const icon = document.getElementById(`report-toggle-${id}`);
    if (!body) return;
    const isHidden = body.style.display === 'none';
    body.style.display = isHidden ? 'block' : 'none';
    if (icon) icon.innerHTML = isHidden ? '&#x25BC;' : '&#x25B6;';
}

// ═══════════════════════════════════════════════════════════════════════════
// STATS (TOKENS) TAB
// ═══════════════════════════════════════════════════════════════════════════

async function loadStats() {
    const startInput = document.getElementById('stats-start-date');
    const endInput = document.getElementById('stats-end-date');

    if (!startInput.value) {
        const end = new Date();
        const start = new Date();
        start.setMonth(start.getMonth() - 1);

        const formatDate = (date) => {
            const y = date.getFullYear();
            const m = String(date.getMonth() + 1).padStart(2, '0');
            const d = String(date.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`;
        };

        endInput.value = formatDate(end);
        startInput.value = formatDate(start);
    }

    try {
        const res = await fetch('/api/patrol/token_stats');
        const data = await res.json();

        const startDate = new Date(startInput.value);
        const endDate = new Date(endInput.value);
        const endDateInclusive = new Date(endDate);
        endDateInclusive.setHours(23, 59, 59, 999);

        const dataMap = {};
        data.forEach(d => {
            dataMap[d.date] = { input: d.input || 0, output: d.output || 0, total: d.total || 0 };
        });

        const filledData = [];
        let currentDate = new Date(startDate);

        while (currentDate <= endDateInclusive) {
            const y = currentDate.getFullYear();
            const m = String(currentDate.getMonth() + 1).padStart(2, '0');
            const d = String(currentDate.getDate()).padStart(2, '0');
            const dateStr = `${y}-${m}-${d}`;

            filledData.push({
                date: dateStr,
                input: dataMap[dateStr]?.input || 0,
                output: dataMap[dateStr]?.output || 0,
                total: dataMap[dateStr]?.total || 0
            });

            currentDate.setDate(currentDate.getDate() + 1);
        }

        renderChart(filledData);
        updateStatsSummary(filledData);
    } catch (e) {
        console.error('Failed to load stats:', e);
    }
}

function toMillions(n) {
    return (n / 1_000_000).toFixed(2);
}

function updateStatsSummary(data) {
    const totalInput = data.reduce((sum, d) => sum + d.input, 0);
    const totalOutput = data.reduce((sum, d) => sum + d.output, 0);
    const totalAll = data.reduce((sum, d) => sum + d.total, 0);

    const outputAndThinking = totalAll - totalInput;
    const inputCost = (totalInput / 1_000_000 * 0.5).toFixed(2);
    const outputCost = (outputAndThinking / 1_000_000 * 3).toFixed(2);
    const totalCost = (parseFloat(inputCost) + parseFloat(outputCost)).toFixed(2);

    const summaryEl = document.getElementById('stats-summary');
    if (summaryEl) {
        summaryEl.style.position = 'relative';
        summaryEl.innerHTML = `
            <span style="position:absolute; top:8px; right:12px; font-size:11px; color:var(--text-muted);">Unit: USD</span>
            <div class="stat-item" style="text-align: center;">
                <span class="stat-label" style="display:block; font-size:12px; color:var(--text-muted); margin-bottom:4px;">Input Tokens</span>
                <span class="stat-value" style="font-size:24px; font-weight:bold; color:#28a745; font-family:var(--font-mono);">${toMillions(totalInput)} M</span>
                <span style="display:block; font-size:11px; color:var(--text-muted); margin-top:2px;">$0.50 / 1M &rarr; $${inputCost}</span>
            </div>
            <div class="stat-item" style="text-align: center;">
                <span class="stat-label" style="display:block; font-size:12px; color:var(--text-muted); margin-bottom:4px;">Output + Thinking</span>
                <span class="stat-value" style="font-size:24px; font-weight:bold; color:#e67e22; font-family:var(--font-mono);">${toMillions(outputAndThinking)} M</span>
                <span style="display:block; font-size:11px; color:var(--text-muted); margin-top:2px;">$3.00 / 1M &rarr; $${outputCost}</span>
            </div>
            <div class="stat-item" style="text-align: center;">
                <span class="stat-label" style="display:block; font-size:12px; color:var(--text-muted); margin-bottom:4px;">Total Tokens</span>
                <span class="stat-value" style="font-size:24px; font-weight:bold; color:#007bff; font-family:var(--font-mono);">${toMillions(totalAll)} M</span>
                <span style="display:block; font-size:11px; color:var(--text-muted); margin-top:2px;">Est. Cost: $${totalCost}</span>
            </div>
        `;
    }
}

function renderChart(data) {
    const ctx = document.getElementById('tokenUsageChart').getContext('2d');

    if (tokenChart) {
        tokenChart.destroy();
    }

    const labels = data.map(d => d.date);
    const inputValues = data.map(d => d.input / 1_000_000);
    const outputValues = data.map(d => d.output / 1_000_000);
    const totalValues = data.map(d => d.total / 1_000_000);

    tokenChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Input Tokens',
                    data: inputValues,
                    borderColor: '#28a745',
                    backgroundColor: 'rgba(40, 167, 69, 0.1)',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4,
                    pointBackgroundColor: '#28a745',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 3,
                    pointHoverRadius: 5
                },
                {
                    label: 'Output Tokens',
                    data: outputValues,
                    borderColor: '#e67e22',
                    backgroundColor: 'rgba(230, 126, 34, 0.1)',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4,
                    pointBackgroundColor: '#e67e22',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 3,
                    pointHoverRadius: 5
                },
                {
                    label: 'Total Tokens',
                    data: totalValues,
                    borderColor: '#007bff',
                    backgroundColor: 'rgba(0, 123, 255, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointBackgroundColor: '#007bff',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            scales: {
                x: {
                    ticks: {
                        color: '#555',
                        font: { family: "'IBM Plex Mono', monospace", size: 10 }
                    },
                    grid: { color: 'rgba(0, 0, 0, 0.08)' }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Million Tokens',
                        color: '#555',
                        font: { family: "'Chakra Petch', sans-serif", size: 11, weight: 600 }
                    },
                    ticks: {
                        color: '#555',
                        font: { family: "'IBM Plex Mono', monospace", size: 10 },
                        callback: v => v.toFixed(2) + ' M'
                    },
                    grid: { color: 'rgba(0, 0, 0, 0.08)' },
                    beginAtZero: true
                }
            },
            plugins: {
                legend: {
                    labels: {
                        color: '#333',
                        font: { family: "'Chakra Petch', sans-serif", size: 11, weight: 600 }
                    }
                },
                tooltip: {
                    backgroundColor: '#f7f5f2',
                    titleColor: '#007bff',
                    bodyColor: '#333',
                    borderColor: 'rgba(0, 0, 0, 0.15)',
                    borderWidth: 1,
                    cornerRadius: 4,
                    padding: 12,
                    titleFont: { family: "'Chakra Petch', sans-serif", size: 11 },
                    bodyFont: { family: "'IBM Plex Mono', monospace", size: 12 },
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(3)} M`
                    }
                }
            }
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    // Default date range for reports: last 7 days
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 7);

    const fmt = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

    const startInput = document.getElementById('report-start-date');
    const endInput = document.getElementById('report-end-date');
    if (startInput) startInput.value = fmt(start);
    if (endInput) endInput.value = fmt(end);

    // Bind generate report button
    const btnGenerate = document.getElementById('btn-generate-report');
    if (btnGenerate) btnGenerate.addEventListener('click', generateReport);

    // Bind PDF save button
    const btnPdf = document.getElementById('btn-save-pdf');
    if (btnPdf) btnPdf.addEventListener('click', saveReportAsPDF);

    // Modal click-outside-to-close
    const modal = document.getElementById('history-modal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeHistoryModal();
        });
    }

    // Stats date change listeners
    const statsStart = document.getElementById('stats-start-date');
    const statsEnd = document.getElementById('stats-end-date');
    if (statsStart) statsStart.addEventListener('change', loadStats);
    if (statsEnd) statsEnd.addEventListener('change', loadStats);

    // Load initial history
    loadHistory();
});
