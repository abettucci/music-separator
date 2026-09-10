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
    root_logger.setLevel(logging.INFO)

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
    .apt_install("ffmpeg", "curl", "unzip")
    # yt-dlp needs a JS runtime to solve YouTube's "n challenge" (EJS); Deno is
    # the recommended one. Installed to /usr/local so it lands on the default PATH.
    .run_commands("curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh")
    .pip_install(
        "python-telegram-bot==20.*",
        "yt-dlp[default,curl-cffi]>=2025.9.5",
        "spotdl==4.4.3",
        # demucs (archived, unmaintained on PyPI) doesn't reliably declare its
        # own dependencies at install time, so pin them explicitly.
        "numpy<2",
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
    import re
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
    stage = "spotify_download" if "open.spotify.com" in url else "youtube_download"

    def safe_process_detail(exc: Exception) -> str:
        """Keep CLI diagnostics useful without persisting links or credentials."""
        detail = (
            getattr(exc, "stderr", None)
            or getattr(exc, "stdout", None)
            or getattr(exc, "output", None)
            or str(exc)
            or "no diagnostic output"
        )
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        detail = re.sub(r"https?://\S+", "[REDACTED_URL]", detail)
        detail = re.sub(r"bot\d{6,}:[A-Za-z0-9_-]+", "[REDACTED_TOKEN]", detail)
        normalized = " ".join(detail.split())
        # CLI tracebacks put the actionable exception at the end, not the beginning.
        # spotdl repeats a generic "AudioProviderError" summary per audio provider
        # it tries, so a short tail only captures that repeated boilerplate —
        # keep a longer window so the real underlying yt-dlp error survives too.
        return normalized[-2000:]

    def download_error_message(detail: str) -> str:
        if "rate/request limit" in detail.lower():
            return "❌ Spotify is temporarily rate-limited. Try a YouTube link or try again later."
        return "❌ I couldn't download that song. Please try another link."

    try:
        logging.info("Song processing started source=%s stem=%s", stage, stem)
        logging.info("Audio download started source=%s", stage)
        audio_path = download_audio(url, work_dir)
        logging.info("Audio download completed source=%s", stage)
        stage = "separation"
        logging.info("Stem separation started stem=%s", stem)
        result_path = separate(audio_path, stem, work_dir)
        logging.info("Stem separation completed stem=%s", stem)

        result_size_mb = os.path.getsize(result_path) / (1024 * 1024)
        if result_size_mb > 49:
            asyncio.run(
                send_message(
                    f"⚠️ File is {result_size_mb:.1f} MB — exceeds Telegram's 50 MB limit. Try a shorter song."
                )
            )
            return

        asyncio.run(send_document(result_path))
        logging.info("Song processing completed stem=%s", stem)
    except subprocess.CalledProcessError as exc:
        detail = safe_process_detail(exc)
        logging.error(
            "Processing failed at stage=%s exit_code=%s detail=%s",
            stage,
            exc.returncode,
            detail,
        )
        asyncio.run(
            send_message(
                download_error_message(detail)
                if stage.endswith("_download")
                else "❌ I couldn't separate that audio. Please try another song."
            )
        )
    except subprocess.TimeoutExpired as exc:
        logging.error(
            "Processing timed out at stage=%s detail=%s",
            stage,
            safe_process_detail(exc),
        )
        asyncio.run(
            send_message(
                "❌ The download took too long. Please try another song."
                if stage.endswith("_download")
                else "❌ The separation took too long. Please try a shorter song."
            )
        )
    except FileNotFoundError as exc:
        logging.error("Processing failed at stage=%s detail=%s", stage, safe_process_detail(exc))
        asyncio.run(
            send_message(
                "❌ The audio download did not produce a file. Please try another link."
                if stage.endswith("_download")
                else "❌ The separation output was not found. Please try another song."
            )
        )
    except Exception as exc:
        logging.error(
            "Processing failed at stage=%s error=%s detail=%s",
            stage,
            type(exc).__name__,
            safe_process_detail(exc),
        )
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
