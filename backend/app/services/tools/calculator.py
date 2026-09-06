import ast
import operator

_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return _ALLOWED_OPERATORS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_eval_node(node.operand))

    raise ValueError(f"Operasi tidak diizinkan dalam ekspresi: {ast.dump(node)}")


def calculate(expression: str) -> str:
    """Hitung hasil dari ekspresi matematika sederhana.

    Mendukung operasi: tambah (+), kurang (-), kali (*), bagi (/),
    pangkat (**), modulo (%), dan tanda kurung untuk mengatur urutan
    operasi. Contoh input: "12 * (3 + 4)", "2 ** 10", "100 / 3".

    Args:
        expression: Ekspresi matematika dalam bentuk string.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
    except ZeroDivisionError:
        return "Error: pembagian dengan nol tidak didefinisikan."
    except Exception as exc:
        return f"Error: tidak bisa menghitung '{expression}' ({exc})"

    return str(result)
