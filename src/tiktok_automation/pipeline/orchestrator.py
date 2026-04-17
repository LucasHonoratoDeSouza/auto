from __future__ import annotations

from collections.abc import Callable

from tiktok_automation.config import Settings
from tiktok_automation.pipeline.clip_scoring import build_candidates, persist_candidates
from tiktok_automation.pipeline.rendering import render_candidate
from tiktok_automation.pipeline.transcription import transcribe_source
from tiktok_automation.pipeline.youtube_ingest import download_source
from tiktok_automation.schemas import PipelineExecution, PipelineRequest, RenderCollection
from tiktok_automation.utils import write_json


StageCallback = Callable[[str, str], None]


def _notify(callback: StageCallback | None, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)


def execute_pipeline(
    request: PipelineRequest,
    settings: Settings,
    stage_callback: StageCallback | None = None,
) -> PipelineExecution:
    _notify(stage_callback, "downloading", "Baixando video e captions do YouTube.")
    asset = download_source(
        url=request.url,
        rights_status=request.rights_status,
        settings=settings,
        strategy_arm_id=request.strategy_arm_id,
    )

    _notify(stage_callback, "transcribing", "Preparando transcript gratis.")
    transcript = transcribe_source(
        asset=asset,
        settings=settings,
        language=request.language,
    )

    _notify(stage_callback, "scoring", "Ranqueando os melhores cortes.")
    collection = build_candidates(transcript=transcript, top_k=request.top_k)
    persist_candidates(collection, settings.runs_root / asset.run_id / "candidates.json")

    _notify(stage_callback, "rendering", "Renderizando cortes verticais com legenda.")
    rendered = []
    for candidate in collection.candidates[: request.render_top_k]:
        rendered.append(render_candidate(asset, transcript, candidate, settings))

    render_collection = RenderCollection(run_id=asset.run_id, rendered=rendered)
    write_json(
        settings.runs_root / asset.run_id / "rendered.json",
        render_collection.model_dump(mode="json"),
    )

    _notify(stage_callback, "completed", "Cortes prontos para revisar.")
    return PipelineExecution(
        run_id=asset.run_id,
        asset=asset,
        transcript=transcript,
        candidates=collection,
        rendered=render_collection,
    )
