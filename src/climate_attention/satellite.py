"""Low-storage MODIS zonal-statistics ingestion and AppEEARS task helpers."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

import httpx

from .config import Country
from .geography import CountryBoundaryIndex
from .models import LandSurfaceObservation


APPEEARS_API = "https://appeears.earthdatacloud.nasa.gov/api"
MODIS_VEGETATION_PRODUCT = "MOD13A2.061"
MODIS_NDVI_LAYER = "_1_km_16_days_NDVI"
MODIS_EVI_LAYER = "_1_km_16_days_EVI"
MODIS_BURNED_AREA_PRODUCT = "MCD64A1.061"
MODIS_BURN_DATE_LAYER = "Burn_Date"
MODIS_SOURCE = "nasa_modis"
EU27 = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus",
    "czechrepublic", "denmark", "estonia", "finland", "france",
    "germany", "greece", "hungary", "ireland", "italy", "latvia",
    "lithuania", "luxembourg", "malta", "netherlands", "poland",
    "portugal", "romania", "slovakia", "slovenia", "spain", "sweden",
}


def _record_id(*parts: object) -> str:
    digest = sha256("\x1f".join(str(part) for part in parts).encode()).hexdigest()[:20]
    return f"satellite:{digest}"


def _parse_date(value: str) -> date:
    cleaned = value.strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            pass
    raise ValueError(f"unsupported AppEEARS date {value!r}")


def _normalise_aid(value: str) -> str:
    match = re.search(r"aid\d{4,}", value, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"cannot find an AppEEARS feature id in {value!r}")
    return match.group(0).lower()


def build_appeears_area_task(
    *,
    countries: Iterable[Country],
    boundaries: CountryBoundaryIndex,
    start: date,
    end: date,
    task_name: str,
    product: str = MODIS_VEGETATION_PRODUCT,
    layer: str = MODIS_NDVI_LAYER,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """Build an AppEEARS request plus its deterministic aid-to-country sidecar."""
    if end < start:
        raise ValueError("AppEEARS task end date must not precede start date")
    selected = {country.id: country for country in countries}
    supported = [
        boundary for boundary in boundaries.boundaries
        if boundary.country_id in selected
    ]
    supported.sort(key=lambda boundary: boundary.country_id)
    if not supported:
        raise ValueError("none of the selected countries has a supported boundary")
    features = []
    aid_map: dict[str, dict[str, str]] = {}
    for index, boundary in enumerate(supported, start=1):
        aid = f"aid{index:04d}"
        country = selected[boundary.country_id]
        features.append({
            "type": "Feature",
            "id": aid,
            "properties": {
                "geography": boundary.country_id,
                "iso3": boundary.iso3,
                "label": country.label,
            },
            "geometry": boundary.geometry,
        })
        aid_map[aid] = {
            "geography": boundary.country_id,
            "country_iso3": boundary.iso3,
            "label": country.label,
        }
    task = {
        "task_type": "area",
        "task_name": task_name,
        "params": {
            "dates": [{
                "startDate": start.strftime("%m-%d-%Y"),
                "endDate": end.strftime("%m-%d-%Y"),
            }],
            "layers": [{"product": product, "layer": layer}],
            "geo": {"type": "FeatureCollection", "features": features},
            "output": {
                "format": {"type": "geotiff", "filename_date": "calendar"},
                "projection": "native",
            },
        },
    }
    return task, aid_map


def write_appeears_task(
    task: dict[str, Any],
    aid_map: dict[str, dict[str, str]],
    *,
    request_path: Path,
    aid_map_path: Path,
) -> None:
    request_path.parent.mkdir(parents=True, exist_ok=True)
    aid_map_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    aid_map_path.write_text(
        json.dumps(aid_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_aid_map(path: Path) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("AppEEARS aid map must be a non-empty JSON object")
    return {str(key).lower(): value for key, value in payload.items()}


def parse_appeears_vegetation_statistics(
    path: Path,
    *,
    aid_map: dict[str, dict[str, str]],
    metric: str = "ndvi",
    product: str = MODIS_VEGETATION_PRODUCT,
    source: str = MODIS_SOURCE,
) -> list[LandSurfaceObservation]:
    """Parse the small Statistics.csv file; no browser-facing raster is retained."""
    if metric not in {"ndvi", "evi"}:
        raise ValueError("vegetation statistics metric must be 'ndvi' or 'evi'")
    expected_dataset = "NDVI" if metric == "ndvi" else "EVI"
    observations: list[LandSurfaceObservation] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"File Name", "Dataset", "Date", "Count", "Mean"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"AppEEARS statistics file is missing columns: {', '.join(sorted(missing))}"
            )
        for row in reader:
            dataset = (row.get("Dataset") or "").upper()
            if expected_dataset not in dataset:
                continue
            aid = _normalise_aid(row.get("aid") or row.get("File Name") or "")
            mapping = aid_map.get(aid)
            if mapping is None:
                raise ValueError(f"AppEEARS feature {aid!r} is absent from the aid map")
            value = float(row["Mean"])
            count = int(float(row["Count"]))
            if not math.isfinite(value) or not -0.2 <= value <= 1.0:
                continue
            observed = _parse_date(row["Date"])
            observations.append(LandSurfaceObservation(
                record_id=_record_id(source, product, metric, mapping["geography"], observed),
                date=observed,
                source=source,
                product=product,
                metric=metric,
                geography=mapping["geography"],
                country_iso3=mapping.get("country_iso3"),
                value=value,
                unit="index",
                period_days=16,
                valid_pixel_count=count,
                land_cover_mask="all_land",
                metadata={
                    "aggregation": "mean",
                    "appeears_feature_id": aid,
                    "dataset": row["Dataset"],
                    "statistics_file": path.name,
                },
            ))
    if not observations:
        raise ValueError(f"no {expected_dataset} rows found in {path}")
    return sorted(observations, key=lambda item: (item.date, item.geography))


def _season_slot(value: date, period_days: int) -> int:
    return (value.timetuple().tm_yday - 1) // period_days


def add_seasonal_anomalies(
    observations: Iterable[LandSurfaceObservation],
    *,
    baseline_start_year: int = 2001,
    baseline_end_year: int = 2020,
    minimum_baseline_observations: int = 5,
) -> list[LandSurfaceObservation]:
    """Subtract each geography's same-season climatology from vegetation values."""
    if baseline_start_year > baseline_end_year:
        raise ValueError("baseline start year cannot exceed end year")
    items = list(observations)
    baseline: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for item in items:
        if item.metric == "burned_area":
            continue
        if baseline_start_year <= item.date.year <= baseline_end_year:
            baseline[(item.metric, item.geography, _season_slot(item.date, item.period_days))].append(item.value)
    output: list[LandSurfaceObservation] = []
    for item in items:
        values = baseline.get(
            (item.metric, item.geography, _season_slot(item.date, item.period_days)), []
        )
        anomaly = None
        standardized = None
        if len(values) >= minimum_baseline_observations:
            centre = statistics.fmean(values)
            anomaly = item.value - centre
            spread = statistics.stdev(values) if len(values) > 1 else 0
            standardized = anomaly / spread if spread > 0 else None
        output.append(item.model_copy(update={
            "anomaly": anomaly,
            "standardized_anomaly": standardized,
            "baseline_start_year": baseline_start_year,
            "baseline_end_year": baseline_end_year,
        }))
    return output


def add_region_rollups(
    observations: Iterable[LandSurfaceObservation],
) -> list[LandSurfaceObservation]:
    """Add pixel-weighted World and EU27 rows without averaging country means equally."""
    items = [item for item in observations if not item.geography.startswith("__")]
    grouped: dict[tuple[date, str, str, str, int], list[LandSurfaceObservation]] = defaultdict(list)
    for item in items:
        grouped[(item.date, item.source, item.product, item.metric, item.period_days)].append(item)
    rollups: list[LandSurfaceObservation] = []
    for (observed, source, product, metric, period_days), dated in grouped.items():
        for region, eligible in (
            ("__global__", dated),
            ("__eu27__", [item for item in dated if item.geography in EU27]),
        ):
            weighted = [item for item in eligible if item.valid_pixel_count]
            if not weighted:
                continue
            total_pixels = sum(item.valid_pixel_count or 0 for item in weighted)
            value = sum(item.value * (item.valid_pixel_count or 0) for item in weighted) / total_pixels
            rollups.append(LandSurfaceObservation(
                record_id=_record_id(source, product, metric, region, observed),
                date=observed,
                source=source,
                product=product,
                metric=metric,
                geography=region,
                value=value,
                unit=weighted[0].unit,
                period_days=period_days,
                valid_pixel_count=total_pixels,
                land_cover_mask=weighted[0].land_cover_mask,
                metadata={"aggregation": "valid-pixel-weighted country rollup"},
            ))
    return sorted([*items, *rollups], key=lambda item: (item.date, item.metric, item.geography))


def burned_area_observations_from_values(
    burn_dates: Iterable[int],
    *,
    year: int,
    pixel_area_hectares: float,
    geography: str,
    country_iso3: str,
    total_pixel_count: int | None = None,
    source_file: str | None = None,
) -> list[LandSurfaceObservation]:
    """Convert MCD64 ordinal burn-day pixels into true daily hectare totals."""
    if pixel_area_hectares <= 0:
        raise ValueError("burned-area pixel size must be positive")
    counts = Counter(int(value) for value in burn_dates if 1 <= int(value) <= 366)
    observations = []
    for ordinal_day, burned_pixels in sorted(counts.items()):
        observed = date(year, 1, 1) + timedelta(days=ordinal_day - 1)
        if observed.year != year:
            continue
        observations.append(LandSurfaceObservation(
            record_id=_record_id(
                MODIS_SOURCE, MODIS_BURNED_AREA_PRODUCT, "burned_area",
                geography, observed,
            ),
            date=observed,
            source=MODIS_SOURCE,
            product=MODIS_BURNED_AREA_PRODUCT,
            metric="burned_area",
            geography=geography,
            country_iso3=country_iso3,
            value=burned_pixels * pixel_area_hectares,
            unit="ha",
            period_days=1,
            valid_pixel_count=total_pixel_count,
            total_pixel_count=total_pixel_count,
            land_cover_mask="burned_pixels",
            metadata={
                "aggregation": "burned pixel count multiplied by native pixel area",
                "burned_pixel_count": burned_pixels,
                "pixel_area_hectares": pixel_area_hectares,
                "source_file": source_file,
            },
        ))
    return observations


def parse_mcd64_burn_date_raster(
    path: Path,
    *,
    aid_map: dict[str, dict[str, str]],
) -> list[LandSurfaceObservation]:
    """Read one native-projection AppEEARS MCD64 Burn_Date GeoTIFF."""
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ValueError(
            "burned-area raster import requires: python -m pip install -e '.[satellite]'"
        ) from exc
    aid = _normalise_aid(path.name)
    mapping = aid_map.get(aid)
    if mapping is None:
        raise ValueError(f"AppEEARS feature {aid!r} is absent from the aid map")
    date_match = re.search(r"_(\d{8})T?\d*[_.]aid", path.name)
    doy_match = re.search(r"_doy(\d{4})(\d{3})", path.name)
    if date_match:
        year = int(date_match.group(1)[:4])
    elif doy_match:
        year = int(doy_match.group(1))
    else:
        raise ValueError(f"cannot determine MCD64 year from {path.name!r}")
    with rasterio.open(path) as dataset:
        if dataset.crs is None or dataset.crs.is_geographic:
            raise ValueError("MCD64 burned-area import requires the native projected output")
        band = dataset.read(1, masked=True)
        values = band.compressed()
        transform = dataset.transform
        pixel_area_hectares = abs(
            transform.a * transform.e - transform.b * transform.d
        ) / 10_000
    return burned_area_observations_from_values(
        values,
        year=year,
        pixel_area_hectares=pixel_area_hectares,
        geography=mapping["geography"],
        country_iso3=mapping["country_iso3"],
        total_pixel_count=len(values),
        source_file=path.name,
    )


def add_burned_area_region_rollups(
    observations: Iterable[LandSurfaceObservation],
) -> list[LandSurfaceObservation]:
    """Add World/EU27 burned-area totals by summing disjoint country pixels."""
    items = [item for item in observations if not item.geography.startswith("__")]
    by_date: dict[date, list[LandSurfaceObservation]] = defaultdict(list)
    for item in items:
        if item.metric == "burned_area":
            by_date[item.date].append(item)
    rollups = []
    for observed, dated in by_date.items():
        for region, eligible in (
            ("__global__", dated),
            ("__eu27__", [item for item in dated if item.geography in EU27]),
        ):
            if not eligible:
                continue
            rollups.append(LandSurfaceObservation(
                record_id=_record_id(
                    MODIS_SOURCE, MODIS_BURNED_AREA_PRODUCT, "burned_area",
                    region, observed,
                ),
                date=observed,
                source=MODIS_SOURCE,
                product=MODIS_BURNED_AREA_PRODUCT,
                metric="burned_area",
                geography=region,
                value=sum(item.value for item in eligible),
                unit="ha",
                period_days=1,
                valid_pixel_count=sum(item.valid_pixel_count or 0 for item in eligible),
                total_pixel_count=sum(item.total_pixel_count or 0 for item in eligible),
                land_cover_mask="burned_pixels",
                metadata={"aggregation": "sum of disjoint country burned pixels"},
            ))
    return sorted([*items, *rollups], key=lambda item: (item.date, item.geography))


class AppEEARSClient:
    """Small authenticated client used to submit tasks and fetch compact support files."""

    def __init__(self, username: str, password: str, *, timeout: float = 60.0):
        self.username = username
        self.password = password
        self.client = httpx.Client(base_url=APPEEARS_API, timeout=timeout, follow_redirects=True)
        self.token: str | None = None

    def __enter__(self) -> "AppEEARSClient":
        response = self.client.post("/login", auth=(self.username, self.password))
        response.raise_for_status()
        self.token = response.json()["token"]
        return self

    def __exit__(self, *_: object) -> None:
        if self.token:
            try:
                self.client.post("/logout", headers=self._headers())
            except httpx.HTTPError:
                pass
        self.client.close()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise ValueError("AppEEARS client is not authenticated")
        return {"Authorization": f"Bearer {self.token}"}

    def submit(self, task: dict[str, Any]) -> str:
        response = self.client.post("/task", json=task, headers=self._headers())
        response.raise_for_status()
        return str(response.json()["task_id"])

    def wait(self, task_id: str, *, poll_seconds: float = 15.0) -> dict[str, Any]:
        while True:
            response = self.client.get(
                f"/task/{task_id}", headers=self._headers(), follow_redirects=False
            )
            if response.status_code == 303:
                return {"task_id": task_id, "status": "done"}
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status")
            if status == "done":
                return payload
            if status == "error":
                raise ValueError(f"AppEEARS task {task_id} failed: {payload.get('error')}")
            time.sleep(poll_seconds)

    def download_support_files(
        self, task_id: str, destination: Path, *, include_burn_date_rasters: bool = False
    ) -> list[Path]:
        response = self.client.get(f"/bundle/{task_id}", headers=self._headers())
        response.raise_for_status()
        files = []
        for item in response.json().get("files", []):
            name = str(item.get("file_name", ""))
            if name.endswith("-Statistics.csv") or (
                include_burn_date_rasters and "Burn_Date" in name and name.endswith(".tif")
            ):
                files.append(item)
        if not files:
            raise ValueError(f"AppEEARS task {task_id} has no statistics CSV")
        destination.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for item in files:
            target = destination / Path(item["file_name"]).name
            temporary = target.with_suffix(target.suffix + ".part")
            with self.client.stream(
                "GET", f"/bundle/{task_id}/{item['file_id']}", headers=self._headers()
            ) as file_response:
                file_response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in file_response.iter_bytes():
                        handle.write(chunk)
            temporary.replace(target)
            downloaded.append(target)
        return downloaded

    def download_statistics(self, task_id: str, destination: Path) -> list[Path]:
        return self.download_support_files(task_id, destination)
