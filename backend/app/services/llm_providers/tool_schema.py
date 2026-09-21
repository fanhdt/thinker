"""Konversi tool Python biasa (di `app.services.tools.registry.AVAILABLE_TOOLS`)
menjadi JSON schema gaya OpenAI function-calling.

Gemini SDK bisa introspeksi fungsi Python langsung (automatic function
calling) -- OpenAI-compatible API butuh JSON schema eksplisit di setiap
request. Ini generator MINIMAL, cukup untuk tool yang ada sekarang
(parameter str/int/float/bool dengan default sederhana), bukan
general-purpose JSON-schema generator.
"""

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def function_to_openai_schema(func: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(func)
    hints = get_type_hints(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        json_type = _TYPE_MAP.get(hints.get(name, str), "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    description = (func.__doc__ or "").strip().split("\n")[0]

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
