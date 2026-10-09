"""Hexagonal dependency rule, enforced by static import scanning."""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "eventssound"
PROJECT = "eventssound"
FRAMEWORKS = {"fastapi", "sqlalchemy", "pydantic_settings", "alembic"}

FORBIDDEN: dict[str, set[str]] = {
    "domain": {
        f"{PROJECT}.application",
        f"{PROJECT}.adapters",
        f"{PROJECT}.entrypoints",
        f"{PROJECT}.config",
        *FRAMEWORKS,
    },
    "application": {f"{PROJECT}.adapters", f"{PROJECT}.entrypoints"},
    "adapters": {f"{PROJECT}.entrypoints"},
}


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def is_forbidden(module: str, forbidden: set[str]) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in forbidden)


def find_violations(layer_dir: Path, forbidden: set[str]) -> list[str]:
    violations: list[str] = []
    for path in sorted(layer_dir.rglob("*.py")):
        for module in sorted(imported_modules(path.read_text(encoding="utf-8"))):
            if is_forbidden(module, forbidden):
                violations.append(f"{path.relative_to(layer_dir).as_posix()} imports {module}")
    return violations


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_respects_dependency_rule(layer: str) -> None:
    assert find_violations(PACKAGE_ROOT / layer, FORBIDDEN[layer]) == []


def test_violation_is_detected_and_names_module_and_import(tmp_path: Path) -> None:
    (tmp_path / "leaky.py").write_text("import sqlalchemy\n", encoding="utf-8")
    (tmp_path / "clean.py").write_text("import dataclasses\n", encoding="utf-8")

    violations = find_violations(tmp_path, FORBIDDEN["domain"])

    assert len(violations) == 1
    assert "leaky.py" in violations[0]
    assert "sqlalchemy" in violations[0]


def test_from_imports_of_inner_layers_are_detected(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "from eventssound.adapters.db.session import Base\n", encoding="utf-8"
    )

    violations = find_violations(tmp_path, FORBIDDEN["application"])

    assert violations and "eventssound.adapters.db.session" in violations[0]
