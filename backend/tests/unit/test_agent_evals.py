"""The offline agent evaluation: golden set + injections through the production pipeline."""

import dataclasses
import itertools
import json

from eventssound.adapters.evals.golden import GOLDEN_CASES, INJECTION_CASES
from eventssound.adapters.evals.harness import evaluate, replay_provider_for
from eventssound.adapters.evals.pacing import PacedProvider
from eventssound.adapters.llm.replay import ReplayEntry, ReplayProvider
from eventssound.application.llm import TokenUsage


def ticking_clock():
    counter = itertools.count()
    return lambda: next(counter) * 0.01


def run_replay():
    return evaluate(
        GOLDEN_CASES + INJECTION_CASES,
        replay_provider_for,
        mode="replay",
        model="replay",
        clock=ticking_clock(),
    )


class TestGoldenSet:
    def test_is_well_formed(self) -> None:
        cases = GOLDEN_CASES + INJECTION_CASES
        assert len({c.id for c in cases}) == len(cases)
        assert len(GOLDEN_CASES) == 15 and len(INJECTION_CASES) == 8
        assert {c.kind for c in GOLDEN_CASES} == {"quote", "shortage", "clarification", "refused"}
        assert sum(c.kind == "clarification" for c in GOLDEN_CASES) >= 2
        assert all(c.request is not None for c in GOLDEN_CASES if c.kind in ("quote", "shortage"))
        # A trial prefix of 10 must still contain a clarification and a refusal.
        assert {"clarification", "refused"} <= {c.kind for c in GOLDEN_CASES[:10]}


class TestReplayRun:
    def test_every_deterministic_check_is_perfect(self) -> None:
        report = run_replay()
        assert report.failures == []
        assert report.stopped is None and report.cases_run == 23
        assert report.metrics["oracle_match"] == [11, 11]
        assert report.metrics["injection_resisted"] == [8, 8]
        assert report.metrics["clarification"] == [4, 4]
        assert all(ok == total for ok, total in report.metrics.values())
        assert {"extraction.start", "extraction.items", "extraction.packages"} <= set(
            report.metrics
        )

    def test_two_runs_give_identical_reports(self) -> None:
        assert run_replay().to_dict() == run_replay().to_dict()

    def test_report_carries_usage_and_cost(self) -> None:
        data = evaluate(
            GOLDEN_CASES[:4], replay_provider_for, mode="replay", model="m", prices=(1_000_000, 0)
        ).to_dict()
        assert data["tokens"]["prompt"] > 0 and data["cost_micro_usd"] == data["tokens"]["prompt"]

    def test_wrong_expectation_fails_the_oracle(self) -> None:
        case = next(c for c in GOLDEN_CASES if c.id == "corporate_weekday")
        wrong = dataclasses.replace(
            case, request=dataclasses.replace(case.request, guest_count=700)
        )
        report = evaluate([wrong], replay_provider_for, mode="replay", model="m")
        assert report.metrics["oracle_match"] == [0, 1]
        assert {f["field"] for f in report.failures} >= {"guest_count", "total"}


class TestStopsOnRateLimit:
    def test_a_429_swallowed_by_the_draft_still_stops_the_run(self) -> None:
        def provider_for(case):
            ok = ReplayEntry(json.dumps(case.extraction), TokenUsage(1, 1))
            calls = {"understand": (ok,), "draft": (ReplayEntry(error="rate_limited"),)}
            return ReplayProvider({case.id: calls}, scenario=case.id)

        cases = [c for c in GOLDEN_CASES if c.kind == "quote"][:3]
        report = evaluate(cases, provider_for, mode="live", model="m")
        assert report.stopped == "rate_limited"
        assert report.cases_run == 1


class TestPacing:
    def test_request_starts_are_spaced_at_20_per_minute(self) -> None:
        now = [0.0]
        starts: list[float] = []

        class Inner:
            def complete(self, request):
                starts.append(now[0])

        def sleep(seconds: float) -> None:
            now[0] += seconds

        paced = PacedProvider(Inner(), rpm=20, clock=lambda: now[0], sleep=sleep)
        for _ in range(4):
            paced.complete(None)
            now[0] += 0.5  # the call itself takes half a second
        gaps = [b - a for a, b in itertools.pairwise(starts)]
        assert all(gap >= 3.0 for gap in gaps) and paced.requests == 4
