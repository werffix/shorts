import subprocess
from pathlib import Path

from shorts_bot.pipeline.models import Segment, Word
from shorts_bot.pipeline.subtitles import write_ass


def render_short(video: Path, words: list[Word], segment: Segment, output: Path) -> Path:
    ass_path = output.with_suffix(".ass")
    write_ass(words, segment.start, segment.end, ass_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    subtitle_path = str(ass_path.resolve()).replace("\\", "\\\\").replace(":", "\\:")
    filter_graph = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,"
        f"ass='{subtitle_path}'"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(segment.start), "-t", str(segment.end - segment.start), "-i", str(video),
         "-vf", filter_graph, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "aac", "-movflags", "+faststart", str(output)],
        check=True,
    )
    return output
