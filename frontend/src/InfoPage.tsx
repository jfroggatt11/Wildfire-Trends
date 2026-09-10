import { useMemo } from 'react'
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  CalendarRange,
  Database,
  Flame,
  Globe2,
  Map as MapIcon,
  Microscope,
  Newspaper,
  RefreshCw,
  Satellite,
  Search,
  ShieldCheck,
  Sparkles,
  ThermometerSun,
  TrendingUp,
  Users,
} from 'lucide-react'
import type { EventStudyData } from './AnalysisLab'
import { formatDate } from './utils'
import './InfoPage.css'

type InfoDestination = 'explore' | 'lab' | 'data' | 'methods'

type InfoManifest = {
  generatedAt: string
  attention: { rowCount: number }
  articles: { count: number }
  events: { count: number }
  satellite?: { observationCount: number; geographyCount: number }
  geographyLabels: Record<string, string>
  dataSources: {
    id: string
    observedDayCount: number
    geographyCount: number
    supportedGeographyCount?: number
  }[]
}

const median = (values: number[]) => {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function pooledClimateResult(study: EventStudyData, windowDays = 14) {
  const values = study.effects
    .filter((effect) => effect.scope === 'affected' && effect.topicId === 'climate_change' &&
      effect.windowDays === windowDays && effect.timing === 'onset' && effect.complete && !effect.overlap &&
      effect.matchedPercentChange != null)
    .map((effect) => effect.matchedPercentChange as number)
  return { year: study.studyYear, value: median(values), count: values.length }
}

const formatPercent = (value: number | null) => value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`

export default function InfoPage({
  manifest,
  studies,
  onNavigate,
}: {
  manifest: InfoManifest
  studies: EventStudyData[]
  onNavigate: (destination: InfoDestination) => void
}) {
  const news = manifest.dataSources.find((source) => source.id === 'gdelt_ngrams')
  const studyResults = useMemo(() => studies.map((study) => pooledClimateResult(study)).sort((left, right) => left.year - right.year), [studies])
  const majorEvents = studies.reduce((total, study) => total + study.events.length, 0)
  const completeSpecifications = studies.reduce(
    (total, study) => total + study.effects.filter((effect) => effect.complete).length,
    0,
  )

  const viewCards = [
    { icon: MapIcon, title: 'Explore', destination: 'explore' as const, copy: 'Find individual floods and fires on the map, then inspect daily attention and the political and geographic coverage breakdown.' },
    { icon: Microscope, title: 'Event study', destination: 'lab' as const, copy: 'Pool comparable events, change the window and media scope, and see median responses, variation, and country patterns.' },
    { icon: Flame, title: 'Wildfire attention', destination: 'lab' as const, copy: 'Rank the fires that broke through and compare attention with GDACS-reported hectares and a severity benchmark.' },
    { icon: TrendingUp, title: 'Event activity', destination: 'lab' as const, copy: 'Compare rolling event starts with attention over time, including country panels and exploratory lead/lag relationships.' },
    { icon: CalendarRange, title: 'Attention timeline', destination: 'lab' as const, copy: 'Follow topics and publishing markets through time, with event, burned-area, and vegetation overlays.' },
    { icon: BookOpen, title: 'Data & methods', destination: 'methods' as const, copy: 'Check source coverage, definitions, analytical decisions, missingness rules, limitations, and the validation protocol.' },
  ]

  return (
    <main className="info-view">
      <section className="info-hero">
        <div className="info-hero-copy">
          <span className="eyebrow">Project overview · T&amp;E research preview</span>
          <h1>How news attention changes around extreme events.</h1>
          <p>Climate Attention Atlas connects an external catalogue of major events with daily news publishing to ask when climate and electric-vehicle attention rises, where it rises, and whether it lasts.</p>
          <div className="info-hero-actions">
            <button onClick={() => onNavigate('lab')}>Open the Analysis Lab <ArrowRight size={15} /></button>
            <button className="secondary" onClick={() => onNavigate('explore')}>Explore the map</button>
          </div>
        </div>
        <aside className="info-hero-note">
          <ShieldCheck size={21} />
          <div><strong>Exploratory, not causal</strong><p>The current evidence shows associations in indexed publishing. It does not yet prove that events caused attention to change.</p></div>
        </aside>
      </section>

      <section className="info-snapshot" aria-label="Current project snapshot">
        <div><strong>{(news?.supportedGeographyCount ?? news?.geographyCount)?.toLocaleString() ?? '—'}</strong><span>markets with mapping support</span></div>
        <div><strong>{news?.observedDayCount.toLocaleString() ?? '—'}</strong><span>observed news days</span></div>
        <div><strong>{manifest.attention.rowCount.toLocaleString()}</strong><span>topic-market rows</span></div>
        <div><strong>{majorEvents.toLocaleString()}</strong><span>major events studied</span></div>
        <div><strong>{completeSpecifications.toLocaleString()}</strong><span>complete specifications</span></div>
      </section>

      <div className="info-content">
        <section className="info-question-grid">
          <article className="info-statement">
            <span className="eyebrow">The purpose</span>
            <h2>Measure the attention response—not just the disaster.</h2>
            <p>The Atlas is designed to reveal whether major wildfires and floods coincide with more discussion of climate change, whether attention spills into electric-vehicle coverage, and whether domestic, European, and global publishing markets react differently.</p>
          </article>
          <article className="info-method-card">
            <span className="eyebrow">Method in one minute</span>
            <ol>
              <li><span>1</span><p><strong>Use an external event catalogue.</strong> GDACS defines events separately from our GDELT outcome; flood reporting can itself include media sources.</p></li>
              <li><span>2</span><p><strong>Count distinct URLs.</strong> GDELT matches climate and EV phrases by UTC day and publishing-outlet country.</p></li>
              <li><span>3</span><p><strong>Compare complete windows.</strong> Event onset or post-event attention is compared with the preceding 7, 14, or 28 days.</p></li>
              <li><span>4</span><p><strong>Keep uncertainty visible.</strong> Missing dates, provider outages, and overlapping events are never silently treated as clean observations.</p></li>
            </ol>
          </article>
        </section>

        <section className="info-section" aria-labelledby="info-sources-heading">
          <header className="info-section-heading"><div><span className="eyebrow">Evidence base</span><h2 id="info-sources-heading">Event and news records, joined by place and time.</h2></div><p>Using an external catalogue reduces circular selection from our news outcome, but does not remove reporting or humanitarian-impact selection.</p></header>
          <div className="info-source-flow">
            <article><span><Newspaper size={19} /></span><small>Attention</small><strong>GDELT Web NGrams</strong><p>Distinct topic-matching news URLs, attributed to the publishing outlet's country.</p></article>
            <ArrowRight className="info-flow-arrow" size={17} />
            <article><span><Globe2 size={19} /></span><small>Events</small><strong>GDACS</strong><p>Named wildfires and floods with dates, affected countries, alert tiers, and severity.</p></article>
            <ArrowRight className="info-flow-arrow" size={17} />
            <article><span><Satellite size={19} /></span><small>Physical context</small><strong>NASA MODIS &amp; FIRMS</strong><p>Burned area, vegetation anomalies, wildfire detections, and fire radiative power.</p></article>
            <ArrowRight className="info-flow-arrow" size={17} />
            <article><span><BarChart3 size={19} /></span><small>Analysis</small><strong>Event windows</strong><p>Before-and-after comparisons across affected, EU, international, and global media.</p></article>
          </div>
          <p className="info-source-note"><Database size={14} /> Natural Earth boundaries support reproducible country assignment and map labels. Google Trends is currently experimental and is planned as a core comparison source.</p>
        </section>

        <section className="info-section" aria-labelledby="info-views-heading">
          <header className="info-section-heading"><div><span className="eyebrow">Inside the Atlas</span><h2 id="info-views-heading">Six ways into the evidence.</h2></div><p>Move from a single event to pooled patterns, long-run timelines, and the full methodological audit trail.</p></header>
          <div className="info-view-grid">
            {viewCards.map(({ icon: Icon, title, copy, destination }) => (
              <button key={title} onClick={() => onNavigate(destination)}>
                <span><Icon size={18} /></span><div><strong>{title}</strong><p>{copy}</p></div><ArrowRight size={14} />
              </button>
            ))}
          </div>
        </section>

        <section className="info-section info-findings" aria-labelledby="info-findings-heading">
          <header className="info-section-heading"><div><span className="eyebrow">How successful is it?</span><h2 id="info-findings-heading">A working platform with promising—but mixed—signals.</h2></div><p>The data pipeline, interactive explorer, multi-event analysis, satellite comparisons, and reproducibility controls are implemented end to end.</p></header>
          <div className="info-result-grid">
            {studyResults.map((result) => (
              <article key={result.year}><small>{result.year} major events</small><strong>{formatPercent(result.value)}</strong><p>Median affected-market climate attention at onset · 14-day window · {result.count} non-overlapping events</p></article>
            ))}
            <article className="info-result-context"><small>Global pattern</small><strong>Mixed</strong><p>Global climate responses were smaller, while EV attention did not show a consistent increase.</p></article>
          </div>

          <div className="info-country-panel">
            <div className="info-country-copy"><span className="eyebrow">Sensitivity to the window</span><h3>Does the pattern hold at 7, 14 and 28 days?</h3><p>Each estimate uses eligible major events with complete affected-market climate counts and excludes overlaps with Orange/Red events. Changing the window also changes the cohort.</p></div>
            <div className="info-country-list">{studies.map((study) => <article key={study.studyYear}>
              <strong>{study.studyYear}</strong>
              {[7, 14, 28].map((window) => {
                const result = pooledClimateResult(study, window)
                return <p key={window}>{window} days: {formatPercent(result.value)} · {result.count} events</p>
              })}
            </article>)}</div>
          </div>
          <div className="info-caution"><ShieldCheck size={17} /><p><strong>Interpret carefully.</strong> These are small, changing samples and 2026 is partial. Differences across years or windows are not causal effects or an estimated trend. Low baseline URL counts can produce large percentage changes.</p></div>

        </section>

        <section className="info-section" aria-labelledby="info-roadmap-heading">
          <header className="info-section-heading"><div><span className="eyebrow">Future plans</span><h2 id="info-roadmap-heading">From exploratory atlas to attention intelligence.</h2></div><p>The next phase expands the history, attention sources, event catalogue, and strength of inference.</p></header>
          <div className="info-roadmap-grid">
            <article><span><RefreshCw size={18} /></span><small>01 · Build the record</small><strong>More history, automatic refreshes</strong><p>Extend the dataset backwards, then refresh news, search, event, and physical sources daily, weekly, or monthly with completeness monitoring.</p></article>
            <article><span><Search size={18} /></span><small>02 · Widen attention</small><strong>Searches and public posts</strong><p>Add Google Trends for what people search, plus Bluesky and—where access permits—X for what people post. Defined groups could include MEPs and politicians relevant to existing T&amp;E work.</p></article>
            <article><span><ThermometerSun size={18} /></span><small>03 · Widen events</small><strong>Weather anomalies and public moments</strong><p>Add temperature departures from local norms, more extreme-weather types, and non-weather events such as COP meetings, EV launches, elections, and policy announcements.</p></article>
            <article><span><Sparkles size={18} /></span><small>04 · Learn what matters</small><strong>New hypotheses and prediction</strong><p>Test timing, spillover, geography, severity, and political-attention hypotheses; then evaluate models out of sample to identify which event features best predict attention.</p></article>
          </div>
        </section>

        <section className="info-validation">
          <div><span><Users size={18} /></span><h2>Validation remains part of the product.</h2></div>
          <p>Priorities include native-speaker and precision/recall reviews, political-classifier audits, stronger outlet-country mapping and news denominators, cross-source event checks, pre-registered confirmatory hypotheses, matched dates or untreated markets, and correction for multiple testing.</p>
          <button onClick={() => onNavigate('methods')}>Read the full methods <ArrowRight size={14} /></button>
        </section>

        <footer className="info-footer">
          <span>Snapshot generated {formatDate(manifest.generatedAt)}</span>
          <p>Climate Attention Atlas · Internal research MVP</p>
        </footer>
      </div>
    </main>
  )
}
