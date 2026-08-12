"""Durable collection run planning and checkpoint state."""

from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import Query, RequestLog, StrictModel, Topic
from .sources.gdelt import GDELTWindow


RunStatus = Literal["planned", "running", "complete", "failed", "interrupted"]
WindowStatus = Literal["pending", "running", "success", "failed", "split"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunWindow(StrictModel):
    window_id: str
    parent_window_id: str | None = None
    query: Query
    start: datetime
    end: datetime
    status: WindowStatus = "pending"
    attempts: int = Field(default=0, ge=0)
    records_returned: int = Field(default=0, ge=0)
    http_status: int | None = None
    error: str | None = None
    updated_at: datetime = Field(default_factory=_now)

    @classmethod
    def from_gdelt(cls, window: GDELTWindow) -> "RunWindow":
        return cls(
            window_id=window.window_id,
            parent_window_id=window.parent_window_id,
            query=window.query,
            start=window.start,
            end=window.end,
        )

    def to_gdelt(self) -> GDELTWindow:
        return GDELTWindow(
            query=self.query,
            start=self.start,
            end=self.end,
            parent_window_id=self.parent_window_id,
        )

    def to_request_log(self) -> RequestLog | None:
        if self.status not in {"success", "failed", "split"}:
            return None
        return RequestLog(
            window_id=self.window_id,
            parent_window_id=self.parent_window_id,
            query_id=self.query.query_id,
            topic_id=self.query.topic_id,
            start=self.start,
            end=self.end,
            status=self.status,
            attempts=self.attempts,
            records_returned=self.records_returned,
            http_status=self.http_status,
            error=self.error,
        )


class CollectionRunState(StrictModel):
    state_version: Literal[1] = 1
    run_id: str
    source: str
    status: RunStatus = "planned"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    requested_start: date
    requested_end: date
    original_config_path: str
    config_snapshot_path: str
    config_sha256: str
    country_config_path: str | None = None
    country_config_snapshot_path: str | None = None
    country_config_sha256: str | None = None
    topics: list[Topic]
    provider_options: dict[str, Any] = Field(default_factory=dict)
    windows: dict[str, RunWindow] = Field(default_factory=dict)
    records_newly_stored: int = Field(default=0, ge=0)
    error: str | None = None

    def resumable_windows(self) -> list[GDELTWindow]:
        work = [
            item.to_gdelt()
            for item in self.windows.values()
            if item.status in {"pending", "running", "failed"}
        ]
        return sorted(
            work,
            key=lambda window: (
                window.start,
                window.query.topic_id,
                window.query.query_id,
                window.query.language or "",
                window.query.geography or "",
                ",".join(window.query.geographies),
            ),
        )

    def is_complete(self) -> bool:
        return bool(self.windows) and all(
            item.status in {"success", "split"} for item in self.windows.values()
        )

    def request_logs(self) -> list[RequestLog]:
        logs = [item.to_request_log() for item in self.windows.values()]
        return sorted(
            (item for item in logs if item is not None),
            key=lambda item: (item.start, item.topic_id, item.query_id),
        )

    def status_counts(self) -> dict[str, int]:
        return {
            status: sum(item.status == status for item in self.windows.values())
            for status in ("pending", "running", "success", "failed", "split")
        }

    def mark_started(self) -> None:
        self.status = "running"
        self.finished_at = None
        self.error = None
        self.updated_at = _now()

    def mark_finished(self, status: Literal["complete", "failed", "interrupted"], error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.finished_at = _now()
        self.updated_at = self.finished_at

    def apply_window_event(
        self,
        event: str,
        window: GDELTWindow,
        log: RequestLog | None,
        children: list[GDELTWindow],
    ) -> None:
        item = self.windows.setdefault(window.window_id, RunWindow.from_gdelt(window))
        if event == "started":
            item.status = "running"
            item.error = None
        elif event in {"success", "failed", "split"}:
            if log is None:
                raise ValueError(f"{event} checkpoint requires a request log")
            item.status = event
            item.attempts += log.attempts
            item.records_returned = log.records_returned
            item.http_status = log.http_status
            item.error = log.error
        else:
            raise ValueError(f"unknown window event: {event}")
        item.updated_at = _now()
        for child in children:
            self.windows.setdefault(child.window_id, RunWindow.from_gdelt(child))
        self.updated_at = item.updated_at


class RunStore:
    """Atomic JSON persistence for operational collection state."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.root = Path(data_root) / "runs"

    def create(
        self,
        *,
        run_id: str,
        source: str,
        start: date,
        end: date,
        config_path: str | Path,
        config_sha256: str,
        country_config_path: str | Path | None = None,
        country_config_sha256: str | None = None,
        topics: list[Topic],
        provider_options: dict[str, Any],
        windows: list[GDELTWindow],
    ) -> CollectionRunState:
        directory = self.root / run_id
        if directory.exists():
            raise ValueError(f"run already exists: {run_id}")
        directory.mkdir(parents=True)
        snapshot = directory / "config.yaml"
        shutil.copyfile(config_path, snapshot)
        country_snapshot: Path | None = None
        if country_config_path is not None:
            country_snapshot = directory / "countries.yaml"
            shutil.copyfile(country_config_path, country_snapshot)
        state = CollectionRunState(
            run_id=run_id,
            source=source,
            requested_start=start,
            requested_end=end,
            original_config_path=str(config_path),
            config_snapshot_path=str(snapshot),
            config_sha256=config_sha256,
            country_config_path=(
                str(country_config_path) if country_config_path is not None else None
            ),
            country_config_snapshot_path=(
                str(country_snapshot) if country_snapshot is not None else None
            ),
            country_config_sha256=country_config_sha256,
            topics=topics,
            provider_options=provider_options,
            windows={window.window_id: RunWindow.from_gdelt(window) for window in windows},
        )
        self.save(state)
        return state

    def save(self, state: CollectionRunState) -> Path:
        path = self.state_path(state.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def load(self, run_id: str) -> CollectionRunState:
        path = self.state_path(run_id)
        try:
            return CollectionRunState.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"unknown run id: {run_id}") from exc

    def list(self) -> list[CollectionRunState]:
        if not self.root.exists():
            return []
        states: list[CollectionRunState] = []
        for path in self.root.glob("*/state.json"):
            states.append(
                CollectionRunState.model_validate_json(path.read_text(encoding="utf-8"))
            )
        return sorted(states, key=lambda state: state.created_at, reverse=True)

    def state_path(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id:
            raise ValueError("invalid run id")
        return self.root / run_id / "state.json"
