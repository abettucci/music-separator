import subprocess
import os
import zipfile
from pathlib import Path

STEM_CHOICES = {"vocals", "drums", "bass", "other", "all"}
MODEL = "htdemucs"


def separate(audio_path: str, stem: str, output_dir: str) -> str:
    """
    Run Demucs on audio_path, then return path to the requested stem as MP3.
    If stem is 'all', returns path to a ZIP containing all 4 stems as MP3.
    """
    if stem not in STEM_CHOICES:
        raise ValueError(f"Invalid stem '{stem}'. Choose from: {STEM_CHOICES}")

    separated_dir = os.path.join(output_dir, "separated")
    subprocess.run(
        [
            "python", "-m", "demucs.separate",
            "-n", MODEL,
            "--mp3",
            "--mp3-preset", "2",
            "-o", separated_dir,
            audio_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    song_name = Path(audio_path).stem
    stems_dir = Path(separated_dir) / MODEL / song_name

    if not stems_dir.exists():
        raise FileNotFoundError(
            f"Demucs output not found at {stems_dir}. Check that the model ran correctly."
        )

    if stem == "all":
        return _zip_all_stems(stems_dir, output_dir, song_name)

    stem_file = stems_dir / f"{stem}.mp3"
    if not stem_file.exists():
        raise FileNotFoundError(f"Stem file not found: {stem_file}")

    return str(stem_file)


def _zip_all_stems(stems_dir: Path, output_dir: str, song_name: str) -> str:
    zip_path = os.path.join(output_dir, f"{song_name}_all_stems.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for stem_file in stems_dir.glob("*.mp3"):
            zf.write(stem_file, stem_file.name)
    return zip_path