"""Collection run provenance manifests."""

from __future__ import annotations

import platform
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from .config import config_hash
from .models import ProviderResult, Query, Topic
from .run_state import CollectionRunState


def package_version() -> str:
    try:
        return version("climate-attention")
    except PackageNotFoundError:
        from . import __version__

        return __version__


def build_manifest(
    *,
    run_id: str,
    source: str,
    status: Literal["success", "failed"],
    started_at: datetime,
    start: date,
    end: date,
    config_path: str | Path,
    topics: list[Topic],
    result: ProviderResult,
    records_newly_stored: int,
    error: str | None = None,
) -> dict[str, Any]:
    path = Path(config_path)
    return {
        "manifest_version": 1,
        "run_id": run_id,
        "status": status,
        "source": source,
        "started_at": started_at.astimezone(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "requested_date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "config": {"path": str(path), "sha256": config_hash(path)},
        "topics": [topic.model_dump(mode="json") for topic in topics],
        "expanded_queries": [
            query.model_dump(mode="json")
            for topic in topics
            for query in Query.from_topic(topic)
        ],
        "requests": [item.model_dump(mode="json") for item in result.requests],
        "summary": {
            "successful_requests": sum(
                item.status == "success" for item in result.requests
            ),
            "failed_requests": sum(item.status == "failed" for item in result.requests),
            "records_collected": len(result.records),
            "records_newly_stored": records_newly_stored,
        },
        "software": {
            "package": "climate-attention",
            "version": package_version(),
            "python": platform.python_version(),
        },
        "error": error,
    }


def build_run_manifest(state: CollectionRunState) -> dict[str, Any]:
    """Build a reproducibility manifest from durable run state."""
    counts = state.status_counts()
    logs = state.request_logs()
    if state.source == "gdelt_timeline":
        query_values = {
            (
                window.query.topic_id,
                window.query.query_id,
                window.query.geography,
                window.query.language,
            ): window.query
            for window in state.windows.values()
        }.values()
    else:
        query_values = [
            query for topic in state.topics for query in Query.from_topic(topic)
        ]
    return {
        "manifest_version": 2,
        "run_id": state.run_id,
        "status": state.status,
        "source": state.source,
        "started_at": state.created_at.isoformat(),
        "finished_at": state.finished_at.isoformat() if state.finished_at else None,
        "requested_date_range": {
            "start": state.requested_start.isoformat(),
            "end": state.requested_end.isoformat(),
        },
        "config": {
            "original_path": state.original_config_path,
            "snapshot_path": state.config_snapshot_path,
            "sha256": state.config_sha256,
        },
        "country_config": (
            {
                "original_path": state.country_config_path,
                "snapshot_path": state.country_config_snapshot_path,
                "sha256": state.country_config_sha256,
            }
            if state.country_config_path
            else None
        ),
        "topics": [topic.model_dump(mode="json") for topic in state.topics],
        "expanded_queries": [query.model_dump(mode="json") for query in query_values],
        "provider_options": state.provider_options,
        "requests": [log.model_dump(mode="json") for log in logs],
        "summary": {
            **{f"{key}_windows": value for key, value in counts.items()},
            "records_collected": sum(
                item.records_returned
                for item in state.windows.values()
                if item.status == "success"
            ),
            "records_newly_stored": state.records_newly_stored,
        },
        "software": {
            "package": "climate-attention",
            "version": package_version(),
            "python": platform.python_version(),
        },
        "error": state.error,
    }
