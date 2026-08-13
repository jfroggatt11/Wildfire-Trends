"""Global NASA FIRMS active-fire collection and country-day aggregation."""

from __future__ import annotations

import csv
import hashlib
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

from ..config import Country
from ..geography import CountryBoundaryIndex, country_iso3
from ..models import DailyHazard
from .base import ProviderError


FIRMS_API_ROOT = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_SOURCE = "VIIRS_SNPP_SP"
ALLOWED_SOURCES = {
    "VIIRS_SNPP_SP",
    "VIIRS_NOAA20_SP",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
}
REQUIRED_COLUMNS = {
    "latitude",
    "longitude",
    "acq_date",
    "confidence",
    "frp",
    "type",
}

NATURAL_EARTH_REVISION = "ca96624a56bd078437bca8184e78163e5039ad19"
NATURAL_EARTH_FILENAME = "ne_50m_admin_0_countries.geojson"
NATURAL_EARTH_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{NATURAL_EARTH_REVISION}/geojson/{NATURAL_EARTH_FILENAME}"
)
NATURAL_EARTH_SHA256 = (
    "3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb"
)


@dataclass(frozen=True)
class FirmsWindow:
    start: date
    end: date

    @property
    def day_range(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def window_id(self) -> str:
        return f"{self.start.isoformat()}_{self.end.isoformat()}"


def plan_firms_windows(start: date, end: date) -> list[FirmsWindow]:
    if end < start:
        raise ValueError("FIRMS end date must not precede start date")
    windows: list[FirmsWindow] = []
    current = start
    while current <= end:
        window_end = min(end, current + timedelta(days=4))
        windows.append(FirmsWindow(current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def firms_map_key(value: str | None = None) -> str:
    key = (value or os.environ.get("FIRMS_MAP_KEY", "")).strip()
    if not key:
        raise ValueError(
            "missing FIRMS_MAP_KEY; request a free NASA FIRMS map key and export it "
            "in the shell before collecting"
        )
    return key


def ensure_natural_earth_boundaries(
    path: Path, *, client: httpx.Client | None = None
) -> Path:
    """Download a pinned public-domain boundary file once and verify its checksum."""
    if path.exists():
        _verify_sha256(path, NATURAL_EARTH_SHA256)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    owns_client = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=True)
    try:
        response = client.get(NATURAL_EARTH_URL)
        response.raise_for_status()
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(response.content)
        _verify_sha256(temporary, NATURAL_EARTH_SHA256)
        os.replace(temporary, path)
    except (httpx.HTTPError, OSError) as exc:
        raise ProviderError(
            f"failed to acquire Natural Earth country boundaries: {exc}"
        ) from exc
    finally:
        if owns_client:
            client.close()
    return path


class FIRMSProvider:
    """Collect complete global five-day windows and aggregate retained detections."""

    def __init__(
        self,
        *,
        map_key: str,
        source: str,
        boundary_index: CountryBoundaryIndex,
        countries: Iterable[Country],
        cache_dir: Path,
        client: httpx.Client | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 30.0,
        request_interval_seconds: float = 25.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if source not in ALLOWED_SOURCES:
            raise ValueError(f"unsupported FIRMS source: {source}")
        self.map_key = map_key
        self.source = source
        self.boundary_index = boundary_index
        self.countries = tuple(countries)
        self.cache_dir = cache_dir
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_interval_seconds = request_interval_seconds
        self.sleep = sleep
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=180, follow_redirects=True)

    def __enter__(self) -> "FIRMSProvider":
        return self

    def __exit__(self, *_: object) -> None:
        if self._owns_client:
            self.client.close()

    def collect(
        self, start: date, end: date
    ) -> tuple[list[DailyHazard], list[dict[str, Any]], dict[str, int]]:
        windows = plan_firms_windows(start, end)
        aggregates: dict[tuple[date, str], dict[str, float | int]] = defaultdict(
            lambda: {
                "count": 0,
                "total_frp": 0.0,
                "max_frp": 0.0,
                "high_confidence": 0,
            }
        )
        requests: list[dict[str, Any]] = []
        totals = {
            "rows_received": 0,
            "rows_retained": 0,
            "rows_unassigned": 0,
            "rows_low_confidence": 0,
            "rows_non_vegetation": 0,
        }
        for index, window in enumerate(windows):
            path, request = self._obtain_window(window)
            requests.append(request)
            window_totals = self._aggregate_file(path, window, aggregates)
            for key, value in window_totals.items():
                totals[key] += value
            if index + 1 < len(windows) and not request["cached"]:
                self.sleep(self.request_interval_seconds)
        return self._daily_rows(start, end, aggregates), requests, totals

    def _obtain_window(self, window: FirmsWindow) -> tuple[Path, dict[str, Any]]:
        path = self.cache_dir / self.source.lower() / f"{window.window_id}.csv"
        if path.exists():
            self._validate_header(path)
            return path, self._request_metadata(window, path, attempts=0, cached=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = (
            f"{FIRMS_API_ROOT}/{self.map_key}/{self.source}/world/"
            f"{window.day_range}/{window.start.isoformat()}"
        )
        error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.client.get(url)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    raise ProviderError(
                        f"FIRMS returned HTTP {response.status_code} for {window.window_id}"
                    )
                text = response.text
                lowered = text[:500].lower()
                if "invalid map_key" in lowered or "error in processing" in lowered:
                    raise ProviderError(
                        f"FIRMS rejected request {window.window_id}"
                    )
                temporary = path.with_suffix(".csv.tmp")
                temporary.write_text(text, encoding="utf-8")
                self._validate_header(temporary)
                os.replace(temporary, path)
                return path, self._request_metadata(
                    window, path, attempts=attempt, cached=False
                )
            except (httpx.HTTPError, OSError, ProviderError) as exc:
                error = exc
                if attempt > self.max_retries:
                    break
                retry_after = 0.0
                if isinstance(exc, httpx.HTTPStatusError):
                    raw_retry = exc.response.headers.get("Retry-After")
                    if raw_retry:
                        try:
                            retry_after = float(raw_retry)
                        except ValueError:
                            pass
                self.sleep(max(retry_after, self.backoff_seconds * (2 ** (attempt - 1))))
        raise ProviderError(
            f"FIRMS request {window.window_id} failed after "
            f"{self.max_retries + 1} attempt(s): {_redact_error(error, self.map_key)}"
        )

    def _validate_header(self, path: Path) -> None:
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                header = next(csv.reader(handle), [])
        except OSError as exc:
            raise ProviderError(f"cannot read FIRMS cache {path}: {exc}") from exc
        missing = REQUIRED_COLUMNS - set(header)
        if missing:
            raise ProviderError(
                f"FIRMS response is missing columns: {', '.join(sorted(missing))}"
            )

    def _aggregate_file(
        self,
        path: Path,
        window: FirmsWindow,
        aggregates: dict[tuple[date, str], dict[str, float | int]],
    ) -> dict[str, int]:
        totals = {
            "rows_received": 0,
            "rows_retained": 0,
            "rows_unassigned": 0,
            "rows_low_confidence": 0,
            "rows_non_vegetation": 0,
        }
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    totals["rows_received"] += 1
                    try:
                        day = date.fromisoformat(row["acq_date"])
                        latitude = float(row["latitude"])
                        longitude = float(row["longitude"])
                        frp = float(row["frp"])
                        fire_type = int(float(row["type"]))
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ProviderError(
                            f"invalid FIRMS row in {path}: {exc}"
                        ) from exc
                    if not window.start <= day <= window.end:
                        raise ProviderError(
                            f"FIRMS cache {path} contains date outside its window: {day}"
                        )
                    if fire_type != 0:
                        totals["rows_non_vegetation"] += 1
                        continue
                    confidence = row["confidence"].strip().lower()
                    if confidence in {"l", "low"}:
                        totals["rows_low_confidence"] += 1
                        continue
                    boundary = self.boundary_index.assign(longitude, latitude)
                    if boundary is None:
                        totals["rows_unassigned"] += 1
                        continue
                    item = aggregates[(day, boundary.country_id)]
                    item["count"] += 1
                    item["total_frp"] += max(0.0, frp)
                    item["max_frp"] = max(float(item["max_frp"]), max(0.0, frp))
                    if confidence in {"h", "high"}:
                        item["high_confidence"] += 1
                    totals["rows_retained"] += 1
        except OSError as exc:
            raise ProviderError(f"cannot process FIRMS cache {path}: {exc}") from exc
        return totals

    def _daily_rows(
        self,
        start: date,
        end: date,
        aggregates: dict[tuple[date, str], dict[str, float | int]],
    ) -> list[DailyHazard]:
        supported = self.boundary_index.supported_country_ids
        collected_at = datetime.now(timezone.utc)
        result: list[DailyHazard] = []
        day = start
        while day <= end:
            for country in self.countries:
                is_supported = country.id in supported
                item = aggregates.get((day, country.id))
                count = int(item["count"]) if item else 0
                total = float(item["total_frp"]) if item else 0.0
                result.append(
                    DailyHazard(
                        record_id=(
                            f"firms:{self.source}:wildfire:{day.isoformat()}:{country.id}"
                        ),
                        date=day,
                        source="firms",
                        hazard_type="wildfire",
                        geography=country.id,
                        country_iso3=country_iso3(country),
                        observation_count=count if is_supported else None,
                        total_intensity=total if is_supported else None,
                        mean_intensity=(total / count if is_supported and count else 0.0)
                        if is_supported
                        else None,
                        max_intensity=(float(item["max_frp"]) if item else 0.0)
                        if is_supported
                        else None,
                        high_confidence_count=(
                            int(item["high_confidence"]) if item else 0
                        )
                        if is_supported
                        else None,
                        request_complete=True,
                        boundary_supported=is_supported,
                        collected_at=collected_at,
                        metadata={
                            "provider_product": self.source,
                            "intensity_measure": "fire_radiative_power",
                            "intensity_unit": "MW",
                            "area": "world",
                            "filters": [
                                "presumed_vegetation_type_0",
                                "exclude_low_confidence",
                            ],
                        },
                    )
                )
            day += timedelta(days=1)
        return result

    def _request_metadata(
        self, window: FirmsWindow, path: Path, *, attempts: int, cached: bool
    ) -> dict[str, Any]:
        return {
            "window_id": window.window_id,
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "area": "world",
            "source": self.source,
            "status": "success",
            "attempts": attempts,
            "cached": cached,
            "cache_path": str(path),
            "sha256": _sha256(path),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_sha256(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise ProviderError(
            f"checksum mismatch for {path}: expected {expected}, found {actual}"
        )


def _redact_error(error: Exception | None, secret: str) -> str:
    return str(error).replace(secret, "[REDACTED]") if error is not None else "unknown error"
