import os
import tempfile
import shutil
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from downloader import download_audio, is_youtube_url, is_spotify_url
from separator import separate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MAX_DURATION_SECONDS = 600  # 10 minutes


def stem_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎵 *Stem Separator Bot*\n\n"
        "Send me a YouTube or Spotify link and I'll separate the stems using Demucs.\n\n"
        "Supported:\n"
        "• `youtube.com` / `youtu.be`\n"
        "• `open.spotify.com`\n\n"
        "Max song duration: 10 minutes.",
        parse_mode="Markdown",
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()
    if not (is_youtube_url(url) or is_spotify_url(url)):
        await update.message.reply_text("❌ Send a YouTube or Spotify link.")
        return

    context.user_data["url"] = url
    await update.message.reply_text(
        "Which stem do you want?",
        reply_markup=stem_keyboard(),
    )


async def handle_stem_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    stem = query.data
    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text("❌ Session expired. Send the URL again.")
        return

    await query.edit_message_text(f"⏳ Processing *{stem}* stem... This takes ~2 minutes.", parse_mode="Markdown")

    work_dir = tempfile.mkdtemp()
    try:
        audio_path = download_audio(url, work_dir)
        result_path = separate(audio_path, stem, work_dir)

        result_size_mb = os.path.getsize(result_path) / (1024 * 1024)
        if result_size_mb > 49:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"⚠️ File is {result_size_mb:.1f} MB — exceeds Telegram's 50 MB limit. Try a shorter song.",
            )
            return

        caption = f"🎵 *{stem.capitalize()}* stem\nProcessed with Demucs ({stem} model)"
        with open(result_path, "rb") as f:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=f,
                filename=os.path.basename(result_path),
                caption=caption,
                parse_mode="Markdown",
            )

    except ValueError as e:
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ {e}")
    except Exception as e:
        logger.exception("Processing failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Something went wrong: {e}",
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        context.user_data.pop("url", None)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_stem_choice))
    app.run_polling()


if __name__ == "__main__":
    main()
