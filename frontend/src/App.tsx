import { Component, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ErrorInfo, PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import { geoNaturalEarth1, geoPath } from 'd3-geo'
import type { Feature, FeatureCollection, Geometry, Point } from 'geojson'
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  CalendarDays,
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
  MapPin,
  Menu,
  Microscope,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import type { AttentionChartPoint } from './AttentionChart'
import type { EventStudyData } from './AnalysisLab'
import {
  fetchAttentionWindow,
  isSupabaseEnabled,
} from './supabase'
import type { WindowQuery } from './supabase'
import { dateWithinRange, formatDate, permutationIncreaseTest } from './utils'

const AttentionChart = lazy(() => import('./AttentionChart'))
const AnalysisLab = lazy(() => import('./AnalysisLab'))

type HazardType = 'wildfire' | 'flood'
type AlertLevel = 'Green' | 'Orange' | 'Red'
type MediaScope = 'affected' | 'eu27' | 'international' | 'global'
type View = 'explore' | 'lab' | 'data' | 'methods'
type DetailTab = 'attention' | 'coverage'
type AttentionMode = 'all' | 'political'

type EventProperties = {
  id: string
  sourceEventId: string
  hazardType: HazardType
  name: string
  startAt: string
  endAt: string
  geographyIds: string[]
  countryIso3s: string[]
  mapCountryId: string | null
  mapCountryIso3: string | null
  mapCountryLabel: string | null
  mapRegionLabel: string | null
  mapRegionType: string | null
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
  geographyLabels: Record<string, string>
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
}

const TOPICS = [
  { id: 'climate_change', label: 'Climate change', color: '#286e59' },
  { id: 'electric_vehicles', label: 'Electric vehicles', color: '#6575b7' },
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

const eventDisplayName = (event: EventProperties) => {
  if (!event.mapCountryLabel) return event.name
  if (event.hazardType === 'flood' && /^flood in /i.test(event.name)) return `Flood in ${event.mapCountryLabel}`
  if (event.hazardType === 'wildfire' && /^(forest fires?|wildfires?) in /i.test(event.name)) return `Wildfire in ${event.mapCountryLabel}`
  return event.name
}

const geographyLabel = (id: string, labels: Record<string, string>) => labels[id] || titleCase(id)

const dayDifference = (date: string, origin: string) =>
  Math.round((new Date(date).getTime() - new Date(origin).getTime()) / 86_400_000)

const formatCoordinates = ([longitude, latitude]: number[]) => {
  const latitudeLabel = `${Math.abs(latitude).toFixed(2)}°${latitude >= 0 ? 'N' : 'S'}`
  const longitudeLabel = `${Math.abs(longitude).toFixed(2)}°${longitude >= 0 ? 'E' : 'W'}`
  return `${latitudeLabel}, ${longitudeLabel}`
}

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

function remoteWindowQuery(event: EventProperties, scope: MediaScope) {
  const { start, end } = eventWindow(event)
  const query: WindowQuery = {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
    topics: TOPICS.map((topic) => topic.id),
  }
  if (scope === 'affected') query.geographies = event.geographyIds
  if (scope === 'eu27') query.geographies = [...EU27]
  if (scope === 'international') query.excludeGeographies = event.geographyIds
  return query
}

function useAtlasData() {
  const [events, setEvents] = useState<EventsGeoJSON | null>(null)
  const [world, setWorld] = useState<WorldGeoJSON | null>(null)
  const [attention, setAttention] = useState<AttentionRow[]>([])
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const [eventStudy, setEventStudy] = useState<EventStudyData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([
      fetch('/data/events.geojson').then((response) => response.json()),
      fetch('/data/world.geojson').then((response) => response.json()),
      fetch('/data/manifest.json').then((response) => response.json()),
      fetch('/data/event-study.json').then((response) => response.json()),
    ])
      .then(([eventsData, worldData, manifestData, eventStudyData]) => {
        if (!active) return
        setEvents(eventsData)
        setWorld(worldData)
        setManifest(manifestData)
        setEventStudy(eventStudyData)
      })
      .catch(() => active && setError('The local research datasets could not be loaded.'))
    if (!isSupabaseEnabled()) setError('Supabase aggregate data access is not configured.')
    return () => {
      active = false
    }
  }, [])

  return { events, world, attention, manifest, eventStudy, error }
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
  const { events, world, attention, manifest, eventStudy, error } = useAtlasData()
  const [view, setView] = useState<View>('explore')
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    const id = new URLSearchParams(window.location.search).get('event')
    return id
  })
  const [scope, setScope] = useState<MediaScope>('affected')
  const [detailTab, setDetailTab] = useState<DetailTab>('attention')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const selectedEvent = useMemo(
    () => events?.features.find((feature) => feature.properties.id === selectedId) ?? null,
    [events, selectedId],
  )

  const selectEvent = (id: string | null) => {
    setSelectedId(id)
    setDetailTab('attention')
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
          detailTab={detailTab}
          onDetailTabChange={setDetailTab}
        />
      ) : view === 'lab' ? (
        <Suspense fallback={<LoadingView />}>
          <AnalysisLab
            study={eventStudy}
            geographyLabels={manifest?.geographyLabels ?? {}}
            eventGeographies={[...new Set(events?.features.flatMap((event) => event.properties.geographyIds) ?? [])]}
            onOpenEvent={(id) => { selectEvent(id); setView('explore') }}
          />
        </Suspense>
      ) : view === 'data' && manifest ? (
        <DataSummary manifest={manifest} />
      ) : view === 'methods' ? (
        <MethodsView manifest={manifest} />
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
        eventDisplayName(event).toLowerCase().includes(normalizedQuery) ||
        event.mapRegionLabel?.toLowerCase().includes(normalizedQuery) ||
        event.mapCountryLabel?.toLowerCase().includes(normalizedQuery) ||
        event.geographyIds.some((country) => geographyLabel(country, manifest?.geographyLabels ?? {}).toLowerCase().includes(normalizedQuery))
      return (
        matchesQuery &&
        hazards.has(event.hazardType) &&
        alerts.has(event.alertLevel) &&
        dateWithinRange(startDate, dateStart, dateEnd)
      )
    })
  }, [events, manifest, query, hazards, alerts, dateStart, dateEnd])

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
                {event.properties.hazardType === 'wildfire' ? <Flame size={16} /> : <CloudRain size={16} />}
              </span>
              <span><strong>{eventDisplayName(event.properties)}</strong><small>{formatDate(event.properties.startAt)} · {event.properties.alertLevel}</small></span>
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
            coordinates={selectedEvent.geometry.coordinates}
            geographyLabels={manifest?.geographyLabels ?? {}}
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

const MAX_MAP_ZOOM = 18

function AtlasMap({ world, events, selectedId, onSelectEvent }: { world: WorldGeoJSON; events: EventFeature[]; selectedId: string | null; onSelectEvent: (id: string | null) => void }) {
  const [transform, setTransform] = useState<AtlasTransform>({ x: 0, y: 0, k: 1 })
  const [frozenClusterZoom, setFrozenClusterZoom] = useState<number | null>(null)
  const [isCameraAnimating, setIsCameraAnimating] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; clientX: number; clientY: number; x: number; y: number } | null>(null)
  const animationFrameRef = useRef<number | null>(null)
  const transformRef = useRef(transform)
  const projection = useMemo(() => geoNaturalEarth1().fitExtent([[22, 22], [978, 528]], world), [world])
  const path = useMemo(() => geoPath(projection), [projection])

  useEffect(() => { transformRef.current = transform }, [transform])

  const cancelCameraAnimation = useCallback(() => {
    if (animationFrameRef.current != null) cancelAnimationFrame(animationFrameRef.current)
    animationFrameRef.current = null
    setIsCameraAnimating(false)
  }, [])

  const animateCameraTo = useCallback((target: AtlasTransform, onComplete: () => void) => {
    cancelCameraAnimation()
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      transformRef.current = target
      setTransform(target)
      onComplete()
      return
    }
    const start = transformRef.current
    const startedAt = performance.now()
    const duration = 640
    setIsCameraAnimating(true)
    const step = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration)
      const eased = 1 - Math.pow(1 - progress, 4)
      const next = {
        x: start.x + (target.x - start.x) * eased,
        y: start.y + (target.y - start.y) * eased,
        k: start.k + (target.k - start.k) * eased,
      }
      transformRef.current = next
      setTransform(next)
      if (progress < 1) {
        animationFrameRef.current = requestAnimationFrame(step)
      } else {
        animationFrameRef.current = null
        setIsCameraAnimating(false)
        onComplete()
      }
    }
    animationFrameRef.current = requestAnimationFrame(step)
  }, [cancelCameraAnimation])

  useEffect(() => () => {
    if (animationFrameRef.current != null) cancelAnimationFrame(animationFrameRef.current)
  }, [])

  useEffect(() => {
    cancelCameraAnimation()
    setFrozenClusterZoom(null)
  }, [events, cancelCameraAnimation])

  const countryPaths = useMemo(
    () => world.features.map((feature, index) => ({ key: `${feature.properties.iso3 || feature.properties.name}-${index}`, path: path(feature) })),
    [world, path],
  )

  const markers = useMemo(() => {
    // Keep the clustering cell approximately 34 screen pixels wide. The old
    // seven-unit floor prevented real coordinates from separating at higher
    // zoom levels and forced us to display displaced "spider" markers.
    const gridSize = Math.max(0.75, 34 / (frozenClusterZoom ?? transform.k))
    const buckets = new Map<string, AtlasMarker>()
    const selected: AtlasMarker[] = []
    for (const event of events) {
      const point = projection(event.geometry.coordinates as [number, number])
      if (!point) continue
      // A cluster is drawn at its members' average projected position. Keep the
      // active event out of that aggregation so a drawer/sidebar selection is
      // always shown at its real coordinate, even while the map is zooming.
      if (event.properties.id === selectedId) {
        selected.push({
          key: `event:${event.properties.id}`,
          x: point[0],
          y: point[1],
          events: [event],
        })
        continue
      }
      const key = `${Math.floor(point[0] / gridSize)}:${Math.floor(point[1] / gridSize)}`
      const bucket = buckets.get(key)
      if (bucket) {
        // Keep the first event's real coordinate as the stable cluster anchor.
        // Recalculating a centroid here makes a numbered bubble drift whenever
        // its membership changes during zoom.
        bucket.events.push(event)
      } else {
        buckets.set(key, { key, x: point[0], y: point[1], events: [event] })
      }
    }
    const clustered = [...buckets.values()].map((marker) => marker.events.length === 1
      ? { ...marker, key: `event:${marker.events[0].properties.id}` }
      : marker)
    // Selected markers are last so SVG paints them above nearby clusters.
    return [...clustered, ...selected]
  }, [events, frozenClusterZoom, projection, selectedId, transform.k])

  const zoomAt = useCallback((factor: number, anchorX = 500, anchorY = 275) => {
    cancelCameraAnimation()
    setFrozenClusterZoom(null)
    setTransform((current) => {
      const nextK = Math.min(MAX_MAP_ZOOM, Math.max(1, current.k * factor))
      const worldX = (anchorX - current.x) / current.k
      const worldY = (anchorY - current.y) / current.k
      const next = { k: nextK, x: anchorX - worldX * nextK, y: anchorY - worldY * nextK }
      transformRef.current = next
      return next
    })
  }, [cancelCameraAnimation])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault()
      const bounds = container.getBoundingClientRect()
      const anchorX = ((event.clientX - bounds.left) / bounds.width) * 1000
      const anchorY = ((event.clientY - bounds.top) / bounds.height) * 550
      const factor = Math.min(1.55, Math.max(0.65, Math.exp(-event.deltaY * 0.0025)))
      zoomAt(factor, anchorX, anchorY)
    }
    let gestureScale = 1
    const handleGestureStart = (event: Event) => {
      event.preventDefault()
      gestureScale = 1
    }
    const handleGestureChange = (event: Event) => {
      event.preventDefault()
      const gesture = event as Event & { scale?: number; clientX?: number; clientY?: number }
      const nextScale = gesture.scale || 1
      const bounds = container.getBoundingClientRect()
      const anchorX = gesture.clientX == null ? 500 : ((gesture.clientX - bounds.left) / bounds.width) * 1000
      const anchorY = gesture.clientY == null ? 275 : ((gesture.clientY - bounds.top) / bounds.height) * 550
      zoomAt(nextScale / gestureScale, anchorX, anchorY)
      gestureScale = nextScale
    }
    container.addEventListener('wheel', handleWheel, { passive: false })
    container.addEventListener('gesturestart', handleGestureStart, { passive: false })
    container.addEventListener('gesturechange', handleGestureChange, { passive: false })
    return () => {
      container.removeEventListener('wheel', handleWheel)
      container.removeEventListener('gesturestart', handleGestureStart)
      container.removeEventListener('gesturechange', handleGestureChange)
    }
  }, [zoomAt])

  const zoomToMarker = (marker: AtlasMarker) => {
    if (marker.events.length === 1) {
      cancelCameraAnimation()
      onSelectEvent(marker.events[0].properties.id)
      return
    }
    const current = transformRef.current
    const nextK = Math.min(12, Math.max(current.k * 2.35, 7 + Math.log10(marker.events.length)))
    setFrozenClusterZoom(current.k)
    animateCameraTo(
      { k: nextK, x: 500 - marker.x * nextK, y: 275 - marker.y * nextK },
      () => setFrozenClusterZoom(null),
    )
  }

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    cancelCameraAnimation()
    setFrozenClusterZoom(null)
    event.currentTarget.setPointerCapture(event.pointerId)
    const current = transformRef.current
    dragRef.current = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY, x: current.x, y: current.y }
  }

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const scaleX = 1000 / bounds.width
    const scaleY = 550 / bounds.height
    setTransform((current) => {
      const next = { ...current, x: drag.x + (event.clientX - drag.clientX) * scaleX, y: drag.y + (event.clientY - drag.clientY) * scaleY }
      transformRef.current = next
      return next
    })
  }

  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return (
    <div className="map-container atlas-svg-map" ref={containerRef} data-camera-animating={isCameraAnimating ? 'true' : 'false'}>
      <svg
        viewBox="0 0 1000 550"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`World map showing ${events.length.toLocaleString()} extreme-weather events`}
        data-zoom={transform.k.toFixed(3)}
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
                  data-count={marker.events.length}
                  data-event-id={isCluster ? undefined : representative.properties.id}
                  transform={`translate(${marker.x} ${marker.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={isCluster ? `${marker.events.length} events. Activate to zoom in and separate them.` : eventDisplayName(representative.properties)}
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
                  <title>{isCluster ? `${marker.events.length} events` : `${eventDisplayName(representative.properties)} · ${representative.properties.alertLevel} alert`}</title>
                </g>
              )
            })}
          </g>
        </g>
      </svg>
      <div className="svg-map-controls" aria-label="Map controls">
        <button onClick={() => zoomAt(1.35)} aria-label="Zoom in">+</button>
        <button onClick={() => zoomAt(0.74)} aria-label="Zoom out">−</button>
        <button onClick={() => { cancelCameraAnimation(); setFrozenClusterZoom(null); transformRef.current = { x: 0, y: 0, k: 1 }; setTransform({ x: 0, y: 0, k: 1 }) }} aria-label="Reset world view"><Globe2 size={14} /></button>
      </div>
      <span className="map-attribution">Made with Natural Earth</span>
    </div>
  )
}

function EventDrawer({
  event,
  coordinates,
  onClose,
  scope,
  onScopeChange,
  attention,
  geographyLabels,
  tab,
  onTabChange,
}: {
  event: EventProperties
  coordinates: number[]
  onClose: () => void
  scope: MediaScope
  onScopeChange: (scope: MediaScope) => void
  attention: AttentionRow[]
  geographyLabels: Record<string, string>
  tab: DetailTab
  onTabChange: (tab: DetailTab) => void
}) {
  const hazard = HAZARDS[event.hazardType]
  const HazardIcon = hazard.icon
  const displayName = eventDisplayName(event)
  const [attentionMode, setAttentionMode] = useState<AttentionMode>('all')
  const remoteAttention = useRemoteAttention(event, scope)
  const chartRows = isSupabaseEnabled() ? remoteAttention.rows : attention
  const chart = useMemo(() => buildEventChart(event, chartRows, scope, attentionMode), [event, chartRows, scope, attentionMode])
  const coverageRows = useMemo(() => eventAttentionRows(event, chartRows, scope), [event, chartRows, scope])
  const locationLabel = [event.mapRegionLabel, event.mapCountryLabel].filter(Boolean).join(', ') || 'Offshore or unavailable'
  const affectedLabels = event.geographyIds.map((id) => geographyLabel(id, geographyLabels))
  const tabs: { id: DetailTab; label: string }[] = [
    { id: 'attention', label: 'Attention' },
    { id: 'coverage', label: 'Coverage breakdown' },
  ]
  return (
    <aside className="event-drawer" role="dialog" aria-label={`Analysis for ${displayName}`}>
      <div className="drawer-header">
        <div className="event-kicker" style={{ color: hazard.color }}><HazardIcon size={15} /> {hazard.label}</div>
        <button className="icon-button" onClick={onClose} aria-label="Close event details"><X size={19} /></button>
        <h2>{displayName}</h2>
        <div className="event-meta">
          <span><CalendarDays size={14} /> {formatDate(event.startAt)} — {formatDate(event.endAt)}</span>
          <span title={event.mapRegionType || undefined}><MapPin size={14} /> Map point: {locationLabel}</span>
          <span className="coordinate-label">{formatCoordinates(coordinates)}</span>
          {affectedLabels.length > 0 && <span><Globe2 size={14} /> Affected: {affectedLabels.join(', ')}</span>}
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
        {tab === 'attention' && <AttentionTab event={event} chart={chart} scope={scope} onScopeChange={onScopeChange} mode={attentionMode} onModeChange={setAttentionMode} loading={remoteAttention.loading} error={remoteAttention.error} />}
        {tab === 'coverage' && <CoverageBreakdown event={event} rows={coverageRows} scope={scope} onScopeChange={onScopeChange} geographyLabels={geographyLabels} loading={remoteAttention.loading} error={remoteAttention.error} />}
      </div>
    </aside>
  )
}

function useRemoteAttention(event: EventProperties, scope: MediaScope) {
  const [rows, setRows] = useState<AttentionRow[]>([])
  const [loading, setLoading] = useState(isSupabaseEnabled())
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isSupabaseEnabled()) return
    let active = true
    setLoading(true)
    setError(null)
    fetchAttentionWindow(remoteWindowQuery(event, scope))
      .then((result) => {
        if (active) setRows(result)
      })
      .catch(() => {
        if (active) {
          setRows([])
          setError('Daily attention could not be loaded from Supabase. Please retry.')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [event, scope])

  return { rows, loading, error }
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

type ChartResult = { points: AttentionChartPoint[]; coverageDays: number; preDays: number; postDays: number }

function eventAttentionRows(event: EventProperties, attention: AttentionRow[], scope: MediaScope) {
  return attention.filter(
    (row) => row.source === 'gdelt_ngrams' && withinWindow(row.date, event) && scopeAllows(row.geography, event, scope),
  )
}

function buildEventChart(event: EventProperties, attention: AttentionRow[], scope: MediaScope, mode: AttentionMode): ChartResult {
  const relevant = eventAttentionRows(event, attention, scope)
  const daily = new Map<string, AttentionChartPoint>()
  for (const row of relevant) {
    const value = mode === 'political' ? row.politicalCount : row.matchedCount
    if (value == null) continue
    const point = daily.get(row.date) ?? { date: row.date, relativeDay: dayDifference(row.date, event.startAt) }
    point[row.topicId] = Number(point[row.topicId] ?? 0) + value
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

function AttentionModeToggle({ mode, onChange }: { mode: AttentionMode; onChange: (mode: AttentionMode) => void }) {
  return (
    <div className="attention-mode-toggle" role="group" aria-label="Attention measure">
      <button className={mode === 'all' ? 'active' : ''} aria-pressed={mode === 'all'} onClick={() => onChange('all')}>All articles</button>
      <button className={mode === 'political' ? 'active' : ''} aria-pressed={mode === 'political'} onClick={() => onChange('political')}>Political only</button>
    </div>
  )
}

function AttentionTab({ event, chart, scope, onScopeChange, mode, onModeChange, loading, error }: { event: EventProperties; chart: ChartResult; scope: MediaScope; onScopeChange: (scope: MediaScope) => void; mode: AttentionMode; onModeChange: (mode: AttentionMode) => void; loading: boolean; error: string | null }) {
  const enoughData = chart.preDays >= 7 && chart.postDays >= 7
  return (
    <>
      <div className="tab-toolbar">
        <ScopeSelect scope={scope} onChange={onScopeChange} />
        <span className="window-chip">±28 days</span>
      </div>
      <section className="drawer-section chart-section">
        <span className="eyebrow">Article attention</span>
        <h3>{mode === 'political' ? 'Political topic coverage' : 'Topic coverage'} around the event</h3>
        <p className="muted-copy">{mode === 'political' ? 'Distinct matched URLs containing a political actor, government action, party-politics or official-source signal' : 'Distinct matched URLs'} published by outlets in {SCOPE_COPY[scope].label.toLowerCase()}.</p>
        <AttentionModeToggle mode={mode} onChange={onModeChange} />
        <div className="chart-wrap">
          {loading ? (
            <div className="chart-loading" role="status">Loading daily attention…</div>
          ) : chart.points.length ? (
            <Suspense fallback={<div className="chart-loading" role="status">Loading chart…</div>}>
              <AttentionChart
                points={chart.points}
                eventDuration={Math.max(0, dayDifference(event.endAt, event.startAt))}
                eventStartLabel={formatDate(event.startAt)}
                eventEndLabel={formatDate(event.endAt)}
                topics={TOPICS}
              />
            </Suspense>
          ) : (
            <EmptyChart message={mode === 'political' ? 'Political classification was not collected for this window.' : undefined} />
          )}
        </div>
        {error && <div className="inline-note"><CircleAlert size={15} /><span>{error}</span></div>}
        {!enoughData && (
          <div className="inline-note"><Info size={15} /><span>Only {chart.coverageDays} day{chart.coverageDays === 1 ? '' : 's'} of this window are present. At least seven pre- and post-event days are required for an MVP estimate.</span></div>
        )}
      </section>
      <BeforeAfterAnalysis event={event} chart={chart} mode={mode} />
    </>
  )
}

const shiftDate = (value: string, days: number) => {
  const result = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  result.setUTCDate(result.getUTCDate() + days)
  return result.toISOString().slice(0, 10)
}

function BeforeAfterAnalysis({ event, chart, mode }: { event: EventProperties; chart: ChartResult; mode: AttentionMode }) {
  const [windowDays, setWindowDays] = useState(7)
  const evaluations = useMemo(() => {
    const byDate = new Map(chart.points.map((point) => [point.date, point]))
    const beforeDates = Array.from({ length: windowDays }, (_, index) => shiftDate(event.startAt, index - windowDays))
    const afterDates = Array.from({ length: windowDays }, (_, index) => shiftDate(event.endAt, index + 1))
    const collect = (dates: string[], topicId: string) => {
      const values: number[] = []
      const missing: string[] = []
      for (const date of dates) {
        const value = byDate.get(date)?.[topicId]
        if (typeof value === 'number') values.push(value)
        else missing.push(date)
      }
      return { values, missing }
    }
    return TOPICS.map((topic) => {
      const before = collect(beforeDates, topic.id)
      const after = collect(afterDates, topic.id)
      return {
        topic,
        before,
        after,
        result: before.missing.length || after.missing.length ? null : permutationIncreaseTest(before.values, after.values),
      }
    })
  }, [chart.points, event.endAt, event.startAt, windowDays])

  return (
    <section className="drawer-section before-after-analysis" aria-live="polite">
      <div className="before-after-heading">
        <div><span className="eyebrow">Before / after</span><h3>Did attention increase?</h3></div>
        <label><span>Comparison window</span><select value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value))}><option value={7}>7 days</option><option value={14}>14 days</option><option value={28}>28 days</option></select></label>
      </div>
      <p className="muted-copy">Mean daily {mode === 'political' ? 'politically flagged ' : ''}matched URLs before and after the event, using complete days only.</p>
      <div className="before-after-grid">
        {evaluations.map(({ topic, before, after, result }) => {
          const significantIncrease = Boolean(result && result.difference > 0 && result.pValue < 0.05)
          const status = !result ? 'unavailable' : significantIncrease ? 'increase' : 'no-detectable-increase'
          const verdict = !result
            ? 'Not testable'
            : significantIncrease
              ? 'Evidence of increase'
              : result.difference > 0
                ? 'Increase not distinguishable'
                : 'No increase observed'
          const pValue = result ? (result.pValue < 0.001 ? '<0.001' : result.pValue.toFixed(3)) : null
          return (
            <article key={topic.id} className={significantIncrease ? 'before-after-card significant' : 'before-after-card'} data-topic={topic.id} data-test-status={status}>
              <header><i style={{ background: topic.color }} /><strong>{topic.label}</strong><span>{verdict}</span></header>
              {!result ? (
                <p className="before-after-unavailable"><CircleAlert size={14} /> Missing {before.missing.length} before and {after.missing.length} after day{after.missing.length === 1 ? '' : 's'}.</p>
              ) : (
                <>
                  <div className="before-after-values">
                    <span><small>Before</small><b>{result.beforeMean.toFixed(1)}</b><em>URLs/day</em></span>
                    <span><small>After</small><b>{result.afterMean.toFixed(1)}</b><em>URLs/day</em></span>
                    <span className="change"><small>Change</small><b>{result.difference > 0 ? '+' : ''}{result.difference.toFixed(1)}</b><em>{result.percentChange == null ? 'zero baseline' : `${result.percentChange > 0 ? '+' : ''}${result.percentChange.toFixed(0)}%`}</em></span>
                  </div>
                  <p className="before-after-test">One-sided p = {pValue} · {result.method === 'exact' ? 'exact' : `${result.permutations.toLocaleString()}-draw`} permutation test</p>
                </>
              )}
            </article>
          )
        })}
      </div>
      <div className="inline-note association-note"><Info size={15} /><span>This is an exploratory association test, not a causal estimate. “Not statistically distinguishable” is not evidence of no effect; stronger inference needs control dates or unaffected media markets and correction for multiple testing.</span></div>
    </section>
  )
}

function EmptyChart({ message }: { message?: string }) {
  return (
    <div className="empty-chart">
      <div className="empty-chart-lines"><i /><i /><i /><i /></div>
      <Activity size={23} />
      <strong>No daily observations in this window</strong>
      <span>{message || 'The event remains available for geographic exploration.'}</span>
    </div>
  )
}

type CoveragePeriod = 'before' | 'during' | 'after'

function rowPeriod(date: string, event: EventProperties): CoveragePeriod {
  const day = date.slice(0, 10)
  if (day < event.startAt.slice(0, 10)) return 'before'
  if (day > event.endAt.slice(0, 10)) return 'after'
  return 'during'
}

function CoverageBreakdown({
  event,
  rows,
  scope,
  onScopeChange,
  geographyLabels,
  loading,
  error,
}: {
  event: EventProperties
  rows: AttentionRow[]
  scope: MediaScope
  onScopeChange: (scope: MediaScope) => void
  geographyLabels: Record<string, string>
  loading: boolean
  error: string | null
}) {
  const [country, setCountry] = useState('all')
  const countryOptions = useMemo(
    () => [...new Set(rows.map((row) => row.geography))]
      .map((id) => ({ id, label: geographyLabel(id, geographyLabels) }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    [geographyLabels, rows],
  )
  const selectedRows = useMemo(
    () => country === 'all' ? rows : rows.filter((row) => row.geography === country),
    [country, rows],
  )

  useEffect(() => setCountry('all'), [event.id, scope])

  const totalMatches = selectedRows.reduce((total, row) => total + (row.matchedCount ?? 0), 0)
  const politicalMatches = selectedRows.reduce((total, row) => total + (row.politicalCount ?? 0), 0)
  const observedDays = new Set(selectedRows.map((row) => row.date)).size
  const marketCount = new Set(selectedRows.map((row) => row.geography)).size
  const politicalShare = totalMatches ? (politicalMatches / totalMatches) * 100 : null

  const phaseStats = TOPICS.map((topic) => ({
    topic,
    periods: (['before', 'during', 'after'] as CoveragePeriod[]).map((period) => {
      const periodRows = selectedRows.filter((row) => rowPeriod(row.date, event) === period)
      const allDaily = new Map<string, number>()
      const politicalDaily = new Map<string, number>()
      for (const row of periodRows) {
        if (row.topicId !== topic.id) continue
        if (row.matchedCount != null) allDaily.set(row.date, (allDaily.get(row.date) ?? 0) + row.matchedCount)
        if (row.politicalCount != null) politicalDaily.set(row.date, (politicalDaily.get(row.date) ?? 0) + row.politicalCount)
      }
      const mean = (values: number[]) => values.length ? values.reduce((total, value) => total + value, 0) / values.length : null
      return {
        period,
        all: mean([...allDaily.values()]),
        political: mean([...politicalDaily.values()]),
        days: allDaily.size,
      }
    }),
  }))

  const signals = [
    { label: 'Political actor', key: 'politicalActorCount' as const },
    { label: 'Government action', key: 'governmentActionCount' as const },
    { label: 'Party politics', key: 'partyPoliticsCount' as const },
    { label: 'Official source', key: 'officialSourceCount' as const },
  ].map((signal) => ({ ...signal, value: selectedRows.reduce((total, row) => total + (row[signal.key] ?? 0), 0) }))

  const marketTotals = [...selectedRows.reduce((totals, row) => {
    totals.set(row.geography, (totals.get(row.geography) ?? 0) + (row.matchedCount ?? 0))
    return totals
  }, new Map<string, number>())]
    .map(([id, value]) => ({ id, label: geographyLabel(id, geographyLabels), value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8)
  const largestMarket = marketTotals[0]?.value ?? 0

  return (
    <>
      <div className="tab-toolbar coverage-toolbar">
        <ScopeSelect scope={scope} onChange={onScopeChange} />
        <label><span>Publishing market</span><select value={country} onChange={(input) => setCountry(input.target.value)}><option value="all">All in scope</option>{countryOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
      </div>
      <section className="drawer-section coverage-breakdown">
        <span className="eyebrow">Aggregate coverage</span>
        <h3>What changed, and where?</h3>
        <p className="muted-copy">Daily topic-match counts from the same ±28-day window as the graph. This replaces article browsing with a view of timing, political content and publishing-market composition.</p>
        {country !== 'all' && <span className="coverage-market-context">Publishing market · {geographyLabel(country, geographyLabels)}</span>}
        {loading ? <div className="coverage-loading" role="status">Loading coverage breakdown…</div> : (
          <>
            <div className="coverage-summary" aria-label="Coverage summary">
              <div><strong>{totalMatches.toLocaleString()}</strong><span>Topic matches</span></div>
              <div><strong>{politicalMatches.toLocaleString()}</strong><span>Political matches</span></div>
              <div><strong>{politicalShare == null ? '—' : `${politicalShare.toFixed(1)}%`}</strong><span>Political share</span></div>
              <div><strong>{country === 'all' ? marketCount.toLocaleString() : observedDays.toLocaleString()}</strong><span>{country === 'all' ? 'Publishing markets' : 'Observed days'}</span></div>
            </div>

            <div className="coverage-section-heading"><div><span className="eyebrow">Timing</span><h4>Average daily URLs by phase</h4></div><small>Event duration shown separately</small></div>
            <div className="phase-table" role="table" aria-label="Average daily coverage before, during and after the event">
              <div role="row"><span role="columnheader">Theme</span><span role="columnheader">Before</span><span role="columnheader">During</span><span role="columnheader">After</span></div>
              {phaseStats.map(({ topic, periods }) => (
                <div role="row" key={topic.id} data-topic={topic.id}>
                  <strong role="cell"><i style={{ background: topic.color }} />{topic.label}</strong>
                  {periods.map((period) => <span role="cell" key={period.period}><b>{period.all == null ? '—' : period.all.toFixed(1)}</b><small>{period.political == null ? '—' : period.political.toFixed(1)} political · {period.days}d</small></span>)}
                </div>
              ))}
            </div>

            <div className="coverage-section-heading"><div><span className="eyebrow">Political composition</span><h4>Signals within topic matches</h4></div><small>Signals overlap</small></div>
            <div className="political-signal-summary">
              {signals.map((signal) => <div key={signal.key}><strong>{signal.value.toLocaleString()}</strong><span>{signal.label}</span></div>)}
            </div>

            {country === 'all' && <>
              <div className="coverage-section-heading"><div><span className="eyebrow">Geography</span><h4>Largest publishing markets</h4></div><small>Top {marketTotals.length}</small></div>
              <div className="market-ranking">
                {marketTotals.map((market) => <button key={market.id} onClick={() => setCountry(market.id)}><span>{market.label}</span><i><b style={{ width: `${largestMarket ? (market.value / largestMarket) * 100 : 0}%` }} /></i><strong>{market.value.toLocaleString()}</strong></button>)}
              </div>
            </>}
          </>
        )}
        {error && <div className="inline-note"><CircleAlert size={15} /><span>{error}</span></div>}
        <div className="inline-note"><Info size={15} /><span>Averages use the observed days shown; missing dates are not treated as zero. Counts are topic–URL observations. A URL matching both themes contributes once to each theme, and overlapping political components should not be added together.</span></div>
      </section>
    </>
  )
}

function MethodsView({ manifest }: { manifest: Manifest | null }) {
  const topicTranslations = [
    {
      id: 'climate_change',
      label: 'Climate change',
      definition: 'General public and media language about anthropogenic climate change.',
      rationale: 'The broad outcome: whether an event changes attention to climate change itself.',
      phrases: [
        ['English · validated', 'climate change · global warming · climate crisis'],
        ['Spanish · draft', 'cambio climático · calentamiento global · crisis climática'],
        ['Portuguese · draft', 'mudanças climáticas · alteração climática · aquecimento global · crise climática'],
        ['French · draft', 'changement climatique · réchauffement climatique · crise climatique'],
        ['German · draft', 'Klimawandel · globale Erwärmung · Klimakrise'],
        ['Italian · draft', 'cambiamento climatico · riscaldamento globale · crisi climatica'],
        ['Russian · draft', 'изменение климата · глобальное потепление · климатический кризис'],
        ['Arabic · draft', 'تغير المناخ · الاحتباس الحراري · أزمة المناخ'],
        ['Chinese · draft', '气候变化 · 全球变暖 · 气候危机'],
        ['Japanese · draft', '気候変動 · 地球温暖化 · 気候危機'],
      ],
    },
    {
      id: 'electric_vehicles',
      label: 'Electric vehicles',
      definition: 'Explicit references to electric vehicles or electric cars.',
      rationale: 'A transport-specific outcome relevant to T&E, narrow enough to audit across languages.',
      phrases: [
        ['English · validated', 'electric vehicle · electric vehicles · electric car · electric cars'],
        ['Spanish · draft', 'vehículo eléctrico · vehículos eléctricos · coche eléctrico · coches eléctricos'],
        ['Portuguese · draft', 'veículo elétrico · veículos elétricos · carro elétrico · carros elétricos'],
        ['French · draft', 'véhicule électrique · véhicules électriques · voiture électrique · voitures électriques'],
        ['German · draft', 'Elektrofahrzeug · Elektrofahrzeuge · Elektroauto · Elektroautos'],
        ['Italian · draft', 'veicolo elettrico · veicoli elettrici · auto elettrica · auto elettriche'],
        ['Russian · draft', 'электромобиль · электромобили · электрический автомобиль'],
        ['Arabic · draft', 'سيارة كهربائية · سيارات كهربائية · مركبة كهربائية · مركبات كهربائية'],
        ['Chinese · draft', '电动汽车 · 电动车'],
        ['Japanese · draft', '電気自動車'],
      ],
    },
  ]

  const references = [
    {
      number: '01',
      title: 'GDELT Web News NGrams 3.0',
      organisation: 'The GDELT Project, 2021',
      note: 'Dataset structure, language segmentation, article URLs and contextual phrase reconstruction.',
      href: 'https://blog.gdeltproject.org/announcing-the-new-web-news-ngrams-3-0-dataset/',
    },
    {
      number: '02',
      title: 'Custom media catalogues with Web NGrams',
      organisation: 'The GDELT Project, 2022',
      note: 'Method for joining matching URLs to external domain catalogues.',
      href: 'https://blog.gdeltproject.org/using-web-ngrams-3-0-custom-media-catalogs-to-segment-by-country-state-ownership-partisanship-or-other-attributes/',
    },
    {
      number: '03',
      title: 'GDACS API',
      organisation: 'Global Disaster Alert and Coordination System',
      note: 'Event, episode, alert-level and archive endpoints used for the event catalogue.',
      href: 'https://www.gdacs.org/gdacsapi/swagger/index.html',
    },
    {
      number: '04',
      title: 'GDACS flood methodology',
      organisation: 'European Commission Joint Research Centre',
      note: 'Impact-oriented flood alerts and hazard-specific severity context.',
      href: 'https://www.gdacs.org/Knowledge/models_fl.aspx',
    },
    {
      number: '05',
      title: 'Natural Earth 1:50m cultural vectors',
      organisation: 'Natural Earth',
      note: 'Administrative country polygons used to check the country containing each event point.',
      href: 'https://www.naturalearthdata.com/downloads/50m-cultural-vectors/',
    },
    {
      number: '06',
      title: 'Permutation test reference',
      organisation: 'SciPy documentation',
      note: 'Exact and randomised independent-sample permutation-test mechanics.',
      href: 'https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html',
    },
    {
      number: '07',
      title: 'Natural Earth Admin-1 states and provinces',
      organisation: 'Natural Earth, version 5.1.1',
      note: 'First-order administrative polygons used to label the region containing each event point.',
      href: 'https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/',
    },
    {
      number: '08',
      title: 'GDELT infrastructure outage notice',
      organisation: 'Kalev Hannes Leetaru / GDELT, June 2025',
      note: 'Provider confirmation of multiple GDELT infrastructure outages during the observed June 2025 coverage collapse.',
      href: 'https://www.linkedin.com/posts/kalevleetaru_we-are-aware-of-multiple-gdelt-infrastructure-activity-7340435180601393154-_SDg',
    },
  ]

  return (
    <main className="methods-view">
      <section className="methods-hero">
        <div>
          <span className="eyebrow">Research protocol · MVP v0.1</span>
          <h1>How the Atlas turns events into evidence.</h1>
          <p>This protocol defines what is counted, how places and political content are classified, and what the before-and-after comparison can support. Definitions describe the current exported MVP—not the full historical availability of its providers.</p>
        </div>
        <div className="methods-hero-meta">
          <span><ShieldCheck size={16} /> Transparent by design</span>
          <small>Last data export {manifest ? formatDate(manifest.generatedAt) : 'not available'}</small>
        </div>
      </section>

      <section className="method-principles" aria-label="Methodological principles">
        <article><span><Layers3 size={18} /></span><div><small>Independent treatment</small><strong>Weather events are defined outside the news data.</strong></div></article>
        <article><span><Globe2 size={18} /></span><div><small>Separate geographies</small><strong>Event location and outlet country are not interchangeable.</strong></div></article>
        <article><span><ShieldCheck size={18} /></span><div><small>Explicit missingness</small><strong>Missing dates are unavailable, never invented zeroes.</strong></div></article>
      </section>

      <section className="methods-shell">
        <aside className="methods-toc" aria-label="Methods contents">
          <span className="eyebrow">On this page</span>
          <nav>
            <a href="#research-design"><span>01</span> Research design</a>
            <a href="#topics"><span>02</span> Topic taxonomy</a>
            <a href="#political"><span>03</span> Political classification</a>
            <a href="#collection"><span>04</span> News collection</a>
            <a href="#events"><span>05</span> Weather events</a>
            <a href="#geography"><span>06</span> Geography &amp; scope</a>
            <a href="#measurement"><span>07</span> Attention measures</a>
            <a href="#before-after"><span>08</span> Before / after test</a>
            <a href="#coverage-breakdown-method"><span>09</span> Coverage breakdown</a>
            <a href="#decisions"><span>10</span> Decision register</a>
            <a href="#limitations"><span>11</span> Limits &amp; validation</a>
            <a href="#references"><span>12</span> References</a>
          </nav>
        </aside>

        <div className="methods-protocol">
          <section className="protocol-section" id="research-design">
            <header><span>01</span><div><small>Foundation</small><h2>Research design</h2></div></header>
            <p className="protocol-lede">The Atlas asks whether attention to climate and transport topics changes around weather events, whether that response differs by publishing market or political content, and whether attention co-moves with accumulated event activity.</p>
            <div className="method-definition-grid three">
              <article><small>Event unit</small><strong>One GDACS event</strong><p>A stable provider ID, hazard type, start and end time, affected countries, point geometry and provider alert fields.</p></article>
              <article><small>Attention unit</small><strong>Topic × outlet country × UTC day</strong><p>A daily count of distinct matching article URLs. Original source language is retained where available.</p></article>
              <article><small>Comparison unit</small><strong>One eligible event window</strong><p>Complete daily observations before and after the event, evaluated separately for each topic, media scope and attention mode.</p></article>
            </div>
            <div className="methods-pipeline" aria-label="Data flow from independent weather events and news articles to an event-window comparison">
              <div className="pipeline-source"><MapPin size={18} /><small>Event stream</small><strong>GDACS records</strong><span>Where and when</span></div>
              <ArrowRight size={17} />
              <div className="pipeline-source"><Search size={18} /><small>News stream</small><strong>GDELT URLs</strong><span>Topic and outlet</span></div>
              <ArrowRight size={17} />
              <div className="pipeline-join"><Layers3 size={18} /><small>Defined join</small><strong>Scope + date window</strong><span>No event inference from news</span></div>
              <ArrowRight size={17} />
              <div className="pipeline-result"><BarChart3 size={18} /><small>Output</small><strong>Change in URLs/day</strong><span>With an uncertainty test</span></div>
            </div>
            <p className="method-caption"><strong>Why independent streams?</strong> Defining events from the same coverage being explained would favour events that already received more news attention.</p>
          </section>

          <section className="protocol-section" id="topics">
            <header><span>02</span><div><small>Outcome definitions</small><h2>Topic taxonomy</h2></div></header>
            <p className="protocol-lede">The current MVP measures two deliberately distinct concepts. Exact phrases inside a topic are alternatives; a URL matching several phrases is still counted once for that topic. A URL may count once in each topic.</p>
            <div className="topic-method-grid">
              {topicTranslations.map((topic) => (
                <article className="topic-method-card" key={topic.id} data-topic={topic.id}>
                  <div className="topic-method-heading"><span className="status-chip active">Active</span><small>{topic.id}</small></div>
                  <h3>{topic.label}</h3>
                  <p><strong>Definition.</strong> {topic.definition}</p>
                  <p><strong>Why included.</strong> {topic.rationale}</p>
                  <details>
                    <summary>View exact multilingual phrases <ChevronRight size={14} /></summary>
                    <div className="translation-table">
                      {topic.phrases.map(([language, phrases]) => <div key={language}><strong>{language}</strong><span>{phrases}</span></div>)}
                    </div>
                  </details>
                </article>
              ))}
            </div>
            <div className="candidate-topics">
              <div><span className="status-chip held">Held back</span><strong>Clean energy</strong><p>Renewable and low-carbon energy technologies and deployment.</p></div>
              <div><span className="status-chip held">Held back</span><strong>Clean transport</strong><p>Low-carbon mobility, transport decarbonisation, electrification, zero-emission movement and modal shift.</p></div>
              <p>These dictionaries remain in project configuration for later validation, but are excluded from the two-topic MVP so exploratory results do not outrun taxonomy review.</p>
            </div>
            <div className="method-callout"><Info size={17} /><p><strong>Translation status.</strong> English seeds are reviewed and marked validated. Spanish, Portuguese, French, German, Italian, Russian, Arabic, Chinese and Japanese terms remain draft until native-speaker review for local usage, inflection and conceptual equivalence. Chinese and Japanese are matched as character sequences.</p></div>
          </section>

          <section className="protocol-section" id="political">
            <header><span>03</span><div><small>Derived classification</small><h2>What “political” means</h2></div></header>
            <p className="protocol-lede">“Political” is a broad discourse-relevance flag, not a claim about tone, ideology, support, opposition or causation.</p>
            <div className="signal-grid">
              <article><small>01</small><strong>Political actor</strong><p>References to elected institutions, office-holders or parties—for example government, minister, parliament or president.</p></article>
              <article><small>02</small><strong>Government action</strong><p>References to policy, law, regulation, public spending, targets, bans or official decisions.</p></article>
              <article><small>03</small><strong>Party politics</strong><p>Electoral competition, governing or opposition parties, and configured major-party names.</p></article>
              <article><small>04</small><strong>Official source</strong><p>The article hostname matches a versioned registry of government, parliamentary or political-party domains.</p></article>
            </div>
            <div className="method-equation"><span>political URL</span><strong>= actor <em>OR</em> action <em>OR</em> party <em>OR</em> official source</strong></div>
            <ul className="method-rules">
              <li>The measure is the distinct-URL union. Component signals overlap and must not be added together.</li>
              <li>Phrase signals may appear anywhere in indexed article text; they do not prove the political actor discussed the weather event.</li>
              <li>The explicit official-domain registry is strongest for the United Kingdom, France, Spain, Germany and Italy. Generic translated phrase signals are global, but non-English translations remain draft.</li>
            </ul>
          </section>

          <section className="protocol-section" id="collection">
            <header><span>04</span><div><small>News data</small><h2>How coverage is queried and sources are selected</h2></div></header>
            <p className="protocol-lede">The collector uses parameterised BigQuery SQL to match configured literal phrases in GDELT Web News NGrams 3.0 original-language text. This is deterministic phrase matching, not an AI-model query.</p>
            <ol className="collection-steps">
              <li><span>1</span><div><strong>Scan configured anchors</strong><p>All active topics are evaluated in one date-window scan. Lower- and title-case anchors reduce query cost.</p></div></li>
              <li><span>2</span><div><strong>Reconstruct the phrase</strong><p>The <code>pre</code>, <code>ngram</code> and <code>post</code> context fields are recombined, with character joining for Chinese and Japanese.</p></div></li>
              <li><span>3</span><div><strong>Deduplicate URLs</strong><p>Synonyms, translations and repeat NGram rows collapse to one URL per topic and UTC day.</p></div></li>
              <li><span>4</span><div><strong>Assign outlet country</strong><p>The article domain is joined to GDELT’s multilingual April 2015 domain-country catalogue. The longest unambiguous suffix wins.</p></div></li>
              <li><span>5</span><div><strong>Aggregate and audit</strong><p>Daily topic and political counts are exported with article metadata, query metadata and coverage checks.</p></div></li>
            </ol>
            <div className="source-selection-note">
              <Database size={18} />
              <div><strong>There is no manually curated global outlet list.</strong><p>Eligible sources are outlets indexed by GDELT whose domains map unambiguously to a publishing country. Ambiguous or unmapped domains are excluded. Official-domain overrides are transparent in the political configuration. The 2015 country catalogue is old and incomplete, so country coverage is a measurement limitation rather than a complete census of national media.</p></div>
            </div>
            <div className="method-callout caution">
              <CircleAlert size={17} />
              <p><strong>Confirmed provider gap.</strong> GDELT reported multiple infrastructure outages in June 2025. Direct coverage checks show a partial collapse on 14 June and no usable Web NGrams coverage through 1 July, with normal volumes returning on 2 July. The Atlas therefore excludes 14 June–1 July 2025 as missing data, removes previously stored zero scaffolds, and marks any event window crossing those dates incomplete.</p>
            </div>
            <details className="technical-details">
              <summary>Technical query safeguards <ChevronRight size={14} /></summary>
              <ul><li>Every job receives a dry run, explicit billing project and per-window byte cap.</li><li>Job estimates, completed byte statistics, batched topic IDs and phrase metadata are retained.</li><li>The affordable anchor strategy can miss uppercase and punctuation-adjacent forms; this requires sensitivity testing.</li><li>No article bodies are downloaded by the frontend export.</li></ul>
            </details>
          </section>

          <section className="protocol-section" id="events">
            <header><span>05</span><div><small>Independent treatment</small><h2>Weather-event definitions</h2></div></header>
            <p className="protocol-lede">The event catalogue comes from GDACS, a UN–European Commission cooperation framework for major sudden-onset disasters. The MVP includes event-level wildfires and floods.</p>
            <div className="hazard-method-grid">
              <article><Flame size={18} /><strong>Wildfire</strong><p>A named GDACS wildfire event. It is not an individual satellite hotspot and does not imply a burned-area estimate.</p></article>
              <article><CloudRain size={18} /><strong>Flood</strong><p>A GDACS flood event assembled from authoritative institutions, media and scientific sources under provider impact rules.</p></article>
            </div>
            <dl className="definition-list">
              <div><dt>Event identity</dt><dd>Provider + hazard code + event ID. This remains stable when an upstream record is revised.</dd></div>
              <div><dt>Event dates</dt><dd>Provider start and end timestamps in UTC. Later provider modification dates replace the stored version.</dd></div>
              <div><dt>Affected countries</dt><dd>The provider’s country array. Multi-country events stay multi-country and are not reduced to the map point.</dd></div>
              <div><dt>Alert level</dt><dd>GDACS Green, Orange or Red assessment of likely humanitarian consequences. Its logic is hazard-specific and incorporates factors such as hazard, exposure and vulnerability; it is not a pure physical-intensity scale.</dd></div>
              <div><dt>Alert score</dt><dd>The provider’s numeric alert field retained alongside the colour. It supports ordering within the GDACS record but is not treated as a universal hazard magnitude.</dd></div>
              <div><dt>Severity</dt><dd>The hazard-specific value and unit supplied by GDACS. Flood severity and wildfire metrics do not share a common unit, so the MVP displays them but never pools them as equivalent.</dd></div>
            </dl>
          </section>

          <section className="protocol-section" id="geography">
            <header><span>06</span><div><small>Location rules</small><h2>Three geographies, four media scopes</h2></div></header>
            <p className="protocol-lede">The most important geographic distinction is between where an event happened and where a publishing outlet is based.</p>
            <div className="geography-diagram" aria-label="Relationship between provider-affected countries, event map point and publishing outlet country">
              <article><span className="geo-symbol event"><MapPin size={17} /></span><small>Provider geography</small><strong>Affected countries</strong><p>Used for affected-country and international media scopes.</p></article>
              <ArrowRight size={17} />
              <article><span className="geo-symbol map"><MapIcon size={17} /></span><small>Display geography</small><strong>Event map point</strong><p>Checked against Natural Earth country and first-order region polygons.</p></article>
              <span className="geo-divider">≠</span>
              <article><span className="geo-symbol outlet"><Globe2 size={17} /></span><small>Media geography</small><strong>Outlet source country</strong><p>Assigned from the article domain; not its subject or audience.</p></article>
            </div>
            <div className="scope-table" role="table" aria-label="Media scope definitions">
              <div role="row"><span role="columnheader">Scope</span><span role="columnheader">Included publishing outlets</span><span role="columnheader">Interpretation</span></div>
              <div role="row"><strong role="cell">Affected countries</strong><span role="cell">Outlet country is in the event’s affected-country array.</span><span role="cell">Domestic or affected-market response.</span></div>
              <div role="row"><strong role="cell">EU27</strong><span role="cell">Outlet country is one of the fixed 27 EU member states.</span><span role="cell">Aggregate European publishing response.</span></div>
              <div role="row"><strong role="cell">International</strong><span role="cell">Outlet country is not in the affected-country array.</span><span role="cell">External response, including EU outlets where applicable.</span></div>
              <div role="row"><strong role="cell">Global</strong><span role="cell">Every available mapped publishing market.</span><span role="cell">Total indexed response in the exported data.</span></div>
            </div>
            <p className="method-caption"><strong>Analysis Lab comparison groups.</strong> To prevent overlap between pooled geographic estimates, the Lab separates affected countries, other EU27 countries and the rest of the world. Global remains an all-market summary. Explore retains the broader EU27 and international scopes above for single-event inspection.</p>
            <p className="method-caption"><strong>Boundary note.</strong> Natural Earth provides a display and validation layer, not the event definition. Its default Admin-0 countries reflect de facto cartographic boundaries, which may differ from legal or political claims.</p>
          </section>

          <section className="protocol-section" id="measurement">
            <header><span>07</span><div><small>Daily outcomes</small><h2>Attention and political-attention measures</h2></div></header>
            <div className="measure-grid">
              <article><small>All coverage</small><strong>Distinct topic URLs per day</strong><div className="mini-formula">matched_count = unique matching URLs</div><p>One URL can count in both active topics, but only once within each topic and day.</p></article>
              <article><small>Political only</small><strong>Distinct political topic URLs per day</strong><div className="mini-formula">political_count = unique matched URLs with ≥1 signal</div><p>The graph toggle and before/after cards use the same selected measure.</p></article>
            </div>
            <ul className="method-rules">
              <li>The current frontend export reports URL counts. Overall country-news denominators are unavailable, but political share is calculated transparently as political URLs divided by matched topic URLs.</li>
              <li>Counts measure indexed publishing output, not readership, public opinion, article prominence or sentiment.</li>
              <li>Raw levels are not directly comparable between countries because outlet mapping and GDELT coverage differ.</li>
              <li>A successful observed zero is valid; an absent date fails completeness and is not replaced with zero.</li>
            </ul>
          </section>

          <section className="protocol-section" id="before-after">
            <header><span>08</span><div><small>Exploratory inference</small><h2>What the single- and multi-event studies estimate</h2></div></header>
            <p className="protocol-lede">Explore compares one selected event with its own pre-event period. Analysis Lab applies the same complete-day principle to 2025 events, then summarises event-level changes without allowing large media markets to dominate the result. Orange and Red alerts are the primary cohort; Green and all-alert filters are sensitivity views.</p>
            <div className="window-diagram" aria-label="Before and after event window">
              <div className="window-before"><span>7, 14 or 28 days</span><strong>Before mean</strong><small>Days ending immediately before the start</small></div>
              <div className="window-event"><span>Event duration</span><strong>Excluded</strong><small>Start through end date</small></div>
              <div className="window-after"><span>7, 14 or 28 days</span><strong>After mean</strong><small>Days beginning immediately after the end</small></div>
            </div>
            <p className="method-caption"><strong>Two Lab timings.</strong> Onset response begins on the event start date and captures the immediate reaction. Persistence begins after the event end date and asks whether attention remains elevated. Both use the selected 7-, 14- or 28-day pre-event baseline.</p>
            <div className="test-output-grid">
              <article><small>Event effect</small><strong>Post mean relative to its own baseline</strong><p>All and political volume use percentage change. Political share uses percentage-point change.</p></article>
              <article><small>Lab aggregation</small><strong>Median event response</strong><p>The middle event is the headline result; the interquartile range shows the middle half of event estimates.</p></article>
              <article><small>Single-event test</small><strong>One-sided permutation result</strong><p>Explore retains its complete-window permutation calculation as a drill-down, not as the pooled Lab estimator.</p></article>
            </div>
            <details className="technical-details">
              <summary>Exact test, simulation and eligibility <ChevronRight size={14} /></summary>
              <ul><li>Every day in both periods must be present; absent dates are never converted to zero.</li><li>The primary Lab cohort contains GDACS Orange and Red floods and wildfires beginning in 2025; Green and all-alert cohorts use the same estimator.</li><li>The default Lab result excludes another selected-cohort event affecting the same country during the analysis window; users may include overlaps as a sensitivity check.</li><li>Explore evaluates every label allocation when there are no more than 50,000 combinations and otherwise uses a deterministic 10,000-shuffle approximation.</li></ul>
            </details>
            <div className="method-definition-grid two">
              <article><small>Event activity panel</small><strong>Rolling event starts by affected geography</strong><p>Multi-country events count once in every affected country, while global and EU27 aggregates count each unique event once. The chart offers 7- and 28-day windows and can overlay two to five countries for one selected attention topic. Its default symmetric focus scale covers 98% of plotted attention anomalies, flags clipped extremes and retains a full-range option.</p></article>
              <article><small>Lead / lag panel</small><strong>Pearson correlation across −28 to +28 days</strong><p>Attention is expressed relative to its preceding 28-day baseline. Positive lag means attention follows event activity. Autocorrelation and common shocks make this exploratory, not causal.</p></article>
            </div>
            <div className="method-callout caution"><CircleAlert size={17} /><p><strong>Interpretation.</strong> These are unadjusted temporal associations, not causal estimates or confidence intervals. News cycles are autocorrelated; seasonality, weekday patterns and concurrent stories can confound comparisons. A confirmatory release should pre-register outcomes and add matched dates, untreated markets or interrupted time-series controls.</p></div>
          </section>

          <section className="protocol-section" id="coverage-breakdown-method">
            <header><span>09</span><div><small>Descriptive evidence</small><h2>What the coverage breakdown contains</h2></div></header>
            <p className="protocol-lede">The Coverage breakdown tab summarizes the same topic-country-day observations as the attention graph instead of presenting individual article links.</p>
            <div className="method-definition-grid two">
              <article><small>Included</small><strong>Timing, themes and markets</strong><p>Mean daily URL counts before, during and after the event; political signal totals; and the largest publishing-outlet countries in the selected scope.</p></article>
              <article><small>Counting boundary</small><strong>Topic–URL observations</strong><p>A URL matching both themes contributes once to each theme. Political component signals overlap, so neither set should be summed into a deduplicated article corpus.</p></article>
            </div>
          </section>

          <section className="protocol-section" id="decisions">
            <header><span>10</span><div><small>Audit trail</small><h2>Current decision register</h2></div></header>
            <div className="decision-table">
              <div><span>Decision</span><span>Reason</span><span>Status</span></div>
              <div><strong>Use GDACS as the event treatment</strong><p>Keeps event selection independent of news attention.</p><span className="status-chip active">In use</span></div>
              <div><strong>Limit the MVP to two topics</strong><p>Prioritises interpretable, auditable concepts before taxonomy expansion.</p><span className="status-chip active">In use</span></div>
              <div><strong>Count distinct URLs</strong><p>Prevents repeated phrases and duplicate NGram rows from inflating attention.</p><span className="status-chip active">In use</span></div>
              <div><strong>Treat political as a union</strong><p>Avoids double counting overlapping actor, action, party and official-source signals.</p><span className="status-chip active">In use</span></div>
              <div><strong>Use outlet country for media scope</strong><p>It is observable and reproducible; article audience geography is not.</p><span className="status-chip active">In use</span></div>
              <div><strong>Separate onset from persistence</strong><p>Distinguishes the immediate response from attention remaining after an event ends.</p><span className="status-chip active">In use</span></div>
              <div><strong>Use Orange and Red events as the primary cohort</strong><p>Prevents thousands of low-salience Green alerts from dominating pooled estimates.</p><span className="status-chip active">In use</span></div>
              <div><strong>Exclude same-country overlaps by default</strong><p>Reduces attribution of one event’s news response to another concurrent major event.</p><span className="status-chip active">In use</span></div>
              <div><strong>Apply a minimum-event threshold to country rankings</strong><p>The default is three eligible events; users can choose 1, 2, 3, 5 or 10 and sort by activity or response.</p><span className="status-chip active">In use</span></div>
              <div><strong>Do not impute missing days</strong><p>Prevents provider gaps from becoming false evidence of low attention.</p><span className="status-chip active">In use</span></div>
              <div><strong>Exclude the confirmed June 2025 GDELT outage</strong><p>Coverage failure is provider unavailability, not a collapse in real news attention.</p><span className="status-chip active">In use</span></div>
              <div><strong>Add normalized country shares</strong><p>Needed for stronger cross-market comparison when denominator coverage is validated.</p><span className="status-chip planned">Planned</span></div>
            </div>
          </section>

          <section className="protocol-section" id="limitations">
            <header><span>11</span><div><small>Research boundaries</small><h2>Limitations and validation priorities</h2></div></header>
            <div className="limits-grid">
              <div><strong>The MVP does not claim</strong><ul><li>that an event caused a change in coverage;</li><li>that URL count equals audience attention;</li><li>that outlet country equals article subject or audience;</li><li>that political classification captures stance or ideology;</li><li>that provider alert levels are comparable physical intensities;</li><li>that every listed article is about the selected event.</li></ul></div>
              <div><strong>Validation before external research use</strong><ol><li>Native-speaker review and precision/recall samples for every language.</li><li>Manual audit of political false positives and false negatives.</li><li>Refresh and quantify domain-to-country mapping coverage.</li><li>Validate event points and multi-country records against provider pages.</li><li>Pre-register hypotheses and correct for multiple comparisons.</li><li>Add denominators, matched controls and robustness specifications.</li></ol></div>
            </div>
            <div className="reproducibility-strip"><Database size={17} /><p><strong>Reproducibility record.</strong> Each research export should retain the retrieval date, package version, frozen topic, political and country configurations, run manifest, query metadata and underlying provider citations. Do not combine date ranges collected under different phrase dictionaries without checking their metadata.</p></div>
          </section>

          <section className="protocol-section" id="references">
            <header><span>12</span><div><small>Source documentation</small><h2>References and technical documentation</h2></div></header>
            <div className="reference-list">
              {references.map((reference) => (
                <a href={reference.href} target="_blank" rel="noreferrer" key={reference.number}>
                  <span>{reference.number}</span>
                  <div><strong>{reference.title}</strong><small>{reference.organisation}</small><p>{reference.note}</p></div>
                  <ExternalLink size={15} />
                </a>
              ))}
            </div>
          </section>
        </div>
      </section>
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
