from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any

import requests


def _log(title: str, payload: Any) -> None:
    print(f"\n=== {title} ===")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(payload)


def run(
    base_url: str,
    user_id: str,
    topic: str,
    with_job: bool,
    poll_max: int,
    poll_interval: float,
    tts_provider: str | None,
    tts_voice: str | None,
    tts_speed: float | None,
) -> int:
    base = base_url.rstrip("/")
    session = requests.Session()
    ok = True

    # 1) health
    r = session.get(f"{base}/health", timeout=15)
    _log("GET /health", {"status_code": r.status_code, "body": r.json()})
    ok = ok and r.status_code == 200

    # 2) upsert user profile
    profile_payload = {
        "category": "Technology",
        "tags": ["AI & Ethics", "Startups"],
    }
    r = session.put(
        f"{base}/users/{user_id}/profile", json=profile_payload, timeout=20
    )
    _log(
        "PUT /users/{user_id}/profile",
        {"status_code": r.status_code, "body": r.json()},
    )
    ok = ok and r.status_code == 200

    # 3) read profile
    r = session.get(f"{base}/users/{user_id}/profile", timeout=20)
    _log(
        "GET /users/{user_id}/profile",
        {"status_code": r.status_code, "body": r.json()},
    )
    ok = ok and r.status_code == 200

    # 4) track event
    event_payload = {
        "user_id": user_id,
        "episode_id": "smoke-episode",
        "event_type": "play_start",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"source": "smoke_test"},
    }
    r = session.post(f"{base}/events/track", json=event_payload, timeout=20)
    _log("POST /events/track", {"status_code": r.status_code, "body": r.json()})
    ok = ok and r.status_code == 200

    # 5) feed and recommendations (may be empty, but endpoint should succeed)
    r = session.get(f"{base}/feed/{user_id}", timeout=20)
    _log("GET /feed/{user_id}", {"status_code": r.status_code, "body": r.json()})
    ok = ok and r.status_code == 200

    r = session.get(f"{base}/recommendations/{user_id}", timeout=20)
    _log(
        "GET /recommendations/{user_id}",
        {"status_code": r.status_code, "body": r.json()},
    )
    ok = ok and r.status_code == 200

    # 6) optional job flow
    if with_job:
        job_payload = {"topic": topic, "top_k": 2, "max_articles": 8}
        if tts_provider:
            job_payload["tts_provider"] = tts_provider
        if tts_voice:
            job_payload["tts_voice"] = tts_voice
        if tts_speed is not None:
            job_payload["tts_speed"] = tts_speed
        r = session.post(f"{base}/jobs/create", json=job_payload, timeout=20)
        body = r.json()
        _log("POST /jobs/create", {"status_code": r.status_code, "body": body})
        ok = ok and r.status_code == 200

        if r.status_code == 200 and body.get("job_id"):
            job_id = body["job_id"]
            max_poll = poll_max
            final = None
            for _ in range(max_poll):
                rr = session.get(f"{base}/jobs/{job_id}", timeout=20)
                final = rr.json()
                state = final.get("status")
                if state in ("completed", "failed"):
                    break
                time.sleep(poll_interval)
            _log("GET /jobs/{job_id} (final)", final)
            ok = ok and bool(final) and final.get("status") in ("completed", "failed")

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="StepWise API smoke test")
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8000", help="API base URL"
    )
    parser.add_argument("--user-id", default="smoke-user", help="User id for test")
    parser.add_argument("--topic", default="AI", help="Topic used for job test")
    parser.add_argument(
        "--with-job",
        action="store_true",
        help="Run /jobs/create and polling (can take long).",
    )
    parser.add_argument(
        "--poll-max",
        type=int,
        default=120,
        help="Max number of polling attempts for /jobs/{job_id}.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval seconds for /jobs/{job_id}.",
    )
    parser.add_argument(
        "--tts-provider",
        default=None,
        choices=["kokoro", "voicevox"],
        help="Optional TTS provider for /jobs/create.",
    )
    parser.add_argument(
        "--tts-voice",
        default=None,
        help="Optional TTS voice override for /jobs/create.",
    )
    parser.add_argument(
        "--tts-speed",
        type=float,
        default=None,
        help="Optional TTS speed override for /jobs/create (0.5-2.0).",
    )
    args = parser.parse_args()
    return run(
        base_url=args.base_url,
        user_id=args.user_id,
        topic=args.topic,
        with_job=args.with_job,
        poll_max=args.poll_max,
        poll_interval=args.poll_interval,
        tts_provider=args.tts_provider,
        tts_voice=args.tts_voice,
        tts_speed=args.tts_speed,
    )


if __name__ == "__main__":
    raise SystemExit(main())
