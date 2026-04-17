from __future__ import annotations

import mimetypes
import secrets
from pathlib import Path
from urllib.parse import urlencode

import requests

from tiktok_automation.config import Settings


class TikTokAPIError(RuntimeError):
    pass


class TikTokClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.oauth_base_url = "https://www.tiktok.com/v2/auth/authorize/"
        self.api_base_url = "https://open.tiktokapis.com"

    def build_authorization_url(self, state: str | None = None, disable_auto_auth: int = 0) -> str:
        if not self.settings.tiktok_client_key or not self.settings.tiktok_redirect_uri:
            raise TikTokAPIError(
                "TIKTOK_CLIENT_KEY e TIKTOK_REDIRECT_URI precisam estar configurados."
            )

        query = {
            "client_key": self.settings.tiktok_client_key,
            "response_type": "code",
            "scope": self.settings.tiktok_scopes,
            "redirect_uri": self.settings.tiktok_redirect_uri,
            "state": state or secrets.token_urlsafe(24),
            "disable_auto_auth": str(disable_auto_auth),
        }
        return f"{self.oauth_base_url}?{urlencode(query)}"

    def exchange_code(self, code: str) -> dict:
        return self._oauth_token(
            {
                "client_key": self._required(self.settings.tiktok_client_key, "TIKTOK_CLIENT_KEY"),
                "client_secret": self._required(
                    self.settings.tiktok_client_secret,
                    "TIKTOK_CLIENT_SECRET",
                ),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self._required(
                    self.settings.tiktok_redirect_uri,
                    "TIKTOK_REDIRECT_URI",
                ),
            }
        )

    def refresh_token(self, refresh_token: str | None = None) -> dict:
        token = refresh_token or self.settings.tiktok_user_refresh_token
        return self._oauth_token(
            {
                "client_key": self._required(self.settings.tiktok_client_key, "TIKTOK_CLIENT_KEY"),
                "client_secret": self._required(
                    self.settings.tiktok_client_secret,
                    "TIKTOK_CLIENT_SECRET",
                ),
                "refresh_token": self._required(token, "TIKTOK_USER_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            }
        )

    def _oauth_token(self, form: dict[str, str]) -> dict:
        response = requests.post(
            f"{self.api_base_url}/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=form,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def query_creator_info(self, access_token: str) -> dict:
        response = requests.post(
            f"{self.api_base_url}/v2/post/publish/creator_info/query/",
            headers=self._bearer_headers(access_token),
            json={},
            timeout=60,
        )
        response.raise_for_status()
        return self._unwrap(response.json())

    def init_direct_post(
        self,
        access_token: str,
        video_path: Path,
        title: str,
        privacy_level: str,
        disable_comment: bool,
        disable_duet: bool,
        disable_stitch: bool,
        is_aigc: bool,
        video_cover_timestamp_ms: int = 0,
    ) -> dict:
        video_size = video_path.stat().st_size
        chunk_size = self._chunk_size_for(video_size)
        total_chunk_count = max(1, (video_size + chunk_size - 1) // chunk_size)
        payload = {
            "post_info": {
                "title": title,
                "privacy_level": privacy_level,
                "disable_comment": disable_comment,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
                "video_cover_timestamp_ms": video_cover_timestamp_ms,
                "brand_content_toggle": False,
                "brand_organic_toggle": False,
                "is_aigc": is_aigc,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunk_count,
            },
        }
        response = requests.post(
            f"{self.api_base_url}/v2/post/publish/video/init/",
            headers=self._bearer_headers(access_token),
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return self._unwrap(response.json())

    def upload_video(self, upload_url: str, video_path: Path) -> None:
        total_size = video_path.stat().st_size
        chunk_size = self._chunk_size_for(total_size)
        mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"

        with video_path.open("rb") as handle:
            cursor = 0
            while cursor < total_size:
                data = handle.read(chunk_size)
                if not data:
                    break
                last_byte = cursor + len(data) - 1
                headers = {
                    "Content-Type": mime_type,
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {cursor}-{last_byte}/{total_size}",
                }
                response = requests.put(
                    upload_url,
                    headers=headers,
                    data=data,
                    timeout=180,
                )
                if response.status_code not in {200, 201, 206}:
                    raise TikTokAPIError(
                        f"Falha no upload para TikTok: HTTP {response.status_code} - {response.text}"
                    )
                cursor = last_byte + 1

    def fetch_post_status(self, access_token: str, publish_id: str) -> dict:
        response = requests.post(
            f"{self.api_base_url}/v2/post/publish/status/fetch/",
            headers=self._bearer_headers(access_token),
            json={"publish_id": publish_id},
            timeout=60,
        )
        response.raise_for_status()
        return self._unwrap(response.json())

    def _unwrap(self, payload: dict) -> dict:
        error = payload.get("error") or {}
        code = error.get("code")
        if code and code != "ok":
            raise TikTokAPIError(f"{code}: {error.get('message', '')}".strip())
        return payload.get("data", payload)

    def _bearer_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def _required(self, value: str | None, env_name: str) -> str:
        if not value:
            raise TikTokAPIError(f"{env_name} nao configurado.")
        return value

    def _chunk_size_for(self, total_size: int) -> int:
        configured = self.settings.upload_chunk_size_bytes
        if total_size < 5 * 1024 * 1024:
            return total_size
        if total_size <= configured:
            return total_size
        return configured

