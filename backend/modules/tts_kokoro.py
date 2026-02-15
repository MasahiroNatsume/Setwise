from __future__ import annotations

from typing import Any, Callable

from modules.tts_base import TtsProvider


class KokoroProvider(TtsProvider):
    name = "kokoro"

    def warmup(self) -> None:
        from modules import synthesizer

        synthesizer.init_kokoro()

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
        from modules import synthesizer

        return synthesizer.synthesize_audio_incremental(
            script,
            output_path,
            chunk_lines=chunk_lines,
            on_chunk=on_chunk,
            stats_out=stats_out,
            voice=voice,
            speed=speed,
            lang=lang,
        )
