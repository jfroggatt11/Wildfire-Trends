import { windowSensitivity } from './analysisEvidence'
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
          <p>Climate Attention Atlas connects independently recorded events with daily news publishing to explore when attention rises, where it rises, and whether it lasts. Climate change and electric vehicles are the prototype’s test topics, using initial search phrases that T&amp;E can refine and expand.</p>
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
            <h2>Test the approach, then expand the questions.</h2>
            <p>Wildfires and floods provide the first event cases; climate change and electric vehicles provide the first topic tests. The current searches demonstrate how domestic, European, and global publishing markets respond. Their phrases are initial research definitions awaiting validation. T&amp;E can help choose the next topics, markets, and local terminology.</p>
          </article>
          <article className="info-method-card">
            <span className="eyebrow">Method in one minute</span>
            <ol>
              <li><span>1</span><p><strong>Use an external event catalogue.</strong> GDACS defines events separately from our GDELT outcome; flood reporting can itself include media sources.</p></li>
              <li><span>2</span><p><strong>Count distinct URLs.</strong> Match configured climate and EV test phrases in original-language text, counting each URL once per topic and UTC day, by publishing-outlet country.</p></li>
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
          <p className="info-source-note"><Database size={14} /> Natural Earth boundaries support reproducible country assignment and map labels. An unofficial Google Trends collector exists; official-API integration and validated search comparisons are planned.</p>
        </section>

        <section className="info-section" aria-labelledby="info-language-heading">
          <header className="info-section-heading"><div><span className="eyebrow">Test phrases and language</span><h2 id="info-language-heading">How the searches work—and how we will verify them.</h2></div><p>Translation choices affect which coverage is found. A working pipeline does not establish that the phrases accurately capture each topic.</p></header>
          <div className="info-question-grid">
            <article className="info-method-card info-language-copy">
              <h3>Match local phrases in the original text</h3>
              <p>Web NGrams uses preconfigured translations and local equivalents: for example, “climate change”, “changement climatique”, and “Klimawandel”. It does not translate each article during collection. Synonyms and translations count as alternatives within a topic, so multiple matches do not inflate its URL count.</p>
              <p>The seed lists cover ten languages. Non-English entries remain drafts: native speakers need to check local usage, plurals, ambiguity, and conceptual equivalence. Chinese and Japanese use character sequences. Unlisted wording can be missed.</p>
              <p>The alternative GDELT DOC API searches English terms over machine-translated coverage. That method needs separate checks; it may find a different set of articles.</p>
            </article>
            <article className="info-method-card">
              <h3>Verification planned with native speakers</h3>
              <ol>
                <li><span>1</span><p><strong>Review the phrases.</strong> Agree what each topic includes and check the local terminology in each priority language and market.</p></li>
                <li><span>2</span><p><strong>Check precision and recall.</strong> Precision asks how many matches are relevant. Recall asks how much relevant coverage is found, using an independent article sample that also includes unmatched coverage.</p></li>
                <li><span>3</span><p><strong>Review, revise, and retest.</strong> Check political labels separately, resolve reviewer disagreements, and test revised lists on a separate sample. Report accuracy and uncertainty by topic and language.</p></li>
              </ol>
              <p className="info-verification-note">This validation is still planned. Translation-status labels alone do not establish classifier accuracy.</p>
            </article>
          </div>
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
            <div className="info-country-copy"><span className="eyebrow">Sensitivity to the window</span><h3>Does the pattern hold at 7, 14 and 28 days?</h3><p>Affected-market climate counts at onset, excluding Orange/Red overlaps. Compare each window’s eligible events with the same events eligible at all three windows.</p></div>
            <div className="info-country-list">{studies.map((study) => <article key={study.studyYear}>
              <strong>{study.studyYear}</strong>
              {windowSensitivity(study.effects.filter((effect) => effect.scope === 'affected' && effect.topicId === 'climate_change' && effect.timing === 'onset'), [7, 14, 28], 'matched').map((row) => <p key={row.windowDays}><strong>{row.windowDays} days</strong> · all eligible: {formatPercent(row.median)} (n={row.count})<br />Same events: {formatPercent(row.fixedMedian)} (n={row.fixedCount})</p>)}
            </article>)}</div>
          </div>
          <div className="info-caution"><ShieldCheck size={17} /><p><strong>Interpret carefully.</strong> These are small, changing samples and 2026 is partial. Differences across years or windows are not causal effects or an estimated trend. Low baseline URL counts can produce large percentage changes.</p></div>

        </section>

        <section className="info-section" aria-labelledby="info-roadmap-heading">
          <header className="info-section-heading"><div><span className="eyebrow">Future plans</span><h2 id="info-roadmap-heading">More sources, more events, stronger comparisons.</h2></div><p>These are proposed extensions. The next phase expands the historical record and the questions T&amp;E can investigate.</p></header>
          <div className="info-roadmap-grid">
            <article><span><RefreshCw size={18} /></span><small>01 · Build the record</small><strong>More history, reviewed topics, regular updates</strong><p>Extend the history to cover more events and strengthen comparisons. Agree T&amp;E’s topic definitions and local phrases, then refresh news, search, event, and physical sources daily, weekly, or monthly, with completeness and language-coverage checks and failed-run alerts.</p></article>
            <article><span><Search size={18} /></span><small>02 · Add search interest</small><strong>Google Trends: access is the next step</strong><p>An unofficial collector exists, but official-API collection is not integrated. As of September 2026, the developer’s individual application has been unanswered for around a month. The proposed next step is an application under T&amp;E’s name with a concrete research use case.</p><p>Google requires <a href="https://developers.google.com/search/apis/trends" target="_blank" rel="noreferrer">API alpha access</a>. Integration is expected to be manageable once granted, followed by a pilot checking collection limits, query choices, scaling, and completeness.</p></article>
            <article><span><Users size={18} /></span><small>03 · Add public posting</small><strong>Follow public and political discussion</strong><p>Add Bluesky and, where access permits, X to measure what people post alongside news publishing and searches. Defined groups could include MEPs and other politicians relevant to T&amp;E’s political and communications work.</p></article>
            <article><span><ThermometerSun size={18} /></span><small>04 · Extend weather coverage</small><strong>Everyday anomalies and more extremes</strong><p>Add temperature departures from local historical norms and more extreme-weather types. Preserve each source’s severity definitions so unlike hazards are not treated as equivalent.</p></article>
            <article><span><CalendarRange size={18} /></span><small>05 · Track public events</small><strong>COPs, launches, elections, and policy</strong><p>Build a dated register with a source, event type, relevant countries, and start and end dates. Keep announcements and implementation dates distinct, then compare attention before, during, and after events—including anticipation of scheduled events.</p></article>
            <article><span><Globe2 size={18} /></span><small>06 · Track geopolitics and energy</small><strong>Hormuz disruptions and oil-price changes</strong><p>Add separate trackers for Strait of Hormuz disruptions, conflicts, sanctions, and supply shocks, alongside oil-price series. Test whether a predefined crossing of US$100 per barrel in a specified benchmark precedes more EV news, searches, or posts, where, and for how long.</p><p>Define the price series and crossing rule in advance, group repeated crossings into episodes, and account for concurrent events. This is a proposed question, not an observed finding.</p></article>
            <article><span><TrendingUp size={18} /></span><small>07 · Test cross-country sequences</small><strong>Does attention in A precede attention in B?</strong><p>Compare predefined country pairs and time lags across news, searches, and posts. Account for shared events, seasonality, and syndicated coverage before interpreting a sequence as discussion spreading between countries. Temporal ordering alone does not establish causation.</p></article>
            <article><span><Sparkles size={18} /></span><small>08 · Evaluate prediction</small><strong>Learn which event features predict attention</strong><p>Test timing, geography, severity, and political-attention hypotheses. Once the historical record and validation are strong enough, evaluate predictions on held-out periods and use interpretable feature-importance methods to identify which event characteristics matter.</p></article>
          </div>
        </section>

        <section className="info-validation">
          <div><span><Users size={18} /></span><h2>Validation remains part of the product.</h2></div>
          <p>Alongside the language reviews above, audit outlet-country attribution and political classifiers, add validated news denominators, and compare event sources. Pre-register confirmatory hypotheses, use matched dates or untreated markets where credible, and correct for multiple testing. A global oil shock may leave no truly untreated country.</p>
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
