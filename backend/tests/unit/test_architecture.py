"""Enforces the dependency rules from AGENTS.md / docs/DECISIONS.md (D2)."""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"
FORBIDDEN_FOR_ENGINE = ("app.api", "app.db", "app.services")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_engine_never_imports_api_db_or_services():
    violations = []
    for path in (APP_DIR / "engine").rglob("*.py"):
        for name in _imports(path):
            if name.startswith(FORBIDDEN_FOR_ENGINE):
                violations.append(f"{path.relative_to(APP_DIR)} imports {name}")
    assert not violations, "engine must stay isolated: " + "; ".join(violations)


def test_schemas_import_nothing_from_other_app_layers():
    allowed_prefix = "app.schemas"
    violations = []
    for path in (APP_DIR / "schemas").rglob("*.py"):
        for name in _imports(path):
            if name.startswith("app.") and not name.startswith(allowed_prefix):
                violations.append(f"{path.relative_to(APP_DIR)} imports {name}")
    assert not violations, "; ".join(violations)


_LAZY_FRAMEWORK_MODULES = ("langchain_backend.py", "builder.py")


def test_only_designated_modules_import_langchain_or_langgraph():
    """Frameworks stay behind our interfaces: langchain_backend.py and graph/builder.py only."""
    violations = []
    for path in (APP_DIR / "engine").rglob("*.py"):
        if path.name in _LAZY_FRAMEWORK_MODULES:
            continue
        for name in _imports(path):
            if name.startswith(("langchain", "langchain_", "langgraph")):
                violations.append(f"{path.relative_to(APP_DIR)} imports {name}")
    assert not violations, "; ".join(violations)


def test_framework_modules_import_lazily():
    """Importing the engine must not require LangChain or LangGraph to be installed."""
    paths = [
        APP_DIR / "engine" / "providers" / "langchain_backend.py",
        APP_DIR / "engine" / "graph" / "builder.py",
    ]
    for path in paths:
        _assert_no_module_level_framework_imports(path)


def _assert_no_module_level_framework_imports(path):
    tree = ast.parse(path.read_text())
    for node in tree.body:  # module level only
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        assert not any(n.startswith(("langchain", "langgraph")) for n in names), names


def _forbidden_imports(folder: str, prefixes: tuple[str, ...]) -> list[str]:
    found = []
    for path in (APP_DIR / folder).rglob("*.py"):
        for name in _imports(path):
            if name.startswith(prefixes):
                found.append(f"{path.relative_to(APP_DIR)} imports {name}")
    return found


def test_db_depends_on_schemas_only():
    assert not _forbidden_imports("db", ("app.engine", "app.services", "app.api"))


def test_services_do_not_import_api_or_sql():
    assert not _forbidden_imports("services", ("app.api", "app.db.sql", "sqlalchemy", "fastapi"))