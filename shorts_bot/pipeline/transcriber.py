from pathlib import Path

from faster_whisper import WhisperModel

from shorts_bot.pipeline.models import Word


def transcribe(video_path: Path, model_name: str) -> list[Word]:
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(video_path), word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    for segment in segments:
        for word in segment.words or []:
            words.append(Word(text=word.word.strip(), start=word.start, end=word.end))
    if not words:
        raise RuntimeError("Speech was not detected in the video")
    return words
