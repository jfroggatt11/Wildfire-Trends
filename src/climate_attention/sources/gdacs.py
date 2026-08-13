"""GDACS multi-hazard major-event catalogue adapter."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

from ..config import Country
from ..geography import country_iso3
from ..models import HazardEvent
from .base import ProviderError


GDACS_SEARCH_URL = (
    "https://www.gdacs.org/gdacsapi/api/Events/geteventlist/search"
)
EVENT_TYPES = {
    "WF": "wildfire",
    "FL": "flood",
    "TC": "tropical_cyclone",
}


class GDACSProvider:
    """Collect the free GDACS catalogue with durable page-level caching."""

    def __init__(
        self,
        *,
        countries: Iterable[Country],
        cache_dir: Path,
        client: httpx.Client | None = None,
        page_size: int = 100,
        max_retries: int = 3,
        backoff_seconds: float = 5.0,
        request_interval_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= page_size <= 100:
            raise ValueError("GDACS page size must be between 1 and 100")
        self.by_iso3 = {country_iso3(country): country for country in countries}
        self.cache_dir = cache_dir
        self.page_size = page_size
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_interval_seconds = request_interval_seconds
        self.sleep = sleep
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)

    def __enter__(self) -> "GDACSProvider":
        return self

    def __exit__(self, *_: object) -> None:
        if self._owns_client:
            self.client.close()

    def collect(
        self, start: date, end: date
    ) -> tuple[list[HazardEvent], list[dict[str, Any]]]:
        if end < start:
            raise ValueError("GDACS end date must not precede start date")
        by_id: dict[str, HazardEvent] = {}
        requests: list[dict[str, Any]] = []
        page_number = 1
        while True:
            document, request = self._obtain_page(start, end, page_number)
            requests.append(request)
            features = document.get("features")
            if document.get("type") != "FeatureCollection" or not isinstance(
                features, list
            ):
                raise ProviderError(
                    f"GDACS page {page_number} is not a GeoJSON FeatureCollection"
                )
            for feature in features:
                event = self._parse_feature(feature)
                previous = by_id.get(event.record_id)
                if previous is None or _event_is_newer(event, previous):
                    by_id[event.record_id] = event
            if len(features) < self.page_size:
                break
            page_number += 1
            if page_number > 10_000:
                raise ProviderError("GDACS pagination exceeded safety limit")
            if not request["cached"]:
                self.sleep(self.request_interval_seconds)
        return sorted(by_id.values(), key=lambda item: (item.start_at, item.record_id)), requests

    def _obtain_page(
        self, start: date, end: date, page_number: int
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        stem = f"{start.isoformat()}_{end.isoformat()}_page{page_number:04d}"
        path = self.cache_dir / f"{stem}.geojson"
        if path.exists():
            document = _read_document(path)
            return document, _request_metadata(
                path, page_number=page_number, attempts=0, cached=True
            )
        params = {
            "eventlist": ";".join(EVENT_TYPES),
            "alertlevel": "green;orange;red",
            "fromDate": start.isoformat(),
            "toDate": end.isoformat(),
            "pageSize": self.page_size,
            "pageNumber": page_number,
            "caller": "climate-attention-research",
        }
        error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.client.get(GDACS_SEARCH_URL, params=params)
                response.raise_for_status()
                document = response.json()
                if not isinstance(document, dict):
                    raise ProviderError("GDACS returned a non-object response")
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".geojson.tmp")
                temporary.write_text(
                    json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, path)
                return document, _request_metadata(
                    path, page_number=page_number, attempts=attempt, cached=False
                )
            except (httpx.HTTPError, json.JSONDecodeError, OSError, ProviderError) as exc:
                error = exc
                if attempt > self.max_retries:
                    break
                self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        raise ProviderError(
            f"GDACS page {page_number} failed after {self.max_retries + 1} "
            f"attempt(s): {error}"
        )

    def _parse_feature(self, feature: Any) -> HazardEvent:
        if not isinstance(feature, dict):
            raise ProviderError("GDACS feature is not an object")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ProviderError("GDACS feature has no properties")
        event_code = str(properties.get("eventtype", "")).upper()
        hazard_type = EVENT_TYPES.get(event_code)
        event_id = properties.get("eventid")
        if hazard_type is None or event_id is None:
            raise ProviderError("GDACS feature lacks a supported event type or id")
        iso3s = _affected_iso3s(properties)
        geography_ids = sorted(
            {
                self.by_iso3[iso3].id
                for iso3 in iso3s
                if iso3 in self.by_iso3
            }
        )
        severity_data = properties.get("severitydata") or {}
        urls = properties.get("url") or {}
        start_at = _gdacs_datetime(properties.get("fromdate"), required=True)
        end_at = _gdacs_datetime(properties.get("todate"))
        source_updated_at = _gdacs_datetime(properties.get("datemodified"))
        name = str(
            properties.get("name")
            or properties.get("description")
            or f"{hazard_type} {event_id}"
        ).strip()
        return HazardEvent(
            record_id=f"gdacs:{event_code}:{event_id}",
            source="gdacs",
            source_event_id=f"{event_code}:{event_id}",
            hazard_type=hazard_type,
            name=name,
            start_at=start_at,
            end_at=end_at,
            geography_ids=geography_ids,
            country_iso3s=iso3s,
            alert_level=_optional_string(properties.get("alertlevel")),
            alert_score=_optional_float(properties.get("alertscore")),
            severity=_optional_float(severity_data.get("severity")),
            severity_unit=_optional_string(severity_data.get("severityunit")),
            source_url=_optional_string(urls.get("report")),
            source_updated_at=source_updated_at,
            geometry=feature.get("geometry"),
            metadata={
                "episode_id": properties.get("episodeid"),
                "episode_alert_level": properties.get("episodealertlevel"),
                "episode_alert_score": properties.get("episodealertscore"),
                "provider_hazard_code": event_code,
                "provider_source": properties.get("source"),
                "provider_source_id": properties.get("sourceid"),
                "severity_text": severity_data.get("severitytext"),
                "details_url": urls.get("details"),
                "geometry_url": urls.get("geometry"),
                "unmatched_country_iso3s": [
                    iso3 for iso3 in iso3s if iso3 not in self.by_iso3
                ],
            },
        )


def _gdacs_datetime(value: Any, *, required: bool = False) -> datetime | None:
    if value in (None, ""):
        if required:
            raise ProviderError("GDACS event has no start timestamp")
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderError(f"invalid GDACS timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _affected_iso3s(properties: dict[str, Any]) -> list[str]:
    values = []
    affected = properties.get("affectedcountries") or []
    if isinstance(affected, list):
        values.extend(
            str(item.get("iso3", "")).upper()
            for item in affected
            if isinstance(item, dict)
        )
    values.append(str(properties.get("iso3", "")).upper())
    return sorted({value for value in values if len(value) == 3})


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"invalid GDACS numeric value: {value!r}") from exc


def _event_is_newer(candidate: HazardEvent, previous: HazardEvent) -> bool:
    return (candidate.source_updated_at or candidate.collected_at) > (
        previous.source_updated_at or previous.collected_at
    )


def _read_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"invalid GDACS cache {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ProviderError(f"GDACS cache is not an object: {path}")
    return document


def _request_metadata(
    path: Path, *, page_number: int, attempts: int, cached: bool
) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "page_number": page_number,
        "status": "success",
        "attempts": attempts,
        "cached": cached,
        "cache_path": str(path),
        "sha256": digest,
    }
