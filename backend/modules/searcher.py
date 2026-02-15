from typing import List

try:
    from ddgs import DDGS  # type: ignore
except Exception:
    from duckduckgo_search import DDGS  # type: ignore

def get_search_suggestions(keyword: str, max_suggestions: int = 5) -> list[str]:
    suggestions = []
    try:
        with DDGS() as ddgs:
            results = ddgs.suggestions(keyword)
            for r in results:
                phrase = r.get("phrase")
                if phrase and phrase.lower() != keyword.lower():
                    suggestions.append(phrase)
                if len(suggestions) >= max_suggestions:
                    break
    except Exception as e:
        print(f"Suggestion error: {e}")

    return suggestions


def _normalize_item(raw: dict, source_type: str) -> dict:
    return {
        "title": raw.get("title"),
        "url": raw.get("href") or raw.get("url"),
        "snippet": raw.get("body"),
        "date": raw.get("date"),
        "source": raw.get("source") or "web",
    }


def get_initial_news(
    keyword: str, limit: int = 15, region: str = "jp-jp", timelimit: str = "d"
) -> List[dict]:
    """
    Search candidate articles using DuckDuckGo with fallbacks.
    """

    # ⭐ ここに置く（検索より前）
    suggestions = get_search_suggestions(keyword)
    if suggestions:
        keyword = f"{keyword} {suggestions[0]}"
        print(f"Using suggestion: {keyword}")

    results: list[dict] = []
    seen_urls: set[str] = set()

    attempts = [
        ("text", {"region": region, "timelimit": "w"}),
        ("text", {"region": "wt-wt", "timelimit": "m"}),
    ]

    try:
        with DDGS() as ddgs:
            for source_type, opts in attempts:
                if len(results) >= limit:
                    break
                try:
                    stream = ddgs.text(
                        keyword,
                        region=opts["region"],
                        timelimit=opts["timelimit"],
                        max_results=limit,
                    )

                    if not stream:
                        continue

                    for r in stream:
                        item = _normalize_item(r, source_type)
                        url = item.get("url")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        results.append(item)
                        if len(results) >= limit:
                            break
                except Exception as inner_e:
                    print(f"Search attempt failed ({source_type}, {opts}): {inner_e}")
    except Exception as e:
        print(f"Error during DuckDuckGo search: {e}")

    return results

