# StepWise Implementation Plan (Sequential + Causal + UX First)

## 0. Goal
- Perceived wait time close to zero from topic input to playback start.
- Causal consistency over rigid template formatting.
- No bridge filler for time padding.
- Target runtime: around 3 minutes.

## 1. Architecture Layers

### 1.1 Structure Layer (logical planning)
- Lightweight pre-research by DDGS with multi-query strategy.
- Causal point extraction (cause/effect/constraint/side_effect/conflict/reframe).
- Causal graph construction and topological ordering.
- Agenda remains mutable for unplayed sections.

### 1.2 Text Layer (sequential generation)
- Intro generation first.
- Body generation section-by-section using prior context.
- Conclusion re-generated at the end based on whole script.

### 1.4 LLM Provider
- Provider: OpenRouter (required).
- Default model: `google/gemini-2.5-flash-lite`.
- Required env var: `OPENROUTER_API_KEY`.
- Optional env vars:
  - `OPENROUTER_MODEL`
  - `OPENROUTER_BASE_URL`

### 1.3 Audio Layer (streaming-oriented synthesis)
- Start TTS at chunk granularity.
- Keep queue/buffer metrics visible.
- Avoid bridge padding; solve stalls with chunking and scheduling.

## 2. Confirmed Runtime Flow
1. topic input
2. lightweight pre-research (DDGS)
3. causal point extraction
4. causal graph build
5. provisional agenda
6. intro generation
7. intro chunk TTS
8. intro playback start (TTFA target: 0.5-1.0s)
9. body section generation (sequential)
10. body chunk TTS
11. repeat for remaining sections
12. final conclusion re-optimization
13. playback end

## 3. DDGS Pre-research Policy

### 3.1 Query set
- {topic} とは
- {topic} 原因 結果
- {topic} メリット デメリット
- {topic} 最新

### 3.2 Scope
- Fast directional context only (definition, causal hints, major conflicts, proper nouns).
- max_results: 3-5.
- Not a full retrieval stage.

## 4. Agenda Rules
- No fixed 3-point template.
- No fixed Why/How frame.
- No fixed length allocation.
- Agenda is represented as a causal DAG.

Output schema:
- nodes: id, title, role, note
- edges: from, to
- ordered_node_ids: topological sequence

## 5. Sequential Generation Rules
- Each section must depend on previous section context.
- Temporary hypothesis-style conclusion may appear early.
- Final conclusion is regenerated and optimized at end.
- No bridge filler or duplicated summary lines.

## 6. UX / Performance Targets
- TTFA: 0.5-1.0s (design target).
- Playback start after intro chunk readiness.
- Maintain >10s queued audio whenever possible.
- Track metrics: pre_research, agenda, intro_gen, intro_tts, ttfa, script_chunks, tts_chunks, total.

## 7. Backend Implementation Status

Implemented in current revision:
- Added `modules/planner.py` for pre-research + causal agenda generation.
- Upgraded `modules/generator.py` to sequential generation APIs:
  - `generate_intro`
  - `generate_body_section`
  - `generate_conclusion`
  - `generate_script_sequential`
- Upgraded `pipeline.py` flow:
  - pre-research -> agenda -> intro-first -> sequential script -> incremental synthesis.
  - intro preview audio generation and TTFA metric recording.
- Added incremental synthesis API in `modules/synthesizer.py`:
  - `synthesize_audio_incremental`.
- Added `preview_audio_url` support in job result schema/API.

## 8. Next Steps (Priority)
1. Frontend: consume `preview_audio_url` for early playback before full completion.
2. Frontend: show job-stage timeline and TTFA metrics.
3. Backend: replace file-based preview with true stream endpoint.
4. Backend: adaptive chunk scheduler with minimum buffer guarantee.
5. Recommendation: combine user profile topic priors with interaction score.

## 9. Guardrails
- No non-causal padding text.
- No rigid fixed-format agenda templates.
- Regenerate only unplayed parts when agenda updates.
- Keep fallback behavior deterministic when LLM parsing fails.
