from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import os
import re
import threading
import time
from typing import Any, Callable
from uuid import uuid4


def _safe_stem(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip())
    return cleaned[:40] or "podcast"


def _agenda_node_map(agenda: dict[str, Any]) -> dict[str, dict[str, str]]:
    nodes = agenda.get("nodes", [])
    return {
        str(n.get("id")): {
            "id": str(n.get("id", "")),
            "title": str(n.get("title", "")),
            "role": str(n.get("role", "point")),
            "note": str(n.get("note", "")),
        }
        for n in nodes
        if isinstance(n, dict)
    }

def _ordered_chapters(agenda: dict[str, Any]) -> list[dict[str, Any]]:
    node_by_id = _agenda_node_map(agenda)
    ordered_ids = [str(x) for x in agenda.get("ordered_node_ids", [])]
    raw = agenda.get("chapters", [])
    out: list[dict[str, Any]] = []

    if isinstance(raw, list):
        for idx, chapter in enumerate(raw, start=1):
            if not isinstance(chapter, dict):
                continue
            node_ids = [str(x) for x in (chapter.get("node_ids") or []) if str(x) in node_by_id]
            if not node_ids:
                continue
            out.append(
                {
                    "chapter_id": str(chapter.get("chapter_id") or f"c{idx}"),
                    "title": str(chapter.get("title") or f"第{idx}章"),
                    "node_ids": node_ids,
                }
            )

    if out:
        return out

    ordered_nodes = [node_by_id.get(node_id) for node_id in ordered_ids]
    ordered_nodes = [n for n in ordered_nodes if n]
    if not ordered_nodes:
        ordered_nodes = [n for n in node_by_id.values() if n.get("title")]

    chunks: list[list[dict[str, str]]] = []
    i = 0
    while i < len(ordered_nodes):
        chunks.append(ordered_nodes[i : i + 2])
        i += 2
    if len(chunks) >= 2 and len(chunks[-1]) == 1:
        chunks[-2].extend(chunks[-1])
        chunks.pop()

    built: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        node_ids = [str(n.get("id")) for n in chunk if n.get("id")]
        titles = [str(n.get("title") or "").strip() for n in chunk[:2]]
        chapter_title = f"第{idx}章: {' / '.join([t for t in titles if t]) or 'Main'}"
        built.append(
            {
                "chapter_id": f"c{idx}",
                "title": chapter_title,
                "node_ids": node_ids,
            }
        )
    return built


def _token_set(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9]{2,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", (text or ""))
    return {x.lower() for x in raw}


def _build_node_context_map(
    *,
    ordered_nodes: list[dict[str, str]],
    selected_articles: list[dict[str, Any]],
    pre_research_items: list[dict[str, Any]],
) -> dict[str, str]:
    candidates: list[str] = []
    for item in selected_articles:
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or item.get("body") or "").strip()
        if title or snippet:
            candidates.append(f"{title} {snippet}".strip())
    for item in pre_research_items:
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if title or snippet:
            candidates.append(f"{title} {snippet}".strip())

    if not candidates:
        candidates = ["関連情報が限定的なため、ノード要点に集中して説明する。"]

    node_context_map: dict[str, str] = {}
    for node in ordered_nodes:
        node_id = str(node.get("id") or "")
        node_query = f"{node.get('title', '')} {node.get('note', '')}".strip()
        node_tokens = _token_set(node_query)
        scored: list[tuple[int, str]] = []
        for cand in candidates:
            score = len(node_tokens & _token_set(cand))
            scored.append((score, cand))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [txt for score, txt in scored[:3] if score > 0]
        if not picked:
            picked = [txt for _, txt in scored[:2]]
        node_context_map[node_id] = "\n".join([f"- {p[:220]}" for p in picked[:3]])
    return node_context_map


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _section_char_budget() -> dict[str, int]:
    min_chars = _env_int("SCRIPT_SECTION_MIN_CHARS", 300)
    max_chars = _env_int("SCRIPT_SECTION_MAX_CHARS", 750)
    if max_chars < min_chars:
        max_chars = min_chars
    target_chars = _env_int("SCRIPT_SECTION_TARGET_CHARS", int((min_chars + max_chars) / 2))
    target_chars = max(min_chars, min(max_chars, target_chars))
    return {
        "min_chars": min_chars,
        "max_chars": max_chars,
        "target_chars": target_chars,
    }


def _intro_char_budget() -> dict[str, int]:
    min_chars = _env_int("SCRIPT_INTRO_MIN_CHARS", 500)
    max_chars = _env_int("SCRIPT_INTRO_MAX_CHARS", 750)
    if max_chars < min_chars:
        max_chars = min_chars
    target_chars = _env_int("SCRIPT_INTRO_TARGET_CHARS", int((min_chars + max_chars) / 2))
    target_chars = max(min_chars, min(max_chars, target_chars))
    return {
        "min_chars": min_chars,
        "max_chars": max_chars,
        "target_chars": target_chars,
    }


def run_pipeline(
    *,
    topic: str,
    top_k: int,
    max_articles: int,
    region: str,
    timelimit: str,
    output_dir: str,
    tts_config: Any | None = None,
    on_stage: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    from modules import extractor, filter, generator, planner, searcher
    from modules.tts_router import (
        TtsConfig,
        combine_audio_files,
        get_default_provider,
        synthesize_script,
    )

    metrics: dict[str, Any] = {}
    transcript_sections: list[dict[str, Any]] = []
    if isinstance(tts_config, TtsConfig):
        tts_cfg = tts_config
    else:
        tts_cfg = TtsConfig(provider=get_default_provider())
    tts_provider_requested = tts_cfg.provider
    tts_provider_used = tts_provider_requested
    tts_fallback_used = False
    tts_fallback_reason: str | None = None
    tts_voice_requested = tts_cfg.voice
    tts_voice_used = tts_cfg.voice
    metrics["tts_provider_requested"] = tts_provider_requested
    metrics["tts_provider_used"] = tts_provider_used

    def set_stage(stage: str, metrics_update: dict[str, Any] | None = None) -> None:
        payload = dict(metrics_update or {})
        payload["tts_provider_requested"] = tts_provider_requested
        payload["tts_provider_used"] = tts_provider_used
        payload["tts_fallback_used"] = tts_fallback_used
        if tts_fallback_reason:
            payload["tts_fallback_reason"] = tts_fallback_reason
        if on_stage:
            on_stage(stage, payload)

    t0 = time.perf_counter()

    # 1) Lightweight pre-research for agenda direction
    t_pre = time.perf_counter()
    set_stage("pre_researching")
    pre_research_items = planner.run_pre_research(
        topic,
        region=region,
        max_results=min(max_articles, 5),
    )
    metrics["pre_research_seconds"] = round(time.perf_counter() - t_pre, 3)
    metrics["pre_research_count"] = len(pre_research_items)
    set_stage("pre_research_completed", {"pre_research_count": len(pre_research_items)})

    # 2) Causal agenda (flexible, graph-based)
    t_agenda = time.perf_counter()
    set_stage("agenda_planning")
    agenda = planner.build_causal_agenda(topic, pre_research_items)
    node_by_id = _agenda_node_map(agenda)
    chapters = _ordered_chapters(agenda)
    ordered_nodes: list[dict[str, str]] = []
    for chapter in chapters:
        for node_id in chapter.get("node_ids", []):
            node = node_by_id.get(str(node_id))
            if node and node.get("title"):
                ordered_nodes.append(node)
    metrics["agenda_seconds"] = round(time.perf_counter() - t_agenda, 3)
    metrics["agenda_node_count"] = len(agenda.get("nodes", []))
    metrics["agenda_edge_count"] = len(agenda.get("edges", []))
    metrics["chapter_count"] = len(chapters)
    metrics["topic"] = topic
    metrics["agenda_nodes"] = list(agenda.get("nodes", []))
    metrics["agenda_edges"] = list(agenda.get("edges", []))
    metrics["agenda_chapters"] = list(chapters)
    metrics["transcript_sections"] = []
    set_stage(
        "agenda_ready",
        {
            "agenda_node_count": metrics["agenda_node_count"],
            "agenda_edge_count": metrics["agenda_edge_count"],
            "chapter_count": metrics["chapter_count"],
            "topic": topic,
            "agenda_nodes": metrics["agenda_nodes"],
            "agenda_edges": metrics["agenda_edges"],
            "agenda_chapters": metrics["agenda_chapters"],
        },
    )

    # 3) Intro generation immediately after agenda
    os.makedirs(output_dir, exist_ok=True)
    episode_id = str(uuid4())
    stem = _safe_stem(topic)
    filename = f"{stem}_{episode_id}.wav"
    output_path = os.path.join(output_dir, filename)

    ready_chunk_filenames: list[str] = []
    ready_chunk_paths: list[str] = []
    ready_chunks_by_index: dict[int, tuple[str, str]] = {}
    script: list[dict[str, str]] = []

    section_budget = _section_char_budget()
    intro_budget = _intro_char_budget()
    chars_per_second = _env_float("SCRIPT_CHARS_PER_SECOND", 5.0)
    estimated_sections: list[dict[str, Any]] = []
    char_budget_sections: list[dict[str, Any]] = []
    coverage_memory: dict[str, Any] = {
        "covered_node_ids": [],
        "covered_points": [],
    }
    node_novelty_scores: list[dict[str, Any]] = []
    dedupe_rewrite_count = 0
    order_violation_rewrites = 0

    intro_seed_texts: list[str] = []
    for item in pre_research_items:
        snippet = str(item.get("snippet") or "").strip()
        title = str(item.get("title") or "").strip()
        if snippet:
            intro_seed_texts.append(f"{title}\n{snippet}".strip())
    if not intro_seed_texts:
        intro_seed_texts = [topic]
    intro_source_context = "\n\n---\n\n".join(intro_seed_texts[:5])

    t_intro_gen = time.perf_counter()
    set_stage("generating_intro")
    intro_script = generator.generate_intro(
        topic=topic,
        agenda=agenda,
        source_context=intro_source_context,
        target_chars=int(intro_budget["target_chars"]),
        min_chars=int(intro_budget["min_chars"]),
        max_chars=int(intro_budget["max_chars"]),
    )
    metrics["intro_generate_seconds"] = round(time.perf_counter() - t_intro_gen, 3)
    metrics["intro_lines"] = len(intro_script)
    estimated_intro_seconds = round(
        generator.estimate_tts_seconds(intro_script, chars_per_second), 3
    )
    intro_chars = generator.count_script_chars_text_only(intro_script)
    estimated_sections.append(
        {
            "section": "intro",
            "target_chars": int(intro_budget["target_chars"]),
            "actual_chars": intro_chars,
            "estimated_seconds": estimated_intro_seconds,
        }
    )
    char_budget_sections.append(
        {
            "section": "intro",
            "target_chars": int(intro_budget["target_chars"]),
            "min_chars": int(intro_budget["min_chars"]),
            "max_chars": int(intro_budget["max_chars"]),
            "actual_chars": intro_chars,
        }
    )
    set_stage("intro_generated", {"intro_lines": len(intro_script)})
    if not intro_script:
        raise RuntimeError("Failed to generate intro script.")

    script.extend(intro_script)
    intro_record = {
        "section_index": 0,
        "section_title": "Introduction",
        "chapter_id": None,
        "chapter_title": "Introduction",
        "node_id": None,
        "node_title": "Introduction",
        "status": "generated",
        "lines": list(intro_script),
    }
    transcript_sections.append(intro_record)
    metrics["transcript_sections"] = list(transcript_sections)

    preview_filename = f"{stem}_{episode_id}_intro.wav"
    preview_path = os.path.join(output_dir, preview_filename)

    body_section_count = 0
    generated_sections_count = 1  # intro already generated
    synthesized_sections = 0
    total_sections = len(ordered_nodes) + 2  # intro + body + conclusion
    tts_cache_hits = 0
    tts_cache_misses = 0
    intro_failed = False
    intro_tts_started_perf: float | None = None
    intro_ready_perf: float | None = None
    first_body_generate_started_perf: float | None = None
    intro_ready_while_body_running = False
    body_generation_done = False

    # 4) Start intro TTS, then prepare next sections in parallel.
    set_stage(
        "synthesizing_intro",
        {
            "section_index": 0,
            "preview_audio_filename": preview_filename,
        },
    )
    intro_tts_started_perf = time.perf_counter()
    intro_stats: dict[str, Any] = {}
    intro_executor = ThreadPoolExecutor(max_workers=1)
    intro_future = intro_executor.submit(
        synthesize_script,
        script=intro_script,
        output_path=preview_path,
        config=tts_cfg,
        chunk_lines=2,
        stats_out=intro_stats,
    )

    # 5) Main source retrieval while intro is synthesizing
    t_search = time.perf_counter()
    set_stage("searching")
    articles = searcher.get_initial_news(
        keyword=topic,
        limit=max_articles,
        region=region,
        timelimit=timelimit,
    )
    metrics["search_seconds"] = round(time.perf_counter() - t_search, 3)
    metrics["search_count"] = len(articles)
    set_stage("search_completed", {"search_count": len(articles)})
    if not articles and not pre_research_items:
        raise RuntimeError("No articles found for this topic. Try broader keywords or retry later.")

    t1 = time.perf_counter()
    set_stage("filtering")
    picked_indices = filter.pick_best_articles(articles, top_k=top_k, topic=topic)
    selected = [articles[i] for i in picked_indices if 0 <= i < len(articles)]
    metrics["filter_seconds"] = round(time.perf_counter() - t1, 3)
    metrics["selected_count"] = len(selected)
    set_stage("filter_completed", {"selected_count": len(selected)})
    if articles and not selected:
        raise RuntimeError("No articles selected by filter stage.")

    t2 = time.perf_counter()
    set_stage("extracting")
    full_texts: list[str] = []
    extract_timeout_seconds = _env_float("EXTRACT_TIMEOUT_SECONDS", 12.0)
    for idx, article in enumerate(selected, start=1):
        url = article.get("url")
        if not url:
            continue
        set_stage(
            "extracting",
            {
                "extract_index": idx,
                "extract_total": len(selected),
                "extract_timeout_seconds": extract_timeout_seconds,
            },
        )
        text = extractor.extract_full_text(
            url,
            timeout_seconds=extract_timeout_seconds,
        )
        if text:
            full_texts.append(text)
    metrics["extract_seconds"] = round(time.perf_counter() - t2, 3)
    metrics["extracted_count"] = len(full_texts)
    set_stage("extract_completed", {"extracted_count": len(full_texts)})

    source_texts: list[str] = list(full_texts)
    for item in pre_research_items:
        snippet = str(item.get("snippet") or "").strip()
        title = str(item.get("title") or "").strip()
        if snippet:
            source_texts.append(f"{title}\n{snippet}".strip())

    if not source_texts:
        raise RuntimeError("Failed to prepare source texts for script generation.")

    source_context = "\n\n---\n\n".join(source_texts[:5])
    node_context_map = _build_node_context_map(
        ordered_nodes=ordered_nodes,
        selected_articles=selected,
        pre_research_items=pre_research_items,
    )

    # 6) Sequential body generation + parallel TTS workers
    pending_tts: dict[Future[Any], dict[str, Any]] = {}
    # Body/conclusion are parallelized by default; set TTS_SERIAL_SECTION_MODE=true to force serial.
    tts_serial_mode = _env_bool("TTS_SERIAL_SECTION_MODE", False)
    tts_workers = 1 if tts_serial_mode else max(1, int(os.environ.get("TTS_MAX_WORKERS", "2")))
    timings_ready = True

    # Intro synthesis is tracked in the same completion path as body/conclusion.
    pending_tts[intro_future] = {
        "section_index": 0,
        "section_title": "Introduction",
        "section_filename": preview_filename,
        "section_path": preview_path,
        "section_record": intro_record,
        "ready_stage_name": "intro_ready",
        "stats_out": intro_stats,
    }

    def _progress_payload() -> dict[str, Any]:
        ratio = synthesized_sections / max(total_sections, 1)
        return {
            "total_sections": total_sections,
            "generated_sections": generated_sections_count,
            "synthesized_sections": synthesized_sections,
            "progress_ratio": round(ratio, 4),
        }

    def _submit_tts_task(
        executor: ThreadPoolExecutor,
        *,
        section_index: int,
        section_title: str,
        section_filename: str,
        section_path: str,
        section_script: list[dict[str, str]],
        section_record: dict[str, Any],
        stage_name: str | None,
        ready_stage_name: str,
    ) -> None:
        stats_out: dict[str, Any] = {}
        if stage_name:
            stage_payload = {
                "section_index": section_index,
                "section_title": section_title,
                "section_filename": section_filename,
            }
            if section_record.get("chapter_id") is not None:
                stage_payload["chapter_id"] = section_record.get("chapter_id")
            if section_record.get("chapter_title") is not None:
                stage_payload["chapter_title"] = section_record.get("chapter_title")
            if section_record.get("node_id") is not None:
                stage_payload["node_id"] = section_record.get("node_id")
            set_stage(
                stage_name,
                stage_payload,
            )
        future = executor.submit(
            synthesize_script,
            script=section_script,
            output_path=section_path,
            config=tts_cfg,
            chunk_lines=2,
            stats_out=stats_out,
        )
        pending_tts[future] = {
            "section_index": section_index,
            "section_title": section_title,
            "section_filename": section_filename,
            "section_path": section_path,
            "section_record": section_record,
            "ready_stage_name": ready_stage_name,
            "stats_out": stats_out,
        }

    def _consume_completed_tts(*, block_until_one: bool) -> None:
        nonlocal synthesized_sections, tts_cache_hits, tts_cache_misses, intro_failed, intro_ready_perf
        nonlocal tts_provider_used, tts_fallback_used, tts_fallback_reason
        nonlocal tts_voice_requested, tts_voice_used
        nonlocal timings_ready, intro_ready_while_body_running
        if not pending_tts:
            return

        done, _ = wait(
            set(pending_tts.keys()),
            timeout=0.5 if block_until_one else 0.0,
            return_when=FIRST_COMPLETED,
        )
        for future in done:
            meta = pending_tts.pop(future, None)
            if not meta:
                continue
            try:
                future.result()
            except Exception as tts_error:
                print(
                    f"[pipeline] tts failed section={meta['section_index']} "
                    f"title={meta['section_title']} error={tts_error}"
                )
                if int(meta["section_index"]) == 0:
                    intro_failed = True
                continue

            stats_out = meta.get("stats_out") or {}
            tts_cache_hits += int(stats_out.get("cache_hits", 0))
            tts_cache_misses += int(stats_out.get("cache_misses", 0))
            if not bool(stats_out.get("line_timings_ready", True)):
                timings_ready = False
            if bool(stats_out.get("timings_deferred", False)):
                timings_ready = False
            used = str(stats_out.get("tts_provider_used") or tts_provider_requested).strip().lower()
            if used:
                tts_provider_used = used
            if bool(stats_out.get("tts_fallback_used", False)):
                tts_fallback_used = True
                reason = str(stats_out.get("tts_fallback_reason") or "").strip()
                if reason:
                    tts_fallback_reason = reason
            req_voice = str(stats_out.get("tts_voice_requested") or "").strip()
            used_voice = str(stats_out.get("tts_voice_used") or "").strip()
            if req_voice:
                tts_voice_requested = req_voice
            if used_voice:
                tts_voice_used = used_voice
            if not os.path.exists(meta["section_path"]):
                if int(meta["section_index"]) == 0:
                    intro_failed = True
                continue

            section_index = int(meta["section_index"])
            if section_index not in ready_chunks_by_index:
                synthesized_sections += 1
            meta["section_record"]["status"] = "ready"
            line_timings = stats_out.get("line_timings")
            if isinstance(line_timings, list):
                section_lines = list(meta["section_record"].get("lines") or [])
                for i, t in enumerate(line_timings):
                    if i >= len(section_lines):
                        break
                    if not isinstance(section_lines[i], dict):
                        continue
                    if not isinstance(t, dict):
                        continue
                    section_lines[i]["start_ms"] = int(t.get("start_ms", 0))
                    section_lines[i]["end_ms"] = int(t.get("end_ms", 0))
                meta["section_record"]["lines"] = section_lines
            section_audio_ms = int(stats_out.get("audio_ms", 0) or 0)
            if section_audio_ms > 0:
                meta["section_record"]["audio_ms"] = section_audio_ms
            ready_chunks_by_index[section_index] = (meta["section_filename"], meta["section_path"])

            ordered_pairs = [ready_chunks_by_index[k] for k in sorted(ready_chunks_by_index.keys())]
            ready_chunk_filenames[:] = [p[0] for p in ordered_pairs]
            ready_chunk_paths[:] = [p[1] for p in ordered_pairs]
            if "ttfa_seconds" not in metrics:
                metrics["ttfa_seconds"] = round(time.perf_counter() - t0, 3)
            metrics["ready_chunk_count"] = len(ready_chunk_filenames)
            metrics["ready_audio_chunks"] = list(ready_chunk_filenames)
            metrics["transcript_sections"] = list(transcript_sections)
            metrics["progress"] = _progress_payload()

            if meta["ready_stage_name"] == "intro_ready":
                intro_ready_perf = time.perf_counter()
                if intro_tts_started_perf is not None:
                    metrics["intro_tts_seconds"] = round(intro_ready_perf - intro_tts_started_perf, 3)
                if first_body_generate_started_perf is not None and not body_generation_done:
                    intro_ready_while_body_running = True
                set_stage(
                    "intro_ready" if not intro_failed else "intro_failed",
                    {
                        "preview_audio_filename": preview_filename,
                        "intro_failed": intro_failed,
                        "ready_audio_chunks": list(ready_chunk_filenames),
                        "ready_chunk_count": len(ready_chunk_filenames),
                        "ttfa_seconds": metrics.get("ttfa_seconds"),
                        "progress": metrics.get("progress", _progress_payload()),
                    },
                )
            else:
                ready_payload = {
                    "section_index": meta["section_index"],
                    "section_title": meta["section_title"],
                    "section_filename": meta["section_filename"],
                    "ready_audio_chunks": list(ready_chunk_filenames),
                    "ready_chunk_count": len(ready_chunk_filenames),
                    "transcript_sections": list(transcript_sections),
                    "progress": metrics["progress"],
                }
                if meta["section_record"].get("chapter_id") is not None:
                    ready_payload["chapter_id"] = meta["section_record"].get("chapter_id")
                if meta["section_record"].get("chapter_title") is not None:
                    ready_payload["chapter_title"] = meta["section_record"].get("chapter_title")
                if meta["section_record"].get("node_id") is not None:
                    ready_payload["node_id"] = meta["section_record"].get("node_id")
                set_stage(
                    meta["ready_stage_name"],
                    ready_payload,
                )

    with ThreadPoolExecutor(max_workers=tts_workers) as tts_executor:
        body_total = len(ordered_nodes)
        body_generated = 0
        for chapter_idx, chapter in enumerate(chapters, start=1):
            chapter_node_ids = [str(x) for x in chapter.get("node_ids", [])]
            chapter_nodes = [node_by_id.get(node_id) for node_id in chapter_node_ids]
            chapter_nodes = [n for n in chapter_nodes if n and n.get("title")]
            chapter_total = len(chapter_nodes)
            if chapter_total == 0:
                continue

            for node_idx, node in enumerate(chapter_nodes, start=1):
                idx = body_generated + 1
                if first_body_generate_started_perf is None:
                    first_body_generate_started_perf = time.perf_counter()
                    metrics["first_body_generate_started_at"] = round(first_body_generate_started_perf - t0, 3)
                    if intro_tts_started_perf is not None:
                        metrics["intro_submit_to_body_start_ms"] = int(
                            round((first_body_generate_started_perf - intro_tts_started_perf) * 1000.0)
                        )

                stage_meta = {
                    "section_index": idx,
                    "section_title": node.get("title", ""),
                    "chapter_index": chapter_idx,
                    "chapter_total": len(chapters),
                    "node_index_in_chapter": node_idx,
                    "node_total_in_chapter": chapter_total,
                }
                set_stage("generating_section", stage_meta)

                tail_lines = script[-10:]
                prior_context = "\n".join(
                    [f"{ln['speaker']}: {ln['text']}" for ln in tail_lines if ln.get("text")]
                )
                node_id = str(node.get("id", f"n{idx}"))
                node_context = node_context_map.get(node_id, f"- {node.get('title', '')}")
                section_script = generator.generate_body_section(
                    topic=topic,
                    agenda_node=node,
                    prior_context=prior_context,
                    node_context=node_context,
                    coverage_memory=coverage_memory,
                    target_chars=int(section_budget["target_chars"]),
                    min_chars=int(section_budget["min_chars"]),
                    max_chars=int(section_budget["max_chars"]),
                )
                if not section_script:
                    _consume_completed_tts(block_until_one=False)
                    continue

                if generator.is_off_topic_section(agenda_node=node, section_script=section_script):
                    for _ in range(2):
                        retried = generator.generate_body_section(
                            topic=topic,
                            agenda_node=node,
                            prior_context=prior_context,
                            node_context=node_context,
                            coverage_memory=coverage_memory,
                            target_chars=int(section_budget["target_chars"]),
                            min_chars=int(section_budget["min_chars"]),
                            max_chars=int(section_budget["max_chars"]),
                        )
                        if retried:
                            section_script = retried
                            order_violation_rewrites += 1
                        if not generator.is_off_topic_section(agenda_node=node, section_script=section_script):
                            break

                novelty = generator.compute_section_novelty(
                    section_script,
                    list(coverage_memory.get("covered_points") or []),
                )
                novelty_threshold = _env_float("SECTION_NOVELTY_THRESHOLD", 0.32)
                if novelty < novelty_threshold:
                    for _ in range(2):
                        rewritten = generator.rewrite_section_to_reduce_overlap(
                            topic=topic,
                            agenda_node=node,
                            section_script=section_script,
                            covered_points=list(coverage_memory.get("covered_points") or []),
                            target_chars=int(section_budget["target_chars"]),
                            min_chars=int(section_budget["min_chars"]),
                            max_chars=int(section_budget["max_chars"]),
                        )
                        if rewritten and rewritten != section_script:
                            section_script = rewritten
                            dedupe_rewrite_count += 1
                            novelty = generator.compute_section_novelty(
                                section_script,
                                list(coverage_memory.get("covered_points") or []),
                            )
                        if novelty >= novelty_threshold:
                            break

                delta = generator.summarize_section_delta(
                    topic=topic,
                    agenda_node=node,
                    section_script=section_script,
                    covered_points=list(coverage_memory.get("covered_points") or []),
                )
                coverage_memory["covered_node_ids"].append(node_id)
                for point in list(delta.get("new_points") or [])[:2]:
                    s = str(point).strip()
                    if s and s not in coverage_memory["covered_points"]:
                        coverage_memory["covered_points"].append(s)

                # Read out chapter title when entering a new chapter.
                if node_idx == 1:
                    chapter_title = str(chapter.get("title", "")).strip()
                    if chapter_title:
                        section_script = [
                            {"speaker": "A", "text": chapter_title},
                            *section_script,
                        ]

                node_novelty_scores.append(
                    {
                        "section_index": idx,
                        "chapter_id": chapter.get("chapter_id"),
                        "chapter_title": chapter.get("title"),
                        "node_id": node_id,
                        "section_title": node.get("title", ""),
                        "novelty_score": novelty,
                    }
                )

                script.extend(section_script)
                body_section_count += 1
                body_generated += 1
                generated_sections_count += 1
                section_record = {
                    "section_index": idx,
                    "section_title": node.get("title", ""),
                    "chapter_id": chapter.get("chapter_id"),
                    "chapter_title": chapter.get("title"),
                    "node_id": node_id,
                    "node_title": node.get("title", ""),
                    "status": "generated",
                    "lines": list(section_script),
                }
                transcript_sections.append(section_record)
                section_chars = generator.count_script_chars_text_only(section_script)
                estimated_sections.append(
                    {
                        "section": f"body_{idx}",
                        "title": node.get("title", ""),
                        "target_chars": int(section_budget["target_chars"]),
                        "actual_chars": section_chars,
                        "estimated_seconds": round(
                            generator.estimate_tts_seconds(section_script, chars_per_second), 3
                        ),
                    }
                )
                char_budget_sections.append(
                    {
                        "section": f"body_{idx}",
                        "title": node.get("title", ""),
                        "target_chars": int(section_budget["target_chars"]),
                        "min_chars": int(section_budget["min_chars"]),
                        "max_chars": int(section_budget["max_chars"]),
                        "actual_chars": section_chars,
                    }
                )
                metrics["chapter_progress"] = {
                    "chapter_index": chapter_idx,
                    "chapter_total": len(chapters),
                    "node_index_in_chapter": node_idx,
                    "node_total_in_chapter": chapter_total,
                    "body_generated": body_generated,
                    "body_total": body_total,
                }
                metrics["transcript_sections"] = list(transcript_sections)
                metrics["progress"] = _progress_payload()
                set_stage(
                    "section_generated",
                    {
                        **stage_meta,
                        "novelty_score": novelty,
                        "transcript_sections": list(transcript_sections),
                        "progress": metrics["progress"],
                        "chapter_progress": metrics["chapter_progress"],
                    },
                )

                section_filename = f"{stem}_{episode_id}_sec{idx:02d}.wav"
                section_path = os.path.join(output_dir, section_filename)
                _submit_tts_task(
                    tts_executor,
                    section_index=idx,
                    section_title=node.get("title", ""),
                    section_filename=section_filename,
                    section_path=section_path,
                    section_script=section_script,
                    section_record=section_record,
                    stage_name="synthesizing_section",
                    ready_stage_name="section_ready",
                )
                if tts_serial_mode:
                    while pending_tts:
                        _consume_completed_tts(block_until_one=True)
                else:
                    _consume_completed_tts(block_until_one=False)

        metrics["body_sections"] = body_section_count
        body_generation_done = True

        # 6) Conclusion generation (sequential) + parallel TTS
        set_stage("generating_conclusion")
        full_context = "\n".join([f"{ln['speaker']}: {ln['text']}" for ln in script])
        conclusion_script = generator.generate_conclusion(
            topic=topic,
            agenda=agenda,
            full_script_context=full_context,
            source_context=source_context,
            coverage_memory=coverage_memory,
            target_chars=int(section_budget["target_chars"]),
            min_chars=int(section_budget["min_chars"]),
            max_chars=int(section_budget["max_chars"]),
        )
        if conclusion_script:
            conclusion_index = len(ordered_nodes) + 1
            script.extend(conclusion_script)
            generated_sections_count += 1
            conclusion_record = {
                "section_index": conclusion_index,
                "section_title": "Conclusion",
                "chapter_id": None,
                "chapter_title": "Conclusion",
                "node_id": None,
                "node_title": "Conclusion",
                "status": "generated",
                "lines": list(conclusion_script),
            }
            transcript_sections.append(conclusion_record)
            conclusion_chars = generator.count_script_chars_text_only(conclusion_script)
            estimated_sections.append(
                {
                    "section": "conclusion",
                    "target_chars": int(section_budget["target_chars"]),
                    "actual_chars": conclusion_chars,
                    "estimated_seconds": round(
                        generator.estimate_tts_seconds(conclusion_script, chars_per_second), 3
                    ),
                }
            )
            char_budget_sections.append(
                {
                    "section": "conclusion",
                    "target_chars": int(section_budget["target_chars"]),
                    "min_chars": int(section_budget["min_chars"]),
                    "max_chars": int(section_budget["max_chars"]),
                    "actual_chars": conclusion_chars,
                }
            )
            metrics["transcript_sections"] = list(transcript_sections)
            metrics["progress"] = _progress_payload()
            set_stage(
                "conclusion_generated",
                {
                    "transcript_sections": list(transcript_sections),
                    "progress": metrics["progress"],
                },
            )
            conclusion_filename = f"{stem}_{episode_id}_conclusion.wav"
            conclusion_path = os.path.join(output_dir, conclusion_filename)
            _submit_tts_task(
                tts_executor,
                section_index=conclusion_index,
                section_title="Conclusion",
                section_filename=conclusion_filename,
                section_path=conclusion_path,
                section_script=conclusion_script,
                section_record=conclusion_record,
                stage_name="synthesizing_conclusion",
                ready_stage_name="conclusion_ready",
            )
            if tts_serial_mode:
                while pending_tts:
                    _consume_completed_tts(block_until_one=True)

        while pending_tts:
            _consume_completed_tts(block_until_one=True)

    intro_executor.shutdown(wait=False)

    metrics["script_lines"] = len(script)
    if not ready_chunk_paths:
        raise RuntimeError("No synthesized audio chunks were produced.")

    # 7) Finalize full episode file by concatenating chunk files (deferred by default).
    defer_finalize = _env_bool("FINALIZE_AUDIO_DEFERRED", True)
    final_audio_ready = False
    final_audio_filename = filename
    if not defer_finalize:
        t_final = time.perf_counter()
        set_stage("finalizing_audio")
        combine_audio_files(ready_chunk_paths, output_path)
        metrics["tts_seconds"] = round(time.perf_counter() - t_final, 3)
        metrics["finalize_seconds_async"] = 0.0
        if not os.path.exists(output_path):
            raise RuntimeError("Audio finalize step did not create output file.")
        final_audio_ready = True
        metrics["finalize_deferred"] = False
    else:
        metrics["tts_seconds"] = 0.0
        metrics["finalize_deferred"] = True
        metrics["finalize_seconds_async"] = None
        set_stage(
            "finalizing_audio_async",
            {
                "audio_filename": filename,
                "ready_audio_chunks": list(ready_chunk_filenames),
                "ready_chunk_count": len(ready_chunk_filenames),
            },
        )

        def _finalize_async() -> None:
            t_final = time.perf_counter()
            ok = False
            error_message: str | None = None
            try:
                combine_audio_files(ready_chunk_paths, output_path)
                ok = os.path.exists(output_path)
            except Exception as exc:
                error_message = str(exc)
                ok = False
            payload: dict[str, Any] = {
                "audio_filename": filename,
                "final_audio_ready": ok,
                "finalize_seconds_async": round(time.perf_counter() - t_final, 3),
            }
            if not ok and error_message:
                payload["error"] = error_message
            set_stage("final_audio_completed", payload)

        threading.Thread(target=_finalize_async, daemon=True).start()

    set_stage(
        "synthesis_completed",
        {
            "audio_filename": filename,
            "playable_from_chunks": bool(ready_chunk_filenames),
            "final_audio_ready": final_audio_ready,
            "final_audio_filename": final_audio_filename,
            "ready_audio_chunks": list(ready_chunk_filenames),
            "ready_chunk_count": len(ready_chunk_filenames),
            "progress": {
                "total_sections": total_sections,
                "generated_sections": generated_sections_count,
                "synthesized_sections": synthesized_sections,
                "progress_ratio": 1.0 if ready_chunk_filenames else 0.0,
            },
        },
    )

    metrics["total_seconds"] = round(time.perf_counter() - t0, 3)
    metrics["intro_tts_async"] = False
    metrics["intro_tts_overlap_seconds"] = 0.0
    metrics["intro_failed"] = intro_failed
    metrics["intro_ready_while_body_running"] = intro_ready_while_body_running
    if "intro_submit_to_body_start_ms" not in metrics and first_body_generate_started_perf is not None and intro_tts_started_perf is not None:
        metrics["intro_submit_to_body_start_ms"] = int(
            round((first_body_generate_started_perf - intro_tts_started_perf) * 1000.0)
        )
    cache_total = tts_cache_hits + tts_cache_misses
    metrics["tts_cache_hits"] = tts_cache_hits
    metrics["tts_cache_misses"] = tts_cache_misses
    metrics["tts_cache_hit_ratio"] = round((tts_cache_hits / cache_total), 4) if cache_total else 0.0
    metrics["tts_provider_requested"] = tts_provider_requested
    metrics["tts_provider_used"] = tts_provider_used
    metrics["tts_fallback_used"] = tts_fallback_used
    metrics["tts_voice_requested"] = tts_voice_requested
    metrics["tts_voice_used"] = tts_voice_used
    metrics["tts_serial_section_mode"] = tts_serial_mode
    metrics["timings_ready"] = bool(timings_ready)
    metrics["playable_from_chunks"] = bool(ready_chunk_filenames)
    metrics["final_audio_ready"] = bool(final_audio_ready)
    metrics["final_audio_filename"] = final_audio_filename
    if tts_fallback_reason:
        metrics["tts_fallback_reason"] = tts_fallback_reason
    metrics["char_budget_mode"] = "per_section"
    metrics["char_budget_intro_min"] = int(intro_budget["min_chars"])
    metrics["char_budget_intro_target"] = int(intro_budget["target_chars"])
    metrics["char_budget_intro_max"] = int(intro_budget["max_chars"])
    metrics["char_budget_section_min"] = int(section_budget["min_chars"])
    metrics["char_budget_section_target"] = int(section_budget["target_chars"])
    metrics["char_budget_section_max"] = int(section_budget["max_chars"])
    metrics["char_budget_sections"] = char_budget_sections
    metrics["actual_script_chars_total"] = generator.count_script_chars_text_only(script)
    metrics["estimated_section_seconds"] = estimated_sections
    metrics["estimated_script_seconds_total"] = round(
        sum(float(item.get("estimated_seconds", 0.0)) for item in estimated_sections),
        3,
    )
    metrics["coverage_points_count"] = len(list(coverage_memory.get("covered_points") or []))
    metrics["node_novelty_scores"] = node_novelty_scores
    metrics["order_violation_rewrites"] = order_violation_rewrites
    metrics["dedupe_rewrite_count"] = dedupe_rewrite_count
    metrics["progress"] = {
        "total_sections": total_sections,
        "generated_sections": generated_sections_count,
        "synthesized_sections": synthesized_sections,
        "progress_ratio": 1.0 if ready_chunk_filenames else 0.0,
    }
    # Compute strict global timestamps for transcript lines based on synthesized per-line timings.
    ordered_sections = sorted(
        [s for s in transcript_sections if isinstance(s, dict)],
        key=lambda s: int(s.get("section_index", 0)),
    )
    cursor_ms = 0
    for sec in ordered_sections:
        lines = sec.get("lines") or []
        if not isinstance(lines, list):
            lines = []
        sec_audio_ms = int(sec.get("audio_ms", 0) or 0)
        max_end = 0
        for line in lines:
            if not isinstance(line, dict):
                continue
            start_ms = int(line.get("start_ms", 0) or 0)
            end_ms = int(line.get("end_ms", 0) or 0)
            if end_ms > max_end:
                max_end = end_ms
            line["global_start_ms"] = cursor_ms + start_ms
            line["global_end_ms"] = cursor_ms + max(end_ms, start_ms)
        sec_len = sec_audio_ms if sec_audio_ms > 0 else max_end
        sec["global_start_ms"] = cursor_ms
        sec["global_end_ms"] = cursor_ms + max(sec_len, 0)
        cursor_ms += max(sec_len, 0)
    metrics["transcript_sections"] = list(transcript_sections)

    return {
        "episode_id": episode_id,
        "topic": topic,
        "selected_titles": [a.get("title", "") for a in selected],
        "audio_filename": filename,
        "preview_audio_filename": preview_filename,
        "script_lines": len(script),
        "agenda_nodes": list(agenda.get("nodes", [])),
        "agenda_edges": list(agenda.get("edges", [])),
        "agenda_chapters": list(chapters),
        "transcript_sections": list(transcript_sections),
        "tts_provider_requested": tts_provider_requested,
        "tts_provider_used": tts_provider_used,
        "tts_fallback_used": tts_fallback_used,
        "tts_voice_requested": tts_voice_requested,
        "tts_voice_used": tts_voice_used,
        "playable_from_chunks": bool(ready_chunk_filenames),
        "final_audio_ready": bool(final_audio_ready),
        "final_audio_filename": final_audio_filename,
        "timings_ready": bool(timings_ready),
        "metrics": metrics,
    }
