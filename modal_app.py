"""
Deploy to Modal:
    modal deploy modal_app.py

Test locally (no GPU, uses CPU):
    modal run modal_app.py

Secrets setup (one time):
    modal secret create telegram-stem-bot TELEGRAM_BOT_TOKEN=<your_token>
"""
import modal

app = modal.App("telegram-stem-bot")


def configure_safe_logging() -> None:
    """Prevent credentials from reaching Modal's container logs."""
    import logging
    import re

    class TelegramTokenFilter(logging.Filter):
        _token_pattern = re.compile(r"(bot\d{6,}:)[A-Za-z0-9_-]+")

        def filter(self, record: logging.LogRecord) -> bool:
            message = record.getMessage()
            redacted = self._token_pattern.sub(r"\1[REDACTED]", message)
            if redacted != message:
                record.msg = redacted
                record.args = ()
            return True

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO)

    for handler in root_logger.handlers:
        if not getattr(handler, "_telegram_token_filter_installed", False):
            handler.addFilter(TelegramTokenFilter())
            handler._telegram_token_filter_installed = True

    # httpx logs full request URLs at INFO level. Telegram embeds the bot token
    # in its Bot API URL, so these logs must remain disabled.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "python-telegram-bot==20.*",
        "yt-dlp",
        "spotdl",
        "demucs",
        "fastapi[standard]",
    )
    # Modal 1.x requires local modules used by a remote function to be added
    # explicitly; otherwise they are not present in the container.
    .add_local_python_source("downloader", "separator")
)


@app.function(
    image=image,
    gpu="T4",
    timeout=600,  # 10 min max per job
    secrets=[modal.Secret.from_name("telegram-stem-bot")],
)
def process_song(url: str, stem: str, chat_id: int) -> None:
    """Download, separate, and send the stem back via Telegram."""
    import os
    import tempfile
    import shutil
    import logging
    import asyncio
    import subprocess
    from telegram import Bot
    from downloader import download_audio
    from separator import separate

    configure_safe_logging()
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    async def send_message(text: str) -> None:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=text)

    async def send_document(result_path: str) -> None:
        async with Bot(token=token) as bot:
            with open(result_path, "rb") as file:
                await bot.send_document(
                    chat_id=chat_id,
                    document=file,
                    filename=os.path.basename(result_path),
                    caption=f"🎵 *{stem.capitalize()}* stem — Demucs htdemucs",
                    parse_mode="Markdown",
                )

    work_dir = tempfile.mkdtemp()
    stage = "download"
    try:
        audio_path = download_audio(url, work_dir)
        stage = "separation"
        result_path = separate(audio_path, stem, work_dir)

        result_size_mb = os.path.getsize(result_path) / (1024 * 1024)
        if result_size_mb > 49:
            asyncio.run(
                send_message(
                    f"⚠️ File is {result_size_mb:.1f} MB — exceeds Telegram's 50 MB limit. Try a shorter song."
                )
            )
            return

        asyncio.run(send_document(result_path))
    except subprocess.CalledProcessError as exc:
        logging.error(
            "Processing failed at stage=%s exit_code=%s", stage, exc.returncode
        )
        asyncio.run(
            send_message(
                "❌ I couldn't download that song. Please try another link."
                if stage == "download"
                else "❌ I couldn't separate that audio. Please try another song."
            )
        )
    except Exception as exc:
        logging.error("Processing failed: %s", type(exc).__name__)
        asyncio.run(
            send_message("❌ Couldn't process that song. Please try another link.")
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Webhook handler (receives Telegram updates via HTTPS) ─────────────────────

@app.function(
    image=image,
    secrets=[modal.Secret.from_name("telegram-stem-bot")],
)
@modal.fastapi_endpoint(method="POST")
def webhook(body: dict) -> dict:
    """Telegram sends updates here. Responds instantly; processing runs async."""
    import os
    import asyncio
    from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application

    configure_safe_logging()
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    bot = Bot(token=token)

    update = Update.de_json(body, bot)

    async def handle():
        # Inline keyboard buttons send callback_query
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            stem = query.data
            # url was embedded in the message text as the last line
            lines = query.message.text.splitlines()
            url = lines[-1].strip()
            await query.edit_message_text(
                f"⏳ Processing *{stem}* stem... I'll send the file when ready (~2 min).",
                parse_mode="Markdown",
            )
            # Fire-and-forget: Modal spawns a new GPU container for this job
            process_song.spawn(url=url, stem=stem, chat_id=query.message.chat_id)
            return

        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()

        if text == "/start":
            await bot.send_message(
                chat_id=update.message.chat_id,
                text=(
                    "🎵 *Stem Separator Bot*\n\n"
                    "Send me a YouTube or Spotify link and I'll separate the stems using Demucs.\n\n"
                    "Max song duration: 10 minutes."
                ),
                parse_mode="Markdown",
            )
            return

        if "youtube.com" in text or "youtu.be" in text or "open.spotify.com" in text:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎤 Vocals", callback_data="vocals"),
                    InlineKeyboardButton("🥁 Drums", callback_data="drums"),
                ],
                [
                    InlineKeyboardButton("🎸 Bass", callback_data="bass"),
                    InlineKeyboardButton("🎹 Other", callback_data="other"),
                ],
                [InlineKeyboardButton("📦 All stems (ZIP)", callback_data="all")],
            ])
            # Embed the URL in the message text so the callback can read it
            await bot.send_message(
                chat_id=update.message.chat_id,
                text=f"Which stem do you want?\n\n{text}",
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=update.message.chat_id,
                text="❌ Send a YouTube or Spotify link.",
            )

    asyncio.run(handle())
    return {"ok": True}


@app.local_entrypoint()
def main():
    """Run locally for testing (uses CPU, slower)."""
    import sys
    if len(sys.argv) < 3:
        print("Usage: modal run modal_app.py <youtube_url> <stem>")
        print("Stems: vocals, drums, bass, other, all")
        sys.exit(1)
    url, stem = sys.argv[1], sys.argv[2]
    print(f"Processing {stem} from {url} ...")
    process_song.remote(url=url, stem=stem, chat_id=0)
