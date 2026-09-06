import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import downloader
import separator


SPOTIFY_TRACK = "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"
YOUTUBE_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class DownloaderTests(unittest.TestCase):
    def test_accepts_supported_https_urls(self):
        for url in (SPOTIFY_TRACK, YOUTUBE_VIDEO, "https://youtu.be/dQw4w9WgXcQ"):
            downloader._validate_source_url(url)

    def test_rejects_unsafe_or_unsupported_urls(self):
        for url in (
            "http://open.spotify.com/track/track-id",
            "https://open.spotify.com/playlist/playlist-id",
            "https://open.spotify.com@127.0.0.1/track/track-id",
            "https://example.com/open.spotify.com/track/track-id",
            "https://open.spotify.com/track/" + "x" * 2_100,
        ):
            with self.assertRaises(ValueError):
                downloader._validate_source_url(url)

    def test_youtube_command_returns_downloaded_path(self):
        with tempfile.TemporaryDirectory() as output_dir:
            downloaded = Path(output_dir) / "audio.wav"
            downloaded.touch()
            with patch(
                "downloader.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=f"{downloaded}\n"),
            ) as run:
                result = downloader._download_youtube(YOUTUBE_VIDEO, output_dir)

            self.assertEqual(result, str(downloaded))
            command = run.call_args.args[0]
            self.assertIn("--no-playlist", command)
            self.assertEqual(command[-1], YOUTUBE_VIDEO)
            self.assertEqual(run.call_args.kwargs["timeout"], downloader.DOWNLOAD_TIMEOUT_SECONDS)

    def test_spotify_uses_standard_youtube_provider_and_returns_mp3(self):
        with tempfile.TemporaryDirectory() as output_dir:
            audio = Path(output_dir) / "track-id.mp3"
            audio.touch()
            with patch(
                "downloader.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=""),
            ) as run:
                result = downloader._download_spotify(SPOTIFY_TRACK, output_dir)

            self.assertEqual(result, str(audio))
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["spotdl", "download", SPOTIFY_TRACK])
            self.assertEqual(command[command.index("--format") + 1], "mp3")
            audio_index = command.index("--audio")
            self.assertEqual(
                command[audio_index + 1:audio_index + 1 + len(downloader.SPOTIFY_AUDIO_PROVIDERS)],
                list(downloader.SPOTIFY_AUDIO_PROVIDERS),
            )
            self.assertEqual(command[command.index("--max-retries") + 1], "0")
            self.assertIn("--no-cache", command)
            self.assertIn("--print-errors", command)
            self.assertEqual(run.call_args.kwargs["timeout"], downloader.DOWNLOAD_TIMEOUT_SECONDS)

    def test_spotify_fails_when_no_audio_file_is_produced(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch(
                "downloader.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="no output"),
            ):
                with self.assertRaises(FileNotFoundError):
                    downloader._download_spotify(SPOTIFY_TRACK, output_dir)

    def test_spotify_uses_custom_credentials_only_from_environment(self):
        with tempfile.TemporaryDirectory() as output_dir:
            Path(output_dir, "track-id.mp3").touch()
            with patch.dict(
                os.environ,
                {"SPOTIFY_CLIENT_ID": "test-client-id", "SPOTIFY_CLIENT_SECRET": "test-client-secret"},
                clear=False,
            ), patch(
                "downloader.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=""),
            ) as run:
                downloader._download_spotify(SPOTIFY_TRACK, output_dir)

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--client-id") + 1], "test-client-id")
            self.assertEqual(command[command.index("--client-secret") + 1], "test-client-secret")


class SeparatorTests(unittest.TestCase):
    def test_rejects_unknown_stem_without_running_demucs(self):
        with patch("separator.subprocess.run") as run:
            with self.assertRaises(ValueError):
                separator.separate("/tmp/song.mp3", "unknown", "/tmp")
        run.assert_not_called()

    def test_returns_requested_stem(self):
        with tempfile.TemporaryDirectory() as output_dir:
            audio_path = Path(output_dir) / "song.mp3"
            audio_path.touch()
            stem_path = Path(output_dir) / "separated" / separator.MODEL / "song" / "vocals.mp3"

            def create_demucs_output(*_args, **_kwargs):
                stem_path.parent.mkdir(parents=True)
                stem_path.touch()
                return subprocess.CompletedProcess([], 0)

            with patch("separator.subprocess.run", side_effect=create_demucs_output) as run:
                result = separator.separate(str(audio_path), "vocals", output_dir)

            self.assertEqual(result, str(stem_path))
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["python", "-m", "demucs.separate"])
            self.assertIn("--mp3", command)

    def test_creates_zip_for_all_stems(self):
        with tempfile.TemporaryDirectory() as output_dir:
            audio_path = Path(output_dir) / "song.mp3"
            audio_path.touch()
            stems_dir = Path(output_dir) / "separated" / separator.MODEL / "song"

            def create_demucs_output(*_args, **_kwargs):
                stems_dir.mkdir(parents=True)
                for stem in ("vocals", "drums", "bass", "other"):
                    (stems_dir / f"{stem}.mp3").touch()
                return subprocess.CompletedProcess([], 0)

            with patch("separator.subprocess.run", side_effect=create_demucs_output):
                result = separator.separate(str(audio_path), "all", output_dir)

            with zipfile.ZipFile(result) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"vocals.mp3", "drums.mp3", "bass.mp3", "other.mp3"},
                )


class ModalConfigurationTests(unittest.TestCase):
    def test_image_and_safe_error_logging_configuration(self):
        source = Path("modal_app.py").read_text()
        self.assertIn('"yt-dlp[default,curl-cffi]"', source)
        self.assertNotIn("spotdl --download-deno", source)
        self.assertIn("SPOTIFY_AUDIO_PROVIDERS", Path("downloader.py").read_text())
        self.assertIn("return normalized[-500:]", source)
        self.assertIn("[REDACTED_URL]", source)
        self.assertIn("[REDACTED_TOKEN]", source)
        self.assertIn("root_logger.setLevel(logging.INFO)", source)
        self.assertIn("Audio download started source=%s", source)
        self.assertIn("Stem separation started stem=%s", source)
        self.assertIn("Processing timed out at stage=%s", source)

    def test_modal_webhook_dispatches_work_asynchronously(self):
        source = Path("modal_app.py").read_text()
        self.assertIn('@modal.fastapi_endpoint(method="POST")', source)
        self.assertIn("process_song.spawn(url=url, stem=stem, chat_id=query.message.chat_id)", source)
        self.assertIn('return {"ok": True}', source)


class LocalBotConfigurationTests(unittest.TestCase):
    def test_polling_bot_uses_shared_url_validation_and_registered_handlers(self):
        source = Path("bot.py").read_text()
        self.assertIn("from downloader import download_audio, is_youtube_url, is_spotify_url", source)
        self.assertIn("if not (is_youtube_url(url) or is_spotify_url(url)):", source)
        self.assertIn("app.add_handler(CallbackQueryHandler(handle_stem_choice))", source)
        self.assertIn("app.run_polling()", source)


if __name__ == "__main__":
    unittest.main()
