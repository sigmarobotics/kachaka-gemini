"""Gemini Files API — local + remote file lifecycle management.

Handles uploading files to the Gemini Files API, tracking metadata locally,
and providing enabled file references for injection into conversations.
"""

import asyncio
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from google import genai

from config import DATA_DIR

UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
META_FILE = os.path.join(DATA_DIR, "files.json")
EXPIRY_HOURS = 48

_meta_lock = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ensure_dirs():
    """Create the uploads directory (and parents) if it doesn't exist."""
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def _load_meta() -> list[dict]:
    """Load the file metadata list from disk."""
    if not os.path.exists(META_FILE):
        return []
    with open(META_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    return data


def _save_meta(records: list[dict]):
    """Persist the file metadata list to disk atomically."""
    _ensure_dirs()
    tmp_path = META_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, META_FILE)


def _is_expired(record: dict) -> bool:
    """Return True if the record's ``expires_at`` timestamp is in the past."""
    expires_at = record.get("expires_at", "")
    if not expires_at:
        return True
    try:
        exp = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) >= exp
    except (ValueError, TypeError):
        return True


def _make_id() -> str:
    """Generate a short unique identifier (12 hex chars)."""
    return uuid.uuid4().hex[:12]


# ── Public API ───────────────────────────────────────────────────────────────


async def upload_file(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    api_key: str,
) -> dict:
    """Save a file locally, upload it to Gemini, and store metadata.

    Returns the new file record dict.
    """
    _ensure_dirs()

    file_id = _make_id()
    # Sanitise filename for local storage: strip path components and unsafe chars
    base_name = os.path.basename(filename)
    safe_name = f"{file_id}_{re.sub(r'[^a-zA-Z0-9._-]', '_', base_name)}"
    local_path = os.path.join(UPLOADS_DIR, safe_name)

    # Write bytes to local storage
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    # Upload to Gemini Files API (blocking SDK call)
    client = genai.Client(api_key=api_key)
    try:
        gemini_file = await asyncio.to_thread(
            client.files.upload, file=local_path
        )
    except Exception:
        # Clean up local file on failure
        if os.path.exists(local_path):
            os.remove(local_path)
        raise

    now = datetime.now(timezone.utc)
    record = {
        "id": file_id,
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(file_bytes),
        "local_path": local_path,
        "gemini_name": gemini_file.name,
        "gemini_uri": gemini_file.uri,
        "uploaded_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=EXPIRY_HOURS)).isoformat(),
        "enabled": True,
    }

    with _meta_lock:
        records = _load_meta()
        records.append(record)
        _save_meta(records)

    print(f"[FileService] Uploaded {filename} -> {gemini_file.name}")
    return record


def list_files() -> list[dict]:
    """Return all file records with a computed ``expired`` boolean field."""
    records = _load_meta()
    for r in records:
        r["expired"] = _is_expired(r)
    return records


async def delete_file(file_id: str, api_key: str = "") -> bool:
    """Delete a file from Gemini, local disk, and metadata.

    Returns True if the record was found and removed.
    """
    records = _load_meta()
    target = None
    for r in records:
        if r["id"] == file_id:
            target = r
            break

    if target is None:
        return False

    # Attempt Gemini-side deletion (best-effort)
    gemini_name = target.get("gemini_name", "")
    if gemini_name and api_key:
        try:
            client = genai.Client(api_key=api_key)
            await asyncio.to_thread(client.files.delete, name=gemini_name)
        except Exception as exc:
            print(f"[FileService] Gemini delete failed for {gemini_name}: {exc}")

    # Remove local file
    local_path = target.get("local_path", "")
    if local_path and os.path.exists(local_path):
        try:
            os.remove(local_path)
        except OSError as exc:
            print(f"[FileService] Local delete failed for {local_path}: {exc}")

    # Remove from metadata
    with _meta_lock:
        records = _load_meta()
        records = [r for r in records if r["id"] != file_id]
        _save_meta(records)

    print(f"[FileService] Deleted file {file_id}")
    return True


def toggle_file(file_id: str, enabled: bool) -> bool:
    """Toggle the ``enabled`` flag for a file record.

    Returns True if the record was found and updated.
    """
    with _meta_lock:
        records = _load_meta()
        found = False
        for r in records:
            if r["id"] == file_id:
                r["enabled"] = enabled
                found = True
                break
        if found:
            _save_meta(records)

    if found:
        print(f"[FileService] Toggled file {file_id} enabled={enabled}")
    return found


async def reupload_file(file_id: str, api_key: str) -> dict | None:
    """Re-upload a local file to Gemini (e.g. after expiry) and update metadata.

    Returns the updated record, or None if not found.
    """
    records = _load_meta()
    target = None
    idx = -1
    for i, r in enumerate(records):
        if r["id"] == file_id:
            target = r
            idx = i
            break

    if target is None:
        return None

    local_path = target.get("local_path", "")
    if not local_path or not os.path.exists(local_path):
        print(f"[FileService] Local file missing for {file_id}: {local_path}")
        return None

    client = genai.Client(api_key=api_key)
    gemini_file = await asyncio.to_thread(
        client.files.upload, file=local_path
    )

    now = datetime.now(timezone.utc)
    target["gemini_name"] = gemini_file.name
    target["gemini_uri"] = gemini_file.uri
    target["uploaded_at"] = now.isoformat()
    target["expires_at"] = (now + timedelta(hours=EXPIRY_HOURS)).isoformat()

    with _meta_lock:
        records = _load_meta()
        for i, r in enumerate(records):
            if r["id"] == file_id:
                records[i] = target
                break
        _save_meta(records)

    print(f"[FileService] Re-uploaded {file_id} -> {gemini_file.name}")
    return target


def get_enabled_files() -> list[dict]:
    """Return Gemini references for enabled, non-expired files.

    Each dict contains ``name`` and ``uri`` keys suitable for inclusion
    in a Gemini API request.
    """
    records = _load_meta()
    result = []
    for r in records:
        if r.get("enabled") and not _is_expired(r):
            name = r.get("gemini_name", "")
            uri = r.get("gemini_uri", "")
            if name and uri:
                result.append({"name": name, "uri": uri})
    return result
