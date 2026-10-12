"""Agent, LLM and embedding code must not leak into the core.

Reuses the scanner of `test_architecture.py` and never weakens its `FORBIDDEN` map. Once the
domain chain settles, a follow-up may fold these names into `FRAMEWORKS`.
"""

import ast
from pathlib import Path

import pytest
from test_architecture import (
    FORBIDDEN,
    PACKAGE_ROOT,
    PROJECT,
    dynamic_import_calls,
    find_violations,
    imported_modules,
    python_files,
)

# Matched by TOP-LEVEL package, so `langchain_openai` is caught without listing every partner
# package; the prefixes cover the whole LangChain/LangGraph/LangSmith family.
AGENT_TOP_LEVELS = {
    "httpx", "httpcore", "requests", "aiohttp", "urllib3", "pgvector", "numpy",
    "openai", "anthropic", "litellm", "pydantic_ai", "cohere", "mistralai", "ollama",
    "tiktoken", "transformers", "sentence_transformers", "instructor", "llama_index",
}  # fmt: skip
AGENT_TOP_LEVEL_PREFIXES = ("langchain", "langgraph", "langsmith")
AGENT_DOTTED = ("google.generativeai", "google.genai", "google.ai")
ORCHESTRATION_TOP_LEVELS = {"openai", "anthropic", "litellm", "pydantic_ai", "llama_index"}
ORCHESTRATION_PREFIXES = AGENT_TOP_LEVEL_PREFIXES
PROVIDER_DIRS = ["adapters/llm", "adapters/embeddings"]
CONFIG = {f"{PROJECT}.config"}
ENV_NAMES = {"environ", "environb", "getenv", "putenv"}


def is_agent_library(module: str) -> bool:
    top = module.split(".")[0]
    return (
        top in AGENT_TOP_LEVELS
        or top.startswith(AGENT_TOP_LEVEL_PREFIXES)
        or any(module == name or module.startswith(f"{name}.") for name in AGENT_DOTTED)
    )


def is_orchestration_library(module: str) -> bool:
    top = module.split(".")[0]
    return top in ORCHESTRATION_TOP_LEVELS or top.startswith(ORCHESTRATION_PREFIXES)


def find_library_violations(
    layer_dir: Path, layer_package: str, banned=is_agent_library
) -> list[str]:  # type: ignore[no-untyped-def]
    violations = []
    for path in python_files(layer_dir):
        package = ".".join([layer_package, *path.relative_to(layer_dir).parent.parts])
        source = path.read_text(encoding="utf-8")
        name = path.relative_to(layer_dir).as_posix()
        violations += [
            f"{name} imports {module}"
            for module in sorted(imported_modules(source, package))
            if banned(module)
        ]
        violations += [f"{name} uses a dynamic import" for _ in dynamic_import_calls(source)]
    return violations


def env_reads(source: str) -> list[str]:
    """Names through which source reads or writes the process environment."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in ENV_NAMES:
            found.append(node.attr)
        elif isinstance(node, ast.Name) and node.id in ENV_NAMES:
            found.append(node.id)
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            found += [a.name for a in node.names if a.name in ENV_NAMES or a.name == "*"]
    return found


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_core_layers_import_no_agent_llm_or_vector_library_and_no_dynamic_imports(
    layer: str,
) -> None:
    assert find_library_violations(PACKAGE_ROOT / layer, f"{PROJECT}.{layer}") == []


@pytest.mark.parametrize("directory", PROVIDER_DIRS)
def test_provider_adapters_do_not_import_orchestration_libraries_or_settings(
    directory: str,
) -> None:
    root = PACKAGE_ROOT / directory
    package = f"{PROJECT}.{directory.replace('/', '.')}"
    assert find_violations(root, CONFIG | {f"{PROJECT}.entrypoints"}) == []
    own_violations = find_library_violations(root, package, is_orchestration_library)
    assert [v for v in own_violations if "dynamic import" not in v] == []


@pytest.mark.parametrize("relative", ["adapters/secret.py", "adapters/openrouter_http.py"])
def test_shared_provider_modules_do_not_import_orchestration_libraries_or_settings(
    relative: str, tmp_path: Path
) -> None:
    (tmp_path / "copy.py").write_text((PACKAGE_ROOT / relative).read_text("utf-8"), "utf-8")

    assert find_violations(tmp_path, CONFIG, f"{PROJECT}.adapters") == []
    assert find_library_violations(tmp_path, f"{PROJECT}.adapters", is_orchestration_library) == []


def test_no_module_except_settings_reads_the_environment() -> None:
    offenders = {}
    scanned = []
    for path in python_files(PACKAGE_ROOT):
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        # Settings is the sanctioned reader. The seed CLI is the one documented exception: it reads
        # the operator override ALLOW_REMOTE_SEED (an injectable `environ`), see its docstring.
        if relative in {"config.py", "entrypoints/cli/seed_catalog.py"}:
            continue
        scanned.append(relative)
        if reads := env_reads(path.read_text("utf-8")):
            offenders[relative] = reads

    assert offenders == {}
    # The scan covers the modules a reviewer would worry about, none skipped.
    assert {"adapters/openrouter_http.py", "adapters/secret.py", "adapters/llm/openrouter.py"} <= (
        set(scanned)
    )


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.environ['A']\n",
        "import os\nos.getenv('A')\n",
        "import os as o\no.environ.get('A')\n",
        "from os import getenv\n",
        "from os import environ\nenviron['A']\n",
        "from os import path, getenv as g\n",
        "from os import *\n",
        "import os\nos.putenv('A', 'b')\n",
        "import os\nos.environb\n",
    ],
    ids=["environ", "getenv", "alias", "from-getenv", "from-environ", "from-aliased-getenv",
         "star", "putenv", "environb"],
)  # fmt: skip
def test_environment_read_detector_catches_every_form(source: str) -> None:
    assert env_reads(source) != []


@pytest.mark.parametrize(
    "source", ["import os\nos.path.join('a')\n", "from os import path\n", "environment = 1\n"]
)
def test_environment_read_detector_ignores_unrelated_code(source: str) -> None:
    assert env_reads(source) == []


def test_real_scans_are_not_vacuous() -> None:
    application = {p.name for p in python_files(PACKAGE_ROOT / "application")}
    llm_adapters = {p.name for p in python_files(PACKAGE_ROOT / "adapters" / "llm")}
    embedding_adapters = {p.name for p in python_files(PACKAGE_ROOT / "adapters" / "embeddings")}

    assert {"llm.py", "embeddings.py"} <= application
    assert {"replay.py", "openrouter.py"} <= llm_adapters
    assert {"fake.py", "openrouter.py"} <= embedding_adapters


def test_the_scanner_does_see_httpx_where_it_is_allowed() -> None:
    # Positive control: adapters may import httpx, and the scan really finds it there.
    found = find_library_violations(PACKAGE_ROOT / "adapters", f"{PROJECT}.adapters")

    assert any("openrouter_http.py imports httpx" in v for v in found)


@pytest.mark.parametrize("layer", ["domain", "application"])
@pytest.mark.parametrize(
    "source",
    [
        "import httpx\n",
        "from httpx import Client\n",
        "import httpx._client\n",
        "import httpcore\n",
        "import requests\n",
        "import langgraph.graph\n",
        "from langchain_core.messages import BaseMessage\n",
        "from langchain_openai import ChatOpenAI\n",
        "import langchain_community.llms\n",
        "from langsmith import Client\n",
        "import openai\n",
        "from anthropic import Anthropic\n",
        "import litellm\n",
        "from pydantic_ai import Agent\n",
        "import google.generativeai as genai\n",
        "from google import generativeai\n",
        "import pgvector\n",
        "import numpy as np\n",
    ],
    ids=["httpx", "from-httpx", "httpx-submodule", "httpcore", "requests", "langgraph",
         "langchain-core", "langchain-openai", "langchain-community", "langsmith", "openai",
         "anthropic", "litellm", "pydantic-ai", "google-generativeai",
         "from-google-generativeai", "pgvector", "numpy"],
)  # fmt: skip
def test_agent_library_imports_are_flagged_in_the_core(
    layer: str, source: str, tmp_path: Path
) -> None:
    (tmp_path / "leaky.py").write_text(source, encoding="utf-8")
    (tmp_path / "clean.py").write_text("import json\n", encoding="utf-8")

    violations = find_library_violations(tmp_path, f"{PROJECT}.{layer}")

    assert violations  # `from x import Name` also reports the candidate submodule
    assert all(v.startswith("leaky.py imports ") for v in violations)


@pytest.mark.parametrize(
    "source",
    [
        "__import__('httpx')\n",
        "import importlib\nimportlib.import_module('langgraph')\n",
        "from importlib import import_module\nimport_module('openai')\n",
    ],
    ids=["dunder-import", "importlib-attribute", "importlib-name"],
)
def test_dynamic_imports_are_flagged_in_application(source: str, tmp_path: Path) -> None:
    (tmp_path / "sneaky.py").write_text(source, encoding="utf-8")

    violations = find_library_violations(tmp_path, f"{PROJECT}.application")

    assert any("sneaky.py" in v and "dynamic import" in v for v in violations)


@pytest.mark.parametrize(
    "source",
    ["import httpx_extra\n", "import mynumpy\n", "import langchain_not\nimport json\n"],
    ids=["httpx-extra", "mynumpy", "langchain-prefix"],
)
def test_similarly_named_modules_are_matched_by_top_level_package(
    source: str, tmp_path: Path
) -> None:
    (tmp_path / "ok.py").write_text(source, encoding="utf-8")

    flagged = {v.split()[-1] for v in find_library_violations(tmp_path, f"{PROJECT}.application")}

    # `langchain*` is an intentional prefix family; the other look-alikes are not flagged.
    assert flagged <= {"langchain_not"}


@pytest.mark.parametrize(
    "source", ["from eventssound.config import Settings\n", "from ...config import Settings\n"]
)
def test_settings_import_in_a_provider_adapter_is_flagged(source: str, tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(source, encoding="utf-8")

    violations = find_violations(tmp_path, CONFIG, f"{PROJECT}.adapters.llm")

    assert violations and "eventssound.config" in violations[0]


@pytest.mark.parametrize("module", ["langchain_openai", "openai.types", "litellm"])
def test_orchestration_libraries_are_flagged_in_provider_adapters(
    module: str, tmp_path: Path
) -> None:
    (tmp_path / "bad.py").write_text(f"import {module}\n", encoding="utf-8")

    violations = find_library_violations(
        tmp_path, f"{PROJECT}.adapters.llm", is_orchestration_library
    )

    assert violations and module in violations[0]


def test_httpx_is_allowed_in_provider_adapters(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("import httpx\n", encoding="utf-8")

    assert (
        find_library_violations(tmp_path, f"{PROJECT}.adapters.llm", is_orchestration_library) == []
    )


def test_core_forbidden_map_keeps_its_original_entries() -> None:
    assert f"{PROJECT}.adapters" in FORBIDDEN["application"]
    assert "pydantic" in FORBIDDEN["application"]
    assert f"{PROJECT}.entrypoints" in FORBIDDEN["adapters"]
