from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from types import CoroutineType
from typing import Any, ParamSpec, TypeVar

from app.core.logging_config import log_event

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

    Log lewat `log_event` (bukan `logger.info("op=%s ...", ...)` format string)
    supaya konsisten JSON dengan event lain di seluruh codebase (`llm_call`,
    `memory_retrieval`, `task_execution_finished`, dst) -- semua bisa
    di-`jq '.data.xxx'` dengan cara yang sama, bukan dua "dialek" log berbeda.

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
                log_event(
                    logger,
                    "operation_finished",
                    operation=operation,
                    duration_ms=round(duration_ms, 1),
                )

        return wrapper

    return decorator
