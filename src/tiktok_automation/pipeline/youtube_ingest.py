from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from tiktok_automation.config import Settings
from tiktok_automation.schemas import RightsStatus, SourceAsset
from tiktok_automation.utils import ensure_directory, slugify, write_json


def _resolve_downloaded_path(info: dict, download_dir: Path) -> Path:
    requested = info.get("requested_downloads") or []
    for item in requested:
        candidate = item.get("filepath")
        if candidate and Path(candidate).exists():
            return Path(candidate)

    video_id = info.get("id")
    for extension in [info.get("ext"), "mp4", "mkv", "webm", "mov"]:
        if not extension:
            continue
        candidate = download_dir / f"{video_id}.{extension}"
        if candidate.exists():
            return candidate

    raise FileNotFoundError("Nao foi possivel localizar o arquivo baixado do YouTube.")


def _resolve_subtitle_path(info: dict, download_dir: Path) -> tuple[Path | None, str | None]:
    requested = info.get("requested_subtitles") or {}
    for language, payload in requested.items():
        filepath = payload.get("filepath") if isinstance(payload, dict) else None
        if filepath and Path(filepath).exists():
            return Path(filepath), language

    video_id = info.get("id")
    if not video_id:
        return None, None

    candidates = sorted(download_dir.glob(f"{video_id}*.vtt"))
    if candidates:
        subtitle = candidates[0]
        language = subtitle.stem.split(".")[-1] if "." in subtitle.stem else None
        return subtitle, language
    return None, None


def _unique_run_id(base_run_id: str, runs_root: Path) -> str:
    if not (runs_root / base_run_id).exists():
        return base_run_id

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    candidate = f"{base_run_id}-{stamp}"
    counter = 1
    while (runs_root / candidate).exists():
        candidate = f"{base_run_id}-{stamp}-{counter:02d}"
        counter += 1
    return candidate


def _base_ydl_options(incoming_dir: Path) -> dict[str, object]:
    return {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(incoming_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "extractor_retries": 3,
        "sleep_interval_requests": 1.0,
    }


def _should_retry_without_subtitles(error: Exception) -> bool:
    message = str(error).lower()
    return "subtitle" in message or "subtitles" in message or "automatic captions" in message


def _download_with_yt_dlp(
    url: str,
    incoming_dir: Path,
    settings: Settings,
    with_subtitles: bool,
) -> dict:
    from yt_dlp import YoutubeDL

    ydl_opts = _base_ydl_options(incoming_dir)
    if with_subtitles:
        ydl_opts.update(
            {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["pt.*", "en.*", "pt", "en"],
                "subtitlesformat": "vtt/best",
            }
        )

    if settings.youtube_proxy_url:
        ydl_opts["proxy"] = settings.youtube_proxy_url
    if settings.cookies_path:
        ydl_opts["cookiefile"] = str(settings.cookies_path)

    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=True)


def download_source(
    url: str,
    rights_status: RightsStatus,
    settings: Settings,
    strategy_arm_id: str | None = None,
) -> SourceAsset:
    incoming_dir = ensure_directory(settings.tmp_root / "incoming")
    try:
        info = _download_with_yt_dlp(
            url=url,
            incoming_dir=incoming_dir,
            settings=settings,
            with_subtitles=True,
        )
    except Exception as exc:
        if not _should_retry_without_subtitles(exc):
            raise

        info = _download_with_yt_dlp(
            url=url,
            incoming_dir=incoming_dir,
            settings=settings,
            with_subtitles=False,
        )

    video_id = info.get("id") or slugify(info.get("title", "source"))
    run_id = _unique_run_id(slugify(str(video_id)), settings.runs_root)
    run_dir = ensure_directory(settings.runs_root / run_id)
    source_dir = ensure_directory(run_dir / "source")
    downloaded_path = _resolve_downloaded_path(info, incoming_dir)
    downloaded_subtitle_path, subtitle_language = _resolve_subtitle_path(info, incoming_dir)
    final_path = source_dir / f"{run_id}.mp4"
    final_subtitle_path: Path | None = None

    if downloaded_path.resolve() != final_path.resolve():
        shutil.move(str(downloaded_path), str(final_path))

    if downloaded_subtitle_path and downloaded_subtitle_path.exists():
        final_subtitle_path = source_dir / f"{run_id}.vtt"
        if downloaded_subtitle_path.resolve() != final_subtitle_path.resolve():
            shutil.move(str(downloaded_subtitle_path), str(final_subtitle_path))
        else:
            final_subtitle_path = downloaded_subtitle_path

    asset = SourceAsset(
        run_id=run_id,
        source_url=url,
        rights_status=rights_status,
        title=info.get("title") or run_id,
        strategy_arm_id=strategy_arm_id,
        subtitle_path=str(final_subtitle_path) if final_subtitle_path else None,
        subtitle_language=subtitle_language,
        uploader=info.get("uploader"),
        channel_url=info.get("channel_url") or info.get("uploader_url"),
        description=info.get("description"),
        upload_date=info.get("upload_date"),
        duration_seconds=info.get("duration"),
        source_video_path=str(final_path),
        thumbnail_url=info.get("thumbnail"),
    )

    write_json(run_dir / "metadata.json", asset.model_dump(mode="json"))
    return asset
