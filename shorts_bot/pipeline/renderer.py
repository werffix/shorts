import subprocess
from pathlib import Path

from shorts_bot.pipeline.models import Segment, Word
from shorts_bot.pipeline.subtitles import write_ass


FORMATS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "16:9_blur": (1920, 1080),
    "1:1": (1080, 1080),
}


def render_short(video: Path, words: list[Word], segment: Segment, output: Path,
                 video_format: str = "9:16", banner_path: Path | None = None) -> Path:
    width, height = FORMATS.get(video_format, FORMATS["9:16"])
    ass_path = output.with_suffix(".ass")
    write_ass(words, segment.start, segment.end, ass_path, width, height)
    output.parent.mkdir(parents=True, exist_ok=True)
    subtitle_path = str(ass_path.resolve()).replace("\\", "\\\\").replace(":", "\\:")
    if video_format == "16:9_blur":
        filter_graph = (
            "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
            "gblur=sigma=30,eq=brightness=-0.05[bg];"
            "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,"
            f"ass='{subtitle_path}'"
        )
    else:
        filter_graph = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,ass='{subtitle_path}'"
        )
    command = ["ffmpeg", "-y", "-ss", str(segment.start), "-t", str(segment.end - segment.start), "-i", str(video)]
    if video_format == "16:9_blur":
        command += ["-filter_complex", filter_graph, "-map", "[out]", "-map", "0:a?"]
    else:
        command += ["-vf", filter_graph]
    command += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", str(output)]
    subprocess.run(command, check=True)
    if banner_path and banner_path.exists():
        with_banner = output.with_suffix(".banner.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(output), "-stream_loop", "-1", "-i", str(banner_path),
            "-filter_complex", f"[1:v]scale={width}:-2,trim=duration={segment.end - segment.start},setpts=PTS-STARTPTS[b];[0:v][b]overlay=0:0:eof_action=repeat:shortest=1[out]",
            "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-c:a", "copy", str(with_banner),
        ], check=True)
        with_banner.replace(output)
    return output
