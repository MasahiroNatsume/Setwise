# API Smoke Test Guide

## Purpose
Quickly validate core backend endpoints while Flutter setup is still in progress.

## Prerequisites
1. Backend dependencies installed:
   - `backend\\venv\\Scripts\\pip install -r backend\\requirements.txt`
2. API server running:
   - `cd backend`
   - `..\\backend\\venv\\Scripts\\uvicorn main:app --reload`

## Run smoke test (fast mode, no generation job)
```powershell
backend\venv\Scripts\python backend\scripts\api_smoke_test.py --base-url http://127.0.0.1:8000
```

This checks:
- `/health`
- `/users/{id}/profile` (PUT/GET)
- `/events/track`
- `/feed/{id}`
- `/recommendations/{id}`

## Run smoke test including job pipeline
```powershell
backend\venv\Scripts\python backend\scripts\api_smoke_test.py --base-url http://127.0.0.1:8000 --with-job --topic AI --poll-max 120 --poll-interval 2
```

Notes:
- This can take time because search/filter/extract/generate/tts are executed.
- Final job status may be `completed` or `failed` depending on external dependencies and keys.
- If jobs are still `running` in final output, increase `--poll-max` (e.g. `180`).

## TTS provider switching (manual API call)
`/jobs/create` supports:
- `tts_provider`: `kokoro` or `voicevox`
- `tts_voice`: optional voice id/name (VOICEVOX expects speaker id like `"3"`)
- `tts_speed`: optional speed (0.5 - 2.0)

Example:
```powershell
backend\venv\Scripts\python -c "import requests, json;print(requests.post('http://127.0.0.1:8000/jobs/create',json={'topic':'AI','tts_provider':'voicevox','tts_voice':'3','tts_speed':1.0}).json())"
```

## Exit code
- `0`: all required endpoint checks succeeded.
- `1`: at least one required check failed.
