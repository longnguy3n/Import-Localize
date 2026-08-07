from __future__ import annotations

import ast
from pathlib import Path


def test_fill_translate_data_columns_accepts_log_callback():
    path = Path(__file__).resolve().parents[1] / "src" / "import_localize" / "services" / "google_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    func = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "fill_translate_data_columns"
    )
    names = [arg.arg for arg in func.args.args] + [arg.arg for arg in func.args.kwonlyargs]
    assert "log_callback" in names
