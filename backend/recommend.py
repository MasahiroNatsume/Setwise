from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _normalize(feature_map: dict[str, float]) -> dict[str, float]:
    if not feature_map:
        return {}
    values = list(feature_map.values())
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return {k: max(0.0, min(1.0, v)) for k, v in feature_map.items()}
    return {k: (v - lo) / (hi - lo) for k, v in feature_map.items()}


def build_recommendations(
    *,
    user_id: str,
    episodes: list[dict[str, Any]],
    user_events: list[dict[str, Any]],
    all_events: list[dict[str, Any]],
    limit: int = 20,
    exploration_ratio: float = 0.2,
) -> list[dict[str, Any]]:
    if not episodes:
        return []

    episode_by_id = {
        str(ep.get("episode_id") or ep.get("id") or ""): ep for ep in episodes
    }
    episode_by_id = {k: v for k, v in episode_by_id.items() if k}
    if not episode_by_id:
        return []

    # Per-user counters
    starts = defaultdict(int)
    completes = defaultdict(int)
    plays30 = defaultdict(int)
    skips = defaultdict(int)
    likes = defaultdict(int)
    saves = defaultdict(int)
    shares = defaultdict(int)

    for event in user_events:
        eid = str(event.get("episode_id") or "")
        if eid not in episode_by_id:
            continue
        et = event.get("event_type")
        if et == "play_start":
            starts[eid] += 1
        elif et == "play_complete":
            completes[eid] += 1
        elif et == "play_30s":
            plays30[eid] += 1
        elif et == "skip_early":
            skips[eid] += 1
        elif et == "like":
            likes[eid] += 1
        elif et == "save":
            saves[eid] += 1
        elif et == "share":
            shares[eid] += 1

    p_rate_raw: dict[str, float] = {}
    save_raw: dict[str, float] = {}
    like_raw: dict[str, float] = {}
    share_raw: dict[str, float] = {}
    skip_raw: dict[str, float] = {}
    for eid in episode_by_id:
        start = starts[eid]
        # If no completion but played 30s exists, treat as weak completion proxy.
        completion = completes[eid] + (0.3 * plays30[eid])
        p_rate_raw[eid] = (completion / start) if start > 0 else 0.0
        save_raw[eid] = 1.0 if saves[eid] > 0 else 0.0
        like_raw[eid] = 1.0 if likes[eid] > 0 else 0.0
        share_raw[eid] = 1.0 if shares[eid] > 0 else 0.0
        skip_raw[eid] = 1.0 if skips[eid] > 0 else 0.0

    p_rate = _normalize(p_rate_raw)
    save = _normalize(save_raw)
    like = _normalize(like_raw)
    share = _normalize(share_raw)
    skip = _normalize(skip_raw)

    scored: list[dict[str, Any]] = []
    for eid, episode in episode_by_id.items():
        score = (
            5.0 * p_rate.get(eid, 0.0)
            + 3.0 * save.get(eid, 0.0)
            + 1.0 * like.get(eid, 0.0)
            + 0.5 * share.get(eid, 0.0)
            - 5.0 * skip.get(eid, 0.0)
        )
        scored.append(
            {
                "episode_id": eid,
                "job_id": episode.get("job_id"),
                "topic": episode.get("topic", ""),
                "audio_url": episode.get("audio_url", ""),
                "score": round(float(score), 4),
                "created_at": _to_dt(episode.get("created_at")),
            }
        )
    scored.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)

    # Exploration candidates based on global popularity and recency.
    popularity = defaultdict(float)
    for event in all_events:
        eid = str(event.get("episode_id") or "")
        if eid not in episode_by_id:
            continue
        et = event.get("event_type")
        if et == "play_start":
            popularity[eid] += 1.0
        elif et == "play_complete":
            popularity[eid] += 3.0
        elif et == "like":
            popularity[eid] += 1.0
        elif et == "save":
            popularity[eid] += 2.0
        elif et == "share":
            popularity[eid] += 1.0
    popular_sorted = sorted(
        episode_by_id.keys(),
        key=lambda eid: (
            popularity[eid],
            _to_dt(episode_by_id[eid].get("created_at")),
        ),
        reverse=True,
    )

    exploration_count = max(0, int(limit * max(0.0, min(1.0, exploration_ratio))))
    exploitation_count = max(0, limit - exploration_count)

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for item in scored:
        if len(selected) >= exploitation_count:
            break
        selected.append(
            {
                "episode_id": item["episode_id"],
                "job_id": item.get("job_id"),
                "topic": item["topic"],
                "audio_url": item["audio_url"],
                "score": item["score"],
                "reason": "exploitation",
            }
        )
        selected_ids.add(item["episode_id"])

    if exploration_count > 0:
        for eid in popular_sorted:
            if len(selected) >= limit:
                break
            if eid in selected_ids:
                continue
            ep = episode_by_id[eid]
            selected.append(
                {
                    "episode_id": eid,
                    "job_id": ep.get("job_id"),
                    "topic": ep.get("topic", ""),
                    "audio_url": ep.get("audio_url", ""),
                    "score": 0.0,
                    "reason": "exploration",
                }
            )
            selected_ids.add(eid)

    # Cold-start guard: if user has no events, prefer recency.
    if not user_events:
        recent = sorted(
            episode_by_id.values(),
            key=lambda ep: _to_dt(ep.get("created_at")),
            reverse=True,
        )
        selected = []
        for ep in recent[:limit]:
            eid = str(ep.get("episode_id") or "")
            if not eid:
                continue
            selected.append(
                {
                    "episode_id": eid,
                    "job_id": ep.get("job_id"),
                    "topic": ep.get("topic", ""),
                    "audio_url": ep.get("audio_url", ""),
                    "score": 0.0,
                    "reason": "cold_start_recent",
                }
            )

    return selected[:limit]
