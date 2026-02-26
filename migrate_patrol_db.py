#!/usr/bin/env python3
"""Migrate patrol data from visual-patrol report.db → kachaka-gemini patrol.db.

Usage:
    python3 migrate_patrol_db.py

Copies patrol_runs, inspection_results, and inspection images.
Old IDs are preserved. Existing data in the target DB is NOT deleted.
"""

import os
import shutil
import sqlite3

# ── Paths ──────────────────────────────────────────────────────────
OLD_DB = os.path.expanduser("~/CodeBase/visual-patrol/data/report/report.db")
OLD_IMAGE_ROOTS = [
    os.path.expanduser("~/CodeBase/visual-patrol/data/robot-a/report/images"),
    os.path.expanduser("~/CodeBase/visual-patrol/data/robot-b/report/images"),
    os.path.expanduser("~/CodeBase/visual-patrol/data/robot-c/report/images"),
]

NEW_DB = os.path.expanduser("~/CodeBase/kachaka-gemini/data/patrol.db")
NEW_IMAGE_DIR = os.path.expanduser("~/CodeBase/kachaka-gemini/data/report/images")

# ── Helpers ────────────────────────────────────────────────────────

def dict_row(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def migrate():
    if not os.path.exists(OLD_DB):
        print(f"Source DB not found: {OLD_DB}")
        return

    os.makedirs(NEW_IMAGE_DIR, exist_ok=True)

    old = sqlite3.connect(OLD_DB, timeout=10)
    old.row_factory = dict_row

    new = sqlite3.connect(NEW_DB, timeout=10)
    new.row_factory = dict_row
    new.execute("PRAGMA journal_mode=WAL")
    new.execute("PRAGMA busy_timeout=5000")

    # Ensure tables exist
    new.execute("""
        CREATE TABLE IF NOT EXISTS patrol_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time       TEXT NOT NULL,
            end_time         TEXT,
            status           TEXT NOT NULL DEFAULT 'Running',
            report_content   TEXT,
            model_id         TEXT,
            video_path       TEXT,
            video_analysis   TEXT,
            input_tokens         INTEGER NOT NULL DEFAULT 0,
            output_tokens        INTEGER NOT NULL DEFAULT 0,
            total_tokens         INTEGER NOT NULL DEFAULT 0,
            report_input_tokens  INTEGER NOT NULL DEFAULT 0,
            report_output_tokens INTEGER NOT NULL DEFAULT 0,
            report_total_tokens  INTEGER NOT NULL DEFAULT 0,
            video_input_tokens   INTEGER NOT NULL DEFAULT 0,
            video_output_tokens  INTEGER NOT NULL DEFAULT 0,
            video_total_tokens   INTEGER NOT NULL DEFAULT 0
        )
    """)
    new.execute("""
        CREATE TABLE IF NOT EXISTS inspection_results (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         INTEGER NOT NULL,
            point_name     TEXT NOT NULL,
            coordinate_x   REAL,
            coordinate_y   REAL,
            prompt         TEXT,
            ai_response    TEXT,
            is_ng          INTEGER NOT NULL DEFAULT 0,
            ai_description TEXT,
            image_path     TEXT,
            timestamp      TEXT NOT NULL,
            input_tokens   INTEGER NOT NULL DEFAULT 0,
            output_tokens  INTEGER NOT NULL DEFAULT 0,
            total_tokens   INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (run_id) REFERENCES patrol_runs(id)
        )
    """)
    new.commit()

    # Check existing max IDs to avoid conflicts
    existing_max_run = new.execute("SELECT MAX(id) FROM patrol_runs").fetchone()["MAX(id)"] or 0
    existing_max_insp = new.execute("SELECT MAX(id) FROM inspection_results").fetchone()["MAX(id)"] or 0

    # ── Migrate patrol_runs ────────────────────────────────────────
    old_runs = old.execute("SELECT * FROM patrol_runs ORDER BY id").fetchall()
    run_count = 0
    for run in old_runs:
        # Skip if ID already exists
        exists = new.execute("SELECT 1 FROM patrol_runs WHERE id = ?", (run["id"],)).fetchone()
        if exists:
            continue

        new.execute("""
            INSERT INTO patrol_runs
                (id, start_time, end_time, status, report_content, model_id,
                 video_path, video_analysis,
                 input_tokens, output_tokens, total_tokens,
                 report_input_tokens, report_output_tokens, report_total_tokens,
                 video_input_tokens, video_output_tokens, video_total_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run["id"],
            run["start_time"] or "",
            run["end_time"],
            run["status"] or "Completed",
            run["report_content"],
            run["model_id"],
            run["video_path"],
            run["video_analysis"],
            run["input_tokens"] or 0,
            run["output_tokens"] or 0,
            run["total_tokens"] or 0,
            run["report_input_tokens"] or 0,
            run["report_output_tokens"] or 0,
            run["report_total_tokens"] or 0,
            run["video_input_tokens"] or 0,
            run["video_output_tokens"] or 0,
            run["video_total_tokens"] or 0,
        ))
        run_count += 1

    new.commit()
    print(f"Migrated {run_count} patrol runs (skipped {len(old_runs) - run_count} existing)")

    # ── Migrate inspection_results ─────────────────────────────────
    old_inspections = old.execute("SELECT * FROM inspection_results ORDER BY id").fetchall()
    insp_count = 0
    img_count = 0
    for insp in old_inspections:
        exists = new.execute("SELECT 1 FROM inspection_results WHERE id = ?", (insp["id"],)).fetchone()
        if exists:
            continue

        new.execute("""
            INSERT INTO inspection_results
                (id, run_id, point_name, coordinate_x, coordinate_y, prompt,
                 ai_response, is_ng, ai_description, image_path, timestamp,
                 input_tokens, output_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            insp["id"],
            insp["run_id"],
            insp["point_name"] or "Unknown",
            insp["coordinate_x"],
            insp["coordinate_y"],
            insp["prompt"],
            insp["ai_response"],
            insp["is_ng"] or 0,
            insp["ai_description"],
            insp["image_path"],
            insp["timestamp"] or "",
            insp["input_tokens"] or 0,
            insp["output_tokens"] or 0,
            insp["total_tokens"] or 0,
        ))
        insp_count += 1

        # ── Copy image ─────────────────────────────────────────────
        if insp["image_path"]:
            copied = False
            for root in OLD_IMAGE_ROOTS:
                src = os.path.join(root, insp["image_path"])
                if os.path.exists(src):
                    dst = os.path.join(NEW_IMAGE_DIR, insp["image_path"])
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    img_count += 1
                    copied = True
                    break
            if not copied:
                print(f"  [WARN] Image not found: {insp['image_path']}")

    new.commit()
    print(f"Migrated {insp_count} inspections (skipped {len(old_inspections) - insp_count} existing)")
    print(f"Copied {img_count} images to {NEW_IMAGE_DIR}")

    old.close()
    new.close()
    print("Done!")


if __name__ == "__main__":
    migrate()
