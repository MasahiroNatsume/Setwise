# StepWise Demo Deploy (ngrok + VOICEVOX Co-located)

## 1. Preconditions
- VOICEVOX Engine runs on `127.0.0.1:50021`.
- Backend `.env` is configured (do not commit it).
- Required ports are reachable from your test clients.

## 2. Recommended backend env
Set these in `backend/.env`:

```env
VOICEVOX_BASE_URL=http://127.0.0.1:50021
VOICEVOX_CONNECT_TIMEOUT_SECONDS=10
VOICEVOX_REQUEST_TIMEOUT_SECONDS=60
TTS_FALLBACK_TO_KOKORO=false
TTS_SERIAL_SECTION_MODE=true
TTS_MAX_WORKERS=1
VOICEVOX_TIMINGS_SECOND_PASS=false
CORS_ALLOW_ORIGINS=*
```

## 3. Start order
1. Start VOICEVOX Engine.
2. Start backend:

```powershell
cd backend
..\backend\venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

3. Health check:

```powershell
backend\venv\Scripts\python -c "import requests; print(requests.get('http://127.0.0.1:8000/health', timeout=5).json())"
```

4. Start ngrok:

```powershell
ngrok http 8000
```

5. Use ngrok URL in Flutter:

```bash
flutter run --dart-define=API_BASE_URL=https://<your-ngrok-subdomain>.ngrok-free.app
```

## 4. Verify TTS provider behavior
Create a VOICEVOX job:

```powershell
backend\venv\Scripts\python -c "import requests, json; body={'topic':'AI','top_k':2,'max_articles':8,'tts_provider':'voicevox','tts_voice':'3','tts_speed':1.0}; print(requests.post('http://127.0.0.1:8000/jobs/create', json=body, timeout=20).json())"
```

Then check result:

```powershell
backend\venv\Scripts\python -c "import requests, json; j='JOB_ID'; d=requests.get(f'http://127.0.0.1:8000/jobs/{j}', timeout=20).json(); print(json.dumps({'status':d.get('status'),'stage':d.get('stage'),'tts_provider_requested':(d.get('result') or {}).get('tts_provider_requested'),'tts_provider_used':(d.get('result') or {}).get('tts_provider_used'),'tts_fallback_used':(d.get('result') or {}).get('tts_fallback_used'),'tts_fallback_reason':(d.get('metrics') or {}).get('tts_fallback_reason')}, ensure_ascii=False, indent=2))"
```

Expected for success:
- `tts_provider_requested = voicevox`
- `tts_provider_used = voicevox`

## 5. GitHub private push checklist
Before pushing:
- Confirm `.gitignore` excludes secrets/build/cache/audio.
- Confirm `backend/.env` is **not tracked**.
- Rotate API keys that may have been exposed.
- Ensure only `.env.example` is committed.

Useful check:

```powershell
git status
git check-ignore -v backend/.env backend/venv backend/audio_output backend/audio_cache
```

## 6. Common issues
- `Read timed out (50021)`: VOICEVOX overloaded or not healthy; keep serial mode and increase timeout.
- Mobile cannot connect: use LAN IP or ngrok URL, not `127.0.0.1`.
- Web CORS issue: set `CORS_ALLOW_ORIGINS` appropriately.
