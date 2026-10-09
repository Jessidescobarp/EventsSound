import importlib

import pytest

LAYERS = ["domain", "application", "adapters", "entrypoints"]


@pytest.mark.parametrize("layer", LAYERS)
def test_packages_importable(layer: str) -> None:
    importlib.import_module(f"eventssound.{layer}")
