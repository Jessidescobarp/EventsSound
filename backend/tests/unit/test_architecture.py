"""Hexagonal dependency rule, enforced by static import scanning."""

import ast
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "eventssound"
PROJECT = "eventssound"
FRAMEWORKS = {
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "alembic",
    "psycopg",
}

FORBIDDEN: dict[str, set[str]] = {
    "domain": {
        f"{PROJECT}.application",
        f"{PROJECT}.adapters",
        f"{PROJECT}.entrypoints",
        f"{PROJECT}.config",
        *FRAMEWORKS,
    },
    "application": {
        f"{PROJECT}.adapters",
        f"{PROJECT}.entrypoints",
        f"{PROJECT}.config",
        *FRAMEWORKS,
    },
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


def python_files(layer_dir: Path) -> list[Path]:
    """Python files of a layer; an empty scan would silently pass, so it fails instead."""
    files = sorted(layer_dir.rglob("*.py"))
    assert files, f"no python files found under {layer_dir}"
    return files


def dynamic_import_calls(source: str) -> list[ast.Call]:
    """Calls to `__import__(...)` or `import_module(...)` (bare or as an attribute)."""
    calls = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name in {"__import__", "import_module"}:
            calls.append(node)
    return calls


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
    for path in python_files(layer_dir):
        package = package_of(path, layer_dir, layer_package)
        source = path.read_text(encoding="utf-8")
        for module in sorted(imported_modules(source, package)):
            if is_forbidden(module, forbidden):
                violations.append(f"{path.relative_to(layer_dir).as_posix()} imports {module}")
    return violations


def is_allowed_in_domain(module: str) -> bool:
    """Domain may import the stdlib and itself, nothing else (allowlist)."""
    if module.split(".")[0] in sys.stdlib_module_names:
        return True
    own = f"{PROJECT}.domain"
    return module in {PROJECT, own} or module.startswith(f"{own}.")


def find_non_stdlib_violations(layer_dir: Path, layer_package: str | None = None) -> list[str]:
    if layer_package is None:
        layer_package = ".".join(layer_dir.relative_to(PACKAGE_ROOT.parent).parts)
    violations: list[str] = []
    for path in python_files(layer_dir):
        source = path.read_text(encoding="utf-8")
        package = package_of(path, layer_dir, layer_package)
        name = path.relative_to(layer_dir).as_posix()
        for module in sorted(imported_modules(source, package)):
            if not is_allowed_in_domain(module):
                violations.append(f"{name} imports {module}")
        violations.extend(f"{name} uses a dynamic import" for _ in dynamic_import_calls(source))
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


def test_domain_imports_only_stdlib_and_itself() -> None:
    assert find_non_stdlib_violations(PACKAGE_ROOT / "domain") == []


def test_third_party_import_in_domain_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "leaky.py").write_text("import numpy\n", encoding="utf-8")

    violations = find_non_stdlib_violations(tmp_path, "eventssound.domain")

    assert len(violations) == 1
    assert "leaky.py" in violations[0]
    assert "numpy" in violations[0]


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime\n",
        "import dataclasses, functools\n",
        "from . import money\n",
        "from .money import Money\n",
        "from eventssound.domain.money import Money\n",
    ],
    ids=["stdlib-from", "stdlib-multi", "relative-package", "relative-module", "absolute-domain"],
)
def test_stdlib_and_domain_imports_are_not_flagged(tmp_path: Path, source: str) -> None:
    (tmp_path / "ok.py").write_text(source, encoding="utf-8")

    assert find_non_stdlib_violations(tmp_path, "eventssound.domain") == []


@pytest.mark.parametrize(
    "source",
    ["from eventssound.config import Settings\n", "from eventssound import adapters\n"],
    ids=["config", "sibling-layer"],
)
def test_non_domain_project_imports_are_flagged(tmp_path: Path, source: str) -> None:
    (tmp_path / "bad.py").write_text(source, encoding="utf-8")

    assert find_non_stdlib_violations(tmp_path, "eventssound.domain") != []


@pytest.mark.parametrize("framework", ["pydantic", "starlette", "psycopg"])
def test_application_must_not_import_frameworks_or_config(tmp_path: Path, framework: str) -> None:
    (tmp_path / "bad.py").write_text(f"import {framework}\n", encoding="utf-8")
    (tmp_path / "bad_config.py").write_text("from eventssound.config import Settings\n", "utf-8")

    violations = find_violations(tmp_path, FORBIDDEN["application"], "eventssound.application")

    assert any(v.startswith("bad.py") and framework in v for v in violations)
    assert any(v.startswith("bad_config.py") and "eventssound.config" in v for v in violations)


def test_real_domain_scan_covers_the_core_modules() -> None:
    names = {path.name for path in python_files(PACKAGE_ROOT / "domain")}

    assert {"money.py", "catalog.py"} <= names


@pytest.mark.parametrize("scan", ["dependency-rule", "stdlib-allowlist"])
def test_scanning_a_directory_without_python_files_fails_loudly(tmp_path: Path, scan: str) -> None:
    with pytest.raises(AssertionError, match="no python files"):
        if scan == "dependency-rule":
            find_violations(tmp_path, FORBIDDEN["domain"], "eventssound.domain")
        else:
            find_non_stdlib_violations(tmp_path, "eventssound.domain")


@pytest.mark.parametrize(
    "source",
    [
        "__import__('numpy')\n",
        "import importlib\nimportlib.import_module('numpy')\n",
        "from importlib import import_module\nimport_module('numpy')\n",
    ],
    ids=["dunder-import", "importlib-attribute", "importlib-name"],
)
def test_dynamic_imports_in_domain_are_flagged(tmp_path: Path, source: str) -> None:
    (tmp_path / "sneaky.py").write_text(source, encoding="utf-8")

    violations = find_non_stdlib_violations(tmp_path, "eventssound.domain")

    assert any("sneaky.py" in v and "dynamic import" in v for v in violations)


def test_routes_do_not_import_adapters() -> None:
    routes = PACKAGE_ROOT / "entrypoints" / "api" / "routes"

    assert (
        find_violations(routes, {f"{PROJECT}.adapters"}, "eventssound.entrypoints.api.routes") == []
    )


def test_a_route_importing_an_adapter_is_detected(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "from eventssound.adapters.db.session import Base\n", encoding="utf-8"
    )

    violations = find_violations(
        tmp_path, {f"{PROJECT}.adapters"}, "eventssound.entrypoints.api.routes"
    )

    assert any(
        v.startswith("bad.py") and "eventssound.adapters.db.session" in v for v in violations
    )
