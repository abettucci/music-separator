import subprocess
import tempfile
import os
import re
from pathlib import Path


def is_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def is_spotify_url(url: str) -> bool:
    return "open.spotify.com" in url


def download_audio(url: str, output_dir: str) -> str:
    """Download audio from YouTube or Spotify URL. Returns path to downloaded WAV file."""
    if is_youtube_url(url):
        return _download_youtube(url, output_dir)
    elif is_spotify_url(url):
        return _download_spotify(url, output_dir)
    else:
        raise ValueError(f"Unsupported URL: {url}. Only YouTube and Spotify links are supported.")


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
            url,
            "--output", output_dir,
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