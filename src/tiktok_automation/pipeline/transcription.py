from __future__ import annotations

from pathlib import Path
from typing import Any
import html
import re

import requests

from tiktok_automation.config import Settings
from tiktok_automation.schemas import SourceAsset, TranscriptResult, TranscriptSegment, WordTiming
from tiktok_automation.utils import ensure_directory, ffprobe_duration, run_command, write_json


def extract_audio(video_path: Path, output_path: Path, settings: Settings) -> None:
    ensure_directory(output_path.parent)
    run_command(
        [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(output_path),
        ]
    )


def _parse_vtt_timestamp(raw: str) -> float:
    left = raw.strip().replace(",", ".")
    parts = left.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    if len(parts) == 2:
        minutes = int(parts[0])
        seconds = float(parts[1])
        return minutes * 60 + seconds
    return float(parts[0])


def _cleanup_vtt_text(lines: list[str]) -> str:
    text = " ".join(part.strip() for part in lines if part.strip())
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _collapse_repeated_phrases(tokens: list[str], max_phrase_size: int = 6) -> list[str]:
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        remaining = len(tokens) - index
        consumed = False
        for phrase_size in range(min(max_phrase_size, remaining // 2), 0, -1):
            phrase = tokens[index : index + phrase_size]
            repeats = 1
            while (
                index + (repeats + 1) * phrase_size <= len(tokens)
                and tokens[index + repeats * phrase_size : index + (repeats + 1) * phrase_size] == phrase
            ):
                repeats += 1
            if repeats > 1:
                collapsed.extend(phrase)
                index += repeats * phrase_size
                consumed = True
                break
        if consumed:
            continue
        collapsed.append(tokens[index])
        index += 1
    return collapsed


def _normalize_vtt_segment_text(text: str) -> str:
    text = text.replace(">>", " ")
    text = re.sub(r"\[\s*__\s*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return ""
    tokens = _collapse_repeated_phrases(tokens)
    cleaned = " ".join(tokens)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"([,.!?;:])(?:\s*\1)+", r"\1", cleaned)
    return cleaned.strip(" -")


def _token_overlap(previous_tokens: list[str], current_tokens: list[str]) -> int:
    max_overlap = min(len(previous_tokens), len(current_tokens))
    for overlap in range(max_overlap, 0, -1):
        if previous_tokens[-overlap:] == current_tokens[:overlap]:
            return overlap
    return 0


def _join_segment_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left.endswith(("-", "(", "/")):
        return left + right
    if left.endswith(("'", '"')) or right.startswith(("'", '"', ",", ".", "!", "?", ";", ":")):
        return left + right
    return f"{left} {right}"


def _merge_vtt_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    merged: list[TranscriptSegment] = []
    previous_raw_tokens: list[str] = []

    for segment in segments:
        normalized_text = _normalize_vtt_segment_text(segment.text)
        if not normalized_text:
            previous_raw_tokens = []
            continue

        current_tokens = normalized_text.split()
        overlap = _token_overlap(previous_raw_tokens, current_tokens)
        delta_tokens = current_tokens[overlap:] if overlap else current_tokens
        delta_text = " ".join(delta_tokens).strip()
        previous_raw_tokens = current_tokens
        if not delta_text:
            continue

        current = TranscriptSegment(
            index=len(merged),
            start=segment.start,
            end=segment.end,
            text=delta_text,
            words=[],
        )

        if merged:
            previous = merged[-1]
            gap = current.start - previous.end
            current_word_count = len(current.text.split())
            previous_word_count = len(previous.text.split())
            should_merge = (
                gap <= 0.25
                and (
                    current_word_count <= 4
                    or previous_word_count <= 3
                    or not re.search(r"[.!?]$", previous.text)
                )
            )
            if should_merge:
                previous.text = _join_segment_text(previous.text, current.text)
                previous.end = max(previous.end, current.end)
                continue

        merged.append(current)

    for index, segment in enumerate(merged):
        segment.index = index
    return merged


def transcript_from_vtt(asset: SourceAsset, settings: Settings) -> TranscriptResult | None:
    if not asset.subtitle_path:
        return None

    subtitle_path = Path(asset.subtitle_path)
    if not subtitle_path.exists():
        return None

    content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", content.strip())
    segments: list[TranscriptSegment] = []

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].upper() == "WEBVTT":
            continue

        time_line = None
        text_start_index = 0
        for index, line in enumerate(lines):
            if "-->" in line:
                time_line = line
                text_start_index = index + 1
                break
        if not time_line:
            continue

        start_raw, end_raw = [piece.strip().split(" ")[0] for piece in time_line.split("-->", 1)]
        start = _parse_vtt_timestamp(start_raw)
        end = _parse_vtt_timestamp(end_raw)
        text = _cleanup_vtt_text(lines[text_start_index:])
        if not text:
            continue

        if segments and segments[-1].text == text and abs(segments[-1].end - start) < 0.15:
            segments[-1].end = max(segments[-1].end, end)
            continue

        segments.append(
            TranscriptSegment(
                index=len(segments),
                start=start,
                end=end,
                text=text,
                words=[],
            )
        )

    segments = _merge_vtt_segments(segments)
    if not segments:
        return None

    duration_seconds = asset.duration_seconds
    if duration_seconds is None:
        duration_seconds = ffprobe_duration(settings.ffprobe_binary, Path(asset.source_video_path))

    transcript = TranscriptResult(
        run_id=asset.run_id,
        source_video_path=asset.source_video_path,
        language=asset.subtitle_language,
        provider="youtube_caption",
        duration_seconds=duration_seconds,
        text=" ".join(segment.text for segment in segments),
        segments=segments,
    )
    write_json(
        settings.runs_root / asset.run_id / "transcript.json",
        transcript.model_dump(mode="json"),
    )
    return transcript


def _persist_transcript(transcript: TranscriptResult, settings: Settings) -> TranscriptResult:
    write_json(
        settings.runs_root / transcript.run_id / "transcript.json",
        transcript.model_dump(mode="json"),
    )
    return transcript


def split_audio(audio_path: Path, settings: Settings) -> list[tuple[float, Path]]:
    duration_seconds = ffprobe_duration(settings.ffprobe_binary, audio_path)
    chunk_seconds = settings.transcription_chunk_minutes * 60
    if audio_path.stat().st_size <= settings.transcription_max_audio_bytes:
        return [(0.0, audio_path)]

    pieces: list[tuple[float, Path]] = []
    for index, start in enumerate(range(0, int(duration_seconds) + 1, chunk_seconds)):
        piece = audio_path.parent / f"{audio_path.stem}.part{index:03d}.mp3"
        run_command(
            [
                settings.ffmpeg_binary,
                "-y",
                "-ss",
                str(start),
                "-i",
                str(audio_path),
                "-t",
                str(chunk_seconds),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(piece),
            ]
        )
        pieces.append((float(start), piece))
    return pieces


def _local_model_name(settings: Settings, language: str | None) -> str:
    model_name = settings.local_transcription_model
    if model_name == "turbo" and language and language.lower().startswith("pt"):
        return "small"
    return model_name


def _transcribe_locally(
    asset: SourceAsset,
    settings: Settings,
    language: str | None = None,
) -> TranscriptResult:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover - depends on local runtime
        raise RuntimeError(
            "Transcricao local indisponivel. Instale as dependencias do projeto "
            "com `uv pip install -e .` para usar o modo gratis."
        ) from exc

    run_dir = settings.runs_root / asset.run_id
    source_video = Path(asset.source_video_path)
    audio_path = run_dir / "source" / f"{asset.run_id}.mp3"
    extract_audio(source_video, audio_path, settings)

    model = WhisperModel(
        _local_model_name(settings, language or asset.subtitle_language),
        device=settings.local_transcription_device,
        compute_type=settings.local_transcription_compute_type,
    )
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language or asset.subtitle_language or None,
        beam_size=settings.local_transcription_beam_size,
        vad_filter=settings.local_transcription_vad_filter,
        word_timestamps=True,
    )

    segments: list[TranscriptSegment] = []
    text_parts: list[str] = []
    for index, item in enumerate(segments_iter):
        text = (item.text or "").strip()
        if not text:
            continue
        words = [
            WordTiming(
                text=(word.word or "").strip(),
                start=float(word.start or item.start),
                end=float(word.end or item.end),
            )
            for word in (item.words or [])
            if (word.word or "").strip()
        ]
        if not words:
            words = _approximate_words(text, float(item.start), float(item.end))
        segments.append(
            TranscriptSegment(
                index=index,
                start=float(item.start),
                end=float(item.end),
                text=text,
                words=words,
            )
        )
        text_parts.append(text)

    if not segments:
        raise RuntimeError("A transcricao local nao retornou segmentos validos.")

    transcript = TranscriptResult(
        run_id=asset.run_id,
        source_video_path=asset.source_video_path,
        language=getattr(info, "language", None) or language or asset.subtitle_language,
        provider="local_faster_whisper",
        duration_seconds=asset.duration_seconds,
        text=" ".join(text_parts).strip(),
        segments=segments,
    )
    return _persist_transcript(transcript, settings)


def _openai_headers(settings: Settings) -> dict[str, str]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY nao definido. Preencha o .env antes de transcrever.")

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
    }
    if settings.openai_organization:
        headers["OpenAI-Organization"] = settings.openai_organization
    if settings.openai_project:
        headers["OpenAI-Project"] = settings.openai_project
    return headers


def _request_transcription(
    audio_path: Path,
    settings: Settings,
    language: str | None = None,
) -> dict[str, Any]:
    headers = _openai_headers(settings)
    data: list[tuple[str, str]] = [
        ("model", settings.openai_transcription_model),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "segment"),
        ("timestamp_granularities[]", "word"),
    ]
    if language:
        data.append(("language", language))

    with audio_path.open("rb") as handle:
        response = requests.post(
            f"{settings.openai_base_url.rstrip('/')}/audio/transcriptions",
            headers=headers,
            data=data,
            files={"file": (audio_path.name, handle, "audio/mpeg")},
            timeout=settings.openai_request_timeout_seconds,
        )
    response.raise_for_status()
    return response.json()


def _parse_words(raw_words: list[dict[str, Any]] | None, offset_seconds: float) -> list[WordTiming]:
    words: list[WordTiming] = []
    for item in raw_words or []:
        text = item.get("word") or item.get("text") or ""
        if not text:
            continue
        start = float(item.get("start", 0.0)) + offset_seconds
        end = float(item.get("end", start)) + offset_seconds
        words.append(WordTiming(text=text, start=start, end=end))
    return words


def _approximate_words(text: str, start: float, end: float) -> list[WordTiming]:
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return []
    segment_duration = max(0.1, end - start)
    word_duration = segment_duration / len(tokens)
    cursor = start
    words: list[WordTiming] = []
    for token in tokens:
        words.append(WordTiming(text=token, start=cursor, end=cursor + word_duration))
        cursor += word_duration
    return words


def _build_segments(
    payload: dict[str, Any],
    offset_seconds: float,
) -> list[TranscriptSegment]:
    global_words = _parse_words(payload.get("words"), offset_seconds)
    segments_payload = payload.get("segments") or []
    segments: list[TranscriptSegment] = []

    if segments_payload:
        for index, item in enumerate(segments_payload):
            start = float(item.get("start", 0.0)) + offset_seconds
            end = float(item.get("end", start)) + offset_seconds
            text = (item.get("text") or "").strip()
            nested_words = _parse_words(item.get("words"), offset_seconds)
            if not nested_words and global_words:
                nested_words = [
                    word
                    for word in global_words
                    if word.start >= start and word.end <= end + 0.05
                ]
            if not nested_words:
                nested_words = _approximate_words(text, start, end)
            segments.append(
                TranscriptSegment(
                    index=index,
                    start=start,
                    end=end,
                    text=text,
                    words=nested_words,
                )
            )
        return segments

    text = (payload.get("text") or "").strip()
    if not text:
        return []

    fallback_words = global_words or _approximate_words(
        text,
        offset_seconds,
        offset_seconds + float(payload.get("duration", 0.0)),
    )
    end = fallback_words[-1].end if fallback_words else offset_seconds
    return [
        TranscriptSegment(
            index=0,
            start=offset_seconds,
            end=end,
            text=text,
            words=fallback_words,
        )
    ]


def transcribe_source(
    asset: SourceAsset,
    settings: Settings,
    language: str | None = None,
) -> TranscriptResult:
    vtt_transcript = transcript_from_vtt(asset, settings)
    if vtt_transcript:
        return vtt_transcript

    provider = settings.transcription_provider
    if provider in {"local", "local-only", "auto"}:
        try:
            return _transcribe_locally(asset=asset, settings=settings, language=language)
        except Exception:
            if provider in {"local", "local-only"}:
                raise

    if not settings.use_openai_transcription and provider in {"auto", "youtube", "youtube-only"}:
        raise RuntimeError(
            "Nao ha captions do YouTube disponiveis para este video e o provider atual "
            "nao permite fallback pago. Mantive o projeto em modo gratis."
        )

    if not settings.openai_api_key:
        raise RuntimeError(
            "Sem transcript gratis disponivel e OPENAI_API_KEY nao configurado. "
            "Para seguir sem pagar, instale/ative o modo local com faster-whisper."
        )

    run_dir = settings.runs_root / asset.run_id
    source_video = Path(asset.source_video_path)
    audio_path = run_dir / "source" / f"{asset.run_id}.mp3"
    extract_audio(source_video, audio_path, settings)
    pieces = split_audio(audio_path, settings)

    combined_segments: list[TranscriptSegment] = []
    text_parts: list[str] = []

    for offset_seconds, piece_path in pieces:
        payload = _request_transcription(
            piece_path,
            settings=settings,
            language=language or settings.openai_transcription_language,
        )
        chunk_segments = _build_segments(payload, offset_seconds)
        base_index = len(combined_segments)
        for relative_index, segment in enumerate(chunk_segments):
            combined_segments.append(
                TranscriptSegment(
                    index=base_index + relative_index,
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    words=segment.words,
                )
            )
        text = (payload.get("text") or "").strip()
        if text:
            text_parts.append(text)

    transcript = TranscriptResult(
        run_id=asset.run_id,
        source_video_path=asset.source_video_path,
        language=language or settings.openai_transcription_language,
        provider="openai",
        duration_seconds=asset.duration_seconds,
        text=" ".join(text_parts).strip(),
        segments=combined_segments,
    )
    return _persist_transcript(transcript, settings)
