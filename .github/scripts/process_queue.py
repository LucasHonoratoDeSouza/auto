from __future__ import annotations

import json
import mimetypes
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUEUE_ITEMS = ROOT / "github_queue" / "items"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _format_dt(value: str) -> str:
    return datetime.fromisoformat(value).astimezone().strftime("%d/%m %H:%M")


def _compose_email(payload: dict) -> EmailMessage:
    video_path = ROOT / payload["video_path"]
    hashtags = payload.get("hashtags") or []
    github_url = payload.get("github_video_url") or ""
    attach_limit_mb = int(os.getenv("NOTIFICATION_ATTACH_VIDEO_MAX_MB", "20"))
    attach_limit_bytes = max(1, attach_limit_mb) * 1024 * 1024
    attach_video = video_path.exists() and video_path.stat().st_size <= attach_limit_bytes

    body_lines = [
        "Seu corte esta chegando na janela de postagem.",
        "",
        f"Titulo: {payload['title']}",
        f"Horario escolhido: {_format_dt(payload['scheduled_at'])}",
        f"Caption: {payload['caption']}",
        f"Hashtags: {' '.join(hashtags) if hashtags else '(nenhuma)'}",
    ]
    if github_url:
        body_lines.extend(["", f"Download: {github_url}"])
    if not attach_video:
        body_lines.extend(
            [
                "",
                "O video nao foi anexado por causa do limite de tamanho do email.",
            ]
        )

    metadata_text = "\n".join(
        [
            f"queue_id: {payload['queue_id']}",
            f"run_id: {payload['run_id']}",
            f"candidate_rank: {payload['candidate_rank']}",
            f"title: {payload['title']}",
            f"scheduled_at: {payload['scheduled_at']}",
            f"caption: {payload['caption']}",
            f"hashtags: {' '.join(hashtags)}",
            f"github_video_url: {github_url}",
        ]
    )

    sender_email = os.environ["MAIL_FROM"]
    sender_name = os.getenv("MAIL_SENDER_NAME", "").strip()

    message = EmailMessage()
    message["Subject"] = f"[Cortes Lab] Post em {os.getenv('NOTIFICATION_LEAD_MINUTES', '5')} min: {payload['title']}"
    message["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
    message["To"] = os.environ["MAIL_TO"]
    message.set_content("\n".join(body_lines))
    message.add_attachment(
        metadata_text.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename=f"{video_path.stem}-post.txt",
    )

    if attach_video:
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

    return message


def _send_email(message: EmailMessage) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "465"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    use_ssl = _env_bool("SMTP_USE_SSL", True)
    use_tls = _env_bool("SMTP_USE_TLS", False)

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=60) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=60) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


def main() -> int:
    if not QUEUE_ITEMS.exists():
        print("github_queue/items inexistente; nada para processar.")
        return 0

    now = datetime.now(timezone.utc)
    sent = 0
    failed = 0

    for path in sorted(QUEUE_ITEMS.glob("*.json")):
        payload = _read_json(path)
        status = payload.get("status")
        if status != "queued":
            continue

        notify_at = datetime.fromisoformat(payload["notify_at"])
        if notify_at > now:
            continue

        try:
            message = _compose_email(payload)
            _send_email(message)
            payload["status"] = "notified"
            payload["notification_sent_at"] = datetime.now(timezone.utc).isoformat()
            payload["notification_channel"] = "github_actions_email"
            payload["error"] = None
            sent += 1
        except Exception as exc:
            payload["status"] = "failed"
            payload["error"] = str(exc)
            failed += 1
        _write_json(path, payload)

    print(f"queue processed: sent={sent} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
