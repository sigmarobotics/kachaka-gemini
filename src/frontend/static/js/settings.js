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
        const responseModeSelect = document.getElementById('setting-response-mode');
        const personaInput = document.getElementById('setting-persona');
        const staticKnowledgeInput = document.getElementById('setting-static-knowledge');
        const voiceSelect = document.getElementById('setting-voice');
        const textGoogleSearch = document.getElementById('setting-text-google-search');
        const liveGoogleSearch = document.getElementById('setting-live-google-search');
        const shelfIdsInput = document.getElementById('setting-shelf-ids');
        const cameraToggle = document.getElementById('setting-camera-to-ai');
        const robotIpDisplay = document.getElementById('setting-robot-ip');
        const funcDeclInput = document.getElementById('setting-function-declarations');
        const interimToggle = document.getElementById('setting-enable-interim');
        const interimPhrasesInput = document.getElementById('setting-interim-phrases');

        if (apiKeyInput) apiKeyInput.placeholder = settings.gemini_api_key_masked || 'Enter Gemini API Key';
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

        if (responseModeSelect) responseModeSelect.value = settings.response_mode || 'audio';
        if (personaInput) personaInput.value = settings.persona || '';
        if (staticKnowledgeInput) staticKnowledgeInput.value = settings.static_knowledge || '';

        const knowledgeBaseInput = document.getElementById('setting-knowledge-base');
        if (knowledgeBaseInput) knowledgeBaseInput.value = settings.knowledge_base || '';

        if (voiceSelect) voiceSelect.value = settings.voice_name || 'Aoede';
        if (textGoogleSearch) textGoogleSearch.checked = settings.text_enable_google_search || false;
        if (liveGoogleSearch) liveGoogleSearch.checked = settings.live_enable_google_search || false;
        if (shelfIdsInput) shelfIdsInput.value = (settings.shelf_ids || []).join(', ');
        if (cameraToggle) cameraToggle.checked = settings.enable_camera_to_ai || false;
        if (robotIpDisplay) robotIpDisplay.textContent = settings.robot_ip || 'N/A';

        // Robot background info
        const robotInfoInput = document.getElementById('setting-robot-info');
        if (robotInfoInput) robotInfoInput.value = settings.robot_background_info || '';

        // Function declarations
        if (funcDeclInput) {
            const decls = settings.function_declarations || [];
            funcDeclInput.value = JSON.stringify(decls, null, 2);
            clearJsonError('func-decl-error');
        }

        // Interim response
        if (interimToggle) interimToggle.checked = settings.enable_interim_response || false;
        if (interimPhrasesInput) {
            const phrases = settings.interim_phrases || {};
            interimPhrasesInput.value = JSON.stringify(phrases, null, 2);
            clearJsonError('interim-phrases-error');
        }

        // Update interim audio status display
        updateInterimAudioStatus(settings.interim_audio_keys || []);

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

    // Live JSON validation
    document.getElementById('setting-function-declarations')
        ?.addEventListener('input', () => validateJsonInput('setting-function-declarations', 'func-decl-error', 'array'));
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

// ─── Save ────────────────────────────────────────────────────────────────────

async function saveSettings() {
    const apiKeyInput = document.getElementById('setting-api-key');
    const apiModeSelect = document.getElementById('setting-api-mode');
    const textModelInput = document.getElementById('setting-text-model');
    const liveModelInput = document.getElementById('setting-live-model');
    const responseModeSelect = document.getElementById('setting-response-mode');
    const personaInput = document.getElementById('setting-persona');
    const staticKnowledgeInput = document.getElementById('setting-static-knowledge');
    const voiceSelect = document.getElementById('setting-voice');
    const textGoogleSearch = document.getElementById('setting-text-google-search');
    const liveGoogleSearch = document.getElementById('setting-live-google-search');
    const shelfIdsInput = document.getElementById('setting-shelf-ids');
    const cameraToggle = document.getElementById('setting-camera-to-ai');
    const funcDeclInput = document.getElementById('setting-function-declarations');
    const interimToggle = document.getElementById('setting-enable-interim');
    const interimPhrasesInput = document.getElementById('setting-interim-phrases');

    // Validate JSON fields
    if (!validateJsonInput('setting-function-declarations', 'func-decl-error', 'array')) {
        showJsonError('func-decl-error', 'Fix JSON errors before saving');
        return;
    }
    if (!validateJsonInput('setting-interim-phrases', 'interim-phrases-error', 'object')) {
        showJsonError('interim-phrases-error', 'Fix JSON errors before saving');
        return;
    }

    const updates = {};

    if (apiKeyInput && apiKeyInput.value.trim()) {
        updates.gemini_api_key = apiKeyInput.value.trim();
    }
    if (apiModeSelect) updates.api_mode = apiModeSelect.value;
    if (textModelInput) updates.text_model = textModelInput.value.trim();
    if (liveModelInput) updates.live_model = liveModelInput.value.trim();
    if (responseModeSelect) updates.response_mode = responseModeSelect.value;
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

    const robotInfoInput = document.getElementById('setting-robot-info');
    if (robotInfoInput) updates.robot_background_info = robotInfoInput.value;

    // Parse function declarations
    if (funcDeclInput && funcDeclInput.value.trim()) {
        try {
            updates.function_declarations = JSON.parse(funcDeclInput.value.trim());
        } catch (e) {
            showJsonError('func-decl-error', `Invalid JSON: ${e.message}`);
            return;
        }
    }

    // Parse interim phrases
    if (interimPhrasesInput && interimPhrasesInput.value.trim()) {
        try {
            updates.interim_phrases = JSON.parse(interimPhrasesInput.value.trim());
        } catch (e) {
            showJsonError('interim-phrases-error', `Invalid JSON: ${e.message}`);
            return;
        }
    }

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
    const textarea = document.getElementById('setting-function-declarations');
    if (!textarea) return;
    try {
        const data = JSON.parse(textarea.value.trim());
        downloadJson(data, 'function_declarations.json');
    } catch (e) {
        showJsonError('func-decl-error', 'Fix JSON errors before downloading');
    }
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
            const textarea = document.getElementById('setting-function-declarations');
            if (textarea) {
                let decls;
                if (Array.isArray(data)) {
                    decls = data;
                } else if (Array.isArray(data.function_declarations)) {
                    decls = data.function_declarations;
                } else {
                    alert('Expected a JSON array or { "function_declarations": [...] }');
                    return;
                }
                textarea.value = JSON.stringify(decls, null, 2);
                clearJsonError('func-decl-error');
            }
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
            const textarea = document.getElementById('setting-function-declarations');
            if (textarea && defaults.function_declarations) {
                textarea.value = JSON.stringify(defaults.function_declarations, null, 2);
                clearJsonError('func-decl-error');
            }
        } else {
            await loadSettings();
        }
    } catch (e) {
        console.error('Failed to fetch defaults:', e);
        await loadSettings();
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
