"""Refresh the YOUTUBE_COOKIES Modal secret from a persistent, logged-in browser profile.

First time (interactive, opens a visible browser so you can log in to Google):
    python scripts/refresh_youtube_cookies.py --login

Afterwards, run on a schedule (e.g. weekly cron) from your own machine — NOT
from a cloud CI runner, since YouTube treats datacenter IPs as suspicious:
    python scripts/refresh_youtube_cookies.py

Requires a local .env (gitignored, see .env.example) with at least
TELEGRAM_BOT_TOKEN, so this script can push the full secret bundle to Modal
without dropping the other keys (`modal secret create` replaces the secret
wholesale, it does not merge).

Setup:
    pip install -r scripts/requirements.txt
    playwright install chromium
"""
import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / ".playwright-youtube-profile"
ENV_FILE = PROJECT_ROOT / ".env"
MODAL_SECRET_NAME = "telegram-stem-bot"


def export_cookies(headless: bool) -> str:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=headless)
        page = context.new_page()
        page.goto("https://www.youtube.com", wait_until="networkidle")

        if not headless:
            input(
                "A browser window opened. Log in to the YouTube/Google account "
                "you want the bot to use, then press Enter here once you see "
                "your account avatar in the top-right corner..."
            )
            page.reload(wait_until="networkidle")

        cookies = context.cookies("https://www.youtube.com")
        context.close()

    if not cookies:
        raise RuntimeError("No cookies captured — the login likely did not complete.")

    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.haxx.se/rfc/cookie_spec.html",
        "# This is a generated file! Do not edit.",
        "",
    ]
    for cookie in cookies:
        domain = cookie["domain"]
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = cookie.get("path", "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = cookie.get("expires", -1)
        expires = str(int(expires)) if expires and expires > 0 else "0"
        lines.append(
            "\t".join([domain, include_subdomains, path, secure, expires, cookie["name"], cookie["value"]])
        )
    return "\n".join(lines) + "\n"


def push_to_modal_secret(cookies_content: str) -> None:
    env = dotenv_values(ENV_FILE)
    telegram_token = env.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise RuntimeError(f"TELEGRAM_BOT_TOKEN missing from {ENV_FILE} — see .env.example")

    command = [
        "modal", "secret", "create", MODAL_SECRET_NAME,
        f"TELEGRAM_BOT_TOKEN={telegram_token}",
        f"YOUTUBE_COOKIES={cookies_content}",
        "--force",
    ]
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        if env.get(key):
            command.append(f"{key}={env[key]}")

    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--login", action="store_true",
        help="Interactive one-time Google login (opens a visible browser window).",
    )
    args = parser.parse_args()

    if args.login and not sys.stdin.isatty():
        raise RuntimeError("--login requires an interactive terminal.")

    cookies_content = export_cookies(headless=not args.login)
    push_to_modal_secret(cookies_content)
    print("YouTube cookies refreshed and pushed to the Modal secret.")


if __name__ == "__main__":
    main()
