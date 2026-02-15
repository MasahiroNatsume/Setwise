# StepWise MVP Checklist

## 0. Definition of MVP
- [ ] A user can complete onboarding, receive generated audio episodes, play them in-app, and interaction events are stored for recommendation scoring.

## 1. Backend Foundation (Priority: P0)
- [ ] Create FastAPI route skeleton (`/health`, `/jobs/create`, `/jobs/{id}`)
- [ ] Define job payload schema (topic, tags, language, max_items)
- [ ] Add basic request validation and error responses
- [ ] Add environment config loader (`.env` + required keys check)
- [ ] Add structured logging (job_id, stage, duration, status)

Done criteria:
- [ ] `/health` returns 200
- [ ] `/jobs/create` returns job_id and queued status

## 2. Async Job Execution (Priority: P0)
- [ ] Introduce queue-backed execution model (Cloud Tasks or Cloud Run Job trigger)
- [ ] Implement job state transitions: `queued -> running -> completed/failed`
- [ ] Persist job metadata in Firestore (`jobs` collection)
- [ ] Add retry policy and max retry count

Done criteria:
- [ ] 10 queued jobs are processed without API timeout
- [ ] Failed jobs are marked with reason and retry count

## 3. Content Pipeline Modules (Priority: P0)
- [ ] `Searcher`: integrate `duckduckgo-search`
- [ ] `Filter`: Gemini Flash title/snippet filtering
- [ ] `Extractor`: `trafilatura` full-text extraction
- [ ] `Generator`: Gemini prompt for 2-host dialogue script
- [ ] Stage-by-stage timeout and fallback handling

Done criteria:
- [ ] At least 1 valid script generated from a keyword input
- [ ] Pipeline per-item failure rate < 5% in local batch test

## 4. TTS Pipeline (Kokoro-82M) (Priority: P0)
- [ ] Ensure `kokoro-v1.0.onnx` and `voices-v1.0.bin` bootstrap script works
- [ ] Standardize JP voice map (`A -> jf_alpha`, `B -> jm_kumo`)
- [ ] Add text normalization preprocessor (symbols/abbreviations)
- [ ] Save generated WAV to Cloud Storage
- [ ] Store audio URL + metadata in Firestore (`episodes` collection)

Done criteria:
- [ ] Test script generates playable audio file
- [ ] End-to-end episode record includes script + audio URL

## 5. Data Model and Events (Priority: P0)
- [ ] Create Firestore collections: `users`, `episodes`, `interactions`, `jobs`
- [ ] Define interaction event schema
- [ ] Implement event ingestion endpoint (`/events/track`)
- [ ] Validate required fields (user_id, episode_id, event_type, timestamp)

Required events:
- [ ] `play_start`
- [ ] `play_30s`
- [ ] `play_complete`
- [ ] `skip_early`
- [ ] `like`
- [ ] `save`
- [ ] `share`

Done criteria:
- [ ] Events are queryable by user_id and episode_id

## 6. Recommendation v1 (Priority: P1)
- [ ] Implement normalized feature builder (0-1 scale)
- [ ] Implement score function:
  - [ ] `Score = 5.0*P_rate + 3.0*Save + 1.0*Like + 0.5*Share - 5.0*Skip`
- [ ] Add 80/20 mix logic (exploitation/exploration)
- [ ] Add simple trend fallback when user data is sparse

Done criteria:
- [ ] Feed API returns deterministic ranked list with mix ratio

## 7. Flutter Base App (Priority: P0)
- [ ] App shell + routing
- [ ] Theme setup (`Material 3`, `flex_color_scheme`)
- [ ] Onboarding Tag Splitter UI
- [ ] Persist selected tags to backend

Done criteria:
- [ ] New user onboarding completion updates profile tags

## 8. Feed and Player UI (Priority: P1)
- [ ] Feed screen (list or vertical swipe MVP)
- [ ] Player with `sliding_up_panel`
- [ ] Audio playback + waveform (`audio_waveforms`)
- [ ] Basic controls: play/pause/seek/next
- [ ] Track and send playback events

Done criteria:
- [ ] User can play episode and event logs are sent successfully

## 9. Integration and E2E (Priority: P0)
- [ ] Connect Flutter app to backend endpoints
- [ ] Validate onboarding -> feed -> playback -> tracking flow
- [ ] Handle loading/empty/error states in UI

Done criteria:
- [ ] Full E2E demo runs with one test account

## 10. Deployment and Ops (Priority: P1)
- [ ] Cloud Run deployment config
- [ ] Secret management for API keys
- [ ] Monitoring dashboard (latency, success rate, failures, cost)
- [ ] Alert rules for failure spikes

Done criteria:
- [ ] 24h run without critical errors

## 11. Suggested First Sprint Scope (1-2 weeks)
- [ ] Sections 1, 2, 3, 4, 5 (P0 core)
- [ ] Minimal Flutter onboarding + playback skeleton (part of 7 and 8)
- [ ] Single E2E happy path demo
