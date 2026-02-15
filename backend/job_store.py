from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobRecord:
    job_id: str
    status: str
    stage: str
    created_at: datetime
    updated_at: datetime
    topic: str
    error: str | None = None
    result: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


class InMemoryJobStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, JobRecord] = {}

    def create(self, job_id: str, topic: str) -> JobRecord:
        now = utc_now()
        record = JobRecord(
            job_id=job_id,
            status="queued",
            stage="queued",
            created_at=now,
            updated_at=now,
            topic=topic,
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> JobRecord:
        with self._lock:
            record = self._jobs[job_id]
            if status is not None:
                record.status = status
            if stage is not None:
                record.stage = stage
            if error is not None:
                record.error = error
            if result is not None:
                record.result = result
            if metrics is not None:
                record.metrics.update(metrics)
            record.updated_at = utc_now()
            return record

    def asdict(self, job_id: str) -> dict[str, Any]:
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        return asdict(record)

    def set(self, record: JobRecord) -> None:
        with self._lock:
            self._jobs[record.job_id] = record


class InMemoryEventStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._events: list[dict[str, Any]] = []

    def add(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e.get("user_id") == user_id]

    def list_all(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events[-limit:])


class InMemoryEpisodeStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._episodes: dict[str, dict[str, Any]] = {}

    def upsert(self, episode_id: str, episode: dict[str, Any]) -> None:
        with self._lock:
            self._episodes[episode_id] = dict(episode)

    def get(self, episode_id: str) -> dict[str, Any] | None:
        with self._lock:
            episode = self._episodes.get(episode_id)
            return dict(episode) if episode else None

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            episodes = list(self._episodes.values())
        episodes.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return episodes[:limit]


class InMemoryUserStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._users: dict[str, dict[str, Any]] = {}

    def upsert(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            old = self._users.get(user_id) or {}
            merged = {**old, **profile}
            self._users[user_id] = merged
            return dict(merged)

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            profile = self._users.get(user_id)
            return dict(profile) if profile else None


def _env_true(name: str, default: bool = False) -> bool:
    raw = str(__import__("os").environ.get(name, str(default))).strip().lower()
    return raw in {"1", "true", "yes", "on"}


class Storage:
    """
    Primary data access layer.
    - Always writes in-memory for local runtime reads.
    - Optionally mirrors to Firestore when configured.
    """

    def __init__(self) -> None:
        self.jobs = InMemoryJobStore()
        self.events = InMemoryEventStore()
        self.episodes = InMemoryEpisodeStore()
        self.users = InMemoryUserStore()
        self._firestore_client: Any | None = None
        self._firestore_enabled = False
        self._init_firestore()

    def _init_firestore(self) -> None:
        use_firestore = _env_true("USE_FIRESTORE", default=False)
        if not use_firestore:
            return
        try:
            from google.cloud import firestore  # type: ignore

            project_id = __import__("os").environ.get("FIRESTORE_PROJECT_ID")
            self._firestore_client = firestore.Client(project=project_id or None)
            self._firestore_enabled = True
            print("[storage] Firestore enabled.")
        except Exception as exc:
            self._firestore_enabled = False
            self._firestore_client = None
            print(f"[storage] Firestore disabled, fallback to in-memory: {exc}")

    @property
    def backend(self) -> str:
        return "firestore" if self._firestore_enabled else "in-memory"

    def create_job(self, job_id: str, topic: str) -> JobRecord:
        record = self.jobs.create(job_id, topic)
        if self._firestore_enabled:
            assert self._firestore_client is not None
            self._firestore_client.collection("jobs").document(job_id).set(
                {
                    "job_id": record.job_id,
                    "topic": record.topic,
                    "status": record.status,
                    "stage": record.stage,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "error": record.error,
                    "result": record.result,
                    "metrics": record.metrics,
                }
            )
        return record

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> JobRecord:
        record = self.jobs.update(
            job_id,
            status=status,
            stage=stage,
            error=error,
            result=result,
            metrics=metrics,
        )
        if self._firestore_enabled:
            assert self._firestore_client is not None
            payload: dict[str, Any] = {"updated_at": record.updated_at}
            if status is not None:
                payload["status"] = status
            if stage is not None:
                payload["stage"] = stage
            if error is not None:
                payload["error"] = error
            if result is not None:
                payload["result"] = result
            if metrics is not None:
                payload["metrics"] = record.metrics
            self._firestore_client.collection("jobs").document(job_id).set(
                payload, merge=True
            )
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        record = self.jobs.get(job_id)
        if record is not None:
            return record
        if not self._firestore_enabled:
            return None
        assert self._firestore_client is not None
        snap = self._firestore_client.collection("jobs").document(job_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        created_at = data.get("created_at") or utc_now()
        updated_at = data.get("updated_at") or created_at
        record = JobRecord(
            job_id=job_id,
            status=data.get("status", "queued"),
            stage=data.get("stage", "queued"),
            created_at=created_at,
            updated_at=updated_at,
            topic=data.get("topic", ""),
            error=data.get("error"),
            result=data.get("result"),
            metrics=data.get("metrics") or {},
        )
        self.jobs.set(record)
        return record

    def upsert_episode(self, episode_id: str, episode: dict[str, Any]) -> None:
        self.episodes.upsert(episode_id, episode)
        if self._firestore_enabled:
            assert self._firestore_client is not None
            self._firestore_client.collection("episodes").document(episode_id).set(
                episode, merge=True
            )

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        episode = self.episodes.get(episode_id)
        if episode is not None:
            return episode
        if not self._firestore_enabled:
            return None
        assert self._firestore_client is not None
        snap = self._firestore_client.collection("episodes").document(episode_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        self.episodes.upsert(episode_id, data)
        return data

    def list_recent_episodes(self, limit: int = 100) -> list[dict[str, Any]]:
        if self._firestore_enabled:
            assert self._firestore_client is not None
            docs = (
                self._firestore_client.collection("episodes")
                .order_by("created_at", direction="DESCENDING")
                .limit(limit)
                .stream()
            )
            episodes: list[dict[str, Any]] = []
            for doc in docs:
                data = doc.to_dict() or {}
                episodes.append(data)
                episode_id = data.get("episode_id") or doc.id
                self.episodes.upsert(episode_id, data)
            if episodes:
                return episodes
        return self.episodes.list_recent(limit)

    def add_event(self, event: dict[str, Any]) -> None:
        self.events.add(event)
        if self._firestore_enabled:
            assert self._firestore_client is not None
            self._firestore_client.collection("interactions").document(
                event["event_id"]
            ).set(event)

    def list_user_events(self, user_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        if self._firestore_enabled:
            assert self._firestore_client is not None
            docs = (
                self._firestore_client.collection("interactions")
                .where("user_id", "==", user_id)
                .order_by("timestamp", direction="DESCENDING")
                .limit(limit)
                .stream()
            )
            events = [doc.to_dict() or {} for doc in docs]
            if events:
                return events
        return self.events.list_by_user(user_id)[-limit:]

    def list_events(self, limit: int = 2000) -> list[dict[str, Any]]:
        if self._firestore_enabled:
            assert self._firestore_client is not None
            docs = (
                self._firestore_client.collection("interactions")
                .order_by("timestamp", direction="DESCENDING")
                .limit(limit)
                .stream()
            )
            events = [doc.to_dict() or {} for doc in docs]
            if events:
                return events
        return self.events.list_all(limit)

    def upsert_user_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        merged = self.users.upsert(user_id, profile)
        if self._firestore_enabled:
            assert self._firestore_client is not None
            self._firestore_client.collection("users").document(user_id).set(
                merged, merge=True
            )
        return merged

    def get_user_profile(self, user_id: str) -> dict[str, Any] | None:
        cached = self.users.get(user_id)
        if cached is not None:
            return cached
        if not self._firestore_enabled:
            return None
        assert self._firestore_client is not None
        snap = self._firestore_client.collection("users").document(user_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        self.users.upsert(user_id, data)
        return data
