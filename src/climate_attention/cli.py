"""Command-line interface for collection, run management, and aggregation."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from .aggregation import aggregate_daily
from .config import (
    ConfigError,
    config_hash,
    load_config,
    load_country_config,
    load_political_config,
)
from .comparison import compare_trends, write_comparisons
from .manifest import build_run_manifest, package_version
from .models import (
    CollectionRequest,
    DailyCountryCoverage,
    DailyTrend,
    PoliticalArticleSample,
)
from .run_state import CollectionRunState, RunStore
from .sources import GoogleTrendsUnofficialProvider
from .sources.base import ProviderCollectionError, ProviderError
from .sources.gdelt import GDELTProvider, plan_gdelt_windows
from .sources.gdelt_timeline import (
    COUNTRY_COVERAGE_TOPIC_ID,
    GDELTSourceCountryProvider,
    GDELTTimelineProvider,
    plan_source_country_windows,
    plan_timeline_windows,
)
from .sources.gdelt_ngrams import (
    GDELTNGramsProvider,
    GoogleBigQueryExecutor,
    audit_country_mapping,
    estimate_ngram_windows,
    plan_ngram_windows,
)
from .sources.google_trends import plan_google_trends_windows
from .sources.firms import (
    FIRMS_SOURCE,
    ALLOWED_SOURCES as FIRMS_ALLOWED_SOURCES,
    NATURAL_EARTH_FILENAME,
    FIRMSProvider,
    ensure_natural_earth_boundaries,
    firms_map_key,
    plan_firms_windows,
)
from .sources.gdacs import GDACSProvider
from .geography import load_country_boundaries
from .storage import LocalParquetStorage
from .supabase_sync import MVP_TOPICS, dotenv_value, sync_articles


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


def _article_sample_size(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("value must be between 0 and 100")
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

    google_trends = subparsers.add_parser(
        "collect-google-trends",
        help="collect unofficial Google Trends indices by query and search country",
    )
    google_trends.add_argument("--config", type=Path, required=True)
    google_trends.add_argument("--countries-config", type=Path, required=True)
    google_trends.add_argument("--start", type=_iso_date, required=True)
    google_trends.add_argument("--end", type=_iso_date, required=True)
    google_trends.add_argument(
        "--topics", nargs="+", help="only collect these topic ids"
    )
    google_trends.add_argument(
        "--countries", nargs="+", help="only collect these configured country ids"
    )
    google_trends.add_argument("--category", type=_nonnegative_int, default=0)
    google_trends.add_argument(
        "--property",
        choices=("web", "news", "images", "youtube", "shopping"),
        default="web",
    )
    google_trends.add_argument("--hl", default="en-US", help="Google request locale")
    google_trends.add_argument(
        "--tz", type=int, default=0, help="timezone offset in minutes from UTC"
    )
    google_trends.add_argument(
        "--plan-only", action="store_true", help="create checkpoints without HTTP requests"
    )
    google_trends.add_argument("--data-dir", type=Path, default=Path("data"))
    _add_runtime_options(google_trends)

    ngrams = subparsers.add_parser(
        "collect-ngrams",
        help="collect distinct-URL GDELT Web NGrams trends through BigQuery",
    )
    ngrams.add_argument("--config", type=Path, required=True)
    ngrams.add_argument("--countries-config", type=Path, required=True)
    ngrams.add_argument("--start", type=_iso_date, required=True)
    ngrams.add_argument("--end", type=_iso_date, required=True)
    ngrams.add_argument("--topics", nargs="+", help="only collect these topic ids")
    ngrams.add_argument(
        "--countries", nargs="+", help="only collect these configured country ids"
    )
    ngrams.add_argument("--window-days", type=int, default=366)
    ngrams.add_argument(
        "--political-config",
        type=Path,
        help="multilingual political signals and audited official domains",
    )
    ngrams.add_argument(
        "--article-sample-size",
        type=_article_sample_size,
        default=0,
        help="deterministic validation URLs per topic/country/day (0-100)",
    )
    ngrams.add_argument(
        "--save-articles",
        action="store_true",
        help="save every matched article and all available GAL metadata (no GKG)",
    )
    ngrams.add_argument(
        "--billing-project",
        required=True,
        help="explicit Google Cloud project used for BigQuery billing",
    )
    ngrams.add_argument("--location", default="US")
    ngrams.add_argument(
        "--include-denominator",
        action="store_true",
        help="also scan GAL for country denominators (potentially very expensive)",
    )
    ngrams.add_argument(
        "--maximum-gb-billed",
        type=_positive_float,
        required=True,
        help="hard per-window BigQuery byte cap",
    )
    ngrams.add_argument(
        "--plan-only", action="store_true", help="save the workload without BigQuery calls"
    )
    ngrams.add_argument("--data-dir", type=Path, default=Path("data"))

    estimate_ngrams = subparsers.add_parser(
        "estimate-ngrams", help="dry-run GDELT NGrams queries and print byte estimates"
    )
    estimate_ngrams.add_argument("--config", type=Path, required=True)
    estimate_ngrams.add_argument("--countries-config", type=Path, required=True)
    estimate_ngrams.add_argument("--start", type=_iso_date, required=True)
    estimate_ngrams.add_argument("--end", type=_iso_date, required=True)
    estimate_ngrams.add_argument("--topics", nargs="+")
    estimate_ngrams.add_argument("--countries", nargs="+")
    estimate_ngrams.add_argument("--window-days", type=int, default=366)
    estimate_ngrams.add_argument("--political-config", type=Path)
    estimate_ngrams.add_argument(
        "--article-sample-size", type=_article_sample_size, default=0
    )
    estimate_ngrams.add_argument("--save-articles", action="store_true")
    estimate_ngrams.add_argument("--billing-project", required=True)
    estimate_ngrams.add_argument("--location", default="US")
    estimate_ngrams.add_argument(
        "--include-denominator",
        action="store_true",
        help="include the optional GAL denominator scan in estimates",
    )

    audit_ngrams = subparsers.add_parser(
        "audit-ngram-countries",
        help="audit configured country labels against GDELT's domain map",
    )
    audit_ngrams.add_argument("--countries-config", type=Path, required=True)
    audit_ngrams.add_argument("--countries", nargs="+")
    audit_ngrams.add_argument("--billing-project", required=True)
    audit_ngrams.add_argument("--location", default="US")
    audit_ngrams.add_argument(
        "--maximum-gb-billed", type=_positive_float, default=0.1
    )
    audit_ngrams.add_argument(
        "--output",
        type=Path,
        default=Path("data/audits/ngram-country-map.csv"),
    )

    firms = subparsers.add_parser(
        "collect-firms",
        help="collect global NASA FIRMS wildfire intensity by country and day",
    )
    firms.add_argument("--countries-config", type=Path, required=True)
    firms.add_argument("--start", type=_iso_date, required=True)
    firms.add_argument("--end", type=_iso_date, required=True)
    firms.add_argument(
        "--source", choices=sorted(FIRMS_ALLOWED_SOURCES), default=FIRMS_SOURCE
    )
    firms.add_argument(
        "--boundaries",
        type=Path,
        help="custom Natural Earth-style country GeoJSON; default is pinned and cached",
    )
    firms.add_argument(
        "--plan-only", action="store_true", help="show the global five-day request plan"
    )
    firms.add_argument("--data-dir", type=Path, default=Path("data"))
    _add_runtime_options(firms)

    gdacs = subparsers.add_parser(
        "collect-gdacs",
        help="collect global GDACS wildfire, flood, and tropical-cyclone events",
    )
    gdacs.add_argument("--countries-config", type=Path, required=True)
    gdacs.add_argument("--start", type=_iso_date, required=True)
    gdacs.add_argument("--end", type=_iso_date, required=True)
    gdacs.add_argument(
        "--plan-only", action="store_true", help="validate without making API requests"
    )
    gdacs.add_argument("--data-dir", type=Path, default=Path("data"))
    _add_runtime_options(gdacs)

    compare = subparsers.add_parser(
        "compare-sources", help="compare paired daily metrics from two sources"
    )
    compare.add_argument("--left-source", default="gdelt")
    compare.add_argument("--right-source", default="gdelt_ngrams")
    metric_choices = ("matched_count", "country_attention_share", "attention_index")
    compare.add_argument(
        "--left-metric", choices=metric_choices, default="country_attention_share"
    )
    compare.add_argument(
        "--right-metric", choices=metric_choices, default="matched_count"
    )
    compare.add_argument("--start", type=_iso_date, required=True)
    compare.add_argument("--end", type=_iso_date, required=True)
    compare.add_argument("--topics", nargs="+")
    compare.add_argument("--countries", nargs="+")
    compare.add_argument("--data-dir", type=Path, default=Path("data"))
    compare.add_argument(
        "--output", type=Path
    )

    export_articles = subparsers.add_parser(
        "export-articles",
        help="export stored matched articles and political flags to CSV",
    )
    export_articles.add_argument("--start", type=_iso_date)
    export_articles.add_argument("--end", type=_iso_date)
    export_articles.add_argument("--topics", nargs="+")
    export_articles.add_argument("--countries", nargs="+")
    export_articles.add_argument(
        "--political-only",
        action="store_true",
        help="only export rows matching at least one political signal",
    )
    export_articles.add_argument("--data-dir", type=Path, default=Path("data"))
    export_articles.add_argument("--output", type=Path, required=True)

    sync_supabase = subparsers.add_parser(
        "sync-supabase",
        help="upsert the matched-article Parquet panel into Supabase Postgres",
    )
    sync_supabase.add_argument("--data-dir", type=Path, default=Path("data"))
    sync_supabase.add_argument("--start", type=_iso_date)
    sync_supabase.add_argument("--end", type=_iso_date)
    sync_supabase.add_argument(
        "--topics", nargs="+", choices=sorted(MVP_TOPICS), default=sorted(MVP_TOPICS)
    )
    sync_supabase.add_argument(
        "--database-url",
        help="Postgres URL; defaults to SUPABASE_DB_URL in the environment or .env",
    )
    sync_supabase.add_argument(
        "--apply-migration",
        action="store_true",
        help="apply the bundled idempotent article schema before syncing",
    )
    sync_supabase.add_argument(
        "--migration",
        type=Path,
        default=Path("supabase/migrations/20260816193000_create_articles.sql"),
    )

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
    runs_retry.add_argument(
        "--maximum-gb-billed",
        type=_positive_float,
        help="override the per-window BigQuery cap for a GDELT NGrams run",
    )
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
        if args.command == "collect-google-trends":
            return _collect_google_trends(args)
        if args.command == "collect-ngrams":
            return _collect_ngrams(args)
        if args.command == "estimate-ngrams":
            return _estimate_ngrams(args)
        if args.command == "audit-ngram-countries":
            return _audit_ngram_countries(args)
        if args.command == "collect-firms":
            return _collect_firms(args)
        if args.command == "collect-gdacs":
            return _collect_gdacs(args)
        if args.command == "compare-sources":
            return _compare_sources(args)
        if args.command == "export-articles":
            return _export_articles(args)
        if args.command == "sync-supabase":
            return _sync_supabase(args)
        if args.command in {"aggregate", "rebuild-aggregates"}:
            return _aggregate(args.data_dir)
        if args.command == "runs":
            return _runs(args)
    except (ConfigError, ValueError, ProviderError) as exc:
        LOGGER.error("%s", exc)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


def _validate_config(path: Path) -> int:
    config = load_config(path)
    enabled = config.enabled_topics()
    query_count = sum(len(topic.queries) for topic in enabled)
    ngram_phrase_count = sum(len(topic.ngram_phrases) for topic in enabled)
    print(
        f"Valid configuration: {len(config.topics)} topic(s), "
        f"{len(enabled)} enabled, {query_count} configured query/queries, "
        f"{ngram_phrase_count} native-language NGram phrase(s)."
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
        raise ValueError(
            "unofficial Google Trends uses a country-aware durable workflow; "
            "run collect-google-trends instead"
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
    if state.source not in {
        "gdelt",
        "gdelt_timeline",
        "gdelt_source_country",
        "google_trends_unofficial",
        "gdelt_ngrams",
    }:
        raise ValueError(f"run {run_id} uses unsupported resumable source {state.source!r}")
    if option_overrides:
        if (
            "maximum_bytes_billed" in option_overrides
            and state.source != "gdelt_ngrams"
        ):
            raise ValueError(
                "--maximum-gb-billed can only override a GDELT NGrams run"
            )
        # Only explicitly supplied retry options should override the frozen values.
        state.provider_options.update(option_overrides)
        store.save(state)
    if state.source in {
        "gdelt_timeline",
        "gdelt_source_country",
        "google_trends_unofficial",
        "gdelt_ngrams",
    }:
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


def _collect_google_trends(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    country_config = load_country_config(args.countries_config)
    topics = config.enabled_topics(set(args.topics) if args.topics else None)
    countries = country_config.enabled_countries(
        set(args.countries) if args.countries else None
    )
    request = CollectionRequest(start=args.start, end=args.end, topics=topics)
    windows, country_geos = plan_google_trends_windows(request, countries)
    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    options = _runtime_options(args)
    if args.max_retries is None:
        options["max_retries"] = 2
    if args.request_interval is None:
        options["request_interval_seconds"] = 30.0
    if args.backoff_seconds is None:
        options["backoff_seconds"] = 60.0
    properties = {"web": "", "shopping": "froogle"}
    options.update(
        {
            "country_geos": country_geos,
            "country_labels": {
                country.id: country.label for country in countries
            },
            "category": args.category,
            "gprop": properties.get(args.property, args.property),
            "hl": args.hl,
            "tz": args.tz,
        }
    )
    store = RunStore(args.data_dir)
    state = store.create(
        run_id=run_id,
        source="google_trends_unofficial",
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
        f"Created unofficial Google Trends run {run_id}: {len(topics)} topic(s), "
        f"{len(countries)} country/countries, {len(windows)} planned request(s)."
    )
    print(
        "Each configured query and country is a separate 0-100 scaling group; "
        "raw levels must not be compared across those groups."
    )
    estimated_minutes = max(0, len(windows) - 1) * options[
        "request_interval_seconds"
    ] / 60
    print(
        f"Minimum pacing time: approximately {estimated_minutes:.1f} minutes, "
        "excluding response latency and retries."
    )
    if args.plan_only:
        print(f"Plan saved. Start it with: climate-attention runs retry {run_id}")
        return 0
    return _execute_timeline_run(state, args.data_dir, store)


def _collect_ngrams(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    country_config = load_country_config(args.countries_config)
    topics = config.enabled_topics(set(args.topics) if args.topics else None)
    countries = country_config.enabled_countries(
        set(args.countries) if args.countries else None
    )
    political = (
        load_political_config(args.political_config)
        if args.political_config
        else None
    )
    if args.save_articles and args.article_sample_size:
        raise ValueError("use either --save-articles or --article-sample-size, not both")
    article_output_size = -1 if args.save_articles else args.article_sample_size
    if article_output_size and political is None:
        raise ValueError("article output requires --political-config")
    if political is not None:
        selected_ids = {country.id for country in countries}
        unknown_domains = set(political.official_domains) - selected_ids
        if unknown_domains:
            raise ValueError(
                "political config has official domains outside the selected countries: "
                + ", ".join(sorted(unknown_domains))
            )
    request = CollectionRequest(start=args.start, end=args.end, topics=topics)
    windows, phrases = plan_ngram_windows(request, window_days=args.window_days)
    maximum_bytes = int(args.maximum_gb_billed * 1_000_000_000)
    options = {
        "billing_project": args.billing_project,
        "location": args.location,
        "maximum_bytes_billed": maximum_bytes,
        "country_labels": {
            country.id: country.ngram_label for country in countries
        },
        "topic_phrases": phrases,
        "batch_topics": True,
        "include_denominator": args.include_denominator,
        "political_signals": political.phrase_mapping() if political else None,
        "official_domains": political.official_domains if political else {},
        "article_sample_size": article_output_size,
        "save_all_articles": args.save_articles,
        "political_config": (
            {
                "path": str(args.political_config),
                "sha256": config_hash(args.political_config),
            }
            if political
            else None
        ),
    }
    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    store = RunStore(args.data_dir)
    state = store.create(
        run_id=run_id,
        source="gdelt_ngrams",
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
        f"Created GDELT NGrams run {run_id}: {len(topics)} topic(s), "
        f"{len(countries)} country/countries, {len(windows)} BigQuery job(s)."
    )
    print("All selected topics share one BigQuery scan per date window.")
    if political:
        article_message = (
            "Every matched article will be saved with GAL metadata; the "
            "Knowledge Graph is not queried."
            if args.save_articles
            else f"Validation sample: {args.article_sample_size} URL(s) per "
            "topic/country/day."
        )
        print(
            "Political actor, government-action, party-politics, and official-source "
            f"counts are computed over distinct topic URLs. {article_message}"
        )
    print(
        "Each job is dry-run first and cannot exceed the configured per-job "
        f"cap of {maximum_bytes / 1_000_000_000:.3f} GB."
    )
    denominator = "with GAL denominators" if args.include_denominator else "counts only"
    attribution = (
        "GDELT's April 2015 domain map plus the configured official-domain overrides"
        if political
        else "GDELT's April 2015 domain map"
    )
    print(
        f"Counts are distinct URLs; country attribution uses {attribution}, with "
        f"ambiguous and unmapped domains excluded ({denominator})."
    )
    if args.plan_only:
        print(f"Plan saved. Start it with: climate-attention runs retry {run_id}")
        return 0
    return _execute_timeline_run(state, args.data_dir, store)


def _estimate_ngrams(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    country_config = load_country_config(args.countries_config)
    topics = config.enabled_topics(set(args.topics) if args.topics else None)
    countries = country_config.enabled_countries(
        set(args.countries) if args.countries else None
    )
    political = (
        load_political_config(args.political_config)
        if args.political_config
        else None
    )
    if args.save_articles and args.article_sample_size:
        raise ValueError("use either --save-articles or --article-sample-size, not both")
    article_output_size = -1 if args.save_articles else args.article_sample_size
    if article_output_size and political is None:
        raise ValueError("article output requires --political-config")
    if political is not None:
        selected_ids = {country.id for country in countries}
        unknown_domains = set(political.official_domains) - selected_ids
        if unknown_domains:
            raise ValueError(
                "political config has official domains outside the selected countries: "
                + ", ".join(sorted(unknown_domains))
            )
    request = CollectionRequest(start=args.start, end=args.end, topics=topics)
    windows, phrases = plan_ngram_windows(request, window_days=args.window_days)
    labels = {country.id: country.ngram_label for country in countries}
    executor = GoogleBigQueryExecutor(
        project=args.billing_project, location=args.location
    )
    estimates = estimate_ngram_windows(
        windows,
        executor=executor,
        country_labels=labels,
        phrases_by_topic=phrases,
        include_denominator=args.include_denominator,
        political_signals=political.phrase_mapping() if political else None,
        official_domains=political.official_domains if political else None,
        article_sample_size=article_output_size,
    )
    for estimate in estimates:
        gb = estimate["estimated_bytes_processed"] / 1_000_000_000
        topic_label = ",".join(estimate["topic_ids"])
        print(
            f"batch[{topic_label}]: {estimate['start']}..{estimate['end']} "
            f"{gb:.3f} GB"
        )
    total = sum(item["estimated_bytes_processed"] for item in estimates)
    maximum = max(
        (item["estimated_bytes_processed"] for item in estimates), default=0
    )
    print(
        f"Dry-run total across {len(estimates)} job(s): "
        f"{total / 1_000_000_000:.3f} GB; largest job: "
        f"{maximum / 1_000_000_000:.3f} GB."
    )
    print("Dry runs do not process data or incur query charges.")
    return 0


def _audit_ngram_countries(args: argparse.Namespace) -> int:
    country_config = load_country_config(args.countries_config)
    countries = country_config.enabled_countries(
        set(args.countries) if args.countries else None
    )
    executor = GoogleBigQueryExecutor(
        project=args.billing_project, location=args.location
    )
    rows, job = audit_country_mapping(
        executor=executor,
        country_labels={country.id: country.ngram_label for country in countries},
        maximum_bytes_billed=int(args.maximum_gb_billed * 1_000_000_000),
    )
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "country_id",
                "country_label",
                "mapped_domain_count",
                "mapping_supported",
                "sample_domains",
                "suggested_labels",
            ),
        )
        writer.writeheader()
        for row in rows:
            mapped = int(row["mapped_domain_count"])
            writer.writerow(
                {
                    **row,
                    "mapping_supported": mapped > 0,
                    "sample_domains": "|".join(row.get("sample_domains") or []),
                    "suggested_labels": "|".join(
                        row.get("suggested_labels") or []
                    ),
                }
            )
    unsupported = sum(int(row["mapped_domain_count"]) == 0 for row in rows)
    print(
        f"Audited {len(rows)} country/countries: {len(rows) - unsupported} mapped, "
        f"{unsupported} unsupported. Wrote {output}."
    )
    print(
        f"BigQuery estimate: {job['estimated_bytes_processed'] / 1_000_000_000:.3f} "
        f"GB; billed: {job['total_bytes_billed'] / 1_000_000_000:.3f} GB."
    )
    return 0


def _collect_firms(args: argparse.Namespace) -> int:
    country_config = load_country_config(args.countries_config)
    countries = country_config.enabled_countries()
    windows = plan_firms_windows(args.start, args.end)
    if args.plan_only:
        interval = args.request_interval if args.request_interval is not None else 25.0
        print(
            f"Global FIRMS plan: {len(windows)} non-overlapping request(s), "
            f"{len(countries)} configured countries, {args.start}..{args.end}."
        )
        print(
            "Each request uses the FIRMS world area and at most five days; raw CSV "
            "windows are cached for safe resumption."
        )
        print(
            f"Minimum deliberate pacing: {max(0, len(windows) - 1) * interval / 60:.1f} "
            "minutes, excluding download and country-assignment time."
        )
        return 0

    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    storage = LocalParquetStorage(args.data_dir)
    key = firms_map_key()
    # FIRMS embeds its secret map key in the request path. Suppress httpx's
    # otherwise helpful request URL logging for this command.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    boundary_path = args.boundaries or (
        args.data_dir / "reference" / NATURAL_EARTH_FILENAME
    )
    if args.boundaries is None:
        ensure_natural_earth_boundaries(boundary_path)
    boundary_index = load_country_boundaries(boundary_path, countries)
    options = _runtime_options(args)
    if args.request_interval is None:
        options["request_interval_seconds"] = 25.0
    requests: list[dict] = []
    try:
        with FIRMSProvider(
            map_key=key,
            source=args.source,
            boundary_index=boundary_index,
            countries=countries,
            cache_dir=args.data_dir / "raw_events" / "firms",
            max_retries=options["max_retries"],
            backoff_seconds=options["backoff_seconds"],
            request_interval_seconds=options["request_interval_seconds"],
        ) as provider:
            observations, requests, totals = provider.collect(args.start, args.end)
        added = storage.write_hazards(observations)
    except ProviderError as exc:
        storage.write_manifest(
            run_id,
            _event_manifest(
                run_id=run_id,
                source="firms",
                status="failed",
                started_at=started_at,
                start=args.start,
                end=args.end,
                country_config=args.countries_config,
                provider_options={
                    "product": args.source,
                    "area": "world",
                    "map_key_stored": False,
                },
                requests=requests,
                summary={},
                error=str(exc),
            ),
        )
        raise
    unsupported = sorted(
        country.id
        for country in countries
        if country.id not in boundary_index.supported_country_ids
    )
    manifest_path = storage.write_manifest(
        run_id,
        _event_manifest(
            run_id=run_id,
            source="firms",
            status="success",
            started_at=started_at,
            start=args.start,
            end=args.end,
            country_config=args.countries_config,
            provider_options={
                "product": args.source,
                "area": "world",
                "window_days": 5,
                "map_key_stored": False,
                "boundary_path": str(boundary_path),
            },
            requests=requests,
            summary={
                **totals,
                "daily_rows": len(observations),
                "daily_rows_newly_stored": added,
                "boundary_supported_countries": len(countries) - len(unsupported),
                "boundary_unsupported_countries": unsupported,
            },
        ),
    )
    print(
        f"Global FIRMS collection complete: {totals['rows_retained']:,} retained "
        f"detections, {len(observations):,} country-day rows ({added:,} new)."
    )
    print(
        f"Dataset: {args.data_dir / 'hazards'}. Manifest: {manifest_path}. "
        f"Unassigned detections: {totals['rows_unassigned']:,}."
    )
    if unsupported:
        print(
            "Boundary coverage is unavailable for: " + ", ".join(unsupported) + ". "
            "Those rows contain null measurements, not false zeroes."
        )
    return 0


def _collect_gdacs(args: argparse.Namespace) -> int:
    country_config = load_country_config(args.countries_config)
    countries = country_config.enabled_countries()
    if args.end < args.start:
        raise ValueError("GDACS end date must not precede start date")
    if args.plan_only:
        print(
            f"GDACS plan: wildfire, flood, and tropical-cyclone events for "
            f"{args.start}..{args.end}, mapped to {len(countries)} configured countries."
        )
        print("Responses will be paged in batches of 100 and cached as GeoJSON.")
        return 0

    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    storage = LocalParquetStorage(args.data_dir)
    options = _runtime_options(args)
    if args.request_interval is None:
        options["request_interval_seconds"] = 1.0
    if args.backoff_seconds is None:
        options["backoff_seconds"] = 5.0
    requests: list[dict] = []
    try:
        with GDACSProvider(
            countries=countries,
            cache_dir=args.data_dir / "raw_events" / "gdacs",
            max_retries=options["max_retries"],
            backoff_seconds=options["backoff_seconds"],
            request_interval_seconds=options["request_interval_seconds"],
        ) as provider:
            events, requests = provider.collect(args.start, args.end)
        added = storage.write_events(events)
    except ProviderError as exc:
        storage.write_manifest(
            run_id,
            _event_manifest(
                run_id=run_id,
                source="gdacs",
                status="failed",
                started_at=started_at,
                start=args.start,
                end=args.end,
                country_config=args.countries_config,
                provider_options={"event_types": ["WF", "FL", "TC"]},
                requests=requests,
                summary={},
                error=str(exc),
            ),
        )
        raise
    counts = {
        hazard: sum(event.hazard_type == hazard for event in events)
        for hazard in ("wildfire", "flood", "tropical_cyclone")
    }
    unmatched = sorted(
        {
            iso3
            for event in events
            for iso3 in event.metadata.get("unmatched_country_iso3s", [])
        }
    )
    manifest_path = storage.write_manifest(
        run_id,
        _event_manifest(
            run_id=run_id,
            source="gdacs",
            status="success",
            started_at=started_at,
            start=args.start,
            end=args.end,
            country_config=args.countries_config,
            provider_options={
                "event_types": ["WF", "FL", "TC"],
                "alert_levels": ["green", "orange", "red"],
                "page_size": 100,
            },
            requests=requests,
            summary={
                "events_collected": len(events),
                "events_newly_stored": added,
                "events_by_hazard": counts,
                "unmatched_country_iso3s": unmatched,
            },
        ),
    )
    print(
        f"GDACS collection complete: {len(events):,} event(s) ({added:,} new): "
        f"{counts['wildfire']} wildfire, {counts['flood']} flood, "
        f"{counts['tropical_cyclone']} tropical cyclone."
    )
    print(f"Dataset: {args.data_dir / 'events'}. Manifest: {manifest_path}.")
    return 0


def _event_manifest(
    *,
    run_id: str,
    source: str,
    status: str,
    started_at: datetime,
    start: date,
    end: date,
    country_config: Path,
    provider_options: dict,
    requests: list[dict],
    summary: dict,
    error: str | None = None,
) -> dict:
    return {
        "manifest_version": 1,
        "run_id": run_id,
        "status": status,
        "source": source,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "requested_date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "country_config": {
            "path": str(country_config),
            "sha256": config_hash(country_config),
        },
        "provider_options": provider_options,
        "requests": requests,
        "summary": summary,
        "software": {
            "package": "climate-attention",
            "version": package_version(),
            "python": sys.version.split()[0],
        },
        "error": error,
    }


def _compare_sources(args: argparse.Namespace) -> int:
    if args.end < args.start:
        raise ValueError("end date must be on or after start date")
    storage = LocalParquetStorage(args.data_dir)
    topics = set(args.topics) if args.topics else None
    countries = set(args.countries) if args.countries else None
    trends = storage.read_trends(
        start=args.start,
        end=args.end,
        topics=topics,
        geographies=countries,
    )
    comparisons = compare_trends(
        trends,
        left_source=args.left_source,
        right_source=args.right_source,
        left_metric=args.left_metric,
        right_metric=args.right_metric,
    )
    output = args.output or args.data_dir / "comparisons/source_comparison.csv"
    path = write_comparisons(output, comparisons)
    print(f"Wrote {len(comparisons)} paired source comparison(s) to {path}.")
    if not comparisons:
        print("No dimensions had non-null selected metrics in both sources.")
    return 0


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
            political_samples = [
                item
                for item in observations
                if isinstance(item, PoliticalArticleSample)
            ]
            # Coverage is written first so topic rows receive their country
            # denominator immediately; it also refreshes matching older rows.
            state.records_newly_stored += storage.write_country_coverages(coverages)
            state.records_newly_stored += storage.write_trends(trends)
            state.records_newly_stored += storage.write_matched_articles(
                political_samples
            )
        state.apply_window_event(event, window, log, children)
        store.save(state)

    if state.source == "google_trends_unofficial":
        provider_class = GoogleTrendsUnofficialProvider
    elif state.source == "gdelt_ngrams":
        provider_class = GDELTNGramsProvider
    elif state.source == "gdelt_source_country":
        provider_class = GDELTSourceCountryProvider
    else:
        provider_class = GDELTTimelineProvider
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
            f"{state.records_newly_stored} new stored row(s) across its datasets."
        )
    print(
        f"Windows: {counts}. Manifest: {manifest_path}. "
        f"Trend dataset: {storage.root / 'trends'}."
    )
    if state.source == "gdelt_ngrams" and state.provider_options.get(
        "article_sample_size", 0
    ):
        print(f"Matched article dataset: {storage.root / 'articles'}.")
    return exit_code


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
                "maximum_bytes_billed": (
                    int(args.maximum_gb_billed * 1_000_000_000)
                    if args.maximum_gb_billed is not None
                    else None
                ),
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


def _sync_supabase(args: argparse.Namespace) -> int:
    if args.start and args.end and args.end < args.start:
        raise ValueError("Supabase sync end date must not precede start date")
    database_url = args.database_url or dotenv_value("SUPABASE_DB_URL")
    if not database_url:
        raise ValueError(
            "missing SUPABASE_DB_URL; add it to .env or pass --database-url"
        )
    copied, files = sync_articles(
        database_url=database_url,
        data_dir=args.data_dir,
        migration_path=args.migration,
        topics=set(args.topics),
        start=args.start,
        end=args.end,
        apply_migration=args.apply_migration,
    )
    print(
        f"Supabase article sync complete: {copied:,} row(s) upserted "
        f"from {files:,} Parquet partition(s)."
    )
    return 0


def _export_articles(args: argparse.Namespace) -> int:
    if args.start and args.end and args.end < args.start:
        raise ValueError("article export end date must not precede start date")
    storage = LocalParquetStorage(args.data_dir)
    articles = storage.read_matched_articles(
        source="gdelt_ngrams",
        topics=set(args.topics) if args.topics else None,
        geographies=set(args.countries) if args.countries else None,
        start=args.start,
        end=args.end,
    )
    if args.political_only:
        articles = [article for article in articles if article.political]
    fields = (
        "record_id",
        "date",
        "source",
        "topic_id",
        "geography",
        "url",
        "domain",
        "published_at",
        "outlet_name",
        "outlet_logo",
        "outlet_twitter",
        "title",
        "image_url",
        "description",
        "language",
        "author",
        "political",
        "political_actor",
        "government_action",
        "party_politics",
        "official_source",
        "matched_topic_phrases",
        "matched_political_phrases",
        "match_evidence_total",
        "match_evidence_truncated",
        "match_evidence_json",
        "collected_at",
        "metadata_json",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for article in articles:
            row = article.model_dump(exclude={"metadata", "match_evidence"})
            row["political"] = article.political
            row["matched_topic_phrases"] = " | ".join(
                dict.fromkeys(
                    item.phrase
                    for item in article.match_evidence
                    if item.evidence_kind == "topic"
                )
            )
            row["matched_political_phrases"] = " | ".join(
                dict.fromkeys(
                    item.phrase
                    for item in article.match_evidence
                    if item.evidence_kind == "political_signal"
                )
            )
            row["match_evidence_json"] = json.dumps(
                [item.model_dump(mode="json") for item in article.match_evidence],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            for field in ("date", "published_at", "collected_at"):
                value = row.get(field)
                row[field] = value.isoformat() if value is not None else ""
            row["metadata_json"] = json.dumps(
                article.metadata, ensure_ascii=False, sort_keys=True, default=str
            )
            writer.writerow(row)
    print(f"Exported {len(articles)} article classification row(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
