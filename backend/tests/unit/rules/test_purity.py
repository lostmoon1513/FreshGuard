"""The rules package must stay pure: no I/O, no network, no clock, no randomness, no LLM."""

import ast
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[3] / "app" / "engine" / "rules"
FORBIDDEN_IMPORT_ROOTS = {
    "httpx", "requests", "aiohttp", "urllib3", "socket", "subprocess", "os", "pathlib",
    "random", "time", "asyncio", "sqlalchemy", "langgraph", "langchain", "logging",
    "app.config", "app.logging",
}  # fmt: skip
FORBIDDEN_CALLS = {"now", "utcnow", "today", "time", "monotonic", "open", "print", "getenv"}


def _rule_files():
    files = sorted(RULES_DIR.glob("*.py"))
    assert len(files) >= 5, "rules package not found"
    return files


def test_rules_only_depend_on_schemas_and_each_other():
    bad = []
    for path in _rule_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if name in FORBIDDEN_IMPORT_ROOTS or root in FORBIDDEN_IMPORT_ROOTS:
                    bad.append(f"{path.name}: imports {name}")
                if name.startswith("app.") and not name.startswith(
                    ("app.schemas", "app.engine.rules")
                ):
                    bad.append(f"{path.name}: imports {name}")
    assert not bad, "; ".join(bad)


def test_rules_never_read_the_clock_or_do_io():
    bad = []
    for path in _rule_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in FORBIDDEN_CALLS:
                    bad.append(f"{path.name}:{node.lineno} calls {name}()")
    assert not bad, "; ".join(bad)