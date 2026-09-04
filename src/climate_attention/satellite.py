"""Low-storage MODIS zonal-statistics ingestion and AppEEARS task helpers."""

from __future__ import annotations

import csv
import calendar
import json
import logging
import math
import re
import statistics
import time
import warnings
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
MODIS_CMG_PRODUCT = "MOD13C2.061"
MODIS_CMG_SHORT_NAME = "MOD13C2"
MODIS_CMG_COLLECTION_ID = "C2565788914-LPCLOUD"
MODIS_CMG_NDVI_VARIABLE = (
    "/MOD_Grid_monthly_CMG_VI/Data_Fields/CMG_0_05_Deg_Monthly_NDVI"
)
MODIS_CMG_EVI_VARIABLE = (
    "/MOD_Grid_monthly_CMG_VI/Data_Fields/CMG_0_05_Deg_Monthly_EVI"
)
MODIS_CMG_ROWS = 3600
MODIS_CMG_COLUMNS = 7200
MODIS_CMG_RESOLUTION_DEGREES = 0.05
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


def parse_mod13c2_date(value: str | Path) -> date:
    """Read a monthly composite start date from a MOD13C2 granule identifier."""
    match = re.search(r"MOD13C2\.A(\d{4})(\d{3})\.061", Path(value).name)
    if not match:
        raise ValueError(f"cannot parse a MOD13C2 date from {value!r}")
    return date(int(match.group(1)), 1, 1) + timedelta(days=int(match.group(2)) - 1)


def mod13c2_opendap_url(granule_id: str) -> str:
    """Build the authenticated Earthdata Cloud OPeNDAP URL for one granule."""
    if not re.fullmatch(r"MOD13C2\.A\d{7}\.061\.\d+", granule_id):
        raise ValueError(f"invalid MOD13C2 granule identifier {granule_id!r}")
    return (
        "https://opendap.earthdata.nasa.gov/collections/"
        f"{MODIS_CMG_COLLECTION_ID}/granules/{granule_id}.dap.nc4"
    )


def download_mod13c2_subset(
    session: Any,
    granule_id: str,
    destination: Path,
    *,
    metric: str = "ndvi",
) -> Path:
    """Download only one monthly NDVI/EVI band as NetCDF4, atomically."""
    variables = {"ndvi": MODIS_CMG_NDVI_VARIABLE, "evi": MODIS_CMG_EVI_VARIABLE}
    if metric not in variables:
        raise ValueError("MOD13C2 metric must be 'ndvi' or 'evi'")
    if destination.exists() and destination.stat().st_size:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with session.get(
            mod13c2_opendap_url(granule_id),
            params={"dap4.ce": variables[metric]},
            stream=True,
            timeout=(30, 300),
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        temporary.replace(destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"failed to download MOD13C2 granule {granule_id}: {exc}") from exc
    return destination


def read_mod13c2_subset(path: Path) -> Any:
    """Read the raw int16 grid from an NDVI/EVI-only OPeNDAP NetCDF4 file."""
    try:
        import rasterio
        from rasterio.errors import NotGeoreferencedWarning
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ValueError("install the satellite extra to read MOD13C2 subsets") from exc
    raster_logger = logging.getLogger("rasterio._env")
    previous_level = raster_logger.level
    try:
        raster_logger.setLevel(logging.WARNING)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(path) as dataset:
                values = dataset.read(1)
    finally:
        raster_logger.setLevel(previous_level)
    if values.shape != (MODIS_CMG_ROWS, MODIS_CMG_COLUMNS):
        raise ValueError(
            f"unexpected MOD13C2 grid {values.shape}; expected "
            f"{(MODIS_CMG_ROWS, MODIS_CMG_COLUMNS)}"
        )
    return values


def discover_mod13c2_granules(start: date, end: date) -> list[str]:
    """Discover the latest revision of every monthly granule through NASA CMR."""
    if end < start:
        raise ValueError("MOD13C2 end date must not precede start date")
    try:
        import earthaccess
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ValueError("install the satellite extra to search NASA Earthdata") from exc
    try:
        results = earthaccess.search_data(
            short_name=MODIS_CMG_SHORT_NAME,
            version="061",
            temporal=(start.isoformat(), end.isoformat()),
            count=-1,
        )
    except Exception as exc:
        raise ValueError(f"failed to search NASA CMR for MOD13C2: {exc}") from exc
    by_date: dict[date, str] = {}
    for result in results:
        granule_id = str(result.get("umm", {}).get("GranuleUR", ""))
        observed = parse_mod13c2_date(granule_id)
        if observed <= end and (
            observed.year > start.year or observed.month >= start.month
        ):
            by_date[observed] = granule_id
    return [by_date[observed] for observed in sorted(by_date)]


def mod13c2_country_observations(
    values: Any,
    *,
    boundaries: CountryBoundaryIndex,
    observed: date,
    granule_id: str,
    metric: str = "ndvi",
    transform: Any | None = None,
) -> list[LandSurfaceObservation]:
    """Compute latitude-area-weighted country means from one global CMG grid."""
    if metric not in {"ndvi", "evi"}:
        raise ValueError("MOD13C2 metric must be 'ndvi' or 'evi'")
    try:
        import numpy as np
        from rasterio.features import rasterize
        from affine import Affine
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ValueError("install the satellite extra to aggregate MOD13C2") from exc
    array = np.asarray(values)
    if array.ndim != 2:
        raise ValueError("MOD13C2 values must be a two-dimensional grid")
    if transform is None:
        if array.shape != (MODIS_CMG_ROWS, MODIS_CMG_COLUMNS):
            raise ValueError(
                f"unexpected MOD13C2 grid {array.shape}; expected "
                f"{(MODIS_CMG_ROWS, MODIS_CMG_COLUMNS)}"
            )
        # The OPeNDAP NetCDF dimension is south-to-north (row 0 begins at -90°),
        # unlike the usual north-up GeoTIFF convention.
        transform = Affine(
            MODIS_CMG_RESOLUTION_DEGREES,
            0,
            -180,
            0,
            MODIS_CMG_RESOLUTION_DEGREES,
            -90,
        )

    # Draw larger countries first and small countries last. all_touched retains
    # microstates and islands that are smaller than a 0.05-degree grid cell.
    supported = sorted(
        boundaries.boundaries,
        key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]),
        reverse=True,
    )
    if not supported:
        raise ValueError("country boundary index contains no countries")
    zones = rasterize(
        [(item.geometry, index) for index, item in enumerate(supported, start=1)],
        out_shape=array.shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint16",
    )
    zone_count = len(supported) + 1
    weighted_sums = np.zeros(zone_count, dtype="float64")
    area_weights = np.zeros(zone_count, dtype="float64")
    valid_counts = np.zeros(zone_count, dtype="int64")
    total_counts = np.zeros(zone_count, dtype="int64")
    for row_start in range(0, array.shape[0], 256):
        row_end = min(row_start + 256, array.shape[0])
        raw = array[row_start:row_end]
        labels = zones[row_start:row_end]
        total_counts += np.bincount(labels.ravel(), minlength=zone_count)
        valid = (labels > 0) & (raw >= -2000) & (raw <= 10000) & (raw != -3000)
        if not np.any(valid):
            continue
        row_numbers = np.arange(row_start, row_end, dtype="float64")
        latitudes = transform.f + (row_numbers + 0.5) * transform.e
        row_weights = np.cos(np.deg2rad(latitudes))[:, None]
        valid_labels = labels[valid]
        valid_values = raw[valid].astype("float64") / 10000.0
        valid_weights = np.broadcast_to(row_weights, raw.shape)[valid]
        weighted_sums += np.bincount(
            valid_labels,
            weights=valid_values * valid_weights,
            minlength=zone_count,
        )
        area_weights += np.bincount(
            valid_labels, weights=valid_weights, minlength=zone_count
        )
        valid_counts += np.bincount(valid_labels, minlength=zone_count)

    period_days = calendar.monthrange(observed.year, observed.month)[1]
    observations = []
    for zone, boundary in enumerate(supported, start=1):
        if not area_weights[zone]:
            continue
        observations.append(LandSurfaceObservation(
            record_id=_record_id(
                MODIS_SOURCE, MODIS_CMG_PRODUCT, metric, boundary.country_id, observed
            ),
            date=observed,
            source=MODIS_SOURCE,
            product=MODIS_CMG_PRODUCT,
            metric=metric,
            geography=boundary.country_id,
            country_iso3=boundary.iso3,
            value=float(weighted_sums[zone] / area_weights[zone]),
            unit="index",
            period_days=period_days,
            valid_pixel_count=int(valid_counts[zone]),
            total_pixel_count=int(total_counts[zone]),
            land_cover_mask="all_valid_cmg_cells",
            metadata={
                "aggregation": "latitude-area-weighted 0.05-degree country cells",
                "area_weight_sum": float(area_weights[zone]),
                "granule_id": granule_id,
                "grid_resolution_degrees": MODIS_CMG_RESOLUTION_DEGREES,
            },
        ))
    return sorted(observations, key=lambda item: item.geography)


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


def _season_slot(item: LandSurfaceObservation) -> int:
    if item.product == MODIS_CMG_PRODUCT:
        return item.date.month
    return (item.date.timetuple().tm_yday - 1) // item.period_days


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
    baseline: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    for item in items:
        if item.metric == "burned_area":
            continue
        if baseline_start_year <= item.date.year <= baseline_end_year:
            baseline[
                (item.product, item.metric, item.geography, _season_slot(item))
            ].append(item.value)
    output: list[LandSurfaceObservation] = []
    for item in items:
        values = baseline.get(
            (
                item.product,
                item.metric,
                item.geography,
                _season_slot(item),
            ),
            [],
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
            weighted = [
                item
                for item in eligible
                if item.metadata.get("area_weight_sum", item.valid_pixel_count or 0)
            ]
            if not weighted:
                continue
            weights = [
                float(item.metadata.get("area_weight_sum", item.valid_pixel_count or 0))
                for item in weighted
            ]
            total_weight = sum(weights)
            total_pixels = sum(item.valid_pixel_count or 0 for item in weighted)
            value = sum(
                item.value * weight for item, weight in zip(weighted, weights, strict=True)
            ) / total_weight
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
                metadata={
                    "aggregation": "valid-area-weighted country rollup",
                    "area_weight_sum": total_weight,
                },
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
        # AppEEARS tasks can run for a while, so tolerate brief DNS/network blips
        # during login, polling, and downloads.
        transport = httpx.HTTPTransport(retries=3)
        self.client = httpx.Client(
            base_url=APPEEARS_API,
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
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
