from __future__ import annotations

import mimetypes
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import Lock, Thread
from time import sleep
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tiktok_automation import __version__
from tiktok_automation.config import get_settings
from tiktok_automation.pipeline.orchestrator import execute_pipeline
from tiktok_automation.platforms.tiktok import TikTokAPIError, TikTokClient
from tiktok_automation.schemas import (
    ApproveCandidateRequest,
    CandidateCollection,
    PipelineRequest,
    QueueItem,
    QueueItemStatus,
    RenderCollection,
    SourceAsset,
    TranscriptResult,
    WebJob,
    WebJobStatus,
)
from tiktok_automation.utils import ensure_directory, read_json, write_json

settings = get_settings()
assets_dir = Path(__file__).with_name("web_assets")
jobs_root = ensure_directory(settings.workspace_root / "web_jobs")
queue_path = settings.workspace_root / "post_queue.json"
project_root = Path(__file__).resolve().parents[2]
env_path = project_root / ".env"
app_timezone = ZoneInfo("America/Sao_Paulo")
queue_lock = Lock()
queue_worker_started = False

app = FastAPI(title="TikTok Automation", version=__version__)
app.mount("/static", StaticFiles(directory=str(assets_dir)), name="static")
app.mount("/media/output", StaticFiles(directory=str(settings.output_root)), name="media-output")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    return jobs_root / f"{job_id}.json"


def _queue_items() -> list[QueueItem]:
    if not queue_path.exists():
        return []
    payload = read_json(queue_path)
    return [QueueItem.model_validate(item) for item in payload]


def _save_queue(items: list[QueueItem]) -> None:
    write_json(queue_path, [item.model_dump(mode="json") for item in items])


def _post_metadata_path(video_path: str) -> Path:
    return Path(video_path).with_suffix(".post.json")


def _save_job(job: WebJob) -> WebJob:
    write_json(_job_path(job.job_id), job.model_dump(mode="json"))
    return job


def _load_job(job_id: str) -> WebJob:
    path = _job_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    return WebJob.model_validate(read_json(path))


def _update_job(job_id: str, **changes) -> WebJob:
    job = _load_job(job_id)
    payload = job.model_dump(mode="json")
    payload.update(changes)
    payload["updated_at"] = _now_iso()
    return _save_job(WebJob.model_validate(payload))


def _queue_item_for(run_id: str, candidate_rank: int) -> QueueItem | None:
    matches = [
        item
        for item in _queue_items()
        if item.run_id == run_id and item.candidate_rank == candidate_rank
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.approved_at, reverse=True)[0]


def _post_metadata_for(video_path: str) -> dict | None:
    path = _post_metadata_path(video_path)
    if not path.exists():
        return None
    return read_json(path)


def _tiktok_status() -> dict:
    has_access_token = bool(settings.tiktok_user_access_token)
    has_refresh_path = bool(
        settings.tiktok_user_refresh_token
        and settings.tiktok_client_key
        and settings.tiktok_client_secret
    )
    return {
        "configured": has_access_token or has_refresh_path,
        "has_access_token": has_access_token,
        "has_refresh_path": has_refresh_path,
        "default_privacy_level": settings.post_default_privacy_level,
    }


def _delivery_mode() -> str:
    return settings.queue_execution_mode.strip().lower() or "notify_email"


def _email_status() -> dict:
    has_host = bool(settings.smtp_host)
    has_to = bool(settings.notification_email_to)
    has_from = bool(settings.notification_email_from or settings.smtp_username)
    auth_ready = not settings.smtp_username or bool(settings.smtp_password)
    return {
        "configured": has_host and has_to and has_from and auth_ready,
        "mode": _delivery_mode(),
        "lead_minutes": settings.notification_lead_minutes,
        "recipient": settings.notification_email_to,
    }


def _extract_hashtags(value: str) -> list[str]:
    found = re.findall(r"#([\w_]+)", value, flags=re.UNICODE)
    seen: set[str] = set()
    hashtags: list[str] = []
    for tag in found:
        normalized = tag.strip()
        if not normalized:
            continue
        token = f"#{normalized}"
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        hashtags.append(token)
    return hashtags


def _video_download_url(item: QueueItem) -> str | None:
    if not settings.app_public_base_url:
        return None
    video_name = Path(item.video_path).name
    return f"{settings.app_public_base_url.rstrip('/')}/media/output/{item.run_id}/{video_name}"


def _notify_at(item: QueueItem) -> datetime:
    return datetime.fromisoformat(item.scheduled_at) - timedelta(
        minutes=max(1, settings.notification_lead_minutes)
    )


def _manual_post_record(item: QueueItem) -> dict:
    return {
        "caption": item.caption,
        "hashtags": item.hashtags,
        "privacy_level": item.privacy_level,
        "posted_at": _now_iso(),
        "publish_id": "manual",
        "status": {
            "mode": "manual",
            "channel": item.notification_channel or "email",
        },
    }


def _upsert_env_value(key: str, value: str) -> None:
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updated = False
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_access_token(client: TikTokClient) -> str:
    access_token = settings.tiktok_user_access_token
    if settings.tiktok_user_refresh_token and settings.tiktok_client_key and settings.tiktok_client_secret:
        try:
            payload = client.refresh_token()
            refreshed_access = payload.get("access_token")
            refreshed_refresh = payload.get("refresh_token")
            if refreshed_access:
                settings.tiktok_user_access_token = refreshed_access
                _upsert_env_value("TIKTOK_USER_ACCESS_TOKEN", refreshed_access)
                access_token = refreshed_access
            if refreshed_refresh:
                settings.tiktok_user_refresh_token = refreshed_refresh
                _upsert_env_value("TIKTOK_USER_REFRESH_TOKEN", refreshed_refresh)
        except Exception:
            if not access_token:
                raise

    if not access_token:
        raise TikTokAPIError(
            "TikTok nao configurado para postar. Configure token de acesso ou refresh token."
        )
    return access_token


def _resolve_privacy_level(creator_info: dict, requested_privacy: str | None) -> str:
    allowed_privacies = creator_info.get("privacy_level_options") or []
    target = requested_privacy or settings.post_default_privacy_level
    if allowed_privacies and target not in allowed_privacies:
        if settings.post_default_privacy_level in allowed_privacies:
            return settings.post_default_privacy_level
        return allowed_privacies[0]
    return target


def _candidate_lookup(run_id: str, candidate_rank: int) -> tuple[SourceAsset, CandidateCollection, RenderCollection, dict]:
    run_dir = settings.runs_root / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run nao encontrado.")

    asset = SourceAsset.model_validate(read_json(run_dir / "metadata.json"))
    collection = CandidateCollection.model_validate(read_json(run_dir / "candidates.json"))
    rendered = RenderCollection.model_validate(read_json(run_dir / "rendered.json"))
    by_rank = {candidate.rank: candidate for candidate in collection.candidates}
    artifact = next((item for item in rendered.rendered if item.candidate_rank == candidate_rank), None)
    candidate = by_rank.get(candidate_rank)
    if not artifact or not candidate:
        raise HTTPException(status_code=404, detail="Candidato renderizado nao encontrado.")
    return asset, collection, rendered, {"candidate": candidate, "artifact": artifact}


def _best_publish_slot() -> tuple[datetime, str]:
    now = datetime.now(app_timezone)
    reserved: list[datetime] = []
    for item in _queue_items():
        if item.status in {
            QueueItemStatus.queued,
            QueueItemStatus.notifying,
            QueueItemStatus.notified,
            QueueItemStatus.posting,
        }:
            reserved.append(datetime.fromisoformat(item.scheduled_at))

    slot_map = {
        0: [(12, 5, "janela de almoco"), (18, 35, "saida do trabalho"), (21, 10, "prime noturno")],
        1: [(12, 5, "janela de almoco"), (18, 35, "saida do trabalho"), (21, 10, "prime noturno")],
        2: [(12, 5, "janela de almoco"), (18, 35, "saida do trabalho"), (21, 10, "prime noturno")],
        3: [(12, 5, "janela de almoco"), (18, 35, "saida do trabalho"), (21, 10, "prime noturno")],
        4: [(12, 5, "janela de almoco"), (18, 50, "sexta a noite"), (21, 25, "sexta prime")],
        5: [(11, 20, "sabado fim da manha"), (15, 40, "sabado tarde"), (20, 15, "sabado a noite")],
        6: [(11, 35, "domingo fim da manha"), (18, 10, "domingo pre-prime"), (20, 30, "domingo prime")],
    }

    for day_offset in range(14):
        current_day = (now + timedelta(days=day_offset)).date()
        weekday = (now + timedelta(days=day_offset)).weekday()
        for hour, minute, reason in slot_map[weekday]:
            slot = datetime(
                current_day.year,
                current_day.month,
                current_day.day,
                hour,
                minute,
                tzinfo=app_timezone,
            )
            if slot <= now + timedelta(minutes=10):
                continue
            if all(abs((slot - item_time).total_seconds()) >= 90 * 60 for item_time in reserved):
                return slot, reason

    fallback = (max(reserved) if reserved else now) + timedelta(hours=2)
    return fallback, "fallback de fila"


def _compose_notification_message(item: QueueItem) -> tuple[EmailMessage, bool]:
    video_path = Path(item.video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video nao encontrado: {video_path}")

    hashtags = item.hashtags or _extract_hashtags(item.caption)
    scheduled = datetime.fromisoformat(item.scheduled_at).astimezone(app_timezone)
    notify_time = _notify_at(item).astimezone(app_timezone)
    download_url = _video_download_url(item)
    max_bytes = max(1, settings.notification_attach_video_max_mb) * 1024 * 1024
    should_attach_video = video_path.stat().st_size <= max_bytes

    body_lines = [
        "Seu corte esta chegando na janela de postagem.",
        "",
        f"Titulo: {item.title}",
        f"Horario escolhido: {scheduled.strftime('%d/%m %H:%M')}",
        f"Aviso enviado em: {notify_time.strftime('%d/%m %H:%M')}",
        f"Arquivo: {video_path.name}",
        "",
        "Caption:",
        item.caption,
        "",
        "Hashtags:",
        " ".join(hashtags) if hashtags else "(nenhuma)",
        "",
        f"Caminho local: {video_path}",
    ]
    if download_url:
        body_lines.extend(["", f"Download: {download_url}"])
    if not should_attach_video:
        body_lines.extend(
            [
                "",
                "Video nao anexado porque passou do limite configurado para email.",
                f"Limite atual: {settings.notification_attach_video_max_mb} MB",
            ]
        )

    metadata_text = "\n".join(
        [
            f"Titulo: {item.title}",
            f"Horario escolhido: {scheduled.isoformat()}",
            f"Caption: {item.caption}",
            f"Hashtags: {' '.join(hashtags) if hashtags else ''}",
            f"Arquivo: {video_path}",
            f"Download: {download_url or ''}",
        ]
    )

    message = EmailMessage()
    message["Subject"] = f"[Cortes Lab] Post em {settings.notification_lead_minutes} min: {item.title}"
    message["From"] = settings.notification_email_from or settings.smtp_username or ""
    message["To"] = settings.notification_email_to or ""
    message.set_content("\n".join(body_lines))
    message.add_attachment(
        metadata_text.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename=f"{video_path.stem}-post.txt",
    )

    if should_attach_video:
        media_type, _ = mimetypes.guess_type(video_path.name)
        if media_type:
            maintype, subtype = media_type.split("/", 1)
        else:
            maintype, subtype = "video", "mp4"
        message.add_attachment(
            video_path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=video_path.name,
        )

    return message, should_attach_video


def _notify_queue_item(item: QueueItem) -> QueueItem:
    email_status = _email_status()
    if not email_status["configured"]:
        raise RuntimeError("Email nao configurado para o modo semi-automatico.")

    message, _ = _compose_notification_message(item)

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=60) as smtp:
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)

    payload = item.model_dump(mode="json")
    payload.update(
        {
            "status": QueueItemStatus.notified,
            "notification_sent_at": _now_iso(),
            "notification_channel": "email",
            "error": None,
        }
    )
    return QueueItem.model_validate(payload)


def _post_queue_item(item: QueueItem) -> QueueItem:
    client = TikTokClient(settings)
    access_token = _resolve_access_token(client)
    creator_info = client.query_creator_info(access_token)
    privacy_level = _resolve_privacy_level(creator_info, item.privacy_level)
    video_path = Path(item.video_path)

    init_payload = client.init_direct_post(
        access_token=access_token,
        video_path=video_path,
        title=item.caption,
        privacy_level=privacy_level,
        disable_comment=not settings.post_allow_comment,
        disable_duet=not settings.post_allow_duet,
        disable_stitch=not settings.post_allow_stitch,
        is_aigc=settings.post_is_aigc,
    )
    upload_url = init_payload.get("upload_url")
    publish_id = init_payload.get("publish_id")
    if not upload_url or not publish_id:
        raise TikTokAPIError("TikTok nao retornou upload_url/publish_id.")

    client.upload_video(upload_url=upload_url, video_path=video_path)
    status = client.fetch_post_status(access_token, publish_id=publish_id)

    post_record = {
        "caption": item.caption,
        "privacy_level": privacy_level,
        "posted_at": _now_iso(),
        "publish_id": publish_id,
        "status": status,
    }
    write_json(_post_metadata_path(item.video_path), post_record)

    payload = item.model_dump(mode="json")
    payload.update(
        {
            "status": QueueItemStatus.posted,
            "posted_at": post_record["posted_at"],
            "publish_id": publish_id,
            "privacy_level": privacy_level,
            "error": None,
        }
    )
    return QueueItem.model_validate(payload)


def _queue_worker_loop() -> None:
    while True:
        sleep(20)
        mode = _delivery_mode()
        if mode == "direct_post":
            if not _tiktok_status()["configured"]:
                continue

            with queue_lock:
                items = _queue_items()
                now = datetime.now(app_timezone)
                due_item = next(
                    (
                        item
                        for item in items
                        if item.status == QueueItemStatus.queued
                        and datetime.fromisoformat(item.scheduled_at) <= now
                    ),
                    None,
                )
                if not due_item:
                    continue

                due_item.status = QueueItemStatus.posting
                due_item.attempts += 1
                _save_queue(items)

            try:
                processed_item = _post_queue_item(due_item)
            except Exception as exc:
                with queue_lock:
                    items = _queue_items()
                    for index, item in enumerate(items):
                        if item.queue_id == due_item.queue_id:
                            item.status = QueueItemStatus.failed
                            item.error = str(exc)
                            items[index] = item
                            break
                    _save_queue(items)
                continue
        else:
            if not _email_status()["configured"]:
                continue

            with queue_lock:
                items = _queue_items()
                now = datetime.now(app_timezone)
                due_item = next(
                    (
                        item
                        for item in items
                        if item.status == QueueItemStatus.queued
                        and _notify_at(item) <= now
                    ),
                    None,
                )
                if not due_item:
                    continue

                due_item.status = QueueItemStatus.notifying
                due_item.attempts += 1
                _save_queue(items)

            try:
                processed_item = _notify_queue_item(due_item)
            except Exception as exc:
                with queue_lock:
                    items = _queue_items()
                    for index, item in enumerate(items):
                        if item.queue_id == due_item.queue_id:
                            item.status = QueueItemStatus.failed
                            item.error = str(exc)
                            items[index] = item
                            break
                    _save_queue(items)
                continue

        with queue_lock:
            items = _queue_items()
            for index, item in enumerate(items):
                if item.queue_id == processed_item.queue_id:
                    items[index] = processed_item
                    break
            _save_queue(items)


def _run_job(job_id: str) -> None:
    job = _update_job(
        job_id,
        status=WebJobStatus.running,
        stage="starting",
        message="Preparando o pipeline.",
        error=None,
    )
    request = PipelineRequest(
        url=job.source_url,
        rights_status=job.rights_status,
        top_k=job.top_k,
        render_top_k=max(job.render_top_k, job.top_k),
        language=job.language,
        strategy_arm_id=job.strategy_arm_id,
    )

    try:
        execution = execute_pipeline(
            request=request,
            settings=settings,
            stage_callback=lambda stage, message: _update_job(
                job_id,
                status=WebJobStatus.running,
                stage=stage,
                message=message,
            ),
        )
        _update_job(
            job_id,
            status=WebJobStatus.completed,
            stage="completed",
            message="Cortes gerados com sucesso.",
            run_id=execution.run_id,
            error=None,
        )
    except Exception as exc:
        _update_job(
            job_id,
            status=WebJobStatus.failed,
            stage="failed",
            message="Falha ao gerar cortes.",
            error=str(exc),
        )


def _metadata_path_for_video(video_path: str) -> Path:
    return Path(video_path).with_suffix(".json")


def _candidate_payload(run_id: str, collection: CandidateCollection, rendered: RenderCollection) -> list[dict]:
    by_rank = {candidate.rank: candidate for candidate in collection.candidates}
    output: list[dict] = []

    for artifact in rendered.rendered:
        candidate = by_rank.get(artifact.candidate_rank)
        if not candidate:
            continue

        metadata_path = _metadata_path_for_video(artifact.output_video_path)
        caption_metadata = read_json(metadata_path) if metadata_path.exists() else {}
        video_name = Path(artifact.output_video_path).name
        queue_item = _queue_item_for(run_id, candidate.rank)
        post_metadata = _post_metadata_for(artifact.output_video_path)
        output.append(
            {
                "rank": candidate.rank,
                "title": candidate.title,
                "hook": candidate.hook,
                "score": candidate.score,
                "start": candidate.start,
                "end": candidate.end,
                "duration_seconds": candidate.duration_seconds,
                "excerpt": candidate.excerpt,
                "reasons": candidate.reasons,
                "suggested_caption": caption_metadata.get(
                    "suggested_caption",
                    candidate.suggested_caption,
                ),
                "suggested_hashtags": caption_metadata.get(
                    "suggested_hashtags",
                    candidate.suggested_hashtags,
                ),
                "video_url": f"/media/output/{run_id}/{video_name}",
                "video_path": artifact.output_video_path,
                "subtitles_path": artifact.subtitles_path,
                "queue": queue_item.model_dump(mode="json") if queue_item else None,
                "post": post_metadata,
            }
        )

    return output


def _run_summary(run_id: str) -> dict:
    run_dir = settings.runs_root / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run nao encontrado.")

    asset = SourceAsset.model_validate(read_json(run_dir / "metadata.json"))
    transcript = TranscriptResult.model_validate(read_json(run_dir / "transcript.json"))
    collection = CandidateCollection.model_validate(read_json(run_dir / "candidates.json"))
    rendered = RenderCollection.model_validate(read_json(run_dir / "rendered.json"))
    candidates = _candidate_payload(run_id, collection, rendered)

    return {
        "run_id": run_id,
        "title": asset.title,
        "source_url": asset.source_url,
        "uploader": asset.uploader,
        "channel_url": asset.channel_url,
        "duration_seconds": asset.duration_seconds,
        "transcript_language": transcript.language,
        "transcript_provider": transcript.provider,
        "candidate_count": len(collection.candidates),
        "rendered_count": len(rendered.rendered),
        "candidates": candidates,
        "posting_ready": _tiktok_status()["configured"],
        "delivery_mode": _delivery_mode(),
        "delivery_ready": _email_status()["configured"] if _delivery_mode() != "direct_post" else _tiktok_status()["configured"],
    }


def _recent_runs(limit: int = 8) -> list[dict]:
    runs: list[dict] = []
    for path in sorted(settings.runs_root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        rendered_path = path / "rendered.json"
        metadata_path = path / "metadata.json"
        transcript_path = path / "transcript.json"
        if not (rendered_path.exists() and metadata_path.exists() and transcript_path.exists()):
            continue
        asset = SourceAsset.model_validate(read_json(metadata_path))
        transcript = TranscriptResult.model_validate(read_json(transcript_path))
        rendered = RenderCollection.model_validate(read_json(rendered_path))
        if not rendered.rendered:
            continue
        preview_name = Path(rendered.rendered[0].output_video_path).name
        runs.append(
            {
                "run_id": path.name,
                "title": asset.title,
                "uploader": asset.uploader,
                "transcript_provider": transcript.provider,
                "video_url": f"/media/output/{path.name}/{preview_name}",
            }
        )
        if len(runs) >= limit:
            break
    return runs


@app.get("/")
def index() -> FileResponse:
    return FileResponse(assets_dir / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/tiktok/status")
def tiktok_status() -> dict:
    return {
        "tiktok": _tiktok_status(),
        "email": _email_status(),
        "delivery_mode": _delivery_mode(),
    }


@app.get("/api/queue")
def queue_status() -> list[dict]:
    return [item.model_dump(mode="json") for item in _queue_items()]


@app.get("/api/recent-runs")
def recent_runs() -> list[dict]:
    return _recent_runs()


@app.post("/api/jobs")
def create_job(request: PipelineRequest) -> dict:
    resolved_render_top_k = max(request.render_top_k, request.top_k)
    job = WebJob(
        job_id=uuid4().hex[:12],
        source_url=request.url,
        rights_status=request.rights_status,
        top_k=request.top_k,
        render_top_k=resolved_render_top_k,
        language=request.language,
        strategy_arm_id=request.strategy_arm_id,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    _save_job(job)
    Thread(target=_run_job, args=(job.job_id,), daemon=True).start()
    return job.model_dump(mode="json")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _load_job(job_id).model_dump(mode="json")


@app.post("/api/runs/{run_id}/approve")
def approve_run_candidate(run_id: str, request: ApproveCandidateRequest) -> dict:
    _, _, _, resolved = _candidate_lookup(run_id, request.candidate_rank)
    candidate = resolved["candidate"]
    artifact = resolved["artifact"]
    scheduled_at, reason = _best_publish_slot()

    caption = (request.caption or candidate.suggested_caption).strip()
    if not caption:
        raise HTTPException(status_code=400, detail="Caption vazia.")
    hashtags = _extract_hashtags(caption)
    if not hashtags:
        hashtags = candidate.suggested_hashtags

    with queue_lock:
        items = _queue_items()
        existing = next(
            (
                item
                for item in items
                if item.run_id == run_id and item.candidate_rank == request.candidate_rank
            ),
            None,
        )
        if existing and existing.status == QueueItemStatus.posted:
            return existing.model_dump(mode="json")

        queue_item = QueueItem(
            queue_id=existing.queue_id if existing else uuid4().hex[:12],
            run_id=run_id,
            candidate_rank=request.candidate_rank,
            title=candidate.title,
            video_path=artifact.output_video_path,
            caption=caption,
            hashtags=hashtags,
            privacy_level=request.privacy_level,
            status=QueueItemStatus.queued,
            approved_at=existing.approved_at if existing else _now_iso(),
            scheduled_at=scheduled_at.isoformat(),
            schedule_reason=reason,
            notification_sent_at=None,
            notification_channel=None,
            attempts=existing.attempts if existing else 0,
            error=None,
        )

        if existing:
            items = [queue_item if item.queue_id == existing.queue_id else item for item in items]
        else:
            items.append(queue_item)
        _save_queue(items)

    return queue_item.model_dump(mode="json")


@app.post("/api/queue/{queue_id}/mark-posted")
def mark_queue_item_posted(queue_id: str) -> dict:
    with queue_lock:
        items = _queue_items()
        match = next((item for item in items if item.queue_id == queue_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Item da fila nao encontrado.")

        post_record = _manual_post_record(match)
        write_json(_post_metadata_path(match.video_path), post_record)

        payload = match.model_dump(mode="json")
        payload.update(
            {
                "status": QueueItemStatus.posted,
                "posted_at": post_record["posted_at"],
                "publish_id": post_record["publish_id"],
                "error": None,
            }
        )
        updated_item = QueueItem.model_validate(payload)
        items = [updated_item if item.queue_id == queue_id else item for item in items]
        _save_queue(items)

    return {
        "queue": updated_item.model_dump(mode="json"),
        "post": post_record,
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _run_summary(run_id)


@app.on_event("startup")
def start_queue_worker() -> None:
    global queue_worker_started
    if queue_worker_started:
        return
    queue_worker_started = True
    Thread(target=_queue_worker_loop, daemon=True).start()
