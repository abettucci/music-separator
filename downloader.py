import subprocess
import os
from pathlib import Path
from urllib.parse import urlparse


MAX_URL_LENGTH = 2_048
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
SPOTIFY_HOSTS = {"open.spotify.com"}


def is_youtube_url(url: str) -> bool:
    return _url_host(url) in YOUTUBE_HOSTS


def is_spotify_url(url: str) -> bool:
    return _url_host(url) in SPOTIFY_HOSTS


def download_audio(url: str, output_dir: str) -> str:
    """Download audio from YouTube or Spotify URL. Returns path to downloaded WAV file."""
    _validate_source_url(url)
    if is_youtube_url(url):
        return _download_youtube(url, output_dir)
    if is_spotify_url(url):
        return _download_spotify(url, output_dir)
    raise ValueError("Only YouTube and Spotify track links are supported.")


def _url_host(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def _validate_source_url(url: str) -> None:
    """Allow only supported HTTPS media URLs before handing them to download tools."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise ValueError("The link is invalid or too long.")

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValueError("The link is invalid.") from exc

    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Send a valid HTTPS YouTube or Spotify link.")

    if hostname in YOUTUBE_HOSTS:
        return

    spotify_path = parsed.path.strip("/").split("/")
    if hostname in SPOTIFY_HOSTS and "track" in spotify_path:
        return

    raise ValueError("Only YouTube videos and Spotify tracks are supported.")


def _download_youtube(url: str, output_dir: str) -> str:
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
    result = subprocess.run(
        [
            "yt-dlp",
            "-x",
            "--audio-format", "wav",
            "--audio-quality", "0",
            "--no-playlist",
            "-o", output_template,
            "--print", "after_move:filepath",
            url,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    filepath = result.stdout.strip().splitlines()[-1]
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Downloaded file not found at: {filepath}")
    return filepath


def _download_spotify(url: str, output_dir: str) -> str:
    # spotdl downloads as MP3 by default; Demucs accepts MP3 directly
    result = subprocess.run(
        [
            "spotdl",
            "download",
            url,
            "--output", os.path.join(output_dir, "{track-id}.{output-ext}"),
            "--format", "wav",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=output_dir,
    )
    # spotdl doesn't print the output path — find the newest WAV in output_dir
    wav_files = sorted(
        Path(output_dir).glob("*.wav"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not wav_files:
        # fallback: accept MP3 too
        mp3_files = sorted(
            Path(output_dir).glob("*.mp3"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not mp3_files:
            raise FileNotFoundError(
                f"spotdl did not produce any audio file in {output_dir}.\nOutput: {result.stdout}\n{result.stderr}"
            )
        return str(mp3_files[0])
    return str(wav_files[0])
