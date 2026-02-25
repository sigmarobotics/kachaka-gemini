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
        const apiModeSelect = document.getElementById('setting-api-mode');
        const textModelInput = document.getElementById('setting-text-model');
        const liveModelInput = document.getElementById('setting-live-model');
        const personaInput = document.getElementById('setting-persona');
        const staticKnowledgeInput = document.getElementById('setting-static-knowledge');
        const voiceSelect = document.getElementById('setting-voice');
        const textGoogleSearch = document.getElementById('setting-text-google-search');
        const liveGoogleSearch = document.getElementById('setting-live-google-search');
        const shelfIdsInput = document.getElementById('setting-shelf-ids');
        const cameraToggle = document.getElementById('setting-camera-to-ai');
        const interimToggle = document.getElementById('setting-enable-interim');
        const interimPhrasesInput = document.getElementById('setting-interim-phrases');

        if (apiKeyInput) apiKeyInput.placeholder = settings.gemini_api_key_masked || 'Enter Gemini API Key';
        const telegramTokenInput = document.getElementById('setting-telegram-token');
        if (telegramTokenInput) telegramTokenInput.placeholder = settings.telegram_bot_token_masked || 'Enter Telegram Bot Token';
        if (apiModeSelect) apiModeSelect.value = settings.api_mode || 'live';

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
        if (shelfIdsInput) shelfIdsInput.value = (settings.shelf_ids || []).join(', ');
        if (cameraToggle) cameraToggle.checked = settings.enable_camera_to_ai || false;
        const robotIpInput = document.getElementById('setting-robot-ip');
        if (robotIpInput) robotIpInput.value = settings.robot_ip || '';

        // Robot background info
        const robotInfoInput = document.getElementById('setting-robot-info');
        if (robotInfoInput) robotInfoInput.value = settings.robot_background_info || '';

        // Function declarations — graphical editor
        const funcDecls = settings.function_declarations || [];
        renderFuncEditor(funcDecls);

        // Interim response
        if (interimToggle) interimToggle.checked = settings.enable_interim_response || false;
        if (interimPhrasesInput) {
            const phrases = settings.interim_phrases || {};
            interimPhrasesInput.value = JSON.stringify(phrases, null, 2);
            clearJsonError('interim-phrases-error');
        }

        // Update interim audio status display
        updateInterimAudioStatus(settings.interim_audio_keys || []);

        // Patrol settings
        const patrolSystemPrompt = document.getElementById('patrol-system-prompt');
        const videoAnalysisPrompt = document.getElementById('video-analysis-prompt');
        const exhibitionTitle = document.getElementById('exhibition-title');
        const drinkShelfId = document.getElementById('drink-shelf-id');
        const telegramChatId = document.getElementById('telegram-chat-id');
        const patrolTelegramNotify = document.getElementById('patrol-telegram-notify');
        const crowdTelegramNotify = document.getElementById('crowd-telegram-notify');

        if (patrolSystemPrompt) patrolSystemPrompt.value = settings.patrol_system_prompt || '';
        if (videoAnalysisPrompt) videoAnalysisPrompt.value = settings.video_analysis_prompt || '';
        if (exhibitionTitle) exhibitionTitle.value = settings.exhibition_title || '';
        if (drinkShelfId) drinkShelfId.value = settings.drink_shelf_id || 'S01';
        if (telegramChatId) telegramChatId.value = settings.telegram_chat_id || '';
        if (patrolTelegramNotify) patrolTelegramNotify.checked = settings.patrol_telegram_notify !== false;
        if (crowdTelegramNotify) crowdTelegramNotify.checked = settings.crowd_telegram_notify !== false;

        // Load patrol model options
        loadPatrolModelOptions(settings.patrol_model || '');

        // Load location options for drink shelf home
        loadDrinkShelfHomeOptions(settings.drink_shelf_home || '');

        // Load patrol points
        renderPatrolPoints(settings.patrol_points || []);

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
        // Silently fail — status will show on next poll
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

    // Robot background info fetch buttons
    document.getElementById('btn-fetch-locations')
        ?.addEventListener('click', fetchLocations);
    document.getElementById('btn-fetch-shelves')
        ?.addEventListener('click', fetchShelves);

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

    // Live JSON validation
    document.getElementById('setting-interim-phrases')
        ?.addEventListener('input', () => validateJsonInput('setting-interim-phrases', 'interim-phrases-error', 'object'));

    // Generate interim audio button
    document.getElementById('btn-generate-interim')
        ?.addEventListener('click', generateInterimAudio);

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

    // Patrol settings
    document.getElementById('btn-query-patrol-models')
        ?.addEventListener('click', () => queryModels('text', 'patrol-model', 'btn-query-patrol-models'));
    document.getElementById('btn-add-patrol-point')
        ?.addEventListener('click', addPatrolPoint);

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

function validateJsonInput(textareaId, errorElId, expectedType) {
    const textarea = document.getElementById(textareaId);
    if (!textarea) return true;
    const val = textarea.value.trim();
    if (!val) {
        clearJsonError(errorElId);
        return true;
    }
    try {
        const parsed = JSON.parse(val);
        if (expectedType === 'array' && !Array.isArray(parsed)) {
            showJsonError(errorElId, 'Must be a JSON array');
            return false;
        }
        if (expectedType === 'object' && (typeof parsed !== 'object' || Array.isArray(parsed))) {
            showJsonError(errorElId, 'Must be a JSON object');
            return false;
        }
        clearJsonError(errorElId);
        return true;
    } catch (e) {
        showJsonError(errorElId, `Invalid JSON: ${e.message}`);
        return false;
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
    const params = fn.parameters || { type: 'object', properties: {}, required: [] };
    const props = params.properties || {};
    const required = params.required || [];

    return `
    <div class="func-card" data-index="${index}">
        <div class="func-card-header" onclick="this.parentElement.classList.toggle('open')">
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

        result.push({
            name,
            description: desc,
            parameters: { type: 'object', properties, required },
        });
    });
    return result;
}

// Global functions for onclick handlers
window.deleteFuncCard = function(index) {
    const card = document.querySelector(`.func-card[data-index="${index}"]`);
    if (card && confirm('Delete this function?')) card.remove();
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
    const apiModeSelect = document.getElementById('setting-api-mode');
    const textModelInput = document.getElementById('setting-text-model');
    const liveModelInput = document.getElementById('setting-live-model');
    const personaInput = document.getElementById('setting-persona');
    const staticKnowledgeInput = document.getElementById('setting-static-knowledge');
    const voiceSelect = document.getElementById('setting-voice');
    const textGoogleSearch = document.getElementById('setting-text-google-search');
    const liveGoogleSearch = document.getElementById('setting-live-google-search');
    const shelfIdsInput = document.getElementById('setting-shelf-ids');
    const cameraToggle = document.getElementById('setting-camera-to-ai');
    const interimToggle = document.getElementById('setting-enable-interim');
    const interimPhrasesInput = document.getElementById('setting-interim-phrases');

    // Validate JSON fields
    if (!validateJsonInput('setting-interim-phrases', 'interim-phrases-error', 'object')) {
        showJsonError('interim-phrases-error', 'Fix JSON errors before saving');
        return;
    }

    const updates = {};

    if (apiKeyInput && apiKeyInput.value.trim()) {
        updates.gemini_api_key = apiKeyInput.value.trim();
    }
    const telegramTokenInput = document.getElementById('setting-telegram-token');
    if (telegramTokenInput && telegramTokenInput.value.trim()) {
        updates.telegram_bot_token = telegramTokenInput.value.trim();
    }
    if (apiModeSelect) updates.api_mode = apiModeSelect.value;
    if (textModelInput) updates.text_model = textModelInput.value.trim();
    if (liveModelInput) updates.live_model = liveModelInput.value.trim();
    if (personaInput) updates.persona = personaInput.value;
    if (staticKnowledgeInput) updates.static_knowledge = staticKnowledgeInput.value;
    const knowledgeBaseInput = document.getElementById('setting-knowledge-base');
    if (knowledgeBaseInput) updates.knowledge_base = knowledgeBaseInput.value;
    if (voiceSelect) updates.voice_name = voiceSelect.value;
    if (textGoogleSearch) updates.text_enable_google_search = textGoogleSearch.checked;
    if (liveGoogleSearch) updates.live_enable_google_search = liveGoogleSearch.checked;
    if (shelfIdsInput) {
        updates.shelf_ids = shelfIdsInput.value
            .split(',')
            .map(s => s.trim())
            .filter(s => s.length > 0);
    }
    if (cameraToggle) updates.enable_camera_to_ai = cameraToggle.checked;
    if (interimToggle) updates.enable_interim_response = interimToggle.checked;

    const robotIpInput = document.getElementById('setting-robot-ip');
    if (robotIpInput && robotIpInput.value.trim()) {
        updates.robot_ip = robotIpInput.value.trim();
    }

    const robotInfoInput = document.getElementById('setting-robot-info');
    if (robotInfoInput) updates.robot_background_info = robotInfoInput.value;

    // Function declarations from graphical editor
    updates.function_declarations = collectFuncDeclarations();

    // Parse interim phrases
    if (interimPhrasesInput && interimPhrasesInput.value.trim()) {
        try {
            updates.interim_phrases = JSON.parse(interimPhrasesInput.value.trim());
        } catch (e) {
            showJsonError('interim-phrases-error', `Invalid JSON: ${e.message}`);
            return;
        }
    }

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
    const robotInfo = document.getElementById('setting-robot-info');
    downloadJson({
        persona: persona?.value || '',
        static_knowledge: staticKnowledge?.value || '',
        knowledge_base: knowledgeBase?.value || '',
        robot_background_info: robotInfo?.value || '',
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
            const robotInfoEl = document.getElementById('setting-robot-info');
            if (data.persona && personaEl) personaEl.value = data.persona;
            if (data.static_knowledge && staticEl) staticEl.value = data.static_knowledge;
            if (data.knowledge_base != null && knowledgeEl) knowledgeEl.value = typeof data.knowledge_base === 'string' ? data.knowledge_base : JSON.stringify(data.knowledge_base, null, 2);
            if (data.robot_background_info && robotInfoEl) robotInfoEl.value = data.robot_background_info;
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

            // When all files are read, join and set
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

// ─── Robot Background Info ───────────────────────────────────────────────────

async function fetchLocations() {
    const btn = document.getElementById('btn-fetch-locations');
    const textarea = document.getElementById('setting-robot-info');
    if (!btn || !textarea) return;

    btn.disabled = true;
    btn.textContent = 'Fetching...';
    try {
        const res = await fetch('/api/locations');
        const data = await res.json();
        const lines = ['可用地點:'];
        for (const loc of data) {
            lines.push(`- ${loc.name} (id: ${loc.id})`);
        }
        textarea.value = lines.join('\n');
    } catch (e) {
        console.error('Failed to fetch locations:', e);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Fetch Locations';
    }
}

async function fetchShelves() {
    const btn = document.getElementById('btn-fetch-shelves');
    const textarea = document.getElementById('setting-robot-info');
    if (!btn || !textarea) return;

    btn.disabled = true;
    btn.textContent = 'Fetching...';
    try {
        const res = await fetch('/api/shelves');
        const data = await res.json();
        const lines = ['\n可用貨架:'];
        for (const shelf of data) {
            let entry = `- ${shelf.name} (id: ${shelf.id}`;
            if (shelf.home) entry += `, home: ${shelf.home}`;
            entry += ')';
            lines.push(entry);
        }
        // Append to existing content
        const current = textarea.value.trim();
        textarea.value = current ? current + '\n' + lines.join('\n') : lines.join('\n');
    } catch (e) {
        console.error('Failed to fetch shelves:', e);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Fetch Shelves';
    }
}

// ─── Interim Audio Generation ────────────────────────────────────────────────

function updateInterimAudioStatus(audioKeys) {
    const statusEl = document.getElementById('interim-audio-status');
    if (!statusEl) return;

    if (!audioKeys || audioKeys.length === 0) {
        statusEl.innerHTML = '<span class="interim-none">No audio generated yet</span>';
        return;
    }

    const items = audioKeys.map(k =>
        `<span class="interim-item">${k}</span>`
    );
    statusEl.innerHTML = `<span class="interim-label">Generated:</span> ${items.join(' ')}`;
}

async function generateInterimAudio() {
    const phrasesInput = document.getElementById('setting-interim-phrases');
    const statusEl = document.getElementById('interim-generate-status');
    const btn = document.getElementById('btn-generate-interim');

    if (!phrasesInput || !btn) return;

    // Validate phrases JSON
    if (!validateJsonInput('setting-interim-phrases', 'interim-phrases-error', 'object')) {
        return;
    }

    let phrases;
    try {
        phrases = JSON.parse(phrasesInput.value.trim());
    } catch (e) {
        showJsonError('interim-phrases-error', `Invalid JSON: ${e.message}`);
        return;
    }

    if (Object.keys(phrases).length === 0) {
        showJsonError('interim-phrases-error', 'No phrases to generate');
        return;
    }

    // Save phrases first
    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interim_phrases: phrases }),
    });

    // Show loading state
    btn.disabled = true;
    btn.textContent = 'Generating...';
    if (statusEl) statusEl.textContent = '';

    try {
        const res = await fetch('/api/generate_interim_audio', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phrases }),
        });

        const data = await res.json();

        if (res.ok) {
            if (statusEl) {
                statusEl.textContent = `Generated ${data.generated.length} audio clips`;
                statusEl.className = 'interim-status success';
            }
            await loadSettings();
        } else {
            if (statusEl) {
                statusEl.textContent = `Error: ${data.error}`;
                statusEl.className = 'interim-status error';
            }
        }
    } catch (e) {
        console.error('Failed to generate interim audio:', e);
        if (statusEl) {
            statusEl.textContent = `Error: ${e.message}`;
            statusEl.className = 'interim-status error';
        }
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Audio with Live API';
    }
}

// ─── Patrol & Exhibition Settings ─────────────────────────────────────────────

// Cached locations list (fetched once per page load)
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

async function loadPatrolModelOptions(selectedModel) {
    const select = document.getElementById('patrol-model');
    if (!select) return;

    // Add empty option for "use text model"
    if (!select.querySelector('option[value=""]')) {
        const emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = '(使用 Text 模型)';
        select.appendChild(emptyOpt);
    }

    // Ensure selected model is in the list
    if (selectedModel && !select.querySelector(`option[value="${selectedModel}"]`)) {
        const opt = document.createElement('option');
        opt.value = selectedModel;
        opt.textContent = selectedModel;
        select.appendChild(opt);
    }
    select.value = selectedModel;
}

async function loadDrinkShelfHomeOptions(selectedLocation) {
    const select = document.getElementById('drink-shelf-home');
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

function renderPatrolPoints(points) {
    const container = document.getElementById('patrol-points-list');
    if (!container) return;
    container.innerHTML = '';

    for (let i = 0; i < points.length; i++) {
        const pt = points[i];
        appendPatrolPointCard(container, pt, i);
    }
    window._patrolPointCounter = points.length;
}

function appendPatrolPointCard(container, pt, index) {
    const card = document.createElement('div');
    card.className = 'patrol-point-card';
    card.dataset.index = index;
    card.innerHTML = `
        <div class="patrol-point-header">
            <span class="patrol-point-label">巡檢點 #${index + 1}</span>
            <button class="param-delete-btn" onclick="deletePatrolPoint(${index})" title="刪除">DEL</button>
        </div>
        <div class="form-group" style="margin-bottom: 6px;">
            <label>地點</label>
            <select class="patrol-point-location">
                <option value="">Loading...</option>
            </select>
        </div>
        <div class="form-group" style="margin-bottom: 6px;">
            <label>分析提示 (選填)</label>
            <textarea class="patrol-point-prompt" rows="2" placeholder="此點位的額外分析提示...">${escapeAttr(pt.prompt || '')}</textarea>
        </div>
    `;
    container.appendChild(card);

    // Populate location dropdown asynchronously
    const locationSelect = card.querySelector('.patrol-point-location');
    fetchLocationsList().then(locations => {
        locationSelect.innerHTML = '';
        for (const loc of locations) {
            const opt = document.createElement('option');
            opt.value = loc.id;
            opt.textContent = `${loc.name} (${loc.id})`;
            locationSelect.appendChild(opt);
        }
        // Set selected value
        if (pt.location_id) {
            locationSelect.value = pt.location_id;
        }
        // If name matches a location but no id was stored, try matching by name
        if (!pt.location_id && pt.name) {
            const match = locations.find(l => l.name === pt.name);
            if (match) locationSelect.value = match.id;
        }
    });
}

function addPatrolPoint() {
    const container = document.getElementById('patrol-points-list');
    if (!container) return;
    const index = window._patrolPointCounter || 0;
    appendPatrolPointCard(container, {}, index);
    window._patrolPointCounter = index + 1;
}

window.deletePatrolPoint = function(index) {
    const card = document.querySelector(`.patrol-point-card[data-index="${index}"]`);
    if (card) card.remove();
};

function collectPatrolPoints() {
    const cards = document.querySelectorAll('.patrol-point-card');
    const result = [];
    cards.forEach(card => {
        const locationSelect = card.querySelector('.patrol-point-location');
        const promptTextarea = card.querySelector('.patrol-point-prompt');
        const locationId = locationSelect?.value || '';
        const selectedOption = locationSelect?.selectedOptions[0];
        const name = selectedOption ? selectedOption.textContent.replace(/\s*\(.*\)$/, '') : '';
        const prompt = promptTextarea?.value?.trim() || '';
        if (locationId) {
            result.push({ name, location_id: locationId, prompt });
        }
    });
    return result;
}

function collectPatrolSettings() {
    const result = {};

    const patrolModel = document.getElementById('patrol-model');
    const patrolSystemPrompt = document.getElementById('patrol-system-prompt');
    const videoAnalysisPrompt = document.getElementById('video-analysis-prompt');
    const exhibitionTitle = document.getElementById('exhibition-title');
    const drinkShelfId = document.getElementById('drink-shelf-id');
    const drinkShelfHome = document.getElementById('drink-shelf-home');
    const telegramChatId = document.getElementById('telegram-chat-id');
    const patrolTelegramNotify = document.getElementById('patrol-telegram-notify');
    const crowdTelegramNotify = document.getElementById('crowd-telegram-notify');

    if (patrolModel) result.patrol_model = patrolModel.value;
    if (patrolSystemPrompt) result.patrol_system_prompt = patrolSystemPrompt.value;
    if (videoAnalysisPrompt) result.video_analysis_prompt = videoAnalysisPrompt.value;
    if (exhibitionTitle) result.exhibition_title = exhibitionTitle.value;
    if (drinkShelfId) result.drink_shelf_id = drinkShelfId.value;
    if (drinkShelfHome) result.drink_shelf_home = drinkShelfHome.value;
    if (telegramChatId) result.telegram_chat_id = telegramChatId.value;
    if (patrolTelegramNotify) result.patrol_telegram_notify = patrolTelegramNotify.checked;
    if (crowdTelegramNotify) result.crowd_telegram_notify = crowdTelegramNotify.checked;

    result.patrol_points = collectPatrolPoints();

    return result;
}
