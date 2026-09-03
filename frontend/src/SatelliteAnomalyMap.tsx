import { useEffect, useMemo, useState } from 'react'
import { geoNaturalEarth1, geoPath } from 'd3-geo'
import type { FeatureCollection, Geometry } from 'geojson'

type WorldProperties = { name?: string; iso3?: string }
type WorldGeoJSON = FeatureCollection<Geometry, WorldProperties>

export type SatelliteMapObservation = {
  countryIso3: string | null
  anomaly: number | null
}

export function anomalyColor(value: number | null) {
  if (value == null || !Number.isFinite(value)) return '#e2e7e3'
  if (Math.abs(value) < 1e-9) return '#e2e7e3'
  const strength = Math.min(1, Math.abs(value) / 0.15)
  const lightness = 90 - strength * 42
  return value < 0
    ? `hsl(28 48% ${lightness}%)`
    : `hsl(145 38% ${lightness}%)`
}

export default function SatelliteAnomalyMap({
  date,
  observations,
}: {
  date: string
  observations: SatelliteMapObservation[]
}) {
  const [world, setWorld] = useState<WorldGeoJSON | null>(null)
  useEffect(() => {
    let active = true
    fetch('/data/world.geojson')
      .then((response) => {
        if (!response.ok) throw new Error(`World map returned ${response.status}`)
        return response.json()
      })
      .then((payload) => active && setWorld(payload))
      .catch(() => active && setWorld(null))
    return () => { active = false }
  }, [])

  const anomalyByIso3 = useMemo(() => new Map(
    observations
      .filter((item): item is SatelliteMapObservation & { countryIso3: string } => Boolean(item.countryIso3))
      .map((item) => [item.countryIso3, item.anomaly]),
  ), [observations])
  const projection = useMemo(
    () => world ? geoNaturalEarth1().fitExtent([[12, 10], [988, 485]], world) : null,
    [world],
  )
  const path = useMemo(() => projection ? geoPath(projection) : null, [projection])

  if (!world || !path) return <div className="satellite-map-loading">Preparing country anomaly map…</div>
  return <div className="satellite-map-panel">
    <div className="satellite-map-heading">
      <div><strong>Vegetation greenness anomaly</strong><small>MODIS NDVI composite beginning {new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(`${date}T00:00:00Z`))}</small></div>
      <div className="satellite-map-scale"><span>Unusually brown</span><i /><span>Unusually green</span></div>
    </div>
    <svg viewBox="0 0 1000 500" role="img" aria-label={`Country map of MODIS NDVI anomaly for ${date}`}>
      <rect width="1000" height="500" fill="#edf3f0" />
      {world.features.map((feature, index) => {
        const shape = path(feature)
        if (!shape) return null
        const value = anomalyByIso3.get(feature.properties.iso3 ?? '') ?? null
        return <path key={`${feature.properties.iso3 || feature.properties.name}-${index}`} d={shape} fill={anomalyColor(value)}><title>{feature.properties.name}: {value == null ? 'No observation' : `${value >= 0 ? '+' : ''}${value.toFixed(3)} NDVI`}</title></path>
      })}
    </svg>
  </div>
}
