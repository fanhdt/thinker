import json
import logging

from app.core.logging_config import JsonFormatter, log_event


def _make_record(logger_name: str = "test") -> logging.LogRecord:
    return logging.LogRecord(
        name=logger_name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="something_happened",
        args=(),
        exc_info=None,
    )


def test_json_formatter_is_actually_used_by_the_class():
    """Regresi utama: `format` sempat ke-dedent sampai keluar dari class
    `JsonFormatter`, sehingga class itu diam-diam jatuh balik ke
    `logging.Formatter.format` bawaan (output teks polos, bukan JSON) --
    tidak ada error, tidak ada warning, cuma output log yang jadi tidak
    terstruktur sama sekali. Assert paling langsung: method `format` harus
    benar-benar didefinisikan DI DALAM class ini, bukan di module level."""
    assert "format" in JsonFormatter.__dict__


def test_json_formatter_produces_valid_parseable_json():
    formatter = JsonFormatter()
    record = _make_record()

    output = formatter.format(record)
    parsed = json.loads(output)  # akan raise kalau bukan JSON valid

    assert parsed["message"] == "something_happened"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test"
    assert "timestamp" in parsed


def test_json_formatter_includes_event_data_under_data_key():
    formatter = JsonFormatter()
    record = _make_record()
    record.event_data = {"method": "create_plan", "duration_ms": 842.1, "success": True}

    parsed = json.loads(formatter.format(record))

    assert parsed["data"] == {"method": "create_plan", "duration_ms": 842.1, "success": True}


def test_log_event_attaches_fields_as_event_data(caplog):
    logger = logging.getLogger("test.log_event")

    with caplog.at_level("INFO"):
        log_event(logger, "llm_call", method="chat", duration_ms=12.3, success=True)

    record = caplog.records[-1]
    assert record.message == "llm_call"
    assert record.event_data == {"method": "chat", "duration_ms": 12.3, "success": True}
