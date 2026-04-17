from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    workspace_root: Path = Path("workspace")
    output_root: Path = Path("output")
    tmp_root: Path = Path(".tmp")
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"

    yt_dlp_cookies_file: str | None = None
    youtube_proxy_url: str | None = None

    transcription_provider: str = "auto"
    local_transcription_model: str = "small"
    local_transcription_device: str = "cpu"
    local_transcription_compute_type: str = "int8"
    local_transcription_beam_size: int = 5
    local_transcription_vad_filter: bool = True

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_organization: str | None = None
    openai_project: str | None = None
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_transcription_language: str = "pt"
    openai_request_timeout_seconds: int = 180
    transcription_max_audio_bytes: int = 18_000_000
    transcription_chunk_minutes: int = 15

    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"
    groq_request_timeout_seconds: int = 60

    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None
    tiktok_redirect_uri: str | None = None
    tiktok_scopes: str = "user.info.basic,video.publish,video.upload"
    tiktok_user_access_token: str | None = None
    tiktok_user_refresh_token: str | None = None
    tiktok_open_id: str | None = None
    tiktok_webhook_url: str | None = None
    tiktok_webhook_verify_token: str | None = None
    tiktok_upload_chunk_size_mb: int = 10

    queue_execution_mode: str = "notify_email"
    notification_lead_minutes: int = 5
    app_public_base_url: str | None = None
    notification_email_to: str | None = None
    notification_email_from: str | None = None
    notification_attach_video_max_mb: int = 20
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    post_default_privacy_level: str = "SELF_ONLY"
    post_allow_comment: bool = True
    post_allow_duet: bool = True
    post_allow_stitch: bool = True
    post_is_aigc: bool = False

    source_rights_policy: str = "strict"
    storage_public_base_url: str | None = None
    storage_upload_root: str | None = None

    goal_followers: int = 10_000
    goal_total_views: int = 100_000
    reward_target_views_per_post: int = 5_000
    reward_target_follows_per_post: int = 25
    reward_target_shares_per_post: int = 20
    reward_target_profile_visits_per_post: int = 50
    reward_target_completion_rate: float = 0.35
    bandit_exploration_floor: float = 0.25
    pivot_post_window: int = 12
    pivot_min_expected_reward: float = 0.35

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def prepare_directories(self) -> None:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.tmp_root.mkdir(parents=True, exist_ok=True)

    @property
    def runs_root(self) -> Path:
        return self.workspace_root / "runs"

    @property
    def cookies_path(self) -> Path | None:
        if not self.yt_dlp_cookies_file:
            return None
        value = self.yt_dlp_cookies_file.strip()
        return Path(value) if value else None

    @property
    def upload_chunk_size_bytes(self) -> int:
        return max(5, min(self.tiktok_upload_chunk_size_mb, 64)) * 1024 * 1024

    @property
    def strategy_state_path(self) -> Path:
        return self.workspace_root / "strategy_state.json"

    @property
    def use_openai_transcription(self) -> bool:
        return self.transcription_provider in {"openai", "openai-only"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    settings.runs_root.mkdir(parents=True, exist_ok=True)
    return settings
