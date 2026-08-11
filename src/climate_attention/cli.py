"""Command-line interface for collection and aggregation."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from .aggregation import aggregate_daily
from .config import ConfigError, load_config
from .manifest import build_manifest
from .models import CollectionRequest, ProviderResult
from .sources import (
    GDELTProvider,
    GoogleTrendsProvider,
    ProviderCollectionError,
    ProviderUnavailableError,
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

    collect = subparsers.add_parser("collect", help="collect data from one provider")
    collect.add_argument(
        "--source",
        required=True,
        choices=("gdelt", "google-trends", "google_trends"),
    )
    collect.add_argument("--config", type=Path, default=Path("config/topics.yaml"))
    collect.add_argument("--start", type=_iso_date, required=True)
    collect.add_argument("--end", type=_iso_date, required=True)
    collect.add_argument("--topics", nargs="+", help="only collect these topic ids")
    collect.add_argument("--data-dir", type=Path, default=Path("data"))
    collect.add_argument("--timeout", type=float, default=30.0)
    collect.add_argument("--max-retries", type=int, default=3)

    aggregate = subparsers.add_parser(
        "aggregate", aliases=["rebuild-aggregates"], help="rebuild daily Parquet"
    )
    aggregate.add_argument("--data-dir", type=Path, default=Path("data"))
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
        if args.command == "collect":
            return _collect(args)
        if args.command in {"aggregate", "rebuild-aggregates"}:
            return _aggregate(args.data_dir)
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


def _collect(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    selected = set(args.topics) if args.topics else None
    topics = config.enabled_topics(selected)
    request = CollectionRequest(start=args.start, end=args.end, topics=topics)
    storage = LocalParquetStorage(args.data_dir)
    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    source = args.source.replace("-", "_")

    if source == "gdelt":
        provider = GDELTProvider(
            timeout=args.timeout,
            max_retries=args.max_retries,
            response_sink=lambda envelope: storage.append_api_response(
                "gdelt", run_id, envelope
            ),
        )
    else:
        provider = GoogleTrendsProvider()

    result = ProviderResult()
    status = "success"
    error: str | None = None
    try:
        with provider:
            result = provider.collect(request)
    except ProviderCollectionError as exc:
        result = exc.result
        status = "failed"
        error = str(exc)
    except ProviderUnavailableError as exc:
        status = "failed"
        error = str(exc)

    added = storage.write_records(result.records)
    manifest = build_manifest(
        run_id=run_id,
        source=source,
        status=status,
        started_at=started_at,
        start=args.start,
        end=args.end,
        config_path=args.config,
        topics=topics,
        result=result,
        records_newly_stored=added,
        error=error,
    )
    manifest_path = storage.write_manifest(run_id, manifest)

    if status == "failed":
        LOGGER.error("Collection failed: %s", error)
        LOGGER.error("Failure manifest: %s", manifest_path)
        return 1

    observations = aggregate_daily(storage.read_records())
    aggregate_path = storage.write_daily(observations)
    print(
        f"Collected {len(result.records)} record(s); {added} new. "
        f"Manifest: {manifest_path}. Daily aggregates: {aggregate_path}."
    )
    return 0


def _aggregate(data_dir: Path) -> int:
    storage = LocalParquetStorage(data_dir)
    records = storage.read_records()
    observations = aggregate_daily(records)
    path = storage.write_daily(observations)
    print(f"Wrote {len(observations)} daily row(s) from {len(records)} record(s) to {path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

