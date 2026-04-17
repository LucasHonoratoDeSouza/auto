from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tiktok_automation.config import Settings
from tiktok_automation.pipeline.smart_crop import render_smart_cropped_segment
from tiktok_automation.pipeline.subtitles import write_ass_subtitles, write_caption_metadata
from tiktok_automation.schemas import ClipCandidate, RenderArtifact, SourceAsset, TranscriptResult
from tiktok_automation.utils import ensure_directory, escape_ffmpeg_filter_path, run_command, slugify


@lru_cache(maxsize=4)
def _available_encoders(ffmpeg_binary: str) -> set[str]:
    result = run_command([ffmpeg_binary, "-hide_banner", "-encoders"])
    encoders: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return encoders


def _video_encoder_args(settings: Settings) -> list[str]:
    encoders = _available_encoders(settings.ffmpeg_binary)

    if "libx264" in encoders:
        return [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
        ]

    if "libopenh264" in encoders:
        return [
            "-c:v",
            "libopenh264",
            "-profile:v",
            "high",
            "-rc_mode",
            "quality",
            "-b:v",
            "4M",
            "-pix_fmt",
            "yuv420p",
        ]

    raise RuntimeError(
        "Nenhum encoder H.264 compativel foi encontrado no ffmpeg. "
        "Instale um ffmpeg com libx264 ou libopenh264."
    )


def render_candidate(
    asset: SourceAsset,
    transcript: TranscriptResult,
    candidate: ClipCandidate,
    settings: Settings,
) -> RenderArtifact:
    clip_slug = slugify(f"{candidate.rank}-{candidate.title}")[:80]
    output_dir = ensure_directory(settings.output_root / asset.run_id)
    subtitles_path = output_dir / f"{clip_slug}.ass"
    metadata_path = output_dir / f"{clip_slug}.json"
    output_video_path = output_dir / f"{clip_slug}.mp4"

    write_ass_subtitles(subtitles_path, candidate, transcript)
    write_caption_metadata(metadata_path, candidate)

    smartcrop_output_path = output_dir / f"{clip_slug}.smartcrop.mp4"
    smartcrop_rendered = False
    try:
        smartcrop_rendered = render_smart_cropped_segment(
            source_video_path=asset.source_video_path,
            output_video_path=smartcrop_output_path,
            start_seconds=candidate.start,
            duration_seconds=candidate.duration_seconds,
            settings=settings,
        )
    except Exception:
        smartcrop_rendered = False

    video_encoder_args = _video_encoder_args(settings)
    subtitle_filter = f"ass='{escape_ffmpeg_filter_path(subtitles_path)}'"

    if smartcrop_rendered:
        run_command(
            [
                settings.ffmpeg_binary,
                "-y",
                "-i",
                str(smartcrop_output_path),
                "-vf",
                subtitle_filter,
                *video_encoder_args,
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(output_video_path),
            ]
        )
        smartcrop_output_path.unlink(missing_ok=True)
    else:
        vf = ",".join(
            [
                "scale=1080:1920:force_original_aspect_ratio=increase",
                "crop=1080:1920",
                subtitle_filter,
            ]
        )
        run_command(
            [
                settings.ffmpeg_binary,
                "-y",
                "-ss",
                f"{candidate.start:.3f}",
                "-i",
                asset.source_video_path,
                "-t",
                f"{candidate.duration_seconds:.3f}",
                "-vf",
                vf,
                *video_encoder_args,
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(output_video_path),
            ]
        )

    return RenderArtifact(
        candidate_rank=candidate.rank,
        title=candidate.title,
        output_video_path=str(output_video_path),
        subtitles_path=str(subtitles_path),
    )
