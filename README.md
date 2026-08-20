# Telegram Stem Separator Bot

Telegram bot that downloads audio from YouTube or Spotify, separates stems with [Demucs](https://github.com/facebookresearch/demucs) (htdemucs model), and sends the requested track back.

## Setup

### 1. Get a Telegram bot token
Create a bot via [@BotFather](https://t.me/BotFather) and copy the token.

### 2. Install Modal
```bash
pip install modal
modal setup   # authenticates your account
```

### 3. Create the Modal secret
```bash
modal secret create telegram-stem-bot TELEGRAM_BOT_TOKEN=<your_token>
```

### 4. Deploy
```bash
pip install -r requirements.txt
modal deploy modal_app.py
```

Modal will print a webhook URL like:
```
https://your-workspace--telegram-stem-bot-webhook.modal.run
```

### 5. Register the webhook with Telegram
```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://your-workspace--telegram-stem-bot-webhook.modal.run"
```

## Local testing (CPU, slower)

For quick tests without deploying:
```bash
cp .env.example .env   # fill in your token
pip install -r requirements.txt
python bot.py          # runs with long-polling, no webhook needed
```

## Cost (Modal GPU T4)

| Usage | Cost |
|-------|------|
| Per song (~4 min) | ~$0.05 |
| 50 songs/month | ~$2.50 |
| Signup credit | $30 (~577 songs free) |

## Files

| File | Purpose |
|------|---------|
| `bot.py` | Telegram bot for local testing (long-polling) |
| `modal_app.py` | Cloud deployment (webhook + GPU function) |
| `downloader.py` | Downloads audio via yt-dlp / spotdl |
| `separator.py` | Runs Demucs, selects stem, returns MP3 |
