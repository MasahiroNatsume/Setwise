from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TtsProviderName = Literal["kokoro", "voicevox"]


@dataclass(frozen=True)
class TtsConfig:
    provider: TtsProviderName = "kokoro"
    voice: str | None = None
    speed: float | None = None
    lang: str = "ja"


@dataclass
class SynthesisStats:
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_ratio: float = 0.0
    line_timings_ready: bool = True
    timings_deferred: bool = False
    finalize_deferred: bool = False
    tts_provider_requested: str = "kokoro"
    tts_provider_used: str = "kokoro"
    tts_fallback_used: bool = False
    tts_fallback_reason: str | None = None
