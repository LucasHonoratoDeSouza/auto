from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from tiktok_automation.config import Settings
from tiktok_automation.utils import clamp, slugify, write_json


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrategyArm(BaseModel):
    arm_id: str
    niche: str
    hook_style: str
    duration_band: str
    posting_slot: str
    delivery_style: str
    caption_style: str
    visual_style: str
    alpha: float = 1.0
    beta: float = 1.0
    posts: int = 0
    total_reward: float = 0.0
    last_used_at: str | None = None

    @property
    def mean_reward(self) -> float:
        if self.posts == 0:
            return 0.0
        return self.total_reward / self.posts


class PostFeedback(BaseModel):
    arm_id: str
    run_id: str | None = None
    posted_at: str = Field(default_factory=utc_now_iso)
    views_2h: int = 0
    views_24h: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    profile_visits: int = 0
    follows_gained: int = 0
    completion_rate: float | None = None
    avg_watch_time_sec: float | None = None
    ineligible_for_fyp: bool = False
    reward: float = 0.0


class GrowthState(BaseModel):
    goal_followers: int
    goal_total_views: int
    current_followers: int = 0
    current_total_views: int = 0
    created_at: str = Field(default_factory=utc_now_iso)
    last_updated_at: str = Field(default_factory=utc_now_iso)
    pivot_note: str | None = None
    arms: list[StrategyArm] = Field(default_factory=list)
    history: list[PostFeedback] = Field(default_factory=list)

    def arm_map(self) -> dict[str, StrategyArm]:
        return {arm.arm_id: arm for arm in self.arms}


class Recommendation(BaseModel):
    pivot_recommended: bool
    pivot_note: str | None = None
    progress_followers: float
    progress_views: float
    strategies: list[StrategyArm]


def build_default_arms() -> list[StrategyArm]:
    niches = ["business", "psychology", "money", "ai-tech"]
    hooks = ["question", "contrarian", "story"]
    durations = ["short", "medium"]
    slots = ["morning", "lunch", "night"]
    arms: list[StrategyArm] = []
    counter = 0

    for niche in niches:
        for hook in hooks:
            for duration in durations:
                slot = slots[counter % len(slots)]
                caption_style = "minimal" if duration == "short" else "contextual"
                visual_style = "aggressive" if hook in {"question", "contrarian"} else "clean"
                if hook == "story":
                    delivery_style = "story-cut"
                elif niche == "ai-tech":
                    delivery_style = "search-gap-answer"
                elif hook == "contrarian":
                    delivery_style = "debate-framing"
                else:
                    delivery_style = "cold-open-quote"
                arm_id = slugify(f"{niche}-{hook}-{duration}-{slot}")
                arms.append(
                    StrategyArm(
                        arm_id=arm_id,
                        niche=niche,
                        hook_style=hook,
                        duration_band=duration,
                        posting_slot=slot,
                        delivery_style=delivery_style,
                        caption_style=caption_style,
                        visual_style=visual_style,
                    )
                )
                counter += 1
    return arms


def initialize_state(settings: Settings) -> GrowthState:
    return GrowthState(
        goal_followers=settings.goal_followers,
        goal_total_views=settings.goal_total_views,
        arms=build_default_arms(),
    )


def save_state(state: GrowthState, path) -> None:
    state.last_updated_at = utc_now_iso()
    write_json(path, state.model_dump(mode="json"))


def compute_reward(
    feedback: PostFeedback,
    settings: Settings,
) -> float:
    follow_score = clamp(
        feedback.follows_gained / max(1, settings.reward_target_follows_per_post),
        0.0,
        1.0,
    )
    view_score = clamp(
        feedback.views_24h / max(1, settings.reward_target_views_per_post),
        0.0,
        1.0,
    )
    share_score = clamp(
        feedback.shares / max(1, settings.reward_target_shares_per_post),
        0.0,
        1.0,
    )
    profile_score = clamp(
        feedback.profile_visits / max(1, settings.reward_target_profile_visits_per_post),
        0.0,
        1.0,
    )
    completion_score = clamp(
        (feedback.completion_rate or 0.0) / max(0.01, settings.reward_target_completion_rate),
        0.0,
        1.0,
    )

    reward = (
        0.40 * follow_score
        + 0.25 * view_score
        + 0.15 * completion_score
        + 0.10 * share_score
        + 0.10 * profile_score
    )

    if feedback.views_24h >= settings.reward_target_views_per_post * 2:
        reward += 0.10
    elif feedback.views_24h >= settings.reward_target_views_per_post:
        reward += 0.05

    if feedback.ineligible_for_fyp:
        reward -= 0.35
    elif feedback.views_2h < 200 and feedback.views_24h < 1000:
        reward -= 0.10

    return round(clamp(reward, 0.0, 1.0), 4)


def update_state_with_feedback(
    state: GrowthState,
    feedback: PostFeedback,
    settings: Settings,
    current_followers: int | None = None,
    current_total_views: int | None = None,
) -> GrowthState:
    arm = state.arm_map().get(feedback.arm_id)
    if not arm:
        raise ValueError(f"Arm desconhecido: {feedback.arm_id}")

    feedback.reward = compute_reward(feedback, settings)
    arm.alpha += feedback.reward
    arm.beta += 1.0 - feedback.reward
    arm.posts += 1
    arm.total_reward += feedback.reward
    arm.last_used_at = feedback.posted_at
    state.history.append(feedback)

    if current_followers is not None:
        state.current_followers = current_followers
    else:
        state.current_followers += feedback.follows_gained

    if current_total_views is not None:
        state.current_total_views = current_total_views
    else:
        state.current_total_views += feedback.views_24h

    state.pivot_note = detect_pivot(state, settings)
    state.last_updated_at = utc_now_iso()
    return state


def detect_pivot(state: GrowthState, settings: Settings) -> str | None:
    if len(state.history) < settings.pivot_post_window:
        return None

    recent = state.history[-settings.pivot_post_window :]
    average_reward = sum(item.reward for item in recent) / len(recent)
    if average_reward >= settings.pivot_min_expected_reward:
        return None

    niche_rewards: dict[str, list[float]] = defaultdict(list)
    arm_lookup = state.arm_map()
    for event in recent:
        arm = arm_lookup.get(event.arm_id)
        if arm:
            niche_rewards[arm.niche].append(event.reward)

    weakest_niche = None
    weakest_reward = 999.0
    for niche, rewards in niche_rewards.items():
        if len(rewards) < 2:
            continue
        niche_avg = sum(rewards) / len(rewards)
        if niche_avg < weakest_reward:
            weakest_reward = niche_avg
            weakest_niche = niche

    if weakest_niche:
        return (
            f"Pivot recomendado: reduzir {weakest_niche} e explorar outros nichos. "
            f"Reward medio recente={average_reward:.2f}"
        )
    return f"Pivot recomendado: reward medio recente={average_reward:.2f}"


def recommend_strategies(
    state: GrowthState,
    settings: Settings,
    limit: int = 5,
) -> Recommendation:
    pivot_note = detect_pivot(state, settings)
    blocked_niche = None
    if pivot_note and "reduzir" in pivot_note:
        blocked_niche = pivot_note.split("reduzir ", 1)[1].split(" ", 1)[0]

    scored: list[tuple[float, StrategyArm]] = []
    for arm in state.arms:
        sample = random.betavariate(arm.alpha, arm.beta)
        exploration_bonus = settings.bandit_exploration_floor / (arm.posts + 1)
        novelty_bonus = 0.12 if arm.posts == 0 else 0.0
        pivot_penalty = 0.25 if blocked_niche and arm.niche == blocked_niche else 0.0
        score = sample + exploration_bonus + novelty_bonus - pivot_penalty
        scored.append((score, arm))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [arm for _, arm in scored[:limit]]

    return Recommendation(
        pivot_recommended=bool(pivot_note),
        pivot_note=pivot_note,
        progress_followers=round(state.current_followers / max(1, state.goal_followers), 4),
        progress_views=round(state.current_total_views / max(1, state.goal_total_views), 4),
        strategies=selected,
    )
