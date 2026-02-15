# StepWise API Contract (v0.3)

Base URL (local):
- `http://127.0.0.1:8000`
- Android emulator: `http://10.0.2.2:8000`

LLM runtime requirements:
- `OPENROUTER_API_KEY` must be set.
- Default model: `google/gemini-2.5-flash-lite` (`OPENROUTER_MODEL` to override).
- Default endpoint: `https://openrouter.ai/api/v1` (`OPENROUTER_BASE_URL` to override).

## 1. Health
### `GET /health`
Response `200`
```json
{
  "status": "ok",
  "storage": "in-memory"
}
```

## 2. User Profile
### `PUT /users/{user_id}/profile`
Request:
```json
{
  "category": "Technology",
  "tags": ["AI & Ethics", "Startups"]
}
```
Response `200`:
```json
{
  "user_id": "demo-user",
  "category": "Technology",
  "tags": ["AI & Ethics", "Startups"],
  "created_at": "2026-02-13T17:03:46.880218Z",
  "updated_at": "2026-02-13T17:03:46.880218Z"
}
```

### `GET /users/{user_id}/profile`
Response `200`: same as upsert response.
Response `404`:
```json
{
  "detail": "User profile not found"
}
```

## 3. Jobs
### `POST /jobs/create`
Request:
```json
{
  "topic": "AI",
  "top_k": 3,
  "max_articles": 15,
  "region": "jp-jp",
  "timelimit": "d"
}
```
Response `200`:
```json
{
  "job_id": "uuid",
  "status": "queued",
  "created_at": "2026-02-13T16:33:25.946735Z"
}
```

### `GET /jobs/{job_id}`
Response `200`:
```json
{
  "job_id": "uuid",
  "status": "completed",
  "stage": "completed",
  "created_at": "2026-02-13T16:33:25.946735Z",
  "updated_at": "2026-02-13T16:34:09.102515Z",
  "error": null,
  "result": {
    "episode_id": "uuid",
    "topic": "AI",
    "selected_titles": ["..."],
    "preview_audio_url": "/audio/podcast_xxx_intro.wav",
    "audio_url": "/audio/podcast_xxx.wav",
    "script_lines": 12,
    "agenda_nodes": [
      {"id": "n1", "title": "背景", "role": "premise", "note": ""}
    ],
    "agenda_edges": [
      {"from": "n1", "to": "n2"}
    ],
    "transcript_sections": [
      {
        "section_index": 1,
        "section_title": "背景",
        "status": "ready",
        "lines": [{"speaker": "A", "text": "..."}]
      }
    ]
  },
  "metrics": {
    "search_seconds": 0.5,
    "tts_seconds": 7.2,
    "total_seconds": 13.8,
    "agenda_nodes": [{"id": "n1", "title": "背景", "role": "premise", "note": ""}],
    "agenda_edges": [{"from": "n1", "to": "n2"}],
    "transcript_sections": [],
    "progress": {
      "total_sections": 4,
      "generated_sections": 2,
      "synthesized_sections": 2,
      "progress_ratio": 0.5
    },
    "ready_audio_chunks": ["podcast_xxx_intro.wav", "podcast_xxx_sec01.wav"]
  }
}
```

## 4. Events
### `POST /events/track`
Request:
```json
{
  "user_id": "demo-user",
  "episode_id": "episode-1",
  "event_type": "play_start",
  "timestamp": "2026-02-13T17:10:00.000000+00:00",
  "metadata": {
    "source": "home_screen"
  }
}
```
Allowed `event_type`:
- `play_start`
- `play_30s`
- `play_complete`
- `skip_early`
- `like`
- `save`
- `share`

Response `200`:
```json
{
  "status": "ok",
  "event_id": "uuid"
}
```

## 5. Recommendations
### `GET /recommendations/{user_id}?limit=20&exploration_ratio=0.2`
Response `200`:
```json
{
  "user_id": "demo-user",
  "items": [
    {
      "episode_id": "ep2",
      "topic": "AI policy",
      "audio_url": "/audio/ep2.wav",
      "score": 5.0,
      "reason": "exploitation"
    }
  ],
  "total_candidates": 1
}
```

## 6. Feed
### `GET /feed/{user_id}?limit=20&exploration_ratio=0.2`
Response `200`:
```json
{
  "user_id": "demo-user",
  "category": "Technology",
  "tags": ["AI & Ethics", "Startups"],
  "items": [
    {
      "episode_id": "ep2",
      "topic": "AI policy",
      "audio_url": "/audio/ep2.wav",
      "score": 5.0,
      "reason": "exploitation"
    }
  ],
  "total_candidates": 1
}
```

## 7. Audio Static
### `GET /audio/{filename}`
Returns generated WAV file via FastAPI StaticFiles.

---

## Error Format
FastAPI default error format:
```json
{
  "detail": "error message"
}
```
