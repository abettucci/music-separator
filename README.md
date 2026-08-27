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
modal deploy modal_app.py
```
No need to `pip install -r requirements.txt` locally — Modal builds its own container image (see the `image = modal.Image...` block in `modal_app.py`) with `demucs`, `torch`, `spotdl`, etc. installed *inside the cloud container*, not on your machine. Installing them locally only makes sense if you plan to run `bot.py` for local testing (see below), and even then it should go in a virtual environment, not your global/pyenv interpreter — those packages (`torch`, `demucs`) can downgrade shared dependencies (`anyio`, `httpx`, `starlette`, `uvicorn`) that other CLI tools rely on.

Modal will print a webhook URL like:
```
https://your-workspace--telegram-stem-bot-webhook.modal.run
```

### 5. Register the webhook with Telegram
```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://your-workspace--telegram-stem-bot-webhook.modal.run"
```

## Local testing (CPU, slower)

For quick tests without deploying, use an isolated virtual environment — do not install into your global/system Python, since `torch`/`demucs` can conflict with other tools' dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your token
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
