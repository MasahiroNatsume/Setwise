from __future__ import annotations

import urllib.error
import urllib.request

import trafilatura


def _download_html(url: str, timeout_seconds: float) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        content_type = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read()
    return raw.decode(content_type, errors="ignore")


def extract_full_text(url: str, timeout_seconds: float = 12.0) -> str:
    """
    Extract the main content from a URL using Trafilatura.
    
    Args:
        url (str): The URL to extract from.
        
    Returns:
        str: The extracted text content, or empty string on failure.
    """
    try:
        html = _download_html(url, timeout_seconds=max(1.0, float(timeout_seconds)))
        if html:
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
            )
            if text:
                return text
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"Extractor timeout/network error for {url}: {e}")
    except Exception as e:
        print(f"Error extracting text from {url}: {e}")
    
    return ""
