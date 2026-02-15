from __future__ import annotations

import os
from typing import Any, Callable

from modules.tts_base import combine_audio_files
from modules.tts_kokoro import KokoroProvider
from modules.tts_types import TtsConfig
from modules.tts_voicevox import VoiceVoxProvider


_KOKORO = KokoroProvider()
_VOICEVOX = VoiceVoxProvider()


def get_default_provider() -> str:
    value = os.environ.get("TTS_DEFAULT_PROVIDER", "kokoro").strip().lower()
    return value if value in {"kokoro", "voicevox"} else "kokoro"


def get_tts_provider(name: str):
    value = (name or "").strip().lower()
    if value == "voicevox":
        return _VOICEVOX
    return _KOKORO


def get_default_voice(provider: str) -> str:
    value = (provider or "").strip().lower()
    if value == "voicevox":
        return str(getattr(_VOICEVOX, "default_speaker", 3))
    return "jf_alpha"


def fallback_enabled() -> bool:
    raw = os.environ.get("TTS_FALLBACK_TO_KOKORO", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def warmup_on_startup() -> None:
    _KOKORO.warmup()
    raw = os.environ.get("VOICEVOX_WARMUP_ENABLED", "true").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        try:
            _VOICEVOX.warmup()
        except Exception as exc:
            print(f"[tts_router] voicevox warmup skipped error={exc}")


def synthesize_script(
    *,
    script: list[dict[str, Any]],
    output_path: str,
    config: TtsConfig,
    chunk_lines: int = 3,
    on_chunk: Callable[[dict[str, Any]], None] | None = None,
    stats_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested = (config.provider or "kokoro").lower()
    provider = get_tts_provider(requested)
    result: dict[str, Any] = {}
    requested_voice = (config.voice or "").strip() or get_default_voice(requested)

    result = provider.synthesize_script(
        script,
        output_path,
        chunk_lines=chunk_lines,
        on_chunk=on_chunk,
        stats_out=stats_out,
        voice=config.voice,
        speed=config.speed,
        lang=config.lang,
    )
    used = provider.name

    used_voice = requested_voice if used == requested else get_default_voice(used)
    result["tts_provider_requested"] = requested
    result["tts_provider_used"] = used
    result["tts_fallback_used"] = False
    result["tts_voice_requested"] = requested_voice
    result["tts_voice_used"] = used_voice
    if stats_out is not None:
        stats_out.update(result)
    return result


__all__ = [
    "TtsConfig",
    "combine_audio_files",
    "fallback_enabled",
    "get_default_provider",
    "get_default_voice",
    "get_tts_provider",
    "synthesize_script",
    "warmup_on_startup",
]
