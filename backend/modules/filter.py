import json
import re
from typing import Dict, List

from modules.llm import get_client, resolve_model_name


def _extract_json_array(text: str) -> list:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        raise ValueError("No JSON array found in model response.")
    return json.loads(match.group(0))


def pick_best_articles(
    articles: List[Dict],
    top_k: int = 3,
    topic: str = "",
) -> List[int]:
    """
    Select the best articles from a list using Gemini.
    """
    if not articles:
        return []

    articles_text = ""
    for i, article in enumerate(articles):
        articles_text += (
            f"[{i}] Title: {article.get('title')}\n"
            f"Snippet: {article.get('snippet')}\n\n"
        )

    prompt = f"""
You are an editor selecting sources for a Japanese causal-analysis podcast.
User topic: {topic or "not provided"}
Select the {top_k} most relevant and substantial articles from the list.
Focus on:
1. The article MUST be directly related to the user topic.
2. Avoid duplicates.
3. Prefer depth and analytical value.
4. Ignore articles that only loosely match keywords.

Return ONLY a JSON array of integers (article indices), for example: [0, 4, 12]

Articles:
{articles_text}
"""

    try:
        client = get_client()
        model_name = resolve_model_name()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        indices = _extract_json_array(response.text or "")
        valid_indices = [
            i for i in indices if isinstance(i, int) and 0 <= i < len(articles)
        ]
        return valid_indices[:top_k]
    except Exception as e:
        print(f"Error filtering articles: {e}")
        return list(range(min(len(articles), top_k)))
