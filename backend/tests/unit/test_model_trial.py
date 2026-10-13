"""The guarded live model trial, driven with fakes: no network, no real key."""

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from eventssound.adapters.evals.golden import GOLDEN_CASES
from eventssound.adapters.evals.harness import replay_provider_for
from eventssound.adapters.llm.openrouter import OpenRouterProvider
from eventssound.entrypoints.cli.model_trial import main

KEY = "sk-or-test-secret-0123456789"


def settings(**over):
    values = {
        "is_production": False,
        "openrouter_api_key": SecretStr(KEY),
        "llm_input_price_micro_usd_per_mtok": 0,
        "llm_output_price_micro_usd_per_mtok": 0,
    }
    return lambda **_: SimpleNamespace(**{**values, **over})


class FakeLive:
    """Answers like a faithful model by routing on the request scenario (the case id)."""

    def __init__(self) -> None:
        self.calls = 0
        self._providers: dict = {}

    def complete(self, request):
        self.calls += 1
        if request.scenario not in self._providers:
            case = next(c for c in GOLDEN_CASES if c.id == request.scenario)
            self._providers[request.scenario] = replay_provider_for(case)
        return self._providers[request.scenario].complete(request)


def run(argv, tmp_path, **kwargs):
    sleeps: list[float] = []
    kwargs.setdefault("settings_factory", settings())
    code = main(argv, sleep=sleeps.append, output_dir=tmp_path, **kwargs)
    return code, sleeps


def boom(*_args, **_kwargs):
    raise AssertionError("must not be reached")


class TestGuards:
    def test_dry_run_prints_the_plan_and_touches_nothing(self, tmp_path, capsys) -> None:
        code, _ = run(
            ["--model", "vendor/m:free"], tmp_path, settings_factory=boom, provider_factory=boom
        )
        out = capsys.readouterr().out
        assert code == 2 and "vendor/m:free" in out and "20 requests/minute" in out
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize(
        ("model", "count", "overrides"),
        [
            ("vendor/m:free", "31", {}),
            ("vendor/m:free", "0", {}),
            ("bad model!", "5", {}),
            ("vendor/m:free", "5", {"is_production": True}),
            ("vendor/m:free", "5", {"openrouter_api_key": None}),
        ],
        ids=["over-cap", "zero", "bad-model", "production", "no-key"],
    )
    def test_refusals_never_build_a_provider(self, tmp_path, model, count, overrides) -> None:
        code, _ = run(
            ["--model", model, "--count", count, "--confirm"],
            tmp_path,
            settings_factory=settings(**overrides),
            provider_factory=boom,
        )
        assert code == 3
        assert list(tmp_path.iterdir()) == []


class TestRun:
    def test_report_table_file_and_secrecy(self, tmp_path, capsys) -> None:
        live = FakeLive()
        code, sleeps = run(
            ["--model", "vendor/m:free", "--count", "5", "--confirm"],
            tmp_path,
            provider_factory=lambda key, model, **kw: live,
        )
        captured = capsys.readouterr()
        (path,) = tmp_path.glob("model-trial-vendor-m-free-*.json")
        text = path.read_text()
        data = json.loads(text)
        assert code == 0 and data["cases_run"] == 5 and data["requests_sent"] == live.calls
        assert "oracle match" in captured.out and data["stopped"] is None
        assert KEY not in captured.out + captured.err + text
        assert len(sleeps) == live.calls - 1 and all(s > 0 for s in sleeps)

    def test_first_429_stops_without_retrying(self, tmp_path, capsys) -> None:
        hits: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(1)
            return httpx.Response(429, headers={"retry-after": "1"})

        def factory(key, model, **kwargs):
            return OpenRouterProvider(key, model, transport=httpx.MockTransport(handler), **kwargs)

        code, _ = run(["--model", "vendor/m:free", "--confirm"], tmp_path, provider_factory=factory)
        data = json.loads(next(tmp_path.glob("*.json")).read_text())
        assert code == 4 and len(hits) == 1
        assert data["stopped"] == "rate_limited" and data["cases_run"] == 1
        assert KEY not in capsys.readouterr().out
