"""Command-line interface for collection, run management, and aggregation."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from .aggregation import aggregate_daily
from .config import ConfigError, config_hash, load_config, load_country_config
from .manifest import build_manifest, build_run_manifest
from .models import CollectionRequest, DailyCountryCoverage, DailyTrend, ProviderResult
from .run_state import CollectionRunState, RunStore
from .sources import GoogleTrendsProvider, ProviderUnavailableError
from .sources.base import ProviderCollectionError
from .sources.gdelt import GDELTProvider, plan_gdelt_windows
from .sources.gdelt_timeline import (
    COUNTRY_COVERAGE_TOPIC_ID,
    GDELTSourceCountryProvider,
    GDELTTimelineProvider,
    plan_source_country_windows,
    plan_timeline_windows,
)
from .storage import LocalParquetStorage


LOGGER = logging.getLogger(__name__)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a valid date (expected YYYY-MM-DD)"
        ) from exc


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _country_batch_size(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 7:
        raise argparse.ArgumentTypeError("value must be between 1 and 7")
    return parsed


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout", type=_positive_float)
    parser.add_argument("--max-retries", type=_nonnegative_int)
    parser.add_argument("--request-interval", type=_nonnegative_float)
    parser.add_argument("--backoff-seconds", type=_nonnegative_float)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="climate-attention",
        description="Collect reproducible longitudinal attention data.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate topic YAML")
    validate.add_argument("--config", type=Path, required=True)
    validate_countries = subparsers.add_parser(
        "validate-countries", help="validate source-country YAML"
    )
    validate_countries.add_argument("--config", type=Path, required=True)

    collect = subparsers.add_parser("collect", help="start or resume collection")
    collect.add_argument(
        "--source", choices=("gdelt", "google-trends", "google_trends")
    )
    collect.add_argument("--config", type=Path)
    collect.add_argument("--start", type=_iso_date)
    collect.add_argument("--end", type=_iso_date)
    collect.add_argument("--topics", nargs="+", help="only collect these topic ids")
    collect.add_argument("--data-dir", type=Path, default=Path("data"))
    collect.add_argument(
        "--resume", metavar="RUN_ID", help="resume this run's unfinished windows"
    )
    _add_runtime_options(collect)

    trends = subparsers.add_parser(
        "collect-trends",
        help="collect daily GDELT attention trends by topic and source country",
    )
    trends.add_argument("--config", type=Path, required=True)
    trends.add_argument("--countries-config", type=Path, required=True)
    trends.add_argument("--start", type=_iso_date, required=True)
    trends.add_argument("--end", type=_iso_date, required=True)
    trends.add_argument("--topics", nargs="+", help="only collect these topic ids")
    trends.add_argument(
        "--countries", nargs="+", help="only collect these configured country ids"
    )
    trends.add_argument(
        "--trend-mode",
        choices=("country-share", "raw-counts"),
        default="country-share",
        help=(
            "country-share uses GDELT's native normalized country timeline "
            "(default); raw-counts makes per-country count and baseline requests"
        ),
    )
    trends.add_argument(
        "--country-batch-size",
        type=_country_batch_size,
        help=(
            "force explicit country batches of this size (1-7); by default one "
            "global request returns the country breakdown"
        ),
    )
    trends.add_argument("--window-days", type=int, default=366)
    trends.add_argument(
        "--plan-only", action="store_true", help="create checkpoints without HTTP requests"
    )
    trends.add_argument("--data-dir", type=Path, default=Path("data"))
    _add_runtime_options(trends)

    aggregate = subparsers.add_parser(
        "aggregate", aliases=["rebuild-aggregates"], help="rebuild daily Parquet"
    )
    aggregate.add_argument("--data-dir", type=Path, default=Path("data"))

    runs = subparsers.add_parser("runs", help="inspect and retry durable runs")
    run_commands = runs.add_subparsers(dest="runs_command", required=True)
    runs_list = run_commands.add_parser("list", help="list collection runs")
    runs_list.add_argument("--data-dir", type=Path, default=Path("data"))
    runs_inspect = run_commands.add_parser("inspect", help="inspect one run")
    runs_inspect.add_argument("run_id")
    runs_inspect.add_argument("--data-dir", type=Path, default=Path("data"))
    runs_inspect.add_argument("--json", action="store_true", dest="as_json")
    runs_retry = run_commands.add_parser("retry", help="retry unfinished windows")
    runs_retry.add_argument("run_id")
    runs_retry.add_argument("--data-dir", type=Path, default=Path("data"))
    _add_runtime_options(runs_retry)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "validate-config":
            return _validate_config(args.config)
        if args.command == "validate-countries":
            return _validate_countries(args.config)
        if args.command == "collect":
            return _collect(args)
        if args.command == "collect-trends":
            return _collect_trends(args)
        if args.command in {"aggregate", "rebuild-aggregates"}:
            return _aggregate(args.data_dir)
        if args.command == "runs":
            return _runs(args)
    except (ConfigError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


def _validate_config(path: Path) -> int:
    config = load_config(path)
    enabled = config.enabled_topics()
    query_count = sum(len(topic.queries) for topic in enabled)
    print(
        f"Valid configuration: {len(config.topics)} topic(s), "
        f"{len(enabled)} enabled, {query_count} configured query/queries."
    )
    return 0


def _validate_countries(path: Path) -> int:
    config = load_country_config(path)
    enabled = config.enabled_countries()
    print(
        f"Valid country configuration: {len(config.countries)} country/countries, "
        f"{len(enabled)} enabled."
    )
    return 0


def _runtime_options(args: argparse.Namespace, base: dict | None = None) -> dict:
    options = dict(base or {})
    defaults = {
        "timeout": 30.0,
        "max_retries": 3,
        "request_interval_seconds": 6.0,
        "backoff_seconds": 30.0,
    }
    names = {
        "timeout": "timeout",
        "max_retries": "max_retries",
        "request_interval": "request_interval_seconds",
        "backoff_seconds": "backoff_seconds",
    }
    for argument, option in names.items():
        value = getattr(args, argument, None)
        if value is not None:
            options[option] = value
        elif option not in options:
            options[option] = defaults[option]
    return options


def _collect(args: argparse.Namespace) -> int:
    if args.resume:
        incompatible = [
            name
            for name in ("source", "config", "start", "end", "topics")
            if getattr(args, name) not in (None, [])
        ]
        if incompatible:
            raise ValueError(
                "--resume uses the frozen run definition; do not also pass "
                + ", ".join(f"--{name}" for name in incompatible)
            )
        explicit = {
            key: value
            for key, value in {
                "timeout": args.timeout,
                "max_retries": args.max_retries,
                "request_interval_seconds": args.request_interval,
                "backoff_seconds": args.backoff_seconds,
            }.items()
            if value is not None
        }
        return _resume_run(args.resume, args.data_dir, explicit)

    source = (args.source or "gdelt").replace("-", "_")
    config_path = args.config or Path("config/topics.yaml")
    if args.start is None or args.end is None:
        raise ValueError("new collection requires --start and --end")
    config = load_config(config_path)
    selected = set(args.topics) if args.topics else None
    topics = config.enabled_topics(selected)
    request = CollectionRequest(start=args.start, end=args.end, topics=topics)

    if source != "gdelt":
        return _collect_unavailable_provider(
            source, config_path, request, LocalParquetStorage(args.data_dir)
        )

    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    options = _runtime_options(args)
    store = RunStore(args.data_dir)
    state = store.create(
        run_id=run_id,
        source=source,
        start=request.start,
        end=request.end,
        config_path=config_path,
        config_sha256=config_hash(config_path),
        topics=topics,
        provider_options=options,
        windows=plan_gdelt_windows(request),
    )
    print(f"Created run {run_id} with {len(state.windows)} planned window(s).")
    return _execute_gdelt_run(state, args.data_dir, store)


def _resume_run(
    run_id: str, data_dir: Path, option_overrides: dict | None = None
) -> int:
    store = RunStore(data_dir)
    state = store.load(run_id)
    if state.source not in {"gdelt", "gdelt_timeline", "gdelt_source_country"}:
        raise ValueError(f"run {run_id} uses unsupported resumable source {state.source!r}")
    if option_overrides:
        # Only explicitly supplied retry options should override the frozen values.
        state.provider_options.update(option_overrides)
        store.save(state)
    if state.source in {"gdelt_timeline", "gdelt_source_country"}:
        return _execute_timeline_run(state, data_dir, store)
    return _execute_gdelt_run(state, data_dir, store)


def _collect_trends(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    country_config = load_country_config(args.countries_config)
    topics = config.enabled_topics(set(args.topics) if args.topics else None)
    countries = country_config.enabled_countries(
        set(args.countries) if args.countries else None
    )
    request = CollectionRequest(start=args.start, end=args.end, topics=topics)
    if args.trend_mode == "country-share":
        windows = plan_source_country_windows(
            request,
            countries,
            window_days=args.window_days,
            batch_size=args.country_batch_size,
        )
        source = "gdelt_source_country"
    else:
        windows = plan_timeline_windows(
            request, countries, window_days=args.window_days
        )
        source = "gdelt_timeline"
    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    options = _runtime_options(args)
    if args.request_interval is None:
        options["request_interval_seconds"] = 65.0
    options["country_labels"] = {
        country.id: country.label for country in countries
    }
    store = RunStore(args.data_dir)
    state = store.create(
        run_id=run_id,
        source=source,
        start=request.start,
        end=request.end,
        config_path=args.config,
        config_sha256=config_hash(args.config),
        country_config_path=args.countries_config,
        country_config_sha256=config_hash(args.countries_config),
        topics=topics,
        provider_options=options,
        windows=windows,
    )
    print(
        f"Created trend run {run_id}: {len(topics)} topic(s), "
        f"{len(countries)} country/countries, {len(windows)} planned window(s), "
        f"mode={args.trend_mode}."
    )
    if args.trend_mode == "raw-counts":
        coverage_windows = sum(
            window.query.topic_id == COUNTRY_COVERAGE_TOPIC_ID for window in windows
        )
        print(
            f"The plan includes {coverage_windows} country-coverage baseline "
            "window(s) for within-country normalization."
        )
    else:
        query_scope = (
            f"explicit batches of {args.country_batch_size}"
            if args.country_batch_size is not None
            else "one global country breakdown per topic window"
        )
        print(
            "Country attention shares are returned natively by GDELT; "
            f"using {query_scope}. matched_count remains null unless raw-count "
            "data is also collected."
        )
    estimated_minutes = len(windows) * options["request_interval_seconds"] / 60
    print(
        f"Minimum pacing time: approximately {estimated_minutes:.1f} minutes, "
        "excluding response latency and retries."
    )
    if args.plan_only:
        print(f"Plan saved. Start it with: climate-attention runs retry {run_id}")
        return 0
    return _execute_timeline_run(state, args.data_dir, store)


def _execute_gdelt_run(
    state: CollectionRunState, data_dir: Path, store: RunStore
) -> int:
    storage = LocalParquetStorage(data_dir)
    pending = state.resumable_windows()
    if not pending and state.is_complete():
        print(f"Run {state.run_id} is already complete; no requests were repeated.")
        return 0
    if not pending:
        raise ValueError(f"run {state.run_id} has no resumable windows")

    state.mark_started()
    store.save(state)

    def checkpoint(event, window, log, records, children):
        if event == "success" and records:
            state.records_newly_stored += storage.write_records(records)
        state.apply_window_event(event, window, log, children)
        store.save(state)

    provider = GDELTProvider(
        **state.provider_options,
        response_sink=lambda envelope: storage.append_api_response(
            "gdelt", state.run_id, envelope
        ),
        window_sink=checkpoint,
    )
    error: str | None = None
    exit_code = 0
    try:
        with provider:
            provider.collect_windows(pending)
        if state.is_complete():
            state.mark_finished("complete")
        else:
            error = "collection ended with unfinished windows"
            state.mark_finished("failed", error)
            exit_code = 1
    except ProviderCollectionError as exc:
        error = str(exc)
        state.mark_finished("failed", error)
        exit_code = 1
    except KeyboardInterrupt:
        error = "collection interrupted by user; the active window remains resumable"
        state.mark_finished("interrupted", error)
        exit_code = 130
    except Exception as exc:  # preserve state even for unexpected provider failures
        error = f"unexpected collection failure: {exc}"
        state.mark_finished("failed", error)
        exit_code = 1

    store.save(state)
    manifest_path = storage.write_manifest(state.run_id, build_run_manifest(state))
    records = storage.read_records()
    aggregate_path = storage.write_daily(aggregate_daily(records))
    counts = state.status_counts()
    if exit_code:
        LOGGER.error("Run %s %s: %s", state.run_id, state.status, error)
        LOGGER.error("Resume with: climate-attention runs retry %s", state.run_id)
    else:
        print(
            f"Run {state.run_id} complete: {state.records_newly_stored} new record(s)."
        )
    print(
        f"Windows: {counts}. Manifest: {manifest_path}. "
        f"Daily aggregates: {aggregate_path}."
    )
    return exit_code


def _execute_timeline_run(
    state: CollectionRunState, data_dir: Path, store: RunStore
) -> int:
    storage = LocalParquetStorage(data_dir)
    pending = state.resumable_windows()
    if not pending and state.is_complete():
        print(f"Run {state.run_id} is already complete; no requests were repeated.")
        return 0
    if not pending:
        raise ValueError(f"run {state.run_id} has no resumable windows")
    state.mark_started()
    store.save(state)

    def checkpoint(event, window, log, observations, children):
        if event == "success" and observations:
            coverages = [
                item
                for item in observations
                if isinstance(item, DailyCountryCoverage)
            ]
            trends = [
                item for item in observations if isinstance(item, DailyTrend)
            ]
            # Coverage is written first so topic rows receive their country
            # denominator immediately; it also refreshes matching older rows.
            state.records_newly_stored += storage.write_country_coverages(coverages)
            state.records_newly_stored += storage.write_trends(trends)
        state.apply_window_event(event, window, log, children)
        store.save(state)

    provider_class = (
        GDELTSourceCountryProvider
        if state.source == "gdelt_source_country"
        else GDELTTimelineProvider
    )
    provider = provider_class(
        **state.provider_options,
        response_sink=lambda envelope: storage.append_api_response(
            state.source, state.run_id, envelope
        ),
        timeline_sink=checkpoint,
    )
    error: str | None = None
    exit_code = 0
    try:
        with provider:
            provider.collect_windows(pending)
        if state.is_complete():
            state.mark_finished("complete")
        else:
            error = "trend collection ended with unfinished windows"
            state.mark_finished("failed", error)
            exit_code = 1
    except ProviderCollectionError as exc:
        error = str(exc)
        state.mark_finished("failed", error)
        exit_code = 1
    except KeyboardInterrupt:
        error = "trend collection interrupted; the active window remains resumable"
        state.mark_finished("interrupted", error)
        exit_code = 130
    except Exception as exc:
        error = f"unexpected trend collection failure: {exc}"
        state.mark_finished("failed", error)
        exit_code = 1

    store.save(state)
    manifest_path = storage.write_manifest(state.run_id, build_run_manifest(state))
    counts = state.status_counts()
    if exit_code:
        LOGGER.error("Trend run %s %s: %s", state.run_id, state.status, error)
        LOGGER.error("Resume with: climate-attention runs retry %s", state.run_id)
    else:
        print(
            f"Trend run {state.run_id} complete: "
            f"{state.records_newly_stored} new daily point(s)."
        )
    print(
        f"Windows: {counts}. Manifest: {manifest_path}. "
        f"Trend dataset: {storage.root / 'trends'}."
    )
    return exit_code


def _collect_unavailable_provider(
    source: str,
    config_path: Path,
    request: CollectionRequest,
    storage: LocalParquetStorage,
) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    provider = GoogleTrendsProvider()
    result = ProviderResult()
    try:
        provider.collect(request)
    except ProviderUnavailableError as exc:
        manifest = build_manifest(
            run_id=run_id,
            source=source,
            status="failed",
            started_at=started_at,
            start=request.start,
            end=request.end,
            config_path=config_path,
            topics=request.topics,
            result=result,
            records_newly_stored=0,
            error=str(exc),
        )
        path = storage.write_manifest(run_id, manifest)
        LOGGER.error("Collection failed: %s", exc)
        LOGGER.error("Failure manifest: %s", path)
        return 1
    return 0


def _runs(args: argparse.Namespace) -> int:
    store = RunStore(args.data_dir)
    if args.runs_command == "list":
        states = store.list()
        if not states:
            print("No durable collection runs found.")
            return 0
        print("RUN ID                         STATUS       SOURCE          WINDOWS (ok/fail/pending)  RANGE")
        for state in states:
            counts = state.status_counts()
            pending = counts["pending"] + counts["running"]
            print(
                f"{state.run_id:<30} {state.status:<12} {state.source:<15} "
                f"{counts['success']}/{counts['failed']}/{pending:<18} "
                f"{state.requested_start}..{state.requested_end}"
            )
        return 0
    if args.runs_command == "inspect":
        state = store.load(args.run_id)
        if args.as_json:
            print(json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True))
        else:
            print(f"Run:       {state.run_id}")
            print(f"Status:    {state.status}")
            print(f"Source:    {state.source}")
            print(f"Range:     {state.requested_start} to {state.requested_end}")
            print(f"Config:    {state.config_snapshot_path}")
            if state.country_config_snapshot_path:
                print(f"Countries: {state.country_config_snapshot_path}")
            print(f"Windows:   {state.status_counts()}")
            print(f"New rows:  {state.records_newly_stored}")
            if state.error:
                print(f"Error:     {state.error}")
            print(f"State:     {store.state_path(state.run_id)}")
        return 0
    if args.runs_command == "retry":
        explicit = {
            key: value
            for key, value in {
                "timeout": args.timeout,
                "max_retries": args.max_retries,
                "request_interval_seconds": args.request_interval,
                "backoff_seconds": args.backoff_seconds,
            }.items()
            if value is not None
        }
        return _resume_run(args.run_id, args.data_dir, explicit)
    raise ValueError(f"unknown runs command: {args.runs_command}")


def _aggregate(data_dir: Path) -> int:
    storage = LocalParquetStorage(data_dir)
    records = storage.read_records()
    observations = aggregate_daily(records)
    path = storage.write_daily(observations)
    print(f"Wrote {len(observations)} daily row(s) from {len(records)} record(s) to {path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
