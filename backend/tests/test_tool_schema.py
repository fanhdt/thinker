from app.services.llm_providers.tool_schema import function_to_openai_schema


def sample_tool(query: str, limit: int = 5) -> str:
    """Cari sesuatu berdasarkan query.

    Args:
        query: Kata kunci pencarian.
        limit: Batas jumlah hasil.
    """
    return "hasil"


def test_function_to_openai_schema_maps_types_correctly():
    schema = function_to_openai_schema(sample_tool)

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "sample_tool"
    assert schema["function"]["description"] == "Cari sesuatu berdasarkan query."

    properties = schema["function"]["parameters"]["properties"]
    assert properties["query"]["type"] == "string"
    assert properties["limit"]["type"] == "integer"


def test_function_to_openai_schema_marks_only_no_default_params_as_required():
    schema = function_to_openai_schema(sample_tool)

    required = schema["function"]["parameters"]["required"]
    assert required == ["query"]
    assert "limit" not in required
