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


def imported_modules(source: str, package: str) -> set[str]:
    """Return absolute module names imported by `source`.

    `package` is the dotted package the source file lives in; it is used to
    resolve relative imports (`from .x import y`, `from .. import z`).
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                parts = package.split(".")
                anchor = parts[: len(parts) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            if not base:
                continue
            modules.add(base)
            # `from pkg import name` may import the submodule `pkg.name`.
            modules.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return modules


def is_forbidden(module: str, forbidden: set[str]) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in forbidden)


def package_of(path: Path, layer_dir: Path, layer_package: str) -> str:
    relative_parent = path.relative_to(layer_dir).parent.parts
    return ".".join([layer_package, *relative_parent])


def find_violations(
    layer_dir: Path, forbidden: set[str], layer_package: str | None = None
) -> list[str]:
    if layer_package is None:
        layer_package = ".".join(layer_dir.relative_to(PACKAGE_ROOT.parent).parts)
    violations: list[str] = []
    for path in sorted(layer_dir.rglob("*.py")):
        package = package_of(path, layer_dir, layer_package)
        source = path.read_text(encoding="utf-8")
        for module in sorted(imported_modules(source, package)):
            if is_forbidden(module, forbidden):
                violations.append(f"{path.relative_to(layer_dir).as_posix()} imports {module}")
    return violations


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_respects_dependency_rule(layer: str) -> None:
    assert find_violations(PACKAGE_ROOT / layer, FORBIDDEN[layer]) == []


def test_violation_is_detected_and_names_module_and_import(tmp_path: Path) -> None:
    (tmp_path / "leaky.py").write_text("import sqlalchemy\n", encoding="utf-8")
    (tmp_path / "clean.py").write_text("import dataclasses\n", encoding="utf-8")

    violations = find_violations(tmp_path, FORBIDDEN["domain"], "eventssound.domain")

    assert len(violations) == 1
    assert "leaky.py" in violations[0]
    assert "sqlalchemy" in violations[0]


def test_from_imports_of_inner_layers_are_detected(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "from eventssound.adapters.db.session import Base\n", encoding="utf-8"
    )

    violations = find_violations(tmp_path, FORBIDDEN["application"], "eventssound.application")

    assert violations and "eventssound.adapters.db.session" in violations[0]


def test_package_import_of_inner_layer_is_detected(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("from eventssound import adapters\n", encoding="utf-8")

    violations = find_violations(tmp_path, FORBIDDEN["application"], "eventssound.application")

    assert violations and "eventssound.adapters" in violations[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from .. import adapters\n", "eventssound.adapters"),
        ("from ..adapters.db import session\n", "eventssound.adapters.db"),
        ("from ..config import Settings\n", "eventssound.config"),
    ],
)
def test_relative_import_violation_is_detected(tmp_path: Path, source: str, expected: str) -> None:
    (tmp_path / "bad.py").write_text(source, encoding="utf-8")

    # A file at the root of eventssound.domain: `..` resolves to eventssound.
    violations = find_violations(tmp_path, FORBIDDEN["domain"], "eventssound.domain")

    assert any(expected in violation for violation in violations)


def test_relative_import_inside_layer_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("from . import entities\nfrom .entities import X\n", "utf-8")

    assert find_violations(tmp_path, FORBIDDEN["domain"], "eventssound.domain") == []
