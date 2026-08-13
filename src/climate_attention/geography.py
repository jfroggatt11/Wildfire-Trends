"""Country-code resolution and dependency-free point-in-country assignment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pycountry

from .config import Country


ISO3_ALIASES = {
    "Brunei": "BRN",
    "Democratic Republic of the Congo": "COD",
    "Ivory Coast": "CIV",
    "Kosovo": "XKX",
    "Micronesia": "FSM",
    "Palestine": "PSE",
    "Russia": "RUS",
    "Turkey": "TUR",
    "Vatican City": "VAT",
}


def country_iso3(country: Country) -> str:
    """Resolve a configured country label to a stable ISO3-like code."""
    if country.iso3 is not None:
        return country.iso3
    alias = ISO3_ALIASES.get(country.label)
    if alias is not None:
        return alias
    try:
        return pycountry.countries.lookup(country.label).alpha_3
    except LookupError as exc:
        raise ValueError(
            f"country {country.id!r} needs an explicit iso3 code; "
            f"could not resolve label {country.label!r}"
        ) from exc


@dataclass(frozen=True)
class CountryBoundary:
    country_id: str
    iso3: str
    bbox: tuple[float, float, float, float]
    geometry: dict[str, Any]


class CountryBoundaryIndex:
    """Small grid index over GeoJSON polygons for global point assignment."""

    def __init__(self, boundaries: Iterable[CountryBoundary], cell_size: int = 5):
        self.boundaries = tuple(boundaries)
        self.cell_size = cell_size
        cells: dict[tuple[int, int], list[int]] = {}
        for index, boundary in enumerate(self.boundaries):
            west, south, east, north = boundary.bbox
            for lon_cell in range(_cell(west, cell_size), _cell(east, cell_size) + 1):
                for lat_cell in range(_cell(south, cell_size), _cell(north, cell_size) + 1):
                    cells.setdefault((lon_cell, lat_cell), []).append(index)
        self._cells = cells

    @property
    def supported_country_ids(self) -> set[str]:
        return {item.country_id for item in self.boundaries}

    def assign(self, longitude: float, latitude: float) -> CountryBoundary | None:
        candidates = self._cells.get(
            (_cell(longitude, self.cell_size), _cell(latitude, self.cell_size)), []
        )
        for index in candidates:
            boundary = self.boundaries[index]
            west, south, east, north = boundary.bbox
            if not (west <= longitude <= east and south <= latitude <= north):
                continue
            if _geometry_contains(boundary.geometry, longitude, latitude):
                return boundary
        return None


def load_country_boundaries(
    path: str | Path, countries: Iterable[Country]
) -> CountryBoundaryIndex:
    """Load configured sovereign-country polygons from Natural Earth-style GeoJSON."""
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read country boundaries {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid country boundary GeoJSON {path}: {exc}") from exc
    if document.get("type") != "FeatureCollection":
        raise ValueError("country boundaries must be a GeoJSON FeatureCollection")

    by_iso3 = {country_iso3(country): country for country in countries}
    boundaries: list[CountryBoundary] = []
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        iso3 = _feature_iso3(properties)
        country = by_iso3.get(iso3)
        geometry = feature.get("geometry")
        if country is None or not geometry:
            continue
        bbox = feature.get("bbox") or _geometry_bbox(geometry)
        if len(bbox) != 4:
            raise ValueError(f"invalid boundary bbox for {country.id}")
        boundaries.append(
            CountryBoundary(
                country_id=country.id,
                iso3=iso3,
                bbox=tuple(float(item) for item in bbox),
                geometry=geometry,
            )
        )
    if not boundaries:
        raise ValueError("country boundary file does not match any configured countries")
    return CountryBoundaryIndex(boundaries)


def _feature_iso3(properties: dict[str, Any]) -> str | None:
    for name in ("ISO_A3", "ADM0_A3", "SOV_A3", "GU_A3", "iso3"):
        value = properties.get(name)
        if isinstance(value, str) and len(value) == 3 and value != "-99":
            return "XKX" if value == "KOS" else value.upper()
    return None


def _cell(value: float, size: int) -> int:
    return int((value + 180) // size)


def _geometry_bbox(geometry: dict[str, Any]) -> list[float]:
    points = list(_coordinate_points(geometry.get("coordinates", [])))
    if not points:
        raise ValueError("country boundary geometry has no coordinates")
    longitudes, latitudes = zip(*points)
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def _coordinate_points(value: Any):
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    if isinstance(value, list):
        for child in value:
            yield from _coordinate_points(child)


def _geometry_contains(geometry: dict[str, Any], longitude: float, latitude: float) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        return _polygon_contains(coordinates, longitude, latitude)
    if geometry_type == "MultiPolygon":
        return any(
            _polygon_contains(polygon, longitude, latitude)
            for polygon in coordinates
        )
    return False


def _polygon_contains(rings: list, longitude: float, latitude: float) -> bool:
    if not rings or not _ring_contains(rings[0], longitude, latitude):
        return False
    return not any(_ring_contains(hole, longitude, latitude) for hole in rings[1:])


def _ring_contains(ring: list, longitude: float, latitude: float) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        if _on_segment(longitude, latitude, x1, y1, x2, y2):
            return True
        crosses = (y1 > latitude) != (y2 > latitude)
        if crosses:
            intersection = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < intersection:
                inside = not inside
        previous = current
    return inside


def _on_segment(
    x: float, y: float, x1: float, y1: float, x2: float, y2: float
) -> bool:
    cross = (y - y1) * (x2 - x1) - (x - x1) * (y2 - y1)
    if abs(cross) > 1e-10:
        return False
    return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)
