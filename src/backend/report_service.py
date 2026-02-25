"""Report Service — PDF report generation and video analysis.

PDF generation ported from visual-patrol v1 (ReportLab + CJK fonts).
Video analysis uses Gemini Files API.
"""

import io
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

from google import genai
from google.genai import types as genai_types

import patrol_db
import settings_service
from config import DATA_DIR

logger = logging.getLogger(__name__)

REPORT_DIR = os.path.join(DATA_DIR, "report")
IMAGE_DIR = os.path.join(REPORT_DIR, "images")
VIDEO_DIR = os.path.join(REPORT_DIR, "video")

# Font paths — search local fonts/ dir first, then system font paths
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_SYSTEM_FONT_DIRS = [
    "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/noto-cjk",
]


def _find_font(name):
    """Search for a font file in local fonts/ dir and system paths."""
    for ext in (".otf", ".ttf", ".ttc"):
        path = os.path.join(FONT_DIR, name + ext)
        if os.path.exists(path):
            return path
    for d in _SYSTEM_FONT_DIRS:
        for ext in (".otf", ".ttf", ".ttc"):
            path = os.path.join(d, name + ext)
            if os.path.exists(path):
                return path
    return None


def _register_cjk_fonts():
    """Register CJK fonts for ReportLab. Returns (normal_name, bold_name)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    normal_path = _find_font("NotoSansCJK-Regular")
    bold_path = _find_font("NotoSansCJK-Bold")

    if normal_path:
        try:
            pdfmetrics.registerFont(TTFont("NotoSansCJK", normal_path))
            if bold_path:
                pdfmetrics.registerFont(TTFont("NotoSansCJKBold", bold_path))
            else:
                pdfmetrics.registerFont(TTFont("NotoSansCJKBold", normal_path))
            return "NotoSansCJK", "NotoSansCJKBold"
        except Exception as e:
            logger.warning("Failed to load NotoSansCJK: %s, falling back to CID", e)

    # Fallback to CID font
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light", "STSong-Light"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


class ReportService:
    """Generates PDF reports and performs video analysis."""

    def generate_patrol_pdf(self, run_id: int) -> bytes | None:
        """Generate a PDF report for a single patrol run. Returns PDF bytes."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
        )

        run = patrol_db.get_run(run_id)
        if not run:
            return None

        inspections = patrol_db.get_inspections(run_id)
        font_normal, font_bold = _register_cjk_fonts()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                topMargin=20*mm, bottomMargin=20*mm)
        story = []
        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle("Title_CJK", parent=styles["Title"],
                                      fontName=font_bold, fontSize=18)
        heading_style = ParagraphStyle("Heading_CJK", parent=styles["Heading2"],
                                        fontName=font_bold, fontSize=14,
                                        textColor=colors.HexColor("#b8860b"))
        body_style = ParagraphStyle("Body_CJK", parent=styles["Normal"],
                                     fontName=font_normal, fontSize=10,
                                     leading=14)
        ok_style = ParagraphStyle("OK", parent=body_style,
                                   textColor=colors.HexColor("#28a745"))
        ng_style = ParagraphStyle("NG", parent=body_style,
                                   textColor=colors.HexColor("#dc3545"))

        # Title
        story.append(Paragraph("VISUAL PATROL — Inspection Report", title_style))
        story.append(Spacer(1, 10*mm))

        # Patrol info table
        info_data = [
            ["Start Time", run.get("start_time", "")],
            ["End Time", run.get("end_time", "")],
            ["Status", run.get("status", "")],
            ["Model", run.get("model_id", "")],
            ["Total Tokens", str(run.get("total_tokens", 0))],
        ]
        info_table = Table(info_data, colWidths=[40*mm, 120*mm])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_normal),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (0, -1), font_bold),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 8*mm))

        # AI Summary
        if run.get("report_content"):
            story.append(Paragraph("AI Summary Report", heading_style))
            story.append(Spacer(1, 3*mm))
            for line in run["report_content"].split("\n"):
                if line.strip():
                    story.append(Paragraph(line, body_style))
            story.append(Spacer(1, 5*mm))

        # Video Analysis
        if run.get("video_analysis"):
            story.append(Paragraph("Video Analysis", heading_style))
            story.append(Spacer(1, 3*mm))
            for line in run["video_analysis"].split("\n"):
                if line.strip():
                    story.append(Paragraph(line, body_style))
            story.append(Spacer(1, 5*mm))

        # Inspection Points
        story.append(Paragraph("Inspection Points", heading_style))
        story.append(Spacer(1, 3*mm))

        for insp in inspections:
            is_ng = insp.get("is_ng", 0)
            status_text = "NG" if is_ng else "OK"
            status_style = ng_style if is_ng else ok_style
            point_name = insp.get("point_name", "Unknown")

            story.append(Paragraph(
                f"<b>{point_name}</b> — "
                f"<font color='{'#dc3545' if is_ng else '#28a745'}'>{status_text}</font>",
                ParagraphStyle("Point", parent=body_style, fontName=font_bold,
                               fontSize=12, textColor=colors.HexColor("#008b72")),
            ))
            story.append(Paragraph(
                f"Time: {insp.get('timestamp', '')} | "
                f"Tokens: {insp.get('total_tokens', 0)}",
                body_style,
            ))

            # Image
            img_path = os.path.join(IMAGE_DIR, insp.get("image_path", ""))
            if os.path.exists(img_path):
                try:
                    img = RLImage(img_path, width=140*mm, height=105*mm,
                                  kind="proportional")
                    story.append(img)
                except Exception as e:
                    story.append(Paragraph(f"(Image load error: {e})", body_style))

            # AI Description
            desc = insp.get("ai_description", "")
            if desc:
                story.append(Paragraph(f"AI Analysis: {desc}", body_style))

            story.append(Spacer(1, 5*mm))

        doc.build(story)
        return buffer.getvalue()

    def analyze_video(self, video_path: str, prompt: str = "") -> dict:
        """Upload video to Gemini Files API and analyze.

        Returns {"text": str, "input_tokens": int, "output_tokens": int, "total_tokens": int}
        """
        settings = settings_service.get_all()
        api_key = settings.get("gemini_api_key", "")
        model_id = settings.get("patrol_model", settings.get("text_model", "gemini-2.0-flash"))

        if not api_key:
            return {"text": "Error: API key not configured", "input_tokens": 0,
                    "output_tokens": 0, "total_tokens": 0}
        if not os.path.exists(video_path):
            return {"text": f"Error: Video not found: {video_path}", "input_tokens": 0,
                    "output_tokens": 0, "total_tokens": 0}
        if not prompt:
            prompt = settings.get("video_analysis_prompt",
                "請分析這段巡檢影片，描述觀察到的環境狀況、異常事項及建議。使用繁體中文。")

        client = genai.Client(api_key=api_key)

        try:
            # Upload video file
            video_file = client.files.upload(file=video_path)
            logger.info("Video uploaded: %s, state=%s", video_file.name, video_file.state)

            # Wait for processing
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = client.files.get(name=video_file.name)

            if video_file.state.name != "ACTIVE":
                return {"text": f"Video processing failed: {video_file.state.name}",
                        "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

            # Generate analysis
            response = client.models.generate_content(
                model=model_id,
                contents=[video_file, prompt],
            )

            usage = response.usage_metadata
            return {
                "text": response.text or "",
                "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(usage, "total_token_count", 0) or 0,
            }
        except Exception as e:
            logger.error("Video analysis error: %s", e, exc_info=True)
            return {"text": f"Video analysis failed: {e}",
                    "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def generate_analysis_report(self, start_date: str, end_date: str,
                                  custom_prompt: str = "") -> dict:
        """Generate an AI analysis report for a date range.

        Returns {"text": str, "input_tokens": int, "output_tokens": int, "total_tokens": int}
        """
        inspections = patrol_db.get_inspections_by_date(start_date, end_date)
        if not inspections:
            return {"text": "No inspection data for this period.",
                    "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        context_lines = []
        for insp in inspections:
            status = "NG" if insp.get("is_ng") else "OK"
            context_lines.append(
                f"[{insp.get('timestamp', '')}] Point: {insp.get('point_name', '')} | "
                f"Status: {status} | {insp.get('ai_description', '')}"
            )
        context = "\n".join(context_lines)

        prompt = custom_prompt or (
            "以下是指定期間的巡檢記錄，請用繁體中文撰寫詳細分析報告。"
            "包含：趨勢分析、異常模式、改善建議。\n\n"
        )
        full_prompt = f"{prompt}\n\n{context}"

        settings = settings_service.get_all()
        api_key = settings.get("gemini_api_key", "")
        model_id = settings.get("patrol_model", settings.get("text_model", "gemini-2.0-flash"))

        if not api_key:
            return {"text": "Error: API key not configured",
                    "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=model_id, contents=full_prompt)
            usage = response.usage_metadata
            return {
                "text": response.text or "",
                "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(usage, "total_token_count", 0) or 0,
            }
        except Exception as e:
            return {"text": f"Report generation failed: {e}",
                    "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# Module-level singleton
report_service = ReportService()
