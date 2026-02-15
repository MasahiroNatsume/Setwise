from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import unicodedata
from typing import Any, Callable

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

KOKORO = None
MISAKI_JA_G2P = None
_CACHE_PATH_INDEX: dict[str, str] = {}
_CACHE_LOCK = threading.Lock()


def _extract_phonemes(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, tuple):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if hasattr(item, "phonemes"):
                maybe = getattr(item, "phonemes")
                if isinstance(maybe, str) and maybe.strip():
                    return maybe.strip()
            if hasattr(item, "ipa"):
                maybe = getattr(item, "ipa")
                if isinstance(maybe, str) and maybe.strip():
                    return maybe.strip()
    if isinstance(value, dict):
        for key in ("phonemes", "ipa", "text"):
            maybe = value.get(key)
            if isinstance(maybe, str) and maybe.strip():
                return maybe.strip()
    if hasattr(value, "phonemes"):
        maybe = getattr(value, "phonemes")
        if isinstance(maybe, str) and maybe.strip():
            return maybe.strip()
    if hasattr(value, "ipa"):
        maybe = getattr(value, "ipa")
        if isinstance(maybe, str) and maybe.strip():
            return maybe.strip()
    return ""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _cache_enabled() -> bool:
    return _env_bool("TTS_CACHE_ENABLED", True)


def _cache_dir() -> str:
    configured = os.environ.get("TTS_CACHE_DIR", "audio_cache").strip() or "audio_cache"
    modules_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(modules_dir)
    path = configured if os.path.isabs(configured) else os.path.join(backend_dir, configured)
    os.makedirs(path, exist_ok=True)
    return path


def _normalize_text_for_cache(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    if _env_bool("TTS_CACHE_NORMALIZE_STRICT", True):
        normalized = re.sub(r"[\U00010000-\U0010ffff]", "", normalized)
        normalized = re.sub(r"[\u2600-\u27bf]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _cache_key(voice_name: str, speed: float, lang: str, text: str) -> str:
    normalized = _normalize_text_for_cache(text)
    raw = f"{voice_name}|{speed:.3f}|{lang}|{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path_for_key(key: str) -> str:
    root = _cache_dir()
    path = os.path.join(root, key[:2], key[2:4], f"{key}.wav")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _read_cached_samples(path: str) -> tuple[np.ndarray, int] | None:
    if not os.path.exists(path):
        return None
    try:
        samples, sr = sf.read(path, dtype="float32")
        if not isinstance(samples, np.ndarray):
            return None
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        return np.asarray(samples, dtype=np.float32), int(sr)
    except Exception:
        return None


def _write_cache_wav(path: str, samples: np.ndarray, sr: int) -> None:
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="cache_", suffix=".tmp", dir=os.path.dirname(path))
    os.close(fd)
    try:
        sf.write(tmp_path, samples, sr, subtype="PCM_16")
        if not os.path.exists(path):
            os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _init_misaki_ja_g2p():
    try:
        from misaki import ja as misaki_ja  # type: ignore
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", "unknown")
        raise RuntimeError(
            "misaki Japanese G2P dependencies are missing. "
            "Install with: pip install misaki fugashi[unidic-lite] jaconv mojimoji"
            f" (missing: {missing})"
        ) from e
    except Exception as e:
        raise RuntimeError(
            "misaki is required for Japanese G2P. "
            "Install with: pip install misaki fugashi[unidic-lite] jaconv mojimoji"
        ) from e

    if hasattr(misaki_ja, "JAG2P"):
        engine = misaki_ja.JAG2P()
        return lambda text: _extract_phonemes(engine(text))
    if hasattr(misaki_ja, "G2P"):
        engine = misaki_ja.G2P()
        return lambda text: _extract_phonemes(engine(text))
    if hasattr(misaki_ja, "g2p"):
        return lambda text: _extract_phonemes(misaki_ja.g2p(text))
    raise RuntimeError("misaki.ja API was found but no supported G2P entrypoint exists.")


def init_kokoro() -> None:
    global KOKORO, MISAKI_JA_G2P
    if KOKORO is None:
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(base_dir, "kokoro-data", "kokoro-v1.0.onnx")
            voices_path = os.path.join(base_dir, "kokoro-data", "voices-v1.0.bin")
            if not os.path.exists(model_path) or not os.path.exists(voices_path):
                print(f"Model files not found in {os.path.dirname(model_path)}")
                print("Please run 'python setup_kokoro.py' first.")
                return
            print(f"Initializing Kokoro ONNX from {model_path}...")
            KOKORO = Kokoro(model_path, voices_path)
            MISAKI_JA_G2P = _init_misaki_ja_g2p()
            print("Kokoro ONNX loaded.")
        except Exception as e:
            print(f"Failed to initialize Kokoro ONNX: {e}")


def _synthesize_line_samples(
    line: dict[str, Any],
    voice_map: dict[str, str],
    *,
    speed: float,
    lang: str,
) -> tuple[np.ndarray | None, int]:
    speaker = line.get("speaker", "A")
    text = line.get("text", "")
    if not text:
        return None, 0
    if text.startswith(f"{speaker}:"):
        text = text.replace(f"{speaker}:", "").strip()
    voice_name = voice_map.get(speaker, "jf_gongitsune")
    try:
        assert MISAKI_JA_G2P is not None and KOKORO is not None
        phonemes = MISAKI_JA_G2P(text)
        if not phonemes:
            raise RuntimeError("misaki returned empty phonemes")
        samples, sample_rate = KOKORO.create(
            phonemes,
            voice=voice_name,
            speed=speed,
            lang=lang,
            is_phonemes=True,
        )
        silence = np.zeros(int(sample_rate * 0.5), dtype=np.float32)
        merged = np.concatenate([samples.astype(np.float32), silence])
        return merged, int(sample_rate)
    except Exception as e:
        print(f"Error synthesizing line '{text}': {e}")
        return None, 0


def _get_or_synthesize_line_samples(
    line: dict[str, Any],
    voice_map: dict[str, str],
    *,
    speed: float,
    lang: str,
) -> tuple[np.ndarray | None, int, bool]:
    speaker = line.get("speaker", "A")
    text = line.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return None, 0, False
    if text.startswith(f"{speaker}:"):
        text = text.replace(f"{speaker}:", "").strip()
    voice_name = voice_map.get(speaker, "jf_gongitsune")

    if _cache_enabled():
        key = _cache_key(voice_name, speed, lang, text)
        with _CACHE_LOCK:
            cached_path = _CACHE_PATH_INDEX.get(key)
        if not cached_path:
            cached_path = _cache_path_for_key(key)
        cached = _read_cached_samples(cached_path)
        if cached is not None:
            with _CACHE_LOCK:
                _CACHE_PATH_INDEX[key] = cached_path
            return cached[0], cached[1], True

        samples, sample_rate = _synthesize_line_samples(
            line,
            voice_map,
            speed=speed,
            lang=lang,
        )
        if samples is None or sample_rate <= 0:
            return None, 0, False
        try:
            _write_cache_wav(cached_path, samples, sample_rate)
            with _CACHE_LOCK:
                _CACHE_PATH_INDEX[key] = cached_path
        except Exception as cache_error:
            print(f"[synthesizer] cache_write_failed path={cached_path} error={cache_error}")
        return samples, sample_rate, False

    samples, sample_rate = _synthesize_line_samples(
        line,
        voice_map,
        speed=speed,
        lang=lang,
    )
    if samples is None or sample_rate <= 0:
        return None, 0, False
    return samples, sample_rate, False


def _script_to_full_text(script: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for line in script:
        text = str(line.get("text", "")).strip()
        speaker = str(line.get("speaker", "")).strip()
        if not text:
            continue
        if speaker and text.startswith(f"{speaker}:"):
            text = text.replace(f"{speaker}:", "", 1).strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _get_or_synthesize_full_samples(
    *,
    full_text: str,
    voice_name: str,
    speed: float,
    lang: str,
) -> tuple[np.ndarray | None, int, bool]:
    if not full_text:
        return None, 0, False

    if _cache_enabled():
        key = _cache_key(voice_name, speed, lang, full_text)
        with _CACHE_LOCK:
            cached_path = _CACHE_PATH_INDEX.get(key)
        if not cached_path:
            cached_path = _cache_path_for_key(key)
        cached = _read_cached_samples(cached_path)
        if cached is not None:
            with _CACHE_LOCK:
                _CACHE_PATH_INDEX[key] = cached_path
            return cached[0], cached[1], True

    try:
        assert MISAKI_JA_G2P is not None and KOKORO is not None
        phonemes = MISAKI_JA_G2P(full_text)
        if not phonemes:
            raise RuntimeError("misaki returned empty phonemes")
        samples, sample_rate = KOKORO.create(
            phonemes,
            voice=voice_name,
            speed=speed,
            lang=lang,
            is_phonemes=True,
        )
        merged = samples.astype(np.float32)
        if _cache_enabled():
            key = _cache_key(voice_name, speed, lang, full_text)
            path = _cache_path_for_key(key)
            try:
                _write_cache_wav(path, merged, int(sample_rate))
                with _CACHE_LOCK:
                    _CACHE_PATH_INDEX[key] = path
            except Exception as cache_error:
                print(f"[synthesizer] cache_write_failed path={path} error={cache_error}")
        return merged, int(sample_rate), False
    except Exception as e:
        print(f"Error synthesizing full script: {e}")
        return None, 0, False


def synthesize_audio_incremental(
    script: list,
    output_path: str = "output.wav",
    *,
    chunk_lines: int = 3,
    on_chunk: Callable[[dict[str, Any]], None] | None = None,
    stats_out: dict[str, Any] | None = None,
    voice: str | None = None,
    speed: float | None = None,
    lang: str = "ja",
) -> dict[str, Any]:
    init_kokoro()
    if KOKORO is None or MISAKI_JA_G2P is None:
        print("TTS Engine not active. Skipping synthesis.")
        return {"cache_hits": 0, "cache_misses": 0, "cache_hit_ratio": 0.0}

    use_voice = (voice or "jf_alpha").strip() or "jf_alpha"
    use_speed = float(speed) if speed is not None else 1.0
    voice_map = {"A": use_voice}
    print("[synthesizer] speaker_mode=single")
    rendered_segments: list[np.ndarray] = []
    rendered_sr: int | None = None
    line_timings: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    cursor_samples = 0

    for line in script:
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        speaker = str(line.get("speaker", "A")).strip() or "A"
        samples, sr, from_cache = _get_or_synthesize_line_samples(
            line,
            voice_map,
            speed=use_speed,
            lang=lang,
        )
        if samples is None or sr <= 0:
            continue
        if rendered_sr is None:
            rendered_sr = int(sr)
        if int(sr) != int(rendered_sr):
            raise RuntimeError(f"Sample rate mismatch in Kokoro line synthesis: {sr} != {rendered_sr}")
        rendered_segments.append(samples.astype(np.float32))
        start_ms = int(round((cursor_samples / rendered_sr) * 1000.0))
        cursor_samples += len(samples)
        end_ms = int(round((cursor_samples / rendered_sr) * 1000.0))
        line_timings.append(
            {
                "speaker": speaker,
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )
        if from_cache:
            cache_hits += 1
        else:
            cache_misses += 1

    if rendered_segments and rendered_sr is not None:
        out_samples = np.concatenate(rendered_segments)
        sf.write(output_path, out_samples, rendered_sr, subtype="PCM_16")
        if on_chunk:
            on_chunk(
                {
                    "chunk_index": 1,
                    "lines": len(line_timings),
                    "seconds": round(float(len(out_samples)) / float(rendered_sr), 3),
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                }
            )

    total = cache_hits + cache_misses
    ratio = (cache_hits / total) if total else 0.0
    audio_ms = 0
    if rendered_segments and rendered_sr is not None:
        audio_ms = int(round((sum(len(seg) for seg in rendered_segments) / rendered_sr) * 1000.0))
    stats = {
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_ratio": round(ratio, 4),
        "line_timings": line_timings,
        "audio_ms": audio_ms,
    }
    if stats_out is not None:
        stats_out.update(stats)

    if os.path.exists(output_path):
        print(f"Audio saved to {output_path}")
    else:
        print("No audio generated.")
    print(f"[synthesizer] cache_stats hits={cache_hits} misses={cache_misses} ratio={round(ratio, 4)}")
    return stats


def synthesize_audio(script: list, output_path: str = "output.wav"):
    synthesize_audio_incremental(script, output_path)


def combine_audio_files(input_paths: list[str], output_path: str) -> None:
    segments: list[np.ndarray] = []
    out_sr: int | None = None
    for path in input_paths:
        if not os.path.exists(path):
            continue
        samples, sr = sf.read(path, dtype="float32")
        if samples is None:
            continue
        if isinstance(samples, np.ndarray) and samples.ndim > 1:
            samples = samples.mean(axis=1)
        if out_sr is None:
            out_sr = int(sr)
        if int(sr) != out_sr:
            raise RuntimeError(f"Sample rate mismatch while combining audio: {sr} != {out_sr}")
        segments.append(np.asarray(samples, dtype=np.float32))
    if not segments or out_sr is None:
        raise RuntimeError("No audio segments to combine.")
    merged = np.concatenate(segments)
    sf.write(output_path, merged, out_sr)
