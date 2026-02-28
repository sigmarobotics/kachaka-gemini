// files.js — File management for Gemini Files API

export function initFiles() {
    const chooseBtn = document.getElementById('btn-choose-file');
    const fileInput = document.getElementById('file-upload-input');
    const uploadBtn = document.getElementById('btn-upload-file');

    if (chooseBtn && fileInput) {
        chooseBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', () => {
            const file = fileInput.files[0];
            const nameEl = document.getElementById('file-upload-name');
            if (file) {
                if (nameEl) nameEl.textContent = `${file.name} (${formatSize(file.size)})`;
                if (uploadBtn) uploadBtn.disabled = false;
            } else {
                if (nameEl) nameEl.textContent = 'No file selected';
                if (uploadBtn) uploadBtn.disabled = true;
            }
        });
    }

    if (uploadBtn) {
        uploadBtn.addEventListener('click', handleUpload);
    }

    // Load file list on init
    loadFileList();
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatExpiry(expiresAt) {
    if (!expiresAt) return 'Unknown';
    const exp = new Date(expiresAt);
    const now = new Date();
    const diffMs = exp - now;
    if (diffMs <= 0) return 'EXPIRED';
    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    const mins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
    if (hours > 0) return `Expires in ${hours}h ${mins}m`;
    return `Expires in ${mins}m`;
}

async function handleUpload() {
    const fileInput = document.getElementById('file-upload-input');
    const uploadBtn = document.getElementById('btn-upload-file');
    const progressDiv = document.getElementById('file-upload-progress');
    const statusEl = document.getElementById('file-upload-status');
    const progressFill = document.getElementById('file-progress-fill');

    const file = fileInput?.files[0];
    if (!file) return;

    // Validate size client-side
    if (file.size > 2 * 1024 * 1024 * 1024) {
        alert('File too large (max 2GB)');
        return;
    }

    // Show progress
    if (progressDiv) progressDiv.style.display = 'flex';
    if (uploadBtn) uploadBtn.disabled = true;
    if (statusEl) statusEl.textContent = 'Uploading...';
    if (progressFill) progressFill.style.width = '30%';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/files/upload', {
            method: 'POST',
            body: formData,
        });

        if (progressFill) progressFill.style.width = '100%';

        if (res.ok) {
            if (statusEl) statusEl.textContent = 'Upload complete!';
            // Reset input
            fileInput.value = '';
            const nameEl = document.getElementById('file-upload-name');
            if (nameEl) nameEl.textContent = 'No file selected';
            // Reload list
            await loadFileList();
        } else {
            const data = await res.json();
            if (statusEl) statusEl.textContent = `Error: ${data.error || 'Upload failed'}`;
        }
    } catch (e) {
        console.error('Upload error:', e);
        if (statusEl) statusEl.textContent = `Error: ${e.message}`;
    } finally {
        if (uploadBtn) uploadBtn.disabled = false;
        setTimeout(() => {
            if (progressDiv) progressDiv.style.display = 'none';
            if (progressFill) progressFill.style.width = '0%';
        }, 3000);
    }
}

async function loadFileList() {
    const container = document.getElementById('file-list');
    if (!container) return;

    try {
        const res = await fetch('/api/files');
        const files = await res.json();

        if (!files || files.length === 0) {
            container.innerHTML = '<div class="file-list-empty">No files uploaded yet</div>';
            return;
        }

        container.innerHTML = files.map(f => renderFileItem(f)).join('');

        // Bind event listeners
        container.querySelectorAll('.file-item-checkbox').forEach(cb => {
            cb.addEventListener('change', () => toggleFile(cb.dataset.fileId, cb.checked));
        });
        container.querySelectorAll('.btn-delete').forEach(btn => {
            btn.addEventListener('click', () => deleteFile(btn.dataset.fileId));
        });
        container.querySelectorAll('.btn-reupload').forEach(btn => {
            btn.addEventListener('click', () => reuploadFile(btn.dataset.fileId));
        });
    } catch (e) {
        console.error('Failed to load files:', e);
        container.innerHTML = '<div class="file-list-empty">Failed to load files</div>';
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function renderFileItem(f) {
    const expired = f.expired;
    const expiryText = formatExpiry(f.expires_at);
    const sizeText = formatSize(f.size_bytes);
    const safeName = escapeHtml(f.filename);

    return `
    <div class="file-item${expired ? ' expired' : ''}">
        <input type="checkbox" class="file-item-checkbox"
               data-file-id="${f.id}"
               ${f.enabled && !expired ? 'checked' : ''}
               ${expired ? 'disabled' : ''}>
        <div class="file-item-info">
            <div class="file-item-name" title="${safeName}">${safeName}</div>
            <div class="file-item-meta">
                ${sizeText}
                &middot;
                <span class="${expired ? 'file-item-expired' : ''}">${expiryText}</span>
            </div>
        </div>
        <div class="file-item-actions">
            ${expired ? `<button class="btn-reupload" data-file-id="${f.id}">Re-upload</button>` : ''}
            <button class="btn-delete" data-file-id="${f.id}">Delete</button>
        </div>
    </div>`;
}

async function toggleFile(fileId, enabled) {
    try {
        await fetch(`/api/files/${fileId}/toggle`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
    } catch (e) {
        console.error('Failed to toggle file:', e);
    }
}

async function deleteFile(fileId) {
    if (!confirm('Delete this file?')) return;
    try {
        const res = await fetch(`/api/files/${fileId}`, { method: 'DELETE' });
        if (res.ok) {
            await loadFileList();
        } else {
            const data = await res.json();
            alert(data.error || 'Failed to delete file');
        }
    } catch (e) {
        console.error('Failed to delete file:', e);
    }
}

async function reuploadFile(fileId) {
    try {
        const res = await fetch(`/api/files/${fileId}/reupload`, { method: 'POST' });
        if (res.ok) {
            await loadFileList();
        } else {
            const data = await res.json();
            alert(data.error || 'Failed to re-upload file');
        }
    } catch (e) {
        console.error('Failed to re-upload file:', e);
    }
}
