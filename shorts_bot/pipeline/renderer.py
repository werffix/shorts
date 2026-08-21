import json
import logging
import subprocess
from pathlib import Path

from shorts_bot.pipeline.models import Segment, Word
from shorts_bot.pipeline.subtitles import write_ass

logger = logging.getLogger(__name__)


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
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "gblur=sigma=30,eq=brightness=-0.05[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,"
            f"ass='{subtitle_path}'[out]"
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
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(
            "FFmpeg failed for format=%s, command=%s, stderr=%s",
            video_format, " ".join(command), result.stderr[-4000:],
        )
        raise RuntimeError(f"FFmpeg render failed for format {video_format}")
    actual_width, actual_height = probe_resolution(output)
    if (actual_width, actual_height) != (width, height):
        logger.error(
            "Unexpected output resolution for format=%s: expected=%sx%s actual=%sx%s",
            video_format, width, height, actual_width, actual_height,
        )
        raise RuntimeError(
            f"Unexpected output resolution: expected {width}x{height}, "
            f"got {actual_width}x{actual_height}"
        )
    if banner_path and banner_path.exists():
        with_banner = output.with_suffix(".banner.mp4")
        banner_result = subprocess.run([
            "ffmpeg", "-y", "-i", str(output), "-stream_loop", "-1", "-i", str(banner_path),
            "-filter_complex", f"[1:v]scale={width}:-2,trim=duration={segment.end - segment.start},setpts=PTS-STARTPTS[b];[0:v][b]overlay=0:0:eof_action=repeat:shortest=1[out]",
            "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-c:a", "copy", str(with_banner),
        ], capture_output=True, text=True)
        if banner_result.returncode != 0:
            logger.error("Banner overlay failed: %s", banner_result.stderr[-4000:])
            raise RuntimeError("Banner overlay failed")
        with_banner.replace(output)
        banner_width, banner_height = probe_resolution(output)
        if (banner_width, banner_height) != (width, height):
            raise RuntimeError(
                f"Banner changed output resolution: expected {width}x{height}, "
                f"got {banner_width}x{banner_height}"
            )
    return output


def probe_resolution(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise RuntimeError(f"ffprobe found no video stream in {path}")
    return int(streams[0]["width"]), int(streams[0]["height"])
