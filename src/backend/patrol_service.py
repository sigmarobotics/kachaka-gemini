"""Patrol Service — orchestrates multi-point patrol with Gemini VLM inspection.

Accepts start_patrol(), runs in a background daemon thread, and exposes
status/progress via get_status() and cancel_patrol().

Flow: move to each patrol point -> capture frame -> VLM analysis -> save to DB
After all points: generate AI summary -> update DB -> Telegram notification
"""

import base64
import json
import logging
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum

from google import genai
from pydantic import BaseModel, Field

import patrol_db
import settings_service
from config import DATA_DIR
from frame_hub import frame_hub
from robot_manager import robot_manager, _send_telegram_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

REPORT_DIR = os.path.join(DATA_DIR, "report")
IMAGE_DIR = os.path.join(REPORT_DIR, "images")
VIDEO_DIR = os.path.join(REPORT_DIR, "video")

# Ensure directories exist at import time
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# UTC+8 timezone
# ---------------------------------------------------------------------------

UTC8 = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Pydantic schema for structured VLM output
# ---------------------------------------------------------------------------


class InspectionResult(BaseModel):
    is_NG: bool = Field(description="True if abnormal/NG condition detected, False if normal/OK")
    Description: str = Field(description="Description of findings. Empty string if OK.")


# ---------------------------------------------------------------------------
# Patrol status enum
# ---------------------------------------------------------------------------


class PatrolStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    MOVING = "moving"
    INSPECTING = "inspecting"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


# ---------------------------------------------------------------------------
# PatrolService
# ---------------------------------------------------------------------------


class PatrolService:
    """Singleton patrol flow controller."""

    def __init__(self):
        self._status: PatrolStatus = PatrolStatus.IDLE
        self._run_id: int | None = None
        self._current_point: int = 0
        self._total_points: int = 0
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._progress_callbacks: list = []
        self._error_message: str = ""

    # ── Properties ────────────────────────────────────────────────

    @property
    def status(self) -> str:
        return self._status.value

    @property
    def is_patrolling(self) -> bool:
        return self._status not in (
            PatrolStatus.IDLE,
            PatrolStatus.COMPLETED,
            PatrolStatus.CANCELLED,
            PatrolStatus.ERROR,
        )

    # ── Public API ────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current patrol status and progress."""
        return {
            "status": self._status.value,
            "run_id": self._run_id,
            "current_point": self._current_point,
            "total_points": self._total_points,
            "error": self._error_message if self._status == PatrolStatus.ERROR else "",
        }

    def start_patrol(self, points: list | None = None) -> dict:
        """Start a patrol run. Returns immediately; patrol runs in background.

        Args:
            points: List of location IDs (strings) or list of dicts with
                    {name, location_id, prompt} for backward compatibility.
                    If None, reads from settings.

        Returns:
            {"ok": bool, "run_id": int} on success.
        """
        with self._lock:
            if self.is_patrolling:
                return {"ok": False, "error": "Patrol already in progress"}

            if not robot_manager.connected:
                return {"ok": False, "error": "Robot not connected"}

            settings = settings_service.get_all()
            api_key = settings.get("gemini_api_key", "")
            if not api_key:
                return {"ok": False, "error": "Gemini API key not configured"}

            if points is None:
                points = settings_service.get("patrol_points", [])

            if not points:
                return {"ok": False, "error": "No patrol points configured"}

            # Normalize: convert list of IDs to list of dicts
            normalized = self._normalize_points(points)
            if not normalized:
                return {"ok": False, "error": "Could not resolve any patrol points"}

            # Initialise DB
            patrol_db.init_db()

            model_id = settings.get("text_model", "gemini-3.5-flash")

            # Create DB run
            start_time = datetime.now(UTC8).isoformat()
            run_id = patrol_db.create_run(start_time=start_time, model_id=model_id)

            # Reset state
            self._status = PatrolStatus.STARTING
            self._run_id = run_id
            self._current_point = 0
            self._total_points = len(normalized)
            self._cancel_event.clear()
            self._error_message = ""

            # Spawn background thread
            self._thread = threading.Thread(
                target=self._patrol_loop,
                args=(run_id, normalized, api_key, model_id, settings),
                daemon=True,
                name=f"patrol-{run_id}",
            )
            self._thread.start()

            logger.info("Patrol started: run_id=%d, points=%d", run_id, len(normalized))
            return {"ok": True, "run_id": run_id}

    def _normalize_points(self, points: list) -> list[dict]:
        """Convert patrol points to normalized format [{name, location_id, prompt}]."""
        from location_service import location_service
        all_locs = location_service.get_all_locations()
        loc_by_id = {loc["id"]: loc for loc in all_locs}
        default_prompt = settings_service.get(
            "patrol_image_prompt",
            "請分析這張照片中的環境狀況。繁體中文。",
        )

        result = []
        for pt in points:
            if isinstance(pt, str):
                # Location ID string
                loc = loc_by_id.get(pt)
                if loc:
                    result.append({
                        "name": loc["name"],
                        "location_id": pt,
                        "prompt": default_prompt,
                    })
            elif isinstance(pt, dict):
                # Legacy dict format
                result.append({
                    "name": pt.get("name", ""),
                    "location_id": pt.get("location_id", ""),
                    "prompt": pt.get("prompt", default_prompt),
                })
        return result

    def cancel_patrol(self) -> dict:
        """Cancel the current patrol run."""
        if not self.is_patrolling:
            return {"ok": False, "error": "No patrol in progress"}

        self._cancel_event.set()
        try:
            robot_manager.cancel_command()
        except Exception as e:
            logger.warning("cancel_command during patrol cancel: %s", e)

        logger.info("Patrol cancel requested: run_id=%s", self._run_id)
        return {"ok": True}

    # ── Progress callbacks ────────────────────────────────────────

    def register_progress_callback(self, cb):
        if cb not in self._progress_callbacks:
            self._progress_callbacks.append(cb)

    def unregister_progress_callback(self, cb):
        try:
            self._progress_callbacks.remove(cb)
        except ValueError:
            pass

    def _emit_progress(self, event: str, data: dict | None = None):
        payload = {"event": event, "run_id": self._run_id, **(data or {})}
        for cb in list(self._progress_callbacks):
            try:
                cb(event, payload)
            except Exception as e:
                logger.warning("Progress callback error: %s", e)

    # ── Background patrol loop ────────────────────────────────────

    def _patrol_loop(
        self,
        run_id: int,
        points: list[dict],
        api_key: str,
        model_id: str,
        settings: dict,
    ):
        """Main patrol loop — runs in a daemon thread."""
        total_input_tokens = 0
        total_output_tokens = 0
        total_total_tokens = 0
        inspections: list[dict] = []

        try:
            client = genai.Client(api_key=api_key)
            system_prompt = self._build_inspection_system_prompt(settings)

            for idx, point in enumerate(points):
                if self._cancel_event.is_set():
                    self._finish_cancelled(run_id, total_input_tokens, total_output_tokens, total_total_tokens)
                    return

                point_name = point.get("name", f"Point-{idx + 1}")
                location_id = point.get("location_id", "")
                prompt = point.get("prompt", "請檢查此位置是否有異常。")

                self._current_point = idx + 1

                # ── MOVE ──
                self._status = PatrolStatus.MOVING
                self._emit_progress("moving", {
                    "current_point": idx + 1,
                    "total_points": len(points),
                    "point_name": point_name,
                })
                logger.info("Patrol [%d/%d] Moving to %s (%s)",
                            idx + 1, len(points), point_name, location_id)

                move_result = robot_manager.execute_function_call(
                    "move_to_location", {"location_id": location_id}
                )

                if self._cancel_event.is_set():
                    self._finish_cancelled(run_id, total_input_tokens, total_output_tokens, total_total_tokens)
                    return

                if not move_result.get("ok"):
                    logger.warning("Move to %s failed: %s", point_name, move_result.get("error", "unknown"))
                    continue

                # ── INSPECT ──
                self._status = PatrolStatus.INSPECTING
                self._emit_progress("inspecting", {
                    "current_point": idx + 1,
                    "total_points": len(points),
                    "point_name": point_name,
                })
                logger.info("Patrol [%d/%d] Inspecting %s", idx + 1, len(points), point_name)

                jpeg_bytes = frame_hub.wait_for_fresh_frame(timeout=10)
                if not jpeg_bytes:
                    logger.warning("No frame captured at %s, skipping", point_name)
                    continue

                # Save image
                image_id = uuid.uuid4().hex[:8]
                image_filename = f"{point_name}_{image_id}.jpg"
                image_path = os.path.join(IMAGE_DIR, image_filename)
                with open(image_path, "wb") as f:
                    f.write(jpeg_bytes)

                state = robot_manager.get_state()
                pose = state.get("pose", {})

                inspection = self._inspect_with_gemini(
                    client=client, model_id=model_id,
                    system_prompt=system_prompt, point_name=point_name,
                    prompt=prompt, jpeg_bytes=jpeg_bytes,
                )

                # Rename image with OK/NG tag
                status_tag = "NG" if inspection["is_ng"] else "OK"
                new_image_filename = f"{point_name}_{status_tag}_{image_id}.jpg"
                new_image_path = os.path.join(IMAGE_DIR, new_image_filename)
                try:
                    os.rename(image_path, new_image_path)
                    image_path = new_image_path
                except OSError as e:
                    logger.warning("Failed to rename image: %s", e)

                patrol_db.insert_inspection(
                    run_id=run_id, point_name=point_name,
                    coordinate_x=pose.get("x", 0.0),
                    coordinate_y=pose.get("y", 0.0),
                    prompt=prompt,
                    ai_response=inspection.get("raw_response", ""),
                    is_ng=1 if inspection["is_ng"] else 0,
                    ai_description=inspection["description"],
                    image_path=image_path,
                    input_tokens=inspection.get("input_tokens", 0),
                    output_tokens=inspection.get("output_tokens", 0),
                    total_tokens=inspection.get("total_tokens", 0),
                )

                total_input_tokens += inspection.get("input_tokens", 0)
                total_output_tokens += inspection.get("output_tokens", 0)
                total_total_tokens += inspection.get("total_tokens", 0)

                inspections.append({
                    "point_name": point_name,
                    "is_ng": inspection["is_ng"],
                    "description": inspection["description"],
                })

                self._emit_progress("inspection_done", {
                    "current_point": idx + 1,
                    "total_points": len(points),
                    "point_name": point_name,
                    "is_ng": inspection["is_ng"],
                    "description": inspection["description"],
                })

            if self._cancel_event.is_set():
                self._finish_cancelled(run_id, total_input_tokens, total_output_tokens, total_total_tokens)
                return

            # ── Return home ──
            try:
                robot_manager.execute_function_call("move_to_location", {"location_id": "home"})
            except Exception:
                pass

            # ── GENERATE SUMMARY ──
            self._status = PatrolStatus.GENERATING_REPORT
            self._emit_progress("generating_report", {})
            logger.info("Patrol generating summary for run_id=%d", run_id)

            summary = self._generate_summary(
                client=client, model_id=model_id, inspections=inspections,
            )

            end_time = datetime.now(UTC8).isoformat()
            patrol_db.update_run(
                run_id, status="Completed", end_time=end_time,
                report_content=summary.get("text", ""),
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_total_tokens,
                report_input_tokens=summary.get("input_tokens", 0),
                report_output_tokens=summary.get("output_tokens", 0),
                report_total_tokens=summary.get("total_tokens", 0),
            )

            # Telegram notification
            if settings_service.get("patrol_telegram_notify", True):
                try:
                    ng_count = sum(1 for i in inspections if i.get("is_ng"))
                    tg_message = (
                        f"*巡檢完成* ({len(inspections)} 個檢查點)\n"
                        f"正常: {len(inspections) - ng_count} | 異常: {ng_count}\n\n"
                        + (summary.get("text", "")[:500])
                    )
                    _send_telegram_text(tg_message)

                    # Try to generate and send PDF
                    try:
                        from report_service import report_service as _report_svc
                        from telegram_service import telegram_manager
                        import asyncio
                        pdf_bytes = _report_svc.generate_patrol_pdf(run_id)
                        if pdf_bytes:
                            loop = asyncio.new_event_loop()
                            loop.run_until_complete(
                                telegram_manager.send_patrol_notification(tg_message, pdf_bytes)
                            )
                            loop.close()
                    except Exception as e:
                        logger.warning("PDF notification failed: %s", e)
                except Exception as e:
                    logger.error("Telegram notification failed: %s", e)

            self._status = PatrolStatus.COMPLETED
            self._emit_progress("completed", {"report": summary.get("text", "")})
            logger.info("Patrol completed: run_id=%d", run_id)

        except Exception as e:
            logger.error("Patrol error: %s\n%s", e, traceback.format_exc())
            self._status = PatrolStatus.ERROR
            self._error_message = str(e)
            try:
                end_time = datetime.now(UTC8).isoformat()
                patrol_db.update_run(
                    run_id, status="Error", end_time=end_time,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    total_tokens=total_total_tokens,
                )
            except Exception:
                pass
            self._emit_progress("error", {"error": str(e)})

    # ── Cancellation helper ───────────────────────────────────────

    def _finish_cancelled(self, run_id, total_input_tokens, total_output_tokens, total_total_tokens):
        self._status = PatrolStatus.CANCELLED
        end_time = datetime.now(UTC8).isoformat()
        try:
            patrol_db.update_run(
                run_id, status="Cancelled", end_time=end_time,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_total_tokens,
            )
        except Exception as e:
            logger.warning("Failed to update cancelled run: %s", e)
        self._emit_progress("cancelled", {})
        logger.info("Patrol cancelled: run_id=%d", run_id)

    # ── Gemini VLM inspection ─────────────────────────────────────

    def _build_inspection_system_prompt(self, settings: dict) -> str:
        return (
            "你是一個巡檢 AI 視覺分析助手。\n"
            "你會收到一張來自機器人攝影機的圖片和巡檢提示。\n"
            "請仔細分析圖片，判斷是否有異常（NG）或一切正常（OK）。\n"
            "回覆必須是 JSON 格式，包含 is_NG (bool) 和 Description (string)。\n"
            "如果正常，Description 可以為空字串。\n"
            "如果異常，Description 需描述發現的問題。\n"
            "請用繁體中文回答。"
        )

    def _inspect_with_gemini(self, client, model_id, system_prompt,
                             point_name, prompt, jpeg_bytes) -> dict:
        try:
            user_prompt = f"巡檢點：{point_name}\n巡檢指示：{prompt}"
            response_format = {
                "type": "text",
                "mime_type": "application/json",
                "schema": InspectionResult.model_json_schema(),
            }
            interaction = client.interactions.create(
                model=model_id,
                system_instruction=system_prompt,
                input=[
                    {"type": "text", "text": user_prompt},
                    {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(jpeg_bytes).decode("utf-8")},
                ],
                response_format=response_format,
            )
            usage = interaction.usage
            input_tokens = (getattr(usage, "total_input_tokens", 0) or 0) if usage else 0
            output_tokens = (getattr(usage, "total_output_tokens", 0) or 0) if usage else 0
            total_tokens = (getattr(usage, "total_tokens", 0) or 0) if usage else 0

            raw_text = interaction.output_text or "{}"
            try:
                parsed = json.loads(raw_text)
                is_ng = parsed.get("is_NG", False)
                description = parsed.get("Description", "")
            except json.JSONDecodeError:
                logger.warning("Failed to parse VLM JSON: %s", raw_text[:200])
                is_ng = False
                description = raw_text

            return {
                "is_ng": is_ng, "description": description,
                "raw_response": raw_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }
        except Exception as e:
            logger.error("VLM inspection error at %s: %s", point_name, e)
            return {
                "is_ng": False, "description": f"Inspection error: {e}",
                "raw_response": "",
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            }

    # ── AI summary generation ─────────────────────────────────────

    def _generate_summary(self, client, model_id, inspections) -> dict:
        try:
            lines = []
            ng_count = ok_count = 0
            for insp in inspections:
                status_str = "NG (異常)" if insp["is_ng"] else "OK (正常)"
                if insp["is_ng"]:
                    ng_count += 1
                else:
                    ok_count += 1
                line = f"- {insp['point_name']}: {status_str}"
                if insp["description"]:
                    line += f" — {insp['description']}"
                lines.append(line)

            context = "\n".join(lines) if lines else "（無巡檢結果）"
            now_str = datetime.now(UTC8).strftime("%Y-%m-%d %H:%M:%S")

            prompt = (
                f"以下是本次巡檢的結果摘要（{now_str}）：\n\n"
                f"{context}\n\n"
                f"共巡檢 {len(inspections)} 個點位，其中 {ok_count} 個正常、{ng_count} 個異常。\n\n"
                f"請用繁體中文撰寫一份簡潔的巡檢總結報告。"
            )

            interaction = client.interactions.create(model=model_id, input=prompt)
            usage = interaction.usage
            return {
                "text": interaction.output_text or "",
                "input_tokens": (getattr(usage, "total_input_tokens", 0) or 0) if usage else 0,
                "output_tokens": (getattr(usage, "total_output_tokens", 0) or 0) if usage else 0,
                "total_tokens": (getattr(usage, "total_tokens", 0) or 0) if usage else 0,
            }
        except Exception as e:
            logger.error("Summary generation error: %s", e)
            return {"text": f"報告生成失敗：{e}", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# Module-level singleton
patrol_service = PatrolService()
