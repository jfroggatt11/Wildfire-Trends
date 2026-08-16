import { Component, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import type { ErrorInfo, PointerEvent as ReactPointerEvent, ReactNode, WheelEvent as ReactWheelEvent } from 'react'
import { geoNaturalEarth1, geoPath } from 'd3-geo'
import type { Feature, FeatureCollection, Geometry, Point } from 'geojson'
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  CalendarDays,
  Check,
  ChevronRight,
  CircleAlert,
  CloudRain,
  Database,
  ExternalLink,
  Filter,
  Flame,
  Globe2,
  Info,
  Layers3,
  Map as MapIcon,
  Menu,
  Microscope,
  Search,
  ShieldCheck,
  Sparkles,
  Wind,
  X,
} from 'lucide-react'
import type { AttentionChartPoint } from './AttentionChart'
import { dateWithinRange, formatDate, getPoliticalSignals, hasPoliticalSignal, newestFirst } from './utils'

const AttentionChart = lazy(() => import('./AttentionChart'))

type HazardType = 'wildfire' | 'flood' | 'tropical_cyclone'
type AlertLevel = 'Green' | 'Orange' | 'Red'
type MediaScope = 'affected' | 'eu27' | 'international' | 'global'
type View = 'explore' | 'lab' | 'data' | 'methods'
type DetailTab = 'briefing' | 'attention' | 'geography' | 'articles' | 'methods'

type EventProperties = {
  id: string
  sourceEventId: string
  hazardType: HazardType
  name: string
  startAt: string
  endAt: string
  geographyIds: string[]
  countryIso3s: string[]
  alertLevel: AlertLevel
  alertScore: number | null
  severity: number | null
  severityUnit: string | null
  sourceUrl: string
}

type EventFeature = Feature<Point, EventProperties>
type EventsGeoJSON = FeatureCollection<Point, EventProperties>
type WorldProperties = { name: string; iso3: string; continent: string }
type WorldGeoJSON = FeatureCollection<Geometry, WorldProperties>

type AttentionRow = {
  date: string
  source: string
  topicId: string
  geography: string
  matchedCount: number | null
  attentionShare: number | null
  attentionIndex: number | null
  politicalCount: number | null
  politicalActorCount: number | null
  governmentActionCount: number | null
  partyPoliticsCount: number | null
  officialSourceCount: number | null
}

type Article = {
  id: string
  date: string
  topicId: string
  geography: string
  url: string
  domain: string
  publishedAt: string | null
  outletName: string | null
  title: string | null
  description: string | null
  language: string | null
  politicalActor: boolean
  governmentAction: boolean
  partyPolitics: boolean
  officialSource: boolean
}

type DataSourceSummary = {
  id: string
  name: string
  provider: string
  role: string
  dateMin: string | null
  dateMax: string | null
  dateRanges: { start: string; end: string; dayCount: number }[]
  observedDayCount: number
  coverageBasis: string
  recordCount: number
  recordLabel: string
  geographyCount: number
  status: 'explorer'
  description: string
  sourceUrl: string
}

type Manifest = {
  generatedAt: string
  events: { count: number; hazards: Record<string, number>; alerts: Record<string, number> }
  attention: {
    rowCount: number
    dateMin: string
    dateMax: string
    sources: Record<string, number>
    topics: Record<string, number>
  }
  articles: { count: number }
  dataSources: DataSourceSummary[]
  analysisStatus: string
  notes: string[]
}

const HAZARDS: Record<
  HazardType,
  { label: string; shortLabel: string; color: string; icon: typeof Flame }
> = {
  wildfire: { label: 'Wildfire', shortLabel: 'Fire', color: '#ef704b', icon: Flame },
  flood: { label: 'Flood', shortLabel: 'Flood', color: '#2b7fa3', icon: CloudRain },
  tropical_cyclone: { label: 'Tropical cyclone', shortLabel: 'Cyclone', color: '#826ab4', icon: Wind },
}

const TOPICS = [
  { id: 'climate_change', label: 'Climate change', color: '#286e59' },
  { id: 'clean_transport', label: 'Clean transport', color: '#d56743' },
  { id: 'electric_vehicles', label: 'Electric vehicles', color: '#6575b7' },
  { id: 'clean_energy', label: 'Clean energy', color: '#c59a2b' },
]

const EU27 = new Set([
  'austria',
  'belgium',
  'bulgaria',
  'croatia',
  'cyprus',
  'czechrepublic',
  'denmark',
  'estonia',
  'finland',
  'france',
  'germany',
  'greece',
  'hungary',
  'ireland',
  'italy',
  'latvia',
  'lithuania',
  'luxembourg',
  'malta',
  'netherlands',
  'poland',
  'portugal',
  'romania',
  'slovakia',
  'slovenia',
  'spain',
  'sweden',
])

const SCOPE_COPY: Record<MediaScope, { label: string; description: string }> = {
  affected: { label: 'Affected countries', description: 'Outlets based in the event countries' },
  eu27: { label: 'EU-27', description: 'Combined response from EU media markets' },
  international: { label: 'International', description: 'Outlets outside affected countries' },
  global: { label: 'Global', description: 'All available publishing markets' },
}

const formatCompact = (value: number) =>
  new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value)

const titleCase = (value: string) =>
  value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())

const dayDifference = (date: string, origin: string) =>
  Math.round((new Date(date).getTime() - new Date(origin).getTime()) / 86_400_000)

function eventWindow(event: EventProperties, days = 28) {
  const start = new Date(event.startAt)
  const end = new Date(event.endAt)
  start.setUTCDate(start.getUTCDate() - days)
  end.setUTCDate(end.getUTCDate() + days)
  return { start, end }
}

function withinWindow(value: string, event: EventProperties, days = 28) {
  const { start, end } = eventWindow(event, days)
  const date = new Date(value)
  return date >= start && date <= end
}

function scopeAllows(geography: string, event: EventProperties, scope: MediaScope) {
  if (scope === 'affected') return event.geographyIds.includes(geography)
  if (scope === 'eu27') return EU27.has(geography)
  if (scope === 'international') return !event.geographyIds.includes(geography)
  return true
}

function useAtlasData() {
  const [events, setEvents] = useState<EventsGeoJSON | null>(null)
  const [world, setWorld] = useState<WorldGeoJSON | null>(null)
  const [attention, setAttention] = useState<AttentionRow[]>([])
  const [articles, setArticles] = useState<Article[]>([])
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([
      fetch('/data/events.geojson').then((response) => response.json()),
      fetch('/data/world.geojson').then((response) => response.json()),
      fetch('/data/manifest.json').then((response) => response.json()),
    ])
      .then(([eventsData, worldData, manifestData]) => {
        if (!active) return
        setEvents(eventsData)
        setWorld(worldData)
        setManifest(manifestData)
      })
      .catch(() => active && setError('The local research datasets could not be loaded.'))
    Promise.all([
      fetch('/data/attention.json').then((response) => response.json()),
      fetch('/data/articles.json').then((response) => response.json()),
    ]).then(([attentionData, articleData]) => {
      if (!active) return
      setAttention(attentionData)
      setArticles(articleData)
    }).catch(() => {
      if (!active) return
      setAttention([])
      setArticles([])
    })
    return () => {
      active = false
    }
  }, [])

  return { events, world, attention, articles, manifest, error }
}

class EventDetailBoundary extends Component<{ children: ReactNode; onClose: () => void }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Event detail rendering failed', error, info)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <aside className="event-drawer event-error" role="alert">
        <CircleAlert size={26} />
        <h2>This event could not be opened</h2>
        <p>The map and filters are still available. Close this panel and try another event.</p>
        <button onClick={this.props.onClose}><X size={16} /> Return to map</button>
      </aside>
    )
  }
}

function App() {
  const { events, world, attention, articles, manifest, error } = useAtlasData()
  const [view, setView] = useState<View>('explore')
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    const id = new URLSearchParams(window.location.search).get('event')
    return id
  })
  const [scope, setScope] = useState<MediaScope>('affected')
  const [detailTab, setDetailTab] = useState<DetailTab>('briefing')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const selectedEvent = useMemo(
    () => events?.features.find((feature) => feature.properties.id === selectedId) ?? null,
    [events, selectedId],
  )

  const selectEvent = (id: string | null) => {
    setSelectedId(id)
    setDetailTab('briefing')
    try {
      const url = new URL(window.location.href)
      if (id) url.searchParams.set('event', id)
      else url.searchParams.delete('event')
      window.history.replaceState({}, '', url)
    } catch {
      // Sandboxed and embedded previews can expose an opaque origin that rejects
      // History API updates. Event selection must remain fully functional there.
    }
  }

  if (error) {
    return (
      <main className="fatal-state">
        <CircleAlert size={30} />
        <h1>Atlas unavailable</h1>
        <p>{error}</p>
      </main>
    )
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => setView('explore')} aria-label="Open map explorer">
          <span className="brand-mark" aria-hidden="true"><span /><span /><span /></span>
          <span>
            <strong>Climate Attention</strong>
            <small>Atlas · T&amp;E internal MVP</small>
          </span>
        </button>
        <nav className={mobileMenuOpen ? 'primary-nav open' : 'primary-nav'} aria-label="Primary navigation">
          <button className={view === 'explore' ? 'active' : ''} onClick={() => { setView('explore'); setMobileMenuOpen(false) }}>
            <MapIcon size={16} /> Explore
          </button>
          <button className={view === 'lab' ? 'active' : ''} onClick={() => { setView('lab'); setMobileMenuOpen(false) }}>
            <Microscope size={16} /> Analysis Lab
          </button>
          <button className={view === 'data' ? 'active' : ''} onClick={() => { setView('data'); setMobileMenuOpen(false) }}>
            <Database size={16} /> Data
          </button>
          <button className={view === 'methods' ? 'active' : ''} onClick={() => { setView('methods'); setMobileMenuOpen(false) }}>
            <BookOpen size={16} /> Methods
          </button>
        </nav>
        <div className="topbar-meta">
          <span className="live-dot" /> Research preview
        </div>
        <button className="menu-button" onClick={() => setMobileMenuOpen((open) => !open)} aria-label="Toggle navigation">
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>

      {view === 'explore' && events && world ? (
        <ExploreView
          events={events}
          world={world}
          manifest={manifest}
          selectedEvent={selectedEvent}
          onSelectEvent={selectEvent}
          scope={scope}
          onScopeChange={setScope}
          attention={attention}
          articles={articles}
          detailTab={detailTab}
          onDetailTabChange={setDetailTab}
        />
      ) : view === 'lab' ? (
        <AnalysisLab manifest={manifest} />
      ) : view === 'data' && manifest ? (
        <DataSummary manifest={manifest} />
      ) : view === 'methods' ? (
        <MethodsView />
      ) : (
        <LoadingView />
      )}
    </div>
  )
}

function LoadingView() {
  return (
    <main className="loading-view">
      <span className="loading-orbit" />
      <p>Preparing the global event layer…</p>
    </main>
  )
}

function ExploreView({
  events,
  world,
  manifest,
  selectedEvent,
  onSelectEvent,
  scope,
  onScopeChange,
  attention,
  articles,
  detailTab,
  onDetailTabChange,
}: {
  events: EventsGeoJSON
  world: WorldGeoJSON
  manifest: Manifest | null
  selectedEvent: EventFeature | null
  onSelectEvent: (id: string | null) => void
  scope: MediaScope
  onScopeChange: (scope: MediaScope) => void
  attention: AttentionRow[]
  articles: Article[]
  detailTab: DetailTab
  onDetailTabChange: (tab: DetailTab) => void
}) {
  const [query, setQuery] = useState('')
  const [hazards, setHazards] = useState<Set<HazardType>>(new Set(Object.keys(HAZARDS) as HazardType[]))
  const [alerts, setAlerts] = useState<Set<AlertLevel>>(new Set(['Green', 'Orange', 'Red']))
  const [dateStart, setDateStart] = useState('2025-01-01')
  const [dateEnd, setDateEnd] = useState('2025-12-31')
  const [filtersOpen, setFiltersOpen] = useState(false)

  const filteredEvents = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return events.features.filter((feature) => {
      const event = feature.properties
      const startDate = event.startAt.slice(0, 10)
      const matchesQuery =
        !normalizedQuery ||
        event.name.toLowerCase().includes(normalizedQuery) ||
        event.geographyIds.some((country) => country.includes(normalizedQuery))
      return (
        matchesQuery &&
        hazards.has(event.hazardType) &&
        alerts.has(event.alertLevel) &&
        dateWithinRange(startDate, dateStart, dateEnd)
      )
    })
  }, [events, query, hazards, alerts, dateStart, dateEnd])

  const priorityEvents = useMemo(
    () =>
      [...filteredEvents]
        .sort((a, b) => {
          const level = { Red: 3, Orange: 2, Green: 1 }
          const alertDifference = level[b.properties.alertLevel] - level[a.properties.alertLevel]
          if (alertDifference) return alertDifference
          return (b.properties.alertScore ?? 0) - (a.properties.alertScore ?? 0)
        })
        .slice(0, 4),
    [filteredEvents],
  )

  const toggleHazard = (hazard: HazardType) => {
    setHazards((current) => {
      const next = new Set(current)
      if (next.has(hazard) && next.size > 1) next.delete(hazard)
      else next.add(hazard)
      return next
    })
  }

  const toggleAlert = (alert: AlertLevel) => {
    setAlerts((current) => {
      const next = new Set(current)
      if (next.has(alert) && next.size > 1) next.delete(alert)
      else next.add(alert)
      return next
    })
  }

  return (
    <main className="explore-view">
      <aside className={filtersOpen ? 'filter-panel open' : 'filter-panel'} aria-label="Map filters">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Event explorer</span>
            <h1>Weather events &amp; media response</h1>
          </div>
          <button className="mobile-close" onClick={() => setFiltersOpen(false)} aria-label="Close filters"><X size={18} /></button>
        </div>
        <p className="panel-intro">Explore major events, then inspect how climate and transport coverage moved around them.</p>

        <label className="search-field">
          <Search size={17} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find country or event" />
          {query && <button onClick={() => setQuery('')} aria-label="Clear search"><X size={15} /></button>}
        </label>

        <section className="filter-section">
          <div className="section-label"><span>Hazard</span><small>{filteredEvents.length.toLocaleString()} events</small></div>
          <div className="hazard-options">
            {(Object.entries(HAZARDS) as [HazardType, (typeof HAZARDS)[HazardType]][]).map(([id, item]) => {
              const Icon = item.icon
              return (
                <button key={id} className={hazards.has(id) ? 'hazard-chip active' : 'hazard-chip'} onClick={() => toggleHazard(id)} aria-pressed={hazards.has(id)}>
                  <Icon size={15} style={{ color: item.color }} /> {item.shortLabel}
                </button>
              )
            })}
          </div>
        </section>

        <section className="filter-section">
          <div className="section-label"><span>Alert level</span><small>GDACS</small></div>
          <div className="alert-options">
            {(['Green', 'Orange', 'Red'] as AlertLevel[]).map((level) => (
              <button key={level} className={alerts.has(level) ? `alert-chip ${level.toLowerCase()} active` : `alert-chip ${level.toLowerCase()}`} onClick={() => toggleAlert(level)} aria-pressed={alerts.has(level)}>
                <span /> {level}
              </button>
            ))}
          </div>
        </section>

        <section className="filter-section">
          <div className="section-label"><span>Event dates</span><small>UTC</small></div>
          <div className="date-range">
            <label><span>From</span><input type="date" value={dateStart} onChange={(event) => setDateStart(event.target.value)} /></label>
            <span className="date-arrow">→</span>
            <label><span>To</span><input type="date" value={dateEnd} onChange={(event) => setDateEnd(event.target.value)} /></label>
          </div>
        </section>

        <section className="filter-section scope-section">
          <div className="section-label"><span>Media response</span><Info size={14} /></div>
          <select value={scope} onChange={(event) => onScopeChange(event.target.value as MediaScope)}>
            {(Object.entries(SCOPE_COPY) as [MediaScope, (typeof SCOPE_COPY)[MediaScope]][]).map(([id, item]) => (
              <option key={id} value={id}>{item.label}</option>
            ))}
          </select>
          <p>{SCOPE_COPY[scope].description}</p>
        </section>

        <section className="watchlist">
          <div className="section-label"><span>Priority events</span><small>By alert</small></div>
          {priorityEvents.map((event) => (
            <button key={event.properties.id} onClick={() => { onSelectEvent(event.properties.id); setFiltersOpen(false) }}>
              <span className="watch-icon" style={{ color: HAZARDS[event.properties.hazardType].color }}>
                {event.properties.hazardType === 'wildfire' ? <Flame size={16} /> : event.properties.hazardType === 'flood' ? <CloudRain size={16} /> : <Wind size={16} />}
              </span>
              <span><strong>{event.properties.name}</strong><small>{formatDate(event.properties.startAt)} · {event.properties.alertLevel}</small></span>
              <ChevronRight size={15} />
            </button>
          ))}
        </section>

        <div className="coverage-note">
          <Database size={16} />
          <div><strong>{manifest ? manifest.events.count.toLocaleString() : '—'} verified events</strong><span>Attention analysis unlocks where continuous coverage passes checks.</span></div>
        </div>
      </aside>

      <section className="map-stage" aria-label="Global event map">
        <AtlasMap world={world} events={filteredEvents} selectedId={selectedEvent?.properties.id ?? null} onSelectEvent={onSelectEvent} />
        <button className="mobile-filter-button" onClick={() => setFiltersOpen(true)}><Filter size={16} /> Filters <span>{filteredEvents.length.toLocaleString()}</span></button>
        <div className="map-stat">
          <span className="eyebrow">Visible events</span>
          <strong>{filteredEvents.length.toLocaleString()}</strong>
          <small>{formatDate(dateStart)} — {formatDate(dateEnd)}</small>
        </div>
        <div className="map-legend" aria-label="Map legend">
          {(Object.entries(HAZARDS) as [HazardType, (typeof HAZARDS)[HazardType]][]).map(([id, item]) => (
            <span key={id}><i style={{ background: item.color }} />{item.label}</span>
          ))}
          <span className="legend-divider" />
          <span><i className="size-dot small" />Lower alert</span>
          <span><i className="size-dot large" />Higher alert</span>
        </div>
      </section>

      {selectedEvent && (
        <EventDetailBoundary key={selectedEvent.properties.id} onClose={() => onSelectEvent(null)}>
          <EventDrawer
            event={selectedEvent.properties}
            onClose={() => onSelectEvent(null)}
            scope={scope}
            onScopeChange={onScopeChange}
            attention={attention}
            articles={articles}
            tab={detailTab}
            onTabChange={onDetailTabChange}
          />
        </EventDetailBoundary>
      )}
    </main>
  )
}

type AtlasTransform = { x: number; y: number; k: number }
type AtlasMarker = { key: string; x: number; y: number; events: EventFeature[] }

function AtlasMap({ world, events, selectedId, onSelectEvent }: { world: WorldGeoJSON; events: EventFeature[]; selectedId: string | null; onSelectEvent: (id: string | null) => void }) {
  const [transform, setTransform] = useState<AtlasTransform>({ x: 0, y: 0, k: 1 })
  const dragRef = useRef<{ pointerId: number; clientX: number; clientY: number; x: number; y: number } | null>(null)
  const projection = useMemo(() => geoNaturalEarth1().fitExtent([[22, 22], [978, 528]], world), [world])
  const path = useMemo(() => geoPath(projection), [projection])

  const countryPaths = useMemo(
    () => world.features.map((feature, index) => ({ key: `${feature.properties.iso3 || feature.properties.name}-${index}`, path: path(feature) })),
    [world, path],
  )

  const markers = useMemo(() => {
    const gridSize = Math.max(7, 34 / transform.k)
    const buckets = new Map<string, AtlasMarker>()
    for (const event of events) {
      const point = projection(event.geometry.coordinates as [number, number])
      if (!point) continue
      const key = `${Math.floor(point[0] / gridSize)}:${Math.floor(point[1] / gridSize)}`
      const bucket = buckets.get(key)
      if (bucket) {
        const count = bucket.events.length
        bucket.x = (bucket.x * count + point[0]) / (count + 1)
        bucket.y = (bucket.y * count + point[1]) / (count + 1)
        bucket.events.push(event)
      } else {
        buckets.set(key, { key, x: point[0], y: point[1], events: [event] })
      }
    }
    return [...buckets.values()]
  }, [events, projection, transform.k])

  const zoomAt = (factor: number, anchorX = 500, anchorY = 275) => {
    setTransform((current) => {
      const nextK = Math.min(8, Math.max(1, current.k * factor))
      const worldX = (anchorX - current.x) / current.k
      const worldY = (anchorY - current.y) / current.k
      return { k: nextK, x: anchorX - worldX * nextK, y: anchorY - worldY * nextK }
    })
  }

  const zoomToMarker = (marker: AtlasMarker) => {
    if (marker.events.length === 1 || transform.k >= 7.5) {
      onSelectEvent(marker.events[0].properties.id)
      return
    }
    const nextK = Math.min(8, Math.max(transform.k * 1.9, transform.k + 1))
    setTransform({ k: nextK, x: 500 - marker.x * nextK, y: 275 - marker.y * nextK })
  }

  const onWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault()
    const bounds = event.currentTarget.getBoundingClientRect()
    const anchorX = ((event.clientX - bounds.left) / bounds.width) * 1000
    const anchorY = ((event.clientY - bounds.top) / bounds.height) * 550
    zoomAt(event.deltaY < 0 ? 1.22 : 0.82, anchorX, anchorY)
  }

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY, x: transform.x, y: transform.y }
  }

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const scaleX = 1000 / bounds.width
    const scaleY = 550 / bounds.height
    setTransform((current) => ({ ...current, x: drag.x + (event.clientX - drag.clientX) * scaleX, y: drag.y + (event.clientY - drag.clientY) * scaleY }))
  }

  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return (
    <div className="map-container atlas-svg-map">
      <svg
        viewBox="0 0 1000 550"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`World map showing ${events.length.toLocaleString()} extreme-weather events`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <rect width="1000" height="550" fill="#edf3f0" />
        <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
          <g className="country-layer" aria-hidden="true">
            {countryPaths.map((country) => country.path && <path key={country.key} d={country.path} />)}
          </g>
          <g className="event-layer">
            {markers.map((marker) => {
              const representative = marker.events[0]
              const isCluster = marker.events.length > 1
              const selected = marker.events.some((event) => event.properties.id === selectedId)
              const radius = isCluster ? Math.min(24, 10 + Math.log2(marker.events.length) * 2.1) : representative.properties.alertLevel === 'Red' ? 8 : representative.properties.alertLevel === 'Orange' ? 6.5 : 5
              return (
                <g
                  key={marker.key}
                  className={isCluster ? 'atlas-marker cluster' : 'atlas-marker event'}
                  transform={`translate(${marker.x} ${marker.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={isCluster ? `${marker.events.length} events. Activate to zoom in.` : representative.properties.name}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => zoomToMarker(marker)}
                  onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') zoomToMarker(marker) }}
                >
                  {selected && <circle className="selected-halo" r={(radius + 6) / transform.k} strokeWidth={3 / transform.k} />}
                  <circle
                    r={radius / transform.k}
                    fill={isCluster ? '#244f44' : HAZARDS[representative.properties.hazardType].color}
                    stroke="#ffffff"
                    strokeWidth={isCluster ? 2 / transform.k : 1.5 / transform.k}
                  />
                  {isCluster && <text y={3.2 / transform.k} fontSize={9.5 / transform.k}>{marker.events.length > 999 ? `${Math.round(marker.events.length / 100) / 10}k` : marker.events.length}</text>}
                  <title>{isCluster ? `${marker.events.length} events` : `${representative.properties.name} · ${representative.properties.alertLevel} alert`}</title>
                </g>
              )
            })}
          </g>
        </g>
      </svg>
      <div className="svg-map-controls" aria-label="Map controls">
        <button onClick={() => zoomAt(1.35)} aria-label="Zoom in">+</button>
        <button onClick={() => zoomAt(0.74)} aria-label="Zoom out">−</button>
        <button onClick={() => setTransform({ x: 0, y: 0, k: 1 })} aria-label="Reset world view"><Globe2 size={14} /></button>
      </div>
      <span className="map-attribution">Made with Natural Earth</span>
    </div>
  )
}

function EventDrawer({
  event,
  onClose,
  scope,
  onScopeChange,
  attention,
  articles,
  tab,
  onTabChange,
}: {
  event: EventProperties
  onClose: () => void
  scope: MediaScope
  onScopeChange: (scope: MediaScope) => void
  attention: AttentionRow[]
  articles: Article[]
  tab: DetailTab
  onTabChange: (tab: DetailTab) => void
}) {
  const hazard = HAZARDS[event.hazardType]
  const HazardIcon = hazard.icon
  const chart = useMemo(() => buildEventChart(event, attention, scope), [event, attention, scope])
  const candidateArticles = useMemo(
    () =>
      articles
        .filter((article) => scopeAllows(article.geography, event, scope) && withinWindow(article.date, event))
        .sort(newestFirst),
    [articles, event, scope],
  )

  const tabs: { id: DetailTab; label: string }[] = [
    { id: 'briefing', label: 'Briefing' },
    { id: 'attention', label: 'Attention' },
    { id: 'geography', label: 'Geography' },
    { id: 'articles', label: 'Articles' },
    { id: 'methods', label: 'Methods' },
  ]

  return (
    <aside className="event-drawer" role="dialog" aria-label={`Analysis for ${event.name}`}>
      <div className="drawer-header">
        <div className="event-kicker" style={{ color: hazard.color }}><HazardIcon size={15} /> {hazard.label}</div>
        <button className="icon-button" onClick={onClose} aria-label="Close event details"><X size={19} /></button>
        <h2>{event.name}</h2>
        <div className="event-meta">
          <span><CalendarDays size={14} /> {formatDate(event.startAt)} — {formatDate(event.endAt)}</span>
          <span><Globe2 size={14} /> {event.geographyIds.map(titleCase).join(', ') || 'Location unavailable'}</span>
        </div>
        <div className="status-row">
          <span className={`alert-badge ${event.alertLevel.toLowerCase()}`}>{event.alertLevel} alert</span>
          {event.severity != null && <span className="severity-badge">{formatCompact(event.severity)} {event.severityUnit ?? 'severity'}</span>}
          <span className="analysis-badge"><span /> Analysis pending</span>
        </div>
      </div>

      <div className="drawer-tabs" role="tablist">
        {tabs.map((item) => (
          <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} onClick={() => onTabChange(item.id)}>{item.label}</button>
        ))}
      </div>

      <div className="drawer-content">
        {tab === 'briefing' && (
          <BriefingTab event={event} chart={chart} candidateArticleCount={candidateArticles.length} scope={scope} onScopeChange={onScopeChange} />
        )}
        {tab === 'attention' && <AttentionTab event={event} chart={chart} scope={scope} onScopeChange={onScopeChange} />}
        {tab === 'geography' && <GeographyTab event={event} attention={attention} scope={scope} onScopeChange={onScopeChange} />}
        {tab === 'articles' && <ArticlesTab articles={candidateArticles} scope={scope} />}
        {tab === 'methods' && <EventMethodsTab />}
      </div>
    </aside>
  )
}

function ScopeSelect({ scope, onChange }: { scope: MediaScope; onChange: (scope: MediaScope) => void }) {
  return (
    <label className="scope-select">
      <span>Media market</span>
      <select value={scope} onChange={(event) => onChange(event.target.value as MediaScope)}>
        {(Object.entries(SCOPE_COPY) as [MediaScope, (typeof SCOPE_COPY)[MediaScope]][]).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}
      </select>
    </label>
  )
}

function BriefingTab({ event, chart, candidateArticleCount, scope, onScopeChange }: { event: EventProperties; chart: ChartResult; candidateArticleCount: number; scope: MediaScope; onScopeChange: (scope: MediaScope) => void }) {
  return (
    <>
      <div className="notice-card warning">
        <CircleAlert size={17} />
        <div><strong>Event effect not yet estimable</strong><p>This event lacks a complete 28-day attention window. The interface will calculate the briefing automatically when the continuous panel is available.</p></div>
      </div>
      <ScopeSelect scope={scope} onChange={onScopeChange} />
      <section className="drawer-section">
        <span className="eyebrow">Research readiness</span>
        <h3>What we can say now</h3>
        <div className="readiness-grid">
          <div><Check size={15} /><span><strong>Physical event</strong><small>Independent GDACS record</small></span></div>
          <div><Check size={15} /><span><strong>Geography</strong><small>{event.geographyIds.length || 0} affected market{event.geographyIds.length === 1 ? '' : 's'}</small></span></div>
          <div className={chart.coverageDays >= 14 ? '' : 'pending'}>{chart.coverageDays >= 14 ? <Check size={15} /> : <Activity size={15} />}<span><strong>Attention window</strong><small>{chart.coverageDays} of 57+ days observed</small></span></div>
          <div className="pending"><Activity size={15} /><span><strong>Event linkage</strong><small>Article validation pending</small></span></div>
        </div>
      </section>
      <section className="drawer-section">
        <div className="section-title-row"><div><span className="eyebrow">Candidate evidence</span><h3>Media published in the event window</h3></div><span className="count-pill">{candidateArticleCount}</span></div>
        <p className="muted-copy">These articles match climate or transport themes in the selected media market. They are not yet verified as reporting on this event.</p>
      </section>
      <a className="source-link" href={event.sourceUrl} target="_blank" rel="noreferrer">Open original GDACS record <ExternalLink size={14} /></a>
    </>
  )
}

type ChartResult = { points: AttentionChartPoint[]; coverageDays: number; preDays: number; postDays: number }

function buildEventChart(event: EventProperties, attention: AttentionRow[], scope: MediaScope): ChartResult {
  const relevant = attention.filter(
    (row) => row.source === 'gdelt_ngrams' && withinWindow(row.date, event) && scopeAllows(row.geography, event, scope),
  )
  const daily = new Map<string, AttentionChartPoint>()
  for (const row of relevant) {
    const point = daily.get(row.date) ?? { date: row.date, relativeDay: dayDifference(row.date, event.startAt) }
    point[row.topicId] = Number(point[row.topicId] ?? 0) + (row.matchedCount ?? 0)
    daily.set(row.date, point)
  }
  const points = [...daily.values()].sort((a, b) => a.date.localeCompare(b.date))
  return {
    points,
    coverageDays: points.length,
    preDays: points.filter((point) => point.relativeDay < 0).length,
    postDays: points.filter((point) => point.relativeDay > dayDifference(event.endAt, event.startAt)).length,
  }
}

function AttentionTab({ event, chart, scope, onScopeChange }: { event: EventProperties; chart: ChartResult; scope: MediaScope; onScopeChange: (scope: MediaScope) => void }) {
  const enoughData = chart.preDays >= 7 && chart.postDays >= 7
  return (
    <>
      <div className="tab-toolbar">
        <ScopeSelect scope={scope} onChange={onScopeChange} />
        <span className="window-chip">±28 days</span>
      </div>
      <section className="drawer-section chart-section">
        <span className="eyebrow">Article attention</span>
        <h3>Topic coverage around the event</h3>
        <p className="muted-copy">Distinct matched URLs published by outlets in {SCOPE_COPY[scope].label.toLowerCase()}.</p>
        <div className="chart-wrap">
          {chart.points.length ? (
            <Suspense fallback={<div className="chart-loading" role="status">Loading chart…</div>}>
              <AttentionChart
                points={chart.points}
                eventDuration={Math.max(0, dayDifference(event.endAt, event.startAt))}
              />
            </Suspense>
          ) : (
            <EmptyChart />
          )}
        </div>
        {!enoughData && (
          <div className="inline-note"><Info size={15} /><span>Only {chart.coverageDays} day{chart.coverageDays === 1 ? '' : 's'} of this window are present. At least seven pre- and post-event days are required for an MVP estimate.</span></div>
        )}
      </section>
      <section className="drawer-section">
        <span className="eyebrow">Before / after</span>
        <h3>Estimated change</h3>
        <div className="metric-grid">
          {TOPICS.map((topic) => <div key={topic.id} className="metric-card"><span style={{ background: topic.color }} /><small>{topic.label}</small><strong>Pending</strong><em>Needs continuous coverage</em></div>)}
        </div>
      </section>
      <section className="drawer-section">
        <span className="eyebrow">Article framing</span>
        <h3>How the discourse changes</h3>
        <p className="muted-copy">Signals overlap and will be reported as separate rates among matched articles.</p>
        <div className="framing-list">
          {['Political actors', 'Government action', 'Party politics', 'Official sources'].map((label) => (
            <div key={label}><span>{label}</span><i><b style={{ width: '0%' }} /></i><strong>Pending</strong></div>
          ))}
        </div>
      </section>
    </>
  )
}

function EmptyChart() {
  return (
    <div className="empty-chart">
      <div className="empty-chart-lines"><i /><i /><i /><i /></div>
      <Activity size={23} />
      <strong>No daily observations in this window</strong>
      <span>The event remains available for geographic exploration.</span>
    </div>
  )
}

function GeographyTab({ event, attention, scope, onScopeChange }: { event: EventProperties; attention: AttentionRow[]; scope: MediaScope; onScopeChange: (scope: MediaScope) => void }) {
  const scopeStats = useMemo(() => {
    return (Object.keys(SCOPE_COPY) as MediaScope[]).map((id) => {
      const rows = attention.filter((row) => row.source === 'gdelt_ngrams' && withinWindow(row.date, event) && scopeAllows(row.geography, event, id))
      return { id, days: new Set(rows.map((row) => row.date)).size, markets: new Set(rows.map((row) => row.geography)).size }
    })
  }, [attention, event])
  return (
    <>
      <section className="drawer-section no-top">
        <span className="eyebrow">Media geography</span>
        <h3>Choose whose response to measure</h3>
        <p className="muted-copy">Event location and publishing market are deliberately kept separate.</p>
        <div className="scope-cards">
          {scopeStats.map((item) => (
            <button key={item.id} className={scope === item.id ? 'active' : ''} onClick={() => onScopeChange(item.id)}>
              <span className="radio-dot">{scope === item.id && <i />}</span>
              <span><strong>{SCOPE_COPY[item.id].label}</strong><small>{SCOPE_COPY[item.id].description}</small></span>
              <em>{item.markets} markets · {item.days} days</em>
            </button>
          ))}
        </div>
      </section>
      <div className="notice-card info">
        <Globe2 size={17} />
        <div><strong>Outlet geography, not audience geography</strong><p>GDELT assigns each article to the publishing outlet’s source country. It does not identify where readers are located.</p></div>
      </div>
      <section className="drawer-section">
        <span className="eyebrow">Affected geography</span>
        <h3>{event.geographyIds.map(titleCase).join(', ')}</h3>
        <div className="country-code-row">{event.countryIso3s.map((code) => <span key={code}>{code}</span>)}</div>
      </section>
    </>
  )
}

function ArticlesTab({ articles, scope }: { articles: Article[]; scope: MediaScope }) {
  const [filter, setFilter] = useState<'all' | 'political'>('all')
  const politicalTotal = useMemo(() => articles.filter(hasPoliticalSignal).length, [articles])
  const filteredArticles = filter === 'political' ? articles.filter(hasPoliticalSignal) : articles
  const visibleArticles = filteredArticles.slice(0, 10)

  return (
    <>
      <div className="notice-card info">
        <ShieldCheck size={17} />
        <div><strong>Candidate evidence—not event-linked</strong><p>These articles match a configured climate or transport theme and fall within the event window. Place and hazard matching comes in the next data phase.</p></div>
      </div>
      <section className="drawer-section">
        <div className="section-title-row"><div><span className="eyebrow">{SCOPE_COPY[scope].label}</span><h3>{articles.length ? 'Articles in the window' : 'No stored articles in the window'}</h3></div></div>
        <div className="article-totals" aria-label="Article totals">
          <div><strong>{articles.length.toLocaleString()}</strong><span>All articles</span></div>
          <div className="political"><strong>{politicalTotal.toLocaleString()}</strong><span>Political</span></div>
        </div>
        <div className="article-filters" role="group" aria-label="Filter articles">
          <button className={filter === 'all' ? 'active' : ''} aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All <span>{articles.length}</span></button>
          <button className={filter === 'political' ? 'active' : ''} aria-pressed={filter === 'political'} onClick={() => setFilter('political')}>Political <span>{politicalTotal}</span></button>
        </div>
        <p className="article-filter-definition">Political includes articles flagged for political actors, government action, party politics or official sources.</p>
        <div className="article-list">
          {visibleArticles.map((article) => {
            const politicalSignals = getPoliticalSignals(article)
            return (
              <a key={article.id} href={article.url} target="_blank" rel="noreferrer" data-political={politicalSignals.length > 0 ? 'true' : 'false'}>
                <div className="article-meta">
                  <span>{article.outletName || article.domain}</span>
                  {politicalSignals.length > 0 && <span className="political-indicator">Political</span>}
                  <span>{formatDate(article.publishedAt || article.date)}</span>
                </div>
                <strong>{article.title || 'Untitled article'}</strong>
                <div className="article-tags"><span>{titleCase(article.topicId)}</span>{politicalSignals.map((signal) => <span className="political-tag" key={signal}>{signal}</span>)}</div>
              </a>
            )
          })}
        </div>
        {!filteredArticles.length && articles.length > 0 && <p className="article-empty">No politically flagged articles are stored for this event window and media market.</p>}
        {filteredArticles.length > visibleArticles.length && <p className="list-footnote">Showing 10 of {filteredArticles.length.toLocaleString()} {filter === 'political' ? 'political ' : ''}candidate articles.</p>}
      </section>
    </>
  )
}

function EventMethodsTab() {
  return (
    <section className="drawer-section no-top method-list">
      <span className="eyebrow">Event study contract</span>
      <h3>How this analysis will work</h3>
      <div><span>01</span><p><strong>Independent treatment</strong>Events come from GDACS, not the news stream being analysed.</p></div>
      <div><span>02</span><p><strong>Fixed comparison window</strong>The MVP uses 28 days before and 28 days after event onset.</p></div>
      <div><span>03</span><p><strong>Explicit media market</strong>Every estimate states whether it represents affected-country, EU, international or global outlets.</p></div>
      <div><span>04</span><p><strong>Eligibility before inference</strong>Incomplete windows and unsupported country mappings do not produce estimates.</p></div>
      <div><span>05</span><p><strong>Association, not causation</strong>Simple before/after changes remain descriptive until a control design is validated.</p></div>
    </section>
  )
}

function AnalysisLab({ manifest }: { manifest: Manifest | null }) {
  const [hypothesis, setHypothesis] = useState('attention')
  const [scope, setScope] = useState<MediaScope>('eu27')
  const [window, setWindow] = useState('28')
  const hypotheses = [
    { id: 'attention', number: 'H1', title: 'Attention response', copy: 'Extreme-weather events increase climate-related media attention.' },
    { id: 'spillover', number: 'H2', title: 'Transport spillover', copy: 'Events shift discourse toward clean transport and electric vehicles.' },
    { id: 'geography', number: 'H3', title: 'Geographic diffusion', copy: 'Affected-country, EU and international responses differ.' },
    { id: 'severity', number: 'H4', title: 'Severity gradient', copy: 'More severe events produce larger or more persistent responses.' },
  ]
  return (
    <main className="lab-view">
      <section className="lab-hero">
        <div><span className="eyebrow">Analysis Lab</span><h1>Turn events into testable questions.</h1><p>Define the media market, window and outcome before comparing responses across the global event catalogue.</p></div>
        <div className="lab-status"><span className="live-dot" /><div><strong>Research pipeline connected</strong><small>Inference waits for continuous windows</small></div></div>
      </section>

      <section className="lab-grid">
        <div className="hypothesis-panel">
          <div className="lab-section-heading"><span>1</span><div><small>Research question</small><h2>Select a hypothesis</h2></div></div>
          <div className="hypothesis-list">
            {hypotheses.map((item) => (
              <button key={item.id} onClick={() => setHypothesis(item.id)} className={hypothesis === item.id ? 'active' : ''}>
                <span>{item.number}</span><div><strong>{item.title}</strong><p>{item.copy}</p></div>{hypothesis === item.id && <Check size={17} />}
              </button>
            ))}
          </div>
        </div>

        <div className="configuration-panel">
          <div className="lab-section-heading"><span>2</span><div><small>Study design</small><h2>Configure comparison</h2></div></div>
          <div className="lab-form">
            <label><span>Event types</span><select defaultValue="all"><option value="all">All available hazards</option><option>Wildfires</option><option>Floods</option><option>Tropical cyclones</option></select></label>
            <label><span>Media market</span><select value={scope} onChange={(event) => setScope(event.target.value as MediaScope)}>{(Object.entries(SCOPE_COPY) as [MediaScope, (typeof SCOPE_COPY)[MediaScope]][]).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}</select></label>
            <label><span>Pre / post window</span><select value={window} onChange={(event) => setWindow(event.target.value)}><option value="7">7 days</option><option value="14">14 days</option><option value="28">28 days</option><option value="56">56 days</option></select></label>
            <label><span>Primary outcome</span><select defaultValue="climate_change">{TOPICS.map((topic) => <option key={topic.id} value={topic.id}>{topic.label}</option>)}</select></label>
          </div>
          <button className="run-button" disabled><Sparkles size={16} /> Run comparison <span>Waiting for panel</span></button>
        </div>

        <div className="results-panel">
          <div className="lab-section-heading"><span>3</span><div><small>Eligibility</small><h2>Evidence available today</h2></div></div>
          <div className="coverage-metrics">
            <div><strong>{manifest?.events.count.toLocaleString() ?? '—'}</strong><span>Mapped events</span><em>Ready</em></div>
            <div><strong>197</strong><span>Media markets</span><em>Mapped</em></div>
            <div><strong>{manifest?.attention.rowCount.toLocaleString() ?? '—'}</strong><span>Attention rows</span><em>Partial</em></div>
            <div><strong>0</strong><span>Complete event windows</span><em className="waiting">Waiting</em></div>
          </div>
          <div className="coverage-calendar">
            <div className="calendar-heading"><span>Daily panel coverage</span><small>Jan 2025 — Jul 2026</small></div>
            <div className="calendar-track"><span className="coverage-point january" title="1 January 2025" /><span className="coverage-block july" title="July 2026" /></div>
            <div className="calendar-labels"><span>Jan ’25</span><span>Jul ’25</span><span>Jan ’26</span><span>Jul ’26</span></div>
          </div>
          <div className="notice-card warning compact"><CircleAlert size={17} /><div><strong>Continuous collection is the next dependency</strong><p>The analytical UI is wired for a ±{window}-day {SCOPE_COPY[scope].label.toLowerCase()} comparison. Results remain disabled until eligible event windows exist.</p></div></div>
        </div>
      </section>
    </main>
  )
}

function MethodsView() {
  return (
    <main className="methods-view">
      <section className="methods-hero"><span className="eyebrow">Methods &amp; definitions</span><h1>Built to make uncertainty visible.</h1><p>The Atlas keeps physical events, publishing geography and media outcomes separate so exploratory findings remain interpretable.</p></section>
      <section className="methods-grid">
        <article><span className="method-icon"><Layers3 size={20} /></span><small>01 · Treatment</small><h2>Independent event layer</h2><p>GDACS supplies named wildfires, floods and tropical cyclones. NASA FIRMS provides a separate physical wildfire-intensity layer. News coverage never defines the primary event treatment.</p></article>
        <article><span className="method-icon"><Globe2 size={20} /></span><small>02 · Geography</small><h2>Two places, two meanings</h2><p>Event geography describes where a disaster occurred. Media geography identifies the publishing outlet’s source country—not the event location or audience.</p></article>
        <article><span className="method-icon"><BarChart3 size={20} /></span><small>03 · Outcome</small><h2>Topic attention</h2><p>Daily counts represent distinct URLs matching configured multilingual topic phrases. Topics overlap and are displayed separately rather than summed into a whole.</p></article>
        <article><span className="method-icon"><ShieldCheck size={20} /></span><small>04 · Eligibility</small><h2>No invented zeroes</h2><p>An estimate requires a complete window, supported country mapping and enough observed variation. Failed checks produce an explicit unavailable state.</p></article>
      </section>
      <section className="method-flow">
        <div><span className="eyebrow">Planned analytical path</span><h2>From event to evidence</h2></div>
        <ol>
          <li><span>1</span><strong>Select event</strong><small>Independent GDACS record</small></li>
          <li><ArrowRight size={17} /></li>
          <li><span>2</span><strong>Define market</strong><small>Local, EU or global outlets</small></li>
          <li><ArrowRight size={17} /></li>
          <li><span>3</span><strong>Check coverage</strong><small>Complete daily window</small></li>
          <li><ArrowRight size={17} /></li>
          <li><span>4</span><strong>Estimate change</strong><small>Effect and uncertainty</small></li>
        </ol>
      </section>
      <section className="limitations-section"><div><span className="eyebrow">Interpretation boundary</span><h2>What the MVP will not claim</h2></div><ul><li>Temporal change alone does not establish that an event caused media coverage.</li><li>An outlet’s country does not identify an article’s audience or subject location.</li><li>Article counts are not directly comparable across countries without accounting for media-system coverage.</li><li>Event-specific framing requires separate article-to-event linkage and validation.</li></ul></section>
    </main>
  )
}

const SOURCE_STATUS = {
  explorer: { label: 'Used in MVP', color: '#286e59' },
} as const

function DataSummary({ manifest }: { manifest: Manifest }) {
  const datedSources = manifest.dataSources.filter((source) => source.dateMin && source.dateMax)
  const coverageStart = datedSources.reduce(
    (earliest, source) => (!earliest || source.dateMin! < earliest ? source.dateMin! : earliest),
    '',
  )
  const coverageEnd = datedSources.reduce(
    (latest, source) => (!latest || source.dateMax! > latest ? source.dateMax! : latest),
    '',
  )
  const startTime = new Date(coverageStart).getTime()
  const totalDuration = Math.max(1, new Date(coverageEnd).getTime() - startTime)
  const providerCount = new Set(manifest.dataSources.map((source) => source.provider)).size

  const rangeStyle = (range: DataSourceSummary['dateRanges'][number]) => {
    const sourceStart = new Date(range.start).getTime()
    const sourceEnd = new Date(range.end).getTime()
    const left = Math.max(0, ((sourceStart - startTime) / totalDuration) * 100)
    const width = Math.max(1, ((sourceEnd - sourceStart) / totalDuration) * 100)
    return { left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }
  }

  const formatCoverageRange = (range: DataSourceSummary['dateRanges'][number]) =>
    range.start === range.end ? formatDate(range.start) : `${formatDate(range.start)} — ${formatDate(range.end)}`

  return (
    <main className="data-summary-view">
      <section className="data-hero">
        <div>
          <span className="eyebrow">Data summary</span>
          <h1>What the Atlas currently covers.</h1>
          <p>Every interval below is calculated from stored research data at export time. This page includes only datasets currently used by the MVP; experimental and unused comparison sources are omitted.</p>
        </div>
        <div className="data-snapshot">
          <Database size={18} />
          <div><strong>Snapshot generated</strong><small>{formatDate(manifest.generatedAt)}</small></div>
        </div>
      </section>

      <section className="data-summary-content">
        <div className="data-overview" aria-label="Data coverage overview">
          <div><strong>{manifest.dataSources.length}</strong><span>Source streams</span></div>
          <div><strong>{providerCount}</strong><span>Upstream providers</span></div>
          <div><strong>{formatDate(coverageStart)}</strong><span>Earliest observation</span></div>
          <div><strong>{formatDate(coverageEnd)}</strong><span>Latest observation</span></div>
        </div>

        <section className="source-coverage-panel" aria-labelledby="coverage-heading">
          <div className="data-section-heading"><div><span className="eyebrow">Coverage timeline</span><h2 id="coverage-heading">Dates available in the MVP</h2></div></div>
          <div className="source-timeline">
            <div className="source-timeline-dates"><span>{formatDate(coverageStart)}</span><span>{formatDate(coverageEnd)}</span></div>
            {manifest.dataSources.map((source) => (
              <div className="source-timeline-row" key={source.id} data-source={source.id}>
                <div><strong>{source.name}</strong><small>{source.observedDayCount.toLocaleString()} days · {source.dateRanges.length} interval{source.dateRanges.length === 1 ? '' : 's'}</small></div>
                <div className="source-timeline-track">
                  {source.dateRanges.map((range) => <span key={`${range.start}-${range.end}`} title={formatCoverageRange(range)} style={{ ...rangeStyle(range), background: SOURCE_STATUS[source.status].color }} />)}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="source-catalogue" aria-labelledby="sources-heading">
          <div className="data-section-heading"><div><span className="eyebrow">Source catalogue</span><h2 id="sources-heading">Inputs currently in use</h2></div></div>
          <div className="source-card-grid">
            {manifest.dataSources.map((source) => (
              <article className="source-card" key={source.id} data-source={source.id}>
                <div className="source-card-top"><span className="source-role">{source.role}</span><span className={`source-status ${source.status}`}><i />{SOURCE_STATUS[source.status].label}</span></div>
                <h3>{source.name}</h3>
                <p className="source-provider">{source.provider}</p>
                <p>{source.description}</p>
                <dl>
                  <div className="source-coverage-ranges"><dt>Intervals</dt><dd>{source.dateRanges.map((range) => <span key={`${range.start}-${range.end}`}>{formatCoverageRange(range)}</span>)}</dd></div>
                  <div><dt>Observed dates</dt><dd>{source.observedDayCount.toLocaleString()} · {source.coverageBasis}</dd></div>
                  <div><dt>Records</dt><dd>{source.recordCount.toLocaleString()} {source.recordLabel}</dd></div>
                  <div><dt>Geographies</dt><dd>{source.geographyCount.toLocaleString()}</dd></div>
                </dl>
                <a href={source.sourceUrl} target="_blank" rel="noreferrer">Open source documentation <ExternalLink size={13} /></a>
              </article>
            ))}
          </div>
        </section>

        <section className="data-notes">
          <div><Info size={18} /><span><strong>How to read this page</strong><small>Separate bars are separate stored intervals. Blank track space means no stored dates. Coverage is not the provider’s full historical availability, and unlike record types should not be summed.</small></span></div>
          <ul>{manifest.notes.map((note) => <li key={note}>{note}</li>)}</ul>
        </section>
      </section>
    </main>
  )
}

export default App
