from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "completed", "failed"]


class JobCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    top_k: int = Field(default=3, ge=1, le=10)
    max_articles: int = Field(default=15, ge=1, le=30)
    region: str = Field(default="jp-jp", min_length=2, max_length=10)
    timelimit: str = Field(default="d", min_length=1, max_length=2)
    tts_provider: Literal["kokoro", "voicevox"] = "kokoro"
    tts_voice: str | None = None
    tts_speed: float | None = Field(default=None, ge=0.5, le=2.0)


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime


class JobResult(BaseModel):
    episode_id: str | None = None
    topic: str
    selected_titles: list[str]
    audio_url: str
    preview_audio_url: str | None = None
    script_lines: int
    agenda_nodes: list[dict[str, Any]] = Field(default_factory=list)
    agenda_edges: list[dict[str, Any]] = Field(default_factory=list)
    agenda_chapters: list[dict[str, Any]] = Field(default_factory=list)
    transcript_sections: list[dict[str, Any]] = Field(default_factory=list)
    tts_provider_requested: str = "kokoro"
    tts_provider_used: str = "kokoro"
    tts_fallback_used: bool = False
    tts_voice_requested: str | None = None
    tts_voice_used: str | None = None
    playable_from_chunks: bool = False
    final_audio_ready: bool = True
    final_audio_filename: str | None = None
    timings_ready: bool = True


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    stage: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    result: JobResult | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class EventTrackRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    episode_id: str = Field(min_length=1, max_length=128)
    event_type: Literal[
        "play_start",
        "play_30s",
        "play_complete",
        "skip_early",
        "like",
        "save",
        "share",
    ]
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventTrackResponse(BaseModel):
    status: Literal["ok"]
    event_id: str


class RecommendationItem(BaseModel):
    episode_id: str
    job_id: str | None = None
    topic: str
    audio_url: str
    score: float
    reason: str


class RecommendationResponse(BaseModel):
    user_id: str
    items: list[RecommendationItem]
    total_candidates: int


class UserProfileUpsertRequest(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list)


class UserProfileResponse(BaseModel):
    user_id: str
    category: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class FeedResponse(BaseModel):
    user_id: str
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    items: list[RecommendationItem]
    total_candidates: int
