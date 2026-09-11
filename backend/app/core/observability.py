from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from types import CoroutineType
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger("thinker.observability")

P = ParamSpec("P")
R = TypeVar("R")


def log_duration(
    operation: str,
) -> Callable[[Callable[P, CoroutineType[Any, Any, R]]], Callable[P, CoroutineType[Any, Any, R]]]:
    """Decorator untuk fungsi/method async -- log durasi eksekusinya (milidetik)
    setelah selesai, baik sukses maupun gagal. Dipakai di titik-titik yang
    memanggil Gemini API supaya kita tahu bagian mana yang lambat tanpa harus
    menebak atau menambah timer manual satu-satu di tiap fungsi (itu akan
    duplikat 6-7 kali dan gampang lupa dipasang di fungsi baru).

    Catatan tipe: anotasi memakai `types.CoroutineType`, bukan `typing.Coroutine`
    yang lebih umum tapi abstrak -- `CoroutineType` adalah tipe konkret yang
    BENAR-BENAR dihasilkan saat memanggil fungsi `async def`. Ini penting supaya
    method yang didekorasi tetap cocok dengan Protocol seperti MessagePipelineLLM
    (yang method-nya dideklarasikan `async def`, sehingga pyright menuntut tipe
    balik persis CoroutineType, bukan Coroutine abstrak yang dianggap berbeda).
    """

    def decorator(
        func: Callable[P, CoroutineType[Any, Any, R]],
    ) -> Callable[P, CoroutineType[Any, Any, R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.monotonic()
            try:
                return await func(*args, **kwargs)
            finally:
                duration_ms = (time.monotonic() - start) * 1000
                logger.info("op=%s duration_ms=%.1f", operation, duration_ms)

        return wrapper

    return decorator


def log_token_usage(operation: str, response: Any) -> None:
    """Log jumlah token dari response Gemini, kalau SDK menyediakannya.
    `usage_metadata` bisa None (mis. saat error partial), jadi semua field
    diakses defensif -- jangan sampai logging observability sendiri yang
    menyebabkan crash.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return

    logger.info(
        "op=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        operation,
        usage.prompt_token_count,
        usage.candidates_token_count,
        usage.total_token_count,
    )
