from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from job_store import Storage
from modules.tts_router import get_default_provider, warmup_on_startup
from modules.tts_types import TtsConfig
from pipeline import run_pipeline
from recommend import build_recommendations
from schemas import (
    EventTrackRequest,
    EventTrackResponse,
    FeedResponse,
    JobCreateRequest,
    JobCreateResponse,
    RecommendationResponse,
    JobStatusResponse,
    UserProfileResponse,
    UserProfileUpsertRequest,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio_output")
os.makedirs(AUDIO_DIR, exist_ok=True)

app = FastAPI(
    title="StepWise API",
    description="Backend for StepWise: Converting Web Content to Podcasts",
    version="0.3.0",
)

cors_origins_raw = os.environ.get("CORS_ALLOW_ORIGINS", "*").strip()
if cors_origins_raw == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = Storage()

app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
async def _warmup_tts_engine() -> None:
    async def _warmup() -> None:
        try:
            await asyncio.to_thread(warmup_on_startup)
            print(f"[{_utc_now_iso()}] startup tts=warmup_done")
        except Exception as exc:
            print(f"[{_utc_now_iso()}] startup tts=warmup_failed error={exc}")

    # Do not block API readiness on model warmup.
    asyncio.create_task(_warmup())


async def _execute_job(job_id: str, req: JobCreateRequest) -> None:
    storage.update_job(job_id, status="running", stage="running")
    print(f"[{_utc_now_iso()}] job={job_id} stage=running topic={req.topic}")
    try:
        timeout_seconds = int(os.environ.get("JOB_TIMEOUT_SECONDS", "900"))

        def on_stage(stage: str, metrics_update: dict | None = None) -> None:
            payload = metrics_update or {}
            if stage == "final_audio_completed":
                current = storage.get_job(job_id)
                if current is not None and isinstance(current.result, dict):
                    updated_result = dict(current.result)
                    if "final_audio_ready" in payload:
                        updated_result["final_audio_ready"] = bool(payload.get("final_audio_ready"))
                    if "audio_filename" in payload:
                        updated_result["final_audio_filename"] = payload.get("audio_filename")
                    storage.update_job(
                        job_id,
                        stage=stage,
                        metrics=payload,
                        result=updated_result,
                    )
                    print(f"[{_utc_now_iso()}] job={job_id} stage={stage}")
                    return
            storage.update_job(job_id, stage=stage, metrics=payload or None)
            print(f"[{_utc_now_iso()}] job={job_id} stage={stage}")

        result = await asyncio.wait_for(
            asyncio.to_thread(
                run_pipeline,
                topic=req.topic,
                top_k=req.top_k,
                max_articles=req.max_articles,
                region=req.region,
                timelimit=req.timelimit,
                output_dir=AUDIO_DIR,
                tts_config=TtsConfig(
                    provider=req.tts_provider or get_default_provider(),  # type: ignore[arg-type]
                    voice=req.tts_voice,
                    speed=req.tts_speed,
                    lang="ja",
                ),
                on_stage=on_stage,
            ),
            timeout=timeout_seconds,
        )
        api_result = {
            "topic": result["topic"],
            "selected_titles": result["selected_titles"],
            "audio_url": f"/audio/{result['audio_filename']}",
            "preview_audio_url": (
                f"/audio/{result['preview_audio_filename']}"
                if result.get("preview_audio_filename")
                else None
            ),
            "script_lines": result["script_lines"],
            "agenda_nodes": result.get("agenda_nodes", []),
            "agenda_edges": result.get("agenda_edges", []),
            "agenda_chapters": result.get("agenda_chapters", []),
            "transcript_sections": result.get("transcript_sections", []),
            "tts_provider_requested": result.get("tts_provider_requested", req.tts_provider),
            "tts_provider_used": result.get("tts_provider_used", req.tts_provider),
            "tts_fallback_used": bool(result.get("tts_fallback_used", False)),
            "tts_voice_requested": result.get("tts_voice_requested", req.tts_voice),
            "tts_voice_used": result.get("tts_voice_used", req.tts_voice),
            "playable_from_chunks": bool(result.get("playable_from_chunks", False)),
            "final_audio_ready": bool(result.get("final_audio_ready", True)),
            "final_audio_filename": result.get("final_audio_filename"),
            "timings_ready": bool(result.get("timings_ready", True)),
            "episode_id": result["episode_id"],
        }
        storage.update_job(
            job_id,
            status="completed",
            stage="completed",
            result=api_result,
            metrics=result["metrics"],
        )
        storage.upsert_episode(
            result["episode_id"],
            {
                "episode_id": result["episode_id"],
                "job_id": job_id,
                "topic": result["topic"],
                "selected_titles": result["selected_titles"],
                "audio_url": api_result["audio_url"],
                "preview_audio_url": api_result["preview_audio_url"],
                "script_lines": result["script_lines"],
                "agenda_nodes": api_result["agenda_nodes"],
                "agenda_edges": api_result["agenda_edges"],
                "agenda_chapters": api_result["agenda_chapters"],
                "transcript_sections": api_result["transcript_sections"],
                "tts_provider_requested": api_result["tts_provider_requested"],
                "tts_provider_used": api_result["tts_provider_used"],
                "tts_fallback_used": api_result["tts_fallback_used"],
                "tts_voice_requested": api_result["tts_voice_requested"],
                "tts_voice_used": api_result["tts_voice_used"],
                "playable_from_chunks": api_result["playable_from_chunks"],
                "final_audio_ready": api_result["final_audio_ready"],
                "final_audio_filename": api_result["final_audio_filename"],
                "timings_ready": api_result["timings_ready"],
                "metrics": result["metrics"],
                "created_at": datetime.now(timezone.utc),
            },
        )
        print(f"[{_utc_now_iso()}] job={job_id} stage=completed")
    except asyncio.TimeoutError:
        msg = f"Job timed out after {timeout_seconds}s"
        storage.update_job(
            job_id,
            status="failed",
            stage="failed",
            error=msg,
        )
        print(f"[{_utc_now_iso()}] job={job_id} stage=failed error={msg}")
    except Exception as exc:
        storage.update_job(
            job_id,
            status="failed",
            stage="failed",
            error=str(exc),
        )
        print(f"[{_utc_now_iso()}] job={job_id} stage=failed error={exc}")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "storage": storage.backend}


@app.post("/jobs/create", response_model=JobCreateResponse)
async def create_job(req: JobCreateRequest) -> JobCreateResponse:
    job_id = str(uuid4())
    record = storage.create_job(job_id, req.topic)
    asyncio.create_task(_execute_job(job_id, req))
    return JobCreateResponse(
        job_id=record.job_id,
        status=record.status,  # type: ignore[arg-type]
        created_at=record.created_at,
    )


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    record = storage.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,  # type: ignore[arg-type]
        stage=record.stage,
        created_at=record.created_at,
        updated_at=record.updated_at,
        error=record.error,
        result=record.result,  # type: ignore[arg-type]
        metrics=record.metrics,
    )


@app.post("/events/track", response_model=EventTrackResponse)
async def track_event(req: EventTrackRequest) -> EventTrackResponse:
    event_id = str(uuid4())
    storage.add_event(
        {
            "event_id": event_id,
            "user_id": req.user_id,
            "episode_id": req.episode_id,
            "event_type": req.event_type,
            "timestamp": req.timestamp.isoformat(),
            "metadata": req.metadata,
        }
    )
    return EventTrackResponse(status="ok", event_id=event_id)


@app.get("/recommendations/{user_id}", response_model=RecommendationResponse)
async def get_recommendations(
    user_id: str, limit: int = 20, exploration_ratio: float = 0.2
) -> RecommendationResponse:
    limit = max(1, min(limit, 50))
    exploration_ratio = max(0.0, min(exploration_ratio, 0.5))
    episodes = storage.list_recent_episodes(limit=200)
    user_events = storage.list_user_events(user_id=user_id, limit=2000)
    all_events = storage.list_events(limit=5000)
    items = build_recommendations(
        user_id=user_id,
        episodes=episodes,
        user_events=user_events,
        all_events=all_events,
        limit=limit,
        exploration_ratio=exploration_ratio,
    )
    return RecommendationResponse(
        user_id=user_id,
        items=items,
        total_candidates=len(episodes),
    )


@app.put("/users/{user_id}/profile", response_model=UserProfileResponse)
async def upsert_user_profile(
    user_id: str, req: UserProfileUpsertRequest
) -> UserProfileResponse:
    now = datetime.now(timezone.utc)
    old = storage.get_user_profile(user_id)
    created_at = old.get("created_at", now) if old else now
    profile = storage.upsert_user_profile(
        user_id,
        {
            "user_id": user_id,
            "category": req.category,
            "tags": req.tags,
            "created_at": created_at,
            "updated_at": now,
        },
    )
    return UserProfileResponse(
        user_id=profile["user_id"],
        category=profile.get("category", ""),
        tags=profile.get("tags", []),
        created_at=profile.get("created_at", now),
        updated_at=profile.get("updated_at", now),
    )


@app.get("/users/{user_id}/profile", response_model=UserProfileResponse)
async def get_user_profile(user_id: str) -> UserProfileResponse:
    profile = storage.get_user_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User profile not found")
    return UserProfileResponse(
        user_id=profile["user_id"],
        category=profile.get("category", ""),
        tags=profile.get("tags", []),
        created_at=profile.get("created_at", datetime.now(timezone.utc)),
        updated_at=profile.get("updated_at", datetime.now(timezone.utc)),
    )


@app.get("/feed/{user_id}", response_model=FeedResponse)
async def get_feed(
    user_id: str, limit: int = 20, exploration_ratio: float = 0.2
) -> FeedResponse:
    recommendation = await get_recommendations(
        user_id=user_id, limit=limit, exploration_ratio=exploration_ratio
    )
    profile = storage.get_user_profile(user_id) or {}
    return FeedResponse(
        user_id=user_id,
        category=profile.get("category"),
        tags=profile.get("tags", []),
        items=recommendation.items,
        total_candidates=recommendation.total_candidates,
    )
