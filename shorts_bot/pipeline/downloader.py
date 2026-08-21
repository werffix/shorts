import subprocess
from pathlib import Path


def download_video(url: str, destination: Path) -> Path:
    """Download a source with a bounded height suitable for fast MVP rendering."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_template = str(destination.with_suffix(".%(ext)s"))
    subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--max-filesize",
            "2G",
            "-f",
            "bv*[height<=1080]+ba/b[height<=1080]/b",
            "--merge-output-format",
            "mp4",
            "-o",
            output_template,
            url,
        ],
        check=True,
    )
    candidates = sorted(destination.parent.glob(f"{destination.stem}.*"))
    if not candidates:
        raise RuntimeError("yt-dlp finished without creating a video file")
    return candidates[0]
