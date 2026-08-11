"""Collection run provenance manifests."""

from __future__ import annotations

import platform
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from .config import config_hash
from .models import ProviderResult, Query, Topic


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
