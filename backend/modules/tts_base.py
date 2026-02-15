from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

import numpy as np
import soundfile as sf


class TtsProvider(ABC):
    name: str

    @abstractmethod
    def warmup(self) -> None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError


def combine_audio_files(input_paths: list[str], output_path: str) -> None:
    segments: list[np.ndarray] = []
    out_sr: int | None = None
    for path in input_paths:
        try:
            samples, sr = sf.read(path, dtype="float32")
        except Exception:
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
