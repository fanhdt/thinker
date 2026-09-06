from app.services.tools.calculator import calculate


def test_calculate_basic_arithmetic():
    assert calculate("2 + 2") == "4"
    assert calculate("10 - 3") == "7"
    assert calculate("6 * 7") == "42"


def test_calculate_respects_order_of_operations():
    assert calculate("2 + 3 * 4") == "14"
    assert calculate("(2 + 3) * 4") == "20"


def test_calculate_division():
    assert calculate("10/4") == "2.5"


def test_calculate_division_by_zerp_returns_error_not_crash():
    result = calculate("1/0")
    assert "Error" in result


def test_calculate_power_and_modulo():
    assert calculate("2 ** 10") == "1024"
    assert calculate("10 % 3") == "1"


def test_calculate_rejects_function_calls():
    result = calculate("__import__('os').system('echo hacked')")
    assert "Error" in result


def test_calculate_rejects_name_references():
    result = calculate("os.getcwd()")
    assert "Error" in result
