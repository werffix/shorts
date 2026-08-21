import json

from openai import OpenAI

from shorts_bot.pipeline.models import Segment, Word


def find_segments(
    words: list[Word], min_duration: int, max_duration: int, api_key: str | None,
    base_url: str | None, model: str,
) -> list[Segment]:
    if api_key:
        transcript = "\n".join(f"[{word.start:.2f}-{word.end:.2f}] {word.text}" for word in words)
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return only JSON with a 'segments' array. Each element has start, end, score and title."},
                {"role": "user", "content": (
                    f"Choose up to 3 engaging, complete clips from this timestamped transcript. "
                    f"Each must last {min_duration}-{max_duration} seconds.\n{transcript}"
                )},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        selected = [
            Segment(float(item["start"]), float(item["end"]), float(item.get("score", 0)), str(item.get("title", "Short")))
            for item in payload.get("segments", [])
        ]
        valid = [item for item in selected if min_duration <= item.end - item.start <= max_duration]
        if valid:
            return valid[:3]
    return _fallback_segment(words, min_duration, max_duration)


def _fallback_segment(words: list[Word], min_duration: int, max_duration: int) -> list[Segment]:
    start = words[0].start
    end = min(words[-1].end, start + max_duration)
    if end - start < min_duration:
        raise RuntimeError("Video speech is shorter than the requested clip duration")
    return [Segment(start=start, end=end, score=0, title="Short")]
