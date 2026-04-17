from __future__ import annotations

from pathlib import Path

from tiktok_automation.schemas import ClipCandidate, TranscriptResult, WordTiming
from tiktok_automation.utils import ass_timestamp, escape_ass_text, write_json


def _approximate_segment_words(segment) -> list[WordTiming]:
    tokens = [token for token in segment.text.split() if token.strip()]
    if not tokens:
        return []
    duration = max(0.1, segment.end - segment.start)
    slice_duration = duration / len(tokens)
    cursor = segment.start
    words: list[WordTiming] = []
    for token in tokens:
        words.append(WordTiming(text=token, start=cursor, end=cursor + slice_duration))
        cursor += slice_duration
    return words


def collect_words(transcript: TranscriptResult, candidate: ClipCandidate) -> list[WordTiming]:
    output: list[WordTiming] = []
    for segment in transcript.segments:
        if segment.end <= candidate.start or segment.start >= candidate.end:
            continue
        source_words = segment.words or _approximate_segment_words(segment)
        for word in source_words:
            if word.end <= candidate.start or word.start >= candidate.end:
                continue
            output.append(
                WordTiming(
                    text=word.text,
                    start=max(0.0, word.start - candidate.start),
                    end=max(0.0, word.end - candidate.start),
                )
            )
    return output


def _line_break(words: list[str]) -> str:
    if len(words) <= 3:
        return " ".join(words)
    midpoint = len(words) // 2
    return " ".join(words[:midpoint]) + r"\N" + " ".join(words[midpoint:])


def group_caption_words(words: list[WordTiming]) -> list[tuple[float, float, str]]:
    if not words:
        return []

    groups: list[tuple[float, float, str]] = []
    current: list[WordTiming] = []

    for word in words:
        if not current:
            current.append(word)
            continue

        current.append(word)
        chunk_duration = current[-1].end - current[0].start
        boundary = (
            len(current) >= 4
            or chunk_duration >= 1.4
            or word.text.endswith((".", "!", "?", ",", ";", ":"))
        )
        if boundary:
            label = _line_break([item.text for item in current])
            groups.append((current[0].start, current[-1].end, label))
            current = []

    if current:
        label = _line_break([item.text for item in current])
        groups.append((current[0].start, current[-1].end, label))

    return groups


def build_ass(candidate: ClipCandidate, transcript: TranscriptResult) -> str:
    duration = candidate.duration_seconds
    words = collect_words(transcript, candidate)
    caption_groups = group_caption_words(words)
    header = """[Script Info]
Title: TikTok Burn-In
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,78,&H0000FFFF,&H0000FFFF,&H00000000,&H66000000,-1,0,0,0,100,100,0,0,1,5,0,8,70,70,170,1
Style: Caption,Arial,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H66000000,-1,0,0,0,100,100,0,0,1,5,0,2,80,80,240,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = [header.rstrip()]

    hook_end = min(duration, 2.6)
    hook_text = escape_ass_text(candidate.hook[:56])
    lines.append(
        "Dialogue: 0,"
        f"{ass_timestamp(0.0)},{ass_timestamp(hook_end)},"
        "Hook,,0,0,0,,"
        f"{hook_text}"
    )

    for start, end, label in caption_groups:
        safe_label = escape_ass_text(label)
        lines.append(
            "Dialogue: 0,"
            f"{ass_timestamp(start)},{ass_timestamp(end)},"
            "Caption,,0,0,0,,"
            f"{safe_label}"
        )

    return "\n".join(lines) + "\n"


def write_ass_subtitles(path: Path, candidate: ClipCandidate, transcript: TranscriptResult) -> None:
    path.write_text(build_ass(candidate, transcript), encoding="utf-8")


def write_caption_metadata(path: Path, candidate: ClipCandidate) -> None:
    write_json(
        path,
        {
            "title": candidate.title,
            "hook": candidate.hook,
            "suggested_caption": candidate.suggested_caption,
            "suggested_hashtags": candidate.suggested_hashtags,
        },
    )
