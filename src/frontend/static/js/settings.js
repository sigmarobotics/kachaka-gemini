// settings.js — Settings page logic

function switchSettingsTab(tabName) {
    document.querySelectorAll('.settings-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.settingsTab === tabName);
    });
    document.querySelectorAll('.settings-pane').forEach(pane => {
        const isActive = pane.id === `settings-pane-${tabName}`;
        pane.style.display = isActive ? '' : 'none';
        pane.classList.toggle('active', isActive);
    });
}

function updateParamDisplay(inputId, displayId) {
    const input = document.getElementById(inputId);
    const display = document.getElementById(displayId);
    if (input && display) display.textContent = input.value;
}

const SAFETY_CATEGORIES = {
    'harassment': 'HARM_CATEGORY_HARASSMENT',
    'hate': 'HARM_CATEGORY_HATE_SPEECH',
    'sexual': 'HARM_CATEGORY_SEXUALLY_EXPLICIT',
    'danger': 'HARM_CATEGORY_DANGEROUS_CONTENT',
};

function loadSafetySettings(safetyObj) {
    for (const [shortKey, fullKey] of Object.entries(SAFETY_CATEGORIES)) {
        const select = document.getElementById(`setting-text-safety-${shortKey}`);
        if (select) select.value = safetyObj[fullKey] || '';
    }
}

function collectSafetySettings() {
    const result = {};
    for (const [shortKey, fullKey] of Object.entries(SAFETY_CATEGORIES)) {
        const select = document.getElementById(`setting-text-safety-${shortKey}`);
        if (select && select.value) {
            result[fullKey] = select.value;
        }
    }
    return result;
}

export async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();

        const apiKeyInput = document.getElementById('setting-api-key');
        const textModelInput = document.getElementById('setting-text-model');
        const liveModelInput = document.getElementById('setting-live-model');
        const personaInput = document.getElementById('setting-persona');
        const staticKnowledgeInput = document.getElementById('setting-static-knowledge');
        const voiceSelect = document.getElementById('setting-voice');
        const textGoogleSearch = document.getElementById('setting-text-google-search');
        const liveGoogleSearch = document.getElementById('setting-live-google-search');

        if (apiKeyInput) apiKeyInput.placeholder = settings.gemini_api_key_masked || 'Enter Gemini API Key';
        const telegramTokenInput = document.getElementById('setting-telegram-token');
        if (telegramTokenInput) telegramTokenInput.placeholder = settings.telegram_bot_token_masked || 'Enter Telegram Bot Token';

        if (textModelInput) {
            const savedTextModel = settings.text_model || 'gemini-3-flash-preview';
            if (!textModelInput.querySelector(`option[value="${savedTextModel}"]`)) {
                const opt = document.createElement('option');
                opt.value = savedTextModel;
                opt.textContent = savedTextModel;
                textModelInput.appendChild(opt);
            }
            textModelInput.value = savedTextModel;
        }
        if (liveModelInput) {
            const savedLiveModel = settings.live_model || 'gemini-2.0-flash-live-001';
            if (!liveModelInput.querySelector(`option[value="${savedLiveModel}"]`)) {
                const opt = document.createElement('option');
                opt.value = savedLiveModel;
                opt.textContent = savedLiveModel;
                liveModelInput.appendChild(opt);
            }
            liveModelInput.value = savedLiveModel;
        }

        if (personaInput) personaInput.value = settings.persona || '';
        if (staticKnowledgeInput) staticKnowledgeInput.value = settings.static_knowledge || '';

        const knowledgeBaseInput = document.getElementById('setting-knowledge-base');
        if (knowledgeBaseInput) knowledgeBaseInput.value = settings.knowledge_base || '';

        if (voiceSelect) voiceSelect.value = settings.voice_name || 'Aoede';
        if (textGoogleSearch) textGoogleSearch.checked = settings.text_enable_google_search || false;
        if (liveGoogleSearch) liveGoogleSearch.checked = settings.live_enable_google_search || false;
        const robotIpInput = document.getElementById('setting-robot-ip');
        if (robotIpInput) robotIpInput.value = settings.robot_ip || '';

        // Robot background info — auto-load A* distances
        loadLocationDistances();

        // Function declarations — graphical editor
        const funcDecls = settings.function_declarations || [];
        renderFuncEditor(funcDecls);

        // Exhibition & patrol settings
        const exhibitionTitle = document.getElementById('exhibition-title');
        const patrolTelegramNotify = document.getElementById('patrol-telegram-notify');
        const liveAutoInterrupt = document.getElementById('live-auto-interrupt');

        if (exhibitionTitle) exhibitionTitle.value = settings.exhibition_title || '';
        if (patrolTelegramNotify) patrolTelegramNotify.checked = settings.patrol_telegram_notify !== false;
        if (liveAutoInterrupt) liveAutoInterrupt.checked = settings.live_auto_interrupt !== false;

        // Telegram chat IDs (textarea, one per line)
        const chatIdsTextarea = document.getElementById('telegram-chat-ids');
        if (chatIdsTextarea) {
            const ids = settings.telegram_chat_ids || [];
            chatIdsTextarea.value = Array.isArray(ids) ? ids.join('\n') : String(ids);
        }

        // Patrol settings
        const patrolImagePrompt = document.getElementById('patrol-image-prompt');
        if (patrolImagePrompt) patrolImagePrompt.value = settings.patrol_image_prompt || '';

        const inspectDwellTime = document.getElementById('inspect-dwell-time');
        if (inspectDwellTime) inspectDwellTime.value = settings.inspect_dwell_time || 10;

        const guideDwellTime = document.getElementById('guide-dwell-time');
        if (guideDwellTime) guideDwellTime.value = settings.guide_dwell_time || 30;

        // Load location options for kiosk location
        loadKioskLocationOptions(settings.kiosk_location || '');

        // Load patrol point checkboxes
        renderPatrolCheckboxes(settings.patrol_points || []);

        // Generation parameters — Text
        const textTemp = document.getElementById('setting-text-temperature');
        const textMaxTokens = document.getElementById('setting-text-max-output-tokens');
        const textTopP = document.getElementById('setting-text-top-p');
        const textTopK = document.getElementById('setting-text-top-k');
        if (textTemp) { textTemp.value = settings.text_temperature ?? 1.0; updateParamDisplay('setting-text-temperature', 'text-temp-display'); }
        if (textMaxTokens) textMaxTokens.value = settings.text_max_output_tokens ?? 8192;
        if (textTopP) { textTopP.value = settings.text_top_p ?? 0.95; updateParamDisplay('setting-text-top-p', 'text-top-p-display'); }
        if (textTopK) textTopK.value = settings.text_top_k ?? 40;

        // Generation parameters — Live
        const liveTemp = document.getElementById('setting-live-temperature');
        const liveMaxTokens = document.getElementById('setting-live-max-output-tokens');
        const liveTopP = document.getElementById('setting-live-top-p');
        const liveTopK = document.getElementById('setting-live-top-k');
        if (liveTemp) { liveTemp.value = settings.live_temperature ?? 1.0; updateParamDisplay('setting-live-temperature', 'live-temp-display'); }
        if (liveMaxTokens) liveMaxTokens.value = settings.live_max_output_tokens ?? 8192;
        if (liveTopP) { liveTopP.value = settings.live_top_p ?? 0.95; updateParamDisplay('setting-live-top-p', 'live-top-p-display'); }
        if (liveTopK) liveTopK.value = settings.live_top_k ?? 40;

        // Safety settings — Text only
        loadSafetySettings(settings.text_safety_settings || {});

        // Load token usage
        await loadTokenUsage();

        // Load profile list
        await loadProfileList();
        setupProfileButtons();
    } catch (e) {
        console.error('Failed to load settings:', e);
    }
}

async function loadTokenUsage() {
    try {
        const res = await fetch('/api/token_usage');
        const data = await res.json();
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val.toLocaleString();
        };
        set('token-today-prompt', data.today.prompt);
        set('token-today-response', data.today.response);
        set('token-today-total', data.today.total);
        set('token-all-prompt', data.all_time.prompt);
        set('token-all-response', data.all_time.response);
        set('token-all-total', data.all_time.total);
    } catch (e) {
        console.error('Failed to load token usage:', e);
    }
}

async function resetTokenUsage() {
    if (!confirm('Reset all token usage records?')) return;
    try {
        await fetch('/api/token_usage/reset', { method: 'POST' });
        await loadTokenUsage();
    } catch (e) {
        console.error('Failed to reset token usage:', e);
    }
}

async function queryModels(mode, selectId, btnId) {
    const btn = document.getElementById(btnId);
    const select = document.getElementById(selectId);
    if (!btn || !select) return;

    const currentValue = select.value;
    btn.disabled = true;
    btn.textContent = '...';

    try {
        const res = await fetch(`/api/models?mode=${mode}`);
        const data = await res.json();

        if (!res.ok) {
            alert(data.error || 'Failed to query models');
            return;
        }

        const models = data.models || [];
        if (models.length === 0) {
            alert(`No ${mode === 'text' ? 'Text API' : 'Live API'} models found. Check your API key.`);
            return;
        }

        select.innerHTML = '';
        for (const m of models) {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.id;
            opt.title = m.description || '';
            select.appendChild(opt);
        }

        if (select.querySelector(`option[value="${currentValue}"]`)) {
            select.value = currentValue;
        }
    } catch (e) {
        console.error('Failed to query models:', e);
        alert('Failed to query models: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Query';
    }
}

async function connectRobot() {
    const ipInput = document.getElementById('setting-robot-ip');
    const statusEl = document.getElementById('robot-connection-status');
    const btn = document.getElementById('btn-robot-connect');
    if (!ipInput || !btn) return;

    const ip = ipInput.value.trim();
    if (!ip) {
        if (statusEl) { statusEl.textContent = 'Please enter an IP address'; statusEl.style.color = 'var(--danger)'; }
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Connecting...';
    if (statusEl) { statusEl.textContent = 'Connecting...'; statusEl.style.color = 'var(--muted)'; }

    try {
        const res = await fetch('/api/robot/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip }),
        });
        const data = await res.json();
        if (data.ok) {
            if (statusEl) { statusEl.textContent = `Connected (serial: ${data.serial})`; statusEl.style.color = 'var(--mint)'; }
            // Refresh patrol checkboxes after connecting
            _cachedLocations = null;
            const settings = await (await fetch('/api/settings')).json();
            renderPatrolCheckboxes(settings.patrol_points || []);
        } else {
            if (statusEl) { statusEl.textContent = `Failed: ${data.error}`; statusEl.style.color = 'var(--danger)'; }
        }
    } catch (e) {
        if (statusEl) { statusEl.textContent = `Error: ${e.message}`; statusEl.style.color = 'var(--danger)'; }
    } finally {
        btn.disabled = false;
        btn.textContent = 'Connect';
    }
}

async function disconnectRobot() {
    const statusEl = document.getElementById('robot-connection-status');
    try {
        await fetch('/api/robot/disconnect', { method: 'POST' });
        if (statusEl) { statusEl.textContent = 'Disconnected'; statusEl.style.color = 'var(--muted)'; }
    } catch (e) {
        if (statusEl) { statusEl.textContent = `Error: ${e.message}`; statusEl.style.color = 'var(--danger)'; }
    }
}

async function loadRobotStatus() {
    const statusEl = document.getElementById('robot-connection-status');
    try {
        const res = await fetch('/api/robot/status');
        const data = await res.json();
        if (data.connected) {
            if (statusEl) { statusEl.textContent = `Connected to ${data.ip} (serial: ${data.serial})`; statusEl.style.color = 'var(--mint)'; }
        } else {
            if (statusEl) { statusEl.textContent = 'Not connected'; statusEl.style.color = 'var(--muted)'; }
        }
    } catch (e) {
        // Silently fail
    }
}

export function initSettings() {
    const saveBtn = document.getElementById('btn-save-settings');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveSettings);
    }

    // Settings tab switching
    document.querySelectorAll('.settings-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchSettingsTab(btn.dataset.settingsTab));
    });

    // Query models buttons (per-mode)
    document.getElementById('btn-query-text-models')
        ?.addEventListener('click', () => queryModels('text', 'setting-text-model', 'btn-query-text-models'));
    document.getElementById('btn-query-live-models')
        ?.addEventListener('click', () => queryModels('live', 'setting-live-model', 'btn-query-live-models'));

    // Download buttons
    document.getElementById('btn-download-system-instruction')
        ?.addEventListener('click', downloadSystemInstruction);
    document.getElementById('btn-download-func-decl')
        ?.addEventListener('click', downloadFuncDecl);

    // Upload inputs
    document.getElementById('upload-system-instruction')
        ?.addEventListener('change', uploadSystemInstruction);
    document.getElementById('upload-knowledge-base')
        ?.addEventListener('change', uploadKnowledgeBase);
    document.getElementById('btn-clear-knowledge-base')
        ?.addEventListener('click', clearKnowledgeBase);
    document.getElementById('upload-func-decl')
        ?.addEventListener('change', uploadFuncDecl);

    // Reset button
    document.getElementById('btn-reset-func-decl')
        ?.addEventListener('click', resetFuncDecl);

    // Add Function button
    document.getElementById('btn-add-function')
        ?.addEventListener('click', () => {
            const container = document.getElementById('func-editor');
            if (!container) return;
            const index = ++window._funcCardCounter;
            const newCard = renderFuncCard({ name: '', description: '', parameters: { type: 'object', properties: {}, required: [] } }, index);
            container.insertAdjacentHTML('beforeend', newCard);
            container.lastElementChild?.classList.add('open');
        });

    // Token usage buttons
    document.getElementById('btn-refresh-tokens')
        ?.addEventListener('click', loadTokenUsage);
    document.getElementById('btn-reset-tokens')
        ?.addEventListener('click', resetTokenUsage);

    // Robot connection buttons
    document.getElementById('btn-robot-connect')
        ?.addEventListener('click', connectRobot);
    document.getElementById('btn-robot-disconnect')
        ?.addEventListener('click', disconnectRobot);

    // Load robot connection status
    loadRobotStatus();

    // Slider display updates
    for (const [sliderId, displayId] of [
        ['setting-text-temperature', 'text-temp-display'],
        ['setting-text-top-p', 'text-top-p-display'],
        ['setting-live-temperature', 'live-temp-display'],
        ['setting-live-top-p', 'live-top-p-display'],
    ]) {
        document.getElementById(sliderId)
            ?.addEventListener('input', () => updateParamDisplay(sliderId, displayId));
    }

    loadSettings();
}

// ─── JSON validation helpers ─────────────────────────────────────────────────

function clearJsonError(errorElId) {
    const errEl = document.getElementById(errorElId);
    if (errEl) {
        errEl.style.display = 'none';
        errEl.textContent = '';
    }
}

function showJsonError(errorElId, msg) {
    const errEl = document.getElementById(errorElId);
    if (errEl) {
        errEl.style.display = 'block';
        errEl.textContent = msg;
    }
}

// ─── Function Declarations Editor ────────────────────────────────────────────

function escapeAttr(str) {
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderFuncEditor(declarations) {
    const container = document.getElementById('func-editor');
    if (!container) return;
    container.innerHTML = declarations.map((fn, i) => renderFuncCard(fn, i)).join('');
    window._funcCardCounter = declarations.length - 1;
}

function renderFuncCard(fn, index) {
    const name = fn.name || '';
    const desc = fn.description || '';
    const enabled = fn.enabled !== false; // default true
    const params = fn.parameters || { type: 'object', properties: {}, required: [] };
    const props = params.properties || {};
    const required = params.required || [];

    return `
    <div class="func-card${enabled ? '' : ' disabled'}" data-index="${index}">
        <div class="func-card-header" onclick="this.parentElement.classList.toggle('open')">
            <label class="func-toggle" onclick="event.stopPropagation()">
                <input type="checkbox" class="func-enabled" ${enabled ? 'checked' : ''} onchange="toggleFuncCard(this)">
                <span class="func-toggle-slider"></span>
            </label>
            <span class="func-card-name">${escapeAttr(name) || '(unnamed)'}</span>
            <div class="func-card-actions">
                <span class="func-card-arrow">&#9660;</span>
                <button class="func-card-delete" onclick="event.stopPropagation(); deleteFuncCard(${index})" title="Delete">DEL</button>
            </div>
        </div>
        <div class="func-card-body">
            <div class="form-group">
                <label>Name</label>
                <input type="text" class="func-name" value="${escapeAttr(name)}" placeholder="function_name">
            </div>
            <div class="form-group">
                <label>Description</label>
                <textarea class="func-desc" rows="2" placeholder="Function description...">${escapeAttr(desc)}</textarea>
            </div>
            <div class="form-group">
                <label>Parameters</label>
                ${renderParamTable(props, required, index)}
                <button class="btn-add-param" onclick="addParam(${index})">+ Add Parameter</button>
            </div>
        </div>
    </div>`;
}

function renderParamTable(properties, required, funcIndex) {
    const paramEntries = Object.entries(properties);
    const headerRow = '<thead><tr><th>Name</th><th>Type</th><th>Description</th><th>Enum</th><th>Req</th><th></th></tr></thead>';

    if (paramEntries.length === 0) {
        return `<table class="param-table" data-func="${funcIndex}">${headerRow}<tbody></tbody></table>`;
    }

    const rows = paramEntries.map(([pName, pDef]) => {
        const pType = pDef.type || 'string';
        const pDesc = pDef.description || '';
        const pEnum = (pDef.enum || []).join(', ');
        const isReq = required.includes(pName);
        return `<tr>
            <td><input type="text" class="param-name" value="${escapeAttr(pName)}"></td>
            <td><select class="param-type">
                <option value="string"${pType === 'string' ? ' selected' : ''}>string</option>
                <option value="number"${pType === 'number' ? ' selected' : ''}>number</option>
                <option value="integer"${pType === 'integer' ? ' selected' : ''}>integer</option>
                <option value="boolean"${pType === 'boolean' ? ' selected' : ''}>boolean</option>
            </select></td>
            <td><input type="text" class="param-desc" value="${escapeAttr(pDesc)}"></td>
            <td><input type="text" class="param-enum" value="${escapeAttr(pEnum)}" placeholder="a, b, c"></td>
            <td style="text-align:center"><input type="checkbox" class="param-required"${isReq ? ' checked' : ''}></td>
            <td><button class="param-delete-btn" onclick="deleteParamRow(this)">DEL</button></td>
        </tr>`;
    }).join('');

    return `<table class="param-table" data-func="${funcIndex}">${headerRow}<tbody>${rows}</tbody></table>`;
}

function collectFuncDeclarations() {
    const cards = document.querySelectorAll('.func-card');
    const result = [];
    cards.forEach(card => {
        const name = card.querySelector('.func-name')?.value?.trim() || '';
        const desc = card.querySelector('.func-desc')?.value?.trim() || '';
        const properties = {};
        const required = [];

        card.querySelectorAll('.param-table tbody tr').forEach(row => {
            const pName = row.querySelector('.param-name')?.value?.trim();
            if (!pName) return;
            const pType = row.querySelector('.param-type')?.value || 'string';
            const pDesc = row.querySelector('.param-desc')?.value?.trim() || '';
            const pEnumStr = row.querySelector('.param-enum')?.value?.trim() || '';
            const isReq = row.querySelector('.param-required')?.checked || false;

            const propDef = { type: pType, description: pDesc };
            if (pEnumStr) {
                propDef.enum = pEnumStr.split(',').map(s => s.trim()).filter(s => s);
            }
            properties[pName] = propDef;
            if (isReq) required.push(pName);
        });

        const enabled = card.querySelector('.func-enabled')?.checked !== false;
        result.push({
            name,
            description: desc,
            parameters: { type: 'object', properties, required },
            enabled,
        });
    });
    return result;
}

// Global functions for onclick handlers
window.deleteFuncCard = function(index) {
    const card = document.querySelector(`.func-card[data-index="${index}"]`);
    if (card && confirm('Delete this function?')) card.remove();
};

window.toggleFuncCard = function(checkbox) {
    const card = checkbox.closest('.func-card');
    if (card) card.classList.toggle('disabled', !checkbox.checked);
};

window.addParam = function(funcIndex) {
    const card = document.querySelector(`.func-card[data-index="${funcIndex}"]`);
    if (!card) return;
    const tbody = card.querySelector('.param-table tbody');
    if (!tbody) return;
    const row = document.createElement('tr');
    row.innerHTML = `
        <td><input type="text" class="param-name" value="" placeholder="param_name"></td>
        <td><select class="param-type">
            <option value="string" selected>string</option>
            <option value="number">number</option>
            <option value="integer">integer</option>
            <option value="boolean">boolean</option>
        </select></td>
        <td><input type="text" class="param-desc" value=""></td>
        <td><input type="text" class="param-enum" value="" placeholder="a, b, c"></td>
        <td style="text-align:center"><input type="checkbox" class="param-required"></td>
        <td><button class="param-delete-btn" onclick="deleteParamRow(this)">DEL</button></td>
    `;
    tbody.appendChild(row);
};

window.deleteParamRow = function(btn) {
    btn.closest('tr').remove();
};

// ─── Save ────────────────────────────────────────────────────────────────────

async function saveSettings() {
    const apiKeyInput = document.getElementById('setting-api-key');
    const textModelInput = document.getElementById('setting-text-model');
    const liveModelInput = document.getElementById('setting-live-model');
    const personaInput = document.getElementById('setting-persona');
    const staticKnowledgeInput = document.getElementById('setting-static-knowledge');
    const voiceSelect = document.getElementById('setting-voice');
    const textGoogleSearch = document.getElementById('setting-text-google-search');
    const liveGoogleSearch = document.getElementById('setting-live-google-search');

    const updates = {};

    if (apiKeyInput && apiKeyInput.value.trim()) {
        updates.gemini_api_key = apiKeyInput.value.trim();
    }
    const telegramTokenInput = document.getElementById('setting-telegram-token');
    if (telegramTokenInput && telegramTokenInput.value.trim()) {
        updates.telegram_bot_token = telegramTokenInput.value.trim();
    }
    if (textModelInput) updates.text_model = textModelInput.value.trim();
    if (liveModelInput) updates.live_model = liveModelInput.value.trim();
    if (personaInput) updates.persona = personaInput.value;
    if (staticKnowledgeInput) updates.static_knowledge = staticKnowledgeInput.value;
    const knowledgeBaseInput = document.getElementById('setting-knowledge-base');
    if (knowledgeBaseInput) updates.knowledge_base = knowledgeBaseInput.value;
    if (voiceSelect) updates.voice_name = voiceSelect.value;
    if (textGoogleSearch) updates.text_enable_google_search = textGoogleSearch.checked;
    if (liveGoogleSearch) updates.live_enable_google_search = liveGoogleSearch.checked;

    const robotIpInput = document.getElementById('setting-robot-ip');
    if (robotIpInput && robotIpInput.value.trim()) {
        updates.robot_ip = robotIpInput.value.trim();
    }

    // robot_background_info is auto-managed ({{AVAILABLE_LOCATIONS}} placeholder)
    // — not saved from UI

    // Function declarations from graphical editor
    updates.function_declarations = collectFuncDeclarations();

    // Patrol & Exhibition settings
    Object.assign(updates, collectPatrolSettings());

    // Generation params — Text
    const textTemp = document.getElementById('setting-text-temperature');
    const textMaxTokens = document.getElementById('setting-text-max-output-tokens');
    const textTopP = document.getElementById('setting-text-top-p');
    const textTopK = document.getElementById('setting-text-top-k');
    if (textTemp) updates.text_temperature = parseFloat(textTemp.value);
    if (textMaxTokens) updates.text_max_output_tokens = parseInt(textMaxTokens.value, 10);
    if (textTopP) updates.text_top_p = parseFloat(textTopP.value);
    if (textTopK) updates.text_top_k = parseInt(textTopK.value, 10);

    // Generation params — Live
    const liveTemp = document.getElementById('setting-live-temperature');
    const liveMaxTokens = document.getElementById('setting-live-max-output-tokens');
    const liveTopP = document.getElementById('setting-live-top-p');
    const liveTopK = document.getElementById('setting-live-top-k');
    if (liveTemp) updates.live_temperature = parseFloat(liveTemp.value);
    if (liveMaxTokens) updates.live_max_output_tokens = parseInt(liveMaxTokens.value, 10);
    if (liveTopP) updates.live_top_p = parseFloat(liveTopP.value);
    if (liveTopK) updates.live_top_k = parseInt(liveTopK.value, 10);

    // Safety settings — Text
    updates.text_safety_settings = collectSafetySettings();

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });
        if (res.ok) {
            const saveBtn = document.getElementById('btn-save-settings');
            const original = saveBtn.textContent;
            saveBtn.textContent = 'Saved!';
            saveBtn.style.background = 'var(--mint)';
            setTimeout(() => {
                saveBtn.textContent = original;
                saveBtn.style.background = '';
            }, 2000);
            if (apiKeyInput) apiKeyInput.value = '';
            if (telegramTokenInput) telegramTokenInput.value = '';
            await loadSettings();
        }
    } catch (e) {
        console.error('Failed to save settings:', e);
    }
}

// ─── Download / Upload helpers ───────────────────────────────────────────────

function downloadJson(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function downloadSystemInstruction() {
    const persona = document.getElementById('setting-persona');
    const staticKnowledge = document.getElementById('setting-static-knowledge');
    const knowledgeBase = document.getElementById('setting-knowledge-base');
    downloadJson({
        persona: persona?.value || '',
        static_knowledge: staticKnowledge?.value || '',
        knowledge_base: knowledgeBase?.value || '',
    }, 'system_instruction.json');
}

function downloadFuncDecl() {
    const data = collectFuncDeclarations();
    downloadJson(data, 'function_declarations.json');
}

function uploadSystemInstruction(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);
            const personaEl = document.getElementById('setting-persona');
            const staticEl = document.getElementById('setting-static-knowledge');
            const knowledgeEl = document.getElementById('setting-knowledge-base');
            if (data.persona && personaEl) personaEl.value = data.persona;
            if (data.static_knowledge && staticEl) staticEl.value = data.static_knowledge;
            if (data.knowledge_base != null && knowledgeEl) knowledgeEl.value = typeof data.knowledge_base === 'string' ? data.knowledge_base : JSON.stringify(data.knowledge_base, null, 2);
        } catch (err) {
            alert('Invalid JSON file');
        }
    };
    reader.readAsText(file);
    event.target.value = '';
}

function uploadFuncDecl(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);
            let decls;
            if (Array.isArray(data)) {
                decls = data;
            } else if (Array.isArray(data.function_declarations)) {
                decls = data.function_declarations;
            } else {
                alert('Expected a JSON array or { "function_declarations": [...] }');
                return;
            }
            renderFuncEditor(decls);
        } catch (err) {
            alert('Invalid JSON file');
        }
    };
    reader.readAsText(file);
    event.target.value = '';
}

function uploadKnowledgeBase(event) {
    const files = Array.from(event.target.files);
    if (files.length === 0) return;
    const textarea = document.getElementById('setting-knowledge-base');
    if (!textarea) return;

    const existing = textarea.value.trim();
    const parts = existing ? [existing] : [];
    let loaded = 0;

    for (const file of files) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target.result;
            let content;

            if (file.name.endsWith('.json')) {
                try {
                    const data = JSON.parse(text);
                    content = JSON.stringify(data, null, 2);
                } catch {
                    content = text;
                }
            } else {
                content = text;
            }

            parts.push(`--- ${file.name} ---\n${content}`);
            loaded++;

            if (loaded === files.length) {
                textarea.value = parts.join('\n\n');
            }
        };
        reader.readAsText(file);
    }
    event.target.value = '';
}

function clearKnowledgeBase() {
    const textarea = document.getElementById('setting-knowledge-base');
    if (textarea) textarea.value = '';
}

async function resetFuncDecl() {
    if (!confirm('Reset function declarations to default?')) return;
    try {
        const res = await fetch('/api/settings/defaults');
        if (res.ok) {
            const defaults = await res.json();
            if (defaults.function_declarations) {
                renderFuncEditor(defaults.function_declarations);
            }
        }
    } catch (e) {
        console.error('Failed to fetch defaults:', e);
    }
}

// ─── Robot Background Info (A* Distances, read-only) ────────────────────────

async function loadLocationDistances() {
    const textarea = document.getElementById('setting-robot-info');
    if (!textarea) return;

    try {
        const res = await fetch('/api/locations');
        const data = await res.json();
        if (!data || data.length === 0) {
            textarea.value = '機器人未連線，無法取得地點資訊';
            return;
        }
        const lines = ['可用地點（依 A* 路徑距離排序）：'];
        for (const loc of data) {
            const dist = loc.distance_m != null ? ` (${loc.distance_m}m)` : '';
            lines.push(`- ${loc.name}${dist}`);
        }
        textarea.value = lines.join('\n');
    } catch (e) {
        console.error('Failed to load location distances:', e);
        textarea.value = '載入失敗';
    }
}

// ─── Patrol Settings (Checkbox-based) ────────────────────────────────────────

let _cachedLocations = null;

async function fetchLocationsList() {
    if (_cachedLocations) return _cachedLocations;
    try {
        const res = await fetch('/api/locations');
        _cachedLocations = await res.json();
    } catch (e) {
        console.error('Failed to fetch locations:', e);
        _cachedLocations = [];
    }
    return _cachedLocations;
}

async function renderPatrolCheckboxes(selectedIds) {
    const container = document.getElementById('patrol-points-checkboxes');
    if (!container) return;

    const locations = await fetchLocationsList();
    if (locations.length === 0) {
        container.innerHTML = '<span class="patrol-empty">機器人未連線，無法取得地點</span>';
        return;
    }

    const selectedSet = new Set(Array.isArray(selectedIds) ? selectedIds : []);
    container.innerHTML = '';

    for (const loc of locations) {
        const label = document.createElement('label');
        label.className = 'patrol-checkbox-item';
        label.innerHTML = `
            <input type="checkbox" value="${escapeAttr(loc.id)}"
                   ${selectedSet.has(loc.id) ? 'checked' : ''}>
            <span>${escapeAttr(loc.name)} <small>(${escapeAttr(loc.id)})</small></span>
        `;
        container.appendChild(label);
    }
}

function collectPatrolPointIds() {
    const checkboxes = document.querySelectorAll('#patrol-points-checkboxes input[type="checkbox"]:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

async function loadKioskLocationOptions(selectedLocation) {
    const select = document.getElementById('kiosk-location');
    if (!select) return;

    const locations = await fetchLocationsList();
    select.innerHTML = '<option value="">(未設定)</option>';
    for (const loc of locations) {
        const opt = document.createElement('option');
        opt.value = loc.id;
        opt.textContent = `${loc.name} (${loc.id})`;
        select.appendChild(opt);
    }

    if (selectedLocation) {
        select.value = selectedLocation;
    }
}

function collectPatrolSettings() {
    const result = {};

    const exhibitionTitle = document.getElementById('exhibition-title');
    const kioskLocation = document.getElementById('kiosk-location');
    const patrolTelegramNotify = document.getElementById('patrol-telegram-notify');
    const liveAutoInterrupt = document.getElementById('live-auto-interrupt');

    if (exhibitionTitle) result.exhibition_title = exhibitionTitle.value;
    if (kioskLocation) result.kiosk_location = kioskLocation.value;
    if (patrolTelegramNotify) result.patrol_telegram_notify = patrolTelegramNotify.checked;
    if (liveAutoInterrupt) result.live_auto_interrupt = liveAutoInterrupt.checked;

    const patrolImagePrompt = document.getElementById('patrol-image-prompt');
    if (patrolImagePrompt) result.patrol_image_prompt = patrolImagePrompt.value;

    const inspectDwellTime = document.getElementById('inspect-dwell-time');
    if (inspectDwellTime) result.inspect_dwell_time = parseInt(inspectDwellTime.value) || 10;

    const guideDwellTime = document.getElementById('guide-dwell-time');
    if (guideDwellTime) result.guide_dwell_time = parseInt(guideDwellTime.value) || 30;

    // Patrol points as list of location IDs
    result.patrol_points = collectPatrolPointIds();

    // Telegram chat IDs from textarea (split by newline)
    const chatIdsTextarea = document.getElementById('telegram-chat-ids');
    if (chatIdsTextarea) {
        result.telegram_chat_ids = chatIdsTextarea.value
            .split('\n')
            .map(s => s.trim())
            .filter(s => s.length > 0);
    }

    return result;
}

// ─── Profiles ────────────────────────────────────────────────────────────────

async function loadProfileList() {
    try {
        const res = await fetch('/api/profiles');
        if (!res.ok) return;
        const names = await res.json();
        const select = document.getElementById('profile-select');
        if (!select) return;
        const current = select.value;
        select.innerHTML = '<option value="">-- Select Profile --</option>';
        for (const name of names) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        }
        if (current) select.value = current;
    } catch (e) {
        console.error('Failed to load profiles:', e);
    }
}

function setupProfileButtons() {
    const saveBtn = document.getElementById('btn-profile-save');
    const loadBtn = document.getElementById('btn-profile-load');
    const deleteBtn = document.getElementById('btn-profile-delete');

    if (saveBtn) saveBtn.addEventListener('click', async () => {
        const name = prompt('Profile name:');
        if (!name || !name.trim()) return;
        try {
            const res = await fetch('/api/profiles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name.trim() }),
            });
            if (res.ok) {
                await loadProfileList();
                const select = document.getElementById('profile-select');
                if (select) select.value = name.trim();
            }
        } catch (e) {
            console.error('Failed to save profile:', e);
        }
    });

    if (loadBtn) loadBtn.addEventListener('click', async () => {
        const select = document.getElementById('profile-select');
        const name = select?.value;
        if (!name) { alert('Select a profile first'); return; }
        try {
            const res = await fetch('/api/profiles/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name }),
            });
            if (res.ok) await loadSettings();
        } catch (e) {
            console.error('Failed to load profile:', e);
        }
    });

    if (deleteBtn) deleteBtn.addEventListener('click', async () => {
        const select = document.getElementById('profile-select');
        const name = select?.value;
        if (!name) { alert('Select a profile first'); return; }
        if (!confirm(`Delete profile "${name}"?`)) return;
        try {
            const res = await fetch(`/api/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (res.ok) await loadProfileList();
        } catch (e) {
            console.error('Failed to delete profile:', e);
        }
    });
}
