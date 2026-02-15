from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List

from modules.llm import get_client, resolve_model_name


def _extract_json_array(text: str) -> list:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        raise ValueError("No JSON array found in model response.")
    return json.loads(match.group(0))


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError("No JSON object found in model response.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON is not an object.")
    return parsed


def _clean_script_items(script: list[Any]) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    for item in script:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            cleaned.append({"speaker": "A", "text": text.strip()})
    return cleaned


def _looks_question_ending(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    if value.endswith("?") or value.endswith("？"):
        return True
    return bool(re.search(r"(でしょうか|ますか|ですか|だろうか|なのか|か)$", value))


def _to_statement_ending(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return value
    value = re.sub(r"[?？]+$", "", value).strip()
    value = re.sub(r"(でしょうか|ますか|ですか|だろうか|なのか|か)$", "", value).strip()
    if not value:
        return "以上を踏まえて、次の実務判断につなげます。"
    if value.endswith(("。", "！", "!", "…")):
        return value
    return value + "。"


def _ensure_last_line_not_question(script: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not script:
        return script
    out = list(script)
    for i in range(len(out) - 1, -1, -1):
        text = str(out[i].get("text", "")).strip()
        if not text:
            continue
        if _looks_question_ending(text):
            out[i] = {"speaker": "A", "text": _to_statement_ending(text)}
        break
    return out


def _recent_tail_lines(prior_context: str, limit: int = 3) -> List[str]:
    lines: List[str] = []
    for raw in (prior_context or "").splitlines():
        value = raw.strip()
        if not value:
            continue
        if ":" in value:
            value = value.split(":", 1)[1].strip()
        if value:
            lines.append(value)
    return lines[-max(1, limit) :]


def _stabilize_body_ending(
    script: List[Dict[str, str]],
    prior_context: str,
    *,
    lookback_lines: int = 3,
    max_recent_question_endings: int = 0,
) -> List[Dict[str, str]]:
    # Allow occasional question endings, but prevent repeated question-ending cadence.
    recent = _recent_tail_lines(prior_context, limit=lookback_lines)
    recent_q = sum(1 for line in recent if _looks_question_ending(line))
    if recent_q > max_recent_question_endings:
        return _ensure_last_line_not_question(script)
    return script


def _truncate(text: str, max_len: int) -> str:
    value = (text or "").strip()
    if len(value) <= max_len:
        return value
    return value[:max_len].rstrip() + "..."


def _normalize_point_text(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_anchor_keywords(node_title: str, node_note: str) -> List[str]:
    text = f"{node_title} {node_note}".strip()
    raw = re.findall(r"[A-Za-z0-9]{2,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", text)
    stop = {
        "こと",
        "ため",
        "よう",
        "これ",
        "それ",
        "もの",
        "です",
        "ます",
        "する",
        "した",
        "して",
        "topic",
        "node",
    }
    out: List[str] = []
    seen: set[str] = set()
    for token in raw:
        key = token.lower()
        if key in stop:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out[:8]


def _is_off_topic(section_script: List[Dict[str, str]], anchor_keywords: List[str]) -> bool:
    if not section_script or not anchor_keywords:
        return False
    text = _script_text(section_script).lower()
    hit = 0
    for token in anchor_keywords:
        if token.lower() in text:
            hit += 1
    return hit <= 0


def is_off_topic_section(
    *,
    agenda_node: dict[str, str],
    section_script: List[Dict[str, str]],
) -> bool:
    anchors = _extract_anchor_keywords(
        str(agenda_node.get("title", "")),
        str(agenda_node.get("note", "")),
    )
    return _is_off_topic(section_script, anchors)


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    s = _normalize_point_text(text)
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _max_similarity_to_points(text: str, points: List[str]) -> float:
    base = _char_ngrams(text, 3)
    if not base:
        return 0.0
    best = 0.0
    for point in points:
        other = _char_ngrams(point, 3)
        if not other:
            continue
        inter = len(base & other)
        union = len(base | other)
        sim = (inter / union) if union else 0.0
        if sim > best:
            best = sim
    return best


def compute_section_novelty(
    section_script: List[Dict[str, str]],
    covered_points: List[str],
) -> float:
    text = _script_text(section_script)
    if not text:
        return 0.0
    if not covered_points:
        return 1.0
    return round(max(0.0, 1.0 - _max_similarity_to_points(text, covered_points)), 4)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _script_text(script: List[Dict[str, str]]) -> str:
    return "\n".join(item.get("text", "") for item in script)


def count_script_chars_text_only(script: List[Dict[str, str]]) -> int:
    total = 0
    for item in script:
        total += len(str(item.get("text", "")))
    return total


def _char_budget_constraints(
    target_chars: int | None,
    *,
    min_chars: int,
    max_chars: int,
) -> dict[str, int]:
    max_chars = max(min_chars, max_chars)
    default_target = int(round((min_chars + max_chars) / 2.0))
    target = int(target_chars if target_chars is not None else default_target)
    target = max(min_chars, min(max_chars, target))
    max_lines = max(6, min(20, int(round(target / 80.0))))
    max_chars_per_line = max(28, min(180, int(round(max_chars / max(max_lines, 1)))))
    return {
        "target_chars": target,
        "min_chars": min_chars,
        "max_chars": max_chars,
        "max_lines": max_lines,
        "max_chars_per_line": max_chars_per_line,
    }


def estimate_tts_seconds(
    script: List[Dict[str, str]],
    chars_per_second: float | None = None,
) -> float:
    cps = chars_per_second if chars_per_second is not None else _env_float("SCRIPT_CHARS_PER_SECOND", 5.0)
    cps = max(3.0, float(cps))
    text = _script_text(script)
    return len(text) / cps if text else 0.0


def _truncate_script_to_char_budget(
    script: List[Dict[str, str]],
    *,
    max_lines: int,
    max_chars_per_line: int,
    target_chars: int,
) -> List[Dict[str, str]]:
    if not script:
        return script
    out: List[Dict[str, str]] = []
    consumed = 0
    for item in script[: max(1, max_lines)]:
        speaker = item.get("speaker", "A")
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        text = text[:max_chars_per_line].strip()
        remain = max(0, target_chars - consumed)
        if remain <= 0:
            break
        text = text[:remain].strip()
        if not text:
            break
        consumed += len(text)
        out.append({"speaker": speaker, "text": text})
        if consumed >= target_chars:
            break
    return out or script[:1]


def _is_english_heavy(script: List[Dict[str, str]]) -> bool:
    text = _script_text(script)
    if not text:
        return False
    alpha = len(re.findall(r"[A-Za-z]", text))
    ja = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text))
    if alpha >= 24 and alpha > (ja * 0.8):
        return True
    return ja < 20 and alpha >= 12


def _is_line_japanese_poor(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    ja = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", value))
    alpha = len(re.findall(r"[A-Za-z]", value))
    return alpha >= 8 and (ja == 0 or alpha > ja)


def _needs_japanese_rewrite(script: List[Dict[str, str]]) -> bool:
    if not script:
        return False
    if _is_english_heavy(script):
        return True
    poor_lines = 0
    for item in script:
        if _is_line_japanese_poor(item.get("text", "")):
            poor_lines += 1
    return poor_lines >= 1


def _rewrite_script_to_japanese(
    *,
    script: List[Dict[str, str]],
    context_prompt: str,
) -> List[Dict[str, str]]:
    if not script:
        return script
    serialized = json.dumps(script, ensure_ascii=False)
    rewrite_prompt = f"""
You are a Japanese broadcast editor.
Rewrite the following dialogue into natural Japanese for TTS.

Strict rules:
- Keep the same number of lines.
- Set every line speaker to A.
- Output language MUST be Japanese.
- Do not write full English sentences.
- Convert English words, abbreviations, and proper nouns to natural katakana reading.
- Do not convert ordinary Japanese words to katakana.
- Keep factual meaning and causal flow.
- Return ONLY JSON array: [{{"speaker":"A","text":"..."}}]

Context:
{context_prompt}

Input dialogue JSON:
{serialized}
"""
    client = get_client()
    model_name = resolve_model_name()
    response = client.models.generate_content(model=model_name, contents=rewrite_prompt)
    parsed = _extract_json_array(response.text or "")
    rewritten = _clean_script_items(parsed)
    return rewritten or script


def _rewrite_script_for_char_budget(
    *,
    script: List[Dict[str, str]],
    target_chars: int,
    min_chars: int,
    max_chars: int,
    max_lines: int,
    max_chars_per_line: int,
    context_prompt: str,
) -> List[Dict[str, str]]:
    serialized = json.dumps(script, ensure_ascii=False)
    prompt = f"""
You are a Japanese broadcast editor.
Rewrite the dialogue to fit a character budget while preserving meaning.

Rules:
- Keep language Japanese.
- Set every line speaker to A.
- Keep between {min_chars} and {target_chars} total characters in text fields.
- Never exceed {max_chars} total characters in text fields.
- Keep max {max_lines} lines.
- Keep each line under {max_chars_per_line} characters.
- Return ONLY JSON array: [{{"speaker":"A","text":"..."}}]

Context:
{context_prompt}

Input:
{serialized}
"""
    client = get_client()
    model_name = resolve_model_name()
    response = client.models.generate_content(model=model_name, contents=prompt)
    parsed = _extract_json_array(response.text or "")
    return _clean_script_items(parsed)


def _apply_char_budget_guardrail(
    script: List[Dict[str, str]],
    *,
    target_chars: int | None,
    min_chars: int,
    max_chars: int,
    context_prompt: str,
) -> List[Dict[str, str]]:
    budget = _char_budget_constraints(target_chars, min_chars=min_chars, max_chars=max_chars)
    actual = count_script_chars_text_only(script)
    if actual > int(budget["target_chars"]) or actual < int(budget["min_chars"]):
        try:
            rewritten = _rewrite_script_for_char_budget(
                script=script,
                target_chars=int(budget["target_chars"]),
                min_chars=int(budget["min_chars"]),
                max_chars=int(budget["max_chars"]),
                max_lines=int(budget["max_lines"]),
                max_chars_per_line=int(budget["max_chars_per_line"]),
                context_prompt=_truncate(context_prompt, 1200),
            )
            if rewritten:
                script = rewritten
        except Exception:
            pass

    return _truncate_script_to_char_budget(
        script,
        max_lines=int(budget["max_lines"]),
        max_chars_per_line=int(budget["max_chars_per_line"]),
        target_chars=int(budget["target_chars"]),
    )


def _generate_script_chunk(
    prompt: str,
    retry_prompt: str | None = None,
    *,
    target_chars: int | None = None,
    min_chars: int = 80,
    max_chars: int = 750,
) -> List[Dict[str, str]]:
    client = get_client()
    model_name = resolve_model_name()

    def _call(contents: str) -> List[Dict[str, str]]:
        response = client.models.generate_content(model=model_name, contents=contents)
        parsed = _extract_json_array(response.text or "")
        return _clean_script_items(parsed)

    first = _call(prompt)
    candidate = first
    if retry_prompt and first and _needs_japanese_rewrite(first):
        second = _call(retry_prompt)
        if second:
            candidate = second

    if candidate and _needs_japanese_rewrite(candidate):
        try:
            candidate = _rewrite_script_to_japanese(
                script=candidate,
                context_prompt=_truncate(prompt, 1200),
            )
        except Exception:
            pass

    if candidate:
        candidate = _apply_char_budget_guardrail(
            candidate,
            target_chars=target_chars,
            min_chars=min_chars,
            max_chars=max_chars,
            context_prompt=prompt,
        )
    if any(_contains_alphabet(item["text"]) for item in candidate):
        candidate = _rewrite_script_to_japanese(
        script=candidate,
        context_prompt=_truncate(prompt, 1200),
    )

    return candidate


def _agenda_to_text(agenda: dict[str, Any]) -> str:
    nodes = agenda.get("nodes", [])
    ordered_ids = agenda.get("ordered_node_ids", [])
    by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict)}
    ordered = []
    for node_id in ordered_ids:
        node = by_id.get(str(node_id))
        if not node:
            continue
        ordered.append(
            f"- {node.get('id')} | {node.get('title')} | role={node.get('role')} | note={node.get('note', '')}"
        )
    if not ordered:
        for idx, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                continue
            ordered.append(
                f"- n{idx} | {node.get('title')} | role={node.get('role', 'point')} | note={node.get('note', '')}"
            )
    return "\n".join(ordered)


def generate_intro(
    *,
    topic: str,
    agenda: dict[str, Any],
    source_context: str,
    target_chars: int | None = None,
    min_chars: int = 80,
    max_chars: int = 750,
) -> List[Dict[str, str]]:
    budget = _char_budget_constraints(target_chars, min_chars=min_chars, max_chars=max_chars)
    prompt = f"""
You are a professional Japanese broadcast writer.
Task: Generate intro only for a single-host podcast.
Topic: {topic}

Hard language rule:
- Output language MUST be Japanese.
- The output must NOT contain standalone A–Z alphabet sequences.
- All alphabet abbreviations MUST be converted to katakana reading.
- Do not leave AI, API, FAS, LLM etc. in Latin letters.
- Proper nouns may remain only if absolutely unavoidable.


Output rule:
- Return ONLY JSON array: [{{"speaker":"A","text":"..."}}]
- Keep total text characters between {int(budget["min_chars"])} and {int(budget["target_chars"])}.
- Keep under {int(budget["max_lines"])} lines.
- Keep each line under {int(budget["max_chars_per_line"])} chars.
- Keep this intro concise and informative (roughly 300-500 Japanese characters).
- Mention what causal points will be covered next.

Agenda (read aloud order):
{_agenda_to_text(agenda)}

Source context:
{_truncate(source_context, 3200)}
"""

    retry_prompt = (
        "Rewrite in Japanese only, keep it compact but concrete, and return JSON array only. "
        "Use speaker A only. "
        + prompt
    )

    try:
        return _generate_script_chunk(
            prompt,
            retry_prompt=retry_prompt,
            target_chars=int(budget["target_chars"]),
            min_chars=int(budget["min_chars"]),
            max_chars=int(budget["max_chars"]),
        )
    except Exception as e:
        print(f"[generator] intro generation failed: {e}")
        return [
            {"speaker": "A", "text": "今日は主題を因果関係で整理します。"},
            {"speaker": "A", "text": "背景から結果までのつながりを順に見ていきましょう。"},
        ]


def generate_body_section(
    *,
    topic: str,
    agenda_node: dict[str, str],
    prior_context: str,
    node_context: str,
    coverage_memory: dict[str, Any] | None = None,
    target_chars: int | None = None,
    min_chars: int = 100,
    max_chars: int = 750,
) -> List[Dict[str, str]]:
    node_title = agenda_node.get("title", "")
    node_role = agenda_node.get("role", "point")
    node_note = agenda_node.get("note", "")
    budget = _char_budget_constraints(target_chars, min_chars=min_chars, max_chars=max_chars)
    covered_points = list((coverage_memory or {}).get("covered_points") or [])
    anchor_keywords = _extract_anchor_keywords(node_title, node_note)

    prompt = f"""
You are writing one body section of a Japanese single-host podcast.
Topic: {topic}
Current node:
- title: {node_title}
- role: {node_role}
- note: {node_note}

Hard language rule:
- Output language MUST be Japanese.
- Do not write full English sentences.
- Proper nouns and unavoidable abbreviations may remain in Latin letters.
- Convert English words, abbreviations, and proper nouns to natural katakana reading as much as possible.
- Do not alter ordinary Japanese words into katakana.

Output rule:
- Return ONLY JSON array: [{{"speaker":"A","text":"..."}}]
- Keep total text characters between {int(budget["min_chars"])} and {int(budget["target_chars"])}.
- Keep under {int(budget["max_lines"])} lines.
- Keep each line under {int(budget["max_chars_per_line"])} chars.
- Build causally from prior context.
- No filler and no repetition.
- Include at least one concrete detail (fact, number, actor, or example).
- Do not repeat already-covered points.
- Include at least two new claims specific to this node.
- Do not introduce points that belong to other nodes.
- Do not pre-explain next node details.
- Avoid reusing the same final sentence pattern from previous section.
- Prefer a declarative ending.
- A question ending is allowed only when it clearly bridges to next section.
- Do not use question endings in consecutive sections.

Prior script tail:
{_truncate(prior_context, 1800)}

Covered points (DO NOT repeat):
{_truncate(" / ".join(covered_points), 1200)}

Current node context only:
{_truncate(node_context, 2200)}
"""
    retry_prompt = (
        "Rewrite this section in Japanese only, keep concrete details, fit the char budget, "
        "and stay strictly inside the current node scope. "
        "Return JSON array only. "
        + prompt
    )
    try:
        section = _generate_script_chunk(
            prompt,
            retry_prompt=retry_prompt,
            target_chars=int(budget["target_chars"]),
            min_chars=int(budget["min_chars"]),
            max_chars=int(budget["max_chars"]),
        )
        if _is_off_topic(section, anchor_keywords):
            strict_retry_prompt = (
                "Current node only. Do not introduce any other node. "
                "Use at least one anchor keyword from node title/note. "
                + prompt
            )
            retried = _generate_script_chunk(
                strict_retry_prompt,
                retry_prompt=None,
                target_chars=int(budget["target_chars"]),
                min_chars=int(budget["min_chars"]),
                max_chars=int(budget["max_chars"]),
            )
            if retried:
                section = retried
        return _stabilize_body_ending(
            section,
            prior_context,
            lookback_lines=3,
            max_recent_question_endings=0,
        )
    except Exception as e:
        print(f"[generator] section generation failed ({node_title}): {e}")
        return [
            {"speaker": "A", "text": f"{node_title}\u306f\u524d\u63d0\u3068\u7d50\u679c\u306e\u3064\u306a\u304c\u308a\u3067\u89e3\u304f\u3068\u7406\u89e3\u3057\u3084\u3059\u304f\u306a\u308a\u307e\u3059\u3002"},
            {"speaker": "A", "text": "\u5b9f\u52d9\u3067\u3069\u3053\u306b\u5f71\u97ff\u3059\u308b\u306e\u304b\u307e\u3067\u78ba\u8a8d\u3057\u307e\u3057\u3087\u3046\u3002"},
        ]


def summarize_section_delta(
    *,
    topic: str,
    agenda_node: dict[str, str],
    section_script: List[Dict[str, str]],
    covered_points: List[str],
) -> dict[str, Any]:
    section_text = _script_text(section_script)
    node_title = str(agenda_node.get("title") or "")
    if not section_text.strip():
        return {"new_points": [], "carry_open_question": ""}

    prompt = f"""
You are extracting novelty from one Japanese podcast section.
Topic: {topic}
Node title: {node_title}

Return ONLY JSON object:
{{
  "new_points": ["...", "..."],
  "carry_open_question": "..."
}}

Rules:
- new_points must be 1 or 2 short Japanese bullet-like strings.
- Do not repeat covered points.
- carry_open_question must be one unresolved question for next section.

Covered points:
{_truncate(" / ".join(covered_points), 1200)}

Section text:
{_truncate(section_text, 2500)}
"""
    try:
        client = get_client()
        model_name = resolve_model_name()
        response = client.models.generate_content(model=model_name, contents=prompt)
        parsed = _extract_json_object(response.text or "")
        points_raw = parsed.get("new_points", [])
        if not isinstance(points_raw, list):
            points_raw = []
        new_points: List[str] = []
        for item in points_raw[:2]:
            s = _normalize_point_text(str(item))
            if s:
                new_points.append(s)
        carry = _normalize_point_text(str(parsed.get("carry_open_question") or ""))
        return {"new_points": new_points, "carry_open_question": carry}
    except Exception:
        # Deterministic fallback: derive from first 2 sentence-like chunks.
        chunks = [c.strip() for c in re.split(r"[。！？\n]+", section_text) if c.strip()]
        fallback_points = [_normalize_point_text(x) for x in chunks[:2] if x.strip()]
        carry = ""
        if chunks:
            carry = f"{chunks[-1]}という点は次でどうなるでしょうか"
        return {"new_points": fallback_points[:2], "carry_open_question": carry}


def rewrite_section_to_reduce_overlap(
    *,
    topic: str,
    agenda_node: dict[str, str],
    section_script: List[Dict[str, str]],
    covered_points: List[str],
    target_chars: int | None,
    min_chars: int,
    max_chars: int,
) -> List[Dict[str, str]]:
    budget = _char_budget_constraints(target_chars, min_chars=min_chars, max_chars=max_chars)
    serialized = json.dumps(section_script, ensure_ascii=False)
    prompt = f"""
You are revising one Japanese podcast section to reduce overlap.
Topic: {topic}
Node: {agenda_node.get("title", "")}

Rules:
- Keep speaker A only.
- Keep language Japanese.
- Remove overlap with covered points.
- Add at least two new claims tied to this node.
- Keep total chars between {int(budget["min_chars"])} and {int(budget["target_chars"])}.
- Return ONLY JSON array: [{{"speaker":"A","text":"..."}}]

Covered points:
{_truncate(" / ".join(covered_points), 1500)}

Current section:
{serialized}
"""
    try:
        rewritten = _generate_script_chunk(
            prompt,
            retry_prompt=None,
            target_chars=int(budget["target_chars"]),
            min_chars=int(budget["min_chars"]),
            max_chars=int(budget["max_chars"]),
        )
        return rewritten or section_script
    except Exception:
        return section_script


def generate_conclusion(
    *,
    topic: str,
    agenda: dict[str, Any],
    full_script_context: str,
    source_context: str,
    coverage_memory: dict[str, Any] | None = None,
    target_chars: int | None = None,
    min_chars: int = 120,
    max_chars: int = 750,
) -> List[Dict[str, str]]:
    budget = _char_budget_constraints(target_chars, min_chars=min_chars, max_chars=max_chars)
    covered_points = list((coverage_memory or {}).get("covered_points") or [])
    open_questions = list((coverage_memory or {}).get("open_questions") or [])
    prompt = f"""
You are writing the final conclusion for a Japanese single-host podcast.
Topic: {topic}

Hard language rule:
- Output language MUST be Japanese.
- Do not write full English sentences.
- Convert English words, abbreviations, and proper nouns to natural katakana reading as much as possible.
- Do not alter ordinary Japanese words into katakana.

Output rule:
- Return ONLY JSON array: [{{"speaker":"A","text":"..."}}]
- Keep total text characters between {int(budget["min_chars"])} and {int(budget["target_chars"])}.
- Keep under {int(budget["max_lines"])} lines.
- Keep each line under {int(budget["max_chars_per_line"])} chars.
- Re-optimize based on the whole script.
- State one strongest causal insight and one practical implication.
- Avoid repeating already-covered points word-by-word.
- Final line must be a declarative sentence (not a question).

Agenda:
{_agenda_to_text(agenda)}

Covered points:
{_truncate(" / ".join(covered_points), 1200)}

Open questions:
{_truncate(" / ".join(open_questions), 600)}

Whole script so far:
{_truncate(full_script_context, 3200)}

Source context:
{_truncate(source_context, 2400)}
"""
    retry_prompt = (
        "Rewrite conclusion in Japanese only, actionable, and within char budget. "
        "Return JSON array only. "
        + prompt
    )
    try:
        conclusion = _generate_script_chunk(
            prompt,
            retry_prompt=retry_prompt,
            target_chars=int(budget["target_chars"]),
            min_chars=int(budget["min_chars"]),
            max_chars=int(budget["max_chars"]),
        )
        return _ensure_last_line_not_question(conclusion)
    except Exception as e:
        print(f"[generator] conclusion generation failed: {e}")
        return [
            {"speaker": "A", "text": "\u7d50\u8ad6\u3068\u3057\u3066\u3001\u4e3b\u984c\u306f\u500b\u5225\u8981\u7d20\u3067\u306f\u306a\u304f\u56e0\u679c\u306e\u9023\u9396\u3068\u3057\u3066\u6349\u3048\u308b\u3079\u304d\u3067\u3059\u3002"},
            {"speaker": "A", "text": "\u524d\u63d0\u3068\u5f71\u97ff\u3092\u5206\u3051\u3066\u898b\u308b\u3068\u3001\u5b9f\u52d9\u5224\u65ad\u306e\u7cbe\u5ea6\u304c\u4e0a\u304c\u308a\u307e\u3059\u3002"},
        ]


def generate_script_sequential(
    *,
    topic: str,
    agenda: dict[str, Any],
    source_texts: List[str],
    intro_override: List[Dict[str, str]] | None = None,
    on_chunk: Callable[[str, List[Dict[str, str]]], None] | None = None,
) -> List[Dict[str, str]]:
    context_blob = "\n\n---\n\n".join(source_texts[:5])
    script: List[Dict[str, str]] = []

    intro = intro_override or generate_intro(topic=topic, agenda=agenda, source_context=context_blob)
    if intro:
        script.extend(intro)
        if on_chunk:
            on_chunk("intro", intro)

    nodes = agenda.get("nodes", [])
    ordered_ids = [str(x) for x in agenda.get("ordered_node_ids", [])]
    node_by_id = {
        str(n.get("id")): {
            "id": str(n.get("id", "")),
            "title": str(n.get("title", "")),
            "role": str(n.get("role", "point")),
            "note": str(n.get("note", "")),
        }
        for n in nodes
        if isinstance(n, dict)
    }

    ordered_nodes: list[dict[str, str]] = []
    for node_id in ordered_ids:
        node = node_by_id.get(node_id)
        if node and node.get("title"):
            ordered_nodes.append(node)
    if not ordered_nodes:
        ordered_nodes = [n for n in node_by_id.values() if n.get("title")]

    for idx, node in enumerate(ordered_nodes, start=1):
        tail_lines = script[-10:]
        prior_context = "\n".join([f"{ln['speaker']}: {ln['text']}" for ln in tail_lines if ln.get("text")])
        section = generate_body_section(
            topic=topic,
            agenda_node=node,
            prior_context=prior_context,
            node_context=context_blob,
        )
        if section:
            script.extend(section)
            if on_chunk:
                on_chunk(f"body_{idx}", section)

    full_context = "\n".join([f"{ln['speaker']}: {ln['text']}" for ln in script])
    conclusion = generate_conclusion(
        topic=topic,
        agenda=agenda,
        full_script_context=full_context,
        source_context=context_blob,
    )
    if conclusion:
        script.extend(conclusion)
        if on_chunk:
            on_chunk("conclusion", conclusion)

    return script


def generate_script(full_texts: List[str]) -> List[Dict[str, str]]:
    if not full_texts:
        return []
    combined_text = "\n\n---\n\n".join(full_texts[:5])
    target_chars = max(600, int(os.environ.get("SCRIPT_TARGET_CHARS", "1000")))
    prompt = (
        f"""
You are a professional broadcast writer.
Create a podcast dialogue script in Japanese.

Hard language rule:
- Output language MUST be Japanese.
- Do not write full English sentences.
- Convert English words, abbreviations, and proper nouns to natural katakana reading as much as possible.
- Do not alter ordinary Japanese words into katakana.

Output:
- Return ONLY JSON array with keys: speaker(A), text.
- Keep total text characters around {target_chars}.

Source Texts:
"""
        + combined_text
    )
    retry_prompt = (
        "Rewrite in Japanese only and return JSON array only. "
        "Convert English/abbreviations/proper nouns to katakana reading. "
        + prompt
    )
    try:
        return _generate_script_chunk(
            prompt,
            retry_prompt=retry_prompt,
            target_chars=target_chars,
            min_chars=max(200, int(target_chars * 0.6)),
        )
    except Exception as e:
        print(f"[generator] legacy generation failed: {e}")
        return []

def _contains_alphabet(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", text))
