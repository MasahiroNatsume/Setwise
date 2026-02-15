from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Any

from modules.llm import get_client, resolve_model_name

try:
    from ddgs import DDGS  # type: ignore
except Exception:
    from duckduckgo_search import DDGS  # type: ignore


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


def _truncate(value: str, max_len: int = 800) -> str:
    s = (value or "").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len].rstrip() + "..."


def _build_chapters_from_ordered_nodes(
    nodes: list[dict[str, str]],
    ordered_node_ids: list[str],
) -> list[dict[str, Any]]:
    by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict)}
    ordered: list[dict[str, str]] = []
    for node_id in ordered_node_ids:
        node = by_id.get(str(node_id))
        if node:
            ordered.append(node)
    if not ordered:
        ordered = list(nodes)

    chunks: list[list[dict[str, str]]] = []
    i = 0
    while i < len(ordered):
        chunks.append(ordered[i : i + 2])
        i += 2

    if len(chunks) >= 2 and len(chunks[-1]) == 1:
        chunks[-2].extend(chunks[-1])
        chunks.pop()

    chapters: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        node_ids = [str(n.get("id")) for n in chunk if n.get("id")]
        titles = [str(n.get("title") or "").strip() for n in chunk if n.get("title")]
        title_seed = " / ".join([t for t in titles[:2] if t]) or f"第{idx}章"
        chapters.append(
            {
                "chapter_id": f"c{idx}",
                "title": f"第{idx}章: {title_seed}",
                "node_ids": node_ids,
            }
        )
    return chapters


def run_pre_research(
    topic: str,
    *,
    region: str = "jp-jp",
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """
    Lightweight pre-research for agenda direction.
    Keeps result count intentionally small for speed.
    """
    queries = [
        f"{topic} とは",
        f"{topic} 原因 結果",
        f"{topic} メリット デメリット",
        f"{topic} 最新",
    ]

    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    per_query_cap = max(1, min(max_results, 5))

    try:
        with DDGS() as ddgs:
            for q in queries:
                try:
                    stream = ddgs.text(
                        q,
                        region=region,
                        timelimit="m",
                        max_results=per_query_cap,
                    )
                    if not stream:
                        continue
                    for item in stream:
                        url = str(item.get("href") or item.get("url") or "").strip()
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        collected.append(
                            {
                                "query": q,
                                "title": item.get("title", ""),
                                "url": url,
                                "snippet": _truncate(str(item.get("body") or "")),
                                "source": item.get("source", "web"),
                            }
                        )
                        if len(collected) >= max_results:
                            return collected
                except Exception as inner_e:
                    print(f"[planner] pre-research query failed: {q} error={inner_e}")
    except Exception as e:
        print(f"[planner] pre-research failed: {e}")

    return collected[:max_results]


def _normalize_agenda(agenda: dict[str, Any], topic: str) -> dict[str, Any]:
    nodes_raw = agenda.get("nodes")
    edges_raw = agenda.get("edges")
    if not isinstance(nodes_raw, list):
        nodes_raw = []
    if not isinstance(edges_raw, list):
        edges_raw = []

    nodes: list[dict[str, str]] = []
    for idx, node in enumerate(nodes_raw):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or f"n{idx+1}")
        title = str(node.get("title") or "").strip()
        role = str(node.get("role") or "point").strip().lower()
        note = str(node.get("note") or "").strip()
        if not title:
            continue
        nodes.append(
            {
                "id": node_id,
                "title": title,
                "role": role,
                "note": note,
            }
        )

    # Enforce node count range for stable downstream timing/UX.
    min_nodes = 5
    max_nodes = 7
    if len(nodes) > max_nodes:
        nodes = nodes[:max_nodes]

    if len(nodes) < min_nodes:
        pad_templates = [
            {"title": f"{topic}の背景", "role": "premise"},
            {"title": f"{topic}の主な要因", "role": "cause"},
            {"title": f"{topic}の影響", "role": "effect"},
            {"title": "実務での再評価", "role": "reframe"},
            {"title": "反対論と制約", "role": "conflict"},
        ]
        existing_titles = {n["title"] for n in nodes}
        next_id = len(nodes) + 1
        for tpl in pad_templates:
            if len(nodes) >= min_nodes:
                break
            if tpl["title"] in existing_titles:
                continue
            nodes.append(
                {
                    "id": f"n{next_id}",
                    "title": tpl["title"],
                    "role": tpl["role"],
                    "note": "",
                }
            )
            existing_titles.add(tpl["title"])
            next_id += 1

    node_ids = {n["id"] for n in nodes}
    edges: list[dict[str, str]] = []
    for edge in edges_raw:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from") or "").strip()
        dst = str(edge.get("to") or "").strip()
        if src in node_ids and dst in node_ids and src != dst:
            edges.append({"from": src, "to": dst})

    if not nodes:
        nodes = [
            {"id": "n1", "title": f"{topic}の背景", "role": "premise", "note": ""},
            {"id": "n2", "title": f"{topic}の主な要因", "role": "cause", "note": ""},
            {"id": "n3", "title": f"{topic}の影響", "role": "effect", "note": ""},
            {"id": "n4", "title": "実務での再評価", "role": "reframe", "note": ""},
        ]
        edges = [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
        ]

    ordered_ids = topological_order(nodes, edges)
    chapters = _build_chapters_from_ordered_nodes(nodes, ordered_ids)
    return {
        "topic": topic,
        "nodes": nodes,
        "edges": edges,
        "ordered_node_ids": ordered_ids,
        "chapters": chapters,
    }


def topological_order(nodes: list[dict[str, str]], edges: list[dict[str, str]]) -> list[str]:
    node_ids = [n["id"] for n in nodes]
    indeg: dict[str, int] = {nid: 0 for nid in node_ids}
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        src, dst = edge["from"], edge["to"]
        graph[src].append(dst)
        indeg[dst] = indeg.get(dst, 0) + 1
        indeg.setdefault(src, 0)

    q = deque([nid for nid in node_ids if indeg.get(nid, 0) == 0])
    ordered: list[str] = []
    while q:
        cur = q.popleft()
        ordered.append(cur)
        for nxt in graph.get(cur, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    if len(ordered) != len(node_ids):
        return node_ids
    return ordered


def build_causal_agenda(
    topic: str,
    pre_research_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build flexible agenda from causal graph (not fixed template).
    """
    bullets = []
    for i, item in enumerate(pre_research_items[:8], start=1):
        bullets.append(
            f"[{i}] title={item.get('title')} snippet={item.get('snippet')} query={item.get('query')}"
        )
    source_blob = "\n".join(bullets) if bullets else "(no pre-research snippets)"

    prompt = f"""
You are a Japanese podcast structure planner.
Topic: {topic}

Build an agenda as a causal graph, not a fixed template.
Rules:
- No fixed 3-point format.
- Use 5 to 7 nodes total.
- Nodes must represent logical roles such as cause/effect/constraint/side_effect/reframe.
- Focus on causal clarity and intellectual depth.
- Keep it suitable for a ~3 minute dialogue.
- Return ONLY JSON object with:
{{
  "nodes": [{{"id":"n1","title":"...","role":"cause|effect|constraint|side_effect|premise|reframe|conflict","note":"..."}}],
  "edges": [{{"from":"n1","to":"n2"}}]
}}

Pre-research snippets:
{source_blob}
"""

    try:
        client = get_client()
        model_name = resolve_model_name()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        parsed = _extract_json_object(response.text or "")
        return _normalize_agenda(parsed, topic)
    except Exception as e:
        print(f"[planner] agenda generation failed: {e}")
        return _normalize_agenda({}, topic)
