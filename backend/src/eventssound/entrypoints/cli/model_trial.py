"""Developer-run live trial to choose the LLM model. NOT part of CI and never run by the app.

Run it as `python -m eventssound.entrypoints.cli.model_trial --model <openrouter id> [--count N]
[--confirm]`. It spends the DEVELOPER'S OWN OpenRouter quota (free models are reported at 20
requests/minute and 50/day, UNVERIFIED), so it is deliberately cheap and cautious:

- without `--confirm` it prints the plan and exits 2: no Settings, no network call;
- `--count` is 1..30 (default 10); more is refused (exit 3). Only the first N golden cases run;
- requests are paced at 20 per minute and the provider never retries: the first HTTP 429 (or an
  auth error) stops the trial at once, prints what was measured and exits 4;
- `APP_ENV=production` is refused (exit 3). The key comes from `Settings` only and is never
  printed or logged; the report and the JSON file hold golden case ids, never prompts or text.

The database is not used: the catalog is the in-memory seed data and search is keyword-only.
"""

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from eventssound.adapters.evals.golden import GOLDEN_CASES
from eventssound.adapters.evals.harness import EvalReport, evaluate
from eventssound.adapters.evals.pacing import PacedProvider
from eventssound.adapters.llm.openrouter import OpenRouterProvider
from eventssound.adapters.openrouter_http import check_model_id
from eventssound.application.llm import LlmValidationError
from eventssound.config import Settings

DEFAULT_COUNT, MAX_COUNT, RPM = 10, 30, 20
EXIT_FAILURE, EXIT_DRY_RUN, EXIT_REFUSED, EXIT_STOPPED = 1, 2, 3, 4
TOKENS_PER_CASE = 2500  # design estimate for understand + draft
OUTPUT_DIR = Path(__file__).resolve().parents[5] / ".dev"
# Never read from the environment: the trial must not need (or touch) a database.
_UNUSED_DATABASE_URL = "postgresql://unused.invalid/unused"


def plan_text(model: str, count: int) -> str:
    pace = 60 / RPM
    return "\n".join(
        [
            "Model trial plan (nothing has been sent)",
            f"  model:     {model}",
            f"  cases:     {count} golden cases",
            f"  requests:  up to {3 * count} (typically {2 * count}): understand, draft, repair",
            f"  tokens:    about {TOKENS_PER_CASE:,} per case, {TOKENS_PER_CASE * count:,} total",
            f"  pacing:    {RPM} requests/minute, one every {pace:.1f}+ s, no retries",
            "  quota:     spends YOUR OpenRouter quota (free models: 50 requests/day reported)",
            "             (UNVERIFIED). The first HTTP 429 stops the trial.",
            "Add --confirm to run it.",
        ]
    )


def _tally(report: EvalReport, names: Sequence[str]) -> tuple[int, int]:
    ok = sum(report.metrics[n][0] for n in names if n in report.metrics)
    return ok, sum(report.metrics[n][1] for n in names if n in report.metrics)


def _row(label: str, ok: int, total: int) -> str:
    rate = f"{100 * ok / total:5.1f}%" if total else "  n/a"
    return f"  {label:<26}{ok:>4}/{total:<4}{rate}"


def table(report: EvalReport) -> str:
    fields = [n for n in report.metrics if n.startswith("extraction.")]
    lines = [
        f"Model trial: {report.model}  ({report.cases_run} cases run"
        + (f", STOPPED: {report.stopped}" if report.stopped else "")
        + ")",
        _row("structured output valid", *_tally(report, ["structured_valid"])),
        _row("extraction accuracy", *_tally(report, fields)),
        _row("oracle match", *_tally(report, ["oracle_match"])),
        _row("clarification correct", *_tally(report, ["clarification"])),
        f"  {'avg latency':<26}{report.to_dict()['avg_latency_ms']:.0f} ms/case",
        f"  {'tokens':<26}{report.prompt_tokens} prompt + {report.completion_tokens} completion",
        f"  {'estimated cost':<26}{report.cost_micro_usd} micro-USD",
    ]
    if report.failures:
        lines.append("First failures (case | field | expected | got):")
        lines += [
            f"  {f['case']} | {f['field']} | {f['expected']} | {f['got']}"
            for f in report.failures[:3]
        ]
    return "\n".join(lines)


def _report_path(output_dir: Path, model: str, now: datetime) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")
    return output_dir / f"model-trial-{slug}-{now.strftime('%Y%m%dT%H%M%S')}.json"


def _refuse(message: str) -> int:
    print(message, file=sys.stderr)
    return EXIT_REFUSED


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_factory: Callable[..., Settings] = Settings,
    provider_factory: Callable[..., object] = OpenRouterProvider,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = datetime.now,
    output_dir: Path = OUTPUT_DIR,
) -> int:
    parser = argparse.ArgumentParser(prog="model_trial", description=__doc__.split("\n")[0])
    parser.add_argument("--model", required=True, help="OpenRouter model id")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)

    if not 1 <= args.count <= MAX_COUNT:
        return _refuse(f"--count must be between 1 and {MAX_COUNT}")
    try:
        model = check_model_id(args.model)
    except LlmValidationError:
        return _refuse("--model is not a valid model id")
    cases = GOLDEN_CASES[: args.count]
    if not args.confirm:
        print(plan_text(model, len(cases)))
        return EXIT_DRY_RUN
    try:
        settings = settings_factory(DATABASE_URL=_UNUSED_DATABASE_URL)
    except ValidationError:
        return _refuse("settings are invalid (details hidden: they may contain secrets)")
    if settings.is_production:
        return _refuse("refused: APP_ENV=production")
    if settings.openrouter_api_key is None:
        return _refuse("refused: OPENROUTER_API_KEY is not set")

    provider = provider_factory(settings.openrouter_api_key, model, max_retries=0)
    paced = PacedProvider(provider, rpm=RPM, clock=clock, sleep=sleep)
    prices = (
        settings.llm_input_price_micro_usd_per_mtok,
        settings.llm_output_price_micro_usd_per_mtok,
    )
    try:
        report = evaluate(
            cases, lambda _case: paced, mode="live", model=model, prices=prices, clock=clock
        )
    except Exception as exc:  # the class name only: messages may echo provider details
        print(f"trial aborted: {type(exc).__name__}", file=sys.stderr)
        return EXIT_FAILURE
    finally:
        close = getattr(provider, "close", None)
        if close:
            close()

    print(table(report))
    stamp = now()
    path = _report_path(output_dir, model, stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {**report.to_dict(), "requests_sent": paced.requests, "at": stamp.isoformat()}
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"Report written to {path}")
    return EXIT_STOPPED if report.stopped else 0


if __name__ == "__main__":
    sys.exit(main())
