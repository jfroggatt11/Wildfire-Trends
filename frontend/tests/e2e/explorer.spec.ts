import { expect, test, type Page } from '@playwright/test'

function collectClientErrors(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.stack || error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  return errors
}

async function openExplorer(page: Page) {
  await page.goto('/', { waitUntil: 'networkidle' })
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await expect(page.locator('.atlas-marker').first()).toBeVisible()
}

test('all media scopes preserve events and open their detail panel', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const visibleCount = page.locator('.map-stat strong')
  await expect(visibleCount).toHaveText('8,942')

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-section select').selectOption(scope)
    await expect(visibleCount).toHaveText('8,942')
    await page.locator('.watchlist > button').first().click()
    await expect(page.locator('.event-drawer')).toBeVisible()
    await expect(page.locator('.event-error')).toHaveCount(0)
    await page.locator('.drawer-header .icon-button').click()
  }

  expect(errors).toEqual([])
})

test('January plus Global opens aggregate attention across every media scope', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.locator('input[type="date"]').nth(1).fill('2025-01-31')
  await expect(page.locator('.map-stat strong')).toHaveText('299')
  await expect(page.locator('.watchlist > button').first()).toContainText('Wildfire in United States')

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-section select').selectOption(scope)
    await page.locator('.watchlist > button').first().click()
    await expect(page.locator('.event-error')).toHaveCount(0)
    await expect(page.locator('.event-drawer')).toContainText('Wildfire in United States')
    await page.locator('.drawer-header .icon-button').click()
  }

  await page.locator('.scope-section select').selectOption('global')
  await page.locator('.watchlist > button').first().click()

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-select select').selectOption(scope)
    await expect(page.locator('.event-error')).toHaveCount(0)
  }

  await expect(page.getByRole('tab')).toHaveCount(2)
  await expect(page.getByRole('tab', { name: 'Attention' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Coverage breakdown' })).toHaveCount(1)
  for (const removedTab of ['Articles', 'Briefing', 'Geography', 'Methods']) {
    await expect(page.getByRole('tab', { name: removedTab })).toHaveCount(0)
  }
  await expect(page.getByRole('heading', { name: /Topic coverage around the event/ })).toBeVisible()

  expect(errors).toEqual([])
})

test('attention toggle and before-after analysis share the selected measure', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AWF%3A1023505', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.event-drawer')).toBeVisible()
  await page.locator('.scope-select select').selectOption('global')

  const cards = page.locator('.before-after-card')
  await expect(cards).toHaveCount(2)
  await expect(page.getByRole('status')).toHaveCount(0, { timeout: 45_000 })
  await expect(page.locator('.before-after-card[data-test-status="unavailable"]')).toHaveCount(0)
  await expect(cards.first()).toContainText('URLs/day')
  await expect(cards.first()).toContainText('One-sided p =')
  await expect(page.locator('.recharts-reference-line')).toHaveCount(2)
  await expect(page.locator('.chart-wrap')).toContainText('Starts')
  await expect(page.locator('.chart-wrap')).toContainText('Ends')
  await expect(page.locator('.chart-wrap')).not.toContainText('Event duration')
  const allArticleResult = await cards.first().textContent()

  await page.getByRole('button', { name: 'Political only' }).click()
  await expect(page.getByRole('button', { name: 'Political only' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('heading', { name: /Political topic coverage around the event/ })).toBeVisible()
  await expect.poll(async () => cards.first().textContent()).not.toBe(allArticleResult)

  await page.getByLabel('Comparison window').selectOption('28')
  await expect(page.locator('.before-after-card[data-test-status="unavailable"]')).toHaveCount(0)
  await expect(cards.first()).toContainText('URLs/day')
  expect(errors).toEqual([])
})

test('coverage breakdown replaces article links with aggregate timing, political and market views', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AWF%3A1023505', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.event-drawer')).toBeVisible()
  await page.locator('.scope-select select').selectOption('affected')
  await expect(page.getByRole('status')).toHaveCount(0, { timeout: 45_000 })
  await page.getByRole('tab', { name: 'Coverage breakdown' }).click()

  await expect(page.getByRole('heading', { name: 'What changed, and where?' })).toBeVisible()
  await expect(page.getByRole('status')).toHaveCount(0, { timeout: 45_000 })
  await expect(page.locator('.coverage-summary strong').first()).not.toHaveText('0')
  await expect(page.getByRole('table', { name: 'Average daily coverage before, during and after the event' })).toBeVisible()
  await expect(page.locator('.phase-table > div[data-topic]')).toHaveCount(2)
  await expect(page.locator('.political-signal-summary > div')).toHaveCount(4)
  await expect(page.locator('.market-ranking button').first()).toBeVisible()
  await expect(page.locator('.article-list')).toHaveCount(0)
  await expect(page.locator('.drawer-content a[href^="http"]')).toHaveCount(0)

  const market = page.locator('.market-ranking button').first()
  const marketName = (await market.locator('span').textContent()) || ''
  await market.click()
  await expect(page.locator('.coverage-toolbar select').nth(1)).not.toHaveValue('all')
  await expect(page.locator('.coverage-breakdown')).toContainText(marketName)
  expect(errors).toEqual([])
})

test('trackpad-style zoom stays inside the map and clusters resolve at source coordinates', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const map = page.locator('.atlas-svg-map')
  const svg = map.locator(':scope > svg')
  await expect(svg).toHaveAttribute('data-zoom', '1.000')

  const prevented = await map.evaluate((element) => !element.dispatchEvent(new WheelEvent('wheel', {
    bubbles: true,
    cancelable: true,
    clientX: element.getBoundingClientRect().left + element.clientWidth / 2,
    clientY: element.getBoundingClientRect().top + element.clientHeight / 2,
    deltaY: -160,
    ctrlKey: true,
  })))
  expect(prevented).toBe(true)
  await expect.poll(async () => Number(await svg.getAttribute('data-zoom'))).toBeGreaterThan(1)

  await page.getByRole('button', { name: 'Reset world view' }).click()
  // SVG paints later markers on top; target the topmost visible cluster just as a user would.
  const cluster = page.locator('.atlas-marker.cluster').last()
  const clusterCount = Number(await cluster.getAttribute('data-count'))
  const clusterPosition = await cluster.getAttribute('transform')
  const markerCountBefore = await page.locator('.atlas-marker').count()
  expect(clusterCount).toBeGreaterThan(1)
  await cluster.click()
  await expect(map).toHaveAttribute('data-camera-animating', 'true')
  await expect(map).toHaveAttribute('data-camera-animating', 'false')
  await expect.poll(async () => Number(await svg.getAttribute('data-zoom'))).toBeGreaterThanOrEqual(7)
  await expect.poll(async () => page.locator('.atlas-marker').count()).toBeGreaterThan(markerCountBefore)
  await expect(page.locator('.atlas-marker[data-expanded="true"]')).toHaveCount(0)
  const positionsAfterSplit = await page.locator('.atlas-marker').evaluateAll((markers) => markers.map((marker) => marker.getAttribute('transform')))
  expect(positionsAfterSplit).toContain(clusterPosition)

  const positionsBeforeZoomOut = await page.locator('.atlas-marker.event').evaluateAll((markers) => Object.fromEntries(markers.map((marker) => [
    marker.getAttribute('data-event-id'),
    marker.getAttribute('transform'),
  ])))
  const zoomOut = map.getByRole('button', { name: 'Zoom out', exact: true })
  await zoomOut.evaluate((button: HTMLButtonElement) => button.click())
  const positionsAfterZoomOut = await page.locator('.atlas-marker.event').evaluateAll((markers) => Object.fromEntries(markers.map((marker) => [
    marker.getAttribute('data-event-id'),
    marker.getAttribute('transform'),
  ])))
  const persistentIds = Object.keys(positionsBeforeZoomOut).filter((id) => id in positionsAfterZoomOut)
  expect(persistentIds.length).toBeGreaterThan(0)
  for (const id of persistentIds) expect(positionsAfterZoomOut[id]).toBe(positionsBeforeZoomOut[id])
  expect(errors).toEqual([])
})

test('event drawer keeps the corrected map-point label without a geography tab', async ({ page }) => {
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AFL%3A1103661', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.event-drawer')).toBeVisible()
  await expect(page.locator('.drawer-header h2')).toHaveText('Flood in United Kingdom')
  await expect(page.locator('.event-meta')).toContainText('Map point: Cornwall, United Kingdom')
  await expect(page.locator('.event-meta')).toContainText('50.42°N, 4.75°W')
  await expect(page.locator('.event-meta')).toContainText('Affected: Ireland, United Kingdom')
  await expect(page.getByRole('tab')).toHaveCount(2)
  await expect(page.getByRole('tab', { name: 'Geography' })).toHaveCount(0)
  expect(errors).toEqual([])
})

test('selected Cornwall event stays pinned to its source coordinate while zooming', async ({ page }) => {
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AFL%3A1103661', { waitUntil: 'networkidle' })
  await expect(page.locator('.event-drawer')).toBeVisible()

  const map = page.locator('.atlas-svg-map')
  const marker = page.locator('.atlas-marker.event[data-event-id="gdacs:FL:1103661"]')
  await expect(marker).toBeVisible()
  await expect(marker.locator('.selected-halo')).toBeVisible()
  const sourcePosition = await marker.getAttribute('transform')

  const zoomIn = map.getByRole('button', { name: 'Zoom in', exact: true })
  // The open analysis drawer intentionally covers the right-side controls at
  // desktop widths, so invoke the control as a keyboard activation would.
  await zoomIn.evaluate((button: HTMLButtonElement) => button.click())
  await zoomIn.evaluate((button: HTMLButtonElement) => button.click())
  await expect.poll(async () => Number(await map.locator(':scope > svg').getAttribute('data-zoom'))).toBeGreaterThan(1.5)
  await expect(marker).toHaveAttribute('transform', sourcePosition || '')
  await expect(marker).toHaveAttribute('data-count', '1')
  expect(errors).toEqual([])
})

test('data summary reports only MVP sources and their stored coverage dates', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.getByRole('button', { name: 'Data', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'What the Atlas currently covers.' })).toBeVisible()
  await expect(page.locator('.source-card')).toHaveCount(2)
  await expect(page.locator('.source-timeline-row')).toHaveCount(2)
  await expect(page.locator('.source-card[data-source="gdacs"]')).toContainText('1 Jan 2025 — 26 Aug 2026')
  await expect(page.locator('.source-card[data-source="gdelt_ngrams"]')).toContainText('31 Jul 2026')
  await expect(page.locator('.source-card[data-source="gdelt_ngrams"]')).toContainText('stored observation dates')
  await expect(page.locator('.source-card[data-source="gdelt_ngrams"] .source-coverage-ranges span')).toHaveCount(2)
  await expect(page.locator('.source-card[data-source="gdelt_articles"]')).toHaveCount(0)
  await expect(page.locator('.source-timeline-row[data-source="gdelt_ngrams"] .source-timeline-track span')).toHaveCount(2)
  await expect(page.getByText('Google Trends comparison series')).toHaveCount(0)
  await expect(page.getByText('NASA FIRMS wildfire detections')).toHaveCount(0)
  await expect(page.getByText('GDELT DOC 2.0 topic timelines')).toHaveCount(0)
  expect((await page.locator('.source-card dd').allTextContents()).some((value) => value.includes('Open'))).toBe(false)

  await page.getByRole('button', { name: 'Explore', exact: true }).click()
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  expect(errors).toEqual([])
})

test('analysis lab runs the major-event study for climate and electric vehicles', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.getByRole('button', { name: 'Analysis Lab', exact: true }).click()
  await page.getByLabel('Study year').selectOption('2025')

  await expect(page.getByRole('heading', { name: 'Compare attention and event activity.' })).toBeVisible()
  await expect(page.locator('.cohort-flow')).toContainText('40')
  await expect(page.locator('.cohort-flow')).toContainText('29')
  await expect(page.locator('.cohort-flow')).toContainText('19')
  await expect(page.locator('.topic-result-grid > article')).toHaveCount(2)
  await expect(page.locator('.topic-result-grid [data-topic="electric_vehicles"]')).toContainText('Electric vehicles')
  await expect(page.locator('.study-timeline')).toBeVisible()
  await expect(page.locator('.ranked-event-table > button').first()).toBeVisible()
  await expect(page.getByLabel('Minimum eligible events')).toHaveValue('3')
  await expect(page.getByLabel('Sort countries by')).toHaveValue('events')
  await expect(page.locator('.country-ranking-empty')).toContainText('No country has at least 3 eligible events')
  await page.getByLabel('Minimum eligible events').selectOption('2')
  await expect(page.locator('.country-comparison .country-row')).toHaveCount(2)
  const activitySortedCounts = (await page.locator('.country-comparison .country-row small').allTextContents()).map((value) => Number.parseInt(value, 10))
  expect(activitySortedCounts.every((count) => count >= 2)).toBe(true)
  expect(activitySortedCounts).toEqual([...activitySortedCounts].sort((left, right) => right - left))
  await page.getByLabel('Sort countries by').selectOption('response')
  await expect(page.locator('.country-comparison h3')).toHaveText('Largest country responses')

  await page.getByRole('button', { name: /H2 EV spillover/ }).click()
  await expect(page.locator('.pooled-result')).toContainText('Electric vehicles · Article attention')

  await page.getByLabel('Chart measure').selectOption('political_share')
  await expect(page.locator('.pooled-result')).toContainText('Politicisation')
  await expect(page.locator('.headline-result-grid article').first()).toContainText('pp')

  await page.getByLabel('Exclude same-country overlapping events').uncheck()
  await expect(page.locator('.cohort-flow')).toContainText('29')

  await page.locator('.ranked-event-table > button').first().click()
  await expect(page.locator('.event-drawer')).toBeVisible()
  await expect(page.locator('.event-error')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('analysis lab exposes the all-alert activity and lag views', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.getByRole('button', { name: 'Analysis Lab', exact: true }).click()
  await page.getByLabel('Study year').selectOption('2025')

  await page.getByLabel('Event alerts').selectOption('green')
  await expect(page.locator('.analysis-loading')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.locator('.cohort-flow strong').first()).not.toHaveText('0')

  await page.getByRole('tab', { name: 'Event activity' }).click()

  await expect(page.getByRole('heading', { name: 'Configure activity' })).toBeVisible()
  await expect(page.locator('.activity-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Do attention anomalies move with event load?' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'When is event activity most associated with attention?' })).toBeVisible()
  await expect(page.locator('.activity-kpis > article')).toHaveCount(4)
  await expect(page.locator('.activity-chart')).toBeVisible()
  await expect(page.locator('.chart-scale-note')).toContainText('symmetric 98% range')
  await expect(page.locator('.outage-note')).toContainText('14 June through 1 July 2025')
  await expect(page.locator('.lag-chart')).toBeVisible()

  await page.getByLabel('Place view').selectOption('compare')
  await expect(page.locator('.activity-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.locator('.comparison-country-list > span')).toHaveCount(3)
  await page.getByLabel('Add country').selectOption('italy')
  await expect(page.locator('.activity-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.locator('.comparison-country-list > span')).toHaveCount(4)
  const comparisonLegend = page.locator('.activity-chart .recharts-legend-item-text')
  for (const country of ['United Kingdom', 'France', 'Germany', 'Italy']) {
    await expect(comparisonLegend.filter({ hasText: country }).first()).toBeVisible()
  }
  await expect(comparisonLegend).toHaveCount(4)
  const lagTicks = (await page.locator('.lag-chart .recharts-yAxis .recharts-cartesian-axis-tick-value').allTextContents()).map(Number).filter(Number.isFinite)
  expect(Math.max(...lagTicks.map(Math.abs))).toBeLessThan(1)

  await page.getByLabel('Attention scale').selectOption('full')
  await expect(page.locator('.chart-scale-note')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('analysis lab charts daily attention with selectable event markers', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.getByRole('button', { name: 'Analysis Lab', exact: true }).click()
  await page.getByLabel('Study year').selectOption('2025')
  await page.getByRole('tab', { name: 'Attention timeline' }).click()

  await expect(page.getByRole('heading', { name: 'Configure timeline' })).toBeVisible()
  await expect(page.locator('.activity-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Climate change in World' })).toBeVisible()
  await expect(page.locator('.timeline-chart')).toBeVisible()
  const eventLines = page.locator('.timeline-chart .recharts-reference-line-line')
  expect(await eventLines.count()).toBeGreaterThan(0)
  await expect(eventLines.first()).toHaveAttribute('stroke-dasharray', '3 4')
  await expect(page.locator('.timeline-total')).toContainText('average matching articles/day')
  await expect(page.locator('.timeline-key')).toContainText('Green alert')
  await expect(page.locator('.timeline-key')).toContainText('unavailable days excluded')

  const majorEventCount = Number.parseInt((await page.locator('.timeline-total small').textContent())?.match(/· ([\d,]+) events/)?.[1].replaceAll(',', '') ?? '0', 10)
  await page.getByLabel('Event alerts').selectOption('all')
  await expect.poll(async () => Number.parseInt((await page.locator('.timeline-total small').textContent())?.match(/· ([\d,]+) events/)?.[1].replaceAll(',', '') ?? '0', 10)).toBeGreaterThan(majorEventCount)

  await page.getByLabel('Geography').selectOption('group')
  await expect(page.locator('.activity-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByLabel('Timeline country group').locator('> span')).toHaveCount(3)
  expect(await page.getByLabel('Add timeline country').locator('option').count()).toBeGreaterThan(150)
  await page.getByLabel('Add timeline country').selectOption('italy')
  await expect(page.locator('.activity-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByLabel('Timeline country group').locator('> span')).toHaveCount(4)
  await expect(page.getByRole('heading', { name: 'Climate change in 4-country group' })).toBeVisible()

  await page.getByLabel('Attention topic').selectOption('electric_vehicles')
  await expect(page.locator('.activity-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Electric vehicles in 4-country group' })).toBeVisible()
  await page.getByLabel('Attention measure').selectOption('political')
  await expect(page.locator('.timeline-total')).toContainText('political articles')
  expect(errors).toEqual([])
})

test('methods page documents the current research protocol and definitions', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.getByRole('button', { name: 'Methods', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'How the Atlas turns events into evidence.' })).toBeVisible()
  await expect(page.locator('.protocol-section')).toHaveCount(12)
  await expect(page.locator('.topic-method-card')).toHaveCount(2)
  await expect(page.locator('.topic-method-card[data-topic="climate_change"]')).toContainText('Climate change')
  await expect(page.locator('.candidate-topics')).toContainText('Clean energy')
  await expect(page.locator('.candidate-topics')).toContainText('Held back')

  const climateDictionary = page.locator('.topic-method-card[data-topic="climate_change"] details')
  await climateDictionary.locator('summary').click()
  await expect(climateDictionary).toHaveAttribute('open', '')
  await expect(climateDictionary).toContainText('cambio climático')
  await expect(climateDictionary).toContainText('Japanese · draft')

  await expect(page.locator('.method-equation')).toContainText('actor OR action OR party OR official source')
  await expect(page.locator('#collection')).toContainText('deterministic phrase matching, not an AI-model query')
  await expect(page.locator('#events')).toContainText('5,000 hectares')
  await expect(page.locator('#events')).toContainText('80,000 displaced people')
  await expect(page.getByRole('table', { name: 'Media scope definitions' })).toContainText('Affected countries')
  await expect(page.getByRole('table', { name: 'Media scope definitions' })).toContainText('Global')
  await expect(page.locator('.window-diagram')).toContainText('Event duration')
  await expect(page.locator('.window-diagram')).toContainText('Excluded')
  await expect(page.locator('.decision-table .status-chip.planned')).toHaveText('Planned')
  await expect(page.locator('#collection')).toContainText('Confirmed provider gap')
  await expect(page.locator('.reference-list > a')).toHaveCount(8)
  await expect(page.locator('.reference-list > a').first()).toHaveAttribute('href', /gdeltproject\.org/)
  await expect(page.locator('.reference-list > a').first()).toHaveAttribute('target', '_blank')

  await page.locator('.methods-toc a[href="#geography"]').click()
  await expect(page.locator('#geography')).toBeInViewport()
  expect(errors).toEqual([])
})

test('clearing and keyboard-editing date filters never unmounts the explorer', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const endDate = page.locator('input[type="date"]').nth(1)
  await endDate.click()
  await endDate.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A')
  await endDate.press('Backspace')
  if (await endDate.inputValue()) await endDate.fill('')

  await expect(endDate).toHaveValue('')
  await expect(page.locator('.app-shell')).toBeVisible()
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await expect(page.locator('.map-stat small')).toContainText('Open')

  await endDate.fill('2025-01-31')
  await expect(page.locator('.map-stat strong')).toHaveText('299')

  const startDate = page.locator('input[type="date"]').first()
  await startDate.fill('2025-02-01')
  await expect(page.locator('.map-stat strong')).toHaveText('0')
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await startDate.fill('2025-01-01')
  await expect(page.locator('.map-stat strong')).toHaveText('299')
  expect(errors).toEqual([])
})

test('hazard and alert filters update map and sidebar together', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const visibleCount = page.locator('.map-stat strong')
  await page.getByRole('button', { name: 'Fire', exact: true }).click()
  await expect(visibleCount).toHaveText('1,027')
  await expect(page.locator('.section-label small').first()).toHaveText('1,027 events')

  await page.getByRole('button', { name: 'Green', exact: true }).click()
  await expect(visibleCount).not.toHaveText('1,027')
  await expect(page.locator('.event-error')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('event selection survives an embedded preview that blocks URL history', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.evaluate(() => {
    window.history.replaceState = () => {
      throw new DOMException('History blocked by embedded preview', 'SecurityError')
    }
  })
  await page.locator('.watchlist > button').first().click()
  await expect(page.locator('.event-drawer')).toBeVisible()
  await expect(page.locator('.event-error')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('search supports empty results and recovers to the full event set', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const search = page.locator('.search-field input')
  await search.fill('no-such-climate-event-country')
  await expect(page.locator('.map-stat strong')).toHaveText('0')
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await expect(page.locator('.atlas-marker')).toHaveCount(0)

  await search.fill('italy')
  await expect(page.locator('.map-stat strong')).not.toHaveText('0')
  await expect(page.locator('.atlas-marker').first()).toBeVisible()

  await page.locator('.search-field button').click()
  await expect(page.locator('.map-stat strong')).toHaveText('8,942')
  expect(errors).toEqual([])
})
