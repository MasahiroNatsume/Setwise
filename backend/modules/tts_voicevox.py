from __future__ import annotations

import hashlib
import io
import os
import threading
from collections import OrderedDict
from typing import Any, Callable

import numpy as np
import requests
import soundfile as sf

from modules.tts_base import TtsProvider


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


def _line_text(line: dict[str, Any]) -> str:
    speaker = str(line.get("speaker", "A")).strip()
    text = str(line.get("text", "")).strip()
    if speaker and text.startswith(f"{speaker}:"):
        text = text.replace(f"{speaker}:", "", 1).strip()
    return text


def _normalized_text_for_cache(text: str) -> str:
    return "\n".join([ln.rstrip() for ln in text.splitlines()]).strip()


def _speaker_from_voice(voice: str | None, default_speaker: int) -> int:
    if not voice:
        return default_speaker
    try:
        return int(voice)
    except Exception:
        return default_speaker


class VoiceVoxProvider(TtsProvider):
    name = "voicevox"

    def __init__(self) -> None:
        self.base_url = (os.environ.get("VOICEVOX_BASE_URL", "http://127.0.0.1:50021").strip() or "http://127.0.0.1:50021").rstrip("/")
        self.default_speaker = _env_int("VOICEVOX_DEFAULT_SPEAKER", 3)
        self.connect_timeout = _env_float("VOICEVOX_CONNECT_TIMEOUT_SECONDS", 5.0)
        self.request_timeout = _env_float("VOICEVOX_REQUEST_TIMEOUT_SECONDS", 20.0)
        self.cache_size = _env_int("VOICEVOX_CACHE_SIZE", 256)
        self.cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "audio_cache",
            "voicevox",
        )
        os.makedirs(self.cache_dir, exist_ok=True)
        self._cache_lock = threading.Lock()
        self._memory_cache: OrderedDict[str, tuple[np.ndarray, int]] = OrderedDict()
        self.engine_version = "unknown"

    def warmup(self) -> None:
        response = requests.get(
            f"{self.base_url}/version",
            timeout=(self.connect_timeout, self.request_timeout),
        )
        response.raise_for_status()
        try:
            self.engine_version = str(response.text or "").strip() or "unknown"
        except Exception:
            self.engine_version = "unknown"

    def _cache_key(self, *, speaker: int, speed: float, text: str) -> str:
        normalized = _normalized_text_for_cache(text)
        raw = f"voicevox|{self.engine_version}|{speaker}|{speed:.3f}|{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> tuple[np.ndarray, int] | None:
        with self._cache_lock:
            cached = self._memory_cache.get(key)
            if cached is not None:
                self._memory_cache.move_to_end(key)
                return np.copy(cached[0]), int(cached[1])

        cache_path = os.path.join(self.cache_dir, f"{key}.wav")
        if not os.path.exists(cache_path):
            return None
        try:
            samples, sr = sf.read(cache_path, dtype="float32")
            if isinstance(samples, np.ndarray) and samples.ndim > 1:
                samples = samples.mean(axis=1)
            arr = np.asarray(samples, dtype=np.float32)
            self._cache_put(key, arr, int(sr), persist=False)
            return arr, int(sr)
        except Exception:
            return None

    def _cache_put(self, key: str, samples: np.ndarray, sr: int, *, persist: bool = True) -> None:
        with self._cache_lock:
            self._memory_cache[key] = (np.copy(samples), int(sr))
            self._memory_cache.move_to_end(key)
            while len(self._memory_cache) > max(1, self.cache_size):
                self._memory_cache.popitem(last=False)
        if not persist:
            return
        cache_path = os.path.join(self.cache_dir, f"{key}.wav")
        try:
            sf.write(cache_path, samples, sr, subtype="PCM_16")
        except Exception:
            return

    def _synthesize_text(
        self,
        *,
        text: str,
        speaker: int,
        speed: float,
    ) -> tuple[np.ndarray, int]:
        text = text.strip()
        if not text:
            raise RuntimeError("VOICEVOX text is empty.")
        q = requests.post(
            f"{self.base_url}/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=(self.connect_timeout, self.request_timeout),
        )
        q.raise_for_status()
        query = q.json()
        query["speedScale"] = max(0.5, min(2.0, float(speed)))

        s = requests.post(
            f"{self.base_url}/synthesis",
            params={"speaker": speaker},
            json=query,
            timeout=(self.connect_timeout, self.request_timeout),
        )
        s.raise_for_status()
        samples, sr = sf.read(io.BytesIO(s.content), dtype="float32")
        if isinstance(samples, np.ndarray) and samples.ndim > 1:
            samples = samples.mean(axis=1)
        return np.asarray(samples, dtype=np.float32), int(sr)

    def synthesize_script(
        self,
        script: list[dict[str, Any]],
        output_path: str,
        *,
        chunk_lines: int = 3,
        on_chunk: Callable[[dict[str, Any]], None] | None = None,
        stats_out: dict[str, Any] | None = None,
        voice: str | None = None,
        speed: float | None = None,
        lang: str = "ja",
    ) -> dict[str, Any]:
        _ = chunk_lines, lang
        speaker = _speaker_from_voice(voice, self.default_speaker)
        use_speed = 1.0 if speed is None else float(speed)
        line_texts: list[str] = []
        line_speakers: list[str] = []

        for line in script:
            text = _line_text(line)
            if not text:
                continue
            line_texts.append(text)
            line_speakers.append(str(line.get("speaker", "A")).strip() or "A")

        if not line_texts:
            raise RuntimeError("VOICEVOX did not produce audio segments.")

        section_text = "\n".join(line_texts)
        cache_key = self._cache_key(speaker=speaker, speed=use_speed, text=section_text)
        cached = self._cache_get(cache_key)
        cache_hits = 0
        cache_misses = 0
        if cached is not None:
            merged, out_sr = cached
            cache_hits = 1
        else:
            cache_misses = 1
            merged, out_sr = self._synthesize_text(
                text=section_text,
                speaker=speaker,
                speed=use_speed,
            )
            self._cache_put(cache_key, merged, out_sr, persist=True)

        if isinstance(merged, np.ndarray) and merged.ndim > 1:
            merged = merged.mean(axis=1)
        merged = np.asarray(merged, dtype=np.float32)
        sf.write(output_path, merged, out_sr, subtype="PCM_16")
        if on_chunk:
            on_chunk(
                {
                    "chunk_index": 1,
                    "lines": len(line_texts),
                    "seconds": round(float(len(merged)) / float(out_sr), 3),
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                }
            )

        timings_second_pass = str(os.environ.get("VOICEVOX_TIMINGS_SECOND_PASS", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        line_timings: list[dict[str, Any]] = []
        timings_ready = not line_texts
        timings_deferred = False
        if line_texts and timings_second_pass:
            cursor_samples = 0
            timings_ready = True
            for idx, text in enumerate(line_texts):
                try:
                    line_samples, line_sr = self._synthesize_text(
                        text=text,
                        speaker=speaker,
                        speed=use_speed,
                    )
                    if int(line_sr) != int(out_sr):
                        raise RuntimeError("VOICEVOX line timing sample rate mismatch.")
                    start_ms = int(round((cursor_samples / line_sr) * 1000.0))
                    cursor_samples += len(line_samples)
                    end_ms = int(round((cursor_samples / line_sr) * 1000.0))
                    line_timings.append(
                        {
                            "speaker": line_speakers[idx],
                            "text": text,
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                        }
                    )
                except Exception:
                    timings_ready = False
                    break
        elif line_texts:
            timings_ready = False
            timings_deferred = True

        audio_ms = int(round((float(len(merged)) / float(out_sr)) * 1000.0)) if out_sr > 0 else 0
        stats = {
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_ratio": round(cache_hits / max(cache_hits + cache_misses, 1), 4),
            "line_timings": line_timings,
            "audio_ms": audio_ms,
            "line_timings_ready": timings_ready,
            "timings_deferred": timings_deferred,
        }
        if stats_out is not None:
            stats_out.update(stats)
        return stats
