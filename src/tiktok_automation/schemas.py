from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RightsStatus(StrEnum):
    owned = "owned"
    licensed = "licensed"
    permissioned = "permissioned"


class SourceAsset(BaseModel):
    run_id: str
    source_url: str
    rights_status: RightsStatus
    title: str
    strategy_arm_id: str | None = None
    subtitle_path: str | None = None
    subtitle_language: str | None = None
    uploader: str | None = None
    channel_url: str | None = None
    description: str | None = None
    upload_date: str | None = None
    duration_seconds: float | None = None
    source_video_path: str
    thumbnail_url: str | None = None


class WordTiming(BaseModel):
    text: str
    start: float
    end: float


class TranscriptSegment(BaseModel):
    index: int
    start: float
    end: float
    text: str
    words: list[WordTiming] = Field(default_factory=list)


class TranscriptResult(BaseModel):
    run_id: str
    source_video_path: str
    language: str | None = None
    provider: str | None = None
    duration_seconds: float | None = None
    text: str
    segments: list[TranscriptSegment] = Field(default_factory=list)

    def all_words(self) -> list[WordTiming]:
        output: list[WordTiming] = []
        for segment in self.segments:
            output.extend(segment.words)
        return output


class ClipCandidate(BaseModel):
    rank: int
    title: str
    hook: str
    start: float
    end: float
    duration_seconds: float
    score: float
    excerpt: str
    reasons: list[str] = Field(default_factory=list)
    suggested_caption: str
    suggested_hashtags: list[str] = Field(default_factory=list)


class CandidateCollection(BaseModel):
    run_id: str
    source_video_path: str
    candidates: list[ClipCandidate] = Field(default_factory=list)


class RenderArtifact(BaseModel):
    candidate_rank: int
    title: str
    output_video_path: str
    subtitles_path: str


class RenderCollection(BaseModel):
    run_id: str
    rendered: list[RenderArtifact] = Field(default_factory=list)


class PipelineRequest(BaseModel):
    url: str
    rights_status: RightsStatus = RightsStatus.permissioned
    top_k: int = 5
    render_top_k: int = 3
    language: str | None = None
    strategy_arm_id: str | None = None


class PipelineExecution(BaseModel):
    run_id: str
    asset: SourceAsset
    transcript: TranscriptResult
    candidates: CandidateCollection
    rendered: RenderCollection


class WebJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class WebJob(BaseModel):
    job_id: str
    source_url: str
    rights_status: RightsStatus
    top_k: int
    render_top_k: int
    language: str | None = None
    strategy_arm_id: str | None = None
    status: WebJobStatus = WebJobStatus.queued
    stage: str = "queued"
    message: str = "Na fila."
    error: str | None = None
    run_id: str | None = None
    created_at: str
    updated_at: str


class QueueItemStatus(StrEnum):
    queued = "queued"
    notifying = "notifying"
    notified = "notified"
    posting = "posting"
    posted = "posted"
    failed = "failed"


class ApproveCandidateRequest(BaseModel):
    candidate_rank: int
    caption: str | None = None
    privacy_level: str | None = None


class QueueItem(BaseModel):
    queue_id: str
    run_id: str
    candidate_rank: int
    title: str
    video_path: str
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    privacy_level: str | None = None
    status: QueueItemStatus = QueueItemStatus.queued
    approved_at: str
    scheduled_at: str
    schedule_reason: str | None = None
    notification_sent_at: str | None = None
    notification_channel: str | None = None
    posted_at: str | None = None
    publish_id: str | None = None
    attempts: int = 0
    error: str | None = None
