from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tiktok_automation.config import get_settings
from tiktok_automation.learning.bandit import (
    PostFeedback,
    GrowthState,
    initialize_state,
    recommend_strategies,
    save_state,
    update_state_with_feedback,
)
from tiktok_automation.pipeline.orchestrator import execute_pipeline
from tiktok_automation.pipeline.clip_scoring import build_candidates, persist_candidates
from tiktok_automation.pipeline.rendering import render_candidate
from tiktok_automation.pipeline.transcription import transcribe_source
from tiktok_automation.pipeline.youtube_ingest import download_source
from tiktok_automation.platforms.tiktok import TikTokClient
from tiktok_automation.schemas import (
    CandidateCollection,
    PipelineRequest,
    RenderCollection,
    RightsStatus,
    SourceAsset,
    TranscriptResult,
)
from tiktok_automation.utils import read_json, write_json

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _load_asset(run_id: str) -> SourceAsset:
    settings = get_settings()
    return SourceAsset.model_validate(read_json(settings.runs_root / run_id / "metadata.json"))


def _load_transcript(run_id: str) -> TranscriptResult:
    settings = get_settings()
    return TranscriptResult.model_validate(read_json(settings.runs_root / run_id / "transcript.json"))


def _load_candidates(run_id: str) -> CandidateCollection:
    settings = get_settings()
    return CandidateCollection.model_validate(read_json(settings.runs_root / run_id / "candidates.json"))


@app.command("from-link")
def from_link(
    url: str = typer.Option(..., help="Link do video-fonte."),
    rights_status: RightsStatus = typer.Option(
        ...,
        help="owned, licensed ou permissioned. Necessario para compliance.",
    ),
    top_k: int = typer.Option(5, help="Quantidade de candidatos ranqueados."),
    render_top_k: int = typer.Option(3, help="Quantidade de cortes para renderizar."),
    language: str | None = typer.Option(None, help="Idioma da transcricao, ex.: pt."),
    strategy_arm_id: str | None = typer.Option(
        None,
        help="Opcional. Arm escolhido pelo growth engine para este run.",
    ),
) -> None:
    settings = get_settings()
    execution = execute_pipeline(
        PipelineRequest(
            url=url,
            rights_status=rights_status,
            top_k=top_k,
            render_top_k=render_top_k,
            language=language,
            strategy_arm_id=strategy_arm_id,
        ),
        settings=settings,
    )

    table = Table(title=f"Run {execution.run_id}")
    table.add_column("Rank")
    table.add_column("Score")
    table.add_column("Inicio")
    table.add_column("Fim")
    table.add_column("Titulo")
    for candidate in execution.candidates.candidates:
        table.add_row(
            str(candidate.rank),
            str(candidate.score),
            f"{candidate.start:.1f}s",
            f"{candidate.end:.1f}s",
            candidate.title,
        )
    console.print(table)
    console.print(f"Run salvo em: {settings.runs_root / execution.run_id}")


@app.command("ingest")
def ingest(
    url: str = typer.Option(..., help="Link do YouTube ou da fonte."),
    rights_status: RightsStatus = typer.Option(..., help="Status de direitos do conteudo."),
    strategy_arm_id: str | None = typer.Option(None, help="Arm opcional associado ao run."),
) -> None:
    settings = get_settings()
    asset = download_source(
        url=url,
        rights_status=rights_status,
        settings=settings,
        strategy_arm_id=strategy_arm_id,
    )
    console.print(asset.model_dump_json(indent=2))


@app.command("transcribe")
def transcribe(
    run_id: str = typer.Option(..., help="Run criado anteriormente pelo ingest."),
    language: str | None = typer.Option(None, help="Idioma da transcricao."),
) -> None:
    settings = get_settings()
    asset = _load_asset(run_id)
    transcript = transcribe_source(asset, settings=settings, language=language)
    console.print(transcript.model_dump_json(indent=2))


@app.command("rank-clips")
def rank_clips(
    run_id: str = typer.Option(..., help="Run com transcript.json pronto."),
    top_k: int = typer.Option(5, help="Quantidade de candidatos."),
) -> None:
    settings = get_settings()
    transcript = _load_transcript(run_id)
    collection = build_candidates(transcript, top_k=top_k)
    persist_candidates(collection, settings.runs_root / run_id / "candidates.json")
    console.print(collection.model_dump_json(indent=2))


@app.command("render-clips")
def render_clips(
    run_id: str = typer.Option(..., help="Run com candidates.json pronto."),
    limit: int = typer.Option(3, help="Quantidade de videos para renderizar."),
) -> None:
    settings = get_settings()
    asset = _load_asset(run_id)
    transcript = _load_transcript(run_id)
    collection = _load_candidates(run_id)
    rendered = [
        render_candidate(asset, transcript, candidate, settings)
        for candidate in collection.candidates[:limit]
    ]
    result = RenderCollection(run_id=run_id, rendered=rendered)
    write_json(
        settings.runs_root / run_id / "rendered.json",
        result.model_dump(mode="json"),
    )
    console.print(result.model_dump_json(indent=2))


@app.command("tiktok-auth-url")
def tiktok_auth_url() -> None:
    client = TikTokClient(get_settings())
    console.print(client.build_authorization_url())


@app.command("tiktok-exchange-code")
def tiktok_exchange_code(
    code: str = typer.Option(..., help="Code recebido no callback do TikTok."),
) -> None:
    client = TikTokClient(get_settings())
    payload = client.exchange_code(code)
    console.print_json(data=payload)


@app.command("tiktok-refresh-token")
def tiktok_refresh_token(
    refresh_token: str | None = typer.Option(
        None,
        help="Opcional. Se omitido, usa TIKTOK_USER_REFRESH_TOKEN do .env.",
    ),
) -> None:
    client = TikTokClient(get_settings())
    payload = client.refresh_token(refresh_token)
    console.print_json(data=payload)


@app.command("tiktok-post")
def tiktok_post(
    video: Path = typer.Option(..., exists=True, dir_okay=False, help="Video final .mp4."),
    title: str = typer.Option(..., help="Titulo/caption inicial do post."),
    access_token: str | None = typer.Option(
        None,
        help="Opcional. Se omitido, usa TIKTOK_USER_ACCESS_TOKEN do .env.",
    ),
    privacy_level: str | None = typer.Option(
        None,
        help="Opcional. Se omitido, usa POST_DEFAULT_PRIVACY_LEVEL.",
    ),
) -> None:
    settings = get_settings()
    token = access_token or settings.tiktok_user_access_token
    if not token:
        raise typer.BadParameter(
            "Forneca --access-token ou configure TIKTOK_USER_ACCESS_TOKEN no .env."
        )

    client = TikTokClient(settings)
    creator_info = client.query_creator_info(token)
    resolved_privacy = privacy_level or settings.post_default_privacy_level
    allowed_privacies = creator_info.get("privacy_level_options") or []
    if allowed_privacies and resolved_privacy not in allowed_privacies:
        raise typer.BadParameter(
            f"privacy_level '{resolved_privacy}' nao permitido para esta conta. "
            f"Opcoes: {allowed_privacies}"
        )

    init_payload = client.init_direct_post(
        access_token=token,
        video_path=video,
        title=title,
        privacy_level=resolved_privacy,
        disable_comment=not settings.post_allow_comment,
        disable_duet=not settings.post_allow_duet,
        disable_stitch=not settings.post_allow_stitch,
        is_aigc=settings.post_is_aigc,
    )
    upload_url = init_payload.get("upload_url")
    publish_id = init_payload.get("publish_id")
    if not upload_url or not publish_id:
        raise typer.BadParameter("TikTok nao retornou upload_url/publish_id.")

    client.upload_video(upload_url=upload_url, video_path=video)
    status = client.fetch_post_status(token, publish_id=publish_id)

    console.print_json(
        data={
            "creator_info": creator_info,
            "init_payload": init_payload,
            "status": status,
        }
    )


@app.command("strategy-init")
def strategy_init(force: bool = typer.Option(False, help="Sobrescreve estado existente.")) -> None:
    settings = get_settings()
    path = settings.strategy_state_path
    if path.exists() and not force:
        raise typer.BadParameter(
            f"{path} ja existe. Use --force se quiser recriar o estado."
        )
    state = initialize_state(settings)
    save_state(state, path)
    console.print(f"Estado inicial salvo em {path}")


@app.command("strategy-next")
def strategy_next(limit: int = typer.Option(5, help="Quantidade de estrategias sugeridas.")) -> None:
    settings = get_settings()
    path = settings.strategy_state_path
    if not path.exists():
        raise typer.BadParameter("Rode strategy-init primeiro.")

    state = GrowthState.model_validate(read_json(path))
    recommendation = recommend_strategies(state, settings=settings, limit=limit)

    table = Table(title="Proximas estrategias")
    table.add_column("Arm")
    table.add_column("Nicho")
    table.add_column("Hook")
    table.add_column("Duracao")
    table.add_column("Slot")
    table.add_column("Delivery")
    table.add_column("Posts")
    table.add_column("Mean")

    for arm in recommendation.strategies:
        table.add_row(
            arm.arm_id,
            arm.niche,
            arm.hook_style,
            arm.duration_band,
            arm.posting_slot,
            arm.delivery_style,
            str(arm.posts),
            f"{arm.mean_reward:.2f}",
        )

    console.print(table)
    console.print(
        {
            "progress_followers": recommendation.progress_followers,
            "progress_views": recommendation.progress_views,
            "pivot_recommended": recommendation.pivot_recommended,
            "pivot_note": recommendation.pivot_note,
            "refresh_sources": [
                "Creator Search Insights",
                "Comment Insights",
                "For You feed review",
            ],
        }
    )


@app.command("strategy-feedback")
def strategy_feedback(
    arm_id: str = typer.Option(..., help="Arm usado no post."),
    run_id: str | None = typer.Option(None, help="Run associado ao post."),
    views_2h: int = typer.Option(0, help="Views nas primeiras 2h."),
    views_24h: int = typer.Option(0, help="Views em 24h."),
    likes: int = typer.Option(0),
    comments: int = typer.Option(0),
    shares: int = typer.Option(0),
    saves: int = typer.Option(0),
    profile_visits: int = typer.Option(0),
    follows_gained: int = typer.Option(0),
    completion_rate: float | None = typer.Option(None),
    avg_watch_time_sec: float | None = typer.Option(None),
    ineligible_for_fyp: bool = typer.Option(False),
    current_followers: int | None = typer.Option(
        None,
        help="Total atual de seguidores do perfil. Se omitido, soma follows_gained.",
    ),
    current_total_views: int | None = typer.Option(
        None,
        help="Views totais atuais do perfil. Se omitido, soma views_24h.",
    ),
) -> None:
    settings = get_settings()
    path = settings.strategy_state_path
    if not path.exists():
        raise typer.BadParameter("Rode strategy-init primeiro.")

    state = GrowthState.model_validate(read_json(path))
    feedback = PostFeedback(
        arm_id=arm_id,
        run_id=run_id,
        views_2h=views_2h,
        views_24h=views_24h,
        likes=likes,
        comments=comments,
        shares=shares,
        saves=saves,
        profile_visits=profile_visits,
        follows_gained=follows_gained,
        completion_rate=completion_rate,
        avg_watch_time_sec=avg_watch_time_sec,
        ineligible_for_fyp=ineligible_for_fyp,
    )
    state = update_state_with_feedback(
        state=state,
        feedback=feedback,
        settings=settings,
        current_followers=current_followers,
        current_total_views=current_total_views,
    )
    save_state(state, path)
    console.print_json(
        data={
            "reward": feedback.reward,
            "current_followers": state.current_followers,
            "current_total_views": state.current_total_views,
            "pivot_note": state.pivot_note,
        }
    )


@app.command("web")
def web(
    host: str = typer.Option("127.0.0.1", help="Host do servidor web."),
    port: int = typer.Option(8787, help="Porta do servidor web."),
    reload: bool = typer.Option(False, help="Ativa autoreload para desenvolvimento."),
) -> None:
    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - depends on local runtime
        raise RuntimeError(
            "Servidor web indisponivel. Instale as dependencias com `uv pip install -e .`."
        ) from exc

    uvicorn.run(
        "tiktok_automation.web:app",
        host=host,
        port=port,
        reload=reload,
    )
