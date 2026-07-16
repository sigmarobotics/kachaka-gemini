import asyncio
import logging
import base64
from datetime import datetime, timezone, timedelta

import settings_service
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from gemini_text_service import GeminiTextSession
from robot_manager import robot_manager

logger = logging.getLogger(__name__)


class TelegramBotManager:
    """Manages a Telegram bot that bridges messages to GeminiTextSession."""

    def __init__(self):
        self._app = None
        self._sessions = {}  # chat_id -> GeminiTextSession
        self._task = None

    async def start(self, token: str):
        """Start the Telegram bot with polling."""
        if self._app:
            await self.stop()

        self._app = Application.builder().token(token).build()

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(
            MessageHandler(filters.PHOTO, self._on_photo)
        )
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("[Telegram] Bot started")

    async def stop(self):
        """Stop the Telegram bot."""
        if not self._app:
            return

        # Close all sessions
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()

        try:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        except Exception as e:
            logger.warning(f"[Telegram] Error during shutdown: {e}")
        self._app = None
        logger.info("[Telegram] Bot stopped")

    async def send_patrol_notification(self, message: str, pdf_bytes: bytes | None = None):
        """Send patrol completion notification to configured staff chat."""
        chat_id = settings_service.get("telegram_chat_id", "")
        token = settings_service.get("telegram_bot_token", "")
        if not chat_id or not token or not self._app:
            logger.warning("[Telegram] Cannot send patrol notification: missing config")
            return

        try:
            bot = self._app.bot
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            if pdf_bytes:
                from io import BytesIO
                utc8 = timezone(timedelta(hours=8))
                ts = datetime.now(utc8).strftime("%Y-%m-%d_%H%M%S")
                await bot.send_document(
                    chat_id=chat_id,
                    document=BytesIO(pdf_bytes),
                    filename=f"Patrol_Report_{ts}.pdf",
                )
            logger.info("[Telegram] Patrol notification sent to %s", chat_id)
        except Exception as e:
            logger.error("[Telegram] Failed to send patrol notification: %s", e)

    async def _get_session(self, chat_id: int) -> GeminiTextSession:
        """Get or create a GeminiTextSession for the given chat_id."""
        if chat_id not in self._sessions:
            # Create a no-op callback; we'll use send_text_and_collect
            async def noop(msg):
                pass
            session = GeminiTextSession(noop)
            ok = await session.connect()
            if not ok:
                raise RuntimeError("Failed to connect GeminiTextSession")
            self._sessions[chat_id] = session
        return self._sessions[chat_id]

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Kachaka Robot Assistant\n\n"
            "Send me text or photos to interact with the robot.\n"
            "/clear - Reset conversation history"
        )

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if chat_id in self._sessions:
            self._sessions[chat_id].clear_history()
        await update.message.reply_text("Conversation history cleared.")

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages."""
        chat_id = update.effective_chat.id
        text = update.message.text

        try:
            session = await self._get_session(chat_id)
            messages = await session.send_text_and_collect(text)
            await self._send_responses(update, messages)
        except Exception as e:
            logger.error(f"[Telegram] Error handling message: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo messages — download and send to Gemini alongside caption."""
        chat_id = update.effective_chat.id
        caption = update.message.caption or "Please describe this image."

        try:
            # Download the largest photo
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            photo_bytes = await file.download_as_bytearray()

            session = await self._get_session(chat_id)

            # Build multimodal content: image + text
            input_items = [
                {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(bytes(photo_bytes)).decode("utf-8")},
                {"type": "text", "text": caption},
            ]

            # Collect responses
            collected = []
            async def collector(msg):
                collected.append(msg)
            original_cb = session.send_callback
            session.send_callback = collector
            try:
                await session._generate(input_items)
            finally:
                session.send_callback = original_cb

            await self._send_responses(update, collected)
        except Exception as e:
            logger.error(f"[Telegram] Error handling photo: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _send_responses(self, update: Update, messages: list):
        """Compose and send collected GeminiTextSession messages to Telegram."""
        text_parts = []
        sent_something = False

        for msg in messages:
            msg_type = msg.get("type", "")

            if msg_type == "text":
                text_parts.append(msg.get("content", ""))

            elif msg_type == "function_call":
                fn_name = msg.get("name", "")
                text_parts.append(f"[Executing: {fn_name}]")

                # If capture_camera, send the photo. Use the JPEG stashed at
                # capture time — this runs AFTER the whole Gemini turn, so the
                # live buffer may show wherever the robot moved afterwards.
                if fn_name == "capture_camera":
                    jpeg_bytes = robot_manager.get_last_capture_jpeg()
                    if jpeg_bytes:
                        if text_parts:
                            await update.message.reply_text("\n".join(text_parts))
                            text_parts.clear()
                            sent_something = True
                        await update.message.reply_photo(photo=jpeg_bytes)
                        sent_something = True

            elif msg_type == "function_result":
                pass  # Results are internal; Gemini will summarize

            elif msg_type == "google_search":
                sources = msg.get("sources", [])
                if sources:
                    links = [f"- {s.get('title', '')}: {s.get('uri', '')}" for s in sources[:5]]
                    text_parts.append("\nSources:\n" + "\n".join(links))

            elif msg_type == "error":
                text_parts.append(f"Error: {msg.get('message', '')}")

            elif msg_type == "token_usage":
                pass  # Skip token usage for Telegram

            elif msg_type == "turn_complete":
                pass

        # Send remaining text
        if text_parts:
            full_text = "\n".join(text_parts)
            # Telegram message limit is 4096 chars
            while full_text:
                chunk = full_text[:4096]
                await update.message.reply_text(chunk)
                full_text = full_text[4096:]
            sent_something = True

        if not sent_something:
            await update.message.reply_text("(No response)")


# Singleton
telegram_manager = TelegramBotManager()
